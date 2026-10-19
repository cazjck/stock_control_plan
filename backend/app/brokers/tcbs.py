"""Adapter TCBS iFlash OpenAPI v1.0.0 (chỉ đọc).

Tài liệu: https://developers.tcbs.com.vn/docs/v1.0.0/introduction/
Xác thực: API key + iOTP (app TCInvest) -> JWT, hiệu lực tối đa 8 giờ.
"""
from __future__ import annotations

import base64
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..models import (
    Account, BoardQuote, BookLevel, Candle, CashBalance, Interval, Loan, MarginBucket, Position, Quote, SessionInfo,
)
from ..util import now_vn, parse_date, parse_dt, to_float, to_pct, VN_TZ
from .base import AuthRequired, BrokerAdapter, BrokerError, ReadOnlyHttp, parse_guard

TOKEN_PATH = "/gaia/v1/oauth2/openapi/token"
TOKEN_LIFETIME = timedelta(hours=7, minutes=50)  # dưới mức 8 giờ tối đa của TCBS


def _jwt_exp(token: str) -> datetime | None:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload)).get("exp")
        return datetime.fromtimestamp(float(exp), tz=timezone.utc).astimezone(VN_TZ) if exp else None
    except Exception:  # noqa: BLE001 - token không phải JWT chuẩn thì dùng hạn mặc định
        return None


class TcbsAdapter(BrokerAdapter):
    name = "tcbs"
    display_name = "TCBS iFlash"
    short_name = "TCBS"

    def __init__(self, *, api_key: str | None, custody_code: str | None, base_url: str, data_dir: Path):
        self._api_key = api_key
        self._custody = custody_code
        self._http = ReadOnlyHttp(base_url, auth_post_allowlist=frozenset({TOKEN_PATH}))
        self._token_file = data_dir / "tcbs_token.json"
        self._account_kind: dict[str, str] = {}
        self._token: str | None = None
        self._expires: datetime | None = None
        self._load_token()

    # ---------- phiên ----------

    def _load_token(self) -> None:
        try:
            d = json.loads(self._token_file.read_text())
            exp = parse_dt(d.get("expires_at"))
            if d.get("token") and exp and exp > now_vn():
                self._token, self._expires = d["token"], exp
        except (OSError, ValueError):
            pass

    def _save_token(self) -> None:
        payload = {"token": self._token, "expires_at": self._expires.isoformat() if self._expires else None}
        fd = os.open(self._token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f)

    def session_info(self) -> SessionInfo:
        configured = bool(self._api_key and self._custody)
        valid = bool(self._token and self._expires and self._expires > now_vn())
        msg = None
        if not configured:
            msg = "Thiếu TCBS_API_KEY hoặc TCBS_CUSTODY_CODE trong backend/.env"
        elif not valid:
            msg = "Cần nhập iOTP từ app TCInvest để lấy token (phiên sống khoảng 24 giờ)"
        return SessionInfo(
            broker=self.name, configured=configured, authenticated=valid,
            needs_otp=configured and not valid, expires_at=self._expires if valid else None,
            message=msg,
        )

    async def authenticate(self, otp: str | None) -> SessionInfo:
        if not (self._api_key and self._custody):
            raise BrokerError("Chưa cấu hình TCBS_API_KEY / TCBS_CUSTODY_CODE")
        if not otp:
            raise BrokerError("Cần iOTP")
        body = await self._http.auth_post(TOKEN_PATH, {"apiKey": self._api_key, "otp": otp.strip()})
        token = (body or {}).get("token")
        if not token:
            raise BrokerError("TCBS không trả về token, kiểm tra API key và iOTP")
        self._token = token
        self._expires = _jwt_exp(token) or (now_vn() + TOKEN_LIFETIME)
        self._save_token()
        return self.session_info()

    def stream_token(self) -> str | None:
        """Token cho luồng giá trực tiếp; None nếu chưa đăng nhập hoặc đã hết hạn."""
        return self._token if self._token and self._expires and self._expires > now_vn() else None

    def _auth(self) -> dict[str, str]:
        if not (self._token and self._expires and self._expires > now_vn()):
            raise AuthRequired("Chưa có token TCBS hợp lệ, cần nhập iOTP")
        return {"Authorization": f"Bearer {self._token}"}

    async def _get(self, path: str, params: dict | None = None, *, margin_only: bool = False):
        """margin_only: endpoint chỉ dành cho tiểu khoản margin. TCBS trả 403 với tiểu khoản thường;
        khi đó không phải phiên hết hạn, nên không xoá token."""
        try:
            return await self._http.get(path, params=params, headers=self._auth())
        except AuthRequired as e:
            if margin_only and e.status == 403:
                raise BrokerError(f"{path}: không áp dụng cho tiểu khoản không margin", 403) from e
            self._token = None
            raise

    # ---------- tài khoản ----------

    @parse_guard
    async def list_accounts(self) -> list[Account]:
        data = await self._get(f"/aion/v1/customers/{self._custody}/accounts")
        out: list[Account] = []
        for a in data or []:
            if str(a.get("accountStatus", "A")).upper() == "C":  # đã đóng
                continue
            t = str(a.get("accountType", "")).lower()
            kind = "margin" if "margin" in t else "normal" if t == "normal" else "other"
            self._account_kind[str(a["accountNo"])] = kind
            out.append(Account(
                broker=self.name, id=str(a["accountNo"]), name=f"Tiểu khoản {a['accountNo']} ({a.get('accountType', '')})",
                kind=kind, custody_code=a.get("custodyID"), margin_limit=a.get("marginLimit"),
            ))
        return out

    @parse_guard
    async def get_positions(self, account_id: str) -> list[Position]:
        """Phản hồi thật: {"stock": [{symbol, totalQtty, costPrice, currentPrice, ...}]}.
        Spec công bố {"assets": [{symbol, quantity, avgPrice, marketValue}]}; nhận cả hai."""
        data = await self._get(f"/aion/v1/accounts/{account_id}/se") or {}
        rows = data.get("stock") if data.get("stock") is not None else data.get("assets")
        out: list[Position] = []
        for a in rows or []:
            qty = int(to_float(a.get("totalQtty", a.get("quantity"))))
            if qty <= 0:
                continue
            price = to_float(a.get("currentPrice")) or None
            mv = to_float(a.get("marketValue")) or (qty * price if price else 0.0)
            if not price and mv:
                price = mv / qty
            out.append(Position(
                broker=self.name, account_id=account_id, symbol=str(a["symbol"]).upper(),
                quantity=qty, avg_cost=to_float(a.get("costPrice", a.get("avgPrice"))),
                price=price, market_value=mv,
            ))
        return out

    @parse_guard
    async def get_cash(self, account_id: str) -> CashBalance:
        data = await self._get(f"/aion/v1/accounts/{account_id}/cashInvestments")
        rows = [r for r in (data or {}).get("data", []) or [] if str(r.get("accountNo", account_id)) == account_id]
        row = rows[0] if rows else {}
        return CashBalance(account_id=account_id, cash=to_float(row.get("cashBalance")),
                           available_cash=to_float(row.get("pp0forBF"), None) if row.get("pp0forBF") is not None else None)

    @staticmethod
    def _risk_rows(data) -> list[dict]:
        """Phản hồi thật của /risk là MỘT đối tượng; spec nói là mảng. Nhận đối tượng, mảng, hoặc bọc trong data/content."""
        if isinstance(data, dict):
            for k in ("data", "content"):
                if isinstance(data.get(k), list):
                    return [r for r in data[k] if isinstance(r, dict)]
            return [data] if "rtt" in data or "riskPolicy" in data else []
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
        return []

    @parse_guard
    async def get_margin(self, account_id: str, positions: list[Position]) -> list[MarginBucket]:
        if self._account_kind.get(account_id) == "normal":
            return []  # tiểu khoản thường không có ký quỹ
        try:
            data = await self._get(f"/hydros/v1/account/{account_id}/risk", margin_only=True)
        except BrokerError as e:
            if isinstance(e, AuthRequired):
                raise
            if e.status in (400, 403, 404):  # tiểu khoản không phải margin
                return []
            raise
        rows = self._risk_rows(data)
        rows = [r for r in rows if str(r.get("accountNo", account_id)) == account_id] or rows
        if not rows:
            return []
        r = rows[0]
        pol = r.get("riskPolicy") or {}
        debt = to_float(r.get("outstanding")) + to_float(r.get("accruedInterest"))
        mv = sum(p.market_value for p in positions) or None
        return [MarginBucket(
            id=account_id, scope="account", label=f"Tài khoản {account_id}",
            symbols=[p.symbol for p in positions],
            ratio_kind="collateral_over_debt",   # RTT TCBS: duy trì 85, giải chấp 80, ban đầu 100
            ratio_pct=to_pct(r.get("rtt")),
            initial_pct=to_pct(pol.get("initialMargin")),
            maintenance_pct=to_pct(pol.get("maintenanceMargin")),
            liquidation_pct=to_pct(pol.get("liquidationMargin")),
            market_value=mv, debt=debt,
            status_text=(r.get("riskStatus") or {}).get("description"),
            raw={**r, "riskPolicy": pol},
        )]

    @parse_guard
    async def get_loans(self, account_id: str) -> list[Loan]:
        """Nguồn chính: /khaos/v1/loan/{acc} (đối chiếu với dữ liệu thật: tổng remainingPrincipal bằng dư nợ gốc
        của /risk, tổng interest bằng lãi dồn). Endpoint margin-info theo spec trả rỗng với tài khoản thật,
        chỉ dùng làm phương án dự phòng."""
        try:
            data = await self._get(f"/khaos/v1/loan/{account_id}", margin_only=True) or {}
        except BrokerError as e:
            if isinstance(e, AuthRequired):
                raise
            data = {}
        rows = data.get("content") if isinstance(data, dict) else data
        out: list[Loan] = []
        for r in rows or []:
            remaining = to_float(r.get("remainingPrincipal"))
            if remaining <= 0 or str(r.get("status", "OPEN")).upper() not in ("OPEN", "ACTIVE"):
                continue
            out.append(Loan(
                id=str(r.get("id", f"{account_id}-{len(out)}")), symbol=(r.get("symbol") or None),
                disbursement_date=parse_date(r.get("openingDate")), due_date=parse_date(r.get("dueDate")),
                principal=to_float(r.get("principal")), remaining_principal=remaining,
                accrued_interest=to_float(r.get("interest")), annual_rate_pct=to_pct(r.get("rate")),
            ))
        return out or await self._loans_from_margin_info(account_id)

    async def _loans_from_margin_info(self, account_id: str) -> list[Loan]:
        today = now_vn().date()
        params = {
            "acctno": account_id, "custodycd": self._custody,
            "fromdate": (today - timedelta(days=365)).isoformat(), "todate": today.isoformat(),  # spec ghi toDate, server đòi todate
            "page": "1", "size": "100",
        }
        try:
            data = await self._get("/erebos/v2/digital/margin-info", params, margin_only=True)
        except BrokerError as e:
            if isinstance(e, AuthRequired):
                raise
            return []
        body = (data or {}).get("response", data) or {}
        out: list[Loan] = []
        for i, r in enumerate(body.get("data", []) or []):
            remaining = to_float(r.get("printAmount"))
            if remaining <= 0:
                continue
            out.append(Loan(
                id=f"{account_id}-{r.get('releaseDate', i)}-{i}",
                disbursement_date=parse_date(r.get("releaseDate")), due_date=parse_date(r.get("overDueDate")),
                principal=to_float(r.get("releasedAmount")), remaining_principal=remaining,
                accrued_interest=to_float(r.get("remainingInterestFee", r.get("intAmount"))),
                annual_rate_pct=to_pct(r.get("rate2")),
            ))
        return out

    # ---------- thị trường ----------

    @parse_guard
    async def get_candles(self, symbol: str, interval: Interval, count: int,
                          *, is_index: bool = False) -> list[Candle]:
        kind = "index" if is_index else "stock"
        params = {"ticker": symbol, "type": kind, "to": int(time.time()), "countBack": count}
        if interval in (Interval.D1, Interval.W1):
            params["resolution"] = "D" if interval == Interval.D1 else "W"
            path = "/nyx/v2/stock/bars-long-term"
        else:
            params["resolution"] = "15" if interval == Interval.M15 else "60"
            path = "/nyx/v2/stock/bars"
        data = await self._get(path, params)
        out: list[Candle] = []
        for b in (data or {}).get("data", []) or []:
            t = parse_dt(b.get("tradingDate"))
            if t is None:
                continue
            out.append(Candle(t=t, open=to_float(b["open"]), high=to_float(b["high"]),
                              low=to_float(b["low"]), close=to_float(b["close"]),
                              volume=to_float(b.get("volume"))))
        out.sort(key=lambda c: c.t)
        return out[-count:]

    @parse_guard
    async def get_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        if not symbols:
            return {}
        data = await self._get("/tartarus/v1/tickerCommons", {"tickers": ",".join(symbols)})
        out: dict[str, Quote] = {}
        for r in (data or {}).get("data", []) or []:
            sym = str(r.get("symbol", "")).upper()
            match, ref = to_float(r.get("matchPrice")), to_float(r.get("refPrice"))
            out[sym] = Quote(symbol=sym, price=match or ref or None, ref_price=ref or None,
                             change_pct=r.get("changePercent"))
        return out

    @parse_guard
    async def get_board(self, symbols: list[str]) -> dict[str, BoardQuote]:
        if not symbols:
            return {}
        data = await self._get("/tartarus/v1/tickerCommons", {"tickers": ",".join(symbols)})
        out: dict[str, BoardQuote] = {}

        def num(r, k):
            v = r.get(k)
            try:
                return float(v) if v is not None and v != "" else None
            except (TypeError, ValueError):
                return None

        for r in (data or {}).get("data", []) or []:
            sym = str(r.get("symbol", "")).upper()
            book = lambda side: [BookLevel(price=num(r, f"{side}Price0{i}") or 0, qty=num(r, f"{side}Qtty0{i}") or 0)
                                 for i in (1, 2, 3) if num(r, f"{side}Price0{i}")]
            match, ref = num(r, "matchPrice"), num(r, "refPrice")
            out[sym] = BoardQuote(
                symbol=sym, ref=ref, ceil=num(r, "ceilPrice"), floor=num(r, "floorPrice"),
                price=match or None, change=num(r, "change"), change_pct=num(r, "changePercent"),
                match_qty=num(r, "matchQtty"), total_vol=num(r, "totalVol"), open=num(r, "open"),
                high=num(r, "high"), low=num(r, "low"), avg=num(r, "avg"), bid=book("bid"), offer=book("offer"),
                foreign_buy=num(r, "buyForeignQtty"), foreign_sell=num(r, "sellForeignQtty"), room=num(r, "room"))
        return out

    async def aclose(self) -> None:
        await self._http.aclose()

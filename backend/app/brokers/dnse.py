"""Adapter DNSE LightSpeed API (OpenAPI v2), chỉ đọc.

Tài liệu: https://developers.dnse.com.vn/  |  SDK: https://github.com/dnse-tech/openapi-sdk
Mọi REST request được ký HMAC-SHA256 (method + path + Date + nonce). Đọc dữ liệu không cần
trading token nên không cần OTP.

Margin của DNSE là isolated theo Deal (mã + gói vay), nên mỗi Deal có nợ là một MarginBucket.

Đối chiếu với API thật (19/10/2026):
- Giá cổ phiếu trong API dữ liệu thị trường (/price/...) tính theo NGHÌN đồng (HPG 20.85), chỉ số theo điểm.
  App dùng đồng, nên giá cổ phiếu được nhân 1.000; chỉ số giữ nguyên.
- /price/{mã}/trades/latest trả nhiều bảng: G1 lô chẵn, G4 lô lẻ, T1..T4 thoả thuận. Chỉ lấy G1.
- Dữ liệu thị trường chỉ cần khoá API, không cần OTP và không hết hạn, nên DNSE là nguồn giá dự phòng
  tốt cho Sổ tổng khi phiên TCBS hết hạn.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from uuid import uuid4

from ..models import (
    Account, BoardQuote, BookLevel, Candle, CashBalance, Interval, Loan, MarginBucket, Position, Quote, SessionInfo,
)
from ..util import now_vn, parse_date, to_float, to_pct, VN_TZ
from .base import BrokerAdapter, BrokerError, ReadOnlyHttp, parse_guard

MAIN_BOARD = "G1"


def to_vnd(x) -> float:
    """Giá cổ phiếu của DNSE theo nghìn đồng -> đồng. Giá đã theo đồng (≥ 1.000) thì giữ nguyên."""
    v = to_float(x)
    return v * 1000 if 0 < v < 1000 else v


_RESOLUTION = {Interval.M15: "15", Interval.H1: "1h", Interval.D1: "1D", Interval.W1: "1W"}
_SECONDS = {Interval.M15: 900, Interval.H1: 3600, Interval.D1: 86400, Interval.W1: 7 * 86400}


def build_signature(secret: str, method: str, path: str, date_value: str, nonce: str) -> str:
    """Chữ ký theo đúng SDK chính thức: base64 của HMAC-SHA256, chỉ mã hoá URL ba ký tự + / =."""
    to_sign = f"(request-target): {method.lower()} {path}\ndate: {date_value}\nnonce: {nonce}"
    mac = hmac.new(secret.encode(), to_sign.encode(), hashlib.sha256).digest()
    return quote(base64.b64encode(mac).decode(), safe="")


class DnseAdapter(BrokerAdapter):
    name = "dnse"
    display_name = "DNSE LightSpeed"
    short_name = "DNSE"

    def __init__(self, *, api_key: str | None, api_secret: str | None, base_url: str, api_version: str):
        self._key = api_key
        self._secret = api_secret
        self._version = api_version
        self._http = ReadOnlyHttp(base_url)  # không có allowlist POST: DNSE chỉ đọc bằng GET

    def session_info(self) -> SessionInfo:
        ok = bool(self._key and self._secret)
        return SessionInfo(
            broker=self.name, configured=ok, authenticated=ok, needs_otp=False,
            message=None if ok else "Thiếu DNSE_API_KEY hoặc DNSE_API_SECRET trong backend/.env",
        )

    def _signed_headers(self, path: str) -> dict[str, str]:
        if not (self._key and self._secret):
            raise BrokerError("Chưa cấu hình DNSE_API_KEY / DNSE_API_SECRET")
        date_value = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
        nonce = uuid4().hex
        sig = build_signature(self._secret, "GET", path, date_value, nonce)
        return {
            "Date": date_value,
            "x-api-key": self._key,
            "version": self._version,
            "X-Signature": (f'Signature keyId="{self._key}",algorithm="hmac-sha256",'
                            f'headers="(request-target) date",signature="{sig}",nonce="{nonce}"'),
        }

    async def _get(self, path: str, params: dict | None = None):
        return await self._http.get(path, params=params, headers=self._signed_headers(path))

    # ---------- tài khoản ----------

    @parse_guard
    async def list_accounts(self) -> list[Account]:
        data = await self._get("/accounts") or {}
        out = []
        for a in data.get("accounts", []) or []:
            out.append(Account(
                broker=self.name, id=str(a["id"]), name=data.get("name"),
                kind="margin" if a.get("dealAccount") else "normal",
                custody_code=data.get("custodyCode"),
            ))
        return out

    @parse_guard
    async def get_positions(self, account_id: str) -> list[Position]:
        data = await self._get(f"/accounts/{account_id}/positions",
                               {"marketType": "STOCK", "pageSize": "200"}) or {}
        out: list[Position] = []
        for p in data.get("positions", []) or []:
            qty = int(to_float(p.get("openQuantity")))
            if qty <= 0:
                continue
            price = to_vnd(p.get("marketPrice")) or None
            out.append(Position(
                broker=self.name, account_id=account_id, symbol=str(p["symbol"]).upper(),
                quantity=qty, avg_cost=to_vnd(p.get("costPrice")), price=price,
                market_value=qty * (price or 0.0), external_id=str(p.get("id")),
                loan_package_id=p.get("loanPackageId"),
            ))
        return out

    @parse_guard
    async def get_cash(self, account_id: str) -> CashBalance:
        data = await self._get(f"/accounts/{account_id}/balances") or {}
        s = data.get("stock") or {}
        return CashBalance(account_id=account_id, cash=to_float(s.get("totalCash")),
                           available_cash=to_float(s.get("availableCash")),
                           reported_debt=to_float(s.get("totalDebt")))

    async def _loans_raw(self, account_id: str) -> list[dict]:
        today = now_vn().date()
        data = await self._get(f"/accounts/{account_id}/loans", {
            "marketType": "STOCK", "pageSize": "200",
            "disbursementFrom": (today - timedelta(days=365)).isoformat(),
            "disbursementTo": today.isoformat(),
        }) or {}
        return [r for r in data.get("loans", []) or [] if to_float(r.get("remainPrincipal")) > 0]

    @parse_guard
    async def get_loans(self, account_id: str) -> list[Loan]:
        return [Loan(
            id=str(r.get("id")), symbol=r.get("symbol"),
            disbursement_date=parse_date(r.get("disbursementDate")), due_date=parse_date(r.get("dueDate")),
            principal=to_float(r.get("principal")), remaining_principal=to_float(r.get("remainPrincipal")),
            accrued_interest=to_float(r.get("remainInterest")), annual_rate_pct=to_pct(r.get("interestRate")),
        ) for r in await self._loans_raw(account_id)]

    @parse_guard
    async def get_margin(self, account_id: str, positions: list[Position]) -> list[MarginBucket]:
        loans = await self._loans_raw(account_id)
        debt_by_position: dict[str, float] = defaultdict(float)
        for r in loans:
            debt_by_position[str(r.get("positionId"))] += to_float(r.get("remainPrincipal")) + to_float(r.get("remainInterest"))

        # gộp theo Deal = (mã, gói vay)
        deals: dict[tuple[str, int | None], list[Position]] = defaultdict(list)
        for p in positions:
            deals[(p.symbol, p.loan_package_id)].append(p)

        pkg_cache: dict[str, dict[int, dict]] = {}
        buckets: list[MarginBucket] = []
        for (symbol, pkg_id), plist in deals.items():
            debt = sum(debt_by_position.get(p.external_id or "", 0.0) for p in plist)
            if debt <= 0:
                continue  # Deal tiền mặt, không có rủi ro margin
            if symbol not in pkg_cache:
                d = await self._get(f"/accounts/{account_id}/loan-packages",
                                    {"marketType": "STOCK", "symbol": symbol}) or {}
                pkg_cache[symbol] = {int(x["id"]): x for x in d.get("loanPackages", []) or []}
            pkg = pkg_cache[symbol].get(pkg_id or -1, {})
            mv = sum(p.market_value for p in plist)
            buckets.append(MarginBucket(
                id=f"{symbol}:{pkg_id}", scope="deal", label=f"{symbol} · {pkg.get('name', 'gói ' + str(pkg_id))}",
                symbols=[symbol],
                ratio_pct=((mv - debt) / mv * 100) if mv else None,
                initial_pct=to_pct(pkg.get("initialRate")),
                maintenance_pct=to_pct(pkg.get("maintenanceRate")),
                liquidation_pct=to_pct(pkg.get("liquidRate")),
                market_value=mv, debt=debt, raw={"package": pkg},
            ))
        return buckets

    # ---------- thị trường ----------

    @parse_guard
    async def get_candles(self, symbol: str, interval: Interval, count: int,
                          *, is_index: bool = False) -> list[Candle]:
        now = int(time.time())
        span = int(count * _SECONDS[interval] * (1.6 if interval in (Interval.D1, Interval.W1) else 4)) + 7 * 86400
        data = await self._get("/price/ohlc", {
            "symbol": symbol, "type": "INDEX" if is_index else "STOCK",
            "resolution": _RESOLUTION[interval], "from": now - span, "to": now,
        }) or {}
        ts, o, h, l, c, v = (data.get(k) or [] for k in ("t", "o", "h", "l", "c", "v"))
        k = 1.0 if is_index else 1000.0          # cổ phiếu theo nghìn đồng, chỉ số theo điểm
        out = [Candle(t=datetime.fromtimestamp(t, tz=timezone.utc).astimezone(VN_TZ),
                      open=to_float(o[i]) * k, high=to_float(h[i]) * k, low=to_float(l[i]) * k,
                      close=to_float(c[i]) * k, volume=to_float(v[i] if i < len(v) else 0))
               for i, t in enumerate(ts)]
        out.sort(key=lambda x: x.t)
        return out[-count:]

    @parse_guard
    async def get_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        out: dict[str, Quote] = {}
        for s in symbols:
            try:
                d = await self._get(f"/price/{s}/trades/latest") or {}
            except BrokerError:
                continue
            trades = d.get("trades") or []
            main = [t for t in trades if t.get("boardId") == MAIN_BOARD] or trades   # lô chẵn, bỏ lô lẻ và thoả thuận
            if main:
                latest = max(main, key=lambda t: str(t.get("time") or ""))
                out[s] = Quote(symbol=s, price=to_vnd(latest.get("matchPrice")) or None)
        return out

    async def _board_one(self, s: str) -> BoardQuote | None:
        """Bảng giá một mã từ ba API của bảng lô chẵn G1: thông tin mã (tham chiếu, trần, sàn),
        sổ lệnh (ba bước giá) và khớp lệnh mới nhất (giá, cao, thấp, khối lượng)."""
        p = {"boardId": MAIN_BOARD}
        sd, qt, tr = await asyncio.gather(self._get(f"/price/{s}/secdef", p), self._get(f"/price/{s}/quotes/latest", p),
                                          self._get(f"/price/{s}/trades/latest", p), return_exceptions=True)
        sd = next((x for x in sd if x.get("boardId") == MAIN_BOARD), sd[0] if sd else {}) if isinstance(sd, list) else {}
        quotes = (qt or {}).get("quotes") if isinstance(qt, dict) else None
        book = next((x for x in quotes or [] if x.get("boardId") == MAIN_BOARD), (quotes or [{}])[0])
        trades = (tr or {}).get("trades") if isinstance(tr, dict) else None
        main = [x for x in trades or [] if x.get("boardId") == MAIN_BOARD] or (trades or [])
        last = max(main, key=lambda x: str(x.get("time") or "")) if main else {}
        if not (sd or book or last):
            return None
        ref = to_vnd(sd.get("basicPrice")) or None
        price = to_vnd(last.get("matchPrice")) or None
        lv = lambda rows: [BookLevel(price=to_vnd(x.get("price")), qty=to_float(x.get("quantity")))   # noqa: E731
                           for x in (rows or [])[:3] if to_float(x.get("price")) > 0]
        return BoardQuote(
            symbol=s, ref=ref, ceil=to_vnd(sd.get("ceilingPrice")) or None, floor=to_vnd(sd.get("floorPrice")) or None,
            price=price, change=(price - ref) if price and ref else None,
            change_pct=((price / ref - 1) * 100) if price and ref else None,
            match_qty=to_float(last.get("matchQtty")) or None, total_vol=to_float(last.get("totalVolumeTraded")) or None,
            open=to_vnd(last.get("openPrice")) or None, high=to_vnd(last.get("highestPrice")) or None,
            low=to_vnd(last.get("lowestPrice")) or None, avg=to_vnd(last.get("avgPrice")) or None,
            bid=lv(book.get("bid")), offer=lv(book.get("offer")))

    @parse_guard
    async def get_board(self, symbols: list[str]) -> dict[str, BoardQuote]:
        sem = asyncio.Semaphore(4)

        async def one(s: str):
            async with sem:
                try:
                    return s, await self._board_one(s)
                except BrokerError:
                    return s, None
        return {s: q for s, q in await asyncio.gather(*(one(s) for s in symbols)) if q is not None}

    async def aclose(self) -> None:
        await self._http.aclose()

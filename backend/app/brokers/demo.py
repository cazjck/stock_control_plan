"""Adapter demo: dữ liệu mẫu cố định, dùng để phát triển và trình diễn không cần token.

Nến được sinh bằng bước đi ngẫu nhiên có hạt giống cố định theo kịch bản, và được co giãn để
giá đóng cửa cuối cùng đúng bằng giá trong fixture."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from ..models import (
    Account, BoardQuote, BookLevel, Candle, CashBalance, Interval, Loan, MarginBucket, Position, Quote, SessionInfo,
)
from ..util import VN_TZ, now_vn
from .base import BrokerAdapter

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "demo" / "portfolio.json"

# (số phiên, drift mỗi phiên, độ biến động mỗi phiên)
SCENARIOS: dict[str, list[tuple[int, float, float]]] = {
    "uptrend": [(220, 0.0011, 0.012), (100, 0.0016, 0.010)],
    "downtrend": [(230, 0.0006, 0.014), (90, -0.0045, 0.012)],
    "soft_decline": [(260, 0.0003, 0.014), (60, -0.0014, 0.013)],
    "sideways": [(200, 0.0004, 0.013), (120, 0.0001, 0.011)],
    "index_pullback": [(270, 0.0007, 0.007), (50, -0.0014, 0.007)],
}
TOTAL = 320


def _last_weekdays(n: int) -> list[datetime]:
    d = now_vn().replace(hour=0, minute=0, second=0, microsecond=0)
    out: list[datetime] = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return list(reversed(out))


def generate_candles(scenario: str, target_close: float, seed: int, n: int = TOTAL) -> list[Candle]:
    rng = np.random.default_rng(seed)
    rets: list[float] = []
    for days, drift, vol in SCENARIOS[scenario]:
        rets.extend(rng.normal(drift, vol, days))
    rets = rets[-n:]
    closes = np.exp(np.cumsum(rets))
    closes = closes * (target_close / closes[-1])
    opens = np.concatenate([[closes[0]], closes[:-1]]) * (1 + rng.normal(0, 0.003, len(closes)))
    spread = np.abs(rng.normal(0, 0.006, len(closes)))
    highs = np.maximum(opens, closes) * (1 + spread)
    lows = np.minimum(opens, closes) * (1 - spread)
    base_vol = 1_500_000 if target_close < 200_000 else 600_000
    vols = base_vol * (1 + rng.normal(0, 0.3, len(closes))) * (1 + 0.8 * (np.array(rets) < -0.02))
    vols = np.abs(vols)
    days = _last_weekdays(len(closes))
    return [Candle(t=d, open=float(o), high=float(h), low=float(l), close=float(c), volume=float(v))
            for d, o, h, l, c, v in zip(days, opens, highs, lows, closes, vols)]


class DemoAdapter(BrokerAdapter):
    name = "demo"
    display_name = "Demo (dữ liệu mẫu)"
    short_name = "Demo"

    def __init__(self) -> None:
        self._d = json.loads(FIXTURE.read_text())
        self._cache: dict[str, list[Candle]] = {}

    def session_info(self) -> SessionInfo:
        return SessionInfo(broker=self.name, configured=True, authenticated=True, needs_otp=False,
                           message="Dữ liệu mẫu, không phải tài khoản thật")

    async def list_accounts(self) -> list[Account]:
        a = self._d["account"]
        return [Account(broker=self.name, id=a["id"], name=a["name"], kind=a["kind"])]

    async def get_positions(self, account_id: str) -> list[Position]:
        return [Position(broker=self.name, account_id=account_id, symbol=p["symbol"], quantity=p["quantity"],
                         avg_cost=p["avg_cost"], price=p["price"], market_value=p["quantity"] * p["price"])
                for p in self._d["positions"]]

    async def get_cash(self, account_id: str) -> CashBalance:
        return CashBalance(account_id=account_id, cash=self._d["cash"], available_cash=self._d["cash"])

    async def get_margin(self, account_id: str, positions: list[Position]) -> list[MarginBucket]:
        m = self._d["margin"]
        mv = sum(p.market_value for p in positions)
        debt = m["principal"] + m["accrued_interest"]
        return [MarginBucket(
            id=account_id, scope="account", label=f"Tài khoản {account_id}", symbols=[p.symbol for p in positions],
            ratio_pct=(mv - debt) / mv * 100 if mv else None, initial_pct=m["initial_pct"],
            maintenance_pct=m["maintenance_pct"], liquidation_pct=m["liquidation_pct"],
            market_value=mv, debt=debt, status_text="Dữ liệu mẫu")]

    async def get_loans(self, account_id: str) -> list[Loan]:
        today = now_vn().date()
        return [Loan(id=f"demo-{i}", disbursement_date=today - timedelta(days=l["opened_days_ago"]),
                     due_date=today + timedelta(days=l["due_in_days"]), principal=l["principal"],
                     remaining_principal=l["remaining"], accrued_interest=l["interest"],
                     annual_rate_pct=l["rate_pct"]) for i, l in enumerate(self._d["loans"])]

    async def get_candles(self, symbol: str, interval: Interval, count: int,
                          *, is_index: bool = False) -> list[Candle]:
        if is_index:
            spec = self._d["index"]
            key, scen, price, seed = spec["symbol"], spec["scenario"], spec["price"], spec["seed"]
        else:
            spec = next((p for p in self._d["positions"] if p["symbol"] == symbol), None)
            if spec is None:
                return []
            key, scen, price, seed = symbol, spec["scenario"], spec["price"], spec["seed"]
        if key not in self._cache:
            self._cache[key] = generate_candles(scen, price, seed)
        daily = self._cache[key]
        if interval == Interval.W1:
            weeks: dict[tuple[int, int], list[Candle]] = {}
            for c in daily:
                weeks.setdefault(c.t.isocalendar()[:2], []).append(c)
            daily = [Candle(t=w[-1].t, open=w[0].open, high=max(x.high for x in w), low=min(x.low for x in w),
                            close=w[-1].close, volume=sum(x.volume for x in w)) for w in weeks.values()]
        return daily[-count:]

    async def get_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        by = {p["symbol"]: p["price"] for p in self._d["positions"]}
        return {s: Quote(symbol=s, price=by[s]) for s in symbols if s in by}


def _tick(p: float) -> float:
    return 10.0 if p < 10_000 else 50.0 if p < 50_000 else 100.0


async def _demo_board(self, symbols: list[str]) -> dict[str, BoardQuote]:
    out: dict[str, BoardQuote] = {}
    for sym in symbols:
        cs = await self.get_candles(sym, Interval.D1, 3)
        if len(cs) < 2:
            continue
        ref, last = cs[-2].close, cs[-1]
        t = _tick(ref)
        rnd = lambda x: round(x / t) * t
        price = rnd(last.close)
        out[sym] = BoardQuote(
            symbol=sym, ref=rnd(ref), ceil=rnd(ref * 1.07 - t / 2), floor=rnd(ref * 0.93 + t / 2), price=price,
            change=price - rnd(ref), change_pct=(price / rnd(ref) - 1) * 100, match_qty=1000, total_vol=last.volume,
            open=rnd(last.open), high=rnd(last.high), low=rnd(last.low),
            bid=[BookLevel(price=price - t * i, qty=5000 * i) for i in (1, 2, 3)],
            offer=[BookLevel(price=price + t * i, qty=4000 * i) for i in (1, 2, 3)],
            foreign_buy=12_000, foreign_sell=8_500)
    return out


DemoAdapter.get_board = _demo_board  # type: ignore[method-assign]

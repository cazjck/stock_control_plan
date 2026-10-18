"""Điều phối: lấy dữ liệu từ adapter, đánh giá rủi ro, lưu cảnh báo, tạo kết quả cho API."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from ..brokers.base import AuthRequired, BrokerAdapter, BrokerError
from ..config import Settings
from ..models import (
    Account, AlertRecord, AlertSeverity, AssetOverview, Candle, CashBalance, Interval, MarginOverview,
    BoardIndex, BoardQuote, BoardResponse, BoardRow,
    MarketInfo, OverviewResponse, Position, PositionEval, PositionPlan, PositionStatus, SourceShare, ScenarioRequest,
    ScenarioResult, SizingPlan,
)
from ..risk.alerts import build_candidates
from ..risk.engine import evaluate_position, market_state
from ..risk.indicators import compute_series, last_indicators, to_frame
from ..risk.margin import asset_overview, margin_overview
from ..risk.rules import Rules
from ..risk.scenario import run_scenario
from ..risk.sizing import size_position
from ..storage.db import Store
from ..util import align_price_scale, now_vn
from ..risk.deleverage import loans_for_bucket
from ..risk.hold import evaluate_hold
from ..risk.margin import loan_interest_per_day, trigger_price
from ..risk.rotation import build_rotation, current_cycle
from ..risk.technical import MarginCtx, build_tech_plan, follow_through
from ..storage.holds import HoldRepo
from ..storage.rotation import RotationRepo
from .lots import LotService
from .rules_service import RulesService


class NotFound(Exception):
    pass


def merge_by_symbol(positions: list[Position]) -> list[Position]:
    """Gộp các dòng cùng mã (sổ tổng tách theo nguồn) thành một dòng: dùng cho bảng giá, kịch bản giả định, khối lượng."""
    out: dict[str, Position] = {}
    for p in positions:
        m = out.get(p.symbol)
        if m is None:
            out[p.symbol] = p.model_copy(update={"sources": list(p.sources), "row_id": p.symbol})
            continue
        q = m.quantity + p.quantity
        out[p.symbol] = m.model_copy(update={
            "quantity": q, "avg_cost": (m.quantity * m.avg_cost + p.quantity * p.avg_cost) / q if q else m.avg_cost,
            "market_value": m.market_value + p.market_value, "price": p.price or m.price,
            "sources": m.sources + p.sources})
    return list(out.values())


@dataclass
class Context:
    broker: str
    account: Account
    fetched_at: float
    as_of: datetime
    rules: Rules
    positions: list[Position]
    cash: CashBalance
    market: MarketInfo
    evals: list[PositionEval]
    assets: AssetOverview
    margin: MarginOverview
    frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


class TTLCache:
    def __init__(self) -> None:
        self._d: dict[Any, tuple[float, Any]] = {}

    def get(self, key: Any, ttl: float) -> Any | None:
        hit = self._d.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
        return None

    def set(self, key: Any, value: Any) -> None:
        self._d[key] = (time.monotonic(), value)

    def clear(self, prefix: Any = None) -> None:
        if prefix is None:
            self._d.clear()
        else:
            for k in [k for k in self._d if k[0] == prefix]:
                del self._d[k]


def _normalize_cost_scale(positions: list[Position]) -> list[str]:
    """Nếu giá vốn và giá thị trường lệch nhau ~1000 lần (nghìn đồng so với đồng) thì đưa về cùng thang."""
    notes = []
    for p in positions:
        if p.price and p.avg_cost > 0:
            ratio = p.price / p.avg_cost
            if 800 <= ratio <= 1250:
                p.avg_cost *= 1000
                notes.append(f"{p.symbol}: giá vốn đã nhân 1000 để cùng thang với giá thị trường")
            elif 1 / 1250 <= ratio <= 1 / 800:
                p.avg_cost /= 1000
                notes.append(f"{p.symbol}: giá vốn đã chia 1000 để cùng thang với giá thị trường")
    return notes


def _is_intraday(last_candle_dt: datetime | None) -> bool:
    n = now_vn()
    if last_candle_dt is None or n.weekday() >= 5:
        return False
    return last_candle_dt.date() == n.date() and 9 <= n.hour < 15


class PortfolioService:
    def __init__(self, settings: Settings, adapters: dict[str, BrokerAdapter], store: Store, rules: RulesService,
                 lots: "LotService | None" = None, rotations: "RotationRepo | None" = None,
                 holds: "HoldRepo | None" = None):
        self.lots = lots
        self.holds = holds
        self.rotations = rotations
        self.s = settings
        self.adapters = adapters
        self.store = store
        self.rules = rules
        self._ctx_cache = TTLCache()
        self._candle_cache = TTLCache()
        self._sem = asyncio.Semaphore(4)  # TCBS không công bố rate limit, giữ số request song song thấp
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    def adapter(self, broker: str) -> BrokerAdapter:
        a = self.adapters.get(broker)
        if not a:
            raise NotFound(f"Broker '{broker}' chưa được bật (BROKERS trong backend/.env)")
        return a

    async def accounts(self, broker: str) -> list[Account]:
        return await self.adapter(broker).list_accounts()

    async def resolve_account(self, broker: str, account_id: str | None) -> Account:
        accs = await self.accounts(broker)
        if not accs:
            raise NotFound("Broker không trả về tiểu khoản nào")
        if account_id:
            acc = next((a for a in accs if a.id == account_id), None)
            if not acc:
                raise NotFound(f"Không có tiểu khoản {account_id}")
            return acc
        return next((a for a in accs if a.kind == "margin"), accs[0])

    # ---------- nến ----------

    async def candles(self, broker: str, symbol: str, interval: Interval, count: int, *,
                      is_index: bool = False) -> list[Candle]:
        key = (broker, symbol, interval.value, count, is_index)
        hit = self._candle_cache.get(key, self.s.candle_ttl_seconds if interval in (Interval.D1, Interval.W1) else 120)
        if hit is not None:
            return hit
        async with self._sem:
            data = await self.adapter(broker).get_candles(symbol, interval, count, is_index=is_index)
        self._candle_cache.set(key, data)
        return data

    # ---------- ngữ cảnh đầy đủ ----------

    async def context(self, broker: str, account_id: str | None, *, force: bool = False) -> Context:
        acc = await self.resolve_account(broker, account_id)
        key = (broker, acc.id)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            if not force:
                hit = self._ctx_cache.get(key, self.s.account_ttl_seconds)
                if hit is not None:
                    return hit
            ctx = await self._build(broker, acc)
            self._ctx_cache.set(key, ctx)
            return ctx

    async def _build(self, broker: str, acc: Account) -> Context:
        ad = self.adapter(broker)
        rules = self.rules.get()
        notes: list[str] = []

        positions, cash = await asyncio.gather(ad.get_positions(acc.id), ad.get_cash(acc.id))
        try:
            quotes = await ad.get_quotes([p.symbol for p in positions])
        except AuthRequired:
            raise
        except BrokerError as e:
            quotes = {}
            notes.append(f"Không lấy được giá realtime: {e.message}")
        for p in positions:
            q = quotes.get(p.symbol)
            if q and q.price:
                p.price = q.price
                p.market_value = q.price * p.quantity
            elif not p.price and p.quantity:
                p.price = p.market_value / p.quantity if p.market_value else None
        fresh = [p for p in positions if quotes.get(p.symbol) and quotes[p.symbol].price]
        if fresh and hasattr(ad, "remember_prices"):
            ad.remember_prices(fresh)       # Sổ tổng: lưu giá gần nhất để dùng khi mất phiên broker
        notes.extend(_normalize_cost_scale(positions))
        src = ad.short_name or ad.display_name
        for p in positions:
            if not p.sources:
                p.sources = [SourceShare(source=src, account=acc.id, quantity=p.quantity, avg_cost=p.avg_cost)]
        if self.lots is not None and broker != "ledger":
            notes.extend(self.lots.observe(broker, acc.id, positions, now_vn().date()))

        # nến ngày cho mọi mã và chỉ số thị trường
        mf = rules.entry.market_filter

        async def fetch(symbol: str, idx: bool = False) -> list[Candle]:
            try:
                return await self.candles(broker, symbol, Interval.D1, 320 if idx else 300, is_index=idx)
            except AuthRequired:
                raise
            except BrokerError as e:
                notes.append(f"{symbol}: không lấy được nến ({e.message})")
                return []

        results = await asyncio.gather(*[fetch(p.symbol) for p in positions], fetch(mf.index, True))
        candle_map = {p.symbol: results[i] for i, p in enumerate(positions)}
        index_candles = results[-1]

        frames: dict[str, pd.DataFrame] = {}
        for p in positions:
            cs = align_price_scale(candle_map[p.symbol], p.price)
            candle_map[p.symbol] = cs
            frames[p.symbol] = to_frame(cs) if cs else pd.DataFrame()
        index_df = to_frame(index_candles) if index_candles else None
        market = market_state(index_df, rules)
        ftd = follow_through(index_df, rules)

        # margin và nợ
        try:
            buckets, loans = await asyncio.gather(ad.get_margin(acc.id, positions), ad.get_loans(acc.id))
        except BrokerError as e:
            if isinstance(e, AuthRequired):
                raise
            buckets, loans = [], []
            notes.append(f"Không lấy được dữ liệu margin/nợ: {e.message}")
        for b in buckets:
            b.source = b.source or src
        for l in loans:
            l.source = l.source or src
        today = now_vn().date()
        margin = margin_overview(buckets, loans, rules, today)
        assets = asset_overview(positions, cash.cash, margin.total_debt or (cash.reported_debt or 0.0),
                                margin.interest_per_day)
        if assets.positions_value > 0 and margin.interest_30d:
            margin.breakeven_monthly_pct = margin.interest_30d / assets.positions_value * 100
        if assets.nav > 0 and margin.interest_30d:
            margin.interest_pct_nav_monthly = margin.interest_30d / assets.nav * 100

        # đánh giá từng vị thế: mỗi dòng (nguồn, mã) một đánh giá riêng
        plan_cache: dict[str, dict[str, PositionPlan]] = {}

        def plan_for(p: Position) -> PositionPlan | None:
            for acc_key in dict.fromkeys([p.account_id, acc.id]):   # kế hoạch theo nguồn, rồi kế hoạch chung
                if acc_key not in plan_cache:
                    plan_cache[acc_key] = self.store.get_plans(broker, acc_key)
                if p.symbol in plan_cache[acc_key]:
                    return plan_cache[acc_key][p.symbol]
            return None

        total_value = assets.positions_value
        evals: list[PositionEval] = []
        for p in positions:
            df = frames.get(p.symbol)
            has_df = df is not None and len(df)
            last_dt = df["t"].iloc[-1] if has_df else None
            e = evaluate_position(p, df if has_df else None, plan_for(p), rules, market, total_value,
                                  intraday=_is_intraday(last_dt), today=today)
            e.row_id, e.account_id, e.sources = p.row_id or p.symbol, p.account_id, p.sources
            e.source = p.sources[0].source if len(p.sources) == 1 else None
            if self.lots is not None:
                e.lots, e.unknown_lot = self.lots.evaluate(broker, acc.id, p, df if has_df else None, rules, today, src)
                due = [l for l in e.lots if l.rule_status in ("stop", "time")]
                for l in reversed(due):
                    e.actions.insert(0, l.action or "")
                if due:
                    e.flags.append("lot_rule")
                    e.urgency += 15
            if self.rotations is not None and has_df and e.data_ok:
                self._apply_rotation(e, p, df, broker, acc.id, margin, market, rules, today, ftd)
            self._apply_margin_prices(e, p, acc.id, margin)
            if self.holds is not None:
                self._apply_hold(e, p, df if has_df else None, broker, acc.id, margin, today)
            evals.append(e)
        evals.sort(key=lambda e: e.urgency, reverse=True)

        # cảnh báo
        cands = build_candidates(evals, assets, margin, rules, today)
        self.store.sync_alerts(broker, acc.id, cands)

        return Context(broker=broker, account=acc, fetched_at=time.monotonic(), as_of=now_vn(), rules=rules,
                       positions=positions, cash=cash, market=market, evals=evals, assets=assets,
                       margin=margin, frames=frames, notes=notes)

    @staticmethod
    def _apply_margin_prices(e: PositionEval, p: Position, acc_id: str, margin: MarginOverview) -> None:
        """Giá gọi ký quỹ và giá xử lý của riêng mã này trong tài khoản của dòng."""
        m = next((x for x in margin.buckets if x.bucket.id in (p.account_id or acc_id, acc_id)), None)
        if m is None or not m.bucket.debt or not m.bucket.market_value or m.bucket.ratio_pct is None:
            return
        b = m.bucket
        e.margin_call_price = trigger_price(b.ratio_kind, b.ratio_pct, b.market_value, b.debt, e.market_value,
                                            e.quantity, b.maintenance_pct)
        e.liquidation_price = trigger_price(b.ratio_kind, b.ratio_pct, b.market_value, b.debt, e.market_value,
                                            e.quantity, b.liquidation_pct)
        if e.margin_call_price and e.price:
            e.margin_call_distance_pct = (e.margin_call_price / e.price - 1) * 100

    def _apply_hold(self, e: PositionEval, p: Position, df: pd.DataFrame | None, broker: str, acc_id: str,
                    margin: MarginOverview, today) -> None:
        """Mục 6c: dòng đang gồng theo quyết định của người dùng."""
        d = self.holds.get(broker, p.account_id or acc_id, p.symbol)
        if d is None:
            return
        m = next((x for x in margin.buckets if x.bucket.id in (p.account_id or acc_id, acc_id)), None)
        per_day = 0.0
        if m is not None and m.bucket.market_value:
            loans = loans_for_bucket(m.bucket.source, len(margin.buckets), margin.loans)
            per_day = loan_interest_per_day(loans) * e.market_value / m.bucket.market_value
        close = float(df["close"].iloc[-1]) if df is not None and len(df) else e.price
        e.hold = evaluate_hold(d, close=close, ratio_pct=m.bucket.ratio_pct if m else None,
                               maintenance_pct=m.bucket.maintenance_pct if m else None, rotation=e.rotation,
                               interest_per_day=per_day, today=today)
        if e.hold.state in ("exit_price", "exit_margin", "review"):
            e.actions.insert(0, e.hold.text)
            e.urgency += 30
            e.flags.append(f"hold_{e.hold.state}")
        elif e.hold.state == "restructure":
            e.actions.insert(0, e.hold.text)
            e.flags.append("hold_restructure")
        else:
            e.actions.append(e.hold.text)
            e.flags.append("holding")

    def _apply_rotation(self, e: PositionEval, p: Position, df: pd.DataFrame, broker: str, acc_id: str,
                        margin: MarginOverview, market: MarketInfo, rules: Rules, today, ftd=None) -> None:
        """Mục 6d rồi 6b: kế hoạch kỹ thuật cho dòng, sau đó khuyến nghị đảo hàng dùng vùng cản của kế hoạch đó.
        Nhật ký đảo hàng theo (broker, tiểu khoản của dòng, mã)."""
        row_acc = p.account_id or acc_id
        m = next((x for x in margin.buckets if x.bucket.id in (row_acc, acc_id)), None)
        if m is None or not (m.bucket.debt or 0) > 0:
            margin_ok: bool | None = True
        elif m.zone == "safe":
            margin_ok = True
        elif m.zone == "unknown":
            margin_ok = None
        else:
            margin_ok = False
        s = compute_series(df, rules.stop_loss.atr_period, rules.take_profit.trailing.atr_period)
        mctx = None
        if m is not None and m.bucket.ratio_pct is not None and m.safe_target_pct is not None and m.bucket.market_value:
            mctx = MarginCtx(kind=m.bucket.ratio_kind, ratio_pct=m.bucket.ratio_pct, value=m.bucket.market_value,
                             debt=m.bucket.debt or 0.0, target=m.safe_target_pct, safe=m.zone == "safe")
        holds = getattr(self, "holds", None)
        hold = holds.get(broker, row_acc, p.symbol) if holds is not None else None
        trades = self.rotations.trades(broker, row_acc, p.symbol)
        open_sold = 0
        try:
            cyc, _ = current_cycle(trades, s, rules, today)
            open_sold = cyc.open_qty if cyc else 0
        except Exception:  # noqa: BLE001 - nhật ký hỏng không được chặn đánh giá
            pass
        e.technical = build_tech_plan(s, e.price, e.quantity + open_sold, e.avg_cost, rules, ftd=ftd, margin=mctx,
                                      review_on=hold.review_on if hold else None) if e.mode != "dca" else None
        zones = [(z.low, z.sell_qty) for z in e.technical.sell_zones] if e.technical and e.technical.sell_zones else None
        rot = build_rotation(s=s, price=e.price, qty=e.quantity, cost=e.avg_cost, mode=e.mode,
                             thesis=e.plan.has_thesis if e.plan else None, market=market, margin_ok=margin_ok,
                             trades=trades, rules=rules, today=today, zones=zones,
                             stage=e.technical.stage if e.technical else None)
        e.rotation = rot
        if rot is None:
            return
        due = [l for l in e.lots if l.rule_status in ("stop", "time")]
        if due:
            n = sum(l.remaining for l in due)
            qty_txt = f"{n:,}".replace(",", ".")
            rot.text = (f"Trước hết bán {qty_txt} cổ phiếu của các lô mua thêm đã tới luật bán (mục 3.5), không chờ nhịp hồi. "
                        f"Với phần còn lại: {rot.text[0].lower()}{rot.text[1:]}")
        if rot.level in ("sell", "rebuy"):
            e.actions.insert(len(due), rot.text)
            e.flags.append(f"rotation_{rot.level}")
            e.urgency += 10 if rot.level == "sell" else 5
        elif rot.level in ("watch", "blocked") and rot.open_qty:
            e.actions.append(rot.text)

    def invalidate(self, broker: str | None = None) -> None:
        self._ctx_cache.clear(broker)  # type: ignore[arg-type]

    # ---------- đầu ra cho API ----------

    async def overview(self, broker: str, account_id: str | None, *, force: bool = False) -> OverviewResponse:
        ctx = await self.context(broker, account_id, force=force)
        alerts = self.store.list_alerts(broker, ctx.account.id, "active")
        counts: dict[str, int] = {s.value: 0 for s in PositionStatus}
        for e in ctx.evals:
            counts[e.status.value] += 1
        counts.update({f"alerts_{sev.value}": sum(1 for a in alerts if a.severity == sev) for sev in AlertSeverity})
        return OverviewResponse(
            broker=broker, account_id=ctx.account.id, as_of=ctx.as_of, session=self.adapter(broker).session_info(),
            market=ctx.market, assets=ctx.assets, margin=ctx.margin, top_alerts=alerts[:3], counts=counts,
            data_age_seconds=int(time.monotonic() - ctx.fetched_at))

    async def positions(self, broker: str, account_id: str | None) -> tuple[list[PositionEval], list[str]]:
        ctx = await self.context(broker, account_id)
        return ctx.evals, ctx.notes

    async def chart(self, broker: str, account_id: str | None, symbol: str, interval: Interval, count: int,
                    row: str | None = None) -> dict[str, Any]:
        symbol = symbol.upper()
        ctx = await self.context(broker, account_id)
        rows = [e for e in ctx.evals if e.symbol == symbol]
        ev = next((e for e in rows if e.row_id == row), None) or (rows[0] if rows else None)
        if interval == Interval.D1 and symbol in ctx.frames and len(ctx.frames[symbol]):
            df = ctx.frames[symbol]
        else:
            pos = next((p for p in ctx.positions if p.symbol == symbol), None)
            cs = await self.candles(broker, symbol, interval, max(count, 120))
            cs = align_price_scale(cs, pos.price if pos else None)
            df = to_frame(cs)
        if df.empty:
            raise NotFound(f"Không có dữ liệu nến cho {symbol}")
        s = compute_series(df, ctx.rules.stop_loss.atr_period, ctx.rules.take_profit.trailing.atr_period).tail(count)
        daily = interval in (Interval.D1, Interval.W1)

        def tfmt(row) -> Any:
            return row["t"].strftime("%Y-%m-%d") if daily else int(row["t"].timestamp())

        def series(col: str) -> list[dict[str, Any]]:
            return [{"time": tfmt(r), "value": float(r[col])} for _, r in s.iterrows() if pd.notna(r[col])]

        return {
            "symbol": symbol, "interval": interval.value,
            "candles": [{"time": tfmt(r), "open": r["open"], "high": r["high"], "low": r["low"],
                         "close": r["close"], "volume": r["volume"]} for _, r in s.iterrows()],
            "sma20": series("sma20"), "sma50": series("sma50"), "ema20": series("ema20"),
            "rsi14": series("rsi14"), "macd": series("macd"), "macd_signal": series("macd_signal"),
            "macd_hist": series("macd_hist"), "atr14": series("atr14"),
            "avg_cost": ev.avg_cost if ev else None, "stop_level": ev.stop_level if ev else None,
            "stop_basis": ev.stop_basis if ev else None, "evaluation": ev.model_dump(mode="json") if ev else None,
            "evaluations": [e.model_dump(mode="json") for e in sorted(rows, key=lambda e: -e.quantity)],
        }

    # ---------- kịch bản và khối lượng (chỉ tính toán) ----------

    async def scenario(self, broker: str, account_id: str | None, req: ScenarioRequest) -> ScenarioResult:
        ctx = await self.context(broker, account_id)
        return run_scenario(req, merge_by_symbol(ctx.positions), ctx.cash.cash, ctx.assets.debt, [m.bucket for m in ctx.margin.buckets],
                            ctx.margin.loans, ctx.rules)

    async def sizing(self, broker: str, account_id: str | None, symbol: str, price: float,
                     stop: float | None = None) -> SizingPlan:
        symbol = symbol.upper()
        ctx = await self.context(broker, account_id)
        rows = [e for e in ctx.evals if e.symbol == symbol]
        held = None if not rows else rows[0] if len(rows) == 1 else rows[0].model_copy(update={
            "quantity": sum(e.quantity for e in rows),
            "avg_cost": sum(e.quantity * e.avg_cost for e in rows) / max(1, sum(e.quantity for e in rows))})
        atr14 = held.indicators.atr14 if held and held.data_ok else None
        if atr14 is None:
            try:
                cs = await self.candles(broker, symbol, Interval.D1, 300)
            except AuthRequired:
                raise
            except BrokerError:
                cs = []  # không có nến thì vẫn tính được theo % giá vào, kèm cảnh báo thiếu ATR
            if cs:
                atr14 = last_indicators(compute_series(to_frame(align_price_scale(cs, price)),
                                                       ctx.rules.stop_loss.atr_period)).atr14
        return size_position(symbol=symbol, price=price, atr14=atr14, capital=ctx.cash.cash,
                             positions_count=sum(1 for p in ctx.positions if p.quantity > 0), held=held,
                             rules=ctx.rules, market=ctx.market, stop=stop)

    # ---------- bảng giá ----------

    async def board(self, broker: str, account_id: str | None) -> BoardResponse:
        """Bảng giá chỉ cho các mã trong danh mục, kèm khối lượng đang giữ và lãi lỗ của bạn."""
        ctx = await self.context(broker, account_id)
        ad = self.adapter(broker)
        held = {p.symbol: p for p in merge_by_symbol(ctx.positions)}
        symbols = sorted(held)
        key = (broker, ctx.account.id, "board")
        quotes = self._candle_cache.get(key, 3)
        note = None
        if quotes is None:
            try:
                quotes = await ad.get_board(symbols)
            except AuthRequired:
                raise
            except BrokerError as e:
                quotes, note = {}, f"Không lấy được bảng giá: {e.message}"
            self._candle_cache.set(key, quotes)
        rows: list[BoardRow] = []
        for s in symbols:
            p = held[s]
            q = quotes.get(s) or BoardQuote(symbol=s, price=p.price)
            price = q.price or p.price
            rows.append(BoardRow(**q.model_dump(), held_qty=p.quantity, avg_cost=p.avg_cost,
                                 pnl_pct=((price / p.avg_cost - 1) * 100) if price and p.avg_cost else None,
                                 sources=[x.source for x in p.sources]))
        idx = None
        mf = ctx.rules.entry.market_filter
        try:
            ic = await self.candles(broker, mf.index, Interval.D1, 320, is_index=True)
            if len(ic) >= 2:
                v, prev = ic[-1].close, ic[-2].close
                idx = BoardIndex(symbol=mf.index, value=v, change=v - prev, change_pct=(v / prev - 1) * 100)
        except BrokerError:
            pass
        src = ad._price_source() if broker == "ledger" else ad  # type: ignore[attr-defined]
        if not quotes and not note:
            note = "Nguồn dữ liệu hiện chỉ có giá khớp, chưa có ba bước giá." if src else "Chưa có nguồn giá: đăng nhập TCBS."
        return BoardResponse(as_of=now_vn(), source=src.display_name if src else None, rows=rows, index=idx, note=note)

    # ---------- snapshot ----------

    async def snapshot(self, broker: str, account_id: str | None = None) -> dict[str, Any]:
        ctx = await self.context(broker, account_id, force=True)
        gaps = [m.bucket.ratio_pct - m.bucket.maintenance_pct for m in ctx.margin.buckets
                if m.bucket.ratio_pct is not None and m.bucket.maintenance_pct is not None]
        a = ctx.assets
        payload = {
            "positions": [e.model_dump(mode="json", include={"symbol", "quantity", "avg_cost", "price", "pnl_pct",
                                                              "status", "stop_level"}) for e in ctx.evals],
            "buckets": [{"id": m.bucket.id, "ratio_pct": m.bucket.ratio_pct, "maintenance_pct": m.bucket.maintenance_pct}
                        for m in ctx.margin.buckets],
            "market": ctx.market.model_dump(mode="json"),
        }
        self.store.save_snapshot(now_vn().date(), broker, ctx.account.id, nav=a.nav, positions_value=a.positions_value,
                                 cash=a.cash, debt=a.debt, interest_per_day=a.interest_per_day,
                                 min_rtt_gap=min(gaps) if gaps else None, payload=payload)
        return {"broker": broker, "account_id": ctx.account.id, "nav": a.nav}

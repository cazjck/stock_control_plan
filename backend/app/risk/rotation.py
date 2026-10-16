"""Đảo hàng khi hồi (mục 6b của docs/trading-rules.md): bán một phần lúc hồi, mua lại lúc chỉnh.

Còn gọi là trading around a core position. Giữ phần lõi, bán tối đa một nửa vào nhịp hồi trong xu hướng giảm,
mua lại đúng số đã bán khi giá chỉnh xuống mà vẫn giữ được đáy cũ. Không bao giờ làm tăng tổng số cổ phiếu.
Hàm thuần tuý, không gọi mạng. Chỉ khuyến nghị; người dùng tự đặt lệnh ở công ty chứng khoán."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import pandas as pd

from ..models import MarketInfo, MarketState, RotationCheck, RotationPlan, RotationTrade
from ..util import vg, vn
from .rules import Rules
from .take_profit import lot


def _ok(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def _fmt(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


@dataclass
class Swing:
    low: float
    high: float
    low_date: date


def swing(s: pd.DataFrame, rules: Rules) -> Swing | None:
    """Đáy gần nhất trong N phiên và đỉnh trong M phiên tính tới đáy đó (đoạn giảm vừa qua)."""
    r = rules.rotation
    if len(s) < 5:
        return None
    win = s.tail(r.low_lookback_sessions)
    i_low = win["low"].astype(float).idxmin()
    low = float(s.loc[i_low, "low"])
    upto = s.loc[:i_low].tail(r.high_lookback_sessions)
    high = float(upto["high"].astype(float).max())
    if not (low > 0 and high > low):
        return None
    return Swing(low=low, high=high, low_date=s.loc[i_low, "date"])


def tier_price(sw: Swing, rebound_pct: float, retrace_pct: float, min_rebound_pct: float) -> float:
    """Giá bắt đầu một bậc bán: điều kiện nào đến trước (hồi % từ đáy hoặc lấy lại % đoạn giảm), nhưng tối thiểu hồi min%."""
    by_rebound = sw.low * (1 + rebound_pct / 100)
    by_retrace = sw.low + retrace_pct / 100 * (sw.high - sw.low)
    return max(sw.low * (1 + min_rebound_pct / 100), min(by_rebound, by_retrace))


@dataclass
class Cycle:
    trades: list[RotationTrade]
    sold: int
    bought: int
    sold_value: float
    first_sell: date

    @property
    def open_qty(self) -> int:
        return max(0, self.sold - self.bought)

    @property
    def sold_avg(self) -> float:
        return self.sold_value / self.sold if self.sold else 0.0


def sessions_after(s: pd.DataFrame, d: date, today: date) -> int:
    """Số phiên đã qua sau ngày d. Dùng nến thật; hôm nay chưa có nến thì đếm thêm nếu là ngày thường."""
    n = int((s["date"] > d).sum())
    last = s["date"].iloc[-1]
    if today > last and today > d and today.weekday() < 5:
        n += 1
    return n


def current_cycle(trades: list[RotationTrade], s: pd.DataFrame, rules: Rules, today: date) -> tuple[Cycle | None, bool]:
    """Chu kỳ đang mở (đã bán, chưa mua lại đủ). Trả thêm cờ: chu kỳ gần nhất vừa quá hạn."""
    win = rules.rotation.rebuy_window_sessions
    cyc: Cycle | None = None
    for t in sorted(trades, key=lambda x: (x.trade_date, x.id)):
        if cyc and cyc.open_qty and sessions_after(s, cyc.first_sell, t.trade_date) > win:
            cyc = None
        if t.side == "sell":
            if cyc is None or cyc.open_qty == 0:
                cyc = Cycle([], 0, 0, 0.0, t.trade_date)
            cyc.trades.append(t)
            cyc.sold += t.quantity
            cyc.sold_value += t.quantity * t.price
        elif cyc is not None and cyc.open_qty:
            cyc.trades.append(t)
            cyc.bought += t.quantity
    if cyc is None or cyc.open_qty == 0:
        return None, False
    if sessions_after(s, cyc.first_sell, today) > win:
        return None, True
    return cyc, False


def build_rotation(*, s: pd.DataFrame, price: float, qty: int, cost: float, mode: str, thesis: bool | None,
                   market: MarketInfo, margin_ok: bool | None, trades: list[RotationTrade], rules: Rules,
                   today: date, zones: list[tuple[float, int]] | None = None, stage: int | None = None) -> RotationPlan | None:
    """zones: vùng cản kỹ thuật (mục 6d) dạng (giá, số cổ phiếu bán ở vùng đó); có thì thay các mốc phần trăm.
    stage = 2 (Weinstein, đang tăng): không bán đảo hàng."""
    r = rules.rotation
    if not r.enabled or mode == "dca" or s is None or len(s) < 5 or qty <= 0:
        return None
    cyc, expired = current_cycle(trades, s, rules, today)
    if cyc is None and price >= cost:
        return None          # đang lãi: dùng luật chốt lời, không đảo hàng
    sw = swing(s, rules)
    if sw is None:
        return None

    close = float(s["close"].iloc[-1])
    sma50 = float(s["sma50"].iloc[-1]) if "sma50" in s and _ok(float(s["sma50"].iloc[-1])) else None
    rsi = float(s["rsi14"].iloc[-1]) if "rsi14" in s and _ok(float(s["rsi14"].iloc[-1])) else None
    rebound = (price / sw.low - 1) * 100
    retrace = (price - sw.low) / (sw.high - sw.low) * 100
    tiers = [tier_price(sw, t.rebound_pct, t.retrace_pct, r.min_rebound_pct) for t in r.sell_tiers]
    if zones:
        tiers = [p for p, _ in zones]
    open_qty = cyc.open_qty if cyc else 0
    base = qty + open_qty
    rebuy_allowed = thesis is not False and margin_ok is not False
    blocked_why = ("hàng kẹt nhóm B (không có luận điểm) chỉ bán, không mua lại" if thesis is False else
                   "tài khoản đang vay margin sát ngưỡng: tiền bán phải trả nợ trước" if margin_ok is False else "")
    above_sma50 = sma50 is not None and close > sma50
    trend_change = (retrace >= r.trend_change_retrace_pct and above_sma50) or stage == 2
    note_expired = (f"Chu kỳ đảo hàng trước đã quá {r.rebuy_window_sessions} phiên không mua lại: coi như đã bán hẳn. "
                    if expired else "")

    tier_qtys: list[int] = []
    cum_pct, prev = 0.0, 0
    if zones:
        tier_qtys = [q for _, q in zones]
    else:
        for t in r.sell_tiers:
            cum_pct = min(cum_pct + t.sell_pct, r.max_rotation_pct)
            cum = lot(base * cum_pct / 100, base)
            tier_qtys.append(max(0, cum - prev))
            prev = cum
    plan = RotationPlan(phase="falling", phase_label="", level="none", text="", rebuy_allowed=rebuy_allowed,
                        low=sw.low, high=sw.high, rebound_pct=rebound, retrace_pct=retrace, tier_prices=tiers, tier_qtys=tier_qtys,
                        base_qty=base, open_qty=open_qty, trades=cyc.trades if cyc else [])

    # ---- phần bán: số cổ phiếu nên đã bán theo các bậc đang đạt ----
    target_pct = 0.0
    met_tiers = []
    for i, t in enumerate(r.sell_tiers):
        met = rebound >= r.min_rebound_pct and (rebound >= t.rebound_pct or retrace >= t.retrace_pct)
        if not met and i > 0 and met_tiers and rsi is not None and rsi >= r.bear_rsi_ceiling:
            met = True       # đã đạt bậc trước và RSI chạm trần vùng giảm (Brown/Cardwell)
        if met:
            met_tiers.append(i + 1)
            target_pct += t.sell_pct
    target_pct = min(target_pct, r.max_rotation_pct)
    target_qty = lot(base * target_pct / 100, base) if target_pct else 0
    if zones:
        met_tiers = [i + 1 for i, (p, _) in enumerate(zones) if price >= p]
        target_qty = min(sum(q for p, q in zones if price >= p), int(base * r.max_rotation_pct / 100))
        target_pct = target_qty / base * 100 if base else 0
    sell_due = 0 if trend_change else max(0, min(qty, target_qty - open_qty))
    if sell_due and qty - sell_due < 100 and qty > sell_due:
        sell_due = lot(sell_due, qty)

    def sell_text() -> str:
        k = met_tiers[-1]
        txt = (f"Nhịp hồi {vn(rebound, 1)}% từ đáy {_fmt(sw.low)}, lấy lại {vn(retrace, 0)}% đoạn giảm từ {_fmt(sw.high)}: "
               f"bán {_fmt(sell_due)} cổ phiếu (đợt {k}, cộng dồn {vn(target_pct, 0)}% lượng gốc {_fmt(base)}). ")
        if margin_ok is False:
            txt += "Tiền bán dùng trả nợ margin trước. "
        if thesis is False:
            txt += "Nhóm B: đây là giá thoát tốt hơn, không mua lại."
        elif margin_ok is False:
            txt += "Chỉ mua lại khi tỷ lệ ký quỹ đã về vùng an toàn."
        else:
            ref = price if not cyc else (cyc.sold_value + sell_due * price) / (cyc.sold + sell_due)
            txt += (f"Mua lại khi giá về {_fmt(ref * (1 - r.rebuy_drop_pct / 100))} trở xuống mà vẫn trên đáy {_fmt(sw.low)}.")
        return txt

    if cyc:
        plan.sold_qty, plan.bought_qty, plan.sold_avg = cyc.sold, cyc.bought, cyc.sold_avg
        before = s[s["date"] <= cyc.first_sell]
        sw0 = swing(before, rules) if len(before) >= 5 else None
        floor = sw0.low if sw0 else sw.low
        since = s[s["date"] > cyc.first_sell]
        n_since = sessions_after(s, cyc.first_sell, today)
        rebuy_below = cyc.sold_avg * (1 - r.rebuy_drop_pct / 100)
        plan.floor, plan.rebuy_below = floor, rebuy_below
        plan.sessions_since_sell, plan.sessions_left = n_since, max(0, r.rebuy_window_sessions - n_since)
        lowest_close = min([float(x) for x in since["close"]] + [price]) if len(since) else price
        prev_high = float(s["high"].iloc[-2]) if len(s) >= 2 else None
        checks = [
            RotationCheck(code="below_sell", label=f"Giá thấp hơn giá bán bình quân từ {vg(r.rebuy_drop_pct)}%",
                          met=price <= rebuy_below, detail=f"giá {_fmt(price)}, cần ≤ {_fmt(rebuy_below)} (bán bq {_fmt(cyc.sold_avg)})"),
            RotationCheck(code="above_floor", label="Vẫn trên đáy cũ (chưa đóng cửa thủng)",
                          met=lowest_close >= floor, detail=f"đóng cửa thấp nhất từ lúc bán {_fmt(lowest_close)}, đáy cũ {_fmt(floor)}"),
            RotationCheck(code="reversal", label="Có phiên đảo chiều: đóng cửa trên giá cao phiên trước",
                          met=prev_high is not None and close > prev_high,
                          detail=f"đóng cửa {_fmt(close)}, cao phiên trước {_fmt(prev_high)}" if prev_high else "chưa đủ dữ liệu"),
            RotationCheck(code="settled", label=f"Đã qua {r.rebuy_min_sessions} phiên từ lần bán (tiền về sau T+2)",
                          met=n_since >= r.rebuy_min_sessions, detail=f"{n_since} phiên"),
            RotationCheck(code="market", label="Thị trường chung không yếu (VN-Index không dưới SMA200)",
                          met=market.state != MarketState.WEAK, detail=market.note or market.state.value),
            RotationCheck(code="margin", label="Không vay margin sát ngưỡng",
                          met=margin_ok is not False, detail="an toàn" if margin_ok else "chưa rõ" if margin_ok is None else "đang sát ngưỡng"),
        ]
        plan.checks = checks
        if thesis is False:
            checks.append(RotationCheck(code="thesis", label="Có luận điểm giữ mã (không phải nhóm B)", met=False,
                                        detail="nhóm B chỉ bán"))
        n_rebuy = lot(cyc.open_qty, cyc.open_qty)
        head = f"Đã bán {_fmt(cyc.sold)} cổ phiếu giá bình quân {_fmt(cyc.sold_avg)}"
        head += f", đã mua lại {_fmt(cyc.bought)}" if cyc.bought else ""
        if lowest_close < floor:
            plan.phase, plan.phase_label, plan.level = "broken", "Thủng đáy cũ", "none"
            plan.text = (f"{head}. Giá đã đóng cửa thủng đáy cũ {_fmt(floor)}: xu hướng giảm tiếp, KHÔNG mua lại. "
                         f"Phần đã bán coi như cắt lỗ đúng lúc; phần lõi theo mức cắt lỗ hàng kẹt.")
        elif all(c.met for c in checks):
            plan.phase, plan.phase_label, plan.level, plan.rebuy_qty = "rebuy_zone", "Vùng mua lại", "rebuy", n_rebuy
            plan.text = (f"{head}. Đủ điều kiện mua lại: mua {_fmt(n_rebuy)} cổ phiếu quanh {_fmt(price)}, chỉ bằng tiền của "
                         f"lần bán, không dùng margin. Lô này chịu luật lô mua thêm (mục 3.5): cắt lỗ riêng, hạn T+2 cộng 3 phiên.")
        elif sell_due:
            plan.phase, plan.phase_label, plan.level, plan.sell_qty = "sell_zone", "Vùng bán", "sell", sell_due
            plan.text = f"{head}. " + sell_text()
        elif price >= cyc.sold_avg * (1 + r.no_chase_above_sell_pct / 100) and above_sma50:
            plan.phase, plan.phase_label, plan.level = "missed", "Không mua đuổi", "none"
            plan.text = (f"{head}. Giá đã vượt giá bán {vn((price / cyc.sold_avg - 1) * 100, 1)}% và trên SMA50: không mua đuổi. "
                         f"Phần đã bán coi như chốt, giữ phần lõi theo luật thường.")
        else:
            plan.phase, plan.phase_label = "wait_rebuy", "Chờ mua lại"
            missing = [c.label.lower() for c in checks if not c.met]
            if not rebuy_allowed:
                plan.level = "blocked"
                plan.text = f"{head}. Chưa được mua lại: {blocked_why}."
            elif price <= rebuy_below:
                plan.level = "watch"
                plan.text = f"{head}. Giá đã vào vùng mua lại, còn thiếu: {'; '.join(missing)}."
            else:
                plan.text = (f"{head}. Chờ giá về {_fmt(rebuy_below)} trở xuống mà vẫn trên đáy {_fmt(floor)}. "
                             f"Còn {plan.sessions_left} phiên trước khi chu kỳ kết thúc.")
        return plan

    # ---- chưa bán trong chu kỳ nào ----
    if trend_change:
        plan.phase, plan.phase_label = "trend_change", "Có thể đổi xu hướng"
        plan.text = (note_expired + f"Giá đã lấy lại {vn(retrace, 0)}% đoạn giảm và đóng cửa trên SMA50: không còn là nhịp hồi "
                     f"trong xu hướng giảm. Không bán đảo hàng, quay về luật thường.")
    elif sell_due:
        plan.phase, plan.phase_label, plan.level, plan.sell_qty = "sell_zone", "Vùng bán", "sell", sell_due
        plan.text = note_expired + sell_text()
    elif rebound >= r.min_rebound_pct:
        plan.phase, plan.phase_label, plan.level = "rebounding", "Đang hồi", "watch"
        plan.text = (note_expired + f"Đang hồi {vn(rebound, 1)}% từ đáy {_fmt(sw.low)}, chưa tới giá bán. Khi giá lên {_fmt(tiers[0])} "
                     f"(còn {vn((tiers[0] / price - 1) * 100, 1)}%) thì bán đợt 1: {_fmt(tier_qtys[0])} cổ phiếu. "
                     f"Đừng mua thêm trong nhịp hồi.")
    else:
        plan.phase, plan.phase_label = "falling", "Sát đáy"
        plan.text = (note_expired + f"Giá sát đáy {_fmt(sw.low)} (đỉnh trước {_fmt(sw.high)}). Chưa có nhịp hồi; không mua thêm "
                     f"để bắt đáy. Khi giá lên {_fmt(tiers[0])} thì bán đợt 1: {_fmt(tier_qtys[0])} cổ phiếu.")
    if not rebuy_allowed and plan.level == "watch":
        plan.text += f" Lưu ý: {blocked_why}."
    return plan

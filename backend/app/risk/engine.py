"""Risk engine theo bộ luật giao dịch v2 (docs/trading-rules.md).

Các hàm ở đây thuần tuý (không gọi mạng, không đọc đĩa) để test được bằng dữ liệu tổng hợp.
Engine chỉ ĐỀ XUẤT: không có đường nào dẫn tới việc đặt lệnh."""
from __future__ import annotations

import math
from datetime import date

import pandas as pd

from ..models import (
    Indicators, LadderStatus, MarketInfo, MarketState, Position, PositionEval, PositionPlan,
    PositionStatus,
)
from ..util import vg, vn
from .indicators import compute_series, last_indicators
from .take_profit import build_plan
from .rules import Rules

STATUS_BASE = {
    PositionStatus.STOP_HIT: 100, PositionStatus.TRAPPED: 90, PositionStatus.TIME_STOP: 60,
    PositionStatus.WARNING: 50, PositionStatus.TAKE_PROFIT: 45, PositionStatus.SAFE: 0,
}


def _ok(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def market_state(df_index: pd.DataFrame | None, rules: Rules) -> MarketInfo:
    mf = rules.entry.market_filter
    if df_index is None or len(df_index) < mf.slow_ma:
        return MarketInfo(state=MarketState.UNKNOWN, index_symbol=mf.index,
                          note=f"Chưa đủ {mf.slow_ma} phiên dữ liệu chỉ số, tạm coi như bình thường")
    c = df_index["close"].astype(float)
    close = float(c.iloc[-1])
    fast = float(c.tail(mf.fast_ma).mean())
    slow = float(c.tail(mf.slow_ma).mean())
    if close < slow:
        state, note = MarketState.WEAK, f"{mf.index} dưới SMA{mf.slow_ma}: thị trường yếu, chốt 10–15% và siết cắt lỗ"
    elif close < fast:
        state, note = MarketState.NO_NEW_BUYS, f"{mf.index} dưới SMA{mf.fast_ma}: không mở vị thế swing mới"
    else:
        state, note = MarketState.NORMAL, f"{mf.index} trên SMA{mf.fast_ma} và SMA{mf.slow_ma}"
    return MarketInfo(state=state, index_symbol=mf.index, close=close, sma50=fast, sma200=slow, note=note)


def _ladder_status(rules: Rules, pnl_pct: float, ladder_done: int, hold_8w: bool) -> list[LadderStatus]:
    out: list[LadderStatus] = []
    sell_idx = 0
    first_sell_seen = False
    for step in rules.take_profit.ladder:
        reached = pnl_pct >= step.gain_pct
        if step.sell_pct > 0:
            executed = sell_idx < ladder_done
            sell_idx += 1
            suspended = hold_8w and first_sell_seen
            first_sell_seen = True
        else:
            executed, suspended = reached, False
        out.append(LadderStatus(gain_pct=step.gain_pct, sell_pct=step.sell_pct,
                                stop_at_gain_pct=step.move_stop_to_gain_pct,
                                reached=reached, executed=executed, suspended=suspended))
    return out


def _fmt(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


def evaluate_position(
    pos: Position,
    df: pd.DataFrame | None,
    plan: PositionPlan | None,
    rules: Rules,
    market: MarketInfo,
    total_value: float,
    *,
    autotuned_stop_pct: float | None = None,
    intraday: bool = False,
    today: date | None = None,
) -> PositionEval:
    mode = plan.mode if plan else "swing"
    cost = pos.avg_cost
    flags: list[str] = []
    actions: list[str] = []

    if df is None or len(df) < 2 or cost <= 0:
        price = pos.price or 0.0
        mv = pos.market_value or price * pos.quantity
        pnl_pct = ((price / cost - 1) * 100) if cost > 0 and price else 0.0
        return PositionEval(
            symbol=pos.symbol, quantity=pos.quantity, avg_cost=cost, price=price, market_value=mv,
            pnl=mv - pos.quantity * cost, pnl_pct=pnl_pct,
            weight_pct=(mv / total_value * 100) if total_value else 0.0, mode=mode,
            status=PositionStatus.SAFE, urgency=0, stop_level=None,
            stop_basis="Thiếu dữ liệu nến để tính", distance_to_stop_pct=None, risk_to_stop_value=None,
            peak_gain_pct=0.0, peak_is_proxy=True, indicators=Indicators(), ladder=[],
            actions=["Chưa lấy được dữ liệu giá lịch sử, không thể đánh giá mã này"],
            flags=["no_data"], plan=plan, data_ok=False,
        )

    s = compute_series(df, rules.stop_loss.atr_period, rules.take_profit.trailing.atr_period)
    ind = last_indicators(s)
    last_close = float(s["close"].iloc[-1])
    price = float(pos.price) if _ok(pos.price) and pos.price else last_close
    mv = pos.quantity * price
    pnl = mv - pos.quantity * cost
    pnl_pct = (price / cost - 1) * 100

    # ---- đỉnh kể từ khi vào lệnh (hoặc 20 phiên gần nhất nếu chưa khai báo ngày vào) ----
    peak_is_proxy = True
    sessions_held: int | None = None
    window = s.tail(20)
    if plan and plan.entry_date:
        w = s[s["date"] >= plan.entry_date]
        if not w.empty:
            window, peak_is_proxy = w, False
            sessions_held = len(w) - 1
    peak_close = max(float(window["close"].max()), price)
    peak_gain = max(0.0, (peak_close / cost - 1) * 100)

    # ---- luật 8 tuần ----
    hold_8w = False
    ew = rules.take_profit.eight_week_rule
    if ew.enabled and plan and plan.entry_date and not peak_is_proxy and sessions_held is not None:
        early = window.head(ew.within_sessions + 1)
        if float(early["close"].max()) >= cost * (1 + ew.gain_pct / 100) and sessions_held < ew.hold_sessions:
            hold_8w = True
            flags.append("eight_week_hold")

    ladder = _ladder_status(rules, pnl_pct, plan.ladder_done if plan else 0, hold_8w)

    # ---- mức cắt lỗ ----
    sl = rules.stop_loss
    stop_pct = sl.weak_market_pct if market.state == MarketState.WEAK else sl.pct
    if autotuned_stop_pct:
        stop_pct = min(stop_pct, autotuned_stop_pct)
    candidates: list[tuple[float, str]] = [(cost * (1 - stop_pct / 100), f"Cắt lỗ ban đầu −{vg(stop_pct)}% giá vốn")]
    if _ok(ind.atr14):
        candidates.append((cost - sl.atr_multiplier * ind.atr14,
                           f"Cắt lỗ {vg(sl.atr_multiplier)}×ATR{sl.atr_period}"))
    initial, initial_basis = max(candidates, key=lambda x: x[0])
    stop, basis = initial, initial_basis

    for step in rules.take_profit.ladder:
        if step.move_stop_to_gain_pct is not None and peak_gain >= step.gain_pct:
            lvl = cost * (1 + step.move_stop_to_gain_pct / 100)
            if lvl > stop:
                stop = lvl
                basis = "Giá vốn (hoà vốn)" if step.move_stop_to_gain_pct == 0 else \
                    f"Khoá lãi +{vg(step.move_stop_to_gain_pct)}% (đã lãi tới +{vg(step.gain_pct)}%)"
    last_step = rules.take_profit.ladder[-1]
    if peak_gain >= last_step.gain_pct and _ok(ind.atr22):
        trail = peak_close - rules.take_profit.trailing.atr_multiplier * ind.atr22
        sma_floor = float(s["close"].tail(rules.take_profit.trailing.floor_sma).mean())
        trail = max(trail, sma_floor)
        if trail > stop:
            stop, basis = trail, f"Trailing Chandelier ({vg(rules.take_profit.trailing.atr_multiplier)}×ATR{rules.take_profit.trailing.atr_period})"

    status = PositionStatus.SAFE
    tp_plan = None
    tr = rules.trapped
    trapped = False
    stop_out: float | None = stop

    if mode == "dca":
        stop_out = cost * (1 - rules.dca.catastrophe_stop_pct / 100)
        basis = f"Ngưỡng thảm hoạ DCA −{vg(rules.dca.catastrophe_stop_pct)}%"
        ladder = []
        if price < stop_out:
            status = PositionStatus.STOP_HIT
            actions.append(f"Giá dưới ngưỡng thảm hoạ DCA ({_fmt(stop_out)}): xem lại luận điểm, nếu bị phá thì thoát")
        else:
            actions.append("Chế độ DCA: mua theo lịch, không nhìn giá. Chỉ xem lại khi luận điểm bị phá.")
    else:
        trapped = pnl_pct <= -tr.loss_pct_threshold
        if trapped:
            status = PositionStatus.TRAPPED
            flags.append("trapped")
            thesis = plan.has_thesis if plan else None
            if thesis is True:
                lvl_a = min(price * (1 - tr.group_a_stop_from_price_pct / 100),
                            (ind.low20 or price) * (1 - tr.group_a_stop_below_low20_pct / 100))
                stop_out, basis = lvl_a, "Hàng kẹt nhóm A: cắt lỗ mới, thủng là bán hết"
                actions.append(f"Nhóm A (có luận điểm): cắt lỗ mới {_fmt(lvl_a)}. Không mua thêm để trung bình giá.")
            elif thesis is False:
                stop_out, basis = None, "Hàng kẹt nhóm B: thoát theo giao thức, không đặt cắt lỗ"
                actions.append(f"Nhóm B (không có luận điểm): bán {vg(tr.group_b_sell_now_pct)}% ngay phiên tới bằng MP; "
                               f"phần còn lại bán khi giá chạm SMA20"
                               + (f" ({_fmt(ind.sma20)})" if ind.sma20 else "")
                               + f" hoặc sau {tr.group_b_sell_rest_after_sessions} phiên.")
            else:
                stop_out, basis = None, "Hàng kẹt: chưa phân loại nhóm A/B"
                actions.append("Phân loại: viết được luận điểm cơ bản bằng 3 câu → nhóm A (giữ có điều kiện), "
                               "không viết được → nhóm B (thoát). Cập nhật trong kế hoạch của mã.")
        else:
            if price < stop:
                status = PositionStatus.STOP_HIT
                actions.append(
                    f"Giá dưới mức cắt lỗ {_fmt(stop)} ({basis}). Nếu đóng cửa dưới mức này: bán toàn bộ bằng ATO/MP trong 15 phút đầu phiên kế tiếp. Không chờ hồi.")
                if intraday:
                    flags.append("intraday")
            elif (plan and plan.entry_date and sessions_held is not None
                  and sessions_held >= sl.time_stop_sessions and pnl_pct < sl.time_stop_min_gain_pct):
                status = PositionStatus.TIME_STOP
                actions.append(f"Đã giữ {sessions_held} phiên mà lãi chưa tới +{vg(sl.time_stop_min_gain_pct)}%: bán toàn bộ (cắt lỗ theo thời gian).")
            elif _ok(ind.rsi14) and _ok(ind.sma20) and last_close < ind.sma20 and ind.rsi14 < 40:
                status = PositionStatus.WARNING
                actions.append(f"Cảnh báo: đóng cửa dưới SMA20 và RSI {vn(ind.rsi14, 0)} < 40. Chuẩn bị sẵn kế hoạch bán nếu chạm {_fmt(stop)}.")

            # chốt lời: một khuyến nghị duy nhất từ module take_profit (bậc giá, cao trào, yếu đi, thị trường yếu)
            tp_plan = build_plan(s=s, price=price, cost=cost, qty=pos.quantity, rules=rules, ladder=ladder,
                                 initial_stop=initial, pnl_pct=pnl_pct, market=market, hold_8w=hold_8w)
            if status in (PositionStatus.SAFE, PositionStatus.WARNING) and tp_plan.advice.level in ("partial", "full"):
                status = PositionStatus.TAKE_PROFIT
                actions.insert(0, tp_plan.advice.text)
            elif tp_plan.advice.level == "watch":
                actions.append(tp_plan.advice.text)
            elif status == PositionStatus.SAFE and hold_8w:
                actions.append("Luật 8 tuần: mã tăng mạnh sớm, giữ tới hết 8 tuần, chỉ bán nếu thủng trailing stop.")
            if status == PositionStatus.SAFE and not actions:
                actions.append(f"Giữ. Cắt lỗ hiện tại {_fmt(stop)} ({basis}).")

    dist = ((price / stop_out - 1) * 100) if stop_out else None
    risk_val = max(0.0, price - stop_out) * pos.quantity if stop_out else None
    urgency = float(STATUS_BASE[status])
    if status in (PositionStatus.SAFE, PositionStatus.WARNING) and dist is not None:
        urgency += max(0.0, 20.0 - dist)
    if status == PositionStatus.TRAPPED:
        urgency += min(10.0, abs(pnl_pct) / 3)

    return PositionEval(
        symbol=pos.symbol, quantity=pos.quantity, avg_cost=cost, price=price, market_value=mv,
        pnl=pnl, pnl_pct=pnl_pct, weight_pct=(mv / total_value * 100) if total_value else 0.0,
        mode=mode, status=status, urgency=urgency, stop_level=stop_out, stop_basis=basis,
        distance_to_stop_pct=dist, risk_to_stop_value=risk_val, peak_gain_pct=peak_gain,
        peak_is_proxy=peak_is_proxy, indicators=ind, ladder=ladder, actions=actions, flags=flags,
        plan=plan, take_profit=tp_plan,
    )

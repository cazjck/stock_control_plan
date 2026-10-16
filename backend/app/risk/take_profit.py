"""Khuyến nghị chốt lời (bổ sung mục 4 của docs/trading-rules.md).

Ba nhánh, theo thứ tự ưu tiên khi đưa ra MỘT khuyến nghị cho hôm nay:
  1. Bán khi yếu đi để giữ lãi (IBD): đóng cửa dưới SMA50 thì bán phần còn lại; thủng EMA21 với khối lượng lớn thì bán một nửa.
  2. Bán vào sức mạnh (O'Neil/IBD climax top, Minervini "khi nghi ngờ thì bán một nửa"):
     từ 2 dấu hiệu tăng cao trào trở lên thì bán một nửa phần đang giữ.
  3. Chốt theo bậc giá mục tiêu (+10%, +15%, +25% giá vốn), mỗi bậc 25% khối lượng ban đầu.
Mục tiêu theo bội số R (2R, 3R, Van Tharp) chỉ để tham chiếu.
RSI quá mua là tín hiệu phụ: chỉ được tính khi đã có ít nhất một dấu hiệu cao trào khác, vì trong xu hướng mạnh
RSI có thể ở vùng cao rất lâu và chưa có kiểm định nghiêm túc cho riêng nó.
Hàm thuần túy, không gọi mạng."""
from __future__ import annotations

import math

import pandas as pd

from ..models import (
    LadderStatus, MarketInfo, MarketState, TakeProfitAdvice, TakeProfitPlan, TakeProfitSignal, TakeProfitTarget,
)
from ..util import vg, vn
from .rules import Rules


def _ok(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def _fmt(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


def lot(q: float, held: int) -> int:
    """Làm tròn xuống lô 100, tối thiểu 100 cổ phiếu, không vượt số đang giữ. Dưới 100 cổ phiếu (lô lẻ) thì bán hết."""
    if held < 100:
        return held
    return min(held, max(100, int(q // 100) * 100))


def _strength(s: pd.DataFrame, rules: Rules) -> list[TakeProfitSignal]:
    cr = rules.take_profit.climax
    c, h, l, v = (s[k].astype(float) for k in ("close", "high", "low", "volume"))
    vol_ma = s["vol_ma20"].astype(float) if "vol_ma20" in s else pd.Series([float("nan")] * len(s))
    last = float(c.iloc[-1])
    out: list[TakeProfitSignal] = []

    win = c.tail(cr.within_sessions + 1)
    low_win = float(win.min())
    run = (last / low_win - 1) * 100 if low_win > 0 else 0.0
    out.append(TakeProfitSignal(code="climax_run", group="strength",
                                label=f"Tăng từ {vg(cr.gain_pct)}% trở lên trong {cr.within_sessions} phiên",
                                met=run >= cr.gain_pct, detail=f"+{vn(run, 1)}% so với đáy {cr.within_sessions} phiên"))

    chg = c.diff().tail(cr.up_days_window)
    ups = int((chg > 0).sum())
    out.append(TakeProfitSignal(code="up_streak", group="strength",
                                label=f"Ít nhất {cr.up_days}/{cr.up_days_window} phiên gần nhất là phiên tăng",
                                met=ups >= cr.up_days, detail=f"{ups}/{cr.up_days_window} phiên tăng"))

    pct = c.pct_change() * 100
    look = pct.tail(cr.lookback_sessions)
    met_big, detail_big = False, "không có"
    if look.notna().any():
        idx = look.idxmax()
        pos_from_end = len(s) - 1 - s.index.get_loc(idx)
        vr = float(v.loc[idx] / vol_ma.loc[idx]) if _ok(float(vol_ma.loc[idx])) and vol_ma.loc[idx] > 0 else 0.0
        met_big = pos_from_end < 5 and vr >= cr.volume_ratio and look.loc[idx] > 0
        detail_big = (f"phiên tăng mạnh nhất {cr.lookback_sessions} phiên là +{vn(float(look.loc[idx]), 1)}% "
                      f"cách đây {pos_from_end} phiên, khối lượng {vn(vr, 1)}× TB20")
    out.append(TakeProfitSignal(code="climax_day", group="strength",
                                label=f"Phiên tăng mạnh nhất {cr.lookback_sessions} phiên rơi vào 5 phiên gần nhất, khối lượng từ {vg(cr.volume_ratio)}× TB20",
                                met=met_big, detail=detail_big))

    gap_days = [i for i in range(max(1, len(s) - 3), len(s)) if float(l.iloc[i]) > float(h.iloc[i - 1])]
    met_gap = bool(gap_days) and run >= cr.exhaustion_gap_min_gain_pct
    out.append(TakeProfitSignal(code="exhaustion_gap", group="strength",
                                label=f"Khoảng trống tăng giá sau khi đã tăng từ {vg(cr.exhaustion_gap_min_gain_pct)}%",
                                met=met_gap, detail=f"{len(gap_days)} khoảng trống trong 3 phiên" if gap_days else "không có khoảng trống"))

    sma50 = float(s["sma50"].iloc[-1]) if "sma50" in s and _ok(float(s["sma50"].iloc[-1])) else None
    ext = (last / sma50 - 1) * 100 if sma50 else None
    out.append(TakeProfitSignal(code="extended", group="strength",
                                label=f"Giá cách SMA50 từ {vg(cr.extension_above_sma50_pct)}% trở lên",
                                met=ext is not None and ext >= cr.extension_above_sma50_pct,
                                detail=f"cách SMA50 {vn(ext, 1, sign=True)}%" if ext is not None else "chưa đủ 50 phiên"))

    rsi = float(s["rsi14"].iloc[-1]) if "rsi14" in s and _ok(float(s["rsi14"].iloc[-1])) else None
    main = sum(x.met for x in out)
    out.append(TakeProfitSignal(code="rsi_overbought", group="strength",
                                label=f"RSI14 từ {vg(cr.rsi_overbought)} (tín hiệu phụ, chỉ tính khi đã có dấu hiệu khác)",
                                met=rsi is not None and rsi >= cr.rsi_overbought and main >= 1,
                                detail=f"RSI {vn(rsi, 0)}" if rsi is not None else "—"))
    return out


def _weakness(s: pd.DataFrame, rules: Rules, pnl_pct: float, hold_8w: bool) -> list[TakeProfitSignal]:
    wr = rules.take_profit.weakness
    last = s.iloc[-1]
    close = float(last["close"])
    applies = pnl_pct >= wr.min_gain_pct
    gate = "" if applies else f" (chỉ xét khi đang lãi từ {vg(wr.min_gain_pct)}%)"
    out: list[TakeProfitSignal] = []

    ema_col = f"ema{wr.ema_period}" if f"ema{wr.ema_period}" in s else "ema21"
    ema = float(last[ema_col]) if ema_col in s and _ok(float(last[ema_col])) else None
    vma = float(last["vol_ma20"]) if "vol_ma20" in s and _ok(float(last["vol_ma20"])) else None
    vr = float(last["volume"]) / vma if vma else 0.0
    broke = ema is not None and close < ema and vr >= wr.heavy_volume_ratio
    detail = (f"đóng cửa {_fmt(close)} {'dưới' if ema and close < ema else 'trên'} EMA{wr.ema_period} {_fmt(ema)}, "
              f"khối lượng {vn(vr, 1)}× TB20" if ema else "chưa đủ dữ liệu")
    if hold_8w:
        detail += " · đang trong 8 tuần giữ, bỏ qua tín hiệu này"
    out.append(TakeProfitSignal(code="ema_break_heavy", group="weakness",
                                label=f"Thủng EMA{wr.ema_period} với khối lượng từ {vg(wr.heavy_volume_ratio)}× TB20{gate}",
                                met=applies and broke and not hold_8w, detail=detail))

    sma_col = f"sma{wr.sma_exit}"
    sma = float(last[sma_col]) if sma_col in s and _ok(float(last[sma_col])) else None
    out.append(TakeProfitSignal(code="below_sma50", group="weakness",
                                label=f"Đóng cửa dưới SMA{wr.sma_exit}{gate}",
                                met=applies and sma is not None and close < sma,
                                detail=f"đóng cửa {_fmt(close)}, SMA{wr.sma_exit} {_fmt(sma)}" if sma else "chưa đủ dữ liệu"))
    return out


def build_plan(*, s: pd.DataFrame, price: float, cost: float, qty: int, rules: Rules, ladder: list[LadderStatus],
               initial_stop: float, pnl_pct: float, market: MarketInfo, hold_8w: bool) -> TakeProfitPlan:
    tp = rules.take_profit
    done_pct = sum(st.sell_pct for st in ladder if st.sell_pct > 0 and st.executed)
    original = int(round(qty / (1 - done_pct / 100))) if done_pct < 100 else qty

    targets: list[TakeProfitTarget] = []
    for st in ladder:
        if st.sell_pct <= 0:
            continue
        p = cost * (1 + st.gain_pct / 100)
        targets.append(TakeProfitTarget(
            label=f"+{vg(st.gain_pct)}%", kind="ladder", price=p, distance_pct=(p / price - 1) * 100,
            sell_pct_of_original=st.sell_pct, sell_qty=lot(original * st.sell_pct / 100, qty),
            reached=price >= p, executed=st.executed, suspended=st.suspended))
    r_value = cost - initial_stop if initial_stop and cost > initial_stop else None
    if r_value:
        for k in tp.r_targets:
            p = cost + k * r_value
            targets.append(TakeProfitTarget(label=f"{vg(k)}R", kind="r", price=p, distance_pct=(p / price - 1) * 100,
                                            reached=price >= p))
    r_multiple = (price - cost) / r_value if r_value else None
    pending = [t for t in targets if t.kind == "ladder" and not t.executed and not t.suspended and not t.reached]
    next_target = min(pending, key=lambda t: t.price) if pending else None

    signals = _strength(s, rules) + _weakness(s, rules, pnl_pct, hold_8w)
    met = {x.code for x in signals if x.met}
    strength_met = [x for x in signals if x.group == "strength" and x.met]

    def advice() -> TakeProfitAdvice:
        if pnl_pct <= 0:
            first = next_target or (targets[0] if targets else None)
            hint = f" Mục tiêu đầu tiên {_fmt(first.price)} (cần tăng {vn(first.distance_pct, 1)}%)." if first else ""
            return TakeProfitAdvice(level="none", text="Chưa có lãi để chốt." + hint)
        if market.state == MarketState.WEAK and pnl_pct >= tp.weak_market_exit_gain_pct:
            return TakeProfitAdvice(level="full", sell_qty=qty, reason_codes=["weak_market"],
                                    text=f"Thị trường yếu và đang lãi {vn(pnl_pct, 1)}%: chốt toàn bộ {_fmt(qty)} cổ phiếu.")
        if "below_sma50" in met:
            return TakeProfitAdvice(level="full", sell_qty=qty, reason_codes=["below_sma50"],
                                    text=f"Đang lãi {vn(pnl_pct, 1)}% nhưng đóng cửa dưới SMA{tp.weakness.sma_exit}: "
                                         f"bán phần còn lại ({_fmt(qty)} cổ phiếu) để giữ lãi.")
        if len(strength_met) >= tp.climax.min_signals_partial:
            n = lot(qty * tp.climax.sell_fraction, qty)
            names = ", ".join(x.label.split(" (")[0].lower() for x in strength_met[:3])
            return TakeProfitAdvice(level="partial", sell_qty=n, reason_codes=[x.code for x in strength_met],
                                    text=f"{len(strength_met)} dấu hiệu tăng cao trào ({names}): bán {_fmt(n)} cổ phiếu "
                                         f"vào sức mạnh, giữ phần còn lại với trailing stop.")
        if "ema_break_heavy" in met:
            n = lot(qty * tp.weakness.ema_sell_fraction, qty)
            return TakeProfitAdvice(level="partial", sell_qty=n, reason_codes=["ema_break_heavy"],
                                    text=f"Thủng EMA{tp.weakness.ema_period} với khối lượng lớn khi đang lãi: "
                                         f"bán {_fmt(n)} cổ phiếu để giữ lãi.")
        due = next((t for t in targets if t.kind == "ladder" and t.reached and not t.executed and not t.suspended), None)
        if due:
            step = next(st for st in ladder if st.sell_pct > 0 and abs(st.gain_pct - float(due.label.strip("+%").replace(",", "."))) < 1e-9)
            stop_txt = f", dời cắt lỗ lên giá vốn +{vg(step.stop_at_gain_pct)}%" if step.stop_at_gain_pct else ""
            return TakeProfitAdvice(level="partial", sell_qty=due.sell_qty or 0, reason_codes=["ladder"],
                                    text=f"Đạt mốc {due.label}: bán {vg(step.sell_pct)}% khối lượng ban đầu "
                                         f"(khoảng {_fmt(due.sell_qty or 0)} cổ phiếu, giá từ {_fmt(due.price)}){stop_txt}.")
        if strength_met:
            return TakeProfitAdvice(level="watch", reason_codes=[x.code for x in strength_met],
                                    text=f"Có dấu hiệu tăng nóng ({strength_met[0].label.split(' (')[0].lower()}). "
                                         f"Chuẩn bị bán một phần nếu xuất hiện thêm dấu hiệu.")
        if next_target:
            return TakeProfitAdvice(level="none", text=f"Giữ. Mục tiêu tiếp theo {_fmt(next_target.price)} "
                                                       f"(còn {vn(next_target.distance_pct, 1)}%), bán {_fmt(next_target.sell_qty or 0)} cổ phiếu.")
        return TakeProfitAdvice(level="none", text="Đã qua mọi bậc chốt lời. Giữ phần còn lại với trailing stop.")

    return TakeProfitPlan(r_value=r_value, r_multiple=r_multiple, original_qty=original, targets=targets,
                          signals=signals, advice=advice(), next_target=next_target)

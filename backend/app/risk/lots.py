"""Đánh giá từng lần mua (lô) và luật "lô mua thêm khi đang lỗ". Hàm thuần túy.

Luật (docs/trading-rules.md mục 3.5):
  - Lô mua thêm khi mã đang lỗ có mức cắt lỗ RIÊNG tính từ giá mua của chính lô:
    cao hơn trong hai mức: đáy phiên mua − 1%, giá mua − 5%. Giá vốn bình quân che mất lỗ nên không dùng.
  - Hạn thời gian: sau 3 phiên kể từ khi cổ phiếu về tài khoản (T+2) mà lô chưa lãi 3% thì bán lô.
  - Thủng mức cắt lỗ của lô thì bán đúng số cổ phiếu của lô bằng ATO phiên kế tiếp.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from ..models import Lot, LotEval
from ..util import vg, vn
from .rules import Rules


def _fmt(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


def _d(x: date) -> str:
    return x.strftime("%d/%m")


def trading_days_after(start: date, n: int, known: list[date]) -> date:
    """Ngày giao dịch thứ n sau `start`. Dùng ngày có nến nếu có, còn lại bỏ qua thứ Bảy, Chủ nhật."""
    after = [d for d in known if d > start]
    if len(after) >= n:
        return after[n - 1]
    d, count = (after[-1] if after else start), len(after)
    while count < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            count += 1
    return d


def default_stop(lot: Lot, df: pd.DataFrame | None, rules: Rules) -> float:
    r = rules.add_on_lots
    by_price = lot.price * (1 - r.stop_from_price_pct / 100)
    if df is not None and len(df):
        day = df[df["date"] == lot.buy_date]
        if len(day):
            return max(by_price, float(day["low"].iloc[0]) * (1 - r.stop_below_buy_day_low_pct / 100))
    return by_price


def evaluate_lot(lot: Lot, *, price: float | None, df: pd.DataFrame | None, rules: Rules, today: date,
                 label: str | None = None) -> LotEval:
    r = rules.add_on_lots
    dates = sorted(set(df["date"])) if df is not None and len(df) else []
    sessions = len([d for d in dates if d > lot.buy_date]) if dates else max(0, int(pd.bdate_range(lot.buy_date, today).size) - 1)
    sellable_from = trading_days_after(lot.buy_date, r.settle_sessions, dates)
    deadline = trading_days_after(lot.buy_date, r.settle_sessions + r.time_stop_sessions_after_settle, dates)
    pnl_pct = (price / lot.price - 1) * 100 if price else None
    ev = LotEval(**lot.model_dump(), source_label=label, current_price=price, pnl_pct=pnl_pct,
                 pnl_value=(price - lot.price) * lot.remaining if price else None, sessions_held=sessions,
                 sellable_from=sellable_from, sellable=sessions >= r.settle_sessions, deadline=deadline)
    if lot.remaining <= 0:
        ev.rule_status, ev.action = "closed", "Lô đã bán hết."
        return ev
    if not lot.add_on_loss:
        ev.rule_status = "info"
        return ev

    stop = lot.stop_price or default_stop(lot, df, rules)
    ev.stop_price = stop
    head = f"Lô mua ngày {_d(lot.buy_date)} ({_fmt(lot.remaining)} cp, giá {_fmt(lot.price)})"
    when = ("bằng ATO phiên kế tiếp" if ev.sellable
            else f"ngay khi cổ phiếu về tài khoản chiều {_d(sellable_from)}")
    if price is not None and price < stop:
        ev.rule_status = "stop"
        ev.action = f"{head} đã thủng mức cắt lỗ {_fmt(stop)}: bán {_fmt(lot.remaining)} cp {when}. Không chờ hồi."
    elif sessions >= r.settle_sessions + r.time_stop_sessions_after_settle and (pnl_pct or 0) < r.time_stop_min_gain_pct:
        ev.rule_status = "time"
        ev.action = (f"{head} sau {sessions} phiên chưa lãi {vg(r.time_stop_min_gain_pct)}% "
                     f"(đang {vn(pnl_pct or 0, 1, sign=True)}%): bắt đáy không thành, bán {_fmt(lot.remaining)} cp {when}.")
    else:
        ev.rule_status = "ok"
        ev.action = (f"{head}: giữ nếu đóng cửa trên {_fmt(stop)}. Hạn {_d(deadline)}: tới lúc đó phải lãi từ "
                     f"{vg(r.time_stop_min_gain_pct)}%, không thì bán lô này.")

    if ev.rule_status in ("stop", "time") and lot.trigger_date and lot.trigger_price:
        ev.delay_sessions = len([d for d in dates if d > lot.trigger_date]) if dates else None
        if price is not None:
            ev.delay_cost = max(0.0, (lot.trigger_price - price) * lot.remaining)
    return ev

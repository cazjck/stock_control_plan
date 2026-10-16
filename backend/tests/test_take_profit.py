"""Khuyến nghị chốt lời: bậc giá mục tiêu, mục tiêu theo R, bán vào sức mạnh, bán khi yếu đi."""
from __future__ import annotations

import numpy as np
import pytest

from app.models import MarketInfo, MarketState, PositionPlan, PositionStatus
from app.risk.engine import evaluate_position
from app.risk.take_profit import lot

from .conftest import flat, make_candles, make_df, make_position
from app.risk.indicators import to_frame

NORMAL = MarketInfo(state=MarketState.NORMAL)
WEAK = MarketInfo(state=MarketState.WEAK)


def ev(closes, *, cost=100.0, qty=1000, plan=None, rules, market=NORMAL, volume=None, spread=0.01):
    candles = make_candles(closes, spread=spread)
    if volume is not None:
        for c, v in zip(candles, volume):
            c.volume = v
    pos = make_position(cost=cost, price=closes[-1], qty=qty)
    return evaluate_position(pos, to_frame(candles), plan, rules, market, pos.market_value)


def sig(r, code):
    return next(x for x in r.take_profit.signals if x.code == code)


def test_lot_rounding():
    assert lot(250, 1000) == 200 and lot(40, 1000) == 100 and lot(5000, 1000) == 1000 and lot(30, 60) == 60


def test_targets_have_concrete_prices_and_quantities(rules):
    r = ev(flat(60) + [103], rules=rules)
    t = {x.label: x for x in r.take_profit.targets}
    assert t["+10%"].price == pytest.approx(110) and t["+10%"].sell_qty == 200      # 25% của 1.000, làm tròn lô 100
    assert t["+25%"].price == pytest.approx(125)
    assert t["+10%"].distance_pct == pytest.approx((110 / 103 - 1) * 100)
    assert r.take_profit.next_target.label == "+10%"
    assert "Mục tiêu tiếp theo 110" in r.take_profit.advice.text


def test_r_targets_from_initial_stop(rules):
    r = ev(flat(60) + [104], rules=rules)
    tp = r.take_profit
    assert tp.r_value == pytest.approx(100 - r.stop_level if r.stop_level < 100 else tp.r_value)
    two_r = next(x for x in tp.targets if x.label == "2R")
    assert two_r.price == pytest.approx(100 + 2 * tp.r_value)
    assert tp.r_multiple == pytest.approx(4 / tp.r_value)


def test_original_quantity_accounts_for_executed_steps(rules):
    plan = PositionPlan(broker="t", account_id="a", symbol="AAA", ladder_done=1)
    r = ev(flat(60) + [111], qty=750, plan=plan, rules=rules)
    assert r.take_profit.original_qty == 1000
    t = {x.label: x for x in r.take_profit.targets}
    assert t["+10%"].executed and t["+15%"].sell_qty == 200


def test_ladder_step_due_gives_quantity(rules):
    r = ev(flat(40) + [101, 104, 108, 111, 112], rules=rules)
    assert r.status == PositionStatus.TAKE_PROFIT
    assert r.take_profit.advice.level == "partial" and r.take_profit.advice.sell_qty == 200
    assert "Đạt mốc +10%" in r.actions[0] and "200 cổ phiếu" in r.actions[0]


def test_climax_signals_trigger_sell_half_into_strength(rules):
    # nền phẳng rồi tăng dựng đứng ~35% trong 8 phiên, phiên cuối tăng mạnh nhất với khối lượng gấp 3
    closes = flat(60) + [102, 105, 109, 113, 118, 123, 128, 136]
    vol = [1_000_000] * 67 + [3_000_000]
    r = ev(closes, rules=rules, volume=vol)
    met = {x.code for x in r.take_profit.signals if x.met}
    assert {"climax_run", "up_streak", "climax_day"} <= met
    assert r.take_profit.advice.level == "partial" and r.take_profit.advice.sell_qty == 500
    assert r.status == PositionStatus.TAKE_PROFIT and "cao trào" in r.actions[0]


def test_single_strength_sign_is_only_watch(rules):
    closes = flat(60) + [101, 102, 101.5, 103, 104, 103.5, 105, 106]   # tăng đều nhưng không cao trào
    r = ev(closes, rules=rules)
    met = [x.code for x in r.take_profit.signals if x.met and x.group == "strength"]
    assert len(met) <= 1
    assert r.take_profit.advice.level in ("none", "watch")


def test_rsi_alone_never_counts(rules):
    r = ev(flat(60, 100) + list(np.linspace(100.5, 104, 12)), rules=rules)
    rsi = sig(r, "rsi_overbought")
    others = [x for x in r.take_profit.signals if x.group == "strength" and x.code != "rsi_overbought" and x.met]
    if not others:
        assert not rsi.met


def test_below_sma50_while_in_profit_sells_rest(rules):
    # lên 118 rồi lùi về 110: vẫn lãi 10%, trên mức cắt lỗ đã khoá lãi, nhưng đóng cửa dưới SMA50
    closes = list(np.linspace(100, 118, 50)) + list(np.linspace(117.5, 110, 15))
    r = ev(closes, rules=rules)
    assert r.status == PositionStatus.TAKE_PROFIT and sig(r, "below_sma50").met
    assert r.take_profit.advice.level == "full" and r.take_profit.advice.sell_qty == 1000
    assert "SMA50" in r.actions[0]


def test_stop_hit_takes_priority_over_take_profit(rules):
    closes = list(np.linspace(100, 140, 50)) + list(np.linspace(139, 112, 25))
    r = ev(closes, rules=rules)
    assert r.status == PositionStatus.STOP_HIT          # thủng trailing stop: bán theo luật cắt lỗ trước


def test_weakness_ignored_when_profit_is_small(rules):
    closes = list(np.linspace(100, 108, 50)) + list(np.linspace(107.5, 103, 10))
    r = ev(closes, rules=rules)
    assert not sig(r, "below_sma50").met and "chỉ xét khi đang lãi" in sig(r, "below_sma50").label


def test_ema21_heavy_break_sells_half(rules):
    closes = list(np.linspace(100, 114, 60)) + [111.5]
    vol = [1_000_000] * 60 + [2_500_000]
    r = ev(closes, rules=rules, volume=vol)
    assert sig(r, "ema_break_heavy").met and not sig(r, "below_sma50").met
    assert r.take_profit.advice.level == "partial" and r.take_profit.advice.sell_qty == 500
    # cùng đường giá nhưng khối lượng bình thường thì không phải tín hiệu
    r2 = ev(closes, rules=rules, volume=[1_000_000] * 61)
    assert not sig(r2, "ema_break_heavy").met


def test_weak_market_full_exit_with_quantity(rules):
    r = ev(flat(40) + [104, 108, 111], rules=rules, market=WEAK)
    assert r.take_profit.advice.level == "full" and r.take_profit.advice.sell_qty == 1000
    assert "chốt toàn bộ" in r.actions[0]


def test_losing_position_gets_no_sell_advice(rules):
    r = ev(flat(59) + [97], rules=rules)
    assert r.take_profit.advice.level == "none" and "Chưa có lãi" in r.take_profit.advice.text


def test_signals_expose_numbers_for_self_check(rules):
    r = ev(flat(60) + [103], rules=rules)
    for x in r.take_profit.signals:
        assert x.detail and x.label


def test_trapped_and_dca_have_no_take_profit_plan(rules):
    assert ev(flat(59) + [88], rules=rules).take_profit is None
    dca = PositionPlan(broker="t", account_id="a", symbol="AAA", mode="dca")
    assert ev(flat(59) + [120], rules=rules, plan=dca).take_profit is None

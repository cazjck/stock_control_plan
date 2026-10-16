"""Kiểm tra risk engine theo từng điều khoản của docs/trading-rules.md (v2)."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import MarketInfo, MarketState, PositionPlan, PositionStatus
from app.risk.engine import evaluate_position, market_state

from .conftest import flat, make_candles, make_df, make_position
from app.risk.indicators import to_frame

NORMAL = MarketInfo(state=MarketState.NORMAL)
WEAK = MarketInfo(state=MarketState.WEAK)


def ev(closes, *, cost=100.0, price=None, plan=None, rules, market=NORMAL, qty=1000):
    price = price if price is not None else closes[-1]
    pos = make_position(cost=cost, price=price, qty=qty)
    return evaluate_position(pos, make_df(closes), plan, rules, market, total_value=pos.market_value)


def test_initial_stop_takes_nearer_of_pct_and_atr(rules):
    # biên độ ±1% -> ATR ~ 2 -> cắt lỗ ATR = 100 - 2*2 = 96, gần hơn mức −7% (93)
    r = ev(flat(60), rules=rules)
    assert r.status == PositionStatus.SAFE
    assert 95.5 < r.stop_level < 96.5
    assert "ATR" in r.stop_basis


def test_stop_hit_when_price_below_stop_but_loss_under_7pct(rules):
    closes = flat(59) + [95.0]
    r = ev(closes, rules=rules)
    assert r.status == PositionStatus.STOP_HIT
    assert r.pnl_pct == pytest.approx(-5.0)
    assert any("bán toàn bộ" in a for a in r.actions)


def test_loss_of_7pct_or_more_is_trapped_not_stop_hit(rules):
    closes = flat(59) + [90.0]
    assert ev(closes, rules=rules).status == PositionStatus.TRAPPED


def test_trapped_group_b_has_no_stop_and_sells_half(rules):
    plan = PositionPlan(broker="t", account_id="a", symbol="AAA", has_thesis=False)
    r = ev(flat(59) + [90.0], plan=plan, rules=rules)
    assert r.stop_level is None
    assert "Nhóm B" in r.actions[0] and "50%" in r.actions[0]


def test_trapped_group_a_gets_new_stop_below_price(rules):
    plan = PositionPlan(broker="t", account_id="a", symbol="AAA", has_thesis=True)
    r = ev(flat(59) + [90.0], plan=plan, rules=rules)
    assert r.stop_level is not None and r.stop_level <= 90 * 0.90 + 1e-6
    assert "Nhóm A" in r.actions[0]


def test_trapped_unclassified_asks_for_classification(rules):
    r = ev(flat(59) + [88.0], rules=rules)
    assert r.status == PositionStatus.TRAPPED and "Phân loại" in r.actions[0]


def test_ladder_moves_stop_up_with_peak_gain(rules):
    closes = flat(40) + [101, 104, 108, 111, 112]
    r = ev(closes, rules=rules)
    assert abs(r.stop_level - 103.0) < 1e-6      # đã chạm +10%: khoá lãi +3%
    assert r.status == PositionStatus.TAKE_PROFIT
    assert any("25%" in a for a in r.actions)


def test_ladder_executed_by_plan_clears_take_profit(rules):
    plan = PositionPlan(broker="t", account_id="a", symbol="AAA", ladder_done=1)
    r = ev(flat(40) + [101, 104, 108, 111, 112], plan=plan, rules=rules)
    assert r.status == PositionStatus.SAFE


def test_stop_never_moves_down_after_pullback(rules):
    # đỉnh +12% rồi lùi về +4%: cắt lỗ vẫn ở mức khoá lãi +3% (không tụt về mức ban đầu)
    closes = flat(40) + [105, 110, 112, 108, 104]
    r = ev(closes, rules=rules)
    assert r.stop_level >= 103.0 - 1e-6


def test_peak_is_proxy_without_entry_date(rules):
    assert ev(flat(40) + [101, 102], rules=rules).peak_is_proxy is True
    plan = PositionPlan(broker="t", account_id="a", symbol="AAA", entry_date=make_candles(flat(40))[-5].t.date())
    assert ev(flat(40) + [101, 102], plan=plan, rules=rules).peak_is_proxy is False


def test_trailing_chandelier_after_25pct(rules):
    closes = flat(30) + list(np_linspace(100, 130, 20)) + [127.0]
    r = ev(closes, rules=rules)
    assert r.stop_level >= 115.0   # tối thiểu mức khoá lãi +15%
    assert "Chandelier" in r.stop_basis or "Khoá lãi" in r.stop_basis


def test_dca_mode_only_has_catastrophe_stop(rules):
    plan = PositionPlan(broker="t", account_id="a", symbol="AAA", mode="dca")
    r = ev(flat(59) + [88.0], plan=plan, rules=rules)
    assert r.status == PositionStatus.SAFE and abs(r.stop_level - 75.0) < 1e-6
    r2 = ev(flat(59) + [70.0], plan=plan, rules=rules)
    assert r2.status == PositionStatus.STOP_HIT


def test_time_stop_after_10_sessions_with_small_gain(rules):
    candles = make_candles(flat(60))
    plan = PositionPlan(broker="t", account_id="a", symbol="AAA", entry_date=candles[-12].t.date())
    pos = make_position(cost=100, price=101)
    r = evaluate_position(pos, to_frame(candles), plan, rules, NORMAL, pos.market_value)
    assert r.status == PositionStatus.TIME_STOP


def test_eight_week_rule_suspends_later_sell_steps(rules):
    candles = make_candles(flat(40) + [100, 108, 115, 122, 124, 125, 126, 127, 128, 129, 130])
    plan = PositionPlan(broker="t", account_id="a", symbol="AAA", entry_date=candles[-11].t.date())
    pos = make_position(cost=100, price=130)
    r = evaluate_position(pos, to_frame(candles), plan, rules, NORMAL, pos.market_value)
    assert "eight_week_hold" in r.flags
    sells = [s for s in r.ladder if s.sell_pct > 0]
    assert not sells[0].suspended and all(s.suspended for s in sells[1:])


def test_warning_when_below_sma20_and_weak_rsi(rules):
    closes = flat(40, 100) + [99, 98, 97, 96.5, 96, 96, 96.5, 96, 95.8, 95.6, 96, 96.2, 96.4, 96.5, 96.3]
    r = ev(closes, cost=100, rules=rules, price=96.3)
    assert r.indicators.rsi14 < 40
    assert r.status in (PositionStatus.WARNING, PositionStatus.STOP_HIT)


def test_weak_market_tightens_stop_to_5pct(rules):
    # biên độ ±5% -> ATR lớn, mức ATR rất thấp nên mức % quyết định: 93 (bình thường) và 95 (thị trường yếu)
    volatile = make_df(flat(60), spread=0.05)
    pos = make_position(cost=100, price=100)
    normal = evaluate_position(pos, volatile, None, rules, NORMAL, pos.market_value)
    weak = evaluate_position(pos, volatile, None, rules, WEAK, pos.market_value)
    assert normal.stop_level == pytest.approx(93.0)
    assert weak.stop_level == pytest.approx(95.0)


def test_weak_market_exit_when_profitable(rules):
    r = ev(flat(40) + [104, 108, 111], rules=rules, market=WEAK)
    assert r.status == PositionStatus.TAKE_PROFIT and "chốt toàn bộ" in r.actions[0]


def test_missing_data_returns_safe_with_flag(rules):
    pos = make_position()
    r = evaluate_position(pos, None, None, rules, NORMAL, 1)
    assert r.data_ok is False and "no_data" in r.flags


def test_market_state_three_levels(rules):
    up = make_df(list(np_linspace(100, 200, 260)))
    assert market_state(up, rules).state == MarketState.NORMAL
    pullback = make_df(list(np_linspace(100, 200, 230)) + list(np_linspace(200, 185, 30)))
    assert market_state(pullback, rules).state == MarketState.NO_NEW_BUYS
    crash = make_df(list(np_linspace(100, 200, 200)) + list(np_linspace(200, 90, 60)))
    assert market_state(crash, rules).state == MarketState.WEAK
    assert market_state(make_df(flat(50)), rules).state == MarketState.UNKNOWN


def np_linspace(a, b, n):
    import numpy as np
    return np.linspace(a, b, n)

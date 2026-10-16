"""Máy tính khối lượng mua theo luật 1,5% rủi ro (mục 1 của bộ luật): kiểm tra công thức bằng số tính tay."""
from __future__ import annotations

import pytest

from app.models import MarketInfo, MarketState, PositionEval, PositionStatus, Indicators
from app.risk.sizing import initial_stop, size_position, split_lots

NORMAL = MarketInfo(state=MarketState.NORMAL)


def plan(rules, *, price=40_000.0, capital=200_000_000.0, atr14=None, stop=None, market=NORMAL, n=2, held=None):
    return size_position(symbol="AAA", price=price, atr14=atr14, capital=capital, positions_count=n, held=held,
                         rules=rules, market=market, stop=stop)


def held_eval(qty=1000, cost=40_000.0, price=40_000.0, mode="swing") -> PositionEval:
    return PositionEval(symbol="AAA", quantity=qty, avg_cost=cost, price=price, market_value=qty * price, pnl=0, pnl_pct=0,
                        weight_pct=10, mode=mode, status=PositionStatus.SAFE, urgency=0, stop_level=None, stop_basis="",
                        distance_to_stop_pct=None, risk_to_stop_value=None, peak_gain_pct=0, peak_is_proxy=True,
                        indicators=Indicators(), ladder=[], actions=[], flags=[])


def codes(p):
    return {w.code for w in p.warnings}


def test_worked_example_from_trading_rules(rules):
    # docs/trading-rules.md mục 1: capital 200tr, risk 1,5% = 3tr, giá 40.000, cắt lỗ 37.000 (cách 3.000)
    p = plan(rules, stop=37_000)
    assert p.risk_money == pytest.approx(3_000_000) and p.stop_distance == pytest.approx(3_000)
    assert p.qty_by_risk == 1000 and p.qty_by_weight == 1000 and p.qty_plan == 1000
    assert p.plan_value == pytest.approx(40_000_000) and p.plan_weight_pct == pytest.approx(20.0)     # vừa chạm trần
    assert p.risk_at_stop == pytest.approx(3_000_000)
    assert p.allowed and p.warnings == []


def test_quantity_rounds_down_to_lot_of_100(rules):
    p = plan(rules, stop=37_200)                        # 3.000.000 / 2.800 = 1.071 cp → 1.000
    assert p.qty_by_risk == 1000
    p = plan(rules, stop=36_000, capital=100_000_000)   # 1.500.000 / 4.000 = 375 cp → 300
    assert p.qty_by_risk == 300 and p.qty_plan == 300 and p.qty_plan % 100 == 0


def test_max_weight_caps_the_plan(rules):
    # stop gần: 1.500.000 / 100 = 15.000 cp, nhưng tỷ trọng 20% × 100tr = 20tr / 10.000 = 2.000 cp
    p = plan(rules, price=10_000, stop=9_900, capital=100_000_000)
    assert p.qty_by_risk == 15_000 and p.qty_by_weight == 2_000 and p.qty_plan == 2_000 and p.binding == "weight"
    assert p.plan_weight_pct == pytest.approx(20.0) and "WEIGHT_CAP" in codes(p) and p.allowed
    assert p.risk_at_stop < p.risk_money                # chưa dùng hết 1,5% rủi ro


def test_capital_is_real_cash_only(rules):
    assert plan(rules, capital=0).qty_plan == 0 and "NO_CAPITAL" in codes(plan(rules, capital=0))
    assert not plan(rules, capital=-5).allowed and plan(rules, capital=-5).capital == 0


def test_capital_too_small_for_one_lot(rules):
    p = plan(rules, price=126_500, capital=12_300_000)
    assert p.qty_plan == 0 and "QTY_ZERO" in codes(p) and not p.allowed


def test_initial_stop_takes_the_nearer_of_pct_and_atr(rules):
    assert initial_stop(100, None, rules, NORMAL) == (pytest.approx(93), "Cắt lỗ ban đầu −7% giá vào")
    s, basis = initial_stop(100, 2, rules, NORMAL)                  # 2×ATR = 4 → 96, gần giá hơn 93
    assert s == pytest.approx(96) and basis == "Cắt lỗ 2×ATR14"
    assert initial_stop(100, 5, rules, NORMAL)[0] == pytest.approx(93)   # 2×ATR = 10 → 90, xa hơn
    assert initial_stop(100, None, rules, MarketInfo(state=MarketState.WEAK))[0] == pytest.approx(95)  # siết 5%


def test_stop_comes_from_rules_when_not_given(rules):
    p = plan(rules, price=100, capital=1_000_000, atr14=2)
    assert p.stop_price == pytest.approx(96) and p.stop_distance_pct == pytest.approx(4.0)
    assert p.qty_by_risk == 3_700 and p.qty_by_weight == 2_000     # 15.000 / 4 = 3.750 → 3.700; trần 200.000 / 100
    assert p.qty_plan == 2_000 and p.binding == "weight"


@pytest.mark.parametrize("bad_stop", [40_000, 41_000])
def test_stop_must_be_below_price(rules, bad_stop):
    with pytest.raises(ValueError):
        plan(rules, stop=bad_stop)
    with pytest.raises(ValueError):
        plan(rules, price=0)


@pytest.mark.parametrize("lots", [0, 1, 2, 3, 4, 5, 7, 10, 11, 23])
def test_split_lots_sums_to_plan(lots):
    out = split_lots(lots, [25, 25, 25, 25])
    assert sum(out) == lots and max(out) - min(out) <= 1 or lots < 4
    if lots:
        assert out[0] >= 1                              # đợt thăm dò luôn có ít nhất 1 lô


def test_split_lots_puts_remainder_on_later_tranches():
    assert split_lots(10, [25, 25, 25, 25]) == [2, 2, 3, 3]
    assert split_lots(3, [25, 25, 25, 25]) == [1, 1, 1, 0]
    assert split_lots(8, [25, 25, 25, 25]) == [2, 2, 2, 2]


def test_four_tranches_of_25_percent(rules):
    p = plan(rules, stop=37_000)                        # 10 lô
    assert [t.pct for t in p.tranches] == [25, 25, 25, 25]
    assert [t.quantity for t in p.tranches] == [200, 200, 300, 300] and sum(t.quantity for t in p.tranches) == p.qty_plan
    assert p.tranches[0].trigger_price == 40_000 and "VN-Index" in p.tranches[0].condition and "RSI14" in p.tranches[0].condition


def test_tranche_triggers_use_max_of_3pct_and_atr(rules):
    p = plan(rules, price=100, atr14=None, stop=90, capital=10_000_000)
    assert [round(t.trigger_price, 4) for t in p.tranches] == [100, 103, 106.09, 109.2727]     # +3% mỗi đợt
    p = plan(rules, price=100, atr14=4, stop=90, capital=10_000_000)                              # 1×ATR = 4 > 3%
    assert [t.trigger_price for t in p.tranches] == [100, 104, 108, 112]
    assert "103" not in p.tranches[1].condition and "104" in p.tranches[1].condition
    assert "đang lãi" in p.tranches[1].condition        # không mua đợt 2 nếu đợt 1 đang lỗ


def test_last_tranche_skipped_when_far_above_average(rules):
    near = plan(rules, price=100, atr14=None, stop=90, capital=10_000_000)
    assert not near.tranches[3].likely_skipped and "Bỏ qua nếu" in near.tranches[3].condition
    far = plan(rules, price=100, atr14=8, stop=80, capital=10_000_000)      # 100, 108, 116, 124: 124 > 108 × 1,10
    assert far.tranches[3].likely_skipped and "Dự kiến bỏ qua" in far.tranches[3].condition
    assert not any(t.likely_skipped for t in far.tranches[:3])


@pytest.mark.parametrize("state,code", [(MarketState.NO_NEW_BUYS, "MARKET_NO_NEW_BUYS"), (MarketState.WEAK, "MARKET_WEAK")])
def test_market_filter_blocks_new_swing_positions(rules, state, code):
    p = plan(rules, market=MarketInfo(state=state, index_symbol="VNINDEX"))
    assert code in codes(p) and not p.allowed
    assert next(w for w in p.warnings if w.code == code).severity == "block"
    assert p.qty_plan > 0                               # vẫn cho xem con số nếu luật cho phép


def test_unknown_market_is_only_informational(rules):
    p = plan(rules, market=MarketInfo(state=MarketState.UNKNOWN))
    assert "MARKET_UNKNOWN" in codes(p) and p.allowed


def test_max_positions_blocks_new_symbol_but_not_held_one(rules):
    assert rules.max_positions == 5
    blocked = plan(rules, n=5)
    assert "MAX_POSITIONS" in codes(blocked) and not blocked.allowed
    assert "MAX_POSITIONS" not in codes(plan(rules, n=4))
    holding = plan(rules, n=5, held=held_eval())
    assert "MAX_POSITIONS" not in codes(holding) and holding.allowed


def test_held_symbol_reports_additional_quantity(rules):
    p = plan(rules, stop=37_000, held=held_eval(qty=400), n=5)
    assert p.held_quantity == 400 and p.qty_plan == 1000 and p.additional_quantity == 600 and "ALREADY_HELD" in codes(p)
    assert plan(rules, stop=37_000, held=held_eval(qty=1500), n=5).additional_quantity == 0
    assert plan(rules, stop=37_000).additional_quantity == 1000


def test_no_averaging_down_on_a_losing_swing_position(rules):
    losing = plan(rules, held=held_eval(cost=45_000, price=40_000), n=5)
    assert "AVERAGING_DOWN" in codes(losing) and not losing.allowed
    assert "AVERAGING_DOWN" not in codes(plan(rules, held=held_eval(cost=35_000, price=40_000), n=5))
    assert "AVERAGING_DOWN" not in codes(plan(rules, held=held_eval(cost=45_000, price=40_000, mode="dca"), n=5))


def test_missing_atr_is_flagged(rules):
    assert "ATR_MISSING" in codes(plan(rules, atr14=None)) and "ATR_MISSING" not in codes(plan(rules, atr14=800))
    assert "ATR_MISSING" not in codes(plan(rules, atr14=None, stop=37_000))     # tự nhập cắt lỗ thì không cần ATR

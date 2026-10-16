"""Kịch bản giả định (stress test): kiểm tra công thức bằng số tính tay, không qua API."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.models import Loan, MarginBucket, ScenarioRequest, ScenarioSell
from app.risk.margin import bucket_metrics, drop_to_threshold, loan_interest_after_paydown, worst_bucket
from app.risk.scenario import ScenarioError, run_scenario
from .conftest import make_position

TODAY = date(2026, 10, 16)


def positions():
    # AAA: 1.000 cp, giá trị 100.000, vốn 120.000. BBB: 500 cp, giá trị 50.000, vốn 80.000
    return [make_position("AAA", qty=1000, cost=120.0, price=100.0), make_position("BBB", qty=500, cost=80.0, price=100.0)]


def bucket(mv=150_000.0, debt=75_000.0, symbols=("AAA", "BBB"), id="b", maintenance=40, liquidation=35):
    return MarginBucket(id=id, scope="account", label=f"Nhóm {id}", symbols=list(symbols), ratio_pct=(mv - debt) / mv * 100,
                        initial_pct=50, maintenance_pct=maintenance, liquidation_pct=liquidation, market_value=mv, debt=debt)


LOANS = [Loan(id="L1", principal=40_000, remaining_principal=40_000, annual_rate_pct=10.0, due_date=TODAY + timedelta(days=30)),
         Loan(id="L2", principal=35_000, remaining_principal=35_000, annual_rate_pct=12.0, due_date=TODAY + timedelta(days=10))]


def run(rules, req=None, *, buckets=None, pos=None, cash=10_000.0, debt=75_000.0, loans=LOANS, **kw):
    req = req or ScenarioRequest(**kw)
    return run_scenario(req, pos or positions(), cash, debt, buckets if buckets is not None else [bucket()], loans, rules)


def test_no_change_scenario_is_identity(rules):
    r = run(rules)
    assert r.after.positions_value == r.before.positions_value == 150_000
    assert r.after.buckets[0].bucket.ratio_pct == pytest.approx(r.before.buckets[0].bucket.ratio_pct)
    assert r.after.nav == r.before.nav and r.after.interest_per_day == pytest.approx(r.before.interest_per_day)
    assert r.realized_pnl == 0 and r.debt_repaid == 0 and r.warnings == []


def test_market_drop_matches_margin_formula(rules):
    # r = 50%, giảm 10%: r' = 1 − (1 − r)/(1 − x) = 1 − 0.5/0.9 = 44,44%
    r = run(rules, market_drop_pct=10)
    assert r.after.positions_value == pytest.approx(135_000)
    assert r.after.buckets[0].bucket.ratio_pct == pytest.approx(44.444, abs=0.001)
    assert r.after.buckets[0].bucket.ratio_pct == pytest.approx((1 - 0.5 / 0.9) * 100)
    assert r.after.nav == pytest.approx(135_000 + 10_000 - 75_000)
    assert r.after.unrealized_pnl == pytest.approx(135_000 - (120_000 + 40_000))       # −25.000
    assert r.before.unrealized_pnl == pytest.approx(150_000 - 160_000)                  # −10.000


def test_drop_to_threshold_lands_exactly_on_maintenance(rules):
    x = drop_to_threshold(50, 40)                  # 16,67%
    m = run(rules, market_drop_pct=x).after.buckets[0]
    assert m.bucket.ratio_pct == pytest.approx(40.0, abs=1e-6)
    assert m.drop_to_maintenance_pct == pytest.approx(0, abs=1e-6)


def test_big_drop_warns_and_needs_cash(rules):
    r = run(rules, market_drop_pct=30)             # r' = 1 − 0,5/0,7 = 28,6% < 35% giải chấp
    m = r.after.buckets[0]
    assert m.zone == "breach" and m.cash_to_safe > 0
    assert r.after.cash_needed == pytest.approx(m.cash_to_safe)
    assert any("giải chấp" in w for w in r.warnings)
    assert r.before.cash_needed == pytest.approx(bucket_metrics(bucket(), rules).cash_to_safe)


def test_sell_repays_debt_at_stressed_price_and_realizes_pnl(rules):
    r = run(rules, market_drop_pct=10, sell=[ScenarioSell(symbol="AAA", quantity=400)])
    assert r.sale_proceeds == pytest.approx(400 * 90)                 # 36.000 sau khi giảm 10%
    assert r.realized_pnl == pytest.approx(400 * (90 - 120))          # −12.000 so với giá vốn
    assert r.debt_repaid == pytest.approx(36_000) and r.after.debt == pytest.approx(39_000)
    b = r.after.buckets[0].bucket
    assert b.market_value == pytest.approx(135_000 - 36_000) and b.debt == pytest.approx(39_000)
    assert b.ratio_pct == pytest.approx((99_000 - 39_000) / 99_000 * 100)
    assert r.after.unrealized_pnl == pytest.approx(99_000 - (600 * 120 + 500 * 80))
    assert r.after.nav == pytest.approx(99_000 + 10_000 - 39_000)


def test_selling_improves_rtt_when_ratio_below_one(rules):
    base = run(rules, market_drop_pct=10).after.buckets[0].bucket.ratio_pct
    sold = run(rules, market_drop_pct=10, sell=[ScenarioSell(symbol="BBB", quantity=500)]).after.buckets[0].bucket.ratio_pct
    assert sold > base


def test_interest_falls_paying_highest_rate_first():
    # trả 35.000: hết khoản 12% (L2), L1 giữ nguyên: 40.000 × 10% / 365
    assert loan_interest_after_paydown(LOANS, 35_000) == pytest.approx(40_000 * 0.10 / 365)
    assert loan_interest_after_paydown(LOANS, 0) == pytest.approx((40_000 * 0.10 + 35_000 * 0.12) / 365)
    assert loan_interest_after_paydown(LOANS, 1e12) == 0
    assert loan_interest_after_paydown(LOANS, -5) == loan_interest_after_paydown(LOANS, 0)


def test_scenario_interest_after_sell_and_cash(rules):
    r = run(rules, sell=[ScenarioSell(symbol="BBB", quantity=500)], add_cash=0)     # thu 50.000, trả hết L2 và 15.000 của L1
    assert r.after.interest_per_day == pytest.approx(25_000 * 0.10 / 365)
    r2 = run(rules, add_cash=75_000)
    assert r2.after.interest_per_day == 0 and r2.after.debt == 0


def test_add_cash_reaches_safe_target(rules):
    need = bucket_metrics(bucket(mv=150_000, debt=88_000), rules).cash_to_safe           # RTT 41,3% → mục tiêu 50%
    r = run(rules, buckets=[bucket(debt=88_000)], debt=88_000, add_cash=need)
    m = r.after.buckets[0]
    assert m.bucket.ratio_pct == pytest.approx(50.0) and m.cash_to_safe == pytest.approx(0, abs=1e-6) and m.zone == "watch"
    assert r.after.cash_needed == pytest.approx(0, abs=1e-6)
    half = run(rules, buckets=[bucket(debt=88_000)], debt=88_000, add_cash=need / 2)
    assert half.after.cash_needed == pytest.approx(need / 2)           # "tiền còn cần nộp"


def test_cash_beyond_debt_becomes_cash_balance(rules):
    r = run(rules, add_cash=100_000)
    assert r.debt_repaid == 75_000 and r.after.debt == 0 and r.after.cash == pytest.approx(10_000 + 25_000)
    assert r.after.buckets[0].bucket.ratio_pct == pytest.approx(100.0)
    assert r.after.nav == pytest.approx(150_000 + 35_000)               # NAV tăng đúng bằng tiền nộp thêm
    assert any("tiền mặt" in w for w in r.warnings)


def test_sell_everything_leaves_no_bucket_ratio(rules):
    r = run(rules, sell=[ScenarioSell(symbol="AAA", quantity=1000), ScenarioSell(symbol="BBB", quantity=500)])
    assert r.after.positions_value == 0 and r.after.debt == 0 and r.after.cash == pytest.approx(10_000 + 75_000)
    assert r.after.buckets[0].zone == "unknown" and r.after.focus_bucket_id is None and r.after.cash_needed == 0


def test_sell_everything_with_debt_left_warns(rules):
    r = run(rules, market_drop_pct=60, sell=[ScenarioSell(symbol="AAA", quantity=1000), ScenarioSell(symbol="BBB", quantity=500)])
    assert r.after.debt == pytest.approx(75_000 - 60_000)
    assert any("còn nợ" in w for w in r.warnings)


def test_duplicate_sell_rows_are_merged(rules):
    r = run(rules, sell=[ScenarioSell(symbol="aaa", quantity=100), ScenarioSell(symbol="AAA", quantity=200)])
    assert [(s.symbol, s.quantity) for s in r.request.sell] == [("AAA", 300)]
    assert r.sale_proceeds == pytest.approx(30_000)


@pytest.mark.parametrize("sell,msg", [([("ZZZ", 100)], "không có trong danh mục"), ([("AAA", 1001)], "Chỉ đang giữ"),
                                      ([("AAA", 600), ("AAA", 600)], "Chỉ đang giữ")])
def test_invalid_sells_are_rejected(rules, sell, msg):
    with pytest.raises(ScenarioError, match=msg):
        run(rules, sell=[ScenarioSell(symbol=s, quantity=q) for s, q in sell])


def test_request_validation():
    for bad in ({"market_drop_pct": -5}, {"market_drop_pct": 120}, {"add_cash": -1}, {"sell": [{"symbol": "A", "quantity": 0}]}):
        with pytest.raises(ValueError):
            ScenarioRequest(**bad)


def test_deal_buckets_get_their_own_symbols_and_cash_goes_to_neediest(rules):
    # DNSE: mỗi Deal một nhóm. AAA ở nhóm yếu (RTT 41%), BBB ở nhóm khoẻ (RTT 70%)
    weak = bucket(mv=100_000, debt=59_000, symbols=("AAA",), id="weak")
    strong = bucket(mv=50_000, debt=15_000, symbols=("BBB",), id="strong")
    r = run(rules, buckets=[strong, weak], debt=74_000, sell=[ScenarioSell(symbol="BBB", quantity=100)], add_cash=5_000)
    a = {m.bucket.id: m for m in r.after.buckets}
    assert a["strong"].bucket.market_value == pytest.approx(40_000) and a["strong"].bucket.debt == pytest.approx(5_000)
    assert a["weak"].bucket.market_value == pytest.approx(100_000)       # bán BBB không đụng nhóm của AAA
    assert a["weak"].bucket.debt == pytest.approx(59_000 - 5_000)        # tiền nộp dồn vào nhóm cần nhiều nhất
    assert r.before.focus_bucket_id == "weak"


def test_symbol_without_bucket_goes_to_largest_bucket(rules):
    b = bucket(symbols=())                                               # TCBS có thể không liệt kê mã
    r = run(rules, buckets=[b], sell=[ScenarioSell(symbol="AAA", quantity=1000)])
    assert r.after.buckets[0].bucket.market_value == pytest.approx(50_000)


def test_buckets_without_ratio_stay_unknown_and_totals_still_work(rules):
    b = MarginBucket(id="x", scope="account", label="x")
    r = run(rules, buckets=[b], market_drop_pct=10)
    assert r.after.buckets[0].zone == "unknown" and r.after.positions_value == pytest.approx(135_000)


def test_no_margin_account(rules):
    r = run(rules, buckets=[], loans=[], debt=0.0, market_drop_pct=10, sell=[ScenarioSell(symbol="AAA", quantity=100)])
    assert r.after.buckets == [] and r.after.focus_bucket_id is None and r.after.debt == 0
    assert r.after.cash == pytest.approx(10_000 + 9_000)


def test_worst_bucket_orders_by_zone_then_distance(rules):
    ms = [bucket_metrics(bucket(mv=100, debt=d, id=str(d)), rules) for d in (30, 58, 50, 70)]   # RTT 70, 42, 50, 30
    assert worst_bucket(ms).bucket.id == "70"                                 # RTT 30% dưới giải chấp
    assert worst_bucket(ms[:3]).bucket.id == "58"
    assert worst_bucket([bucket_metrics(MarginBucket(id="u", scope="account", label="u"), rules)]) is None

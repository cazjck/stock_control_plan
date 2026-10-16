from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.models import AlertSeverity, Loan, MarginBucket
from app.risk.alerts import build_candidates
from app.risk.margin import asset_overview, bucket_metrics, drop_to_threshold, margin_overview
from .conftest import make_position


def bucket(ratio, mv=100_000_000, m=40, l=35):
    return MarginBucket(id="b", scope="account", label="TK", ratio_pct=ratio, initial_pct=50,
                        maintenance_pct=m, liquidation_pct=l, market_value=mv, debt=mv * (1 - ratio / 100))


def test_drop_to_threshold_formula():
    # r=50%, m=40%: x = 1 - 0.5/0.6 = 16.67%
    assert drop_to_threshold(50, 40) == pytest.approx(16.667, abs=0.01)
    assert drop_to_threshold(40, 40) == 0 and drop_to_threshold(30, 40) == 0
    assert drop_to_threshold(100, 40) == pytest.approx(100.0)


def test_drop_formula_is_consistent_with_price_move():
    # sau khi giảm đúng x% thì tỷ lệ phải bằng ngưỡng
    r, m = 0.55, 0.40
    x = drop_to_threshold(55, 40) / 100
    V, D = 100.0, 100.0 * (1 - r)
    assert (V * (1 - x) - D) / (V * (1 - x)) == pytest.approx(m, abs=1e-9)


def test_cash_to_safe_reaches_target(rules):
    m = bucket_metrics(bucket(44.0), rules)          # target = 40 + 10 = 50
    assert m.cash_to_safe == pytest.approx(6_000_000)
    assert bucket_metrics(bucket(60.0), rules).cash_to_safe == 0


@pytest.mark.parametrize("ratio,zone", [(70, "safe"), (48, "watch"), (38, "danger"), (34, "breach")])
def test_zones(rules, ratio, zone):
    assert bucket_metrics(bucket(ratio), rules).zone == zone


def test_unknown_when_missing(rules):
    b = MarginBucket(id="x", scope="account", label="x")
    assert bucket_metrics(b, rules).zone == "unknown"


def test_interest_and_maturity(rules):
    today = date(2026, 10, 16)
    loans = [Loan(id="1", due_date=today + timedelta(days=3), remaining_principal=365_000_000, accrued_interest=1,
                  annual_rate_pct=10.0),
             Loan(id="2", due_date=today + timedelta(days=20), remaining_principal=100, accrued_interest=0),
             Loan(id="3", due_date=today - timedelta(days=2), remaining_principal=50, accrued_interest=0)]
    mo = margin_overview([], loans, rules, today)
    assert mo.interest_per_day == pytest.approx(100_000)         # 365tr × 10% / 365
    by = {m.label: m for m in mo.maturity}
    assert by["Trong 7 ngày"].count == 1 and by["15–30 ngày"].count == 1 and by["Quá hạn"].count == 1


def test_asset_overview_nav():
    p = make_position(qty=100, cost=10, price=12)
    a = asset_overview([p], cash=500, debt=300, interest_per_day=1)
    assert a.nav == 1200 + 500 - 300 and a.unrealized_pnl == 200


def test_alerts_for_rtt_loans_and_loss(rules):
    today = date(2026, 10, 16)
    loans = [Loan(id="L1", due_date=today + timedelta(days=1), remaining_principal=10, accrued_interest=0, annual_rate_pct=12),
             Loan(id="L2", due_date=today + timedelta(days=6), remaining_principal=10, accrued_interest=0, annual_rate_pct=12),
             Loan(id="L3", due_date=today + timedelta(days=30), remaining_principal=10, accrued_interest=0, annual_rate_pct=12)]
    mo = margin_overview([bucket(38.0)], loans, rules, today)
    assets = asset_overview([make_position(qty=100, cost=100, price=80)], cash=0, debt=0, interest_per_day=0)
    c = {a.key: a for a in build_candidates([], assets, mo, rules, today)}
    assert c["RTT:b"].severity == AlertSeverity.CRITICAL
    assert c["LOAN:L1:1"].severity == AlertSeverity.CRITICAL
    assert c["LOAN:L2:7"].severity == AlertSeverity.WARNING
    assert not any(k.startswith("LOAN:L3") for k in c)
    assert c["LOSS:portfolio"].severity == AlertSeverity.CRITICAL   # lỗ 20% NAV > 10%


def coverage_bucket(rtt=88.2, debt=315_400_000.0):
    return MarginBucket(id="t", scope="account", label="TCBS", ratio_kind="collateral_over_debt", ratio_pct=rtt,
                        initial_pct=100, maintenance_pct=85, liquidation_pct=80, market_value=520.8e6, debt=debt)


def test_collateral_over_debt_drop_formula():
    # tài sản đảm bảo giảm x% thì RTT giảm x%: x = 1 - m/r
    assert drop_to_threshold(88.2, 85, "collateral_over_debt") == pytest.approx(3.628, abs=0.001)
    assert drop_to_threshold(88.2, 80, "collateral_over_debt") == pytest.approx(9.30, abs=0.01)
    assert drop_to_threshold(84, 85, "collateral_over_debt") == 0
    # kiểm chứng ngược: sau khi giảm đúng x% thì RTT bằng ngưỡng
    x = drop_to_threshold(88.2, 85, "collateral_over_debt") / 100
    assert 88.2 * (1 - x) == pytest.approx(85)


def test_collateral_over_debt_cash_to_safe(rules):
    m = bucket_metrics(coverage_bucket(), rules)         # mục tiêu = 85 + 10 = 95
    assert m.safe_target_pct == 95
    expected = 315_400_000 * (1 - 88.2 / 95)
    assert m.cash_to_safe == pytest.approx(expected)
    # trả đúng số đó thì RTT đạt mục tiêu: RTT = r*D/(D-Δ)
    d = 315_400_000
    assert 88.2 * d / (d - m.cash_to_safe) == pytest.approx(95)
    assert m.zone == "watch" and m.drop_to_maintenance_pct == pytest.approx(3.628, abs=0.001)


def test_collateral_zones(rules):
    assert bucket_metrics(coverage_bucket(79), rules).zone == "breach"
    assert bucket_metrics(coverage_bucket(84), rules).zone == "danger"
    assert bucket_metrics(coverage_bucket(120), rules).zone == "safe"
    assert bucket_metrics(coverage_bucket(120), rules).cash_to_safe == 0


def test_loan_stats(rules):
    from app.risk.margin import loan_detail, loan_stats
    today = date(2026, 10, 16)
    loans = [
        Loan(id="a", source="SSI", principal=200, remaining_principal=100, accrued_interest=5, annual_rate_pct=10,
             disbursement_date=today - timedelta(days=100), due_date=today + timedelta(days=36)),
        Loan(id="b", source="TCBS", principal=300, remaining_principal=300, accrued_interest=7, annual_rate_pct=14,
             disbursement_date=today - timedelta(days=20), due_date=today + timedelta(days=73)),
        Loan(id="c", source="SSI", principal=50, remaining_principal=50, accrued_interest=0, annual_rate_pct=None),
    ]
    d = [loan_detail(l, today) for l in loans]
    assert d[0].days_borrowed == 100 and d[0].days_to_due == 36
    assert d[0].interest_to_maturity == pytest.approx(100 * 0.10 / 365 * 36)
    s = loan_stats(d)
    assert s.principal_disbursed == 550 and s.principal_paid == 100 and s.principal_remaining == 450
    assert s.accrued_interest == 12 and s.payoff_today == 462
    assert s.interest_per_day == pytest.approx(100 * 0.10 / 365 + 300 * 0.14 / 365)
    assert s.avg_rate_pct == pytest.approx((100 * 10 + 300 * 14) / 400)    # khoản không có lãi suất bị loại khỏi bình quân
    assert s.loans_without_due_date == 1 and s.next_due_date == today + timedelta(days=36) and s.next_due_amount == 105
    assert s.avg_days_borrowed == pytest.approx((100 * 100 + 300 * 20) / 400)
    mo = margin_overview([], loans, rules, today)
    assert [x.source for x in mo.stats_by_source] == ["SSI", "TCBS"] and mo.stats.count == 3


def test_breakeven_and_interest_vs_nav_in_api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.config import get_settings
    monkeypatch.setenv("DATA_DIR", str(tmp_path)); monkeypatch.setenv("BROKERS", "demo")
    monkeypatch.delenv("APP_ACCESS_TOKEN", raising=False)
    get_settings.cache_clear()
    from app.main import create_app
    with TestClient(create_app()) as c:
        m = c.get("/api/margin").json()
        o = c.get("/api/overview").json()["assets"]
    get_settings.cache_clear()
    assert m["breakeven_monthly_pct"] == pytest.approx(m["interest_30d"] / o["positions_value"] * 100)
    assert m["interest_pct_nav_monthly"] == pytest.approx(m["interest_30d"] / o["nav"] * 100)
    assert m["stats"]["payoff_today"] == pytest.approx(m["stats"]["principal_remaining"] + m["stats"]["accrued_interest"])
    assert all("days_to_due" in l for l in m["loans"])


def test_scenario_keeps_tcbs_rtt_definition(rules):
    """RTT TCBS sau kịch bản phải là tài sản đảm bảo / dư nợ, không phải (giá trị − nợ) / giá trị."""
    from app.models import ScenarioRequest
    from app.risk.scenario import run_scenario
    from .conftest import make_position
    pos = make_position(symbol="PDR", qty=46_500, cost=21_400, price=11_200)
    b = MarginBucket(id="t", scope="account", label="TCBS", ratio_kind="collateral_over_debt", ratio_pct=88.2,
                     initial_pct=100, maintenance_pct=85, liquidation_pct=80, market_value=pos.market_value,
                     debt=315_400_000, symbols=["PDR"])
    same = run_scenario(ScenarioRequest(), [pos], 0, b.debt, [b], [], rules)
    assert same.after.buckets[0].bucket.ratio_pct == pytest.approx(88.2)
    assert same.after.buckets[0].zone == "watch"
    drop = run_scenario(ScenarioRequest(market_drop_pct=10), [pos], 0, b.debt, [b], [], rules)
    assert drop.after.buckets[0].bucket.ratio_pct == pytest.approx(88.2 * 0.9)
    cash = drop.before.buckets[0].cash_to_safe
    fixed = run_scenario(ScenarioRequest(add_cash=cash), [pos], 0, b.debt, [b], [], rules)
    assert fixed.after.buckets[0].bucket.ratio_pct == pytest.approx(95, abs=0.01)   # duy trì 85 + biên 10
    sold = run_scenario(ScenarioRequest(sell=[{"symbol": "PDR", "quantity": 10_000}]), [pos], 0, b.debt, [b], [], rules)
    c = 0.882 * 315_400_000 / pos.market_value
    assert sold.after.buckets[0].bucket.ratio_pct == pytest.approx(c * 36_500 * 11_200 / (315_400_000 - 112_000_000) * 100)

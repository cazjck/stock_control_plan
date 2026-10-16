"""Kế hoạch hạ margin (mục 5b): thứ tự bán theo luật, vừa đủ về vùng an toàn, rồi hết nợ."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.models import (
    Indicators, LotEval, Loan, MarginBucket, PositionEval, PositionPlan, PositionStatus,
)
from app.risk.deleverage import build_overview, build_plan, ratio_for
from app.risk.margin import bucket_metrics

TODAY = date(2026, 10, 16)


def ev(symbol, qty, price, cost, *, acc="ssi", status=PositionStatus.TRAPPED, thesis=None, lots=(), urgency=90):
    mv = qty * price
    return PositionEval(
        row_id=f"{acc}:{symbol}", account_id=acc, symbol=symbol, quantity=qty, avg_cost=cost, price=price, market_value=mv,
        pnl=mv - qty * cost, pnl_pct=(price / cost - 1) * 100, weight_pct=0, mode="swing", status=status, urgency=urgency,
        stop_level=None, stop_basis="", distance_to_stop_pct=None, risk_to_stop_value=None, peak_gain_pct=0,
        peak_is_proxy=True, indicators=Indicators(), ladder=[], actions=[], flags=[],
        plan=PositionPlan(broker="ledger", account_id=acc, symbol=symbol, has_thesis=thesis) if thesis is not None else None,
        lots=[LotEval.model_construct(rule_status="stop", remaining=q) for q in lots])


def equity_bucket(value, debt, acc="ssi", maint=35.0):
    return MarginBucket(id=acc, scope="account", label=acc.upper(), source=acc.upper(), ratio_kind="equity_over_value",
                        ratio_pct=(value - debt) / value * 100, maintenance_pct=maint, liquidation_pct=25,
                        market_value=value, debt=debt)


def loan(amount, rate=13.5, days=60, source="SSI"):
    return Loan(id=f"L{amount}", source=source, remaining_principal=amount, annual_rate_pct=rate,
                due_date=TODAY + timedelta(days=days))


def test_ratio_for_both_kinds():
    assert ratio_for("equity_over_value", None, 0, 0, 1000, 600) == pytest.approx(40)
    assert ratio_for("collateral_over_debt", 88.2, 520.8e6, 315.4e6, 520.8e6, 315.4e6) == pytest.approx(88.2)
    assert ratio_for("collateral_over_debt", 88.2, 520.8e6, 315.4e6, 520.8e6 * 0.9, 315.4e6) == pytest.approx(88.2 * 0.9)
    assert ratio_for("equity_over_value", None, 0, 0, 1000, 0) is None       # hết nợ


def test_worst_loss_sells_just_enough_to_reach_target(rules):
    dxg = ev("DXG", 64_000, 10_000, 17_200)
    b = equity_bucket(640e6, 402e6)
    p = build_plan(bucket_metrics(b, rules), [dxg], [loan(402e6)], rules, TODAY)
    assert p.zone == "watch" and p.target_pct == 45
    [s] = p.safe_steps
    assert s.kind == "worst_loss" and s.quantity % 100 == 0 and s.reaches_target
    assert s.ratio_after >= 45
    less = s.quantity - 100      # ít hơn 100 cổ phiếu thì chưa đủ
    k = 1 - rules.margin.sell_cost_pct / 100
    v, d = 640e6 - less * 10_000, 402e6 - less * 10_000 * k
    assert (v - d) / v * 100 < 45
    assert p.safe_interest_after < p.interest_per_day
    assert p.zero_steps and p.zero_steps[-1].debt_after == 0 and p.zero_shortfall == 0


def test_rule_sells_come_first_in_order(rules):
    a = ev("AAA", 10_000, 10_000, 20_000, lots=[2_000], urgency=120)
    b_ = ev("BBB", 10_000, 10_000, 12_000, thesis=False, urgency=90)
    c = ev("CCC", 10_000, 10_000, 30_000, status=PositionStatus.STOP_HIT, urgency=100)
    bucket = equity_bucket(300e6, 250e6, maint=10)
    p = build_plan(bucket_metrics(bucket, rules), [a, b_, c], [loan(250e6)], rules, TODAY)
    kinds = [(s.kind, s.symbol, s.quantity) for s in p.safe_steps]
    assert kinds[:3] == [("lot_rule", "AAA", 2_000), ("stop", "CCC", 10_000), ("group_b", "BBB", 5_000)]


def test_safe_account_lists_only_rule_sells(rules):
    x = ev("XXX", 10_000, 10_000, 9_000, status=PositionStatus.SAFE)
    b = equity_bucket(100e6, 10e6)
    p = build_plan(bucket_metrics(b, rules), [x], [loan(10e6)], rules, TODAY)
    assert p.zone == "safe" and p.safe_steps == [] and p.safe_reached
    assert "Đang an toàn" in p.headline and p.zero_steps[0].quantity == 1_100   # 10 triệu / (10.000 × 0,9975) làm tròn lên lô 100


def test_tcbs_collateral_kind_and_cash_alternative(rules):
    pdr = ev("PDR", 46_500, 11_200, 21_400, acc="tcbs")
    b = MarginBucket(id="tcbs", scope="account", label="TCBS", source="TCBS", ratio_kind="collateral_over_debt",
                     ratio_pct=88.2, maintenance_pct=85, liquidation_pct=80, market_value=46_500 * 11_200,
                     debt=315_400_000)
    m = bucket_metrics(b, rules)
    p = build_plan(m, [pdr], [loan(257_678_280, source="TCBS")], rules, TODAY)
    [s] = p.safe_steps
    assert 95 <= s.ratio_after < 95.5 and s.quantity == 4_700
    assert p.cash_alternative == pytest.approx(m.cash_to_safe)


def test_selling_everything_not_enough_needs_cash(rules):
    x = ev("XXX", 1_000, 10_000, 50_000)
    b = equity_bucket(10e6, 12e6)                     # nợ lớn hơn giá trị cổ phiếu
    p = build_plan(bucket_metrics(b, rules), [x], [loan(12e6)], rules, TODAY)
    assert not p.safe_reached
    assert p.zero_shortfall == pytest.approx(12e6 - 10e6 * (1 - rules.margin.sell_cost_pct / 100))
    assert any("nộp thêm tiền" in n for n in p.notes) and any("còn nợ" in n for n in p.notes)


def test_loans_due_within_30_days_and_overview_by_source(rules):
    dxg = ev("DXG", 64_000, 10_000, 17_200)
    pdr = ev("PDR", 25_800, 11_200, 14_700, acc="vps")
    ms = [bucket_metrics(equity_bucket(640e6, 402e6), rules), bucket_metrics(equity_bucket(306.9e6, 190e6, acc="vps", maint=30), rules)]
    loans = [loan(10e6, days=24), loan(392e6, days=40), loan(190e6, rate=14.19, source="VPS")]
    o = build_overview(ms, [dxg, pdr], loans, rules, TODAY)
    ssi = next(p for p in o.plans if p.bucket_id == "ssi")
    assert ssi.due_30d_count == 1 and ssi.due_30d_amount == 10e6 and ssi.due_30d_first == TODAY + timedelta(days=24)
    assert o.plans[0].bucket_id == "ssi"                           # tài khoản nguy hiểm hơn lên trước
    assert o.total_debt == pytest.approx(592e6) and o.interest_after_safe < o.interest_per_day
    vps = next(p for p in o.plans if p.bucket_id == "vps")
    assert vps.interest_per_day == pytest.approx(190e6 * 0.1419 / 365)    # khoản vay theo đúng công ty

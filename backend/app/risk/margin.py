"""Tính toán margin: khoảng cách tới call margin, tiền cần nộp, lãi mỗi ngày, lịch đáo hạn.

Có hai cách đo tỷ lệ (MarginBucket.ratio_kind). Giả định cả danh mục giảm x% cùng lúc.

1) equity_over_value (DNSE): r = (giá trị tài sản − nợ) / giá trị tài sản
     r' = 1 − (1 − r) / (1 − x)        =>  x = 1 − (1 − r) / (1 − m)
     tiền cần nộp để về mức mục tiêu t:  C = (t − r) × V

2) collateral_over_debt (RTT của TCBS): r = tài sản đảm bảo / dư nợ, tài sản đảm bảo tỷ lệ với giá
     r' = r × (1 − x)                  =>  x = 1 − m / r
     trả bớt nợ ΔD để đạt t:  r × D / (D − ΔD) = t  =>  ΔD = D × (1 − r / t)
"""
from __future__ import annotations

from datetime import date

from ..models import (
    AssetOverview, Loan, LoanDetail, LoanStats, MarginBucket, MarginMetrics, MarginOverview, MaturityBucket, Position,
)
from .rules import Rules


def drop_to_threshold(ratio_pct: float, threshold_pct: float, kind: str = "equity_over_value") -> float:
    if kind == "collateral_over_debt":
        if ratio_pct <= threshold_pct or ratio_pct <= 0:
            return 0.0
        return max(0.0, min(100.0, (1 - threshold_pct / ratio_pct) * 100))
    r, m = ratio_pct / 100, threshold_pct / 100
    if r <= m:
        return 0.0
    if m >= 1:
        return 0.0
    return max(0.0, min(100.0, (1 - (1 - r) / (1 - m)) * 100))


def trigger_price(kind: str, ratio_pct: float | None, value: float, debt: float, row_value: float, qty: int,
                  threshold_pct: float | None) -> float | None:
    """Giá của MỘT mã mà tại đó tỷ lệ ký quỹ cả tài khoản chạm ngưỡng, giả định các mã khác đứng giá.

    equity_over_value: (V' − D) / V' = m  =>  V' = D / (1 − m)
    collateral_over_debt (RTT TCBS): tài sản đảm bảo tỷ lệ với giá trị, c = r × D / V  =>  c × V' / D = m  =>  V' = V × m / r
    Giá = (V' − giá trị các mã khác) / số lượng. Không có nghĩa (≤ 0) thì trả None: mã này một mình không kéo tài khoản tới ngưỡng."""
    if threshold_pct is None or qty <= 0 or debt <= 0 or value <= 0:
        return None
    other = value - row_value
    if kind == "collateral_over_debt":
        if not ratio_pct or ratio_pct <= 0:
            return None
        target_value = value * threshold_pct / ratio_pct
    else:
        m = threshold_pct / 100
        if m >= 1:
            return None
        target_value = debt / (1 - m)
    p = (target_value - other) / qty
    return p if p > 0 else None


def bucket_metrics(b: MarginBucket, rules: Rules) -> MarginMetrics:
    buf = rules.margin.rtt_buffer_pct_points
    warn = rules.alerts.rtt_warn_points
    if b.ratio_pct is None or b.maintenance_pct is None:
        return MarginMetrics(bucket=b, drop_to_maintenance_pct=None, drop_to_liquidation_pct=None,
                             cash_to_safe=None, safe_target_pct=None, zone="unknown")
    k = b.ratio_kind
    d_m = drop_to_threshold(b.ratio_pct, b.maintenance_pct, k)
    d_l = drop_to_threshold(b.ratio_pct, b.liquidation_pct, k) if b.liquidation_pct is not None else None
    target = b.maintenance_pct + buf
    if k == "collateral_over_debt":
        cash = max(0.0, b.debt * (1 - b.ratio_pct / target)) if b.debt and target > 0 else None
    else:
        cash = max(0.0, (target - b.ratio_pct) / 100 * (b.market_value or 0.0)) if b.market_value else None
    if b.liquidation_pct is not None and b.ratio_pct <= b.liquidation_pct:
        zone = "breach"
    elif b.ratio_pct <= b.maintenance_pct:
        zone = "danger"
    elif b.ratio_pct <= b.maintenance_pct + max(buf, warn):
        zone = "watch"
    else:
        zone = "safe"
    return MarginMetrics(bucket=b, drop_to_maintenance_pct=d_m, drop_to_liquidation_pct=d_l,
                         cash_to_safe=cash, safe_target_pct=target, zone=zone)


def loan_interest_per_day(loans: list[Loan]) -> float:
    return sum(l.remaining_principal * (l.annual_rate_pct or 0.0) / 100 / 365 for l in loans)


def loan_interest_after_paydown(loans: list[Loan], amount: float) -> float:
    """Lãi mỗi ngày sau khi trả bớt `amount` nợ gốc. Giả định trả khoản có lãi suất cao nhất trước,
    cùng lãi suất thì trả khoản đáo hạn sớm trước. Phần vượt tổng nợ gốc bị bỏ qua."""
    left = max(0.0, amount)
    total = 0.0
    for l in sorted(loans, key=lambda l: (-(l.annual_rate_pct or 0.0), l.due_date or date.max)):
        paid = min(left, l.remaining_principal)
        left -= paid
        total += (l.remaining_principal - paid) * (l.annual_rate_pct or 0.0) / 100 / 365
    return total


_ZONE_RANK = {"breach": 0, "danger": 1, "watch": 2, "safe": 3}


def worst_bucket(metrics: list[MarginMetrics]) -> MarginMetrics | None:
    """Nhóm sát ngưỡng nhất: ưu tiên vùng nguy hiểm, rồi khoảng cách tới ngưỡng duy trì nhỏ nhất.
    Bỏ qua nhóm chưa có tỷ lệ. Cùng quy tắc với worstBucket trong frontend/src/lib/verdict.ts."""
    known = [m for m in metrics if m.zone in _ZONE_RANK]
    return min(known, key=lambda m: (_ZONE_RANK[m.zone], m.drop_to_maintenance_pct
                                     if m.drop_to_maintenance_pct is not None else float("inf")), default=None)


def maturity_buckets(loans: list[Loan], today: date) -> list[MaturityBucket]:
    defs = [("Quá hạn", -10_000, -1), ("Trong 7 ngày", 0, 7), ("8–14 ngày", 8, 14),
            ("15–30 ngày", 15, 30), ("Trên 30 ngày", 31, 10_000)]
    out = []
    for label, lo, hi in defs:
        amount, count = 0.0, 0
        for l in loans:
            if not l.due_date:
                continue
            d = (l.due_date - today).days
            if lo <= d <= hi:
                amount += l.remaining_principal + l.accrued_interest
                count += 1
        out.append(MaturityBucket(label=label, days=hi if hi < 10_000 else 31, amount=amount, count=count))
    return out


def loan_detail(l: Loan, today: date) -> LoanDetail:
    per_day = l.remaining_principal * (l.annual_rate_pct or 0.0) / 100 / 365
    to_due = (l.due_date - today).days if l.due_date else None
    return LoanDetail(
        **l.model_dump(), days_borrowed=(today - l.disbursement_date).days if l.disbursement_date else None,
        days_to_due=to_due, interest_per_day=per_day,
        interest_to_maturity=per_day * max(0, to_due) if to_due is not None else None)


def loan_stats(details: list[LoanDetail], source: str | None = None) -> LoanStats:
    rem = sum(d.remaining_principal for d in details)
    disb = sum(max(d.principal, d.remaining_principal) for d in details)
    per_day = sum(d.interest_per_day for d in details)
    accrued = sum(d.accrued_interest for d in details)
    rated = [d for d in details if d.annual_rate_pct is not None and d.remaining_principal > 0]
    rated_rem = sum(d.remaining_principal for d in rated)
    dated = [d for d in details if d.days_borrowed is not None and d.remaining_principal > 0]
    dated_rem = sum(d.remaining_principal for d in dated)
    upcoming = sorted((d for d in details if d.due_date and d.remaining_principal > 0), key=lambda d: d.due_date)
    nxt = upcoming[0].due_date if upcoming else None
    return LoanStats(
        source=source, count=len(details), principal_disbursed=disb, principal_paid=disb - rem,
        principal_remaining=rem, accrued_interest=accrued, payoff_today=rem + accrued,
        interest_per_day=per_day, interest_per_month=per_day * 30, interest_per_year=per_day * 365,
        avg_rate_pct=(sum(d.remaining_principal * d.annual_rate_pct for d in rated) / rated_rem) if rated_rem else None,
        interest_to_maturity=sum(d.interest_to_maturity or 0.0 for d in details),
        loans_without_due_date=sum(1 for d in details if d.due_date is None),
        avg_days_borrowed=(sum(d.remaining_principal * d.days_borrowed for d in dated) / dated_rem) if dated_rem else None,
        next_due_date=nxt,
        next_due_amount=sum(d.remaining_principal + d.accrued_interest for d in upcoming if d.due_date == nxt) if nxt else None,
    )


def margin_overview(buckets: list[MarginBucket], loans: list[Loan], rules: Rules, today: date) -> MarginOverview:
    metrics = [bucket_metrics(b, rules) for b in buckets]
    debt_loans = sum(l.remaining_principal + l.accrued_interest for l in loans)
    debt_buckets = sum(b.debt or 0.0 for b in buckets)
    per_day = loan_interest_per_day(loans)
    details = [loan_detail(l, today) for l in sorted(loans, key=lambda l: l.due_date or date.max)]
    sources = sorted({d.source or "Không rõ" for d in details})
    by_source = [loan_stats([d for d in details if (d.source or "Không rõ") == s], s) for s in sources] if len(sources) > 1 else []
    return MarginOverview(
        buckets=metrics, loans=details, maturity=maturity_buckets(loans, today),
        total_debt=max(debt_loans, debt_buckets), interest_per_day=per_day, interest_30d=per_day * 30,
        stats=loan_stats(details) if details else None, stats_by_source=by_source,
    )


def asset_overview(positions: list[Position], cash: float, debt: float, interest_per_day: float) -> AssetOverview:
    pv = sum(p.market_value for p in positions)
    cv = sum(p.cost_value for p in positions)
    nav = pv + cash - debt
    pnl = pv - cv
    return AssetOverview(
        positions_value=pv, cost_value=cv, cash=cash, debt=debt, nav=nav,
        unrealized_pnl=pnl, unrealized_pnl_pct=(pnl / cv * 100) if cv else None,
        interest_per_day=interest_per_day,
        interest_pct_nav_per_day=(interest_per_day / nav * 100) if nav > 0 else None,
    )

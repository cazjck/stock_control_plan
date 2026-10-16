"""Kịch bản giả định (mục 6.1 đến 6.3 của docs/dashboard-features.md).

Hàm thuần tuý: nhận số liệu đã có, trả kết quả, không gọi broker, không ghi gì.

Giả định (cũng hiện trên giao diện):
- Mọi mã trong danh mục giảm cùng X% (beta = 1), kể cả mã bị bán thử.
- Bán thử khớp ở giá sau khi giảm; tiền bán dùng trả nợ margin ngay, bỏ qua phí và thuế.
- Tiền nộp thêm cũng dùng trả nợ, ưu tiên nhóm cần nhiều tiền nhất để về vùng an toàn,
  phần còn dư chia theo dư nợ. Vốn chủ tăng đúng bằng số tiền như công thức C = (t − r) × V.
- RTT của TCBS (tài sản đảm bảo / dư nợ) được tính lại theo đúng cách đo đó, xem _bucket_after.
- Mỗi lần trả nợ, lãi vay mỗi ngày giảm theo khoản có lãi suất cao nhất trước.
"""
from __future__ import annotations

from ..models import (
    Loan, MarginBucket, MarginMetrics, Position, ScenarioRequest, ScenarioResult, ScenarioSell, ScenarioState,
)
from ..util import vn
from .margin import bucket_metrics, loan_interest_after_paydown, loan_interest_per_day, worst_bucket
from .rules import Rules


class ScenarioError(ValueError):
    """Đầu vào kịch bản không hợp lệ (mã không có trong danh mục, bán quá số đang giữ)."""


def _unit_price(p: Position) -> float:
    return p.market_value / p.quantity if p.quantity else (p.price or 0.0)


def _shares(symbol: str, buckets: list[MarginBucket]) -> dict[int, float]:
    """Mã thuộc nhóm ký quỹ nào. Mã nằm ở nhiều nhóm thì chia theo giá trị nhóm; broker không gán mã
    vào nhóm nào thì dồn vào nhóm lớn nhất."""
    hit = [i for i, b in enumerate(buckets) if symbol in b.symbols]
    if not hit:
        hit = [max(range(len(buckets)), key=lambda i: buckets[i].market_value or 0.0)]
    weights = {i: (buckets[i].market_value or 0.0) for i in hit}
    total = sum(weights.values())
    return {i: (w / total if total else 1 / len(hit)) for i, w in weights.items()}


def _usable(b: MarginBucket) -> bool:
    return b.ratio_pct is not None and b.maintenance_pct is not None and bool(b.market_value)


def _allocate_cash(amount: float, needs: list[float], debts: list[float]) -> list[float]:
    """Chia tiền nộp thêm: nhóm cần nhiều nhất được đầy trước, phần dư chia theo dư nợ còn lại."""
    alloc = [0.0] * len(needs)
    for i in sorted(range(len(needs)), key=lambda i: -needs[i]):
        alloc[i] = min(amount, needs[i])
        amount -= alloc[i]
    if amount > 0:
        rem = [max(0.0, d - a) for d, a in zip(debts, alloc)]
        total = sum(rem)
        if total > 0:
            for i, r in enumerate(rem):
                alloc[i] += min(r, amount * r / total)
    return alloc


def _bucket_after(b: MarginBucket, value: float, debt: float) -> MarginBucket:
    """Tỷ lệ ký quỹ sau kịch bản, đúng cách đo của từng công ty.

    collateral_over_debt (RTT của TCBS): RTT = Σ(số lượng × tỷ lệ tính tài sản × giá tính tài sản) / dư nợ.
    Tỷ lệ tính tài sản và giá trần cho vay của từng mã không có trong API, nên suy ra hệ số
    c = tài sản đảm bảo / giá trị thị trường từ RTT hiện tại (tài sản đảm bảo = RTT × dư nợ), rồi giữ c cố định:
    giá giảm hoặc bán bớt thì tài sản đảm bảo giảm theo c, tiền bán và tiền nộp trừ thẳng vào dư nợ."""
    if b.ratio_kind == "collateral_over_debt" and b.debt and b.market_value and b.ratio_pct is not None:
        c = (b.ratio_pct / 100 * b.debt) / b.market_value
        ratio = (c * value / debt * 100) if debt > 0 else None
        status = "Kịch bản giả định" if debt > 0 else "Đã trả hết nợ"
        return b.model_copy(update=dict(ratio_pct=ratio, market_value=value, debt=debt, status_text=status))
    ratio = (value - debt) / value * 100 if value > 0 else None
    return b.model_copy(update=dict(ratio_pct=ratio, market_value=value, debt=debt,
                                    status_text="Kịch bản giả định" if value > 0 else "Đã bán hết cổ phiếu"))


def _state(positions_value: float, cost_value: float, cash: float, debt: float, interest: float,
           metrics: list[MarginMetrics]) -> ScenarioState:
    pnl = positions_value - cost_value
    focus = worst_bucket(metrics)
    return ScenarioState(
        positions_value=positions_value, cash=cash, debt=debt, nav=positions_value + cash - debt,
        unrealized_pnl=pnl, unrealized_pnl_pct=(pnl / cost_value * 100) if cost_value else None,
        interest_per_day=interest, buckets=metrics, focus_bucket_id=focus.bucket.id if focus else None,
        cash_needed=sum(m.cash_to_safe or 0.0 for m in metrics))


def run_scenario(req: ScenarioRequest, positions: list[Position], cash: float, debt: float,
                 buckets: list[MarginBucket], loans: list[Loan], rules: Rules) -> ScenarioResult:
    x = req.market_drop_pct / 100
    by_symbol = {p.symbol: p for p in positions}

    sells: dict[str, int] = {}
    for s in req.sell:
        sym = s.symbol.upper()
        if sym not in by_symbol:
            raise ScenarioError(f"{sym} không có trong danh mục, không thể bán thử")
        sells[sym] = sells.get(sym, 0) + s.quantity
    for sym, q in sells.items():
        if q > by_symbol[sym].quantity:
            raise ScenarioError(f"Chỉ đang giữ {vn(by_symbol[sym].quantity, 0)} cp {sym}, không thể bán thử {vn(q, 0)} cp")

    # ---- danh mục ----
    pv_before = sum(p.market_value for p in positions)
    cost_before = sum(p.quantity * p.avg_cost for p in positions)
    sold_value: dict[str, float] = {}
    pv_after = cost_after = realized = 0.0
    for p in positions:
        unit = _unit_price(p) * (1 - x)
        q_sold = sells.get(p.symbol, 0)
        sold_value[p.symbol] = q_sold * unit
        realized += q_sold * (unit - p.avg_cost)
        pv_after += (p.quantity - q_sold) * unit
        cost_after += (p.quantity - q_sold) * p.avg_cost
    proceeds = sum(sold_value.values())

    # ---- từng nhóm ký quỹ ----
    metrics_before = [bucket_metrics(b, rules) for b in buckets]
    sold_in_bucket = [0.0] * len(buckets)
    for sym, v in sold_value.items():
        if v and buckets:
            for i, share in _shares(sym, buckets).items():
                sold_in_bucket[i] += v * share

    value_after, debt_after_b = [], []
    for i, b in enumerate(buckets):
        if not _usable(b):
            value_after.append(b.market_value or 0.0)
            debt_after_b.append(b.debt or 0.0)
            continue
        debt0 = b.debt if b.debt is not None else b.market_value * (1 - b.ratio_pct / 100)
        value_after.append(max(0.0, b.market_value * (1 - x) - sold_in_bucket[i]))
        debt_after_b.append(max(0.0, debt0 - sold_in_bucket[i]))

    interim = [bucket_metrics(_bucket_after(b, v, d), rules) if _usable(b) else m
               for b, v, d, m in zip(buckets, value_after, debt_after_b, metrics_before)]
    alloc = _allocate_cash(req.add_cash, [(m.cash_to_safe or 0.0) if _usable(b) else 0.0 for b, m in zip(buckets, interim)],
                           [d if _usable(b) else 0.0 for b, d in zip(buckets, debt_after_b)])
    metrics_after = [bucket_metrics(_bucket_after(b, v, max(0.0, d - a)), rules) if _usable(b) else m
                     for b, v, d, a, m in zip(buckets, value_after, debt_after_b, alloc, metrics_before)]

    # ---- tổng ----
    paid = proceeds + req.add_cash
    repaid = min(paid, debt)
    debt_after = debt - repaid
    cash_after = cash + (paid - repaid)
    interest_before = loan_interest_per_day(loans)
    interest_after = loan_interest_after_paydown(loans, repaid)

    warnings: list[str] = []
    for m in metrics_after:
        b = m.bucket
        if b.ratio_pct is None and b.market_value == 0 and (b.debt or 0) > 0:
            warnings.append(f"{b.label}: đã bán hết cổ phiếu nhưng còn nợ {vn(b.debt, 0)} đồng")
        elif m.zone == "breach":
            warnings.append(f"{b.label}: RTT {vn(b.ratio_pct)}% dưới ngưỡng giải chấp {vn(b.liquidation_pct, 0)}%")
        elif m.zone == "danger":
            warnings.append(f"{b.label}: RTT {vn(b.ratio_pct)}% dưới ngưỡng duy trì {vn(b.maintenance_pct, 0)}%, sẽ bị gọi ký quỹ")
    if paid > debt > 0 or (paid > 0 and debt == 0):
        warnings.append(f"Tiền bán và tiền nộp vượt dư nợ: phần dư {vn(paid - repaid, 0)} đồng thành tiền mặt")

    return ScenarioResult(
        request=req.model_copy(update=dict(sell=[ScenarioSell(symbol=s, quantity=q) for s, q in sells.items()])),
        before=_state(pv_before, cost_before, cash, debt, interest_before, metrics_before),
        after=_state(pv_after, cost_after, cash_after, debt_after, interest_after, metrics_after),
        sale_proceeds=proceeds, realized_pnl=realized, debt_repaid=repaid, warnings=warnings)

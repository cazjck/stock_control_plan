"""Kế hoạch hạ margin (mục 5b của docs/trading-rules.md).

Mỗi tài khoản ký quỹ được lập lộ trình bán: trước hết là các lệnh luật đã yêu cầu (lô mua thêm tới luật bán,
thủng cắt lỗ, hàng kẹt nhóm B, phần bán đảo hàng), sau đó bán mã lỗ nặng nhất vừa đủ để RTT lên vùng an toàn.
Giai đoạn 2 bán tiếp tới khi hết nợ. Hàm thuần tuý, không gọi mạng, chỉ khuyến nghị."""
from __future__ import annotations

import math
from datetime import date, timedelta

from ..models import (
    DeleverageOverview, DeleveragePlan, DeleverageStep, Loan, MarginMetrics, PositionEval, PositionStatus,
)
from ..util import vg, vn
from .margin import loan_interest_after_paydown, loan_interest_per_day
from .rules import Rules


def _fmt(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


def ratio_for(kind: str, ratio0: float | None, value0: float, debt0: float, value: float, debt: float) -> float | None:
    """Tỷ lệ ký quỹ khi giá trị cổ phiếu còn `value` và dư nợ còn `debt`, đúng cách đo của từng công ty."""
    if debt <= 0:
        return None
    if kind == "collateral_over_debt":
        if ratio0 is None or value0 <= 0 or debt0 <= 0:
            return None
        c = ratio0 / 100 * debt0 / value0        # tài sản đảm bảo / giá trị thị trường, giữ cố định
        return c * value / debt * 100
    return (value - debt) / value * 100 if value > 0 else None


def rows_for_bucket(bucket_id: str, n_buckets: int, evals: list[PositionEval]) -> list[PositionEval]:
    rows = [e for e in evals if e.account_id == bucket_id]
    if not rows and n_buckets == 1:
        rows = list(evals)
    return rows


def loans_for_bucket(source: str | None, n_buckets: int, loans: list[Loan]) -> list[Loan]:
    if n_buckets == 1:
        return list(loans)
    return [l for l in loans if source and l.source == source]


class _Book:
    """Sổ nháp: số cổ phiếu còn lại, giá trị, dư nợ sau từng bước bán."""

    def __init__(self, m: MarginMetrics, rows: list[PositionEval], loans: list[Loan], rules: Rules):
        b = m.bucket
        self.kind = b.ratio_kind
        self.value0 = sum(e.market_value for e in rows) or (b.market_value or 0.0)
        self.debt0 = b.debt or 0.0
        self.ratio0 = b.ratio_pct
        if self.kind == "collateral_over_debt" and b.market_value:
            self.value0 = b.market_value
        self.value, self.debt, self.paid = self.value0, self.debt0, 0.0
        self.left = {e.row_id: e.quantity for e in rows}
        self.taken: dict[str, int] = {}
        self.loans = loans
        self.k = 1 - rules.margin.sell_cost_pct / 100
        self.target = m.safe_target_pct
        self.steps: list[DeleverageStep] = []

    def ratio(self, value: float | None = None, debt: float | None = None) -> float | None:
        return ratio_for(self.kind, self.ratio0, self.value0, self.debt0,
                         self.value if value is None else value, self.debt if debt is None else debt)

    def safe(self) -> bool:
        if self.debt <= 0:
            return True
        r = self.ratio()
        return r is not None and self.target is not None and r >= self.target

    def preview(self, e: PositionEval, qty: int) -> float | None:
        gross = qty * e.price
        return self.ratio(self.value - gross, max(0.0, self.debt - gross * self.k))

    def take(self, e: PositionEval, qty: int, kind: str, reason: str, deferred: bool = False) -> DeleverageStep | None:
        qty = min(qty, self.left.get(e.row_id, 0))
        if qty <= 0 or self.debt <= 0:
            return None
        gross = qty * e.price
        net = gross * self.k
        self.left[e.row_id] -= qty
        self.taken[e.row_id] = self.taken.get(e.row_id, 0) + qty
        self.value -= gross
        self.paid += min(net, self.debt)
        self.debt = max(0.0, self.debt - net)
        st = DeleverageStep(kind=kind, symbol=e.symbol, row_id=e.row_id, quantity=qty, price=e.price, proceeds=net,
                            reason=reason, ratio_after=self.ratio(), debt_after=self.debt,
                            interest_per_day_after=loan_interest_after_paydown(self.loans, self.paid),
                            reaches_target=self.safe(), deferred=deferred)
        self.steps.append(st)
        return st


def _lot_down(q: float) -> int:
    return int(q // 100) * 100


def _lot_up(q: float, cap: int) -> int:
    return min(cap, int(math.ceil(q / 100)) * 100)


def _min_qty_to_target(book: _Book, e: PositionEval) -> int | None:
    """Số cổ phiếu ít nhất (bội số 100) của dòng e để RTT đạt mục tiêu; None nếu bán hết vẫn chưa đủ."""
    have = book.left.get(e.row_id, 0)
    r_all = book.preview(e, have)
    if book.target is None or have <= 0 or not (r_all is None or r_all >= book.target):
        return None
    lo, hi = 0, (have + 99) // 100
    while lo < hi:
        mid = (lo + hi) // 2
        r = book.preview(e, min(have, mid * 100))
        if r is None or r >= book.target:
            hi = mid
        else:
            lo = mid + 1
    return min(have, lo * 100)


def build_plan(m: MarginMetrics, rows: list[PositionEval], loans: list[Loan], rules: Rules, today: date) -> DeleveragePlan:
    b = m.bucket
    book = _Book(m, rows, loans, rules)
    interest0 = loan_interest_per_day(loans)
    notes: list[str] = []

    # ---- giai đoạn 1a: lệnh luật đã yêu cầu ----
    for e in sorted(rows, key=lambda x: -x.urgency):
        due = sum(l.remaining for l in e.lots if l.rule_status in ("stop", "time"))
        if due:
            book.take(e, due, "lot_rule", "các lô đã thủng cắt lỗ hoặc hết hạn (mục 3.5)")
    for e in rows:
        if e.status == PositionStatus.STOP_HIT:
            book.take(e, book.left[e.row_id], "stop", "giá dưới mức cắt lỗ")
    for e in rows:
        if e.status == PositionStatus.TRAPPED and e.plan and e.plan.has_thesis is False:
            want = _lot_down(e.quantity * rules.trapped.group_b_sell_now_pct / 100)
            book.take(e, want - book.taken.get(e.row_id, 0), "group_b",
                      f"bán {vg(rules.trapped.group_b_sell_now_pct)}% ngay (mục 6.2)")
    for e in rows:
        if e.rotation and e.rotation.level == "sell":
            book.take(e, e.rotation.sell_qty - book.taken.get(e.row_id, 0), "rotation",
                      f"nhịp hồi {vn(e.rotation.rebound_pct or 0, 1)}% tới vùng bán (mục 6b)")

    # ---- giai đoạn 1b: mã lỗ nặng nhất vừa đủ về vùng an toàn ----
    # mã đang gồng theo quyết định (mục 6c) xếp sau cùng và ghi là hoãn; hết hiệu lực gồng thì như mã thường
    def holding(e: PositionEval) -> bool:
        return e.hold is not None and e.hold.state in ("holding", "restructure", "review")

    by_loss = sorted(rows, key=lambda x: (holding(x), x.pnl_pct))
    committed: tuple[float | None, float] | None = None
    if b.ratio_pct is not None and book.target is not None:
        for e in by_loss:
            if holding(e) and committed is None:
                committed = (book.ratio(), loan_interest_after_paydown(loans, book.paid))
            if book.safe():
                break
            if book.left.get(e.row_id, 0) <= 0:
                continue
            before = book.ratio()
            q = _min_qty_to_target(book, e)
            if q is None:
                after_all = book.preview(e, book.left[e.row_id])
                if after_all is not None and before is not None and after_all <= before:
                    continue        # bán mã này không làm RTT tăng (nợ lớn hơn giá trị)
                book.take(e, book.left[e.row_id], "worst_loss", f"lỗ {vn(e.pnl_pct, 1, sign=True)}%, bán hết vẫn chưa đủ",
                          deferred=holding(e))
            else:
                book.take(e, q, "worst_loss",
                          f"lỗ {vn(e.pnl_pct, 1, sign=True)}%, vừa đủ đưa RTT lên {vg(book.target)}%", deferred=holding(e))
    elif b.ratio_pct is None:
        notes.append("Chưa có tỷ lệ ký quỹ của tài khoản này. Nhập RTT hoặc ngưỡng ở Sổ danh mục để tính bước về vùng an toàn.")

    safe_steps = list(book.steps)
    deferred = [s for s in safe_steps if s.deferred]
    if not deferred:
        committed = (book.ratio(), loan_interest_after_paydown(loans, book.paid))
    elif committed is None:
        committed = (b.ratio_pct, interest0)
    safe_ratio, safe_debt, safe_paid = book.ratio(), book.debt, book.paid
    safe_reached = book.safe() if b.ratio_pct is not None and book.target is not None else False
    safe_interest = loan_interest_after_paydown(loans, safe_paid)
    if b.ratio_pct is not None and not safe_reached and book.debt > 0:
        notes.append("Bán hết các mã trong tài khoản vẫn chưa đưa RTT về vùng an toàn: cần nộp thêm tiền.")

    # ---- giai đoạn 2: hết nợ ----
    book.steps = []
    for e in by_loss:
        if book.debt <= 0:
            break
        have = book.left.get(e.row_id, 0)
        if have <= 0:
            continue
        need = _lot_up(book.debt / (e.price * book.k), have) if e.price > 0 else have
        book.take(e, need, "to_zero", f"lỗ {vn(e.pnl_pct, 1, sign=True)}%, bán để trả nợ", deferred=holding(e))
    zero_steps = list(book.steps)
    shortfall = book.debt

    # ---- khoản vay đáo hạn trong 30 ngày ----
    soon = [l for l in loans if l.due_date and l.due_date <= today + timedelta(days=30)]
    due_amt = sum(l.remaining_principal + l.accrued_interest for l in soon)
    due_first = min((l.due_date for l in soon), default=None)

    # ---- câu tóm tắt ----
    total_safe = sum(s.quantity * s.price for s in safe_steps)
    if (b.debt or 0) <= 0:
        head = "Không có nợ."
    elif b.ratio_pct is None:
        head = f"Dư nợ {_fmt(b.debt or 0)}. Chưa đủ dữ liệu tỷ lệ ký quỹ để tính bước về vùng an toàn."
    elif m.zone == "safe" and not safe_steps:
        head = (f"Đang an toàn (RTT {vn(b.ratio_pct, 1)}%). Không có lệnh bắt buộc. "
                f"Muốn hết nợ cần bán khoảng {_fmt(sum(s.quantity * s.price for s in zero_steps))} giá trị cổ phiếu.")
    elif safe_reached:
        effect = (f"RTT từ {vn(b.ratio_pct, 1)}% lên {vn(safe_ratio, 1)}%" if safe_ratio is not None
                  else "trả hết nợ")
        lead = (f"Đang an toàn (RTT {vn(b.ratio_pct, 1)}%), nhưng luật đang yêu cầu bán {len(safe_steps)} lệnh"
                if m.zone == "safe" else f"Bán {len(safe_steps)} lệnh")
        head = (f"{lead}, tổng khoảng {_fmt(total_safe)}: {effect}, lãi mỗi ngày giảm từ {_fmt(interest0)} "
                f"còn {_fmt(safe_interest)}.")
    else:
        head = f"Bán hết vẫn chưa an toàn: cần nộp thêm khoảng {_fmt(m.cash_to_safe or 0)}."
    if deferred:
        syms = sorted({s.symbol for s in deferred})
        c_ratio = committed[0]
        gap = ""
        if c_ratio is not None and b.maintenance_pct is not None:
            from .margin import drop_to_threshold
            gap = (f" RTT giữ ở {vn(c_ratio, 1)}%, giảm thêm "
                   f"{vn(drop_to_threshold(c_ratio, b.maintenance_pct, b.ratio_kind), 1)}% là bị gọi ký quỹ.")
        head = (f"Bạn đang gồng {', '.join(syms)} theo quyết định: hoãn bán "
                f"{_fmt(sum(s.quantity for s in deferred))} cổ phiếu ({_fmt(sum(s.quantity * s.price for s in deferred))}).{gap}"
                + (f" Thay cho phần hoãn, có thể nộp khoảng {_fmt(m.cash_to_safe or 0)}." if m.cash_to_safe else ""))
    if due_amt:
        notes.append(f"{len(soon)} khoản vay đáo hạn trong 30 ngày, sớm nhất {due_first:%d/%m}: cần {_fmt(due_amt)} gốc và lãi.")
    if shortfall > 0:
        notes.append(f"Bán hết cổ phiếu vẫn còn nợ {_fmt(shortfall)}.")

    return DeleveragePlan(
        bucket_id=b.id, label=b.label, source=b.source, ratio_kind=b.ratio_kind, ratio_pct=b.ratio_pct,
        maintenance_pct=b.maintenance_pct, liquidation_pct=b.liquidation_pct, target_pct=m.safe_target_pct, zone=m.zone,
        market_value=book.value0, debt=book.debt0, interest_per_day=interest0, cash_alternative=m.cash_to_safe,
        safe_steps=safe_steps, safe_ratio_after=safe_ratio, safe_debt_after=safe_debt, safe_interest_after=safe_interest,
        safe_reached=safe_reached, committed_ratio_after=committed[0], committed_interest_after=committed[1],
        deferred_symbols=sorted({s.symbol for s in deferred}), zero_steps=zero_steps, zero_shortfall=shortfall,
        zero_interest_saved=safe_interest - (zero_steps[-1].interest_per_day_after if zero_steps else safe_interest),
        due_30d_amount=due_amt, due_30d_first=due_first, due_30d_count=len(soon), headline=head, notes=notes)


def build_overview(metrics: list[MarginMetrics], evals: list[PositionEval], loans: list[Loan], rules: Rules,
                   today: date) -> DeleverageOverview:
    n = len(metrics)
    plans = [build_plan(m, rows_for_bucket(m.bucket.id, n, evals), loans_for_bucket(m.bucket.source, n, loans), rules, today)
             for m in metrics if (m.bucket.debt or 0) > 0]
    rank = {"breach": 0, "danger": 1, "watch": 2, "unknown": 3, "safe": 4}
    plans.sort(key=lambda p: (rank.get(p.zone, 5), -(p.debt)))
    return DeleverageOverview(
        plans=plans, total_debt=sum(p.debt for p in plans),
        interest_per_day=sum(p.interest_per_day for p in plans),
        interest_after_safe=sum(p.committed_interest_after for p in plans),
        safe_sell_value=sum(s.quantity * s.price for p in plans for s in p.safe_steps if not s.deferred),
        safe_proceeds=sum(s.proceeds for p in plans for s in p.safe_steps if not s.deferred),
        deferred_sell_value=sum(s.quantity * s.price for p in plans for s in p.safe_steps if s.deferred),
        accounts_unsafe=sum(1 for p in plans if p.zone in ("breach", "danger", "watch")))

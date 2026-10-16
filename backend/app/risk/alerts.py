"""Sinh cảnh báo P0 từ kết quả đánh giá. Mỗi cảnh báo có `key` ổn định để lưu trữ khử trùng lặp."""
from __future__ import annotations

from datetime import date

from ..models import (
    AlertCandidate, AlertSeverity, AssetOverview, MarginOverview, PositionEval, PositionStatus,
)
from ..util import vg, vn
from .rules import Rules


def _vnd(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


def build_candidates(
    positions: list[PositionEval], assets: AssetOverview, margin: MarginOverview,
    rules: Rules, today: date,
) -> list[AlertCandidate]:
    out: list[AlertCandidate] = []

    # 5.1 cắt lỗ theo mã (theo dòng: cùng mã ở nhiều nguồn thì mỗi nguồn một cảnh báo)
    for p in positions:
        rk = p.row_id or p.symbol
        nm = f"{p.symbol} ({p.source})" if rk != p.symbol and p.source else p.symbol
        if p.status == PositionStatus.STOP_HIT:
            out.append(AlertCandidate(
                key=f"STOP:{rk}", rule="stop_loss", severity=AlertSeverity.CRITICAL, symbol=p.symbol,
                title=f"{nm} chạm mức cắt lỗ",
                message=f"Giá {_vnd(p.price)} dưới mức cắt lỗ {_vnd(p.stop_level or 0)} ({p.stop_basis}). "
                        f"Lãi lỗ {vn(p.pnl_pct, 1, sign=True)}%.",
                data={"price": p.price, "stop": p.stop_level, "pnl_pct": p.pnl_pct}))
        elif p.status == PositionStatus.TRAPPED:
            out.append(AlertCandidate(
                key=f"TRAPPED:{rk}", rule="trapped", severity=AlertSeverity.CRITICAL, symbol=p.symbol,
                title=f"{nm} là hàng kẹt ({vn(p.pnl_pct, 1, sign=True)}%)",
                message=p.actions[0] if p.actions else "Áp dụng giao thức thoát hàng kẹt.",
                data={"pnl_pct": p.pnl_pct}))
        elif p.status == PositionStatus.TIME_STOP:
            out.append(AlertCandidate(
                key=f"TIME:{rk}", rule="time_stop", severity=AlertSeverity.WARNING, symbol=p.symbol,
                title=f"{nm} hết hạn cắt lỗ theo thời gian", message=p.actions[0], data={}))
        elif p.status == PositionStatus.WARNING:
            out.append(AlertCandidate(
                key=f"WARN:{rk}", rule="technical_warning", severity=AlertSeverity.WARNING, symbol=p.symbol,
                title=f"{nm} yếu đi", message=p.actions[0], data={}))
        elif p.status == PositionStatus.TAKE_PROFIT:
            out.append(AlertCandidate(
                key=f"TP:{rk}:{int(p.pnl_pct // 5)}", rule="take_profit", severity=AlertSeverity.INFO,
                symbol=p.symbol, title=f"{nm} tới mốc chốt lời", message=p.actions[0],
                data={"pnl_pct": p.pnl_pct}))

    # 6c gồng có kế hoạch: ba tín hiệu kết thúc gồng (không tắt được) và thời điểm cơ cấu
    for p in positions:
        h = p.hold
        if h is None or h.state == "holding":
            continue
        rk = p.row_id or p.symbol
        nm = f"{p.symbol} ({p.source})" if rk != p.symbol and p.source else p.symbol
        title = {"exit_price": f"{nm}: thủng giá thoát, kết thúc gồng",
                 "exit_margin": f"{nm}: tỷ lệ ký quỹ chạm sàn, kết thúc gồng",
                 "review": f"{nm}: tới ngày xem lại quyết định gồng",
                 "restructure": f"{nm}: thời điểm cơ cấu"}[h.state]
        out.append(AlertCandidate(
            key=f"HOLD:{h.state}:{rk}:{h.decision.id}:{h.decision.review_on.isoformat()}",
            rule="hold_restructure" if h.state == "restructure" else "hold_exit",
            severity=AlertSeverity.WARNING if h.state == "restructure" else AlertSeverity.CRITICAL,
            symbol=p.symbol, title=title, message=h.text,
            data={"state": h.state, "days_held": h.days_held, "interest_cost": h.interest_cost}))

    # 6b đảo hàng: vào vùng bán hoặc đủ điều kiện mua lại
    for p in positions:
        rot = p.rotation
        if rot is None or rot.level not in ("sell", "rebuy"):
            continue
        rk = p.row_id or p.symbol
        nm = f"{p.symbol} ({p.source})" if rk != p.symbol and p.source else p.symbol
        if rot.level == "sell":
            out.append(AlertCandidate(
                key=f"ROT:SELL:{rk}:{rot.sold_qty}:{rot.sell_qty}", rule="rotation", severity=AlertSeverity.WARNING,
                symbol=p.symbol, title=f"{nm}: nhịp hồi {vn(rot.rebound_pct or 0, 1)}%, vùng bán đảo hàng",
                message=rot.text, data={"sell_qty": rot.sell_qty, "rebound_pct": rot.rebound_pct}))
        else:
            out.append(AlertCandidate(
                key=f"ROT:BUY:{rk}:{rot.sold_qty}:{rot.bought_qty}", rule="rotation", severity=AlertSeverity.INFO,
                symbol=p.symbol, title=f"{nm}: đủ điều kiện mua lại {_vnd(rot.rebuy_qty)} cổ phiếu",
                message=rot.text, data={"rebuy_qty": rot.rebuy_qty, "rebuy_below": rot.rebuy_below}))

    # 3.5 lô mua thêm khi đang lỗ: cảnh báo không tắt được cho tới khi bán hoặc ghi lý do
    for p in positions:
        for l in p.lots:
            if l.rule_status not in ("stop", "time"):
                continue
            delay = ""
            if l.delay_sessions:
                delay = f" Đã chần chừ {l.delay_sessions} phiên"
                delay += f", mất thêm {_vnd(l.delay_cost)} đồng." if l.delay_cost else "."
            out.append(AlertCandidate(
                key=f"LOT:{l.broker}:{l.id}", rule="add_on_lot", severity=AlertSeverity.CRITICAL, symbol=p.symbol,
                title=f"{p.symbol}{f' ({l.source_label})' if l.source_label else ''}: lô mua ngày {l.buy_date:%d/%m} phải bán",
                message=(l.action or "") + delay,
                data={"lot_id": l.id, "remaining": l.remaining, "delay_sessions": l.delay_sessions, "delay_cost": l.delay_cost}))

    # 5.2 RTT
    for m in margin.buckets:
        b = m.bucket
        if m.zone in ("breach", "danger"):
            sev = AlertSeverity.CRITICAL
        elif m.zone == "watch":
            sev = AlertSeverity.WARNING
        else:
            continue
        gap = (b.ratio_pct - b.maintenance_pct) if b.ratio_pct is not None and b.maintenance_pct is not None else 0
        out.append(AlertCandidate(
            key=f"RTT:{b.id}", rule="rtt", severity=sev,
            title=f"RTT {b.label} còn cách ngưỡng duy trì {vn(gap, 1)} điểm %" if gap > 0 else f"RTT {b.label} đã dưới ngưỡng duy trì",
            message=(f"RTT {vn(b.ratio_pct, 1)}% so với ngưỡng duy trì {vn(b.maintenance_pct, 1)}%. "
                     f"Thị trường giảm thêm {vn(m.drop_to_maintenance_pct, 1)}% là bị gọi ký quỹ. "
                     f"Cần nộp khoảng {_vnd(m.cash_to_safe or 0)} để về vùng an toàn."),
            data={"ratio": b.ratio_pct, "maintenance": b.maintenance_pct, "cash_to_safe": m.cash_to_safe}))

    # 5.3 đáo hạn
    for l in margin.loans:
        if not l.due_date:
            continue
        days = (l.due_date - today).days
        thresholds = sorted(rules.alerts.loan_due_days)
        hit = next((t for t in thresholds if days <= t), None)
        if days < 0:
            sev, title = AlertSeverity.CRITICAL, f"Khoản vay quá hạn {-days} ngày"
        elif hit is not None:
            sev = AlertSeverity.CRITICAL if hit <= 1 else AlertSeverity.WARNING
            title = f"Khoản vay đáo hạn sau {days} ngày"
        else:
            continue
        out.append(AlertCandidate(
            key=f"LOAN:{l.id}:{hit if days >= 0 else 'over'}", rule="loan_due", severity=sev, title=title,
            message=f"Đáo hạn {l.due_date:%d/%m/%Y}, còn nợ gốc {_vnd(l.remaining_principal)} và lãi {_vnd(l.accrued_interest)}.",
            data={"due": l.due_date.isoformat(), "principal": l.remaining_principal}))

    # 5.4 lỗ danh mục / chi phí lãi
    if assets.nav > 0 and assets.unrealized_pnl < 0:
        loss_pct = -assets.unrealized_pnl / assets.nav * 100
        if loss_pct >= rules.alerts.portfolio_loss_pct_nav:
            out.append(AlertCandidate(
                key="LOSS:portfolio", rule="portfolio_loss", severity=AlertSeverity.CRITICAL,
                title=f"Lỗ chưa thực hiện {vn(loss_pct, 1)}% NAV",
                message=f"Lỗ {_vnd(-assets.unrealized_pnl)} đã vượt ngưỡng {vg(rules.alerts.portfolio_loss_pct_nav)}% NAV.",
                data={"loss_pct_nav": loss_pct}))
    if assets.interest_pct_nav_per_day and assets.interest_pct_nav_per_day > rules.margin.interest_alert_pct_nav_per_day:
        out.append(AlertCandidate(
            key="INTEREST:day", rule="interest", severity=AlertSeverity.CRITICAL,
            title=f"Lãi margin {_vnd(assets.interest_per_day)} đồng mỗi ngày",
            message=f"Bằng {vn(assets.interest_pct_nav_per_day, 3)}% NAV mỗi ngày, vượt ngưỡng "
                    f"{vg(rules.margin.interest_alert_pct_nav_per_day)}%. Phải giảm nợ trong tuần.",
            data={"per_day": assets.interest_per_day}))
    return out

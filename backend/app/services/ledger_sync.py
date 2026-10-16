"""Đồng bộ danh mục từ một broker thật vào sổ tổng: chỉ ĐỌC từ broker, rồi ghi vào SQLite của ứng dụng."""
from __future__ import annotations

from ..brokers.base import BrokerError
from ..models import LedgerAccount
from ..storage.ledger import LedgerRepo
from ..util import now_vn
from .portfolio import PortfolioService


async def sync_from_broker(svc: PortfolioService, repo: LedgerRepo, broker: str) -> dict:
    if broker in ("ledger",):
        raise BrokerError("Không thể đồng bộ sổ tổng vào chính nó")
    ad = svc.adapter(broker)
    if not ad.session_info().authenticated:
        raise BrokerError(f"{ad.display_name} chưa đăng nhập. Nhập iOTP ở trang Thiết lập rồi đồng bộ lại.")
    now = now_vn()
    summary = {"broker": broker, "synced_at": now.isoformat(), "accounts": [], "positions": 0, "debts": 0}
    for acc in await ad.list_accounts():
        positions = await ad.get_positions(acc.id)
        quotes = {}
        try:
            quotes = await ad.get_quotes([p.symbol for p in positions])
        except BrokerError:
            pass
        for p in positions:
            q = quotes.get(p.symbol)
            if q and q.price:
                p.price, p.market_value = q.price, q.price * p.quantity
        cash = await ad.get_cash(acc.id)
        buckets = await ad.get_margin(acc.id, positions)
        loans = await ad.get_loans(acc.id)
        if not positions and not loans and not cash.cash:
            continue  # tiểu khoản trống, không chép
        acct_buckets = [b for b in buckets if b.scope == "account"]
        b = acct_buckets[0] if len(acct_buckets) == 1 else None
        mv = sum(p.market_value for p in positions)
        la = LedgerAccount(
            id=f"{broker}-{acc.id}".lower(), name=f"{ad.display_name} · {acc.id}", source="sync",
            source_broker=broker, source_account=acc.id, cash=cash.cash,
            ratio_kind=b.ratio_kind if b else "equity_over_value",
            ratio_pct=b.ratio_pct if b and b.ratio_kind == "collateral_over_debt" else None,
            ratio_ref_value=mv if b and b.ratio_kind == "collateral_over_debt" else None,
            initial_pct=b.initial_pct if b else None, maintenance_pct=b.maintenance_pct if b else None,
            liquidation_pct=b.liquidation_pct if b else None, synced_at=now,
        )
        repo.replace_synced(
            la,
            [{"symbol": p.symbol, "quantity": p.quantity, "avg_cost": p.avg_cost, "last_price": p.price} for p in positions],
            [{"symbol": l.symbol, "principal": l.principal or l.remaining_principal, "remaining_principal": l.remaining_principal,
              "accrued_interest": l.accrued_interest, "annual_rate_pct": l.annual_rate_pct,
              "disbursement_date": l.disbursement_date, "due_date": l.due_date} for l in loans],
        )
        summary["accounts"].append(la.name)
        summary["positions"] += len(positions)
        summary["debts"] += len(loans)
    svc.invalidate("ledger")
    return summary

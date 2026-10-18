"""Adapter "Danh mục tổng": đọc sổ danh mục lưu cục bộ (SSI, VPS nhập tay; TCBS đồng bộ) như một broker.

Adapter chỉ đọc sổ. Việc ghi vào sổ nằm ở app/storage/ledger.py, gọi từ API sổ sách của ứng dụng.
Giá và nến lấy từ một broker thật đã đăng nhập (nguồn giá); không có nguồn giá thì dùng giá đã ghi trong sổ.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Callable

from ..models import (
    Account, Candle, CashBalance, Interval, LedgerAccount, Loan, MarginBucket, Position, Quote, SessionInfo,
    SourceShare,
)
from ..storage.ledger import LedgerRepo
from .base import AuthRequired, BrokerAdapter, BrokerError

ALL = "ALL"
_SHORT = {"tcbs": "TCBS", "dnse": "DNSE", "demo": "Demo"}


def source_label(a: LedgerAccount, all_accounts: list[LedgerAccount] | None = None) -> str:
    """Nhãn nguồn: "TCBS" cho phần đồng bộ (thêm số tiểu khoản nếu đồng bộ nhiều tiểu khoản), tên tiểu danh mục nếu nhập tay."""
    if a.source != "sync" or not a.source_broker:
        return a.name
    short = _SHORT.get(a.source_broker, a.source_broker.upper())
    same = [x for x in (all_accounts or []) if x.source == "sync" and x.source_broker == a.source_broker]
    return f"{short} {a.source_account}" if len(same) > 1 else short


class LedgerAdapter(BrokerAdapter):
    name = "ledger"
    display_name = "Danh mục tổng"

    def __init__(self, repo: LedgerRepo, price_source: Callable[[], BrokerAdapter | None]):
        self._repo = repo
        self._price_source = price_source

    def session_info(self) -> SessionInfo:
        src = self._price_source()
        msg = (f"Giá lấy từ {src.display_name}" if src else
               "Chưa có nguồn giá: đăng nhập TCBS để cập nhật giá. Hiện dùng giá đã ghi trong sổ.")
        return SessionInfo(broker=self.name, configured=True, authenticated=True, needs_otp=False, message=msg)

    def _scope(self, account_id: str) -> list[LedgerAccount]:
        accs = self._repo.accounts()
        return accs if account_id == ALL else [a for a in accs if a.id == account_id]

    async def list_accounts(self) -> list[Account]:
        accs = self._repo.accounts()
        debt_by = {d.account_id for d in self._repo.debts()}
        out = [Account(broker=self.name, id=ALL, name="Tất cả tiểu danh mục",
                       kind="margin" if debt_by else "normal")]
        out += [Account(broker=self.name, id=a.id, name=a.name, kind="margin" if a.id in debt_by else "normal")
                for a in accs]
        return out

    async def get_positions(self, account_id: str) -> list[Position]:
        """Mỗi (tiểu danh mục, mã) là một dòng, kể cả ở mục "Tất cả": giá vốn, lãi lỗ và luật của từng nguồn khác nhau,
        và lệnh bán phải đặt ở từng công ty. Gộp theo mã chỉ để xem mức độ tập trung, việc đó làm ở giao diện."""
        accs = self._repo.accounts()
        scope = {a.id: a for a in (accs if account_id == ALL else [a for a in accs if a.id == account_id])}
        out: list[Position] = []
        for p in self._repo.positions():
            if p.account_id not in scope or p.quantity <= 0:
                continue
            out.append(Position(
                broker=self.name, account_id=p.account_id, symbol=p.symbol, quantity=p.quantity, avg_cost=p.avg_cost,
                price=p.last_price, market_value=p.quantity * (p.last_price or 0.0), row_id=f"{p.account_id}:{p.symbol}",
                sources=[SourceShare(source=source_label(scope[p.account_id], accs), account=p.account_id,
                                     quantity=p.quantity, avg_cost=p.avg_cost)]))
        return sorted(out, key=lambda x: (x.symbol, x.account_id))

    def remember_prices(self, positions: list[Position]) -> None:
        """Ghi giá gần nhất vào sổ (chỉ SQLite của ứng dụng)."""
        self._repo.remember_prices({(p.account_id, p.symbol): p.price for p in positions if p.price})

    async def get_cash(self, account_id: str) -> CashBalance:
        return CashBalance(account_id=account_id, cash=sum(a.cash for a in self._scope(account_id)))

    async def get_margin(self, account_id: str, positions: list[Position]) -> list[MarginBucket]:
        """Mỗi tiểu danh mục có nợ là một nhóm ký quỹ riêng, vì mỗi công ty chứng khoán tính ký quỹ độc lập."""
        # giá theo từng dòng (tiểu danh mục, mã): cùng mã ở hai nguồn có thể khác giá khi một nguồn không có giá trực tiếp
        price = {(p.account_id, p.symbol): p.price for p in positions if p.price}
        debts = defaultdict(float)
        for d in self._repo.debts():
            debts[d.account_id] += d.remaining_principal + d.accrued_interest
        out: list[MarginBucket] = []
        for a in self._scope(account_id):
            debt = debts.get(a.id, 0.0)
            if debt <= 0 and a.ratio_pct is None:
                continue
            rows = self._repo.positions(a.id)
            mv = sum(p.quantity * (price.get((a.id, p.symbol)) or p.last_price or p.avg_cost) for p in rows)
            status = None
            if a.ratio_kind == "collateral_over_debt":
                if a.ratio_pct is None:
                    ratio, status = None, "Nhập RTT đang hiện trên app của công ty chứng khoán để tính"
                elif a.ratio_ref_value:
                    ratio = a.ratio_pct * mv / a.ratio_ref_value   # tài sản đảm bảo tỷ lệ với giá
                    status = "RTT quy đổi theo giá hiện tại từ lần ghi gần nhất"
                else:
                    ratio = a.ratio_pct
            else:
                ratio = ((mv - debt) / mv * 100) if mv > 0 else None
            out.append(MarginBucket(
                id=a.id, scope="account", label=a.name, source=source_label(a, self._repo.accounts()), symbols=[p.symbol for p in rows], ratio_kind=a.ratio_kind,
                ratio_pct=ratio, initial_pct=a.initial_pct, maintenance_pct=a.maintenance_pct,
                liquidation_pct=a.liquidation_pct, market_value=mv or None, debt=debt, status_text=status,
                raw={"source": a.source, "synced_at": a.synced_at.isoformat() if a.synced_at else None,
                     "recorded_ratio": a.ratio_pct, "ratio_ref_value": a.ratio_ref_value},
            ))
        return out

    async def get_loans(self, account_id: str) -> list[Loan]:
        accs = self._repo.accounts()
        scope = {a.id: a for a in self._scope(account_id)}
        return [Loan(id=f"L{d.id}", symbol=d.symbol, source=source_label(scope[d.account_id], accs),
                     disbursement_date=d.disbursement_date, due_date=d.due_date, principal=d.principal,
                     remaining_principal=d.remaining_principal, accrued_interest=d.accrued_interest,
                     annual_rate_pct=d.annual_rate_pct)
                for d in self._repo.debts() if d.account_id in scope and (d.remaining_principal > 0 or d.accrued_interest > 0)]  # đã trả hết gốc nhưng còn lãi

    async def get_candles(self, symbol: str, interval: Interval, count: int, *, is_index: bool = False) -> list[Candle]:
        src = self._price_source()
        if src is None:
            raise BrokerError("Chưa có nguồn giá cho danh mục tổng. Đăng nhập TCBS để có nến và chỉ báo.")
        try:
            return await src.get_candles(symbol, interval, count, is_index=is_index)
        except AuthRequired as e:
            # không để màn hình sổ tổng bị chặn bởi đăng nhập của nguồn giá
            raise BrokerError(f"Nguồn giá {src.display_name} cần đăng nhập lại") from e

    async def get_board(self, symbols: list[str]):
        src = self._price_source()
        if src is None or not symbols:
            return {}
        try:
            return await src.get_board(symbols)
        except BrokerError:
            return {}

    async def get_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        src = self._price_source()
        if src is None or not symbols:
            return {}
        try:
            return await src.get_quotes(symbols)
        except BrokerError:
            return {}

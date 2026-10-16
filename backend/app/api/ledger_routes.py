"""API sổ danh mục tổng. Mọi route ghi ở đây chỉ ghi vào SQLite của ứng dụng (sổ sách),
không route nào gửi lệnh hay yêu cầu ghi tới broker."""
from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from ..brokers.base import BrokerError
from ..models import LedgerAccount, LedgerDebt, LedgerPosition
from ..services.ledger_sync import sync_from_broker
from ..services.portfolio import PortfolioService
from ..storage.ledger import LedgerError, LedgerRepo
from ..util import now_vn
from .deps import require_token, service

router = APIRouter(prefix="/api/ledger", dependencies=[Depends(require_token)])


def repo(request: Request) -> LedgerRepo:
    return request.app.state.ledger


def _err(e: LedgerError) -> HTTPException:
    return HTTPException(422, {"code": "LEDGER", "message": str(e)})


# ---------- đọc ----------

class PositionView(LedgerPosition):
    price: float | None = None
    price_is_live: bool = False
    cost_value: float
    market_value: float | None
    pnl: float | None
    pnl_pct: float | None


class AccountView(LedgerAccount):
    positions: list[PositionView]
    debts: list[LedgerDebt]
    totals: dict[str, float | None]


class LedgerView(BaseModel):
    accounts: list[AccountView]
    price_source: str | None
    totals: dict[str, float | None]


@router.get("", response_model=LedgerView)
async def get_ledger(r: LedgerRepo = Depends(repo), svc: PortfolioService = Depends(service)):
    ad = svc.adapters.get("ledger")
    positions = r.positions()
    quotes = {}
    if ad is not None:
        quotes = await ad.get_quotes(sorted({p.symbol for p in positions}))
    src = ad._price_source() if ad is not None else None  # type: ignore[attr-defined]
    accounts: list[AccountView] = []
    grand = {"cost": 0.0, "value": 0.0, "debt": 0.0, "cash": 0.0}
    for a in r.accounts():
        pv: list[PositionView] = []
        for p in (x for x in positions if x.account_id == a.id):
            q = quotes.get(p.symbol)
            price = q.price if q and q.price else p.last_price
            cost = p.quantity * p.avg_cost
            mv = p.quantity * price if price else None
            pv.append(PositionView(**p.model_dump(), price=price, price_is_live=bool(q and q.price), cost_value=cost,
                                   market_value=mv, pnl=(mv - cost) if mv is not None else None,
                                   pnl_pct=((mv / cost - 1) * 100) if mv is not None and cost else None))
        debts = r.debts(a.id)
        t = {"cost": sum(x.cost_value for x in pv), "value": sum(x.market_value or 0 for x in pv),
             "debt": sum(d.remaining_principal + d.accrued_interest for d in debts), "cash": a.cash}
        t["pnl"] = t["value"] - t["cost"]
        t["nav"] = t["value"] + t["cash"] - t["debt"]
        for k in grand:
            grand[k] += t[k]
        accounts.append(AccountView(**a.model_dump(), positions=pv, debts=debts, totals=t))
    grand["pnl"] = grand["value"] - grand["cost"]
    grand["nav"] = grand["value"] + grand["cash"] - grand["debt"]
    return LedgerView(accounts=accounts, price_source=src.display_name if src else None, totals=grand)


# ---------- tiểu danh mục ----------

class AccountIn(BaseModel):
    name: str | None = Field(default=None, max_length=60)
    cash: float | None = Field(default=None, ge=0)
    ratio_kind: Literal["equity_over_value", "collateral_over_debt"] | None = None
    ratio_pct: float | None = Field(default=None, ge=0, le=1000)
    initial_pct: float | None = Field(default=None, ge=0, le=1000)
    maintenance_pct: float | None = Field(default=None, ge=0, le=1000)
    liquidation_pct: float | None = Field(default=None, ge=0, le=1000)
    note: str | None = Field(default=None, max_length=500)


def _with_ref(r: LedgerRepo, account_id: str | None, fields: dict) -> dict:
    """Khi người dùng ghi RTT từ app, lưu kèm giá trị cổ phiếu lúc đó để sau này quy đổi theo giá mới."""
    if "ratio_pct" in fields and fields["ratio_pct"] is not None:
        rows = r.positions(account_id) if account_id else []
        fields["ratio_ref_value"] = sum(p.quantity * (p.last_price or p.avg_cost) for p in rows) or None
    return fields


@router.post("/accounts", response_model=LedgerAccount)
async def create_account(body: AccountIn, r: LedgerRepo = Depends(repo), svc: PortfolioService = Depends(service)):
    try:
        a = r.create_account(body.name or "", **{k: v for k, v in body.model_dump(exclude_unset=True).items() if k != "name"})
    except LedgerError as e:
        raise _err(e) from e
    svc.invalidate("ledger")
    return a


@router.put("/accounts/{account_id}", response_model=LedgerAccount)
async def update_account(account_id: str, body: AccountIn, r: LedgerRepo = Depends(repo),
                         svc: PortfolioService = Depends(service)):
    try:
        a = r.update_account(account_id, **_with_ref(r, account_id, body.model_dump(exclude_unset=True)))
    except LedgerError as e:
        raise _err(e) from e
    svc.invalidate("ledger")
    return a


@router.delete("/accounts/{account_id}")
async def delete_account(account_id: str, request: Request, r: LedgerRepo = Depends(repo), svc: PortfolioService = Depends(service)):
    try:
        r.delete_account(account_id)
        request.app.state.lots.delete_for("ledger", account_id)
    except LedgerError as e:
        raise _err(e) from e
    svc.invalidate("ledger")
    return {"ok": True}


# ---------- cổ phiếu ----------

class PurchaseIn(BaseModel):
    symbol: str = Field(min_length=2, max_length=10)
    quantity: int = Field(gt=0)
    price: float | None = Field(default=None, gt=0)
    total_amount: float | None = Field(default=None, gt=0)
    bought_at: date | None = None
    record_lot: bool = True   # False khi nhập lại tổng từ ảnh chụp danh mục: không biết ngày mua thật

    @model_validator(mode="after")
    def _one_of(self):
        if (self.price is None) == (self.total_amount is None):
            raise ValueError("Nhập giá mua mỗi cổ phiếu hoặc tổng tiền mua, chỉ một trong hai")
        return self


@router.post("/accounts/{account_id}/purchases", response_model=LedgerPosition)
async def add_purchase(account_id: str, body: PurchaseIn, request: Request, r: LedgerRepo = Depends(repo),
                       svc: PortfolioService = Depends(service)):
    before = next((x for x in r.positions(account_id) if x.symbol == body.symbol.strip().upper()), None)
    try:
        p = r.record_purchase(account_id, body.symbol, body.quantity, price=body.price,
                              total_amount=body.total_amount, bought_at=body.bought_at)
    except LedgerError as e:
        raise _err(e) from e
    unit = body.price if body.price is not None else body.total_amount / body.quantity  # type: ignore[operator]
    if body.record_lot:
        request.app.state.lots.add(
            broker="ledger", account_id=account_id, symbol=p.symbol, buy_date=body.bought_at or now_vn().date(),
            quantity=body.quantity, price=unit, source="ledger",
            add_on_loss=before is not None and unit < before.avg_cost)
    svc.invalidate("ledger")
    return p


class PositionIn(BaseModel):
    quantity: int | None = Field(default=None, gt=0)
    avg_cost: float | None = Field(default=None, gt=0)
    last_price: float | None = Field(default=None, gt=0)
    bought_at: date | None = None


@router.put("/positions/{pid}", response_model=LedgerPosition)
async def update_position(pid: int, body: PositionIn, r: LedgerRepo = Depends(repo), svc: PortfolioService = Depends(service)):
    try:
        p = r.update_position(pid, **body.model_dump(exclude_unset=True))
    except LedgerError as e:
        raise _err(e) from e
    svc.invalidate("ledger")
    return p


@router.delete("/positions/{pid}")
async def delete_position(pid: int, request: Request, r: LedgerRepo = Depends(repo), svc: PortfolioService = Depends(service)):
    try:
        pos = next((x for x in r.positions() if x.id == pid), None)
        r.delete_position(pid)
        if pos is not None:
            request.app.state.lots.delete_for("ledger", pos.account_id, pos.symbol)
    except LedgerError as e:
        raise _err(e) from e
    svc.invalidate("ledger")
    return {"ok": True}


# ---------- nợ margin ----------

class DebtIn(BaseModel):
    symbol: str | None = Field(default=None, max_length=10)
    principal: float | None = Field(default=None, gt=0)
    remaining_principal: float | None = Field(default=None, ge=0)
    accrued_interest: float | None = Field(default=None, ge=0)
    annual_rate_pct: float | None = Field(default=None, ge=0, le=100)
    disbursement_date: date | None = None
    due_date: date | None = None
    note: str | None = Field(default=None, max_length=500)


@router.post("/accounts/{account_id}/debts", response_model=LedgerDebt)
async def add_debt(account_id: str, body: DebtIn, r: LedgerRepo = Depends(repo), svc: PortfolioService = Depends(service)):
    if body.principal is None:
        raise HTTPException(422, {"code": "LEDGER", "message": "Cần nhập nợ gốc"})
    f = body.model_dump(exclude_unset=True)
    try:
        d = r.add_debt(account_id, principal=f.pop("principal"), **{k: v for k, v in f.items() if v is not None})
    except LedgerError as e:
        raise _err(e) from e
    svc.invalidate("ledger")
    return d


@router.put("/debts/{did}", response_model=LedgerDebt)
async def update_debt(did: int, body: DebtIn, r: LedgerRepo = Depends(repo), svc: PortfolioService = Depends(service)):
    try:
        d = r.update_debt(did, **body.model_dump(exclude_unset=True))
    except LedgerError as e:
        raise _err(e) from e
    svc.invalidate("ledger")
    return d


@router.delete("/debts/{did}")
async def delete_debt(did: int, r: LedgerRepo = Depends(repo), svc: PortfolioService = Depends(service)):
    try:
        r.delete_debt(did)
    except LedgerError as e:
        raise _err(e) from e
    svc.invalidate("ledger")
    return {"ok": True}


# ---------- đồng bộ ----------

@router.post("/sync/{broker}")
async def sync(broker: str, r: LedgerRepo = Depends(repo), svc: PortfolioService = Depends(service)):
    """Chép danh mục, tiền, khoản vay và RTT từ broker thật vào sổ. Chỉ đọc từ broker."""
    return await sync_from_broker(svc, r, broker)

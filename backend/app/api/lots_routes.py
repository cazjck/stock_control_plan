"""API từng lần mua (lô). Chỉ ghi vào SQLite của ứng dụng."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..models import Lot
from ..services.portfolio import PortfolioService
from ..storage.lots import LotError, LotRepo
from ..util import now_vn
from .deps import require_token, service

router = APIRouter(prefix="/api/lots", dependencies=[Depends(require_token)])


def repo(request: Request) -> LotRepo:
    return request.app.state.lots


def _err(e: Exception) -> HTTPException:
    return HTTPException(422, {"code": "LOTS", "message": str(e)})


class LotIn(BaseModel):
    symbol: str = Field(min_length=2, max_length=10)
    buy_date: date
    quantity: int = Field(gt=0)
    price: float = Field(gt=0)
    add_on_loss: bool | None = None   # để trống: tự xét theo giá vốn hiện tại
    stop_price: float | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=300)


@router.get("", response_model=list[Lot])
async def list_lots(broker: str, account: str | None = None, symbol: str | None = None, r: LotRepo = Depends(repo)):
    return r.lots(broker, account, symbol)


@router.post("", response_model=Lot)
async def add_lot(body: LotIn, request: Request, broker: str, account: str | None = None, r: LotRepo = Depends(repo),
                  svc: PortfolioService = Depends(service)):
    """Ghi một lần mua trong quá khứ (ví dụ đọc từ lịch sử lệnh).
    Sổ tổng: chỉ cho tiểu danh mục nhập tay, truyền account là mã tiểu danh mục (vd "vps")."""
    if broker == "ledger":
        ledger = request.app.state.ledger
        acc_obj = next((a for a in ledger.accounts() if a.id == account), None)
        if acc_obj is None or acc_obj.source != "manual":
            raise _err(ValueError("Với sổ danh mục, chọn một tiểu danh mục nhập tay (ví dụ SSI, VPS). Phần đồng bộ thì ghi ở broker gốc."))
        lp = next((p for p in ledger.positions(acc_obj.id) if p.symbol == body.symbol.upper()), None)
        if lp is None:
            raise _err(ValueError(f"{acc_obj.name} không nắm giữ {body.symbol.upper()}"))
        acc_id, symbol, held, avg = acc_obj.id, lp.symbol, lp.quantity, lp.avg_cost
    else:
        acc = await svc.resolve_account(broker, account)
        pos = next((p for p in (await svc.context(broker, acc.id)).positions if p.symbol == body.symbol.upper()), None)
        if pos is None:
            raise _err(ValueError(f"Tiểu khoản {acc.id} không nắm giữ {body.symbol.upper()}"))
        acc_id, symbol, held, avg = acc.id, pos.symbol, pos.quantity, pos.avg_cost
    open_qty = sum(l.remaining for l in r.lots(broker, acc_id, symbol, open_only=True))
    if open_qty + body.quantity > held:
        raise _err(ValueError(f"Tổng các lần mua ({open_qty + body.quantity:,} cp) vượt khối lượng đang giữ ({held:,} cp)".replace(",", ".")))
    add_on = body.add_on_loss if body.add_on_loss is not None else body.price < avg
    try:
        lot = r.add(broker=broker, account_id=acc_id, symbol=symbol, buy_date=body.buy_date, quantity=body.quantity,
                    price=body.price, source="manual", add_on_loss=add_on, stop_price=body.stop_price, note=body.note)
    except LotError as e:
        raise _err(e) from e
    svc.invalidate(broker)
    return lot


class LotPatch(BaseModel):
    stop_price: float | None = Field(default=None, gt=0)
    add_on_loss: bool | None = None
    note: str | None = Field(default=None, max_length=300)
    buy_date: date | None = None
    price: float | None = Field(default=None, gt=0)
    quantity: int | None = Field(default=None, gt=0)


@router.put("/{lot_id}", response_model=Lot)
async def update_lot(lot_id: int, body: LotPatch, r: LotRepo = Depends(repo), svc: PortfolioService = Depends(service)):
    try:
        lot = r.get(lot_id)
        f = body.model_dump(exclude_unset=True)
        if lot.source == "auto":
            f = {k: v for k, v in f.items() if k in ("stop_price", "add_on_loss", "note", "price")}
        if f.get("buy_date") and f["buy_date"] > now_vn().date():
            raise LotError("Ngày mua không được ở tương lai")
        lot = r.update(lot_id, **f)
    except LotError as e:
        raise _err(e) from e
    svc.invalidate()
    return lot


@router.delete("/{lot_id}")
async def delete_lot(lot_id: int, r: LotRepo = Depends(repo), svc: PortfolioService = Depends(service)):
    try:
        r.delete(lot_id)
    except LotError as e:
        raise _err(e) from e
    svc.invalidate()
    return {"ok": True}

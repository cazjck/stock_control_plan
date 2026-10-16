"""API nhật ký đảo hàng (mục 6b). Chỉ ghi vào SQLite của ứng dụng; app không đặt lệnh."""
from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..models import RotationTrade
from ..risk.rotation import current_cycle
from ..services.portfolio import PortfolioService
from ..storage.rotation import RotationRepo
from ..util import now_vn
from .deps import require_token, service

router = APIRouter(prefix="/api/rotations", dependencies=[Depends(require_token)])


def repo(request: Request) -> RotationRepo:
    return request.app.state.rotations


def _err(msg: str) -> HTTPException:
    return HTTPException(422, {"code": "ROTATION", "message": msg})


class RotationIn(BaseModel):
    symbol: str = Field(min_length=2, max_length=10)
    side: Literal["sell", "buy"]
    trade_date: date
    quantity: int = Field(gt=0)
    price: float = Field(gt=0)
    note: str | None = Field(default=None, max_length=300)


@router.get("", response_model=list[RotationTrade])
async def list_trades(broker: str, account: str | None = None, symbol: str | None = None, r: RotationRepo = Depends(repo)):
    return r.trades(broker, account, symbol)


@router.post("", response_model=RotationTrade)
async def add_trade(body: RotationIn, request: Request, broker: str, account: str | None = None,
                    r: RotationRepo = Depends(repo), svc: PortfolioService = Depends(service)):
    """Ghi một lần bán hoặc mua lại đã khớp ở công ty chứng khoán.
    Sổ tổng: truyền account là mã tiểu danh mục (vd "vps") của dòng đang xem."""
    if body.trade_date > now_vn().date():
        raise _err("Ngày giao dịch không được ở tương lai")
    symbol = body.symbol.upper()
    if broker == "ledger":
        if not account or account == "ALL" or account not in {a.id for a in request.app.state.ledger.accounts()}:
            raise _err("Với sổ danh mục, chọn tiểu danh mục của dòng (ví dụ vps, ssi)")
        acc_id = account
    else:
        acc_id = (await svc.resolve_account(broker, account)).id
    if body.side == "buy":
        ctx = await svc.context(broker, acc_id)
        df = ctx.frames.get(symbol)
        cyc = None
        if df is not None and len(df):
            cyc, _ = current_cycle(r.trades(broker, acc_id, symbol), df, ctx.rules, body.trade_date)
        if cyc is None:
            raise _err("Chưa có lần bán đảo hàng nào đang chờ mua lại cho mã này")
        if body.quantity > cyc.open_qty:
            raise _err(f"Mua lại tối đa {cyc.open_qty:,} cổ phiếu, đúng số đã bán. Đảo hàng không được làm tăng vị thế.".replace(",", "."))
    t = r.add(broker=broker, account_id=acc_id, symbol=symbol, side=body.side, trade_date=body.trade_date,
              quantity=body.quantity, price=body.price, note=body.note)
    svc.invalidate(broker)
    return t


@router.delete("/{trade_id}")
async def delete_trade(trade_id: int, r: RotationRepo = Depends(repo), svc: PortfolioService = Depends(service)):
    if r.get(trade_id) is None:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "Không có giao dịch này"})
    r.delete(trade_id)
    svc.invalidate()
    return {"ok": True}

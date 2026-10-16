"""API quyết định gồng có kế hoạch (mục 6c). Chỉ ghi vào SQLite của ứng dụng; app không đặt lệnh."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..models import HoldDecision
from ..services.portfolio import PortfolioService
from ..storage.holds import HoldRepo
from ..util import now_vn
from .deps import require_token, service

router = APIRouter(prefix="/api/holds", dependencies=[Depends(require_token)])


def repo(request: Request) -> HoldRepo:
    return request.app.state.holds


def _err(msg: str) -> HTTPException:
    return HTTPException(422, {"code": "HOLD", "message": msg})


class HoldIn(BaseModel):
    symbol: str = Field(min_length=2, max_length=10)
    exit_close_below: float | None = Field(default=None, gt=0)    # để trống: mức vô hiệu kỹ thuật, không có thì đáy 20 phiên × 0,97
    ratio_floor_pct: float | None = Field(default=None, gt=0, lt=1000)   # để trống: ngưỡng duy trì
    review_on: date | None = None                                  # để trống: 30 ngày sau
    reason: str = Field(min_length=10, max_length=500)


@router.get("", response_model=list[HoldDecision])
async def list_holds(broker: str, account: str | None = None, r: HoldRepo = Depends(repo)):
    return r.list(broker, account)


@router.put("", response_model=HoldDecision)
async def put_hold(body: HoldIn, request: Request, broker: str, account: str | None = None,
                   r: HoldRepo = Depends(repo), svc: PortfolioService = Depends(service)):
    """Ghi hoặc sửa quyết định gồng của một dòng. Sổ tổng: account là mã tiểu danh mục của dòng (vd tcbs-…, ssi)."""
    symbol = body.symbol.upper()
    if broker == "ledger":
        if not account or account == "ALL" or account not in {a.id for a in request.app.state.ledger.accounts()}:
            raise _err("Với sổ danh mục, chọn tiểu danh mục của dòng")
        acc_id = account
    else:
        acc_id = (await svc.resolve_account(broker, account)).id
    ctx = await svc.context(broker, acc_id)
    ev = next((e for e in ctx.evals if e.symbol == symbol and (e.account_id or acc_id) == acc_id), None)
    if ev is None:
        raise _err(f"Không nắm giữ {symbol} ở tài khoản này")
    exit_px = body.exit_close_below
    if exit_px is None and ev.technical and ev.technical.invalidation:
        exit_px = round(ev.technical.invalidation, -1)     # mức vô hiệu của kế hoạch kỹ thuật (mục 6d)
    if exit_px is None:
        if not ev.indicators.low20:
            raise _err("Chưa có đáy 20 phiên để đặt giá thoát mặc định, hãy nhập giá thoát")
        exit_px = round(ev.indicators.low20 * 0.97, -1)
    if exit_px >= ev.price:
        raise _err("Giá thoát phải thấp hơn giá hiện tại, nếu không thì quyết định đã hết hiệu lực ngay khi ghi")
    today = now_vn().date()
    review = body.review_on or today + timedelta(days=30)
    if review <= today:
        raise _err("Ngày xem lại phải sau hôm nay")
    d = r.upsert(broker=broker, account_id=acc_id, symbol=symbol, exit_close_below=exit_px,
                 ratio_floor_pct=body.ratio_floor_pct, review_on=review, reason=body.reason.strip(), decided_at=today)
    svc.invalidate(broker)
    return d


@router.delete("/{hold_id}")
async def delete_hold(hold_id: int, r: HoldRepo = Depends(repo), svc: PortfolioService = Depends(service)):
    if r.by_id(hold_id) is None:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "Không có quyết định này"})
    r.delete(hold_id)
    svc.invalidate()
    return {"ok": True}

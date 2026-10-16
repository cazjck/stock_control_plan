"""Các endpoint REST. Toàn bộ chỉ đọc dữ liệu từ broker; không có endpoint nào đặt lệnh."""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ValidationError

from ..config import Settings
from ..models import (
    DeleverageOverview,
    BoardQuote, BoardResponse,
    Account, AlertRecord, Interval, MarginOverview, MarketInfo, OverviewResponse, PositionEval, PositionPlan,
    ScenarioRequest, ScenarioResult, SessionInfo, SizingPlan,
)
from ..risk.deleverage import build_overview
from ..risk.scenario import ScenarioError
from ..util import now_vn
from ..services.portfolio import PortfolioService
from ..services.rules_service import RulesService
from ..storage.db import Store
from .deps import require_token, rules_service, service, settings_dep, store, streams

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])
public = APIRouter(prefix="/api")


def _broker(svc: PortfolioService, broker: str | None) -> str:
    if broker:
        return broker
    if not svc.adapters:
        raise HTTPException(404, "Chưa bật broker nào")
    return next(iter(svc.adapters))


# ---------- meta ----------

@public.get("/health")
async def health(settings: Settings = Depends(settings_dep)) -> dict[str, Any]:
    return {"ok": True, "read_only": True, "brokers": settings.enabled_brokers,
            "protected": bool(settings.app_access_token)}


class BrokerStatus(BaseModel):
    name: str
    display_name: str
    session: SessionInfo


@router.get("/brokers", response_model=list[BrokerStatus])
async def brokers(svc: PortfolioService = Depends(service)):
    return [BrokerStatus(name=n, display_name=a.display_name, session=a.session_info()) for n, a in svc.adapters.items()]


class AuthBody(BaseModel):
    otp: str | None = None


@router.post("/brokers/{name}/auth", response_model=SessionInfo)
async def broker_auth(name: str, body: AuthBody, svc: PortfolioService = Depends(service)):
    """Đăng nhập broker (lấy token phiên). Với TCBS cần iOTP; không liên quan tới đặt lệnh."""
    info = await svc.adapter(name).authenticate(body.otp)
    svc.invalidate(name)
    return info


@router.get("/accounts", response_model=list[Account])
async def accounts(broker: str | None = None, svc: PortfolioService = Depends(service)):
    return await svc.accounts(_broker(svc, broker))


# ---------- dashboard ----------

@router.get("/overview", response_model=OverviewResponse)
async def overview(broker: str | None = None, account: str | None = None, refresh: bool = False,
                   svc: PortfolioService = Depends(service)):
    return await svc.overview(_broker(svc, broker), account, force=refresh)


class PositionsResponse(BaseModel):
    positions: list[PositionEval]
    market: MarketInfo
    notes: list[str]


@router.get("/positions", response_model=PositionsResponse)
async def positions(broker: str | None = None, account: str | None = None, svc: PortfolioService = Depends(service)):
    b = _broker(svc, broker)
    ctx = await svc.context(b, account)
    return PositionsResponse(positions=ctx.evals, market=ctx.market, notes=ctx.notes)


@router.get("/symbols/{symbol}/chart")
async def chart(symbol: str, broker: str | None = None, account: str | None = None,
                interval: Interval = Interval.D1, count: int = Query(250, ge=30, le=600), row: str | None = None,
                svc: PortfolioService = Depends(service)):
    return await svc.chart(_broker(svc, broker), account, symbol, interval, count, row)


@router.get("/board", response_model=BoardResponse)
async def board(broker: str | None = None, account: str | None = None, svc: PortfolioService = Depends(service)):
    """Bảng giá cho các mã trong danh mục đang chọn."""
    return await svc.board(_broker(svc, broker), account)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@router.get("/board/stream")
async def board_stream(request: Request, broker: str | None = None, account: str | None = None,
                       svc: PortfolioService = Depends(service), reg=Depends(streams)):
    """Bảng giá thời gian thực qua Server-Sent Events. Sự kiện: snapshot, quote, index, status."""
    b = _broker(svc, broker)
    snap = await svc.board(b, account)
    hub = reg.hub_for(b)
    symbols = {r.symbol for r in snap.rows}

    async def gen():
        yield _sse("snapshot", {**snap.model_dump(mode="json"), "live": hub is not None,
                                "status": hub.status if hub else "unsupported"})
        if hub is None:
            return
        q = hub.subscribe()
        fields = set(BoardQuote.model_fields)
        hub.watch(symbols, {r.symbol: BoardQuote(**r.model_dump(include=fields)) for r in snap.rows})
        try:
            yield _sse("status", {"status": hub.status, "message": hub.message})
            while not await request.is_disconnected():
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": giữ kết nối\n\n"
                    continue
                if ev["type"] == "quote" and ev["row"]["symbol"] not in symbols:
                    continue
                yield _sse(ev["type"], ev)
        finally:
            hub.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/margin", response_model=MarginOverview)
async def margin(broker: str | None = None, account: str | None = None, svc: PortfolioService = Depends(service)):
    return (await svc.context(_broker(svc, broker), account)).margin


@router.get("/margin/plan", response_model=DeleverageOverview)
async def margin_plan(broker: str | None = None, account: str | None = None, svc: PortfolioService = Depends(service)):
    """Kế hoạch hạ margin từng tài khoản (mục 5b). Chỉ tính toán, không đặt lệnh."""
    ctx = await svc.context(_broker(svc, broker), account)
    return build_overview(ctx.margin.buckets, ctx.evals, ctx.margin.loans, ctx.rules, now_vn().date())


# ---------- kịch bản giả định và máy tính khối lượng (chỉ tính toán) ----------

@router.post("/scenarios/run", response_model=ScenarioResult)
async def scenario_run(body: ScenarioRequest, broker: str | None = None, account: str | None = None,
                       svc: PortfolioService = Depends(service)):
    """Tính RTT, lãi lỗ, lãi vay sau một kịch bản giả định. POST chỉ vì có thân yêu cầu: không ghi gì, không gọi broker."""
    try:
        return await svc.scenario(_broker(svc, broker), account, body)
    except ScenarioError as e:
        raise HTTPException(422, {"code": "INVALID_SCENARIO", "message": str(e)}) from e


@router.get("/sizing", response_model=SizingPlan)
async def sizing(symbol: str = Query(..., pattern=r"^[A-Za-z0-9]{1,12}$"), price: float = Query(..., gt=0),
                 stop: float | None = Query(None, gt=0, description="Giá cắt lỗ dự kiến; bỏ trống thì tính theo luật"),
                 broker: str | None = None, account: str | None = None, svc: PortfolioService = Depends(service)):
    try:
        return await svc.sizing(_broker(svc, broker), account, symbol, price, stop)
    except ValueError as e:
        raise HTTPException(422, {"code": "INVALID_SIZING", "message": str(e)}) from e


# ---------- cảnh báo ----------

@router.get("/alerts", response_model=list[AlertRecord])
async def alerts(status: str | None = "active", broker: str | None = None, account: str | None = None,
                 st: Store = Depends(store)):
    return st.list_alerts(broker, account, None if status in (None, "all") else status)


class ResolveBody(BaseModel):
    note: str | None = None


NON_DISMISSABLE = {"add_on_lot", "hold_exit"}  # chỉ đóng khi đã bán, hoặc ghi rõ lý do không bán


def _alert(st: Store, alert_id: int) -> AlertRecord:
    a = next((x for x in st.list_alerts(limit=100_000) if x.id == alert_id), None)
    if not a:
        raise HTTPException(404, "Không có cảnh báo này")
    return a


@router.post("/alerts/{alert_id}/ack", response_model=AlertRecord)
async def ack_alert(alert_id: int, st: Store = Depends(store)):
    if _alert(st, alert_id).rule in NON_DISMISSABLE:
        raise HTTPException(409, {"code": "NOT_DISMISSABLE",
                                  "message": "Cảnh báo bán lô không thể chỉ đánh dấu đã xem. Hãy bán theo luật, hoặc ghi rõ lý do không bán."})
    a = st.set_alert_status(alert_id, "acked")
    if not a:
        raise HTTPException(404, "Không có cảnh báo này")
    return a


@router.post("/alerts/{alert_id}/resolve", response_model=AlertRecord)
async def resolve_alert(alert_id: int, body: ResolveBody, st: Store = Depends(store)):
    if _alert(st, alert_id).rule in NON_DISMISSABLE and not (body.note or "").strip():
        raise HTTPException(422, {"code": "NOTE_REQUIRED", "message": "Ghi lại bạn đã làm gì hoặc vì sao không bán lô này."})
    a = st.set_alert_status(alert_id, "resolved", body.note)
    if not a:
        raise HTTPException(404, "Không có cảnh báo này")
    return a


# ---------- kế hoạch từng mã ----------

class PlanBody(BaseModel):
    mode: Literal["swing", "dca"] = "swing"
    entry_date: date | None = None
    has_thesis: bool | None = None
    ladder_done: int = 0
    note: str | None = None


@router.get("/plans", response_model=list[PositionPlan])
async def list_plans(broker: str | None = None, account: str | None = None,
                     svc: PortfolioService = Depends(service), st: Store = Depends(store)):
    b = _broker(svc, broker)
    acc = await svc.resolve_account(b, account)
    return list(st.get_plans(b, acc.id).values())


@router.put("/plans/{symbol}", response_model=PositionPlan)
async def put_plan(symbol: str, body: PlanBody, broker: str | None = None, account: str | None = None,
                   svc: PortfolioService = Depends(service), st: Store = Depends(store)):
    b = _broker(svc, broker)
    acc = await svc.resolve_account(b, account)
    plan = PositionPlan(broker=b, account_id=acc.id, symbol=symbol.upper(), **body.model_dump())
    st.upsert_plan(plan)
    svc.invalidate(b)
    return plan


# ---------- thiết lập luật ----------

class RulesResponse(BaseModel):
    effective: dict[str, Any]
    defaults: dict[str, Any]
    has_overrides: bool


class RulesPatch(BaseModel):
    patch: dict[str, Any]
    confirm_open_positions: bool = False


async def _has_open_positions(svc: PortfolioService, broker: str | None) -> bool:
    try:
        b = _broker(svc, broker)
        ctx = await svc.context(b, None)
        return bool(ctx.positions)
    except Exception:  # noqa: BLE001 - không xác định được thì coi như đang có vị thế
        return True


@router.get("/settings/rules", response_model=RulesResponse)
async def get_rules(rs: RulesService = Depends(rules_service)):
    return RulesResponse(effective=rs.effective_dict(), defaults=rs.defaults_dict(), has_overrides=rs.has_overrides())


@router.put("/settings/rules", response_model=RulesResponse)
async def put_rules(body: RulesPatch, broker: str | None = None, rs: RulesService = Depends(rules_service),
                    svc: PortfolioService = Depends(service)):
    had_open = await _has_open_positions(svc, broker)
    if had_open and not body.confirm_open_positions:
        raise HTTPException(409, {
            "code": "OPEN_POSITIONS",
            "message": "Đang có vị thế mở. Bộ luật chỉ nên đổi khi không có vị thế, để tránh sửa luật cho hợp cảm xúc. "
                       "Gửi confirm_open_positions=true nếu bạn chắc chắn."})
    try:
        rs.update(body.patch, had_open_positions=had_open)
    except ValidationError as e:
        raise HTTPException(422, {"code": "INVALID_RULES", "message": str(e.errors()[0]["msg"]),
                                  "errors": e.errors(include_url=False, include_context=False)}) from e
    svc.invalidate()
    return RulesResponse(effective=rs.effective_dict(), defaults=rs.defaults_dict(), has_overrides=rs.has_overrides())


@router.delete("/settings/rules", response_model=RulesResponse)
async def reset_rules(broker: str | None = None, rs: RulesService = Depends(rules_service),
                      svc: PortfolioService = Depends(service)):
    rs.reset(had_open_positions=await _has_open_positions(svc, broker))
    svc.invalidate()
    return RulesResponse(effective=rs.effective_dict(), defaults=rs.defaults_dict(), has_overrides=False)


@router.get("/settings/rule-changes")
async def rule_changes(st: Store = Depends(store)):
    return st.list_rule_changes()


# ---------- snapshot ----------

@router.get("/snapshots")
async def snapshots(broker: str | None = None, account: str | None = None, days: int = Query(30, ge=1, le=365),
                    svc: PortfolioService = Depends(service), st: Store = Depends(store)):
    b = _broker(svc, broker)
    acc = await svc.resolve_account(b, account)
    return st.list_snapshots(b, acc.id, days)


@router.post("/snapshots/run")
async def run_snapshot(broker: str | None = None, account: str | None = None, svc: PortfolioService = Depends(service)):
    return await svc.snapshot(_broker(svc, broker), account)

"""FastAPI app: dashboard quản trị rủi ro chứng khoán, CHỈ ĐỌC."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, Request
from starlette.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.ledger_routes import router as ledger_router
from .api.lots_routes import router as lots_router
from .api.rotation_routes import router as rotation_router
from .api.hold_routes import router as hold_router
from .api.routes import public, router
from .brokers.base import AuthRequired, BrokerError, ReadOnlyViolation
from .brokers.registry import build_adapters
from .config import get_settings
from .services.portfolio import NotFound, PortfolioService
from .services.rules_service import RulesService
from .storage.db import Store
from .storage.ledger import LedgerRepo
from .storage.lots import LotRepo
from .storage.holds import HoldRepo
from .storage.rotation import RotationRepo
from .streaming.board_stream import StreamRegistry
from .services.lots import LotService

log = logging.getLogger("stockctl")
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


async def daily_snapshot(svc: PortfolioService) -> None:
    """Chụp danh mục cuối ngày cho mọi broker đã đăng nhập (mục 7.1). Sổ tổng chỉ chụp mục "Tất cả"."""
    for name, ad in svc.adapters.items():
        if not ad.session_info().authenticated:
            continue
        try:
            accounts = await ad.list_accounts()
            if name == "ledger":
                accounts = [a for a in accounts if a.id == "ALL"] if len(accounts) > 1 else []
            for acc in accounts:
                await svc.snapshot(name, acc.id)
        except BrokerError as e:
            log.warning("snapshot %s lỗi: %s", name, e.message)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    store = Store(s.resolved_data_dir / "stockctl.sqlite")
    rules = RulesService(store)
    ledger = LedgerRepo(store)
    lot_repo = LotRepo(store)
    adapters = build_adapters(s, ledger)
    rotation_repo = RotationRepo(store)
    hold_repo = HoldRepo(store)
    svc = PortfolioService(s, adapters, store, rules, LotService(lot_repo, ledger), rotation_repo, hold_repo)
    app.state.store, app.state.rules, app.state.portfolio, app.state.ledger = store, rules, svc, ledger
    app.state.lots = lot_repo
    app.state.rotations = rotation_repo
    app.state.holds = hold_repo
    app.state.streams = StreamRegistry(adapters)

    sched = AsyncIOScheduler(timezone=s.timezone)
    sched.add_job(daily_snapshot, CronTrigger(day_of_week="mon-fri", hour=15, minute=15, timezone=s.timezone),
                  args=[svc], id="daily_snapshot", replace_existing=True)
    sched.start()
    try:
        yield
    finally:
        sched.shutdown(wait=False)
        await app.state.streams.close()
        for a in adapters.values():
            await a.aclose()
        store.close()


class SpaStaticFiles(StaticFiles):
    """Phục vụ frontend đã build; đường dẫn của router phía trình duyệt (vd /positions) trả về index.html."""

    async def get_response(self, path: str, scope):  # type: ignore[override]
        try:
            return await super().get_response(path, scope)
        except HTTPException as e:
            if e.status_code == 404 and not path.startswith("api/") and "." not in path.rsplit("/", 1)[-1]:
                return await super().get_response("index.html", scope)
            raise


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="Stock Control Plan", version="0.1.0", lifespan=lifespan,
                  description="Dashboard quản trị rủi ro chứng khoán Việt Nam. CHỈ ĐỌC: không đặt lệnh.")
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_list, allow_methods=["GET", "POST", "PUT", "DELETE"],
                       allow_headers=["*"])

    @app.exception_handler(AuthRequired)
    async def _auth(_: Request, e: AuthRequired):
        return JSONResponse(status_code=401, content={"detail": {"code": "AUTH_REQUIRED", "message": e.message}})

    @app.exception_handler(BrokerError)
    async def _broker(_: Request, e: BrokerError):
        return JSONResponse(status_code=502, content={"detail": {"code": "BROKER_ERROR", "message": e.message}})

    @app.exception_handler(NotFound)
    async def _nf(_: Request, e: NotFound):
        return JSONResponse(status_code=404, content={"detail": {"code": "NOT_FOUND", "message": str(e)}})

    @app.exception_handler(ReadOnlyViolation)
    async def _ro(_: Request, e: ReadOnlyViolation):
        return JSONResponse(status_code=403, content={"detail": {"code": "READ_ONLY", "message": str(e)}})

    app.include_router(public)
    app.include_router(router)
    app.include_router(ledger_router)
    app.include_router(lots_router)
    app.include_router(rotation_router)
    app.include_router(hold_router)
    if FRONTEND_DIST.is_dir():
        app.mount("/", SpaStaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    return app


app = create_app()

"""FastAPI app: dashboard quản trị rủi ro chứng khoán, CHỈ ĐỌC."""
from __future__ import annotations

import asyncio

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
from .api.notify_routes import router as notify_router
from .notify.service import NotifyService
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


async def notify_cycle(notify: NotifyService) -> None:
    try:
        n = await notify.run_cycle()
        if n:
            log.info("đã gửi %d cảnh báo qua Telegram", n)
    except Exception as e:  # noqa: BLE001 - lỗi thông báo không được làm dừng lịch
        log.error("thông báo lỗi: %s", e)


async def brief_job(notify: NotifyService, kind: str) -> None:
    try:
        await notify.send_brief(kind, scheduled=True)
    except Exception as e:  # noqa: BLE001
        log.error("bản tin %s lỗi: %s", kind, e)


def daily_backup(data_dir) -> None:
    """Mục vận hành: sao lưu SQLite mỗi đêm, giữ 14 bản."""
    from .services.backup import backup_sqlite
    from .util import now_vn
    try:
        out = backup_sqlite(data_dir / "stockctl.sqlite", data_dir / "backups", now_vn().date())
        log.info("đã sao lưu %s", out.name)
    except Exception as e:  # noqa: BLE001 - lỗi sao lưu không được làm dừng ứng dụng
        log.error("sao lưu lỗi: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    store = Store(s.resolved_data_dir / "stockctl.sqlite")
    rules = RulesService(store)
    ledger = LedgerRepo(store)
    lot_repo = LotRepo(store)
    adapters = build_adapters(s, ledger, lambda: store.kv_get("price_source"))
    rotation_repo = RotationRepo(store)
    hold_repo = HoldRepo(store)
    svc = PortfolioService(s, adapters, store, rules, LotService(lot_repo, ledger), rotation_repo, hold_repo)
    app.state.store, app.state.rules, app.state.portfolio, app.state.ledger = store, rules, svc, ledger
    app.state.lots = lot_repo
    app.state.rotations = rotation_repo
    app.state.holds = hold_repo
    notify = NotifyService(store, svc, s.telegram_bot_token, s.telegram_chat_id, s.app_public_url)
    app.state.notify = notify
    app.state.streams = StreamRegistry(adapters)

    sched = AsyncIOScheduler(timezone=s.timezone)
    sched.add_job(daily_snapshot, CronTrigger(day_of_week="mon-fri", hour=15, minute=15, timezone=s.timezone),
                  args=[svc], id="daily_snapshot", replace_existing=True)
    # thông báo: 5 phút một lần trong giờ giao dịch, thêm một lượt trước phiên và sau phiên
    sched.add_job(notify_cycle, CronTrigger(day_of_week="mon-fri", hour="9-14", minute="*/5", timezone=s.timezone),
                  args=[notify], id="notify_intraday", replace_existing=True, max_instances=1, coalesce=True)
    sched.add_job(notify_cycle, CronTrigger(day_of_week="mon-fri", hour="8,15", minute="30,5", timezone=s.timezone),
                  args=[notify], id="notify_edges", replace_existing=True, max_instances=1, coalesce=True)
    sched.add_job(brief_job, CronTrigger(day_of_week="mon-fri", hour=8, minute=45, timezone=s.timezone),
                  args=[notify, "open"], id="brief_open", replace_existing=True)
    sched.add_job(brief_job, CronTrigger(day_of_week="mon-fri", hour=15, minute=20, timezone=s.timezone),
                  args=[notify, "close"], id="brief_close", replace_existing=True)
    sched.add_job(daily_backup, CronTrigger(hour=23, minute=30, timezone=s.timezone),
                  args=[s.resolved_data_dir], id="daily_backup", replace_existing=True)
    sched.start()
    poller = asyncio.create_task(notify.poll_forever())
    try:
        yield
    finally:
        poller.cancel()
        sched.shutdown(wait=False)
        await app.state.streams.close()
        for a in adapters.values():
            await a.aclose()
        store.close()


class SpaStaticFiles(StaticFiles):
    """Phục vụ frontend đã build; đường dẫn của router phía trình duyệt (vd /positions) trả về index.html."""

    async def get_response(self, path: str, scope):  # type: ignore[override]
        try:
            resp = await super().get_response(path, scope)
        except HTTPException as e:
            if e.status_code == 404 and not path.startswith("api/") and "." not in path.rsplit("/", 1)[-1]:
                resp = await super().get_response("index.html", scope)
            else:
                raise
        return self._cache_headers(path, resp)

    @staticmethod
    def _cache_headers(path: str, resp):
        """index.html luôn hỏi lại máy chủ (bản mới hiện ngay sau khi triển khai); file trong assets/ có mã băm
        trong tên nên lưu đệm lâu dài được."""
        if path.startswith("assets/"):
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif resp.media_type and "html" in resp.media_type:
            resp.headers["Cache-Control"] = "no-cache"
        return resp


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
    app.include_router(notify_router)
    if FRONTEND_DIST.is_dir():
        app.mount("/", SpaStaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    return app


app = create_app()

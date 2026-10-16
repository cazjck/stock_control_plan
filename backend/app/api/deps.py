from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException, Request

from ..config import Settings, get_settings
from ..services.portfolio import PortfolioService
from ..services.rules_service import RulesService
from ..storage.db import Store


def settings_dep() -> Settings:
    return get_settings()


async def require_token(request: Request, settings: Settings = Depends(settings_dep)) -> None:
    """Nếu APP_ACCESS_TOKEN được đặt thì mọi request /api phải gửi header X-App-Token khớp."""
    expected = settings.app_access_token
    if not expected:
        return
    # EventSource của trình duyệt không gửi được header, nên luồng SSE được phép gửi mã qua tham số app_token
    given = request.headers.get("x-app-token", "") or request.query_params.get("app_token", "")
    if not hmac.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail={"code": "APP_TOKEN", "message": "Thiếu hoặc sai X-App-Token"})


def service(request: Request) -> PortfolioService:
    return request.app.state.portfolio


def rules_service(request: Request) -> RulesService:
    return request.app.state.rules


def store(request: Request) -> Store:
    return request.app.state.store


def streams(request: Request):
    return request.app.state.streams

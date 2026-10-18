"""API cài đặt thông báo Telegram. Chỉ lưu cấu hình vào SQLite của ứng dụng và gửi tin cho chính người dùng."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..notify.service import NotifyService
from ..notify.telegram import TelegramError
from .deps import require_token

router = APIRouter(prefix="/api/notify", dependencies=[Depends(require_token)])


def svc(request: Request) -> NotifyService:
    return request.app.state.notify


def _err(e: Exception) -> HTTPException:
    return HTTPException(422, {"code": "TELEGRAM", "message": str(e)})


class TelegramIn(BaseModel):
    token: str | None = Field(default=None, max_length=200)
    chat_id: int | str | None = None
    chat_title: str | None = Field(default=None, max_length=200)
    enabled: bool | None = None
    min_severity: Literal["info", "warning", "critical"] | None = None
    app_url: str | None = Field(default=None, max_length=200)


class DiscoverIn(BaseModel):
    token: str | None = Field(default=None, max_length=200)


@router.get("/telegram")
async def status(n: NotifyService = Depends(svc)):
    return n.status()


@router.put("/telegram")
async def save(body: TelegramIn, n: NotifyService = Depends(svc)):
    if body.token:
        try:
            await n.client(body.token).me()
        except TelegramError as e:
            raise _err(e) from None
    return n.save(body.model_dump(exclude_none=True))


@router.post("/telegram/discover")
async def discover(body: DiscoverIn, n: NotifyService = Depends(svc)):
    """Tên bot và các cuộc trò chuyện đã nhắn /start cho bot."""
    try:
        c = n.client(body.token)
        me = await c.me()
        return {"bot": me.get("username"), "chats": await c.chats()}
    except TelegramError as e:
        raise _err(e) from None


@router.post("/telegram/test")
async def test(n: NotifyService = Depends(svc)):
    try:
        await n.send_test()
    except TelegramError as e:
        raise _err(e) from None
    return n.status()


@router.post("/run")
async def run(n: NotifyService = Depends(svc)):
    """Chạy ngay một lượt: làm mới dữ liệu và gửi cảnh báo mới."""
    return {"sent": await n.run_cycle(), **n.status()}

"""Gửi tin Telegram cho CHÍNH người dùng. Chỉ gọi api.telegram.org với ba phương thức: getMe, getUpdates, sendMessage.
Không liên quan tới broker; không có đường nào dẫn tới đặt lệnh. Lỗi trả về không bao giờ chứa mã bot."""
from __future__ import annotations

from typing import Any

import httpx

API = "https://api.telegram.org"
METHODS = frozenset({"getMe", "getUpdates", "sendMessage"})
MAX_LEN = 4096


class TelegramError(Exception):
    pass


class Telegram:
    def __init__(self, token: str, client: httpx.AsyncClient | None = None):
        if not token or ":" not in token:
            raise TelegramError("Mã bot không đúng dạng (lấy từ BotFather, có dấu hai chấm)")
        self._token = token
        self._client = client

    async def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        if method not in METHODS:
            raise TelegramError(f"Phương thức {method} không được phép")
        url = f"{API}/bot{self._token}/{method}"
        own = self._client is None
        client = self._client or httpx.AsyncClient(timeout=10)
        try:
            if method == "sendMessage":
                r = await client.post(url, json=params or {})
            else:
                r = await client.get(url, params=params or {})
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise TelegramError(f"Không kết nối được Telegram ({type(e).__name__})") from None
        finally:
            if own:
                await client.aclose()
        if not isinstance(data, dict) or not data.get("ok"):
            desc = data.get("description") if isinstance(data, dict) else None
            raise TelegramError(f"Telegram từ chối: {desc or r.status_code}")
        return data.get("result")

    async def me(self) -> dict[str, Any]:
        return await self.call("getMe")

    async def chats(self) -> list[dict[str, Any]]:
        """Các cuộc trò chuyện đã nhắn cho bot gần đây (người dùng cần gửi /start cho bot trước)."""
        out: dict[int, dict[str, Any]] = {}
        for u in await self.call("getUpdates", {"limit": 50}) or []:
            msg = u.get("message") or u.get("channel_post") or u.get("my_chat_member") or {}
            c = msg.get("chat") or {}
            if "id" in c:
                name = c.get("title") or " ".join(x for x in (c.get("first_name"), c.get("last_name")) if x) or c.get("username") or str(c["id"])
                out[c["id"]] = {"id": c["id"], "type": c.get("type", ""), "title": name}
        return list(out.values())

    async def send(self, chat_id: int | str, text: str) -> None:
        if len(text) > MAX_LEN:
            text = text[: MAX_LEN - 1] + "…"
        await self.call("sendMessage", {"chat_id": chat_id, "text": text, "disable_web_page_preview": True})

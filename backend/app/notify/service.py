"""Thông báo Telegram (vận hành): định kỳ làm mới dữ liệu, sinh cảnh báo như trang Cảnh báo, gửi những cảnh báo
mới hoặc nặng lên. Cấu hình lưu trong SQLite của ứng dụng (kv 'telegram'), người dùng nhập ở trang Thiết lập.
Chỉ gửi tin cho người dùng; không đặt lệnh."""
from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

from ..brokers.base import AuthRequired, BrokerError
from ..services.portfolio import PortfolioService
from ..storage.db import Store
from ..util import now_vn
from .telegram import Telegram, TelegramError

log = logging.getLogger(__name__)
KEY = "telegram"
LEVELS = {"info": {"info", "warning", "critical"}, "warning": {"warning", "critical"}, "critical": {"critical"}}
ICON = {"critical": "🔴", "warning": "🟠", "info": "🔵"}


def mask(token: str | None) -> str | None:
    if not token:
        return None
    bot_id = token.split(":", 1)[0]
    return f"{bot_id}:••••{token[-4:]}"


class NotifyService:
    def __init__(self, store: Store, portfolio: PortfolioService, env_token: str | None = None,
                 env_chat: str | None = None, app_url: str | None = None):
        self.store = store
        self.portfolio = portfolio
        self._env_token, self._env_chat, self._env_url = env_token, env_chat, app_url

    # ---------- cấu hình ----------
    def config(self) -> dict[str, Any]:
        raw = self.store.kv_get(KEY)
        c = json.loads(raw) if raw else {}
        c.setdefault("token", self._env_token)
        c.setdefault("chat_id", self._env_chat)
        c.setdefault("enabled", bool(c.get("token") and c.get("chat_id")))
        c.setdefault("min_severity", "warning")
        c.setdefault("app_url", self._env_url)
        return c

    def save(self, patch: dict[str, Any]) -> dict[str, Any]:
        c = self.config()
        for k in ("token", "chat_id", "chat_title", "enabled", "min_severity", "app_url"):
            if k in patch and patch[k] is not None:
                c[k] = patch[k]
        if c.get("min_severity") not in LEVELS:
            c["min_severity"] = "warning"
        self.store.kv_set(KEY, json.dumps(c))
        return self.status()

    def _record(self, **kw: Any) -> None:
        c = self.config()
        c.update(kw)
        self.store.kv_set(KEY, json.dumps(c))

    def status(self) -> dict[str, Any]:
        c = self.config()
        return {"configured": bool(c.get("token") and c.get("chat_id")), "enabled": bool(c.get("enabled")),
                "token_masked": mask(c.get("token")), "chat_id": c.get("chat_id"), "chat_title": c.get("chat_title"),
                "min_severity": c.get("min_severity"), "app_url": c.get("app_url"),
                "last_sent_at": c.get("last_sent_at"), "last_error": c.get("last_error"), "last_run_at": c.get("last_run_at")}

    def client(self, token: str | None = None) -> Telegram:
        t = token or self.config().get("token")
        if not t:
            raise TelegramError("Chưa có mã bot")
        return Telegram(t)

    # ---------- gửi ----------
    def _link(self, path: str) -> str:
        url = (self.config().get("app_url") or "").rstrip("/")
        return f"\nMở app: {url}{path}" if url else ""

    def compose(self, alerts: list[dict[str, Any]], notices: list[str]) -> str | None:
        if not alerts and not notices:
            return None
        lines = [f"Mớn nước: {len(alerts)} cảnh báo mới" if alerts else "Mớn nước"]
        for n in notices:
            lines += ["", f"⚠️ {n}"]
        sev = {"critical": 0, "warning": 1, "info": 2}
        shown = sorted(alerts, key=lambda a: sev.get(a["severity"], 3))
        budget, used = 3600, 0
        for i, a in enumerate(shown):
            block = f"{ICON.get(a['severity'], '•')} {a['title']}\n{a['message'][:500]}"
            if used + len(block) > budget:
                lines += ["", f"…và {len(shown) - i} cảnh báo khác"]
                break
            lines += ["", block]
            used += len(block)
        return "\n".join(lines) + self._link("/alerts")

    async def send_test(self) -> None:
        c = self.config()
        if not c.get("chat_id"):
            raise TelegramError("Chưa chọn cuộc trò chuyện nhận tin")
        broker = "ledger" if "ledger" in self.portfolio.adapters else None
        all_open = self.store.list_alerts(broker=broker, status="open", limit=100)
        crit = [a for a in all_open if a.severity.value == "critical"]
        text = "Mớn nước: kết nối Telegram thành công. Từ giờ cảnh báo mới sẽ được gửi vào đây."
        if all_open:
            text += f"\n\nHiện có {len(all_open)} cảnh báo đang mở, {len(crit)} khẩn:"
            for a in crit[:8]:
                text += f"\n🔴 {a.title}"
        text += self._link("/alerts")
        await self.client().send(c["chat_id"], text)
        self._record(last_sent_at=now_vn().isoformat(), last_error=None)

    async def _targets(self) -> list[tuple[str, str]]:
        """Tài khoản cần làm mới: có Sổ tổng thì chỉ mục Tất cả (tránh báo trùng TCBS), không thì từng broker."""
        ads = self.portfolio.adapters
        out: list[tuple[str, str]] = []
        if "ledger" in ads:
            accs = await ads["ledger"].list_accounts()
            subs = [a for a in accs if a.id != "ALL"]
            if subs:
                return [("ledger", "ALL" if any(a.id == "ALL" for a in accs) else subs[0].id)]
        for name, ad in ads.items():
            if name == "ledger" or not ad.session_info().authenticated:
                continue
            out += [(name, a.id) for a in await ad.list_accounts()]
        return out

    def _session_notices(self) -> list[str]:
        notes = []
        today = now_vn().date().isoformat()
        for name, ad in self.portfolio.adapters.items():
            s = ad.session_info()
            if not s.configured or name in ("ledger", "demo"):
                continue
            soon = s.expires_at is not None and s.expires_at - now_vn() < timedelta(hours=2)
            if s.needs_otp or soon:
                key = f"notify_session_{name}_{today}"
                if self.store.kv_get(key):
                    continue
                self.store.kv_set(key, "1")
                when = f" lúc {s.expires_at:%H:%M}" if soon and s.expires_at else ""
                notes.append(f"Phiên {ad.display_name} {'sắp hết hạn' + when if soon and not s.needs_otp else 'đã hết hạn'}: "
                             f"nhập iOTP trong app để app tiếp tục theo dõi giá và ký quỹ.")
        return notes

    async def run_cycle(self) -> int:
        """Làm mới dữ liệu, gửi cảnh báo mới. Trả về số cảnh báo đã gửi."""
        c = self.config()
        self._record(last_run_at=now_vn().isoformat())
        if not (c.get("enabled") and c.get("token") and c.get("chat_id")):
            return 0
        targets = await self._targets()
        for broker, acc in targets:
            try:
                await self.portfolio.context(broker, acc, force=True)
            except AuthRequired:
                pass
            except BrokerError as e:
                log.warning("thông báo: không làm mới %s/%s: %s", broker, acc, e.message)
        # có Sổ tổng thì chỉ báo cảnh báo của Sổ tổng: TCBS đã nằm trong đó, tránh báo trùng
        only = {"ledger"} if any(b == "ledger" for b, _ in targets) else None
        alerts = self.store.pending_notifications(LEVELS[c["min_severity"]], only)
        text = self.compose(alerts, self._session_notices())
        if not text:
            return 0
        try:
            await self.client().send(c["chat_id"], text)
        except TelegramError as e:
            self._record(last_error=str(e))
            log.warning("gửi Telegram lỗi: %s", e)
            return 0
        self.store.mark_notified([a["id"] for a in alerts])
        self._record(last_sent_at=now_vn().isoformat(), last_error=None)
        return len(alerts)

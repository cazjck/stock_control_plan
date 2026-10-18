"""Thông báo Telegram: chỉ gọi api.telegram.org, không lộ mã bot, gửi mỗi cảnh báo một lần, báo lại khi nặng lên."""
from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest
import respx

from app.config import get_settings
from app.models import AlertCandidate, AlertSeverity
from app.notify.service import NotifyService, mask
from app.notify.telegram import Telegram, TelegramError

TOKEN = "123456:ABC-test-token-xyz"
BASE = f"https://api.telegram.org/bot{TOKEN}"


def test_notify_module_only_talks_to_telegram():
    src = "".join(p.read_text() for p in (Path(__file__).parents[1] / "app" / "notify").glob("*.py"))
    hosts = set(re.findall(r"https?://([a-zA-Z0-9.\-]+)", src))
    assert hosts == {"api.telegram.org"}
    assert "sendMessage" in src and "auth_post" not in src and "orders" not in src


def test_mask_and_token_format():
    assert mask(TOKEN) == "123456:••••-xyz"
    with pytest.raises(TelegramError):
        Telegram("not-a-token")


@respx.mock
async def test_errors_never_leak_token_and_methods_are_limited():
    respx.get(f"{BASE}/getMe").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(TelegramError) as e:
        await Telegram(TOKEN).me()
    assert TOKEN not in str(e.value)
    with pytest.raises(TelegramError):
        await Telegram(TOKEN).call("deleteMessage")
    respx.get(f"{BASE}/getUpdates").mock(return_value=httpx.Response(200, json={"ok": True, "result": [
        {"message": {"chat": {"id": 42, "type": "private", "first_name": "Khánh"}}},
        {"message": {"chat": {"id": 42, "type": "private", "first_name": "Khánh"}}},
        {"channel_post": {"chat": {"id": -100, "type": "channel", "title": "Mớn nước"}}}]}))
    assert sorted(c["id"] for c in await Telegram(TOKEN).chats()) == [-100, 42]


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("DATA_DIR", str(tmp_path)); monkeypatch.setenv("BROKERS", "demo")
    monkeypatch.delenv("APP_ACCESS_TOKEN", raising=False)
    get_settings.cache_clear()
    from app.main import create_app
    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()


def _cand(key, sev, title="t"):
    return AlertCandidate(key=key, rule="rtt", severity=sev, title=title, message="m", data={})


@respx.mock
def test_send_once_then_again_when_more_severe(client):
    sent: list[dict] = []
    respx.post(f"{BASE}/sendMessage").mock(side_effect=lambda r: (sent.append(json.loads(r.content)),
                                                                  httpx.Response(200, json={"ok": True, "result": {}}))[1])
    respx.get(f"{BASE}/getMe").mock(return_value=httpx.Response(200, json={"ok": True, "result": {"username": "mon_nuoc_bot"}}))
    n: NotifyService = client.app.state.notify
    st = client.put("/api/notify/telegram", json={"token": TOKEN, "chat_id": 42, "enabled": True}).json()
    assert st["token_masked"] == mask(TOKEN) and TOKEN not in json.dumps(st)
    store = n.store
    store.sync_alerts("demo", "A", [_cand("RTT:x", AlertSeverity.WARNING, "RTT sát ngưỡng"),
                                     _cand("TP:y", AlertSeverity.INFO, "Tới mốc chốt lời")])
    assert client.post("/api/notify/run").json()["sent"] >= 1          # gồm cả cảnh báo của dữ liệu mẫu demo
    assert sent[-1]["chat_id"] == 42 and "RTT sát ngưỡng" in sent[-1]["text"]
    assert "Tới mốc chốt lời" not in sent[-1]["text"]                  # mặc định từ mức cảnh báo: bỏ tin info
    n_msgs = len(sent)
    assert client.post("/api/notify/run").json()["sent"] == 0           # không gửi lại
    assert len(sent) == n_msgs
    store.sync_alerts("demo", "A", [_cand("RTT:x", AlertSeverity.CRITICAL, "RTT dưới duy trì"),
                                     _cand("TP:y", AlertSeverity.INFO, "Tới mốc chốt lời")])
    assert client.post("/api/notify/run").json()["sent"] == 1           # nặng lên: báo lại đúng cảnh báo đó
    assert "🔴 RTT dưới duy trì" in sent[-1]["text"]
    assert client.post("/api/notify/telegram/test").status_code == 200
    assert "kết nối Telegram thành công" in sent[-1]["text"]


def test_disabled_or_unconfigured_sends_nothing(client):
    assert client.post("/api/notify/run").json()["sent"] == 0
    assert client.get("/api/notify/telegram").json()["configured"] is False
    assert client.post("/api/notify/telegram/test").status_code == 422


def test_compose_truncates_long_batches(client):
    n: NotifyService = client.app.state.notify
    alerts = [{"severity": "warning", "title": f"Cảnh báo {i}", "message": "x" * 500} for i in range(30)]
    text = n.compose(alerts, ["Phiên TCBS đã hết hạn"])
    assert len(text) < 4096 and "cảnh báo khác" in text and text.index("Phiên TCBS") < text.index("Cảnh báo 0")

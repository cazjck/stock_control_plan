"""Bảng kiểm trước khi mua, bản tin đầu/cuối phiên, lệnh Telegram."""
from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.config import get_settings
from app.models import MarginBucket, MarketInfo, MarketState
from app.risk.margin import bucket_metrics
from app.risk.pretrade import build_pretrade, margin_effect
from app.risk.sizing import size_position

from .test_deleverage import equity_bucket, ev, loan

TOKEN = "123456:ABC-test-token-xyz"
BASE = f"https://api.telegram.org/bot{TOKEN}"
NORMAL = MarketInfo(state=MarketState.NORMAL, note="VNINDEX trên SMA50 và SMA200")


def _sizing(rules, *, capital=500e6, held=None, positions=1, price=20_000):
    return size_position(symbol="AAA", price=price, atr14=500, capital=capital, positions_count=positions, held=held,
                         rules=rules, market=NORMAL)


def test_clean_cash_account_is_ok(rules):
    s = _sizing(rules)
    c = build_pretrade(symbol="AAA", quantity=s.additional_quantity, price=20_000, sizing=s, held=None, tech=None,
                       series=None, margin=None, loans=[], buys_today=0, rules=rules)
    assert c.verdict in ("ok", "caution")              # thiếu nến thì tín hiệu vào lệnh là cảnh báo, không chặn
    assert not [i for i in c.items if i.status == "fail"] and c.max_qty == s.additional_quantity


def test_margin_debt_blocks_and_shows_interest_saved(rules):
    s = _sizing(rules)
    m = bucket_metrics(equity_bucket(640e6, 402e6), rules)
    c = build_pretrade(symbol="AAA", quantity=1_000, price=20_000, sizing=s, held=None, tech=None, series=None,
                       margin=m, loans=[loan(402e6)], buys_today=0, rules=rules)
    assert c.verdict == "blocked"
    codes = {i.code: i for i in c.items}
    assert codes["margin_debt"].status == "fail" and "trả nợ" in codes["margin_debt"].detail
    assert c.margin.ratio_after < c.margin.ratio_before
    assert c.margin.interest_saved_if_repay == pytest.approx(20e6 * 0.135 / 365)
    assert "lãi mỗi ngày" in c.suggestion


def test_over_size_averaging_down_and_daily_limit(rules):
    held = ev("AAA", 10_000, 15_000, 20_000)               # đang lỗ, hàng kẹt
    s = _sizing(rules, held=held)
    c = build_pretrade(symbol="AAA", quantity=50_000, price=15_000, sizing=s, held=held, tech=None, series=None,
                       margin=None, loans=[], buys_today=rules.behavior.max_new_buys_per_day, rules=rules)
    st = {i.code: i.status for i in c.items}
    assert st["averaging_down"] == "fail" and st["trapped"] == "fail" and st["buys_today"] == "fail"
    assert c.verdict == "blocked" and c.headline.startswith("Không nên mua AAA")


def test_margin_effect_below_maintenance_wording(rules):
    m = bucket_metrics(equity_bucket(640e6, 402e6), rules)
    eff = margin_effect(m, [], 300e6)
    assert eff.ratio_after < m.bucket.maintenance_pct


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


def test_pretrade_api_and_validation(client):
    r = client.get("/api/pretrade", params={"broker": "demo", "symbol": "HPG", "qty": 2000})
    assert r.status_code == 200
    d = r.json()
    assert d["symbol"] == "HPG" and d["quantity"] == 2000 and d["verdict"] == "blocked"
    assert any(i["code"] == "averaging_down" for i in d["items"])
    assert client.get("/api/pretrade", params={"broker": "demo", "symbol": "HPG", "qty": -1}).status_code == 422


def test_brief_preview_contains_margin_and_todo(client):
    t = client.get("/api/notify/brief", params={"kind": "open"}).json()["text"]
    assert "Bản tin đầu phiên" in t and "Ký quỹ:" in t and "Giá gọi ký quỹ" in t and "Việc cần làm:" in t
    c = client.get("/api/notify/brief", params={"kind": "close"}).json()["text"]
    assert "Bản tin cuối phiên" in c and "Hôm nay:" in c


@respx.mock
def test_commands_reply_only_to_configured_chat(client):
    sent: list[dict] = []
    respx.get(f"{BASE}/getMe").mock(return_value=httpx.Response(200, json={"ok": True, "result": {"username": "b"}}))
    respx.post(f"{BASE}/sendMessage").mock(side_effect=lambda r: (sent.append(json.loads(r.content)),
                                                                  httpx.Response(200, json={"ok": True, "result": {}}))[1])
    respx.get(f"{BASE}/getUpdates").mock(return_value=httpx.Response(200, json={"ok": True, "result": [
        {"update_id": 10, "message": {"chat": {"id": 42}, "text": "/kiemtra HPG 2000"}},
        {"update_id": 11, "message": {"chat": {"id": 999}, "text": "/tinhtrang"}},      # người lạ: bỏ qua
        {"update_id": 12, "message": {"chat": {"id": 42}, "text": "/tinhtrang"}},
        {"update_id": 13, "message": {"chat": {"id": 42}, "text": "xin chào"}}]}))
    client.put("/api/notify/telegram", json={"token": TOKEN, "chat_id": 42, "enabled": True})
    n = client.app.state.notify
    assert client.portal.call(n.poll_once, 0) == 3
    assert [m["chat_id"] for m in sent] == [42, 42, 42]
    assert sent[0]["text"].startswith("⛔ Không nên mua HPG")
    assert "Ký quỹ:" in sent[1]["text"] and "/kiemtra" in sent[2]["text"]
    assert n.store.kv_get("telegram_offset") == "14"


@respx.mock
def test_scheduled_brief_respects_switch(client):
    respx.get(f"{BASE}/getMe").mock(return_value=httpx.Response(200, json={"ok": True, "result": {"username": "b"}}))
    route = respx.post(f"{BASE}/sendMessage").mock(return_value=httpx.Response(200, json={"ok": True, "result": {}}))
    client.put("/api/notify/telegram", json={"token": TOKEN, "chat_id": 42, "enabled": True, "brief": False})
    n = client.app.state.notify
    assert client.portal.call(lambda: n.send_brief("open", scheduled=True)) is False
    assert client.post("/api/notify/brief", params={"kind": "open"}).status_code == 200      # gửi tay vẫn được
    assert route.call_count == 1


def test_brief_warns_when_prices_are_stale():
    from datetime import date
    from types import SimpleNamespace
    from app.notify.brief import brief_text
    ctx = SimpleNamespace(notes=["DXG: không lấy được nến (Chưa có nguồn giá cho danh mục tổng.)"], market=NORMAL, evals=[],
                          frames={}, margin=SimpleNamespace(buckets=[], loans=[], interest_per_day=0), rules=None)
    import app.notify.brief as b
    orig = b.todo_items
    b.todo_items = lambda *a, **k: []
    try:
        assert "Chưa lấy được giá mới" in brief_text(ctx, "open", date(2026, 10, 19))
    finally:
        b.todo_items = orig

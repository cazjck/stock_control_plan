"""Chọn nguồn giá cho Sổ tổng theo cài đặt: nguồn chính, có hoặc không dùng nguồn còn lại làm dự phòng."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.brokers.registry import parse_pref, price_source_from, source_order
from app.config import get_settings


class Fake:
    def __init__(self, name, ok):
        self.name, self.display_name, self._ok = name, name.upper(), ok

    def session_info(self):
        return SimpleNamespace(authenticated=self._ok)


def test_order_and_bad_values():
    assert source_order(parse_pref(None)) == ["tcbs", "dnse", "demo"]                 # mặc định TCBS trước
    assert source_order(parse_pref('{"primary":"dnse"}')) == ["dnse", "tcbs", "demo"]
    assert source_order(parse_pref('{"primary":"dnse","fallback":false}')) == ["dnse", "demo"]
    assert parse_pref('{"primary":"xyz"}')["primary"] == "tcbs" and parse_pref("không phải json")["fallback"] is True


@pytest.mark.parametrize("pref,tcbs_ok,expected", [
    (None, True, "tcbs"),
    (None, False, "dnse"),                                    # TCBS hết phiên: dự phòng DNSE
    ('{"primary":"dnse"}', True, "dnse"),
    ('{"primary":"tcbs","fallback":false}', False, None),     # tắt dự phòng: không có nguồn
])
def test_pick_follows_preference(pref, tcbs_ok, expected):
    ads = {"tcbs": Fake("tcbs", tcbs_ok), "dnse": Fake("dnse", True)}
    got = price_source_from(ads, lambda: pref)()
    assert (got.name if got else None) == expected


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


def test_api_get_put(client):
    d = client.get("/api/settings/data-source").json()
    assert d["primary"] == "tcbs" and d["fallback"] is True and d["active"] == "demo"
    assert {s["name"]: s["enabled"] for s in d["sources"]} == {"tcbs": False, "dnse": False}
    d = client.put("/api/settings/data-source", json={"primary": "dnse", "fallback": False}).json()
    assert d["primary"] == "dnse" and d["order"] == ["dnse", "demo"]
    assert json.loads(client.app.state.store.kv_get("price_source")) == {"primary": "dnse", "fallback": False}
    assert client.put("/api/settings/data-source", json={"primary": "vps"}).status_code == 422

"""Giao diện đã build: index.html luôn hỏi lại máy chủ để thấy bản mới ngay sau khi triển khai,
file trong assets/ (có mã băm trong tên) được lưu đệm lâu dài."""
from __future__ import annotations

import pytest

from app.config import get_settings
from app.main import FRONTEND_DIST

pytestmark = pytest.mark.skipif(not (FRONTEND_DIST / "index.html").exists(), reason="chưa build frontend")


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


def test_html_is_revalidated_and_assets_are_immutable(client):
    for path in ("/", "/positions", "/settings"):
        r = client.get(path)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache", path
    asset = next((FRONTEND_DIST / "assets").glob("*.js")).name
    r = client.get(f"/assets/{asset}")
    assert r.status_code == 200 and "immutable" in r.headers["cache-control"]
    assert client.get("/assets/khong-ton-tai.js").status_code == 404

"""Bảng giá cho các mã trong danh mục."""
from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.config import get_settings
from .test_adapters import TCBS, _tcbs_authed


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path)); monkeypatch.setenv("BROKERS", "demo")
    monkeypatch.delenv("APP_ACCESS_TOKEN", raising=False)
    get_settings.cache_clear()
    from app.main import create_app
    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()


def test_board_lists_only_portfolio_symbols_with_personal_columns(client):
    b = client.get("/api/board").json()
    assert sorted(r["symbol"] for r in b["rows"]) == ["FPT", "HPG", "MWG", "SSI", "VND"]
    fpt = next(r for r in b["rows"] if r["symbol"] == "FPT")
    assert fpt["held_qty"] == 1000 and fpt["avg_cost"] == 112_000 and fpt["sources"] == ["Demo"]
    assert fpt["ceil"] > fpt["ref"] > fpt["floor"] and len(fpt["bid"]) == 3 and len(fpt["offer"]) == 3
    assert fpt["pnl_pct"] == pytest.approx((fpt["price"] / 112_000 - 1) * 100)
    assert b["index"]["symbol"] == "VNINDEX" and b["source"] == "Demo (dữ liệu mẫu)"


def test_board_for_ledger_uses_price_source(client):
    client.post("/api/ledger/accounts", json={"name": "SSI"})
    client.post("/api/ledger/accounts/ssi/purchases", json={"symbol": "HPG", "quantity": 1000, "price": 30_000})
    b = client.get("/api/board", params={"broker": "ledger"}).json()
    [hpg] = b["rows"]
    assert hpg["held_qty"] == 1000 and hpg["sources"] == ["SSI"] and hpg["ref"] is not None


@respx.mock
async def test_tcbs_board_mapping(tmp_path):
    respx.get(f"{TCBS}/tartarus/v1/tickerCommons").mock(return_value=httpx.Response(200, json={"data": [{
        "symbol": "PDR", "ceilPrice": 11950.0, "floorPrice": 10450.0, "refPrice": 11200.0, "matchPrice": 11300.0,
        "matchQtty": 500.0, "change": 100.0, "changePercent": 0.89, "open": 11200.0, "high": 11400.0, "low": 11100.0,
        "avg": 11250.0, "totalVol": 3_200_000.0, "bidPrice01": 11250.0, "bidQtty01": 12000.0, "bidPrice02": 11200.0,
        "bidQtty02": 30000.0, "bidPrice03": 0.0, "bidQtty03": 0.0, "offerPrice01": 11300.0, "offerQtty01": 8000.0,
        "offerPrice02": 11350.0, "offerQtty02": 9000.0, "offerPrice03": 11400.0, "offerQtty03": 15000.0,
        "buyForeignQtty": 1000.0, "sellForeignQtty": 52000.0, "room": 1.0e7}]}))
    ad = _tcbs_authed(tmp_path)
    q = (await ad.get_board(["PDR"]))["PDR"]
    assert (q.ceil, q.floor, q.ref, q.price) == (11950, 10450, 11200, 11300)
    assert [b.price for b in q.bid] == [11250, 11200]          # bước 3 bằng 0 nghĩa là trống, bị bỏ
    assert [o.qty for o in q.offer] == [8000, 9000, 15000]
    assert q.foreign_sell == 52000
    await ad.aclose()

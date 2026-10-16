"""Từng lần mua (lô) và luật lô mua thêm khi đang lỗ."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.models import Lot, Position
from app.risk.indicators import to_frame
from app.risk.lots import evaluate_lot, trading_days_after
from app.services.lots import LotService
from app.storage.db import Store
from app.storage.lots import LotRepo
from .conftest import flat, make_candles


def lot(**kw) -> Lot:
    base = dict(id=1, broker="t", account_id="a", symbol="AAA", buy_date=date(2026, 10, 12), quantity=2000,
                remaining=2000, price=20_000, source="manual", add_on_loss=True)
    base.update(kw)
    return Lot(**base)


@pytest.fixture
def df():
    # 30 phiên kết thúc thứ Sáu 16/10/2026, giá quanh 20.000, biên độ ±1%
    from datetime import datetime
    from app.util import VN_TZ
    return to_frame(make_candles(flat(30, 20_000), end=datetime(2026, 10, 16, tzinfo=VN_TZ)))


def test_trading_days_skip_weekends():
    assert trading_days_after(date(2026, 10, 15), 2, []) == date(2026, 10, 19)   # thứ Năm + 2 phiên = thứ Hai


def test_default_stop_uses_buy_day_low(df, rules):
    low = float(df[df["date"] == date(2026, 10, 12)]["low"].iloc[0])
    ev = evaluate_lot(lot(), price=20_100, df=df, rules=rules, today=date(2026, 10, 16))
    assert ev.stop_price == pytest.approx(max(low * 0.99, 19_000))
    assert ev.rule_status == "ok" and ev.sellable and ev.sessions_held == 4


def test_stop_breach_tells_exact_quantity(df, rules):
    ev = evaluate_lot(lot(stop_price=19_500), price=19_400, df=df, rules=rules, today=date(2026, 10, 16))
    assert ev.rule_status == "stop" and "bán 2.000 cp bằng ATO" in ev.action
    assert ev.pnl_pct == pytest.approx(-3.0) and ev.pnl_value == pytest.approx(-1_200_000)


def test_not_yet_settled_says_when_shares_arrive(df, rules):
    ev = evaluate_lot(lot(buy_date=date(2026, 10, 15), stop_price=19_500), price=19_000, df=df, rules=rules,
                      today=date(2026, 10, 16))
    assert not ev.sellable and ev.sellable_from == date(2026, 10, 19)
    assert "về tài khoản chiều 19/10" in ev.action


def test_time_stop_after_settle_plus_three_sessions(df, rules):
    ev = evaluate_lot(lot(buy_date=date(2026, 10, 8)), price=20_200, df=df, rules=rules, today=date(2026, 10, 16))
    assert ev.sessions_held == 6 and ev.rule_status == "time"     # 2 phiên chờ về + 3 phiên, lãi 1% < 3%
    ok = evaluate_lot(lot(buy_date=date(2026, 10, 8)), price=20_700, df=df, rules=rules, today=date(2026, 10, 16))
    assert ok.rule_status == "ok"                                 # lãi 3,5%: đạt


def test_regular_lots_are_informational_only(df, rules):
    ev = evaluate_lot(lot(add_on_loss=False), price=15_000, df=df, rules=rules, today=date(2026, 10, 16))
    assert ev.rule_status == "info" and ev.pnl_pct == pytest.approx(-25)


def test_delay_cost_counts_from_trigger(df, rules):
    ev = evaluate_lot(lot(stop_price=19_500, trigger_date=date(2026, 10, 13), trigger_price=19_400), price=18_900,
                      df=df, rules=rules, today=date(2026, 10, 16))
    assert ev.delay_sessions == 3 and ev.delay_cost == pytest.approx(500 * 2000)


# ---------------- tự phát hiện ----------------

@pytest.fixture
def svc(tmp_path):
    return LotService(LotRepo(Store(tmp_path / "l.sqlite")))


def pos(q, c, price=None):
    return Position(broker="t", account_id="a", symbol="PDR", quantity=q, avg_cost=c, price=price or c, market_value=q * (price or c))


def test_first_observation_is_baseline_only(svc):
    svc.observe("t", "a", [pos(10_000, 20_000)], date(2026, 10, 15))
    assert svc.repo.lots("t") == []


def test_buy_more_creates_lot_with_exact_implied_price(svc):
    d = date(2026, 10, 15)
    svc.observe("t", "a", [pos(10_000, 20_000, 11_200)], d)
    svc.observe("t", "a", [pos(12_000, 18_500, 11_000)], d)        # mua 2.000 cp giá 11.000
    [l] = svc.repo.lots("t")
    assert (l.quantity, l.source, l.add_on_loss, l.estimated) == (2000, "auto", True, False)
    assert l.price == pytest.approx(11_000)


def test_selling_reduces_newest_lot_first(svc):
    d = date(2026, 10, 15)
    svc.observe("t", "a", [pos(10_000, 20_000, 11_200)], d)
    svc.observe("t", "a", [pos(12_000, 18_500, 11_000)], d)
    svc.observe("t", "a", [pos(10_500, 18_500, 11_000)], d)        # bán 1.500
    [l] = svc.repo.lots("t")
    assert l.remaining == 500
    svc.observe("t", "a", [], d)                                    # bán hết
    assert svc.repo.lots("t")[0].remaining == 0


def test_unknown_part_and_its_implied_cost(svc, rules):
    d = date(2026, 10, 15)
    svc.observe("t", "a", [pos(10_000, 20_000, 11_200)], d)
    p = pos(12_000, 18_500, 11_000)
    svc.observe("t", "a", [p], d)
    lots, unknown = svc.evaluate("t", "a", p, None, rules, d, "TCBS")
    assert len(lots) == 1 and unknown.quantity == 10_000 and unknown.avg_cost == pytest.approx(20_000)


# ---------------- API ----------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path)); monkeypatch.setenv("BROKERS", "demo")
    monkeypatch.delenv("APP_ACCESS_TOKEN", raising=False)
    get_settings.cache_clear()
    from app.main import create_app
    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()


def _recent_weekday(n_back: int) -> str:
    from app.util import now_vn
    d, k = now_vn().date(), 0
    while k < n_back:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            k += 1
    return d.isoformat()


def test_manual_lot_flow_and_non_dismissable_alert(client):
    # VND demo: 4.000 cp, giá vốn 19.400, giá 18.600. Ghi lần mua thêm 2.000 cp giá 18.900, cắt lỗ 18.700
    r = client.post("/api/lots", params={"broker": "demo"}, json={
        "symbol": "VND", "buy_date": _recent_weekday(3), "quantity": 2000, "price": 18_900, "stop_price": 18_700})
    assert r.status_code == 200 and r.json()["add_on_loss"] is True
    vnd = next(p for p in client.get("/api/positions").json()["positions"] if p["symbol"] == "VND")
    lotv = vnd["lots"][0]
    assert lotv["rule_status"] == "stop" and lotv["pnl_pct"] == pytest.approx((18_600 / 18_900 - 1) * 100)
    assert vnd["actions"][0].startswith("Lô mua ngày") and "lot_rule" in vnd["flags"]
    assert vnd["unknown_lot"]["quantity"] == 2000
    alert = next(a for a in client.get("/api/alerts").json() if a["rule"] == "add_on_lot")
    assert client.post(f"/api/alerts/{alert['id']}/ack").status_code == 409
    assert client.post(f"/api/alerts/{alert['id']}/resolve", json={"note": ""}).status_code == 422
    assert client.post(f"/api/alerts/{alert['id']}/resolve", json={"note": "đã bán 2.000 cp"}).status_code == 200


def test_manual_lots_cannot_exceed_holding(client):
    r = client.post("/api/lots", params={"broker": "demo"}, json={"symbol": "VND", "buy_date": _recent_weekday(3), "quantity": 5000, "price": 18_000})
    assert r.status_code == 422 and "vượt khối lượng" in r.json()["detail"]["message"]
    assert client.post("/api/lots", params={"broker": "demo"}, json={"symbol": "ZZZ", "buy_date": _recent_weekday(3), "quantity": 1, "price": 1}).status_code == 422
    future = (date.today() + timedelta(days=5)).isoformat()
    assert client.post("/api/lots", params={"broker": "demo"}, json={"symbol": "VND", "buy_date": future, "quantity": 100, "price": 1}).status_code == 422


def test_edit_and_delete_lot(client):
    lid = client.post("/api/lots", params={"broker": "demo"}, json={"symbol": "FPT", "buy_date": _recent_weekday(10), "quantity": 500, "price": 110_000}).json()["id"]
    assert client.put(f"/api/lots/{lid}", json={"stop_price": 105_000}).json()["stop_price"] == 105_000
    assert client.delete(f"/api/lots/{lid}").status_code == 200
    assert client.get("/api/lots", params={"broker": "demo"}).json() == []


def test_ledger_purchases_become_dated_lots(client):
    client.post("/api/ledger/accounts", json={"name": "SSI"})
    client.post("/api/ledger/accounts/ssi/purchases", json={"symbol": "HPG", "quantity": 3000, "price": 28_000, "bought_at": _recent_weekday(20)})
    client.post("/api/ledger/accounts/ssi/purchases", json={"symbol": "HPG", "quantity": 2000, "price": 25_000, "bought_at": _recent_weekday(3)})
    hpg = next(p for p in client.get("/api/positions", params={"broker": "ledger"}).json()["positions"] if p["symbol"] == "HPG")
    assert [(l["quantity"], l["add_on_loss"], l["source_label"]) for l in hpg["lots"]] == [(2000, True, "SSI"), (3000, False, "SSI")]
    assert hpg["unknown_lot"] is None
    # xoá dòng trong sổ thì xoá luôn các lô
    pid = client.get("/api/ledger").json()["accounts"][0]["positions"][0]["id"]
    client.delete(f"/api/ledger/positions/{pid}")
    assert client.get("/api/lots", params={"broker": "ledger"}).json() == []


def test_ledger_manual_account_accepts_dated_lots(client):
    r = client.post("/api/lots", params={"broker": "ledger"}, json={"symbol": "HPG", "buy_date": _recent_weekday(3), "quantity": 1, "price": 1})
    assert r.status_code == 422 and "tiểu danh mục nhập tay" in r.json()["detail"]["message"]
    client.post("/api/ledger/accounts", json={"name": "VPS"})
    # nhập lại tổng từ ảnh chụp: không tạo lô ngày hôm nay
    client.post("/api/ledger/accounts/vps/purchases", json={"symbol": "PDR", "quantity": 25_800, "total_amount": 393_450_000, "record_lot": False})
    assert client.get("/api/lots", params={"broker": "ledger"}).json() == []
    r = client.post("/api/lots", params={"broker": "ledger", "account": "vps"}, json={"symbol": "PDR", "buy_date": _recent_weekday(1), "quantity": 2000, "price": 11_000})
    assert r.status_code == 200 and r.json()["add_on_loss"] is True            # 11.000 < giá vốn 15.250
    pdr = next(p for p in client.get("/api/positions", params={"broker": "ledger"}).json()["positions"] if p["symbol"] == "PDR")
    assert [l["quantity"] for l in pdr["lots"]] == [2000] and pdr["unknown_lot"]["quantity"] == 23_800
    too_many = client.post("/api/lots", params={"broker": "ledger", "account": "vps"}, json={"symbol": "PDR", "buy_date": _recent_weekday(5), "quantity": 26_000, "price": 15_000})
    assert too_many.status_code == 422

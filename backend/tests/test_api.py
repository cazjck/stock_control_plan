from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BROKERS", "demo")
    monkeypatch.delenv("APP_ACCESS_TOKEN", raising=False)
    get_settings.cache_clear()
    from app.main import create_app
    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()


def test_health_and_brokers(client):
    assert client.get("/api/health").json()["read_only"] is True
    b = client.get("/api/brokers").json()
    assert b[0]["name"] == "demo" and b[0]["session"]["authenticated"]


def test_overview_numbers_are_consistent(client):
    o = client.get("/api/overview").json()
    a = o["assets"]
    assert a["nav"] == pytest.approx(a["positions_value"] + a["cash"] - a["debt"])
    assert o["read_only"] is True and o["market"]["state"] in {"NORMAL", "NO_NEW_BUYS", "WEAK", "UNKNOWN"}
    m = o["margin"]["buckets"][0]
    assert m["zone"] == "watch" and m["drop_to_maintenance_pct"] > 0 and m["cash_to_safe"] > 0
    assert o["margin"]["interest_per_day"] > 0


def test_positions_cover_every_status_family_and_sorted_by_urgency(client):
    p = client.get("/api/positions").json()["positions"]
    statuses = {e["symbol"]: e["status"] for e in p}
    assert statuses["VND"] == "STOP_HIT" and statuses["HPG"] == "TRAPPED" and statuses["SSI"] == "TRAPPED"
    assert statuses["FPT"] == "TAKE_PROFIT" and statuses["MWG"] == "WARNING"
    urg = [e["urgency"] for e in p]
    assert urg == sorted(urg, reverse=True) and p[0]["status"] == "STOP_HIT"


def test_chart_series(client):
    ch = client.get("/api/symbols/FPT/chart", params={"count": 120}).json()
    assert len(ch["candles"]) == 120 and ch["stop_level"] and ch["avg_cost"] == 112000
    assert {"sma20", "sma50", "ema20", "rsi14", "macd", "macd_hist", "atr14"} <= set(ch)
    assert client.get("/api/symbols/NOPE/chart").status_code == 404


def test_alerts_lifecycle(client):
    client.get("/api/overview")
    al = client.get("/api/alerts").json()
    assert any(a["key"] == "STOP:VND" and a["severity"] == "critical" for a in al)
    aid = next(a["id"] for a in al if a["key"] == "STOP:VND")
    assert client.post(f"/api/alerts/{aid}/ack").json()["status"] == "acked"
    r = client.post(f"/api/alerts/{aid}/resolve", json={"note": "đã bán trên app"}).json()
    assert r["status"] == "resolved" and r["resolution_note"] == "đã bán trên app"
    assert client.post("/api/alerts/99999/ack").status_code == 404
    client.get("/api/overview", params={"refresh": True})
    # điều kiện vẫn còn nên cảnh báo mở lại như một vi phạm mới
    assert any(a["key"] == "STOP:VND" and a["status"] == "open" for a in client.get("/api/alerts").json())


def test_plan_changes_trapped_guidance(client):
    r = client.put("/api/plans/HPG", json={"mode": "swing", "has_thesis": False})
    assert r.status_code == 200 and r.json()["has_thesis"] is False
    hpg = next(e for e in client.get("/api/positions").json()["positions"] if e["symbol"] == "HPG")
    assert hpg["stop_level"] is None and "Nhóm B" in hpg["actions"][0]
    client.put("/api/plans/HPG", json={"mode": "swing", "has_thesis": True})
    hpg = next(e for e in client.get("/api/positions").json()["positions"] if e["symbol"] == "HPG")
    assert hpg["stop_level"] and "Nhóm A" in hpg["actions"][0]
    assert any(p["symbol"] == "HPG" for p in client.get("/api/plans").json())


def test_dca_plan_removes_stop_pressure(client):
    client.put("/api/plans/VND", json={"mode": "dca"})
    vnd = next(e for e in client.get("/api/positions").json()["positions"] if e["symbol"] == "VND")
    assert vnd["status"] == "SAFE" and vnd["stop_basis"].startswith("Ngưỡng thảm hoạ")


def test_rules_change_requires_confirmation_with_open_positions(client):
    r = client.put("/api/settings/rules", json={"patch": {"stop_loss": {"pct": 6}}})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "OPEN_POSITIONS"
    ok = client.put("/api/settings/rules", json={"patch": {"stop_loss": {"pct": 6}}, "confirm_open_positions": True})
    assert ok.status_code == 200 and ok.json()["effective"]["stop_loss"]["pct"] == 6 and ok.json()["has_overrides"]
    changes = client.get("/api/settings/rule-changes").json()
    assert changes[0]["diff"]["stop_loss.pct"] == {"from": 7.0, "to": 6.0} and changes[0]["had_open_positions"]
    bad = client.put("/api/settings/rules", json={"patch": {"stop_loss": {"pct": 99}}, "confirm_open_positions": True})
    assert bad.status_code == 422
    reset = client.delete("/api/settings/rules")
    assert reset.json()["effective"]["stop_loss"]["pct"] == 7 and not reset.json()["has_overrides"]


def test_rules_change_affects_evaluation(client):
    client.put("/api/settings/rules", json={"patch": {"take_profit": {"ladder": [
        {"gain_pct": 20, "sell_pct": 50, "move_stop_to_gain_pct": 5}]}}, "confirm_open_positions": True})
    fpt = next(e for e in client.get("/api/positions").json()["positions"] if e["symbol"] == "FPT")
    assert fpt["status"] != "TAKE_PROFIT"          # +12.9% chưa tới mốc +20% mới


def test_snapshot_run_and_list(client):
    r = client.post("/api/snapshots/run")
    assert r.status_code == 200
    snaps = client.get("/api/snapshots").json()
    assert len(snaps) == 1 and snaps[0]["nav"] > 0 and snaps[0]["min_rtt_gap"] is not None
    client.post("/api/snapshots/run")
    assert len(client.get("/api/snapshots").json()) == 1      # cùng ngày thì ghi đè, không nhân đôi


def test_unknown_broker_and_missing_endpoints(client):
    assert client.get("/api/overview", params={"broker": "tcbs"}).status_code == 404
    for path in ("/api/orders", "/api/order", "/api/trade", "/api/place-order"):
        assert client.get(path).status_code == 404 and client.post(path).status_code in (404, 405)


def test_no_write_routes_beyond_bookkeeping(client):
    """Mọi route POST/PUT/DELETE chỉ phục vụ sổ sách của app (cảnh báo, kế hoạch, luật, snapshot, đăng nhập),
    ngoại lệ duy nhất là /api/scenarios/run: POST chỉ vì có thân yêu cầu, chỉ tính toán, không ghi gì."""
    allowed = ("/api/alerts/", "/api/plans/", "/api/settings/rules", "/api/snapshots/run", "/api/brokers/",
               "/api/scenarios/run",
               "/api/ledger", "/api/lots", "/api/rotations", "/api/holds")  # sổ danh mục tổng: chỉ ghi vào SQLite của ứng dụng; đồng bộ chỉ ĐỌC từ broker
    spec = client.get("/openapi.json").json()
    for path, ops in spec["paths"].items():
        for method in ops:
            if method in ("post", "put", "delete", "patch"):
                assert path.startswith(allowed), f"{method.upper()} {path} không nằm trong danh sách cho phép"


def _run(client, **body):
    return client.post("/api/scenarios/run", json=body)


def test_scenario_drop_follows_margin_formula(client):
    before = client.get("/api/margin").json()["buckets"][0]["bucket"]["ratio_pct"]
    r = _run(client, market_drop_pct=10)
    assert r.status_code == 200
    d = r.json()
    r0, x = before / 100, 0.10
    assert d["before"]["buckets"][0]["bucket"]["ratio_pct"] == pytest.approx(before)
    assert d["after"]["buckets"][0]["bucket"]["ratio_pct"] == pytest.approx((1 - (1 - r0) / (1 - x)) * 100)
    assert d["after"]["buckets"][0]["drop_to_maintenance_pct"] < d["before"]["buckets"][0]["drop_to_maintenance_pct"]
    assert d["after"]["unrealized_pnl"] < d["before"]["unrealized_pnl"] and d["after"]["debt"] == d["before"]["debt"]
    assert d["after"]["focus_bucket_id"] == d["before"]["focus_bucket_id"] == "DEMO-0001"
    assert d["request"]["market_drop_pct"] == 10


def test_scenario_drop_to_threshold_needs_cash_then_cash_fixes_it(client):
    m = client.get("/api/margin").json()["buckets"][0]
    d = _run(client, market_drop_pct=m["drop_to_maintenance_pct"] + 3).json()          # vượt ngưỡng duy trì 3 điểm
    assert d["after"]["buckets"][0]["zone"] in ("danger", "breach") and d["after"]["cash_needed"] > m["cash_to_safe"]
    assert any("gọi ký quỹ" in w or "giải chấp" in w for w in d["warnings"])
    fixed = _run(client, market_drop_pct=m["drop_to_maintenance_pct"] + 3, add_cash=d["after"]["cash_needed"]).json()
    assert fixed["after"]["cash_needed"] == pytest.approx(0, abs=1) and fixed["after"]["buckets"][0]["zone"] == "watch"
    assert fixed["after"]["debt"] == pytest.approx(d["after"]["debt"] - d["after"]["cash_needed"])


def test_scenario_sell_uses_proceeds_to_repay_debt_and_cuts_interest(client):
    d = _run(client, sell=[{"symbol": "HPG", "quantity": 3000}]).json()
    assert d["sale_proceeds"] == pytest.approx(3000 * 24_800) and d["debt_repaid"] == pytest.approx(d["sale_proceeds"])
    assert d["realized_pnl"] == pytest.approx(3000 * (24_800 - 28_000))
    assert d["after"]["debt"] == pytest.approx(d["before"]["debt"] - d["sale_proceeds"])
    assert d["after"]["interest_per_day"] < d["before"]["interest_per_day"]
    assert d["after"]["positions_value"] == pytest.approx(d["before"]["positions_value"] - d["sale_proceeds"])
    assert d["after"]["buckets"][0]["bucket"]["ratio_pct"] > d["before"]["buckets"][0]["bucket"]["ratio_pct"]
    assert d["after"]["nav"] == pytest.approx(d["before"]["nav"])                      # bán không đổi NAV khi giá không đổi


def test_scenario_add_cash_only(client):
    d = _run(client, add_cash=30_000_000).json()
    assert d["after"]["debt"] == pytest.approx(d["before"]["debt"] - 30_000_000)
    assert d["after"]["nav"] == pytest.approx(d["before"]["nav"] + 30_000_000)
    assert d["after"]["buckets"][0]["bucket"]["ratio_pct"] > 50 and d["after"]["cash_needed"] == 0


def test_scenario_rejects_bad_input(client):
    r = _run(client, sell=[{"symbol": "NOPE", "quantity": 100}])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_SCENARIO"
    r = _run(client, sell=[{"symbol": "FPT", "quantity": 1001}])
    assert r.status_code == 422 and "Chỉ đang giữ 1.000 cp FPT" in r.json()["detail"]["message"]
    assert _run(client, market_drop_pct=-5).status_code == 422
    assert _run(client, market_drop_pct=95).status_code == 422
    assert _run(client, add_cash=-1).status_code == 422
    assert client.post("/api/scenarios/run", params={"broker": "tcbs"}, json={}).status_code == 404


def test_scenario_writes_nothing(client):
    """POST chỉ để tính: không đổi dữ liệu, không ghi snapshot, cảnh báo hay kế hoạch."""
    ov = client.get("/api/overview").json()
    alerts, plans, snaps = client.get("/api/alerts", params={"status": "all"}).json(), client.get("/api/plans").json(), client.get("/api/snapshots").json()
    for body in ({"market_drop_pct": 30}, {"sell": [{"symbol": "VND", "quantity": 4000}]}, {"add_cash": 1e9}):
        assert _run(client, **body).status_code == 200
    assert client.get("/api/overview").json()["assets"] == ov["assets"]
    assert client.get("/api/alerts", params={"status": "all"}).json() == alerts
    assert client.get("/api/plans").json() == plans and client.get("/api/snapshots").json() == snaps


def test_sizing_new_symbol_hits_market_filter_and_max_positions(client):
    s = client.get("/api/sizing", params={"symbol": "abc", "price": 18_600}).json()
    assert s["symbol"] == "ABC" and s["capital"] == 12_300_000            # tiền mặt thực có, không tính margin
    assert s["risk_money"] == pytest.approx(12_300_000 * 0.015)
    assert s["stop_price"] == pytest.approx(18_600 * 0.93) and s["qty_plan"] == 100 and s["qty_plan"] % 100 == 0
    codes = {w["code"] for w in s["warnings"]}
    assert s["market"]["state"] == "NO_NEW_BUYS" and {"MARKET_NO_NEW_BUYS", "MAX_POSITIONS", "ATR_MISSING"} <= codes
    assert s["allowed"] is False and s["positions_count"] == 5 == s["max_positions"]
    assert [t["pct"] for t in s["tranches"]] == [25, 25, 25, 25]


def test_sizing_held_symbol_uses_atr_and_reports_holding(client):
    s = client.get("/api/sizing", params={"symbol": "FPT", "price": 126_500}).json()
    assert s["held_quantity"] == 1000 and s["atr14"] and s["stop_price"] < 126_500
    assert "MAX_POSITIONS" not in {w["code"] for w in s["warnings"]} and "ALREADY_HELD" in {w["code"] for w in s["warnings"]}
    assert s["stop_distance"] == pytest.approx(126_500 - s["stop_price"])
    assert s["qty_plan"] <= s["qty_by_risk"] and s["qty_plan"] <= s["qty_by_weight"]


def test_sizing_blocks_averaging_down_a_trapped_position(client):
    s = client.get("/api/sizing", params={"symbol": "HPG", "price": 24_800}).json()
    assert "AVERAGING_DOWN" in {w["code"] for w in s["warnings"]} and s["allowed"] is False


def test_sizing_custom_stop_and_validation(client):
    s = client.get("/api/sizing", params={"symbol": "ABC", "price": 18_600, "stop": 17_600}).json()
    assert s["stop_price"] == 17_600 and s["stop_basis"] == "Giá cắt lỗ do bạn nhập" and "ATR_MISSING" not in {w["code"] for w in s["warnings"]}
    assert s["qty_by_risk"] == 100                                           # 184.500 / 1.000 = 184 → 100
    r = client.get("/api/sizing", params={"symbol": "ABC", "price": 18_600, "stop": 18_600})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID_SIZING"
    assert client.get("/api/sizing", params={"symbol": "ABC"}).status_code == 422
    assert client.get("/api/sizing", params={"symbol": "ABC", "price": 0}).status_code == 422
    assert client.get("/api/sizing", params={"symbol": "../x", "price": 1}).status_code == 422
    assert client.get("/api/sizing", params={"symbol": "ABC", "price": 1, "broker": "tcbs"}).status_code == 404


def test_access_token_protection(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path)); monkeypatch.setenv("BROKERS", "demo")
    monkeypatch.setenv("APP_ACCESS_TOKEN", "s3cret")
    get_settings.cache_clear()
    from app.main import create_app
    with TestClient(create_app()) as c:
        assert c.get("/api/health").json()["protected"] is True
        assert c.get("/api/overview").status_code == 401
        assert c.get("/api/overview", headers={"X-App-Token": "wrong"}).status_code == 401
        assert c.get("/api/overview", headers={"X-App-Token": "s3cret"}).status_code == 200
    get_settings.cache_clear()

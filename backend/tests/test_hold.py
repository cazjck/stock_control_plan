"""Gồng có kế hoạch (mục 6c): ngưỡng thoát cứng, sàn ký quỹ, ngày xem lại, thời điểm cơ cấu, hoãn trong kế hoạch hạ margin."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.config import get_settings
from app.models import HoldDecision, HoldStatus, RotationPlan
from app.risk.deleverage import build_plan
from app.risk.hold import evaluate_hold
from app.risk.margin import bucket_metrics

from .test_deleverage import TODAY, equity_bucket, ev, loan

D = HoldDecision(id=1, broker="ledger", account_id="ssi", symbol="DXG", decided_at=TODAY - timedelta(days=5),
                 exit_close_below=9_000, ratio_floor_pct=None, review_on=TODAY + timedelta(days=25),
                 reason="Ngành bất động sản đang ở đáy chu kỳ")


def run(**kw):
    base = dict(close=10_000, ratio_pct=37.5, maintenance_pct=35, rotation=None, interest_per_day=100_000, today=TODAY)
    return evaluate_hold(D, **{**base, **kw})


def test_holding_reports_days_cost_and_exit_lines():
    h = run()
    assert h.state == "holding" and h.days_held == 5 and h.interest_cost == 500_000
    assert h.ratio_floor_pct == 35                       # để trống: lấy ngưỡng duy trì
    assert h.distance_to_exit_pct == pytest.approx((10_000 / 9_000 - 1) * 100)
    assert "Thoát nếu đóng cửa dưới 9.000" in h.text


def test_exit_signals_in_priority_order():
    assert run(close=8_900).state == "exit_price"
    assert run(ratio_pct=35).state == "exit_margin"
    assert run(today=D.review_on).state == "review"
    assert run(close=8_900, ratio_pct=30).state == "exit_price"


def test_rebound_into_sell_zone_is_restructure_time():
    rot = RotationPlan(phase="sell_zone", phase_label="Vùng bán", level="sell", text="", sell_qty=23_100, rebound_pct=12)
    h = run(rotation=rot)
    assert h.state == "restructure" and "Bán 23.100 cổ phiếu" in h.text and "trả nợ margin trước" in h.text


def test_plan_defers_worst_loss_of_held_symbol(rules):
    dxg = ev("DXG", 64_000, 10_000, 17_200)
    dxg.hold = HoldStatus(decision=D, state="holding", text="", days_held=5, interest_cost=0, interest_per_day=0,
                          distance_to_exit_pct=10, ratio_pct=37.5, ratio_floor_pct=35)
    b = equity_bucket(640e6, 402e6)
    p = build_plan(bucket_metrics(b, rules), [dxg], [loan(402e6)], rules, TODAY)
    [s] = p.safe_steps
    assert s.deferred and s.kind == "worst_loss"
    assert p.deferred_symbols == ["DXG"]
    assert p.committed_ratio_after == pytest.approx(b.ratio_pct)      # không bán gì: RTT giữ nguyên
    assert p.committed_interest_after == pytest.approx(p.interest_per_day)
    assert p.headline.startswith("Bạn đang gồng DXG theo quyết định: hoãn bán")
    assert "là bị gọi ký quỹ" in p.headline and "có thể nộp khoảng" in p.headline


def test_exit_state_is_no_longer_deferred(rules):
    dxg = ev("DXG", 64_000, 10_000, 17_200)
    dxg.hold = HoldStatus(decision=D, state="exit_price", text="", days_held=5, interest_cost=0, interest_per_day=0,
                          distance_to_exit_pct=-1, ratio_pct=37.5, ratio_floor_pct=35)
    p = build_plan(bucket_metrics(equity_bucket(640e6, 402e6), rules), [dxg], [loan(402e6)], rules, TODAY)
    assert not p.safe_steps[0].deferred and p.deferred_symbols == []


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


def test_api_put_hold_with_defaults_and_validation(client):
    pos = client.get("/api/positions", params={"broker": "demo"}).json()["positions"]
    p = next(x for x in pos if x["indicators"].get("low20"))
    sym = p["symbol"]
    assert client.put("/api/holds", params={"broker": "demo"}, json={"symbol": sym, "reason": "ngắn"}).status_code == 422
    r = client.put("/api/holds", params={"broker": "demo"}, json={"symbol": sym, "reason": "Tin rằng ngành đang ở đáy chu kỳ"})
    expected = round(p["technical"]["invalidation"], -1) if p.get("technical") else round(p["indicators"]["low20"] * 0.97, -1)
    if p["price"] <= expected:
        assert r.status_code == 422
        return
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["exit_close_below"] == pytest.approx(expected)          # mặc định: mức vô hiệu kỹ thuật (mục 6d)
    assert date.fromisoformat(d["review_on"]) > date.fromisoformat(d["decided_at"])
    bad = client.put("/api/holds", params={"broker": "demo"},
                     json={"symbol": sym, "reason": "Tin rằng ngành đang ở đáy chu kỳ", "exit_close_below": p["price"] * 2})
    assert bad.status_code == 422
    row = next(x for x in client.get("/api/positions", params={"broker": "demo"}).json()["positions"] if x["symbol"] == sym)
    assert row["hold"]["decision"]["id"] == d["id"]
    assert client.delete(f"/api/holds/{d['id']}").status_code == 200
    assert client.get("/api/holds", params={"broker": "demo"}).json() == []

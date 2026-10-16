"""Đảo hàng khi hồi (mục 6b): bán một phần lúc hồi, mua lại lúc chỉnh, không bao giờ tăng vị thế."""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pytest

from app.models import MarketInfo, MarketState, RotationTrade
from app.risk.indicators import compute_series
from app.risk.rotation import build_rotation

from app.config import get_settings

from .conftest import flat, make_df


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

NORMAL = MarketInfo(state=MarketState.NORMAL)
WEAK = MarketInfo(state=MarketState.WEAK)
DECLINE = flat(20, 100) + list(np.linspace(100, 60, 40))      # đỉnh ~101, đáy ~59,4


def run(closes, *, cost=100.0, qty=10_000, trades=(), thesis=None, margin_ok=True, market=NORMAL, mode="swing"):
    s = compute_series(make_df(closes))
    today = s["date"].iloc[-1]
    return build_rotation(s=s, price=closes[-1], qty=qty, cost=cost, mode=mode, thesis=thesis, market=market,
                          margin_ok=margin_ok, trades=list(trades), rules=RULES, today=today), s


@pytest.fixture(autouse=True)
def _rules(rules):
    global RULES
    RULES = rules


def sell(s, idx, qty, price, i=1):
    return RotationTrade(id=i, broker="t", account_id="a", symbol="AAA", side="sell",
                         trade_date=s["date"].iloc[idx], quantity=qty, price=price)


def test_sat_day_khong_khuyen_mua_them():
    p, _ = run(DECLINE)
    assert p.phase == "falling" and p.level == "none" and p.sell_qty == 0
    assert "không mua thêm" in p.text
    assert p.tier_prices[0] > p.low


def test_dang_hoi_chua_toi_vung_ban():
    p, _ = run(DECLINE + [62, 63.5])
    assert p.phase == "rebounding" and p.level == "watch"


def test_hoi_10_phan_tram_ban_bac_1_30_phan_tram():
    p, _ = run(DECLINE + [62, 64, 66.5])
    assert p.phase == "sell_zone" and p.level == "sell"
    assert p.sell_qty == 3_000
    assert "Mua lại khi giá về" in p.text


def test_hoi_20_phan_tram_ban_toi_da_mot_nua():
    p, _ = run(DECLINE + [63, 66, 69, 72.5])
    assert p.sell_qty == 5_000                  # 30% + 20%, trần 50%
    assert p.base_qty == 10_000


def test_nhom_b_chi_ban_khong_mua_lai():
    p, _ = run(DECLINE + [62, 64, 66.5], thesis=False)
    assert p.level == "sell" and not p.rebuy_allowed and "không mua lại" in p.text


def test_dang_lai_hoac_dca_khong_ap_dung():
    assert run(DECLINE + [62, 64, 66.5], cost=50)[0] is None
    assert run(DECLINE + [62, 64, 66.5], mode="dca")[0] is None


def test_lay_lai_qua_618_va_tren_sma50_la_doi_xu_huong():
    closes = DECLINE + list(np.linspace(62, 90, 15))
    p, s = run(closes)
    assert float(s["close"].iloc[-1]) > float(s["sma50"].iloc[-1])
    assert p.phase == "trend_change" and p.sell_qty == 0


REBOUND = DECLINE + [62, 64, 67]          # bán 3.000 ở 67 (phiên cuối của đoạn này)


def sold(closes):
    """Lần bán 3.000 cp giá 67 vào phiên thứ len(REBOUND) của chuỗi đầy đủ (ngày khớp với nến)."""
    _, s = run(closes)
    return sell(s, len(REBOUND) - 1, 3_000, 67)


def test_du_dieu_kien_mua_lai_dung_so_da_ban():
    closes = REBOUND + [65, 63, 61, 60.5, 61.8]
    p, _ = run(closes, qty=7_000, trades=[sold(closes)])
    assert p.open_qty == 3_000 and p.base_qty == 10_000
    assert p.rebuy_below == pytest.approx(67 * 0.93)
    assert {c.code: c.met for c in p.checks} == {"below_sell": True, "above_floor": True, "reversal": True,
                                                  "settled": True, "market": True, "margin": True}
    assert p.phase == "rebuy_zone" and p.level == "rebuy" and p.rebuy_qty == 3_000
    assert "mục 3.5" in p.text


def test_margin_sat_nguong_khoa_mua_lai():
    closes = REBOUND + [65, 63, 61, 60.5, 61.8]
    p, _ = run(closes, qty=7_000, trades=[sold(closes)], margin_ok=False)
    assert p.phase == "wait_rebuy" and p.level == "blocked" and "trả nợ" in p.text


def test_thi_truong_yeu_chua_mua_lai():
    closes = REBOUND + [65, 63, 61, 60.5, 61.8]
    p, _ = run(closes, qty=7_000, trades=[sold(closes)], market=WEAK)
    assert p.phase == "wait_rebuy" and p.level == "watch"


def test_thung_day_cu_thi_khong_mua_lai():
    closes = REBOUND + [64, 61, 58, 57, 58.5]
    p, _ = run(closes, qty=7_000, trades=[sold(closes)])
    assert p.phase == "broken" and p.rebuy_qty == 0 and "KHÔNG mua lại" in p.text


def test_gia_vuot_xa_gia_ban_khong_mua_duoi():
    closes = REBOUND + list(np.linspace(70, 92, 12))
    p, _ = run(closes, qty=7_000, trades=[sold(closes)])
    assert p.phase == "missed" and "không mua đuổi" in p.text


def test_mua_lai_du_thi_dong_chu_ky():
    closes = REBOUND + [65, 63, 61, 60.5, 61.8]
    _, s1 = run(closes)
    buy = RotationTrade(id=2, broker="t", account_id="a", symbol="AAA", side="buy", trade_date=s1["date"].iloc[-1],
                        quantity=3_000, price=61.8)
    p, _ = run(closes, qty=10_000, trades=[sold(closes), buy])
    assert p.open_qty == 0 and p.phase in ("falling", "rebounding")


def test_qua_han_khong_mua_lai_thi_coi_nhu_ban_han():
    closes = REBOUND + [66] * 25
    p, _ = run(closes, qty=7_000, trades=[sold(closes)])
    assert p.open_qty == 0 and "coi như đã bán hẳn" in p.text


def test_api_ghi_nhat_ky_va_chan_mua_lai_vuot_so_da_ban(client):
    today = __import__("app.util", fromlist=["now_vn"]).now_vn().date()
    d = today - timedelta(days=1 if today.weekday() else 3)
    r = client.post("/api/rotations", params={"broker": "demo"},
                    json={"symbol": "VND", "side": "sell", "trade_date": d.isoformat(), "quantity": 1000, "price": 20_000})
    assert r.status_code == 200, r.text
    r = client.post("/api/rotations", params={"broker": "demo"},
                    json={"symbol": "VND", "side": "buy", "trade_date": today.isoformat(), "quantity": 1500, "price": 18_000})
    assert r.status_code == 422 and "tối đa 1.000" in r.json()["detail"]["message"]
    r = client.post("/api/rotations", params={"broker": "demo"},
                    json={"symbol": "FPT", "side": "buy", "trade_date": today.isoformat(), "quantity": 100, "price": 1})
    assert r.status_code == 422
    rows = client.get("/api/rotations", params={"broker": "demo"}).json()
    assert [x["side"] for x in rows] == ["sell"]
    assert client.delete(f"/api/rotations/{rows[0]['id']}").status_code == 200
    assert client.get("/api/rotations", params={"broker": "demo"}).json() == []



def test_lo_mua_them_phai_ban_di_truoc_dao_hang():
    """Lô mua thêm đã thủng cắt lỗ (mục 3.5) được nhắc trước; đảo hàng không được làm người dùng chờ hồi."""
    from types import SimpleNamespace

    from app.models import LotEval, MarginOverview
    from app.risk.engine import evaluate_position
    from app.services.portfolio import PortfolioService

    from .conftest import make_position

    closes = DECLINE + [62, 64, 66.5]
    df = make_df(closes)
    pos = make_position(qty=10_000, cost=100, price=closes[-1])
    e = evaluate_position(pos, df, None, RULES, NORMAL, pos.market_value)
    e.lots = [LotEval.model_construct(rule_status="stop", remaining=2_000)]
    e.actions.insert(0, "Lô mua ngày 11/09 phải bán")
    fake = SimpleNamespace(rotations=SimpleNamespace(trades=lambda *a: []))
    PortfolioService._apply_rotation(fake, e, pos, df, "t", "a", MarginOverview.model_construct(buckets=[]), NORMAL,
                                     RULES, df["date"].iloc[-1])
    assert e.rotation.level == "sell"
    assert e.rotation.text.startswith("Trước hết bán 2.000 cổ phiếu của các lô mua thêm đã tới luật bán (mục 3.5), không chờ")
    assert e.actions[0] == "Lô mua ngày 11/09 phải bán" and e.actions[1] == e.rotation.text

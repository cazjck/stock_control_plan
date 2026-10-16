"""Sổ danh mục tổng: nhập tay (SSI, VPS), đồng bộ từ broker thật, và đánh giá rủi ro trên sổ."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.brokers.ledger import ALL, LedgerAdapter
from app.config import get_settings
from app.models import Position
from app.storage.db import Store
from app.storage.ledger import LedgerError, LedgerRepo


@pytest.fixture
def repo(tmp_path):
    return LedgerRepo(Store(tmp_path / "l.sqlite"))


# ---------------- lưu trữ ----------------

def test_purchase_merges_and_recomputes_average_cost(repo):
    a = repo.create_account("SSI")
    repo.record_purchase(a.id, "hpg", 1000, price=28_000)
    p = repo.record_purchase(a.id, "HPG", 1000, total_amount=24_000_000)
    assert (p.symbol, p.quantity, p.avg_cost) == ("HPG", 2000, 26_000)


@pytest.mark.parametrize("kw,msg", [
    ({"price": None, "total_amount": None}, "chỉ một trong hai"),
    ({"price": 1.0, "total_amount": 5.0}, "chỉ một trong hai"),
    ({"price": -1.0}, "lớn hơn 0"),
])
def test_purchase_validation(repo, kw, msg):
    a = repo.create_account("VPS")
    with pytest.raises(LedgerError, match=msg):
        repo.record_purchase(a.id, "FPT", 100, **kw)
    with pytest.raises(LedgerError):
        repo.record_purchase(a.id, "fpt!", 100, price=1)


def test_account_names_unique_and_ids_safe(repo):
    a = repo.create_account("Chứng khoán SSI")
    assert a.id == "chung-khoan-ssi"
    with pytest.raises(LedgerError):
        repo.create_account("chứng khoán ssi")
    with pytest.raises(LedgerError):
        repo.create_account("   ")


def test_delete_account_cascades(repo):
    a = repo.create_account("SSI")
    repo.record_purchase(a.id, "HPG", 100, price=1000)
    repo.add_debt(a.id, principal=1e6)
    repo.delete_account(a.id)
    assert repo.positions() == [] and repo.debts() == []


def test_synced_account_is_read_only(repo):
    from app.models import LedgerAccount
    repo.replace_synced(LedgerAccount(id="tcbs-1", name="TCBS · 1", source="sync", source_broker="tcbs"),
                        [{"symbol": "PDR", "quantity": 100, "avg_cost": 23000, "last_price": 11200}],
                        [{"principal": 5e6, "remaining_principal": 5e6}])
    pid = repo.positions("tcbs-1")[0].id
    for call in (lambda: repo.record_purchase("tcbs-1", "PDR", 1, price=1),
                 lambda: repo.update_position(pid, quantity=5), lambda: repo.delete_position(pid),
                 lambda: repo.add_debt("tcbs-1", principal=1), lambda: repo.delete_debt(repo.debts()[0].id)):
        with pytest.raises(LedgerError, match="đồng bộ"):
            call()
    # đổi tên vẫn được, các trường số bị bỏ qua
    a = repo.update_account("tcbs-1", name="TCBS chính", cash=999)
    assert a.name == "TCBS chính" and a.cash == 0


# ---------------- adapter ----------------

async def test_all_keeps_one_row_per_source(repo):
    ssi, vps = repo.create_account("SSI"), repo.create_account("VPS")
    repo.record_purchase(ssi.id, "HPG", 1000, price=30_000)
    repo.record_purchase(vps.id, "HPG", 3000, price=26_000)
    repo.record_purchase(vps.id, "FPT", 100, price=100_000)
    ad = LedgerAdapter(repo, lambda: None)
    accs = await ad.list_accounts()
    assert [a.id for a in accs] == [ALL, "ssi", "vps"]
    rows = await ad.get_positions(ALL)
    assert [(p.symbol, p.sources[0].source, p.quantity, p.avg_cost) for p in rows] == [
        ("FPT", "VPS", 100, 100_000), ("HPG", "SSI", 1000, 30_000), ("HPG", "VPS", 3000, 26_000)]
    assert len({p.row_id for p in rows}) == 3
    assert [p.symbol for p in await ad.get_positions("ssi")] == ["HPG"]


async def test_margin_bucket_per_broker_equity_kind(repo):
    ssi = repo.create_account("SSI", maintenance_pct=30, liquidation_pct=25)
    repo.record_purchase(ssi.id, "HPG", 10_000, price=25_000)       # 250 tr
    repo.add_debt(ssi.id, principal=100e6, accrued_interest=0, annual_rate_pct=12)
    ad = LedgerAdapter(repo, lambda: None)
    positions = [Position(broker="ledger", account_id=ALL, symbol="HPG", quantity=10_000, avg_cost=25_000,
                          price=20_000, market_value=200e6)]
    b = (await ad.get_margin(ALL, positions))[0]
    assert b.ratio_kind == "equity_over_value"
    assert b.market_value == 200e6 and b.debt == 100e6
    assert b.ratio_pct == pytest.approx(50.0)                       # (200 − 100) / 200 tính theo giá hiện tại
    loans = await ad.get_loans(ALL)
    assert len(loans) == 1 and loans[0].symbol is None and loans[0].source == "SSI"


async def test_collateral_ratio_is_rescaled_by_current_value(repo):
    vps = repo.create_account("VPS", ratio_kind="collateral_over_debt", ratio_pct=120.0, ratio_ref_value=100e6,
                              maintenance_pct=85, liquidation_pct=80)
    repo.record_purchase(vps.id, "SSI", 4000, price=25_000)          # 100 tr theo giá mua
    repo.add_debt(vps.id, principal=50e6)
    ad = LedgerAdapter(repo, lambda: None)
    pos = [Position(broker="ledger", account_id=ALL, symbol="SSI", quantity=4000, avg_cost=25_000, price=22_500, market_value=90e6)]
    b = (await ad.get_margin(ALL, pos))[0]
    assert b.ratio_pct == pytest.approx(108.0)                       # 120 × 90/100
    repo.update_account(vps.id, ratio_pct=None)
    b2 = (await ad.get_margin(ALL, pos))[0]
    assert b2.ratio_pct is None and "Nhập RTT" in b2.status_text


async def test_no_price_source_means_no_candles_but_quotes_empty(repo):
    from app.brokers.base import BrokerError
    ad = LedgerAdapter(repo, lambda: None)
    assert await ad.get_quotes(["HPG"]) == {}
    with pytest.raises(BrokerError, match="nguồn giá"):
        from app.models import Interval
        await ad.get_candles("HPG", Interval.D1, 10)


# ---------------- API ----------------

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


def test_ledger_is_listed_as_a_broker(client):
    names = [b["name"] for b in client.get("/api/brokers").json()]
    assert names == ["demo", "ledger"]


def test_manual_flow_end_to_end(client):
    a = client.post("/api/ledger/accounts", json={"name": "SSI", "cash": 5_000_000, "maintenance_pct": 30,
                                                  "liquidation_pct": 25}).json()
    assert a["id"] == "ssi"
    r = client.post(f"/api/ledger/accounts/{a['id']}/purchases", json={"symbol": "fpt", "quantity": 1000, "total_amount": 100_000_000})
    assert r.status_code == 200 and r.json()["avg_cost"] == 100_000
    client.post(f"/api/ledger/accounts/{a['id']}/debts", json={"principal": 40_000_000, "annual_rate_pct": 13, "due_date": "2027-01-15"})
    led = client.get("/api/ledger").json()
    acc = led["accounts"][0]
    assert acc["totals"]["cost"] == 100_000_000 and acc["totals"]["debt"] == 40_000_000
    # nguồn giá demo có FPT giá 126.500
    assert led["price_source"] == "Demo (dữ liệu mẫu)" and acc["positions"][0]["price"] == 126_500
    assert acc["positions"][0]["pnl_pct"] == pytest.approx(26.5)

    o = client.get("/api/overview", params={"broker": "ledger"}).json()
    assert o["account_id"] == "ALL"
    b = o["margin"]["buckets"][0]["bucket"]
    assert b["label"] == "SSI" and b["ratio_pct"] == pytest.approx((126.5 - 40) / 126.5 * 100)
    p = client.get("/api/positions", params={"broker": "ledger"}).json()["positions"]
    assert p[0]["symbol"] == "FPT" and p[0]["status"] == "TAKE_PROFIT"     # +26,5% chạm bậc chốt lời


def test_ledger_validation_errors_are_readable(client):
    client.post("/api/ledger/accounts", json={"name": "VPS"})
    r = client.post("/api/ledger/accounts/vps/purchases", json={"symbol": "HPG", "quantity": 100})
    assert r.status_code == 422
    r = client.post("/api/ledger/accounts/vps/purchases", json={"symbol": "HPG", "quantity": 0, "price": 1})
    assert r.status_code == 422
    r = client.post("/api/ledger/accounts", json={"name": "vps"})
    assert r.status_code == 422 and "Đã có" in r.json()["detail"]["message"]
    assert client.post("/api/ledger/accounts/khong-co/purchases", json={"symbol": "HPG", "quantity": 1, "price": 1}).status_code == 422


def test_edit_and_delete_rows(client):
    client.post("/api/ledger/accounts", json={"name": "VPS"})
    pid = client.post("/api/ledger/accounts/vps/purchases", json={"symbol": "HPG", "quantity": 100, "price": 25_000}).json()["id"]
    assert client.put(f"/api/ledger/positions/{pid}", json={"quantity": 300}).json()["quantity"] == 300
    did = client.post("/api/ledger/accounts/vps/debts", json={"principal": 1_000_000}).json()["id"]
    assert client.put(f"/api/ledger/debts/{did}", json={"remaining_principal": 500_000}).json()["remaining_principal"] == 500_000
    assert client.delete(f"/api/ledger/debts/{did}").status_code == 200
    assert client.delete(f"/api/ledger/positions/{pid}").status_code == 200
    assert client.delete("/api/ledger/accounts/vps").status_code == 200
    assert client.get("/api/ledger").json()["accounts"] == []


def test_recording_app_rtt_stores_reference_value(client):
    client.post("/api/ledger/accounts", json={"name": "VPS", "ratio_kind": "collateral_over_debt"})
    client.post("/api/ledger/accounts/vps/purchases", json={"symbol": "SSI", "quantity": 1000, "price": 26_000})
    a = client.put("/api/ledger/accounts/vps", json={"ratio_pct": 130, "maintenance_pct": 85}).json()
    assert a["ratio_pct"] == 130 and a["ratio_ref_value"] == 26_000_000


def test_sync_copies_broker_into_ledger_and_is_repeatable(client):
    r = client.post("/api/ledger/sync/demo")
    assert r.status_code == 200 and r.json()["positions"] == 5 and r.json()["debts"] == 3
    client.post("/api/ledger/sync/demo")                               # đồng bộ lại: thay thế, không nhân đôi
    led = client.get("/api/ledger").json()
    assert len(led["accounts"]) == 1
    acc = led["accounts"][0]
    assert acc["source"] == "sync" and acc["source_broker"] == "demo" and acc["synced_at"]
    assert len(acc["positions"]) == 5 and len(acc["debts"]) == 3
    assert acc["cash"] == 12_300_000
    # phần đồng bộ không sửa tay được
    pid = acc["positions"][0]["id"]
    r = client.put(f"/api/ledger/positions/{pid}", json={"quantity": 1})
    assert r.status_code == 422 and "đồng bộ" in r.json()["detail"]["message"]
    # sổ tổng sau đồng bộ cho ra cùng giá trị cổ phiếu với broker gốc
    src = client.get("/api/overview", params={"broker": "demo"}).json()["assets"]
    led_o = client.get("/api/overview", params={"broker": "ledger"}).json()["assets"]
    assert led_o["positions_value"] == pytest.approx(src["positions_value"])
    assert led_o["debt"] == pytest.approx(src["debt"])


def test_sync_refuses_ledger_and_unknown(client):
    assert client.post("/api/ledger/sync/ledger").status_code == 502
    assert client.post("/api/ledger/sync/tcbs").status_code == 404


def test_manual_and_synced_rows_are_evaluated_separately(client):
    client.post("/api/ledger/sync/demo")
    client.post("/api/ledger/accounts", json={"name": "SSI"})
    client.post("/api/ledger/accounts/ssi/purchases", json={"symbol": "FPT", "quantity": 1000, "price": 100_000})
    rows = [p for p in client.get("/api/positions", params={"broker": "ledger"}).json()["positions"] if p["symbol"] == "FPT"]
    by = {r["source"]: r for r in rows}
    assert set(by) == {"Demo", "SSI"}
    assert by["Demo"]["avg_cost"] == 112_000 and by["SSI"]["avg_cost"] == 100_000     # mỗi nguồn giữ giá vốn riêng
    assert by["SSI"]["pnl_pct"] > by["Demo"]["pnl_pct"]                                # và lãi lỗ riêng
    assert by["Demo"]["stop_level"] != by["SSI"]["stop_level"]                         # mức cắt lỗ tính riêng
    accs = client.get("/api/accounts", params={"broker": "ledger"}).json()
    assert [a["id"] for a in accs][:1] == ["ALL"] and len(accs) == 3
    # bảng giá và kịch bản vẫn gộp theo mã
    board = client.get("/api/board", params={"broker": "ledger"}).json()
    fpt = next(r for r in board["rows"] if r["symbol"] == "FPT")
    assert fpt["held_qty"] == 2000 and fpt["avg_cost"] == pytest.approx(106_000) and sorted(fpt["sources"]) == ["Demo", "SSI"]


def test_alerts_per_source_row_and_chart_row_selection(client):
    client.post("/api/ledger/sync/demo")
    client.post("/api/ledger/accounts", json={"name": "SSI"})
    client.post("/api/ledger/accounts/ssi/purchases", json={"symbol": "HPG", "quantity": 1000, "price": 30_000})
    client.get("/api/overview", params={"broker": "ledger"})
    titles = [a["title"] for a in client.get("/api/alerts", params={"broker": "ledger", "account": "ALL"}).json() if a["symbol"] == "HPG"]
    assert any("(SSI)" in t for t in titles) and any("(Demo)" in t for t in titles)
    ch = client.get("/api/symbols/HPG/chart", params={"broker": "ledger", "row": "ssi:HPG"}).json()
    assert ch["avg_cost"] == 30_000 and ch["evaluation"]["source"] == "SSI"
    assert sorted(e["source"] for e in ch["evaluations"]) == ["Demo", "SSI"]


def test_sources_are_shown_per_position_bucket_and_loan(client):
    client.post("/api/ledger/sync/demo")
    client.post("/api/ledger/accounts", json={"name": "SSI", "maintenance_pct": 30})
    client.post("/api/ledger/accounts/ssi/purchases", json={"symbol": "FPT", "quantity": 500, "price": 100_000})
    client.post("/api/ledger/accounts/ssi/debts", json={"principal": 20_000_000})
    rows = client.get("/api/positions", params={"broker": "ledger"}).json()["positions"]
    assert sorted((r["source"], r["quantity"]) for r in rows if r["symbol"] == "FPT") == [("Demo", 1000), ("SSI", 500)]
    assert [r["source"] for r in rows if r["symbol"] == "HPG"] == ["Demo"]
    m = client.get("/api/margin", params={"broker": "ledger"}).json()
    assert sorted(b["bucket"]["source"] for b in m["buckets"]) == ["Demo", "SSI"]
    assert {l["source"] for l in m["loans"]} == {"Demo", "SSI"}


def test_real_broker_views_label_their_own_source(client):
    p = client.get("/api/positions", params={"broker": "demo"}).json()["positions"]
    assert all(e["sources"] == [{"source": "Demo", "account": "DEMO-0001", "quantity": e["quantity"], "avg_cost": e["avg_cost"]}] for e in p)
    m = client.get("/api/margin", params={"broker": "demo"}).json()
    assert m["buckets"][0]["bucket"]["source"] == "Demo" and all(l["source"] == "Demo" for l in m["loans"])


async def test_paid_principal_with_unpaid_interest_still_counts(repo):
    a = repo.create_account("VPS")
    repo.add_debt(a.id, principal=35_003_300, remaining_principal=0, accrued_interest=196_845)
    repo.add_debt(a.id, principal=1_000, remaining_principal=0, accrued_interest=0)       # đã tất toán hẳn
    loans = await LedgerAdapter(repo, lambda: None).get_loans(ALL)
    assert [(l.remaining_principal, l.accrued_interest) for l in loans] == [(0, 196_845)]

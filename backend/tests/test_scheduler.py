from __future__ import annotations

from app.brokers.registry import build_adapters
from app.config import Settings
from app.main import daily_snapshot
from app.services.portfolio import PortfolioService
from app.services.rules_service import RulesService
from app.storage.db import Store


async def test_daily_snapshot_stores_one_row_per_account(tmp_path):
    s = Settings(data_dir=tmp_path, brokers="demo")
    store = Store(tmp_path / "t.sqlite")
    svc = PortfolioService(s, build_adapters(s), store, RulesService(store))
    await daily_snapshot(svc)
    await daily_snapshot(svc)                       # chạy lại cùng ngày: ghi đè, không nhân đôi
    rows = store.list_snapshots("demo", "DEMO-0001")
    assert len(rows) == 1
    r = rows[0]
    assert r["nav"] == r["positions_value"] + r["cash"] - r["debt"]
    assert r["debt"] > 0 and r["min_rtt_gap"] > 0
    store.close()


async def test_daily_snapshot_skips_unauthenticated_brokers(tmp_path):
    s = Settings(data_dir=tmp_path, brokers="tcbs", tcbs_api_key="k", tcbs_custody_code="105C000001")
    store = Store(tmp_path / "t.sqlite")
    svc = PortfolioService(s, build_adapters(s), store, RulesService(store))
    await daily_snapshot(svc)                       # chưa có token TCBS nên bỏ qua, không lỗi
    assert store.list_snapshots("tcbs", "x") == []
    store.close()
    for a in svc.adapters.values():
        await a.aclose()

"""Dựng danh sách adapter từ cấu hình."""
from __future__ import annotations

from ..config import Settings
from .base import BrokerAdapter
from .demo import DemoAdapter
from ..storage.ledger import LedgerRepo
from .dnse import DnseAdapter
from .ledger import LedgerAdapter
from .tcbs import TcbsAdapter


def price_source_from(adapters: dict[str, BrokerAdapter]):
    """Nguồn giá cho danh mục tổng: broker thật đầu tiên đang đăng nhập, ưu tiên TCBS rồi DNSE, cuối cùng là demo."""
    def pick() -> BrokerAdapter | None:
        for name in ("tcbs", "dnse", "demo"):
            a = adapters.get(name)
            if a is not None and a.session_info().authenticated:
                return a
        return None
    return pick


def build_adapters(s: Settings, ledger_repo: LedgerRepo | None = None) -> dict[str, BrokerAdapter]:
    out: dict[str, BrokerAdapter] = {}
    for name in s.enabled_brokers:
        if name == "demo":
            out[name] = DemoAdapter()
        elif name == "tcbs":
            out[name] = TcbsAdapter(api_key=s.tcbs_api_key, custody_code=s.tcbs_custody_code,
                                    base_url=s.tcbs_base_url, data_dir=s.resolved_data_dir)
        elif name == "dnse":
            out[name] = DnseAdapter(api_key=s.dnse_api_key, api_secret=s.dnse_api_secret,
                                    base_url=s.dnse_base_url, api_version=s.dnse_api_version)
        else:
            raise ValueError(f"Broker không hỗ trợ: {name}")
    if ledger_repo is not None:
        out["ledger"] = LedgerAdapter(ledger_repo, price_source_from(dict(out)))
    return out

"""Dựng danh sách adapter từ cấu hình."""
from __future__ import annotations

import json
from typing import Callable

from ..config import Settings
from .base import BrokerAdapter
from .demo import DemoAdapter
from ..storage.ledger import LedgerRepo
from .dnse import DnseAdapter
from .ledger import LedgerAdapter
from .tcbs import TcbsAdapter


SOURCES = ("tcbs", "dnse")
DEFAULT_PREF = {"primary": "tcbs", "fallback": True}


def parse_pref(raw: str | None) -> dict:
    try:
        p = {**DEFAULT_PREF, **(json.loads(raw) if raw else {})}
    except ValueError:
        p = dict(DEFAULT_PREF)
    if p["primary"] not in SOURCES:
        p["primary"] = DEFAULT_PREF["primary"]
    p["fallback"] = bool(p["fallback"])
    return p


def source_order(pref: dict) -> list[str]:
    """Thứ tự thử nguồn giá: nguồn chính, rồi nguồn còn lại nếu cho phép dự phòng, cuối cùng là demo."""
    first = pref["primary"]
    other = [s for s in SOURCES if s != first]
    return [first] + (other if pref["fallback"] else []) + ["demo"]


def price_source_from(adapters: dict[str, BrokerAdapter], pref_getter: Callable[[], str | None] | None = None):
    """Nguồn giá cho danh mục tổng theo lựa chọn ở trang Thiết lập (mặc định: TCBS trước, DNSE dự phòng).
    Chỉ chọn nguồn đang dùng được (đã đăng nhập hoặc có khoá)."""
    def pick() -> BrokerAdapter | None:
        pref = parse_pref(pref_getter() if pref_getter else None)
        for name in source_order(pref):
            a = adapters.get(name)
            if a is not None and a.session_info().authenticated:
                return a
        return None
    return pick


def build_adapters(s: Settings, ledger_repo: LedgerRepo | None = None,
                   pref_getter: Callable[[], str | None] | None = None) -> dict[str, BrokerAdapter]:
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
        out["ledger"] = LedgerAdapter(ledger_repo, price_source_from(dict(out), pref_getter))
    return out

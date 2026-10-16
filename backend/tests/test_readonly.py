"""Bảo đảm tính READ-ONLY của dự án ở nhiều lớp: giao diện, HTTP client, mã nguồn, và lưu lượng thực."""
from __future__ import annotations

import base64
import inspect
import json
import re
import time
from pathlib import Path

import httpx
import pytest
import respx

from app.brokers.base import BrokerAdapter, ReadOnlyHttp, ReadOnlyViolation
from app.brokers.demo import DemoAdapter
from app.brokers.dnse import DnseAdapter
from app.brokers.ledger import LedgerAdapter
from app.brokers.tcbs import TcbsAdapter
from app.models import Interval

APP = Path(__file__).resolve().parents[1] / "app"
FORBIDDEN = re.compile(r"(order|place|cancel|amend|replace|transfer|withdraw|deposit|buy|sell|trade|close_position)", re.I)


def _public_methods(cls):
    return [n for n, _ in inspect.getmembers(cls, predicate=callable) if not n.startswith("_")]


@pytest.mark.parametrize("cls", [BrokerAdapter, DemoAdapter, TcbsAdapter, DnseAdapter, LedgerAdapter])
def test_adapters_expose_no_trading_methods(cls):
    bad = [m for m in _public_methods(cls) if FORBIDDEN.search(m)]
    assert bad == [], f"{cls.__name__} có phương thức giống giao dịch: {bad}"


def test_readonly_http_has_no_write_verbs():
    assert not any(hasattr(ReadOnlyHttp, v) for v in ("post", "put", "delete", "patch", "request", "send"))


async def test_auth_post_rejects_non_allowlisted_path():
    http = ReadOnlyHttp("https://example.test", auth_post_allowlist=frozenset({"/login"}))
    with pytest.raises(ReadOnlyViolation):
        await http.auth_post("/orders", {"x": 1})
    await http.aclose()


def test_no_write_http_calls_in_broker_or_service_code():
    """Mã nguồn broker và service không được gọi post/put/delete/patch trực tiếp (chỉ ReadOnlyHttp.auth_post)."""
    pat = re.compile(r"\.(post|put|delete|patch)\(")
    offenders = []
    for f in list((APP / "brokers").glob("*.py")) + list((APP / "services").glob("*.py")):
        if f.name == "base.py":
            continue
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if pat.search(line):
                offenders.append(f"{f.name}:{i}: {line.strip()}")
    assert offenders == []


def test_no_order_endpoint_paths_in_adapters():
    pat = re.compile(r"/orders|/order/|/cash/(deposit|withdraw)|/stock/transfer|/trading-token|/send-email-otp|/close\b", re.I)
    offenders = []
    for f in (APP / "brokers").glob("*.py"):
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if pat.search(line) and not line.strip().startswith(("#", '"""')):
                offenders.append(f"{f.name}:{i}: {line.strip()}")
    assert offenders == []


# ---------- lưu lượng thực: mọi request ra ngoài chỉ là GET (trừ POST lấy token TCBS) ----------

def _jwt(exp: float) -> str:
    b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{b({'alg': 'none'})}.{b({'exp': exp})}.sig"


@respx.mock
async def test_tcbs_traffic_is_get_only_except_token(tmp_path):
    base = "https://openapi.tcbs.com.vn"
    respx.post(f"{base}/gaia/v1/oauth2/openapi/token").mock(
        return_value=httpx.Response(200, json={"token": _jwt(time.time() + 3600)}))
    respx.get(url__regex=rf"{base}/.*").mock(return_value=httpx.Response(200, json={}))
    ad = TcbsAdapter(api_key="k", custody_code="105C000000", base_url=base, data_dir=tmp_path)
    await ad.authenticate("123456")
    await ad.list_accounts(); await ad.get_positions("A"); await ad.get_cash("A")
    await ad.get_margin("A", []); await ad.get_loans("A")
    await ad.get_candles("FPT", Interval.D1, 10); await ad.get_quotes(["FPT"])
    methods = {c.request.method for c in respx.calls}
    assert methods == {"GET", "POST"}
    posts = [c.request.url.path for c in respx.calls if c.request.method == "POST"]
    assert posts == ["/gaia/v1/oauth2/openapi/token"]
    await ad.aclose()


@respx.mock
async def test_dnse_traffic_is_get_only():
    base = "https://openapi.dnse.com.vn"
    respx.get(url__regex=rf"{base}/.*").mock(return_value=httpx.Response(200, json={}))
    ad = DnseAdapter(api_key="k", api_secret="s", base_url=base, api_version="2026-07-23")
    await ad.list_accounts(); await ad.get_positions("A"); await ad.get_cash("A"); await ad.get_loans("A")
    await ad.get_margin("A", []); await ad.get_candles("FPT", Interval.D1, 10); await ad.get_quotes(["FPT"])
    assert {c.request.method for c in respx.calls} == {"GET"}
    await ad.aclose()

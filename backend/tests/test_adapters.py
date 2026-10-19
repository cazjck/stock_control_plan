"""Kiểm tra ánh xạ dữ liệu của adapter bằng phản hồi mô phỏng theo OpenAPI spec của từng broker."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from urllib.parse import quote

import httpx
import pytest
import respx

from app.brokers.base import AuthRequired
from app.brokers.dnse import DnseAdapter, build_signature
from app.brokers.tcbs import TcbsAdapter
from app.models import Interval
from .test_readonly import _jwt

TCBS = "https://openapi.tcbs.com.vn"
DNSE = "https://openapi.dnse.com.vn"


# ---------------- TCBS ----------------

def tcbs(tmp_path):
    return TcbsAdapter(api_key="key", custody_code="105C000001", base_url=TCBS, data_dir=tmp_path)


async def test_tcbs_requires_otp_before_any_call(tmp_path):
    ad = tcbs(tmp_path)
    info = ad.session_info()
    assert info.configured and not info.authenticated and info.needs_otp
    with pytest.raises(AuthRequired):
        await ad.list_accounts()
    await ad.aclose()


@respx.mock
async def test_tcbs_token_is_persisted_with_private_permissions(tmp_path):
    respx.post(f"{TCBS}/gaia/v1/oauth2/openapi/token").mock(
        return_value=httpx.Response(200, json={"token": _jwt(time.time() + 7200)}))
    ad = tcbs(tmp_path)
    info = await ad.authenticate("111111")
    assert info.authenticated and info.expires_at is not None
    f = tmp_path / "tcbs_token.json"
    assert f.exists() and oct(f.stat().st_mode & 0o777) == "0o600"
    # adapter mới nạp lại token từ đĩa, không cần OTP
    ad2 = tcbs(tmp_path)
    assert ad2.session_info().authenticated
    await ad.aclose(); await ad2.aclose()


@respx.mock
async def test_tcbs_401_clears_session(tmp_path):
    respx.post(f"{TCBS}/gaia/v1/oauth2/openapi/token").mock(
        return_value=httpx.Response(200, json={"token": _jwt(time.time() + 7200)}))
    respx.get(f"{TCBS}/aion/v1/customers/105C000001/accounts").mock(return_value=httpx.Response(401))
    ad = tcbs(tmp_path)
    await ad.authenticate("1")
    with pytest.raises(AuthRequired):
        await ad.list_accounts()
    assert ad.session_info().needs_otp
    await ad.aclose()


@respx.mock
async def test_tcbs_mapping(tmp_path):
    respx.post(f"{TCBS}/gaia/v1/oauth2/openapi/token").mock(
        return_value=httpx.Response(200, json={"token": _jwt(time.time() + 7200)}))
    respx.get(f"{TCBS}/aion/v1/customers/105C000001/accounts").mock(return_value=httpx.Response(200, json=[
        {"custodyID": "105C000001", "accountNo": "0001", "accountType": "margin", "accountStatus": "A", "marginLimit": 5e8},
        {"custodyID": "105C000001", "accountNo": "0002", "accountType": "normal", "accountStatus": "C"}]))
    # cấu trúc thật quan sát được ngày 16/10/2026 (giá trị đã thay bằng số giả)
    respx.get(f"{TCBS}/aion/v1/accounts/0001/se").mock(return_value=httpx.Response(200, json={
        "object": "SE", "accountNo": "0001", "stock": [
            {"symbol": "fpt", "secType": "001", "totalQtty": 1000, "costPrice": 110000, "currentPrice": 125000, "availableTrading": 1000, "t0": 0, "t1": 0, "t2": 0},
            {"symbol": "ZZZ", "totalQtty": 0, "costPrice": 1, "currentPrice": 1}]}))
    respx.get(f"{TCBS}/aion/v1/accounts/0001/cashInvestments").mock(return_value=httpx.Response(200, json={
        "data": [{"accountNo": "0001", "cashBalance": 12_000_000, "pp0forBF": 3}]}))
    respx.get(f"{TCBS}/hydros/v1/account/0001/risk").mock(return_value=httpx.Response(200, json={
        "accountNo": "0001", "rtt": 88.2, "outstanding": 100e6, "accruedInterest": 2e6, "dueAmount": 0.0,
        "riskPolicy": {"initialMargin": 100, "maintenanceMargin": 85, "liquidationMargin": 80, "numDayMarginCall": 3},
        "riskStatus": {"code": "SAFE", "description": "Safe"}}))
    respx.get(f"{TCBS}/khaos/v1/loan/0001").mock(return_value=httpx.Response(200, json={"size": 100, "content": [
        {"id": 7, "status": "OPEN", "symbol": "FPT", "openingDate": "2026-01-08", "dueDate": "2026-12-28", "principal": 100e6,
         "remainingPrincipal": 100e6, "interest": 2e6, "rate": 13.5},
        {"id": 8, "status": "PAID", "symbol": "HPG", "openingDate": "2026-01-01", "dueDate": "2026-02-01", "principal": 5,
         "remainingPrincipal": 0, "interest": 0, "rate": 13.5}]}))
    respx.get(f"{TCBS}/nyx/v2/stock/bars-long-term").mock(return_value=httpx.Response(200, json={"ticker": "FPT", "data": [
        {"open": 1, "high": 2, "low": 1, "close": 2, "volume": 10, "tradingDate": "2026-10-14T00:00:00.000Z"},
        {"open": 2, "high": 3, "low": 2, "close": 3, "volume": 11, "tradingDate": "2026-10-15T00:00:00.000Z"}]}))
    respx.get(f"{TCBS}/tartarus/v1/tickerCommons").mock(return_value=httpx.Response(200, json={"data": [
        {"symbol": "FPT", "matchPrice": 0, "refPrice": 126000, "changePercent": 0}]}))

    ad = tcbs(tmp_path)
    await ad.authenticate("1")
    accs = await ad.list_accounts()
    assert [(a.id, a.kind) for a in accs] == [("0001", "margin")]          # tài khoản đã đóng bị bỏ
    pos = await ad.get_positions("0001")
    assert [(p.symbol, p.quantity) for p in pos] == [("FPT", 1000)]
    assert (pos[0].price, pos[0].avg_cost, pos[0].market_value) == (125000, 110000, 125_000_000)
    cash = await ad.get_cash("0001")
    assert cash.cash == 12_000_000
    b = (await ad.get_margin("0001", pos))[0]
    assert (b.ratio_pct, b.initial_pct, b.maintenance_pct, b.liquidation_pct, b.debt) == (88.2, 100.0, 85.0, 80.0, 102e6)
    assert b.ratio_kind == "collateral_over_debt"
    loans = await ad.get_loans("0001")
    assert len(loans) == 1                                    # khoản đã tất toán (PAID) bị bỏ
    assert (loans[0].symbol, loans[0].due_date.isoformat(), loans[0].annual_rate_pct) == ("FPT", "2026-12-28", 13.5)
    assert (loans[0].remaining_principal, loans[0].accrued_interest) == (100e6, 2e6)
    cs = await ad.get_candles("FPT", Interval.D1, 10)
    assert [c.t.date().isoformat() for c in cs] == ["2026-10-14", "2026-10-15"]
    q = (await ad.get_quotes(["FPT"]))["FPT"]
    assert q.price == 126000          # matchPrice = 0 trước giờ giao dịch -> dùng giá tham chiếu
    await ad.aclose()


# ---------------- DNSE ----------------

def test_dnse_signature_matches_documented_algorithm():
    date = "Fri, 16 Oct 2026 03:00:00 +0000"
    sig = build_signature("secret", "GET", "/accounts", date, "abc123")
    to_sign = "(request-target): get /accounts\ndate: Fri, 16 Oct 2026 03:00:00 +0000\nnonce: abc123"
    expected = quote(base64.b64encode(hmac.new(b"secret", to_sign.encode(), hashlib.sha256).digest()).decode(), safe="")
    assert sig == expected
    assert not any(ch in sig for ch in "+/=")   # chỉ còn dạng đã mã hoá %2B %2F %3D


@respx.mock
async def test_dnse_sends_signed_headers():
    route = respx.get(f"{DNSE}/accounts").mock(return_value=httpx.Response(200, json={"accounts": []}))
    ad = DnseAdapter(api_key="KEY", api_secret="SEC", base_url=DNSE, api_version="2026-07-23")
    await ad.list_accounts()
    h = route.calls[0].request.headers
    assert h["x-api-key"] == "KEY" and h["version"] == "2026-07-23" and h["date"]
    assert h["x-signature"].startswith('Signature keyId="KEY",algorithm="hmac-sha256",headers="(request-target) date",signature="')
    assert 'nonce="' in h["x-signature"]
    # nonce khác nhau mỗi request
    await ad.list_accounts()
    n = [c.request.headers["x-signature"].split('nonce="')[1] for c in route.calls]
    assert n[0] != n[1]
    await ad.aclose()


@respx.mock
async def test_dnse_margin_is_per_deal():
    respx.get(f"{DNSE}/accounts/A1/positions").mock(return_value=httpx.Response(200, json={"positions": [
        {"id": 11, "symbol": "FPT", "openQuantity": 1000, "costPrice": 100000, "marketPrice": 120000, "loanPackageId": 7},
        {"id": 12, "symbol": "HPG", "openQuantity": 2000, "costPrice": 28000, "marketPrice": 25000, "loanPackageId": 1},
        {"id": 13, "symbol": "VNM", "openQuantity": 0, "costPrice": 1, "marketPrice": 1}]}))
    respx.get(f"{DNSE}/accounts/A1/loans").mock(return_value=httpx.Response(200, json={"loans": [
        {"id": 1, "positionId": 11, "symbol": "FPT", "dueDate": "2026-11-20", "disbursementDate": "2026-10-01",
         "remainPrincipal": 60_000_000, "remainInterest": 1_000_000, "interestRate": 0.125, "principal": 60_000_000}]}))
    respx.get(f"{DNSE}/accounts/A1/loan-packages", params={"marketType": "STOCK", "symbol": "FPT"}).mock(
        return_value=httpx.Response(200, json={"loanPackages": [
            {"id": 7, "name": "Margin 50", "initialRate": 0.5, "maintenanceRate": 0.4, "liquidRate": 0.35, "interestRate": 0.125}]}))
    ad = DnseAdapter(api_key="k", api_secret="s", base_url=DNSE, api_version="v")
    pos = await ad.get_positions("A1")
    assert [p.symbol for p in pos] == ["FPT", "HPG"]
    buckets = await ad.get_margin("A1", pos)
    assert len(buckets) == 1                       # HPG không có nợ nên không có bucket
    b = buckets[0]
    assert b.scope == "deal" and b.symbols == ["FPT"]
    assert b.market_value == 120_000_000 and b.debt == 61_000_000
    assert b.ratio_pct == pytest.approx((120 - 61) / 120 * 100)
    assert (b.initial_pct, b.maintenance_pct, b.liquidation_pct) == (50.0, 40.0, 35.0)
    await ad.aclose()


@respx.mock
async def test_dnse_ohlc_mapping_and_cash():
    t0 = 1760400000
    respx.get(f"{DNSE}/price/ohlc").mock(return_value=httpx.Response(200, json={
        "t": [t0 + 86400, t0], "o": [2, 1], "h": [3, 2], "l": [1, 1], "c": [3, 2], "v": [10, 9]}))
    respx.get(f"{DNSE}/accounts/A1/balances").mock(return_value=httpx.Response(200, json={
        "stock": {"totalCash": 5_000_000, "availableCash": 4_000_000, "totalDebt": 7}}))
    ad = DnseAdapter(api_key="k", api_secret="s", base_url=DNSE, api_version="v")
    cs = await ad.get_candles("FPT", Interval.D1, 10)
    assert [c.close for c in cs] == [2000, 3000]               # sắp xếp theo thời gian; nghìn đồng -> đồng
    idx = await ad.get_candles("VNINDEX", Interval.D1, 10, is_index=True)
    assert [c.close for c in idx] == [2, 3]                    # chỉ số giữ nguyên điểm
    cash = await ad.get_cash("A1")
    assert cash.cash == 5_000_000 and cash.available_cash == 4_000_000
    await ad.aclose()


# ---------- cấu trúc phản hồi thật khác tài liệu: phải chịu được và báo lỗi rõ ----------

def _tcbs_authed(tmp_path):
    import json as _j
    (tmp_path / "tcbs_token.json").write_text(_j.dumps({"token": "t", "expires_at": "2099-01-01T00:00:00+07:00"}))
    return tcbs(tmp_path)


@pytest.mark.parametrize("payload", [
    {"accountNo": "0001", "rtt": 88.2, "riskPolicy": {"maintenanceMargin": 85}},                  # một đối tượng (thực tế)
    [{"accountNo": "0001", "rtt": 88.2, "riskPolicy": {"maintenanceMargin": 85}}],                # mảng (theo spec)
    {"data": [{"accountNo": "0001", "rtt": 88.2, "riskPolicy": {"maintenanceMargin": 85}}]},      # bọc trong data
])
@respx.mock
async def test_tcbs_risk_accepts_object_list_or_wrapped(tmp_path, payload):
    respx.get(f"{TCBS}/hydros/v1/account/0001/risk").mock(return_value=httpx.Response(200, json=payload))
    ad = _tcbs_authed(tmp_path)
    b = (await ad.get_margin("0001", []))[0]
    assert b.ratio_pct == 88.2 and b.maintenance_pct == 85.0
    await ad.aclose()


@respx.mock
async def test_tcbs_unexpected_shape_becomes_clear_broker_error(tmp_path):
    from app.brokers.base import BrokerError
    respx.get(f"{TCBS}/hydros/v1/account/0001/risk").mock(return_value=httpx.Response(200, json={"rtt": 1, "riskPolicy": "oops"}))
    respx.get(f"{TCBS}/aion/v1/accounts/0001/se").mock(return_value=httpx.Response(200, json={"stock": ["chuỗi", "không phải đối tượng"]}))
    ad = _tcbs_authed(tmp_path)
    for call in (ad.get_margin("0001", []), ad.get_positions("0001")):
        with pytest.raises(BrokerError) as ei:
            await call
        assert "không đúng cấu trúc" in ei.value.message
    await ad.aclose()


@respx.mock
async def test_tcbs_loans_fall_back_to_margin_info_with_lowercase_todate(tmp_path):
    respx.get(f"{TCBS}/khaos/v1/loan/0001").mock(return_value=httpx.Response(200, json={"content": []}))
    route = respx.get(f"{TCBS}/erebos/v2/digital/margin-info").mock(return_value=httpx.Response(200, json={"response": {"data": [
        {"releaseDate": "2026-10-01", "overDueDate": "2026-12-01", "releasedAmount": 5, "printAmount": 5, "remainingInterestFee": 1, "rate2": 13.5}]}}))
    ad = _tcbs_authed(tmp_path)
    loans = await ad.get_loans("0001")
    assert len(loans) == 1
    q = route.calls[0].request.url.params
    assert "todate" in q and "toDate" not in q     # server thật đòi 'todate' chữ thường
    await ad.aclose()


@respx.mock
async def test_tcbs_non_margin_account_403_does_not_log_out(tmp_path):
    """Thực tế: /risk và /khaos/loan trả 403 với tiểu khoản thường. Không được coi là hết phiên."""
    respx.get(f"{TCBS}/hydros/v1/account/0002/risk").mock(return_value=httpx.Response(403))
    respx.get(f"{TCBS}/khaos/v1/loan/0002").mock(return_value=httpx.Response(403))
    respx.get(f"{TCBS}/erebos/v2/digital/margin-info").mock(return_value=httpx.Response(403))
    ad = _tcbs_authed(tmp_path)
    assert await ad.get_margin("0002", []) == []
    assert await ad.get_loans("0002") == []
    assert ad.session_info().authenticated          # vẫn đăng nhập
    await ad.aclose()


@respx.mock
async def test_tcbs_skips_margin_calls_for_known_normal_accounts(tmp_path):
    respx.get(f"{TCBS}/aion/v1/customers/105C000001/accounts").mock(return_value=httpx.Response(200, json=[
        {"accountNo": "0001", "accountType": "margin", "accountStatus": "A"},
        {"accountNo": "0002", "accountType": "normal", "accountStatus": "A"}]))
    risk = respx.get(f"{TCBS}/hydros/v1/account/0002/risk").mock(return_value=httpx.Response(403))
    ad = _tcbs_authed(tmp_path)
    await ad.list_accounts()
    assert await ad.get_margin("0002", []) == [] and not risk.called
    await ad.aclose()


@respx.mock
async def test_tcbs_other_endpoints_403_still_means_session_expired(tmp_path):
    respx.get(f"{TCBS}/aion/v1/accounts/0001/se").mock(return_value=httpx.Response(403))
    ad = _tcbs_authed(tmp_path)
    with pytest.raises(AuthRequired):
        await ad.get_positions("0001")
    assert not ad.session_info().authenticated
    await ad.aclose()


@respx.mock
async def test_dnse_quote_uses_main_board_and_thousand_vnd():
    """Theo phản hồi thật: nhiều bảng (G1 lô chẵn, G4 lô lẻ, T1 thoả thuận), giá theo nghìn đồng."""
    respx.get(f"{DNSE}/price/HPG/trades/latest").mock(return_value=httpx.Response(200, json={"trades": [
        {"boardId": "G1", "symbol": "HPG", "matchPrice": 20.85, "time": "2026-10-19 13:25:47.996"},
        {"boardId": "G4", "symbol": "HPG", "matchPrice": 20.9, "time": "2026-10-19 13:26:00.000"},
        {"boardId": "T1", "symbol": "HPG", "matchPrice": 22.35, "time": "2026-10-19 13:29:56.036"}]}))
    ad = DnseAdapter(api_key="k", api_secret="s", base_url=DNSE, api_version="v")
    q = await ad.get_quotes(["HPG"])
    assert q["HPG"].price == pytest.approx(20_850)
    await ad.aclose()


def test_dnse_to_vnd():
    from app.brokers.dnse import to_vnd
    assert to_vnd(20.85) == pytest.approx(20_850) and to_vnd(28_000) == 28_000 and to_vnd(None) == 0

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models import Candle
from app.risk.rules import build_rules, deep_merge
from app.util import align_price_scale, parse_date, parse_dt, to_pct, VN_TZ


def test_to_pct_heuristic():
    assert to_pct(0.4) == 40 and to_pct(40) == 40 and to_pct(1) == 100 and to_pct(None) is None and to_pct("x") is None


def test_parse_dates():
    assert str(parse_date("16/10/2026")) == "2026-10-16"
    assert str(parse_date("2026-10-16")) == "2026-10-16"
    # 17:00Z ngày 15 là 00:00 ngày 16 giờ Việt Nam
    assert str(parse_date("2026-10-15T17:00:00.000Z")) == "2026-10-16"
    assert parse_dt(1760582400).tzinfo is not None
    assert parse_date("") is None and parse_date("không phải ngày") is None


def _c(close):
    from datetime import datetime
    return Candle(t=datetime(2026, 10, 16, tzinfo=VN_TZ), open=close, high=close, low=close, close=close)


def test_align_price_scale_both_directions():
    assert align_price_scale([_c(25.5)], 25500)[0].close == pytest.approx(25500)
    assert align_price_scale([_c(25500)], 25.5)[0].close == pytest.approx(25.5)
    assert align_price_scale([_c(25500)], 26000)[0].close == 25500       # cùng thang: giữ nguyên
    assert align_price_scale([], 1) == []


def test_rules_defaults_match_documented_values():
    r = build_rules()
    assert r.stop_loss.pct == 7 and r.risk_per_trade_pct == 1.5 and r.monthly_risk_budget_pct == 6
    assert [s.gain_pct for s in r.take_profit.ladder] == [7, 10, 15, 25]
    assert r.take_profit.trailing.atr_multiplier == 3 and r.entry.market_filter.slow_ma == 200


def test_rules_override_and_validation():
    assert build_rules({"stop_loss": {"pct": 6}}).stop_loss.pct == 6
    with pytest.raises(ValidationError):
        build_rules({"stop_loss": {"pct": 40}})
    with pytest.raises(ValidationError):
        build_rules({"take_profit": {"ladder": [{"gain_pct": 20, "sell_pct": 50}, {"gain_pct": 10, "sell_pct": 50}]}})
    with pytest.raises(ValidationError):
        build_rules({"take_profit": {"ladder": [{"gain_pct": 10, "sell_pct": 70}, {"gain_pct": 20, "sell_pct": 70}]}})


def test_deep_merge_replaces_lists_and_keeps_siblings():
    out = deep_merge({"a": {"x": 1, "y": 2}, "l": [1, 2]}, {"a": {"x": 9}, "l": [3]})
    assert out == {"a": {"x": 9, "y": 2}, "l": [3]}


def test_vietnamese_number_helpers():
    from app.util import vg, vn
    assert vn(1234.5, 1) == "1.234,5" and vn(0.039, 3) == "0,039" and vn(None) == "—"
    assert vn(-4.1, 1) == "−4,1" and vn(5.2, 1, sign=True) == "+5,2" and vn(-0.001, 1) == "0,0"
    assert vg(7) == "7" and vg(6.5) == "6,5" and vg(0.1) == "0,1" and vg(2.25) == "2,25"

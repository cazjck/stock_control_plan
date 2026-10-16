"""Kế hoạch theo kỹ thuật (mục 6d): giai đoạn Weinstein, vùng hội tụ, khối lượng bán theo vùng, xác nhận đáy."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.models import MarketInfo, MarketState, TechZone
from app.risk.deleverage import ratio_for
from app.risk.indicators import compute_series
from app.risk.rotation import build_rotation
from app.risk.technical import MarginCtx, build_tech_plan, follow_through, size_zones, stage_of, zones

from .conftest import make_candles, make_df
from app.risk.indicators import to_frame


def series(closes, **kw):
    return compute_series(make_df(closes, **kw))


def test_weinstein_stages(rules):
    up = list(np.linspace(50, 120, 220))
    down = list(np.linspace(120, 50, 220))
    base = list(np.linspace(120, 60, 120)) + [60 + (i % 6) * 0.3 for i in range(200)]
    assert stage_of(series(up), rules)[0] == 2
    assert stage_of(series(down), rules)[0] == 4
    st, label, _ = stage_of(series(base), rules)
    assert st == 1 and "tạo nền" in label
    assert stage_of(series(up[:100]), rules)[0] is None


def test_zones_merge_tools_and_split_above_below(rules):
    closes = list(np.linspace(100, 60, 120)) + list(np.linspace(60, 70, 15)) + [68] * 5
    s = series(closes)
    above, below = zones(s, 68, rules)
    assert above and all(z.low > 68 for z in above)
    assert below and all(z.high < 68 for z in below)
    assert [z.price for z in above] == sorted(z.price for z in above)        # gần trước
    assert [z.price for z in below] == sorted((z.price for z in below), reverse=True)
    fib = [z for z in above if any(t.startswith("Fibonacci") for t in z.tools)]
    assert fib and all(1 <= z.strength <= len(z.tools) for z in above)


def Z(p, strength=2):
    return TechZone(price=p, low=p, high=p, kind="resistance", tools=["SMA20", "Fibonacci 38,2%"][:strength],
                    strength=strength, distance_pct=0)


def test_size_zones_ten_percent_each_capped(rules):
    out = size_zones([Z(105), Z(110, 1), Z(115), Z(120), Z(125)], 10_000, 100, rules, None)
    assert [z.price for z in out] == [105, 115, 120]                       # bỏ vùng chỉ có 1 công cụ, tối đa 3 vùng
    assert [z.sell_qty for z in out] == [1_000, 1_000, 1_000] and out[-1].cum_pct == 30


def test_first_zone_sized_to_make_margin_safe(rules):
    m = MarginCtx(kind="equity_over_value", ratio_pct=37.5, value=650e6, debt=402e6, target=45, safe=False)
    out = size_zones([Z(10_300), Z(11_200)], 64_000, 10_150, rules, m)
    k = 1 - rules.margin.sell_cost_pct / 100
    z = out[0]
    v = 650e6 * 10_300 / 10_150
    assert z.margin_sized and z.ratio_after >= 45
    less = z.sell_qty - 100
    assert ratio_for("equity_over_value", None, 0, 0, v - less * 10_300, 402e6 - less * 10_300 * k) < 45
    assert out[-1].cum_pct <= rules.technical.margin_max_total_pct


def _index(closes, volumes):
    cs = make_candles(closes)
    for c, v in zip(cs, volumes):
        c.volume = v
    return to_frame(cs)


def test_follow_through_day(rules):
    closes = list(np.linspace(1300, 1200, 30)) + [1190, 1195, 1198, 1200, 1218, 1220]
    vols = [100] * 35 + [150]
    vols[-2] = 160                       # phiên +1,5% (ngày thứ 5 của nhịp hồi) khối lượng cao hơn phiên trước
    vols[-3] = 90
    ok = follow_through(_index(closes, vols), rules)
    assert ok.met and "tăng 1,5" in ok.detail
    weak = follow_through(_index(closes[:-2] + [1205, 1208], vols), rules)
    assert not weak.met


def test_plan_stage2_has_no_sell_zones_and_rotation_respects_stage(rules):
    up = list(np.linspace(50, 120, 220))
    s = series(up)
    p = build_tech_plan(s, 120, 10_000, 100, rules)
    assert p.stage == 2 and p.sell_zones == [] and p.scenarios[0].title == "Nếu tiếp tục tăng"


def test_rotation_uses_technical_zone_prices(rules):
    closes = flat = [100.0] * 20 + list(np.linspace(100, 60, 40)) + [62, 64, 65]
    s = series(closes)
    rot = build_rotation(s=s, price=65, qty=10_000, cost=100, mode="swing", thesis=None,
                         market=MarketInfo(state=MarketState.NORMAL), margin_ok=True, trades=[], rules=rules,
                         today=s["date"].iloc[-1], zones=[(64.5, 1_000), (70, 1_000)])
    assert rot.tier_prices == [64.5, 70] and rot.tier_qtys == [1_000, 1_000]
    assert rot.level == "sell" and rot.sell_qty == 1_000
    no = build_rotation(s=s, price=65, qty=10_000, cost=100, mode="swing", thesis=None,
                        market=MarketInfo(state=MarketState.NORMAL), margin_ok=True, trades=[], rules=rules,
                        today=s["date"].iloc[-1], zones=[(64.5, 1_000)], stage=2)
    assert no.phase == "trend_change" and no.sell_qty == 0


def test_bottom_label_and_invalidation(rules):
    closes = list(np.linspace(100, 60, 120)) + list(np.linspace(60, 66, 15))
    p = build_tech_plan(series(closes), 66, 10_000, 100, rules)
    assert 0 <= p.bottom_score <= 6 and len(p.bottom_checks) == 6
    assert p.bottom_label in ("Chưa có bằng chứng đáy", "Đáy đang hình thành", "Đáy được xác nhận")
    assert p.invalidation < 66 and [x.name for x in p.scenarios] == ["rebound", "sideways", "decline"]

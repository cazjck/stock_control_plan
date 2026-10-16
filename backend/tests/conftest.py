from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from app.models import Candle, Position
from app.risk.indicators import to_frame
from app.risk.rules import build_rules
from app.util import VN_TZ


@pytest.fixture
def rules():
    return build_rules()


def make_candles(closes, *, spread=0.01, volume=1_000_000, end=None) -> list[Candle]:
    """Nến tổng hợp: high/low cách close ± spread, ngày giao dịch liên tiếp (bỏ qua cuối tuần)."""
    end = end or datetime.now(VN_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    days, d = [], end
    while len(days) < len(closes):
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    days.reverse()
    out, prev = [], closes[0]
    for t, c in zip(days, closes):
        out.append(Candle(t=t, open=prev, high=max(prev, c) * (1 + spread), low=min(prev, c) * (1 - spread),
                          close=c, volume=volume))
        prev = c
    return out


def make_df(closes, **kw) -> pd.DataFrame:
    return to_frame(make_candles(closes, **kw))


def make_position(symbol="AAA", qty=1000, cost=100.0, price=100.0) -> Position:
    return Position(broker="t", account_id="a", symbol=symbol, quantity=qty, avg_cost=cost, price=price,
                    market_value=qty * price)


def flat(n=60, level=100.0, wobble=0.0, seed=1):
    rng = np.random.default_rng(seed)
    return list(level * (1 + rng.normal(0, wobble, n)))

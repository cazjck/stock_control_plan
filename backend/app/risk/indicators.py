"""Chỉ báo kỹ thuật bằng TA-Lib trên DataFrame nến."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import talib

from ..models import Candle, Indicators


def to_frame(candles: list[Candle]) -> pd.DataFrame:
    df = pd.DataFrame([c.model_dump() for c in candles])
    if df.empty:
        return pd.DataFrame(columns=["t", "date", "open", "high", "low", "close", "volume"])
    df["date"] = df["t"].map(lambda x: x.date())
    return df.sort_values("t").reset_index(drop=True)


def _f(x) -> float | None:
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else float(x)


def compute_series(df: pd.DataFrame, atr_period: int = 14, trail_atr_period: int = 22) -> pd.DataFrame:
    """Trả về bản sao df với các cột chỉ báo. Yêu cầu >= 2 nến; cột thiếu dữ liệu là NaN."""
    out = df.copy()
    c = out["close"].to_numpy(dtype="float64")
    h = out["high"].to_numpy(dtype="float64")
    l = out["low"].to_numpy(dtype="float64")
    v = out["volume"].to_numpy(dtype="float64")
    n = len(out)
    nan = np.full(n, np.nan)

    def safe(fn, *args, **kw):
        try:
            return fn(*args, **kw)
        except Exception:  # noqa: BLE001 - quá ít dữ liệu cho chu kỳ yêu cầu
            return nan

    out["sma20"] = safe(talib.SMA, c, 20)
    out["sma50"] = safe(talib.SMA, c, 50)
    out["sma200"] = safe(talib.SMA, c, 200)
    out["ema20"] = safe(talib.EMA, c, 20)
    out["ema21"] = safe(talib.EMA, c, 21)  # IBD: thủng EMA21 với khối lượng lớn là tín hiệu bán giữ lãi
    out["rsi14"] = safe(talib.RSI, c, 14)
    out["atr14"] = safe(talib.ATR, h, l, c, atr_period)
    out["atr22"] = safe(talib.ATR, h, l, c, trail_atr_period)
    macd = safe(talib.MACD, c, 12, 26, 9)
    if isinstance(macd, tuple):
        out["macd"], out["macd_signal"], out["macd_hist"] = macd
    else:
        out["macd"] = out["macd_signal"] = out["macd_hist"] = nan
    out["vol_ma20"] = safe(talib.SMA, v, 20)
    return out


def last_indicators(s: pd.DataFrame) -> Indicators:
    if s.empty:
        return Indicators()
    r = s.iloc[-1]
    close = _f(r["close"])
    sma20 = _f(r.get("sma20"))
    atr14 = _f(r.get("atr14"))
    vol_ma = _f(r.get("vol_ma20"))
    tail = s.tail(20)
    return Indicators(
        close=close, sma20=sma20, sma50=_f(r.get("sma50")), ema20=_f(r.get("ema20")),
        rsi14=_f(r.get("rsi14")), atr14=atr14,
        atr14_pct=(atr14 / close * 100) if atr14 and close else None,
        atr22=_f(r.get("atr22")), macd=_f(r.get("macd")), macd_signal=_f(r.get("macd_signal")),
        macd_hist=_f(r.get("macd_hist")), high20=_f(tail["high"].max()), low20=_f(tail["low"].min()),
        volume_ratio=(float(r["volume"]) / vol_ma) if vol_ma else None,
        close_vs_sma20_pct=((close / sma20 - 1) * 100) if close and sma20 else None,
    )

"""Hàm tiện ích: chuẩn hoá đơn vị, ngày giờ, thang giá."""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .models import Candle

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def now_vn() -> datetime:
    return datetime.now(VN_TZ)


def to_pct(x: Any) -> float | None:
    """Chuẩn hoá tỷ lệ về đơn vị %. Giá trị |x| <= 1.5 được coi là phân số (0.4 -> 40).

    Đây là heuristic vì tài liệu broker không nêu rõ đơn vị. Kiểm tra lại với dữ liệu thật
    ở lần chạy đầu tiên (trường `raw` trong MarginBucket giữ nguyên giá trị gốc)."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v * 100 if abs(v) <= 1.5 else v


def to_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


_DMY = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})")


def parse_dt(value: Any) -> datetime | None:
    """Đọc ngày giờ từ ISO, epoch giây/mili giây, hoặc DD/MM/YYYY. Trả về giờ Việt Nam."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(VN_TZ)
    s = str(value).strip()
    m = _DMY.match(s)
    if m:
        d, mo, y = (int(g) for g in m.groups())
        return datetime(y, mo, d, tzinfo=VN_TZ)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=VN_TZ)
    return dt.astimezone(VN_TZ)


def parse_date(value: Any) -> date | None:
    dt = parse_dt(value)
    return dt.date() if dt else None


def align_price_scale(candles: list[Candle], reference_price: float | None) -> list[Candle]:
    """Một số API trả giá theo nghìn đồng, số khác theo đồng. Nếu giá tham chiếu và giá đóng
    cửa nến lệch nhau ~1000 lần thì đưa nến về cùng thang với giá tham chiếu."""
    if not candles or not reference_price or reference_price <= 0:
        return candles
    last = candles[-1].close
    if last <= 0:
        return candles
    ratio = reference_price / last
    if 800 <= ratio <= 1250:
        k = 1000.0
    elif 1 / 1250 <= ratio <= 1 / 800:
        k = 0.001
    else:
        return candles
    return [
        c.model_copy(update=dict(open=c.open * k, high=c.high * k, low=c.low * k, close=c.close * k))
        for c in candles
    ]


def mask_secret(s: str | None) -> str:
    if not s:
        return ""
    return s[:3] + "…" + s[-2:] if len(s) > 8 else "•••"


def vn(x: float | None, digits: int = 1, *, sign: bool = False) -> str:
    """Số kiểu Việt Nam: dấu chấm ngăn nghìn, dấu phẩy thập phân, dấu trừ thật. vn(1234.5, 1) -> '1.234,5'."""
    if x is None:
        return "—"
    s = f"{abs(x):,.{digits}f}".replace(",", "\0").replace(".", ",").replace("\0", ".")
    if x < 0 and float(f"{abs(x):.{digits}f}") != 0:
        return "\u2212" + s
    return ("+" + s) if sign and x > 0 else s


def vg(x: float) -> str:
    """Như định dạng %g nhưng dùng dấu phẩy: 7 -> '7', 6.5 -> '6,5'."""
    return str(int(x)) if float(x).is_integer() else vn(x, 2).rstrip("0").rstrip(",")

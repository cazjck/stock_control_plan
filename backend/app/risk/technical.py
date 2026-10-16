"""Kế hoạch theo kỹ thuật (mục 6d của docs/trading-rules.md).

- Giai đoạn xu hướng theo đường 30 tuần (Stan Weinstein), quy ra 150 phiên ngày.
- Vùng cản và vùng đỡ: hội tụ của SMA20/50/200 (Granville), Fibonacci đoạn giảm gần nhất, đỉnh đáy cục bộ (Dow, Murphy),
  vùng giá khớp nhiều nhất (Market Profile, Steidlmayer), dải Bollinger.
- Sáu dấu hiệu xác nhận đáy, gồm ngày bùng nổ của thị trường chung (O'Neil).
- Khối lượng bán ở mỗi vùng cản: 10% mỗi vùng; vùng đầu nâng lên vừa đủ đưa tài khoản margin về vùng an toàn.
Hàm thuần tuý, không gọi mạng. Chỉ khuyến nghị."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from ..models import TechCheck, TechPlan, TechScenario, TechZone
from ..util import vg, vn
from .deleverage import ratio_for
from .rules import Rules
from .take_profit import lot


def _ok(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def _fmt(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


def _d(x) -> str:
    return f"{x:%d/%m}" if hasattr(x, "strftime") else str(x)


# ---------------- giai đoạn (Weinstein) ----------------

def stage_of(s: pd.DataFrame, rules: Rules) -> tuple[int | None, str, str]:
    r = rules.technical
    c = s["close"].astype(float)
    if len(c) < r.stage_ma + r.stage_slope_sessions:
        return None, "Chưa đủ dữ liệu", f"Cần {r.stage_ma + r.stage_slope_sessions} phiên để tính đường 30 tuần"
    ma = c.rolling(r.stage_ma).mean()
    now, before = float(ma.iloc[-1]), float(ma.iloc[-1 - r.stage_slope_sessions])
    slope = (now / before - 1) * 100
    prior = float(ma.iloc[-1 - 3 * r.stage_slope_sessions]) if len(ma.dropna()) > 3 * r.stage_slope_sessions else before
    prior_slope = (before / prior - 1) * 100
    price = float(c.iloc[-1])
    where = f"giá {_fmt(price)} {'trên' if price > now else 'dưới'} đường 30 tuần {_fmt(now)}, đường dốc {vn(slope, 1, sign=True)}% trong {r.stage_slope_sessions} phiên"
    if abs(slope) <= r.stage_flat_pct:
        if prior_slope < 0:
            return 1, "Giai đoạn 1: tạo nền", where + ". Đường đã đi ngang sau một đoạn giảm: thị trường đang tìm đáy, chưa xác nhận tăng."
        return 3, "Giai đoạn 3: tạo đỉnh", where + ". Đường đi ngang sau một đoạn tăng: lực mua đang yếu đi."
    if slope > 0 and price > now:
        return 2, "Giai đoạn 2: đang tăng", where + ". Xu hướng tăng: ngừng bán đảo hàng, giữ theo luật chốt lời."
    if slope < 0 and price < now:
        return 4, "Giai đoạn 4: đang giảm", where + ". Xu hướng giảm: nhịp hồi là để bán bớt, không mua thêm."
    if slope < 0:
        return 4, "Giai đoạn 4: đang giảm (giá vừa vượt đường)", where + ". Giá vượt đường nhưng đường vẫn dốc xuống: chưa đổi xu hướng."
    return 2, "Giai đoạn 2: mới chớm", where + ". Đường đã dốc lên nhưng giá dưới đường: theo dõi."


# ---------------- vùng giá ----------------

@dataclass
class _Lvl:
    price: float
    family: str
    label: str


def _pivots(arr: np.ndarray, k: int, kind: str) -> list[int]:
    out = []
    for i in range(k, len(arr) - k):
        w = arr[i - k:i + k + 1]
        if (kind == "high" and arr[i] == w.max()) or (kind == "low" and arr[i] == w.min()):
            out.append(i)
    return out


def raw_levels(s: pd.DataFrame, rules: Rules) -> list[_Lvl]:
    r = rules.technical
    w = s.tail(r.lookback).reset_index(drop=True)
    h, l, c, v = (w[k].astype(float).to_numpy() for k in ("high", "low", "close", "volume"))
    out: list[_Lvl] = []
    last = s.iloc[-1]
    for col, fam in (("sma20", "SMA20"), ("sma50", "SMA50"), ("sma200", "SMA200")):
        if col in s and _ok(float(last[col])):
            out.append(_Lvl(float(last[col]), fam, fam))
    # Fibonacci của đoạn giảm gần nhất: đáy 60 phiên, đỉnh trong lookback trước đáy
    tail = min(60, len(w))
    i_low = len(w) - tail + int(np.argmin(l[-tail:]))
    if i_low > 0:
        i_high = int(np.argmax(h[:i_low + 1]))
        hi, lo = h[i_high], l[i_low]
        if hi > lo * 1.05:
            for f in (0.382, 0.5, 0.618):
                out.append(_Lvl(lo + f * (hi - lo), "Fibonacci", f"Fibonacci {vn(f * 100, 1 if f != 0.5 else 0)}%"))
    # đỉnh đáy cục bộ
    k = r.pivot_bars
    dates = list(w["date"])
    for i in _pivots(h, k, "high"):
        out.append(_Lvl(float(h[i]), "Đỉnh đáy cũ", f"Đỉnh {_d(dates[i])}"))
    for i in _pivots(l, k, "low"):
        out.append(_Lvl(float(l[i]), "Đỉnh đáy cũ", f"Đáy {_d(dates[i])}"))
    # vùng giá khớp nhiều nhất
    tp = (h + l + c) / 3
    if v.sum() > 0 and tp.max() > tp.min():
        bins = np.linspace(tp.min(), tp.max(), 25)
        idx = np.clip(np.digitize(tp, bins) - 1, 0, 23)
        vol = np.bincount(idx, weights=v, minlength=24)
        b = int(np.argmax(vol))
        out.append(_Lvl(float((bins[b] + bins[b + 1]) / 2), "Khớp nhiều nhất", "Vùng giá khớp nhiều nhất 120 phiên"))
    # Bollinger
    if len(c) >= 20:
        m, sd = c[-20:].mean(), c[-20:].std(ddof=0)
        out.append(_Lvl(float(m + 2 * sd), "Bollinger", "Bollinger trên"))
        out.append(_Lvl(float(m - 2 * sd), "Bollinger", "Bollinger dưới"))
    return out


def zones(s: pd.DataFrame, price: float, rules: Rules) -> tuple[list[TechZone], list[TechZone]]:
    r = rules.technical
    atr = float(s["atr14"].iloc[-1]) if "atr14" in s and _ok(float(s["atr14"].iloc[-1])) else price * 0.03
    gap = r.merge_atr * atr
    lv = sorted((x for x in raw_levels(s, rules) if x.price > 0), key=lambda x: x.price)
    groups: list[list[_Lvl]] = []
    for x in lv:
        if groups and x.price - groups[-1][0].price <= gap:
            groups[-1].append(x)
        else:
            groups.append([x])
    above: list[TechZone] = []
    below: list[TechZone] = []
    for g in groups:
        p = float(np.mean([x.price for x in g]))
        fams = sorted({x.family for x in g})
        labels = list(dict.fromkeys(x.label for x in g))
        z = dict(price=p, low=min(x.price for x in g), high=max(x.price for x in g), tools=labels,
                 strength=len(fams), distance_pct=(p / price - 1) * 100)
        if z["low"] > price * 1.003 and z["distance_pct"] <= r.max_zone_distance_pct:
            above.append(TechZone(kind="resistance", **z))
        elif z["high"] < price * 0.997:
            below.append(TechZone(kind="support", **z))
    below.reverse()                     # gần giá nhất trước
    return above, below


# ---------------- xác nhận đáy ----------------

def follow_through(idx: pd.DataFrame | None, rules: Rules) -> TechCheck:
    r = rules.technical
    label = f"Thị trường có ngày bùng nổ xác nhận (O'Neil): từ phiên thứ 4 của nhịp hồi, VN-Index tăng từ {vg(r.ftd_min_gain_pct)}%"
    if idx is None or len(idx) < r.ftd_window + 2:
        return TechCheck(code="ftd", label=label, met=False, detail="chưa đủ dữ liệu chỉ số")
    w = idx.tail(r.ftd_window).reset_index(drop=True)
    c, lo, v = (w[k].astype(float).to_numpy() for k in ("close", "low", "volume"))
    i_low = int(np.argmin(lo))
    up = [j for j in range(max(1, i_low), len(w)) if c[j] > c[j - 1]]
    if not up:
        return TechCheck(code="ftd", label=label, met=False, detail=f"chưa có nhịp hồi từ đáy {_d(w['date'][i_low])}")
    day1 = up[0]
    has_vol = v.sum() > 0
    for j in range(day1 + 3, len(w)):
        gain = (c[j] / c[j - 1] - 1) * 100
        if gain >= r.ftd_min_gain_pct and (not has_vol or v[j] > v[j - 1]):
            return TechCheck(code="ftd", label=label, met=True,
                             detail=f"phiên {_d(w['date'][j])} tăng {vn(gain, 2)}%" + ("" if has_vol else " (chỉ số không có khối lượng)"))
    return TechCheck(code="ftd", label=label, met=False,
                     detail=f"nhịp hồi từ đáy {_d(w['date'][i_low])} được {len(w) - 1 - day1 + 1} phiên, chưa có phiên bùng nổ")


def bottom_checks(s: pd.DataFrame, rules: Rules, ftd: TechCheck | None) -> list[TechCheck]:
    r = rules.technical
    w = s.tail(r.lookback).reset_index(drop=True)
    l, c, v = (w[k].astype(float).to_numpy() for k in ("low", "close", "volume"))
    rsi = w["rsi14"].astype(float).to_numpy() if "rsi14" in w else np.full(len(w), np.nan)
    out: list[TechCheck] = []
    piv = _pivots(l, r.pivot_bars, "low")
    if len(piv) >= 2:
        a, b = piv[-2], piv[-1]
        met = l[b] > l[a] and c[-1] > l[b]
        out.append(TechCheck(code="higher_low", label="Đáy sau cao hơn đáy trước (Dow)", met=met,
                             detail=f"đáy {_d(w['date'][a])} {_fmt(l[a])}, đáy {_d(w['date'][b])} {_fmt(l[b])}"))
    else:
        out.append(TechCheck(code="higher_low", label="Đáy sau cao hơn đáy trước (Dow)", met=False, detail="chưa có hai đáy cục bộ"))
    sma20 = w["sma20"].astype(float).to_numpy() if "sma20" in w else np.full(len(w), np.nan)
    up20 = len(sma20) > 6 and _ok(sma20[-1]) and _ok(sma20[-6]) and sma20[-1] > sma20[-6]
    out.append(TechCheck(code="above_sma20", label="Đóng cửa trên SMA20 và SMA20 đã quay lên (Granville)",
                         met=bool(_ok(sma20[-1]) and c[-1] > sma20[-1] and up20),
                         detail=f"đóng cửa {_fmt(c[-1])}, SMA20 {_fmt(sma20[-1]) if _ok(sma20[-1]) else '—'}"
                                + (f", {'đang lên' if up20 else 'chưa lên'}" if _ok(sma20[-1]) else "")))
    out.append(TechCheck(code="rsi50", label="RSI14 trên 50: chuyển sang vùng của xu hướng tăng (Cardwell, Brown)",
                         met=bool(_ok(rsi[-1]) and rsi[-1] > 50), detail=f"RSI14 {vn(rsi[-1], 0) if _ok(rsi[-1]) else '—'}"))
    div, ddet = False, "không có"
    if len(piv) >= 2 and _ok(rsi[piv[-1]]) and _ok(rsi[piv[-2]]):
        a, b = piv[-2], piv[-1]
        if l[b] < l[a] and rsi[b] > rsi[a]:
            div, ddet = True, f"giá đáy thấp hơn ({_fmt(l[b])} < {_fmt(l[a])}) nhưng RSI cao hơn ({vn(rsi[b], 0)} > {vn(rsi[a], 0)})"
    hist = float(s["macd_hist"].iloc[-1]) if "macd_hist" in s and _ok(float(s["macd_hist"].iloc[-1])) else None
    if not div and hist is not None and hist > 0:
        div, ddet = True, f"histogram MACD dương ({vn(hist, 2)})"
    out.append(TechCheck(code="divergence", label="Phân kỳ dương RSI hoặc histogram MACD đã dương", met=div, detail=ddet))
    ch = np.diff(c[-21:]) if len(c) >= 21 else np.array([])
    vv = v[-20:] if len(v) >= 20 else np.array([])
    if len(ch) == len(vv) and len(vv):
        upv, dnv = float(vv[ch > 0].sum()), float(vv[ch < 0].sum())
        out.append(TechCheck(code="accumulation", label="Tích luỹ: 20 phiên, khối lượng phiên tăng lớn hơn phiên giảm",
                             met=upv > dnv, detail=f"phiên tăng {vn(upv / 1e6, 1)} triệu cp, phiên giảm {vn(dnv / 1e6, 1)} triệu cp"))
    else:
        out.append(TechCheck(code="accumulation", label="Tích luỹ: 20 phiên, khối lượng phiên tăng lớn hơn phiên giảm",
                             met=False, detail="chưa đủ dữ liệu"))
    out.append(ftd or TechCheck(code="ftd", label="Thị trường có ngày bùng nổ xác nhận (O'Neil)", met=False, detail="chưa có dữ liệu chỉ số"))
    return out


# ---------------- khối lượng bán theo vùng ----------------

@dataclass
class MarginCtx:
    kind: str
    ratio_pct: float
    value: float          # giá trị cổ phiếu cả tài khoản
    debt: float
    target: float
    safe: bool


def size_zones(res: list[TechZone], qty: int, price: float, rules: Rules, margin: MarginCtx | None) -> list[TechZone]:
    r = rules.technical
    k = 1 - rules.margin.sell_cost_pct / 100
    strong = [z for z in res if z.strength >= r.min_strength][: r.max_zones]
    if not strong or qty <= 0:
        return []
    out: list[TechZone] = []
    cum_pct, cum_qty = 0.0, 0
    cap = r.max_total_pct
    for i, z in enumerate(strong):
        pct = r.sell_pct_per_zone
        sized = False
        if i == 0 and margin and not margin.safe and margin.debt > 0:
            scale = z.price / price
            v1 = margin.value * scale
            best = None
            for q in range(100, qty + 1, 100):
                ra = ratio_for(margin.kind, margin.ratio_pct, margin.value, margin.debt, v1 - q * z.price,
                               margin.debt - q * z.price * k)
                if ra is None or ra >= margin.target:
                    best = q
                    break
            if best is not None and best / qty * 100 > pct:
                pct, sized = min(best / qty * 100, r.margin_max_total_pct), True
            cap = r.margin_max_total_pct if sized else cap
        new_cum = min(cum_pct + pct, cap)
        if new_cum <= cum_pct:
            break
        target_qty = lot(qty * new_cum / 100, qty) if not sized else min(qty, int(math.ceil(qty * new_cum / 100 / 100)) * 100)
        q = max(0, target_qty - cum_qty)
        if q == 0:
            break
        cum_qty += q
        cum_pct = new_cum
        ra = None
        if margin and margin.debt > 0:
            scale = z.price / price
            ra = ratio_for(margin.kind, margin.ratio_pct, margin.value, margin.debt,
                           margin.value * scale - cum_qty * z.price, margin.debt - sum(
                               x.sell_qty * x.price for x in out) * k - q * z.price * k)
        out.append(z.model_copy(update=dict(sell_pct=new_cum - (out[-1].cum_pct if out else 0), sell_qty=q,
                                            cum_pct=new_cum, ratio_after=ra, margin_sized=sized)))
    return out


# ---------------- kế hoạch ----------------

def build_tech_plan(s: pd.DataFrame, price: float, qty: int, cost: float, rules: Rules, *,
                    ftd: TechCheck | None = None, margin: MarginCtx | None = None,
                    review_on: date | None = None) -> TechPlan | None:
    if s is None or len(s) < 30 or qty <= 0:
        return None
    r = rules.technical
    st, st_label, st_detail = stage_of(s, rules)
    res, sup = zones(s, price, rules)
    sells = size_zones(res, qty, price, rules, margin) if st != 2 else []
    checks = bottom_checks(s, rules, ftd)
    score = sum(1 for x in checks if x.met)
    blabel = ("Chưa có bằng chứng đáy" if score <= 2 else "Đáy đang hình thành" if score <= 4 else "Đáy được xác nhận")
    atr = float(s["atr14"].iloc[-1]) if "atr14" in s and _ok(float(s["atr14"].iloc[-1])) else price * 0.03
    strong_sup = next((z for z in sup if z.strength >= r.min_strength), None)
    if strong_sup:
        inval = strong_sup.low - r.invalidation_atr * atr
        basis = f"vùng đỡ {_fmt(strong_sup.low)}–{_fmt(strong_sup.high)} ({', '.join(strong_sup.tools[:3])}) trừ {vg(r.invalidation_atr)}×ATR14"
    else:
        lo = float(s["low"].astype(float).tail(60).min())
        inval = lo - r.invalidation_atr * atr
        basis = f"đáy 60 phiên {_fmt(lo)} trừ {vg(r.invalidation_atr)}×ATR14"

    # kịch bản
    if st == 2:
        reb = TechScenario(name="rebound", title="Nếu tiếp tục tăng", trigger="Giá giữ trên đường 30 tuần đang dốc lên",
                           action="Giai đoạn 2: không bán đảo hàng. Giữ và để luật chốt lời, trailing stop làm việc.")
    elif sells:
        steps = "; ".join(f"tới {_fmt(z.low)}–{_fmt(z.high)} bán {_fmt(z.sell_qty)} cp" + (
            f" (tỷ lệ ký quỹ còn {vn(z.ratio_after, 1)}%)" if z.ratio_after is not None else "")
            for z in sells)
        extra = " Vùng đầu đã nâng khối lượng để tài khoản về vùng an toàn." if sells[0].margin_sized else ""
        reb = TechScenario(name="rebound", title="Nếu hồi", trigger=f"Giá lên vùng cản đầu tiên {_fmt(sells[0].low)}–{_fmt(sells[0].high)} "
                           f"({', '.join(sells[0].tools[:3])}), còn {vn(sells[0].distance_pct, 1)}%",
                           action=f"Bán từng phần ở các vùng cản: {steps}. Tiền bán trả nợ margin trước.{extra} "
                                  "Nếu giá đóng cửa vượt hẳn vùng cản cuối và đường 30 tuần quay lên thì ngừng bán.")
    else:
        reb = TechScenario(name="rebound", title="Nếu hồi", trigger="Chưa có vùng cản nào đủ mạnh trong 40% phía trên",
                           action="Dùng các mốc phần trăm của mục 6b.")
    side = TechScenario(name="sideways", title="Nếu đi ngang", trigger="Giá dao động giữa vùng đỡ và vùng cản gần nhất",
                        action=(f"Xem lại vào {review_on:%d/%m}" if review_on else "Xem lại sau 20 phiên")
                               + ". Tiền lãi margin vẫn chạy mỗi ngày; đi ngang lâu là lý do để giảm nợ dần.")
    dec = TechScenario(name="decline", title="Nếu giảm", trigger=f"Giá đóng cửa dưới {_fmt(inval)} ({basis})",
                       action="Giả định đáy đã sai. Làm theo kế hoạch hạ margin, không bình quân giá xuống.")
    nxt = f"vùng cản đầu tiên {_fmt(sells[0].low)}–{_fmt(sells[0].high)}" if sells else (
        f"vùng cản {_fmt(res[0].low)}–{_fmt(res[0].high)}" if res else "chưa có vùng cản rõ")
    summary = (f"{st_label}. {blabel} ({score}/6 dấu hiệu). Phía trên: {nxt}. "
               f"Phía dưới: mức vô hiệu {_fmt(inval)} (cách {vn((inval / price - 1) * 100, 1)}%).")
    return TechPlan(stage=st, stage_label=st_label, stage_detail=st_detail, resistance=res[:6], support=sup[:4],
                    sell_zones=sells, invalidation=inval, invalidation_basis=basis, bottom_checks=checks,
                    bottom_score=score, bottom_label=blabel, scenarios=[reb, side, dec], summary=summary)

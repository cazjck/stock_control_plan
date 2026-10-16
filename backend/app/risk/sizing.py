"""Máy tính khối lượng mua theo luật (mục 1 và 2.1 của docs/trading-rules.md).

    risk_money    = capital × risk_per_trade
    stop_distance = giá vào − giá cắt lỗ
    qty_plan      = floor(risk_money / stop_distance, lô 100), không quá capital × max_weight / giá

capital là tiền mặt thực có, không tính margin. Hàm thuần tuý, chỉ ĐỀ XUẤT con số: không có đường nào dẫn tới đặt lệnh.
"""
from __future__ import annotations

import math

from ..models import (
    MarketInfo, MarketState, PositionEval, SizingPlan, SizingTranche, SizingWarning,
)
from ..util import vg, vn
from .rules import Rules

LOT = 100


def _floor_lot(qty: float) -> int:
    return int(math.floor(qty / LOT + 1e-9)) * LOT


def initial_stop(price: float, atr14: float | None, rules: Rules, market: MarketInfo) -> tuple[float, str]:
    """Mức cắt lỗ ban đầu cho vị thế mới (mục 3.1): lấy mức GẦN giá hơn giữa −7% và 2×ATR14.
    Thị trường yếu thì dùng ngưỡng siết (5%), giống risk engine."""
    sl = rules.stop_loss
    pct = sl.weak_market_pct if market.state == MarketState.WEAK else sl.pct
    candidates = [(price * (1 - pct / 100), f"Cắt lỗ ban đầu −{vg(pct)}% giá vào")]
    if atr14:
        candidates.append((price - sl.atr_multiplier * atr14, f"Cắt lỗ {vg(sl.atr_multiplier)}×ATR{sl.atr_period}"))
    return max(candidates, key=lambda c: c[0])


def split_lots(total_lots: int, pcts: list[float]) -> list[int]:
    """Chia số lô theo tỷ lệ, tổng đúng bằng total_lots. Phần dư theo phần thập phân lớn nhất, bằng nhau thì
    dồn về các đợt sau (đợt thăm dò không bao giờ lớn hơn tỷ lệ). Đợt 1 luôn có ít nhất 1 lô nếu kế hoạch có lô."""
    total = sum(pcts)
    exact = [total_lots * p / total for p in pcts]
    lots = [int(e + 1e-9) for e in exact]
    order = sorted(range(len(pcts)), key=lambda i: (round(exact[i] - lots[i], 9), i), reverse=True)
    for i in order[:total_lots - sum(lots)]:
        lots[i] += 1
    if total_lots and len(lots) > 1 and lots[0] == 0:
        donor = max(range(len(lots) - 1, 0, -1), key=lambda i: lots[i])
        lots[donor] -= 1
        lots[0] = 1
    return lots


def _tranches(price: float, atr14: float | None, qty_plan: int, rules: Rules) -> list[SizingTranche]:
    e = rules.entry
    lots = split_lots(qty_plan // LOT, e.tranches)
    step = lambda p: max(p * e.add_only_if_up_pct / 100, e.add_only_if_up_atr_mult * (atr14 or 0.0))  # noqa: E731
    triggers = [price]
    for _ in e.tranches[1:]:
        triggers.append(triggers[-1] + step(triggers[-1]))

    out: list[SizingTranche] = []
    for i, (pct, n) in enumerate(zip(e.tranches, lots)):
        qty = n * LOT
        skipped = False
        if i == 0:
            cond = (f"Có tín hiệu vào (đóng cửa trên SMA20 đang dốc lên, RSI14 từ {vg(e.rsi_min)} đến {vg(e.rsi_max)}, "
                    f"khối lượng ≥ {vg(e.volume_ratio_min)}× trung bình 20 phiên) và VN-Index cho phép mua.")
        else:
            cond = (f"Đóng cửa từ {vn(triggers[i], 0)} trở lên (cao hơn giá đợt trước ít nhất "
                    f"max(+{vg(e.add_only_if_up_pct)}%, {vg(e.add_only_if_up_atr_mult)}×ATR14)), đợt trước đã về tài khoản "
                    f"và đang lãi, cách đợt trước tối thiểu 1 phiên.")
            if i == len(e.tranches) - 1:
                fills = [(triggers[j], lots[j] or 1) for j in range(i)]
                avg = sum(p * w for p, w in fills) / sum(w for _, w in fills)
                skipped = triggers[i] > avg * (1 + e.skip_tranche_if_above_avg_pct / 100)
                cond += (f" Dự kiến bỏ qua: khi đó giá cách giá vốn trung bình hơn {vg(e.skip_tranche_if_above_avg_pct)}%."
                         if skipped else
                         f" Bỏ qua nếu giá cách giá vốn trung bình quá {vg(e.skip_tranche_if_above_avg_pct)}%.")
        out.append(SizingTranche(index=i + 1, pct=pct, quantity=qty, value=qty * triggers[i], trigger_price=triggers[i],
                                 condition=cond, likely_skipped=skipped))
    return out


def size_position(*, symbol: str, price: float, atr14: float | None, capital: float, positions_count: int,
                  held: PositionEval | None, rules: Rules, market: MarketInfo, stop: float | None = None) -> SizingPlan:
    if price <= 0:
        raise ValueError("Giá vào phải lớn hơn 0")
    custom_stop = stop is not None
    if stop is None:
        stop, basis = initial_stop(price, atr14, rules, market)
    else:
        basis = "Giá cắt lỗ do bạn nhập"
    distance = price - stop
    if distance <= 0:
        raise ValueError("Giá cắt lỗ phải thấp hơn giá vào")

    capital = max(0.0, capital)
    risk_money = capital * rules.risk_per_trade_pct / 100
    qty_by_risk = _floor_lot(risk_money / distance)
    qty_by_weight = _floor_lot(capital * rules.max_weight_pct / 100 / price)
    qty_plan = min(qty_by_risk, qty_by_weight)
    binding = "weight" if qty_by_weight < qty_by_risk else "risk"
    plan_value = qty_plan * price
    held_qty = held.quantity if held else 0

    w: list[SizingWarning] = []
    if capital <= 0:
        w.append(SizingWarning(code="NO_CAPITAL", severity="block", message=(
            "Không có tiền mặt. Vốn giao dịch tính theo tiền mặt thực có, không tính margin.")))
    elif qty_plan == 0:
        w.append(SizingWarning(code="QTY_ZERO", severity="block", message=(
            f"Vốn {vn(capital, 0)} đồng chưa đủ mua 1 lô ({LOT} cp) với rủi ro {vg(rules.risk_per_trade_pct)}% vốn và "
            f"tỷ trọng tối đa {vg(rules.max_weight_pct)}% vốn.")))
    elif binding == "weight":
        w.append(SizingWarning(code="WEIGHT_CAP", severity="info", message=(
            f"Khối lượng bị giới hạn bởi tỷ trọng tối đa {vg(rules.max_weight_pct)}% vốn, "
            f"chưa dùng hết mức rủi ro {vg(rules.risk_per_trade_pct)}%.")))

    mf = rules.entry.market_filter
    if market.state == MarketState.NO_NEW_BUYS:
        w.append(SizingWarning(code="MARKET_NO_NEW_BUYS", severity="block", message=(
            f"{mf.index} dưới SMA{mf.fast_ma}: luật không cho mở vị thế swing mới, chỉ quản lý vị thế đang có.")))
    elif market.state == MarketState.WEAK:
        w.append(SizingWarning(code="MARKET_WEAK", severity="block", message=(
            f"{mf.index} dưới SMA{mf.slow_ma}: thị trường yếu, luật không cho mở vị thế swing mới.")))
    elif market.state == MarketState.UNKNOWN:
        w.append(SizingWarning(code="MARKET_UNKNOWN", severity="info", message=(
            "Chưa đủ dữ liệu chỉ số để xác định bộ lọc thị trường, tạm coi như bình thường.")))

    if not held_qty and positions_count >= rules.max_positions:
        w.append(SizingWarning(code="MAX_POSITIONS", severity="block", message=(
            f"Đang giữ {positions_count} mã, đã tới giới hạn {rules.max_positions} mã. Bán bớt một mã trước khi mở mã mới.")))
    if held_qty:
        w.append(SizingWarning(code="ALREADY_HELD", severity="info", message=(
            f"Đang giữ {vn(held_qty, 0)} cp. Kế hoạch là tổng khối lượng cho mã này, phần cần mua thêm là "
            f"{vn(max(0, qty_plan - held_qty), 0)} cp.")))
        if held and held.mode == "swing" and held.price < held.avg_cost:
            w.append(SizingWarning(code="AVERAGING_DOWN", severity="block", message=(
                f"Đang giữ {symbol} ở giá thấp hơn giá vốn ({vn(held.avg_cost, 0)}). "
                "Mã swing cấm mua thêm khi đang lỗ, đó là trung bình giá xuống.")))
    if atr14 is None and not custom_stop:
        w.append(SizingWarning(code="ATR_MISSING", severity="warn", message=(
            "Chưa có ATR14 của mã này nên mức cắt lỗ chỉ tính theo % giá vào. Mã biến động mạnh có thể cần cắt lỗ gần hơn.")))

    return SizingPlan(
        symbol=symbol, price=price, stop_price=stop, stop_basis=basis, stop_distance=distance,
        stop_distance_pct=distance / price * 100, atr14=atr14, capital=capital, risk_pct=rules.risk_per_trade_pct,
        risk_money=risk_money, max_weight_pct=rules.max_weight_pct, qty_by_risk=qty_by_risk,
        qty_by_weight=qty_by_weight, qty_plan=qty_plan, binding=binding, plan_value=plan_value,
        plan_weight_pct=(plan_value / capital * 100) if capital else None, risk_at_stop=qty_plan * distance,
        tranches=_tranches(price, atr14, qty_plan, rules), held_quantity=held_qty,
        additional_quantity=max(0, qty_plan - held_qty) if held_qty else qty_plan, positions_count=positions_count,
        max_positions=rules.max_positions, market=market, allowed=not any(x.severity == "block" for x in w),
        warnings=w)

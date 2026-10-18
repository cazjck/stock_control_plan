"""Bảng kiểm trước khi mua (mục 1, 2, 5, 6, 7 của docs/trading-rules.md).

Gom mọi luật liên quan tới một lệnh mua dự định thành một câu trả lời: được mua, cân nhắc, hay không nên mua,
kèm từng dòng kiểm tra và số liệu để tự đối chiếu. Hàm thuần tuý; chỉ tính toán, không đặt lệnh."""
from __future__ import annotations

import math

import pandas as pd

from ..models import (
    Loan, MarginMetrics, PositionEval, PreTradeCheck, PreTradeItem, PreTradeMargin, SizingPlan, TechPlan,
)
from ..util import vg, vn
from .deleverage import ratio_for
from .margin import drop_to_threshold, loan_interest_after_paydown, loan_interest_per_day
from .rules import Rules


def _fmt(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


def _ok(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def margin_effect(m: MarginMetrics, loans: list[Loan], value: float) -> PreTradeMargin:
    """Tỷ lệ ký quỹ nếu mua `value` bằng tiền vay, và lãi bớt được nếu dùng chính số tiền đó trả nợ."""
    b = m.bucket
    v0, d0 = b.market_value or 0.0, b.debt or 0.0
    after = ratio_for(b.ratio_kind, b.ratio_pct, v0, d0, v0 + value, d0 + value) if d0 + value > 0 else None
    drop_b = drop_to_threshold(b.ratio_pct, b.maintenance_pct, b.ratio_kind) if b.ratio_pct is not None and b.maintenance_pct else None
    drop_a = drop_to_threshold(after, b.maintenance_pct, b.ratio_kind) if after is not None and b.maintenance_pct else None
    saved = loan_interest_per_day(loans) - loan_interest_after_paydown(loans, value) if loans else 0.0
    return PreTradeMargin(account_label=b.source or b.label, ratio_before=b.ratio_pct, ratio_after=after,
                          maintenance_pct=b.maintenance_pct, drop_before=drop_b, drop_after=drop_a,
                          interest_saved_if_repay=saved)


def entry_signals(s: pd.DataFrame | None, rules: Rules) -> list[PreTradeItem]:
    """Tín hiệu vào lệnh swing (mục 2.3): RSI, khối lượng, khoảng cách SMA20, không mua phiên tăng nóng."""
    if s is None or len(s) < 21:
        return [PreTradeItem(code="signals", label="Tín hiệu vào lệnh (mục 2.3)", status="warn",
                             detail="Chưa có dữ liệu nến để kiểm tra", rule="2.3")]
    e = rules.entry
    last = s.iloc[-1]
    rsi = float(last.get("rsi14", float("nan")))
    vol_ma = float(last.get("vol_ma20", float("nan")))
    vr = float(last["volume"]) / vol_ma if _ok(vol_ma) and vol_ma > 0 else float("nan")
    sma20 = float(last.get("sma20", float("nan")))
    close = float(last["close"])
    dist = (close / sma20 - 1) * 100 if _ok(sma20) and sma20 > 0 else float("nan")
    day = (close / float(s["close"].iloc[-2]) - 1) * 100
    out = [
        PreTradeItem(code="rsi", label=f"RSI14 trong khoảng {vg(e.rsi_min)}–{vg(e.rsi_max)}", rule="2.3",
                     status="pass" if _ok(rsi) and e.rsi_min <= rsi <= e.rsi_max else "warn",
                     detail=f"RSI14 {vn(rsi, 0)}" if _ok(rsi) else "chưa có"),
        PreTradeItem(code="volume", label=f"Khối lượng từ {vg(e.volume_ratio_min)}× trung bình 20 phiên", rule="2.3",
                     status="pass" if _ok(vr) and vr >= e.volume_ratio_min else "warn",
                     detail=f"{vn(vr, 2)}×" if _ok(vr) else "chưa có"),
        PreTradeItem(code="sma20", label=f"Giá trên SMA20 và cách không quá {vg(e.max_distance_to_sma20_pct)}%", rule="2.3",
                     status="pass" if _ok(dist) and 0 <= dist <= e.max_distance_to_sma20_pct else "warn",
                     detail=f"cách SMA20 {vn(dist, 1, sign=True)}%" if _ok(dist) else "chưa có"),
    ]
    if day > e.no_buy_if_day_gain_pct_above:
        out.append(PreTradeItem(code="hot_day", label=f"Không mua phiên tăng trên {vg(e.no_buy_if_day_gain_pct_above)}%",
                                status="fail", detail=f"phiên gần nhất {vn(day, 1, sign=True)}%", rule="2.3"))
    return out


def build_pretrade(*, symbol: str, quantity: int | None, price: float, sizing: SizingPlan, held: PositionEval | None,
                   tech: TechPlan | None, series: pd.DataFrame | None, margin: MarginMetrics | None, loans: list[Loan],
                   buys_today: int, rules: Rules) -> PreTradeCheck:
    qty = quantity if quantity and quantity > 0 else sizing.additional_quantity
    value = qty * price
    items: list[PreTradeItem] = []

    # 1. luật vốn, thị trường, số mã, trung bình giá xuống: lấy từ máy tính khối lượng
    rule_of = {"NO_CAPITAL": "1", "QTY_ZERO": "1", "WEIGHT_CAP": "1", "MARKET_NO_NEW_BUYS": "2.4", "MARKET_WEAK": "2.4",
               "MARKET_UNKNOWN": "2.4", "MAX_POSITIONS": "1", "ALREADY_HELD": "2.1", "AVERAGING_DOWN": "2.1",
               "ATR_MISSING": "3.1"}
    label_of = {"NO_CAPITAL": "Không có tiền mặt", "QTY_ZERO": "Vốn chưa đủ một lô theo luật",
                "WEIGHT_CAP": "Giới hạn tỷ trọng tối đa", "MARKET_NO_NEW_BUYS": "Thị trường chưa cho mở vị thế mới",
                "MARKET_WEAK": "Thị trường yếu", "MARKET_UNKNOWN": "Chưa rõ bộ lọc thị trường",
                "MAX_POSITIONS": "Đã đủ số mã tối đa", "ALREADY_HELD": "Đang giữ mã này",
                "AVERAGING_DOWN": "Mua bình quân giá xuống", "ATR_MISSING": "Thiếu ATR14 để đặt cắt lỗ"}
    sev = {"block": "fail", "warn": "warn", "info": "info"}
    for w in sizing.warnings:
        items.append(PreTradeItem(code=w.code.lower(), label=label_of.get(w.code, w.code), status=sev[w.severity],
                                  detail=w.message, rule=rule_of.get(w.code, "")))
    if not any(w.code.startswith("MARKET_") for w in sizing.warnings):
        items.append(PreTradeItem(code="market", label="Bộ lọc thị trường chung", status="pass",
                                  detail=sizing.market.note or "VN-Index trên SMA50 và SMA200", rule="2.4"))

    # 2. khối lượng so với luật
    if sizing.qty_plan > 0:
        over = qty > sizing.additional_quantity
        items.append(PreTradeItem(code="size", label="Khối lượng trong giới hạn theo rủi ro 1R và tỷ trọng",
                                  status="fail" if over else "pass", rule="1",
                                  detail=f"định mua {_fmt(qty)} cp, tối đa {_fmt(sizing.additional_quantity)} cp "
                                         f"(cắt lỗ {_fmt(sizing.stop_price)}, rủi ro {vg(rules.risk_per_trade_pct)}% vốn)"))

    # 3. margin
    m_eff = None
    if margin is not None and (margin.bucket.debt or 0) > 0:
        m_eff = margin_effect(margin, loans, value)
        items.append(PreTradeItem(
            code="margin_debt", label="Đang vay margin: ưu tiên trả nợ trước khi mua", status="fail", rule="5, 6.4",
            detail=f"{m_eff.account_label} đang nợ {_fmt(margin.bucket.debt or 0)}."
                   + (f" Dùng {_fmt(value)} trả nợ thì bớt {_fmt(m_eff.interest_saved_if_repay)} lãi mỗi ngày." if value > 0 else "")))
        if value > 0 and m_eff.ratio_after is not None and m_eff.ratio_before is not None:
            items.append(PreTradeItem(
                code="margin_ratio", label="Tỷ lệ ký quỹ nếu mua bằng tiền vay",
                status="fail" if margin.bucket.maintenance_pct and m_eff.ratio_after <= margin.bucket.maintenance_pct + rules.margin.rtt_buffer_pct_points else "warn",
                rule="5", detail=(f"từ {vn(m_eff.ratio_before, 1)}% xuống {vn(m_eff.ratio_after, 1)}%"
                                  + ("; dưới ngưỡng duy trì ngay khi mua, sẽ bị gọi ký quỹ"
                                     if margin.bucket.maintenance_pct and m_eff.ratio_after <= margin.bucket.maintenance_pct
                                     else f"; giảm thêm {vn(m_eff.drop_after, 1)}% là bị gọi ký quỹ (hiện {vn(m_eff.drop_before, 1)}%)"
                                     if m_eff.drop_after is not None and m_eff.drop_before is not None else ""))))

    # 4. mã đang giữ: hàng kẹt, đang gồng, lô mua thêm
    if held is not None:
        if getattr(held.status, "value", held.status) == "TRAPPED":
            items.append(PreTradeItem(code="trapped", label="Mã là hàng kẹt: không mua thêm", status="fail", rule="6.3",
                                      detail=f"đang lỗ {vn(held.pnl_pct, 1, sign=True)}%"))
        if held.hold is not None:
            items.append(PreTradeItem(code="holding", label="Mã đang gồng theo quyết định", status="fail", rule="6c",
                                      detail="Quyết định gồng là giữ chờ hồi rồi cơ cấu, không phải mua thêm"))

    # 5. kỹ thuật
    if tech is not None and tech.stage is not None:
        st = {4: "fail", 1: "warn", 3: "warn", 2: "pass"}[tech.stage]
        items.append(PreTradeItem(code="stage", label="Giai đoạn xu hướng (Weinstein)", status=st, rule="6d",
                                  detail=tech.stage_label))
        items.append(PreTradeItem(code="bottom", label="Dấu hiệu xác nhận đáy", status="info", rule="6d",
                                  detail=f"{tech.bottom_score}/6, {tech.bottom_label.lower()}"))
    items += entry_signals(series, rules)

    # 6. hành vi
    lim = rules.behavior.max_new_buys_per_day
    items.append(PreTradeItem(code="buys_today", label=f"Tối đa {lim} lệnh mua mỗi ngày", rule="7",
                              status="fail" if buys_today >= lim else "pass", detail=f"hôm nay đã ghi {buys_today} lần mua"))

    fails = [x for x in items if x.status == "fail"]
    warns = [x for x in items if x.status == "warn"]
    verdict = "blocked" if fails else "caution" if warns else "ok"
    if verdict == "blocked":
        head = f"Không nên mua {symbol}: {len(fails)} luật không cho phép ({', '.join(x.label.lower() for x in fails[:3])})."
    elif verdict == "caution":
        head = f"Được mua theo luật nhưng cần cân nhắc {len(warns)} điểm."
    else:
        head = f"Được mua {symbol} theo luật."
    if value <= 0:
        sug = "Luật không cho mua thêm cổ phiếu nào lúc này. Nhập khối lượng để xem ảnh hưởng tới ký quỹ."
    elif m_eff and m_eff.interest_saved_if_repay > 0:
        sug = (f"Số tiền {_fmt(value)} nếu dùng trả nợ {m_eff.account_label} sẽ bớt {_fmt(m_eff.interest_saved_if_repay)} "
               f"lãi mỗi ngày, khoảng {_fmt(m_eff.interest_saved_if_repay * 30)} mỗi tháng, chắc chắn hơn kỳ vọng từ lệnh mua.")
    elif verdict != "blocked" and sizing.tranches:
        t1 = sizing.tranches[0]
        sug = (f"Nếu mua: chia đợt theo mục 2.1, đợt 1 khoảng {_fmt(t1.quantity)} cp; cắt lỗ {_fmt(sizing.stop_price)} "
               f"(rủi ro tối đa {_fmt(sizing.risk_at_stop)}).")
    else:
        sug = ""
    return PreTradeCheck(symbol=symbol, quantity=qty, price=price, value=value, verdict=verdict, headline=head, items=items,
                         max_qty=sizing.additional_quantity, stop_price=sizing.stop_price, margin=m_eff, suggestion=sug)

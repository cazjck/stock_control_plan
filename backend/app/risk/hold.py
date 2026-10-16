"""Gồng có kế hoạch (mục 6c). Hàm thuần tuý: xét quyết định gồng của một dòng theo giá, tỷ lệ ký quỹ, ngày."""
from __future__ import annotations

from datetime import date

from ..models import HoldDecision, HoldStatus, RotationPlan
from ..util import vn


def _fmt(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


def evaluate_hold(d: HoldDecision, *, close: float, ratio_pct: float | None, maintenance_pct: float | None,
                  rotation: RotationPlan | None, interest_per_day: float, today: date) -> HoldStatus:
    days = max(0, (today - d.decided_at).days)
    cost = interest_per_day * days
    floor = d.ratio_floor_pct if d.ratio_floor_pct is not None else maintenance_pct
    dist = (close / d.exit_close_below - 1) * 100 if d.exit_close_below > 0 else None
    base = (f"Đang gồng {days} ngày theo quyết định {d.decided_at:%d/%m}, đã trả khoảng {_fmt(cost)} lãi margin cho phần này "
            f"({_fmt(interest_per_day)}/ngày).")
    if close < d.exit_close_below:
        state = "exit_price"
        text = (f"Giá đóng cửa {_fmt(close)} đã thủng giá thoát bạn tự đặt {_fmt(d.exit_close_below)}: giả định đáy đã sai. "
                f"Kết thúc gồng, bán theo kế hoạch hạ margin. {base}")
    elif floor is not None and ratio_pct is not None and ratio_pct <= floor:
        state = "exit_margin"
        text = (f"Tỷ lệ ký quỹ {vn(ratio_pct, 1)}% đã chạm sàn {vn(floor, 1)}%: nộp tiền hoặc bán ngay theo kế hoạch hạ margin, "
                f"trước khi bị bán cưỡng bức. {base}")
    elif today >= d.review_on:
        state = "review"
        text = (f"Tới ngày xem lại {d.review_on:%d/%m}. Giá chưa thoát được vùng lỗ thì quyết định lại: tiếp tục gồng "
                f"(ghi lý do mới và ngày xem lại mới) hoặc bán theo kế hoạch hạ margin. {base}")
    elif rotation is not None and rotation.level == "sell":
        state = "restructure"
        text = (f"Thời điểm cơ cấu: nhịp hồi {vn(rotation.rebound_pct or 0, 1)}% đã tới vùng bán. Bán {_fmt(rotation.sell_qty)} cổ phiếu "
                f"theo mục 6b, tiền bán trả nợ margin trước, sau đó mới tính mua lại để hạ giá vốn. {base}")
    else:
        state = "holding"
        text = (f"{base} Thoát nếu đóng cửa dưới {_fmt(d.exit_close_below)} (còn cách {vn(dist or 0, 1)}%)"
                + (f" hoặc tỷ lệ ký quỹ xuống {vn(floor, 1)}%" if floor is not None else "")
                + f". Xem lại ngày {d.review_on:%d/%m}.")
    return HoldStatus(decision=d, state=state, text=text, days_held=days, interest_cost=cost,
                      interest_per_day=interest_per_day, distance_to_exit_pct=dist, ratio_pct=ratio_pct,
                      ratio_floor_pct=floor)

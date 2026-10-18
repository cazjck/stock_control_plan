"""Bản tin đầu phiên, cuối phiên và câu trả lời cho lệnh Telegram. Chỉ đọc số liệu đã có, không đặt lệnh."""
from __future__ import annotations

from datetime import date
from typing import Any

from ..models import PreTradeCheck
from ..risk.deleverage import build_overview
from ..util import vn

ZONE_ICON = {"breach": "🔴", "danger": "🔴", "watch": "🟠", "safe": "🟢", "unknown": "⚪"}


def _fmt(x: float | None) -> str:
    return "—" if x is None else f"{x:,.0f}".replace(",", ".")


def _money(x: float) -> str:
    a = abs(x)
    if a >= 1e9:
        return f"{vn(x / 1e9, 2)} tỷ"
    if a >= 1e6:
        return f"{vn(x / 1e6, 1)} tr"
    return _fmt(x)


def todo_items(ctx: Any, today: date, limit: int = 3) -> list[str]:
    """Tối đa `limit` việc cần làm, theo thứ tự ưu tiên của bộ luật."""
    out: list[str] = []
    for e in ctx.evals:
        if e.hold and e.hold.state in ("exit_price", "exit_margin", "review"):
            out.append(f"{e.symbol} ({e.source or ''}): {e.hold.text.split('.')[0]}.")
    plan = build_overview(ctx.margin.buckets, ctx.evals, ctx.margin.loans, ctx.rules, today)
    for p in plan.plans:
        for s in p.safe_steps:
            if not s.deferred:
                out.append(f"Bán {_fmt(s.quantity)} {s.symbol} ({p.source or p.label}): {s.reason}.")
    for e in ctx.evals:
        t = e.technical
        if t and t.sell_zones and t.sell_zones[0].distance_pct <= 3:
            z = t.sell_zones[0]
            out.append(f"{e.symbol} ({e.source or ''}) sát vùng bán {_fmt(z.low)}–{_fmt(z.high)}, còn {vn(z.distance_pct, 1)}%: "
                       f"đặt sẵn lệnh bán {_fmt(z.sell_qty)} cp.")
        if e.rotation and e.rotation.level == "rebuy":
            out.append(f"{e.symbol}: đủ điều kiện mua lại {_fmt(e.rotation.rebuy_qty)} cp (đảo hàng).")
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq[:limit]


def margin_lines(ctx: Any) -> list[str]:
    lines = []
    for m in ctx.margin.buckets:
        b = m.bucket
        if not (b.debt or 0) > 0 or b.ratio_pct is None:
            continue
        drop = f", giảm {vn(m.drop_to_maintenance_pct, 1)}% là bị gọi" if m.drop_to_maintenance_pct is not None else ""
        lines.append(f"{ZONE_ICON.get(m.zone, '•')} {b.source or b.label}: {vn(b.ratio_pct, 1)}% (duy trì {vn(b.maintenance_pct, 0)}){drop}")
    return lines


def call_price_lines(ctx: Any) -> list[str]:
    out = []
    for e in sorted(ctx.evals, key=lambda x: x.margin_call_distance_pct or -100, reverse=True):
        if e.margin_call_price is None or e.margin_call_distance_pct is None or e.margin_call_distance_pct < -50:
            continue
        out.append(f"{e.symbol} ({e.source or ''}) {_fmt(e.price)}: gọi ký quỹ dưới {_fmt(e.margin_call_price)} "
                   f"({vn(e.margin_call_distance_pct, 1, sign=True)}%)")
    return out


def brief_text(ctx: Any, kind: str, today: date, *, snapshots: list[dict] | None = None,
               alerts_today: int = 0, link: str = "") -> str:
    title = {"open": "Bản tin đầu phiên", "close": "Bản tin cuối phiên"}.get(kind, "Tình trạng")
    lines = [f"Mớn nước · {title} {today:%d/%m}"]
    stale = [n for n in getattr(ctx, "notes", []) if "nguồn giá" in n or "giá realtime" in n or "không lấy được nến" in n]
    if stale:
        lines += ["", "⚠️ Chưa lấy được giá mới (phiên TCBS hết hạn?). Tỷ lệ ký quỹ dưới đây tính bằng giá cũ, có thể sai. "
                      "Nhập iOTP trong app."]
    if ctx.market.note:
        lines += ["", f"Thị trường: {ctx.market.note}"]
    if kind == "close":
        moves = []
        for e in ctx.evals:
            df = ctx.frames.get(e.symbol)
            if df is not None and len(df) >= 2:
                prev = float(df["close"].iloc[-2]) if df["date"].iloc[-1] == today else float(df["close"].iloc[-1])
                if prev:
                    moves.append(f"{e.symbol} ({e.source or ''}) {_fmt(e.price)} {vn((e.price / prev - 1) * 100, 1, sign=True)}%")
        if moves:
            lines += ["", "Hôm nay:"] + moves
        if snapshots and len(snapshots) >= 2 and snapshots[-1].get("nav") is not None and snapshots[-2].get("nav") is not None:
            d = snapshots[-1]["nav"] - snapshots[-2]["nav"]
            lines.append(f"Tài sản ròng {_money(snapshots[-1]['nav'])} ({'+' if d >= 0 else '−'}{_money(abs(d))} so với phiên trước)")
    ml = margin_lines(ctx)
    if ml:
        lines += ["", "Ký quỹ:"] + ml
    cl = call_price_lines(ctx)
    if cl:
        lines += ["", "Giá gọi ký quỹ (các mã khác đứng giá):"] + cl
    per_day = ctx.margin.interest_per_day
    if per_day:
        lines += ["", f"Lãi margin: {_money(per_day)}/ngày, khoảng {_money(per_day * 30)}/tháng"]
    todo = todo_items(ctx, today)
    if todo:
        lines += ["", "Việc cần làm:" if kind != "close" else "Việc cho phiên sau:"] + [f"{i + 1}. {x}" for i, x in enumerate(todo)]
    elif kind != "close":
        lines += ["", "Không có lệnh bắt buộc hôm nay. Giữ kỷ luật, không mua thêm khi đang vay margin."]
    if kind == "close" and alerts_today:
        lines.append(f"\n{alerts_today} cảnh báo mới trong ngày.")
    return "\n".join(lines) + link


def pretrade_text(c: PreTradeCheck) -> str:
    icon = {"blocked": "⛔", "caution": "⚠️", "ok": "✅"}[c.verdict]
    lines = [f"{icon} {c.headline}", f"{c.symbol}: {_fmt(c.quantity)} cp × {_fmt(c.price)} = {_money(c.value)}"]
    bad = [i for i in c.items if i.status in ("fail", "warn")]
    for i in bad[:8]:
        lines.append(f"{'✗' if i.status == 'fail' else '!'} {i.label}: {i.detail}")
    ok = sum(1 for i in c.items if i.status == "pass")
    if ok:
        lines.append(f"✓ {ok} kiểm tra khác đạt")
    if c.max_qty:
        lines.append(f"Tối đa theo luật: {_fmt(c.max_qty)} cp, cắt lỗ {_fmt(c.stop_price)}")
    if c.suggestion:
        lines += ["", c.suggestion]
    return "\n".join(lines)


HELP = ("Lệnh của Mớn nước:\n"
        "/tinhtrang: ký quỹ, giá gọi ký quỹ, việc cần làm\n"
        "/kiemtra MÃ [SỐ_LƯỢNG] [GIÁ] [NGUỒN]: bảng kiểm trước khi mua, ví dụ /kiemtra PDR 2000 hoặc /kiemtra DXG 1000 10200 ssi\n"
        "App chỉ đọc và khuyến nghị, không đặt lệnh.")

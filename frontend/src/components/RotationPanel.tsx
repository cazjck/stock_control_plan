import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Trash2, X } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { cn, fmtInt, fmtPct, parseVnNumber } from "../lib/format";
import { maskText } from "../lib/privacy";
import { useSelection } from "../lib/selection";
import type { PositionEval, RotationPlan } from "../lib/types";
import { Button, Field, inputCls } from "./ui";

const LEVEL: Record<RotationPlan["level"], string> = {
  sell: "bg-amber-fill text-ink",
  rebuy: "bg-ok text-paper",
  watch: "bg-amber-soft text-amber",
  blocked: "bg-lead-soft text-lead",
  none: "border border-line text-muted",
};

const today = () => new Date().toISOString().slice(0, 10);
const errText = (e: unknown) => (e instanceof ApiError ? e.message : "Không lưu được. Thử lại.");

/** Thước nhịp hồi: đáy, giá bán từng đợt, giá mua lại và giá hiện tại trên cùng một trục, kèm bảng từng bước. */
function Ruler({ r, price }: { r: RotationPlan; price: number }) {
  if (r.low == null || r.high == null) return null;
  const lo = Math.min(r.low, r.floor ?? r.low, r.rebuy_below ?? r.low, price) * 0.98;
  const hi = Math.max(r.high, price, r.sold_avg ?? 0) * 1.01;
  const pos = (v: number) => ((v - lo) / (hi - lo)) * 100;
  const x = (v: number) => `${pos(v)}%`;
  const w = (a: number, b: number) => `${(Math.max(0, b - a) / (hi - lo)) * 100}%`;
  const [t1, t2] = r.tier_prices;
  const open = r.open_qty > 0 && r.rebuy_below != null;
  const ticks: [string, number, string][] = [
    ["Đáy", r.low, "bg-ink"],
    ...(t1 != null ? [["Đợt 1", t1, "bg-amber-fill"] as [string, number, string]] : []),
    ...(t2 != null ? [["Đợt 2", t2, "bg-amber"] as [string, number, string]] : []),
    ...(open ? [["Mua lại", r.rebuy_below!, "bg-ok"] as [string, number, string]] : []),
  ];
  let cum = 0;
  const steps = r.tier_prices.map((p, i) => {
    cum += r.tier_qtys[i] ?? 0;
    const done = r.open_qty >= cum && cum > 0;
    const reached = price >= p;
    return { i, p, qty: r.tier_qtys[i] ?? 0, done, reached, gap: (p / price - 1) * 100 };
  });
  return (
    <figure className="mt-4">
      <div className="relative h-16" aria-hidden>
        <div className="absolute inset-x-0 top-7 h-2 rounded-full bg-line" />
        {t1 != null && <div className="absolute top-7 h-2 bg-amber-soft" style={{ left: x(t1), width: w(t1, r.high) }} />}
        {t2 != null && <div className="absolute top-7 h-2 bg-amber-fill/60" style={{ left: x(t2), width: w(t2, r.high) }} />}
        {open && r.floor != null && <div className="absolute top-7 h-2 bg-ok/50" style={{ left: x(r.floor), width: w(r.floor, r.rebuy_below!) }} />}
        <span className="absolute top-0 -translate-x-1/2 text-center" style={{ left: x(price) }}>
          <span className="num block whitespace-nowrap rounded bg-ink px-1.5 text-[11px] leading-5 text-paper">Giá {fmtInt(price)}</span>
          <span className="mx-auto block h-3 w-0.5 bg-ink" />
        </span>
        {ticks.map(([k, v, c]) => (
          <span key={k} className="absolute top-6 flex -translate-x-1/2 flex-col items-center" style={{ left: x(v) }}>
            <span className={cn("block h-4 w-0.5", c)} />
            <span className="mt-0.5 whitespace-nowrap text-[11px] text-muted">{k}</span>
          </span>
        ))}
      </div>
      <figcaption className="sr-only">Thước giá: đáy {fmtInt(r.low)}, giá hiện tại {fmtInt(price)}, đỉnh trước {fmtInt(r.high)}</figcaption>

      <ol className="mt-3 divide-y divide-line rounded-md border border-line text-sm">
        {steps.map((s) => (
          <li key={s.i} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 px-3 py-2">
            <span className="w-14 font-semibold">Đợt {s.i + 1}</span>
            <span>Khi giá lên <span className="num font-medium">{fmtInt(s.p)}</span> trở lên → bán {s.i > 0 ? "thêm " : ""}<span className="num font-medium">{fmtInt(s.qty)}</span> cổ phiếu</span>
            <span className={cn("num ml-auto text-xs", s.done ? "text-muted" : s.reached ? "font-semibold text-amber" : "text-muted")}>
              {s.done ? "đã bán" : s.reached ? "đã tới giá: bán" : `còn +${fmtPct(s.gap, 1)}`}
            </span>
          </li>
        ))}
        {open && (
          <li className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 px-3 py-2">
            <span className="w-14 font-semibold text-ok">Mua lại</span>
            <span>Khi giá về <span className="num font-medium">{fmtInt(r.rebuy_below)}</span> trở xuống, vẫn trên đáy <span className="num">{fmtInt(r.floor)}</span> → mua lại <span className="num font-medium">{fmtInt(r.open_qty)}</span> cổ phiếu</span>
          </li>
        )}
      </ol>
      <p className="mt-2 text-xs text-muted">
        Đáy gần nhất <span className="num">{fmtInt(r.low)}</span>, đỉnh trước đoạn giảm <span className="num">{fmtInt(r.high)}</span>.
        Bán tối đa một nửa, phần còn lại giữ làm phần lõi.
        {!r.rebuy_allowed && " Mã này chỉ bán, chưa được mua lại."}
      </p>
    </figure>
  );
}

function RecordTrade({ ev, r }: { ev: PositionEval; r: RotationPlan }) {
  const { sel: current } = useSelection();
  const sel = current.broker === "ledger" && ev.account_id ? { ...current, account: ev.account_id } : current;
  const qc = useQueryClient();
  const side0: "sell" | "buy" = r.open_qty > 0 && (r.level === "rebuy" || r.sell_qty === 0) ? "buy" : "sell";
  const [side, setSide] = useState<"sell" | "buy">(side0);
  const suggested = side === "buy" ? r.open_qty || r.rebuy_qty : r.sell_qty;
  const [date, setDate] = useState(today());
  const [qty, setQty] = useState(suggested ? String(suggested) : "");
  const [price, setPrice] = useState(String(Math.round(ev.price)));
  const q = parseVnNumber(qty), p = parseVnNumber(price);
  const m = useMutation({
    mutationFn: () => api.rotationAdd(sel, { symbol: ev.symbol, side, trade_date: date, quantity: Math.round(q ?? 0), price: p ?? 0 }),
    onSuccess: () => { setQty(""); void qc.invalidateQueries(); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); m.mutate(); };
  return (
    <form onSubmit={submit} className="mt-4 rounded-md border border-dashed border-line p-3">
      <p className="mb-2 text-sm font-medium">Ghi lệnh đã khớp ở công ty chứng khoán</p>
      <div className="grid gap-3 sm:grid-cols-4">
        <Field label="Loại">
          <select className={inputCls} value={side} onChange={(e) => { const s = e.target.value as "sell" | "buy"; setSide(s); const n = s === "buy" ? r.open_qty : r.sell_qty; setQty(n ? String(n) : ""); }}>
            <option value="sell">Bán đảo hàng</option>
            <option value="buy" disabled={!r.open_qty}>Mua lại</option>
          </select>
        </Field>
        <Field label="Ngày khớp"><input type="date" className={inputCls} value={date} max={today()} onChange={(e) => setDate(e.target.value)} required /></Field>
        <Field label="Số lượng"><input className={cn(inputCls, "num")} inputMode="numeric" value={qty} onChange={(e) => setQty(e.target.value)} required /></Field>
        <Field label="Giá khớp"><input className={cn(inputCls, "num")} inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} required /></Field>
      </div>
      <p className="mt-2 text-xs text-muted">
        Ứng dụng không đặt lệnh. Ghi lại sau khi khớp để tính giá bán bình quân, vùng mua lại và hạn {r.open_qty ? `(còn ${r.sessions_left} phiên)` : "20 phiên"}.
        {side === "buy" && " Mua lại tối đa đúng số đã bán."}
      </p>
      {m.isError && <p role="alert" className="mt-1 text-sm text-lead">{errText(m.error)}</p>}
      <Button type="submit" variant="primary" className="mt-2" disabled={m.isPending || !q || !p || !date}>
        {side === "sell" ? "Ghi lần bán" : "Ghi lần mua lại"}
      </Button>
    </form>
  );
}

function Trades({ r }: { r: RotationPlan }) {
  const qc = useQueryClient();
  const del = useMutation({ mutationFn: (id: number) => api.rotationDelete(id), onSuccess: () => void qc.invalidateQueries() });
  if (!r.trades.length) return null;
  return (
    <ul className="mt-3 divide-y divide-line rounded-md border border-line text-sm">
      {r.trades.map((t) => (
        <li key={t.id} className="flex items-center gap-3 px-3 py-1.5">
          <span className="w-20 text-muted">{new Date(`${t.trade_date}T00:00:00`).toLocaleDateString("vi-VN")}</span>
          <span className={cn("w-16 font-medium", t.side === "sell" ? "text-amber" : "text-ok")}>{t.side === "sell" ? "Bán" : "Mua lại"}</span>
          <span className="num">{fmtInt(t.quantity)} cp × {fmtInt(t.price)}</span>
          <button type="button" aria-label={`Xoá giao dịch ngày ${t.trade_date}`} onClick={() => del.mutate(t.id)}
            className="ml-auto inline-flex size-8 items-center justify-center rounded-md text-muted hover:bg-sea-soft"><Trash2 size={14} /></button>
        </li>
      ))}
    </ul>
  );
}

/** Mục 6b: bán một phần khi hồi, mua lại khi chỉnh. Chỉ khuyến nghị và ghi nhật ký. */
export function RotationPanel({ ev }: { ev: PositionEval }) {
  const r = ev.rotation;
  if (!r) {
    return <p className="text-sm text-muted">Chỉ áp dụng cho mã đang lỗ ở chế độ lướt sóng. Mã này dùng luật chốt lời thường.</p>;
  }
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn("rounded px-2 py-0.5 text-xs font-semibold", LEVEL[r.level])}>{r.phase_label}</span>
        {r.rebound_pct != null && <span className="num text-xs text-muted">hồi {fmtPct(r.rebound_pct, 1)} từ đáy · lấy lại {fmtPct(r.retrace_pct ?? 0, 0)} đoạn giảm</span>}
      </div>
      <p className="mt-2 text-[15px]">{maskText(r.text)}</p>
      <Ruler r={r} price={ev.price} />
      {r.open_qty > 0 && r.checks.length > 0 && (
        <ul className="mt-4 space-y-1 text-sm" aria-label="Điều kiện mua lại">
          {r.checks.map((c) => (
            <li key={c.code} className="flex gap-2">
              {c.met ? <Check size={16} className="mt-0.5 shrink-0 text-ok" aria-label="đạt" /> : <X size={16} className="mt-0.5 shrink-0 text-lead" aria-label="chưa đạt" />}
              <span>{c.label} <span className="num text-xs text-muted">({c.detail})</span></span>
            </li>
          ))}
        </ul>
      )}
      <Trades r={r} />
      <RecordTrade key={`${r.phase}-${r.open_qty}-${r.sell_qty}`} ev={ev} r={r} />
      <p className="mt-3 text-xs text-muted">
        Giá vốn chỉ giảm khi mua lại thấp hơn giá bán. Nếu mã tăng một mạch, bạn còn ít cổ phiếu hơn. Đảo hàng không thay thế cắt lỗ.
      </p>
    </div>
  );
}

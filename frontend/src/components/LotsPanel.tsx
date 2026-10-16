import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Pencil, Trash2, X } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { cn, fmtInt, fmtMoney, fmtPnlPct, fmtSigned, parseVnNumber, pnlTone } from "../lib/format";
import { maskText } from "../lib/privacy";
import { useSelection } from "../lib/selection";
import type { LotEval, PositionEval } from "../lib/types";
import { SourceTag } from "./SourceTags";
import { Button, Field, inputCls } from "./ui";

const vnDate = (iso: string | null | undefined) => (iso ? new Date(`${iso}T00:00:00`).toLocaleDateString("vi-VN") : "—");
const pnlCls = pnlTone;
const errText = (e: unknown) => (e instanceof ApiError ? e.message : "Không lưu được. Thử lại.");

const RULE = {
  stop: { label: "Phải bán: thủng cắt lỗ", cls: "bg-lead text-paper" },
  time: { label: "Phải bán: hết hạn", cls: "bg-lead text-paper" },
  ok: { label: "Đang theo dõi", cls: "bg-amber-soft text-amber" },
  info: { label: "Lần mua thường", cls: "bg-transparent text-muted border border-line" },
  closed: { label: "Đã bán hết", cls: "bg-transparent text-muted border border-line" },
} as const;

function useInvalidate() {
  const qc = useQueryClient();
  return () => void qc.invalidateQueries();
}

function StopEditor({ lot }: { lot: LotEval }) {
  const [edit, setEdit] = useState(false);
  const [v, setV] = useState(lot.stop_price ? String(Math.round(lot.stop_price)) : "");
  const inv = useInvalidate();
  const m = useMutation({ mutationFn: () => api.lotUpdate(lot.id, { stop_price: parseVnNumber(v) }), onSuccess: () => { setEdit(false); inv(); } });
  if (!lot.add_on_loss || lot.rule_status === "closed") return <span className="text-muted">—</span>;
  if (!edit) {
    return (
      <span className="inline-flex items-center gap-1">
        <span className="num">{fmtInt(lot.stop_price)}</span>
        <button type="button" aria-label="Sửa mức cắt lỗ của lô" onClick={() => setEdit(true)} className="inline-flex size-8 items-center justify-center rounded-md text-muted hover:bg-sea-soft"><Pencil size={14} /></button>
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1">
      <input aria-label="Mức cắt lỗ mới" className={cn(inputCls, "num w-24 text-right")} value={v} onChange={(e) => setV(e.target.value)} />
      <button type="button" aria-label="Lưu" onClick={() => m.mutate()} className="inline-flex size-8 items-center justify-center rounded-md hover:bg-sea-soft"><Check size={15} /></button>
      <button type="button" aria-label="Hủy" onClick={() => setEdit(false)} className="inline-flex size-8 items-center justify-center rounded-md hover:bg-sea-soft"><X size={15} /></button>
    </span>
  );
}

function LotRow({ lot }: { lot: LotEval }) {
  const inv = useInvalidate();
  const del = useMutation({ mutationFn: () => api.lotDelete(lot.id), onSuccess: inv });
  const r = RULE[lot.rule_status];
  const cell = "num px-3 py-2 text-right";
  return (
    <>
      <tr className={cn(lot.rule_status === "closed" && "opacity-60")}>
        <td className="px-3 py-2">
          <span className="num font-medium">{vnDate(lot.buy_date)}</span>
          <span className="block text-[11px] text-muted">
            {lot.source === "auto" ? "tự phát hiện" : lot.source === "ledger" ? "từ sổ" : "nhập tay"}
            {lot.estimated && " · giá ước tính"}
          </span>
        </td>
        <td className="px-3 py-2"><SourceTag source={lot.source_label} /></td>
        <td className={cell}>{fmtInt(lot.remaining)}{lot.remaining !== lot.quantity && <span className="block text-[11px] text-muted">mua {fmtInt(lot.quantity)}</span>}</td>
        <td className={cell}>{fmtInt(lot.price)}</td>
        <td className={cn(cell, pnlCls(lot.pnl_pct))}>
          <span className="font-medium">{fmtPnlPct(lot.pnl_pct)}</span>
          <span className="block text-xs">{fmtSigned(lot.pnl_value)}</span>
        </td>
        <td className="px-3 py-2 text-right"><StopEditor lot={lot} /></td>
        <td className="px-3 py-2">
          <span className={cn("inline-flex rounded-sm px-1.5 py-0.5 text-[11px] font-semibold", r.cls)}>{r.label}</span>
          {lot.add_on_loss && lot.rule_status === "ok" && <span className="num block text-[11px] text-muted">hạn {vnDate(lot.deadline)}</span>}
        </td>
        <td className="px-2 py-2 text-right">
          {lot.source !== "ledger" && (
            <button type="button" aria-label={`Xoá lần mua ngày ${vnDate(lot.buy_date)}`}
                    onClick={() => { if (window.confirm("Xoá lần mua này khỏi lịch sử?")) del.mutate(); }}
                    className="inline-flex size-8 items-center justify-center rounded-md text-muted hover:bg-lead-soft hover:text-lead"><Trash2 size={14} /></button>
          )}
        </td>
      </tr>
      {(lot.rule_status === "stop" || lot.rule_status === "time") && (
        <tr>
          <td colSpan={8} className="border-t-0 bg-lead-soft px-3 py-2 text-sm text-lead">
            {maskText(lot.action)}
            {lot.delay_sessions ? <strong className="ml-1">Đã chần chừ {lot.delay_sessions} phiên{lot.delay_cost ? `, mất thêm ${fmtMoney(lot.delay_cost)}` : ""}.</strong> : null}
          </td>
        </tr>
      )}
    </>
  );
}

function AddLot({ symbol, avgCost, account }: { symbol: string; avgCost: number; account?: string | null }) {
  const { sel: current } = useSelection();
  const sel = account ? { ...current, account } : current;
  const inv = useInvalidate();
  const [date, setDate] = useState("");
  const [qty, setQty] = useState("");
  const [price, setPrice] = useState("");
  const [stop, setStop] = useState("");
  const p = parseVnNumber(price), q = parseVnNumber(qty);
  const m = useMutation({
    mutationFn: () => api.lotAdd(sel, { symbol, buy_date: date, quantity: Math.round(q ?? 0), price: p ?? 0, stop_price: stop ? parseVnNumber(stop) : null }),
    onSuccess: () => { setDate(""); setQty(""); setPrice(""); setStop(""); inv(); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); m.mutate(); };
  return (
    <form onSubmit={submit} className="mt-3 rounded-md border border-dashed border-line p-3">
      <p className="mb-2 text-sm font-medium">Ghi một lần mua trong quá khứ</p>
      <div className="grid gap-3 sm:grid-cols-4">
        <Field label="Ngày mua"><input type="date" className={inputCls} value={date} max={new Date().toISOString().slice(0, 10)} onChange={(e) => setDate(e.target.value)} required /></Field>
        <Field label="Số lượng"><input className={cn(inputCls, "num")} inputMode="numeric" value={qty} onChange={(e) => setQty(e.target.value)} placeholder="2.000" required /></Field>
        <Field label="Giá mua"><input className={cn(inputCls, "num")} inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} placeholder="11.000" required /></Field>
        <Field label="Cắt lỗ của lô (tuỳ chọn)" hint="Để trống: đáy phiên mua −1% hoặc giá mua −5%"><input className={cn(inputCls, "num")} inputMode="decimal" value={stop} onChange={(e) => setStop(e.target.value)} /></Field>
      </div>
      <p className="mt-2 text-xs text-muted">
        Giá mua thấp hơn giá vốn hiện tại ({fmtInt(avgCost)}) thì lô được coi là mua thêm khi đang lỗ và có luật bán riêng.
      </p>
      {m.isError && <p role="alert" className="mt-1 text-sm text-lead">{errText(m.error)}</p>}
      <Button type="submit" variant="primary" className="mt-2" disabled={m.isPending || !date || !q || !p}>Ghi lần mua</Button>
    </form>
  );
}

/** Các lần mua của một mã: ngày, khối lượng, giá, lãi lỗ từng lô, và luật bán của lô mua thêm khi đang lỗ. */
export function LotsPanel({ ev, broker }: { ev: PositionEval; broker?: string }) {
  const lots = ev.lots ?? [];
  const open = lots.filter((l) => l.rule_status !== "closed");
  return (
    <div>
      {lots.length === 0 ? (
        <p className="text-sm text-muted">
          Chưa có lịch sử từng lần mua. Từ nay, mỗi lần khối lượng tăng ứng dụng sẽ tự ghi một lô.
          Lần mua cũ thì ghi tay bên dưới.
        </p>
      ) : (
        <div className="scroll-x rounded-md border border-line">
          <table className="w-full min-w-[46rem] text-sm">
            <caption className="sr-only">Các lần mua {ev.symbol}</caption>
            <thead><tr className="border-b border-line text-left">
              {["Ngày mua", "Nguồn", "Số lượng", "Giá mua", "Lãi lỗ", "Cắt lỗ lô", "Luật", ""].map((h, i) => (
                <th key={h || i} scope="col" className={cn("eyebrow px-3 py-2 font-normal", i >= 2 && i <= 5 && "text-right")}>{h}</th>
              ))}
            </tr></thead>
            <tbody className="divide-y divide-line">
              {lots.map((l) => <LotRow key={`${l.broker}-${l.id}`} lot={l} />)}
              {ev.unknown_lot && (
                <tr>
                  <td className="px-3 py-2 text-muted">Chưa rõ ngày</td>
                  <td className="px-3 py-2" />
                  <td className="num px-3 py-2 text-right">{fmtInt(ev.unknown_lot.quantity)}</td>
                  <td className="num px-3 py-2 text-right">{fmtInt(ev.unknown_lot.avg_cost)}</td>
                  <td className={cn("num px-3 py-2 text-right", ev.unknown_lot.avg_cost ? pnlCls(ev.price - ev.unknown_lot.avg_cost) : "")}>
                    {ev.unknown_lot.avg_cost ? fmtPnlPct((ev.price / ev.unknown_lot.avg_cost - 1) * 100) : "—"}
                  </td>
                  <td colSpan={3} className="px-3 py-2 text-xs text-muted">giá vốn suy ra từ tổng trừ các lần mua đã biết</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      {open.length > 0 && <p className="mt-2 text-xs text-muted">Bán ra được trừ vào lần mua gần nhất trước. Lãi lỗ từng lô tính theo giá hiện tại {fmtInt(ev.price)}.</p>}
      {(broker !== "ledger" || ev.account_id) && (
        <AddLot symbol={ev.symbol} avgCost={ev.avg_cost} account={broker === "ledger" ? ev.account_id : undefined} />
      )}
    </div>
  );
}

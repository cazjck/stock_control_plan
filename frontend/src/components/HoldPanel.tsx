import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../lib/api";
import { cn, fmtDate, fmtInt, fmtMoney, fmtPct, parseVnNumber } from "../lib/format";
import { maskText } from "../lib/privacy";
import { useSelection } from "../lib/selection";
import type { HoldStatus, PositionEval } from "../lib/types";
import { Button, Field, inputCls, Stat } from "./ui";

const STATE: Record<HoldStatus["state"], { label: string; cls: string }> = {
  holding: { label: "Đang gồng", cls: "bg-sea-soft text-ink" },
  restructure: { label: "Thời điểm cơ cấu", cls: "bg-amber-fill text-ink" },
  review: { label: "Tới ngày xem lại", cls: "bg-lead text-paper" },
  exit_margin: { label: "Chạm sàn ký quỹ: kết thúc gồng", cls: "bg-lead text-paper" },
  exit_price: { label: "Thủng giá thoát: kết thúc gồng", cls: "bg-lead text-paper" },
};

const errText = (e: unknown) => (e instanceof ApiError ? e.message : "Không lưu được. Thử lại.");
const plusDays = (n: number) => { const d = new Date(); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); };

function HoldForm({ ev, onDone }: { ev: PositionEval; onDone?: () => void }) {
  const { sel: current } = useSelection();
  const sel = current.broker === "ledger" && ev.account_id ? { ...current, account: ev.account_id } : current;
  const d = ev.hold?.decision;
  const low20 = ev.indicators.low20;
  const inval = ev.technical?.invalidation ?? null;
  const suggested = inval ? Math.round(inval / 10) * 10 : low20 ? Math.round((low20 * 0.97) / 10) * 10 : null;
  const why = inval ? `mức vô hiệu kỹ thuật (${ev.technical?.invalidation_basis})` : `đáy 20 phiên ${fmtInt(low20)} trừ 3%`;
  const [reason, setReason] = useState(d?.reason ?? "");
  const [exit, setExit] = useState(d ? String(Math.round(d.exit_close_below)) : suggested ? String(suggested) : "");
  const [floor, setFloor] = useState(d?.ratio_floor_pct != null ? String(d.ratio_floor_pct) : "");
  const [review, setReview] = useState(d?.review_on ?? plusDays(30));
  const qc = useQueryClient();
  const m = useMutation({
    mutationFn: () => api.holdPut(sel, { symbol: ev.symbol, reason: reason.trim(), exit_close_below: parseVnNumber(exit),
      ratio_floor_pct: floor ? parseVnNumber(floor) : null, review_on: review }),
    onSuccess: () => { void qc.invalidateQueries(); onDone?.(); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); m.mutate(); };
  return (
    <form onSubmit={submit} className="space-y-3">
      <Field label="Vì sao tin mã này sẽ hồi" hint="Viết bằng lời, ít nhất 10 ký tự. Tới ngày xem lại bạn sẽ đọc lại câu này.">
        <textarea className={cn(inputCls, "min-h-20")} value={reason} onChange={(e) => setReason(e.target.value)} required minLength={10} />
      </Field>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Giá thoát (đóng cửa dưới)" hint={suggested ? `Gợi ý ${fmtInt(suggested)}: ${why}. Đóng cửa dưới mức này là giả định "đáy" sai.` : undefined}>
          <input className={cn(inputCls, "num")} inputMode="decimal" value={exit} onChange={(e) => setExit(e.target.value)} required />
        </Field>
        <Field label="Sàn tỷ lệ ký quỹ (%)" hint="Để trống: ngưỡng duy trì của tài khoản. Chạm sàn là phải nộp tiền hoặc bán.">
          <input className={cn(inputCls, "num")} inputMode="decimal" value={floor} onChange={(e) => setFloor(e.target.value)} placeholder="ngưỡng duy trì" />
        </Field>
        <Field label="Ngày xem lại">
          <input type="date" className={inputCls} value={review} min={plusDays(1)} onChange={(e) => setReview(e.target.value)} required />
        </Field>
      </div>
      {m.isError && <p role="alert" className="text-sm text-lead">{errText(m.error)}</p>}
      <Button type="submit" variant="primary" disabled={m.isPending || reason.trim().length < 10 || !parseVnNumber(exit)}>
        {d ? "Lưu quyết định" : "Ghi quyết định gồng"}
      </Button>
    </form>
  );
}

/** Mục 6c: gồng có kế hoạch. Bộ luật không khuyến nghị, nhưng nếu đã chọn thì gồng có điều kiện. */
export function HoldPanel({ ev }: { ev: PositionEval }) {
  const [edit, setEdit] = useState(false);
  const qc = useQueryClient();
  const h = ev.hold;
  const del = useMutation({ mutationFn: (id: number) => api.holdDelete(id), onSuccess: () => void qc.invalidateQueries() });
  if (!h) {
    return (
      <div>
        <p className="mb-3 text-sm text-muted">
          Bộ luật ưu tiên giảm margin (mục 5, 6.4). Nếu bạn vẫn chọn giữ mã này chờ hồi, hãy ghi quyết định kèm ngưỡng thoát.
          App sẽ đếm số ngày và tiền lãi đã trả, báo thời điểm cơ cấu khi giá hồi, và báo khi giả định bị phá.
        </p>
        <HoldForm ev={ev} />
      </div>
    );
  }
  const s = STATE[h.state];
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn("rounded px-2 py-0.5 text-xs font-semibold", s.cls)}>{s.label}</span>
        <span className="text-xs text-muted">từ {fmtDate(h.decision.decided_at)} · xem lại {fmtDate(h.decision.review_on)}</span>
      </div>
      <p className="mt-2 text-[15px]">{maskText(h.text)}</p>
      <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
        <Stat label="Đã gồng" value={`${h.days_held} ngày`} />
        <Stat label="Lãi margin đã trả" value={fmtMoney(h.interest_cost)} sub={`${fmtMoney(h.interest_per_day)}/ngày`} tone="lead" />
        <Stat label="Giá thoát" value={fmtInt(h.decision.exit_close_below)} sub={h.distance_to_exit_pct != null ? `còn cách ${fmtPct(h.distance_to_exit_pct, 1)}` : undefined} />
        <Stat label="Tỷ lệ ký quỹ / sàn" value={h.ratio_pct != null ? fmtPct(h.ratio_pct, 1) : "—"} sub={h.ratio_floor_pct != null ? `sàn ${fmtPct(h.ratio_floor_pct, 1)}` : undefined} />
      </dl>
      <blockquote className="mt-3 border-l-2 border-line pl-3 text-sm text-muted">Lý do đã ghi: {h.decision.reason}</blockquote>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button type="button" onClick={() => setEdit((x) => !x)}>{edit ? "Đóng" : h.state === "review" ? "Gia hạn hoặc sửa" : "Sửa quyết định"}</Button>
        <Button type="button" onClick={() => del.mutate(h.decision.id)} disabled={del.isPending}>Bỏ quyết định gồng</Button>
      </div>
      {edit && <div className="mt-3 rounded-md border border-dashed border-line p-3"><HoldForm ev={ev} onDone={() => setEdit(false)} /></div>}
    </div>
  );
}

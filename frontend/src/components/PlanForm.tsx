import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useSelection } from "../lib/selection";
import type { PositionEval } from "../lib/types";
import { Button, Field, inputCls } from "./ui";

type Thesis = "unset" | "yes" | "no";

/** Kế hoạch từng mã do bạn khai báo, vì broker không cho biết ngày mua hay bạn đã bán bậc chốt lời nào. */
export function PlanForm({ ev }: { ev: PositionEval }) {
  const { sel } = useSelection();
  const qc = useQueryClient();
  const plan = ev.plan;
  const [mode, setMode] = useState<"swing" | "dca">(plan?.mode ?? "swing");
  const [entry, setEntry] = useState(plan?.entry_date ?? "");
  const [thesis, setThesis] = useState<Thesis>(plan?.has_thesis == null ? "unset" : plan.has_thesis ? "yes" : "no");
  const [ladder, setLadder] = useState(plan?.ladder_done ?? 0);
  const [note, setNote] = useState(plan?.note ?? "");

  useEffect(() => {
    setMode(plan?.mode ?? "swing"); setEntry(plan?.entry_date ?? "");
    setThesis(plan?.has_thesis == null ? "unset" : plan.has_thesis ? "yes" : "no");
    setLadder(plan?.ladder_done ?? 0); setNote(plan?.note ?? "");
  }, [plan, ev.symbol]);

  const save = useMutation({
    mutationFn: () => api.putPlan(ev.symbol, sel.broker === "ledger" && ev.account_id ? { ...sel, account: ev.account_id } : sel, {
      mode, entry_date: entry || null, has_thesis: thesis === "unset" ? null : thesis === "yes", ladder_done: ladder, note: note || null,
    }),
    onSuccess: () => void qc.invalidateQueries(),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  const radio = "flex min-h-10 cursor-pointer items-center gap-2 rounded-md border border-line px-3 text-sm has-[:checked]:border-ink has-[:checked]:bg-ink has-[:checked]:text-paper";

  return (
    <form onSubmit={submit} className="space-y-4">
      <fieldset>
        <legend className="mb-1 text-sm font-medium">Chế độ</legend>
        <div className="flex flex-wrap gap-2">
          <label className={radio}><input className="sr-only" type="radio" name="mode" checked={mode === "swing"} onChange={() => setMode("swing")} />Lướt sóng (có cắt lỗ)</label>
          <label className={radio}><input className="sr-only" type="radio" name="mode" checked={mode === "dca"} onChange={() => setMode("dca")} />Tích luỹ DCA</label>
        </div>
        {mode === "dca" && <p className="mt-1 text-xs text-muted">DCA chỉ có ngưỡng thảm hoạ. Chỉ chọn khi bạn viết được luận điểm cơ bản bằng 3 câu.</p>}
      </fieldset>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Ngày mua lần đầu" hint="Dùng để tính đỉnh kể từ khi vào lệnh, cắt lỗ theo thời gian và luật 8 tuần. Để trống thì dùng đỉnh 20 phiên gần nhất.">
          <input type="date" className={inputCls} value={entry} max={new Date().toISOString().slice(0, 10)} onChange={(e) => setEntry(e.target.value)} />
        </Field>
        <Field label="Số bậc chốt lời đã bán" hint="Mỗi bậc là 25% khối lượng ban đầu (mốc +10%, +15%, +25%).">
          <select className={inputCls} value={ladder} onChange={(e) => setLadder(Number(e.target.value))}>
            {[0, 1, 2, 3].map((n) => <option key={n} value={n}>{n === 0 ? "Chưa bán bậc nào" : `Đã bán ${n} bậc`}</option>)}
          </select>
        </Field>
      </div>

      {ev.status === "TRAPPED" && (
        <fieldset>
          <legend className="mb-1 text-sm font-medium">Mã này có luận điểm cơ bản viết được bằng 3 câu không?</legend>
          <div className="flex flex-wrap gap-2">
            {([["unset", "Chưa phân loại"], ["yes", "Có, giữ có điều kiện (nhóm A)"], ["no", "Không, thoát (nhóm B)"]] as const).map(([v, l]) => (
              <label key={v} className={radio}><input className="sr-only" type="radio" name="thesis" checked={thesis === v} onChange={() => setThesis(v)} />{l}</label>
            ))}
          </div>
        </fieldset>
      )}

      <Field label="Ghi chú">
        <textarea className={`${inputCls} min-h-20`} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Luận điểm, lý do mua, điều gì làm bạn bán" />
      </Field>

      <div className="flex items-center gap-3">
        <Button type="submit" variant="primary" disabled={save.isPending}>{save.isPending ? "Đang lưu…" : "Lưu kế hoạch"}</Button>
        {save.isSuccess && <span role="status" className="text-sm text-ok">Đã lưu kế hoạch.</span>}
        {save.isError && <span role="alert" className="text-sm text-lead">Không lưu được. Thử lại.</span>}
      </div>
    </form>
  );
}

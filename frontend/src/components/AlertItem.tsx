import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Info, OctagonAlert, TriangleAlert } from "lucide-react";
import { api } from "../lib/api";
import { maskText } from "../lib/privacy";
import { cn, fmtTime } from "../lib/format";
import type { AlertRecord } from "../lib/types";
import { Button, inputCls } from "./ui";

const SEV = {
  critical: { icon: OctagonAlert, cls: "text-lead", label: "Nghiêm trọng" },
  warning: { icon: TriangleAlert, cls: "text-amber", label: "Cần chú ý" },
  info: { icon: Info, cls: "text-sea", label: "Thông tin" },
} as const;

const RULE_LABEL: Record<string, string> = {
  add_on_lot: "Lô mua thêm",
  stop_loss: "Cắt lỗ", trapped: "Hàng kẹt", time_stop: "Cắt lỗ theo thời gian", technical_warning: "Tín hiệu kỹ thuật",
  take_profit: "Chốt lời", rtt: "Ký quỹ", loan_due: "Đáo hạn", portfolio_loss: "Lỗ danh mục", interest: "Lãi vay",
};

function linkFor(a: AlertRecord): string | null {
  if (a.symbol) return `/symbol/${a.symbol}`;
  if (a.rule === "rtt" || a.rule === "loan_due" || a.rule === "interest") return "/margin";
  return null;
}

export function AlertItem({ alert, manage = false }: { alert: AlertRecord; manage?: boolean }) {
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const [resolving, setResolving] = useState(false);
  const done = () => void qc.invalidateQueries({ queryKey: ["alerts"] });
  const ack = useMutation({ mutationFn: () => api.ack(alert.id), onSuccess: done });
  const resolve = useMutation({ mutationFn: () => api.resolve(alert.id, note), onSuccess: () => { setResolving(false); done(); } });
  const sev = SEV[alert.severity];
  const Icon = sev.icon;
  const link = linkFor(alert);
  const inactive = alert.status === "cleared" || alert.status === "resolved";

  return (
    <article className={cn("rounded-md border border-line bg-panel p-3.5", inactive && "opacity-70")}>
      <div className="flex items-start gap-3">
        <Icon size={20} className={cn("mt-0.5 shrink-0", sev.cls)} aria-label={sev.label} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <h3 className="display text-lg leading-snug">{maskText(alert.title)}</h3>
            <span className="eyebrow">{RULE_LABEL[alert.rule] ?? alert.rule}</span>
          </div>
          <p className="mt-0.5 text-sm text-muted">{maskText(alert.message)}</p>
          <p className="mt-1.5 text-xs text-muted">
            {alert.status === "acked" && "Đã xem · "}
            {alert.status === "cleared" && "Điều kiện đã hết · "}
            {alert.status === "resolved" && `Đã xử lý${alert.resolution_note ? `: ${alert.resolution_note}` : ""} · `}
            Lần cuối {fmtTime(alert.last_seen)}
            {link && <> · <Link to={link} className="font-medium text-sea underline underline-offset-2">Xem chi tiết</Link></>}
          </p>
        </div>
      </div>

      {manage && !inactive && (
        <div className="mt-3 border-t border-line pt-3">
          {!resolving ? (
            <div className="flex flex-wrap gap-2">
              {alert.status === "open" && alert.rule !== "add_on_lot" && (
                <Button onClick={() => ack.mutate()} disabled={ack.isPending}><Check size={15} aria-hidden /> Đã xem</Button>
              )}
              <Button onClick={() => setResolving(true)}>Đã xử lý…</Button>
            </div>
          ) : (
            <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); resolve.mutate(); }}>
              <input className={`${inputCls} max-w-sm`} aria-label="Bạn đã làm gì?" placeholder={alert.rule === "add_on_lot" ? "Bắt buộc: đã bán bao nhiêu, hoặc vì sao không bán" : "Bạn đã làm gì? Ví dụ: bán hết trên app"} value={note} onChange={(e) => setNote(e.target.value)} autoFocus />
              <Button type="submit" variant="primary" disabled={resolve.isPending || (alert.rule === "add_on_lot" && !note.trim())}>Lưu ghi chú</Button>
              <Button variant="ghost" onClick={() => setResolving(false)}>Hủy</Button>
            </form>
          )}
        </div>
      )}
    </article>
  );
}

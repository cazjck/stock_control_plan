import { CircleCheck, CircleDashed } from "lucide-react";
import { cn, fmtInt, fmtPct } from "../lib/format";
import { maskText } from "../lib/privacy";
import type { TakeProfitPlan, TakeProfitSignal, TakeProfitTarget } from "../lib/types";

const LEVEL = {
  full: { cls: "border-lead/50 bg-lead-soft text-lead", title: "Bán phần còn lại" },
  partial: { cls: "border-ok/50 bg-ok-soft text-ok", title: "Chốt một phần" },
  watch: { cls: "border-amber/50 bg-amber-soft text-amber", title: "Theo dõi" },
  none: { cls: "border-line bg-paper text-ink", title: "Giữ" },
} as const;

function Advice({ plan }: { plan: TakeProfitPlan }) {
  const l = LEVEL[plan.advice.level];
  return (
    <div className={cn("rounded-md border px-3.5 py-3", l.cls)} role="status">
      <p className="display text-lg leading-tight">{l.title}{plan.advice.sell_qty ? ` · ${fmtInt(plan.advice.sell_qty)} cp` : ""}</p>
      <p className="mt-0.5 text-sm text-ink">{maskText(plan.advice.text)}</p>
    </div>
  );
}

function TargetState({ t }: { t: TakeProfitTarget }) {
  if (t.suspended) return <span className="text-amber">Tạm hoãn (8 tuần)</span>;
  if (t.executed) return <span className="text-muted">Đã bán</span>;
  if (t.reached) return <span className="font-medium text-ok">{t.kind === "ladder" ? "Đã tới, cần bán" : "Đã tới"}</span>;
  return <span className="num text-muted">còn {fmtPct(t.distance_pct)}</span>;
}

function Targets({ plan }: { plan: TakeProfitPlan }) {
  const ladder = plan.targets.filter((t) => t.kind === "ladder");
  const r = plan.targets.filter((t) => t.kind === "r");
  return (
    <div>
      <p className="eyebrow mb-1">Giá mục tiêu</p>
      <ul className="divide-y divide-line text-sm">
        {ladder.map((t) => (
          <li key={t.label} className="flex flex-wrap items-baseline justify-between gap-x-3 py-2">
            <span className="flex items-baseline gap-3">
              <span className="num w-12 shrink-0">{t.label}</span>
              <span className="num font-medium">{fmtInt(t.price)}</span>
              <span className="text-muted">bán {fmtInt(t.sell_qty)} cp</span>
            </span>
            <TargetState t={t} />
          </li>
        ))}
      </ul>
      {r.length > 0 && (
        <p className="mt-2 text-xs text-muted">
          Tham chiếu theo R (1R = {fmtInt(plan.r_value)} đồng/cp, lãi hiện tại {plan.r_multiple != null ? `${plan.r_multiple.toFixed(1).replace(".", ",")}R` : "—"}):{" "}
          {r.map((t) => `${t.label} ${fmtInt(t.price)}`).join(" · ")}
        </p>
      )}
      <p className="mt-1 text-xs text-muted">Khối lượng ban đầu ước tính {fmtInt(plan.original_qty)} cp. Mỗi bậc bán 25% khối lượng ban đầu, làm tròn lô 100.</p>
    </div>
  );
}

function Signals({ list, title }: { list: TakeProfitSignal[]; title: string }) {
  return (
    <div>
      <p className="eyebrow mb-1">{title}</p>
      <ul className="space-y-1.5 text-sm">
        {list.map((x) => (
          <li key={x.code} className="flex gap-2">
            {x.met
              ? <CircleCheck size={16} className="mt-0.5 shrink-0 text-ok" aria-label="Đạt" />
              : <CircleDashed size={16} className="mt-0.5 shrink-0 text-muted" aria-label="Chưa đạt" />}
            <span className={x.met ? "" : "text-muted"}>
              {x.label}
              <span className="num block text-xs text-muted">{x.detail}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Khuyến nghị chốt lời hôm nay: một hành động, giá mục tiêu, và bảng kiểm dấu hiệu để tự đối chiếu. */
export function TakeProfitPanel({ plan }: { plan: TakeProfitPlan | null | undefined }) {
  if (!plan) {
    return <p className="text-sm text-muted">Mã đang lỗ sâu hoặc ở chế độ DCA nên không có kế hoạch chốt lời. Xem mục việc cần làm.</p>;
  }
  return (
    <div className="space-y-4">
      <Advice plan={plan} />
      <Targets plan={plan} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Signals title="Bán vào sức mạnh: dấu hiệu cao trào" list={plan.signals.filter((x) => x.group === "strength")} />
        <Signals title="Bán khi yếu đi để giữ lãi" list={plan.signals.filter((x) => x.group === "weakness")} />
      </div>
      <p className="text-xs text-muted">Từ 2 dấu hiệu cao trào thì bán một nửa. Một dấu hiệu chỉ là lời nhắc theo dõi. Thứ tự ưu tiên ở mục 4b của bộ luật.</p>
    </div>
  );
}

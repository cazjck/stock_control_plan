import { Check, ChevronDown, X } from "lucide-react";
import { cn, fmtInt, fmtPct } from "../lib/format";
import { maskText } from "../lib/privacy";
import type { PositionEval, TechPlan, TechZone } from "../lib/types";

const STAGE_TONE: Record<number, string> = { 1: "bg-amber-soft text-amber", 2: "bg-ok text-paper", 3: "bg-amber-soft text-amber", 4: "bg-lead text-paper" };

function Dots({ n, max = 4 }: { n: number; max?: number }) {
  return (
    <span className="inline-flex gap-0.5" aria-label={`${n} nhóm công cụ`}>
      {Array.from({ length: max }, (_, i) => (
        <span key={i} aria-hidden className={cn("size-1.5 rounded-full", i < n ? "bg-ink" : "bg-line")} />
      ))}
    </span>
  );
}

type Row =
  | { type: "zone"; z: TechZone; sell?: TechZone }
  | { type: "price"; price: number }
  | { type: "invalid"; price: number; basis: string };

/** Thang giá: vùng cản phía trên, giá hiện tại, vùng đỡ và mức vô hiệu phía dưới. Đọc từ trên xuống như bảng giá. */
function Ladder({ t, price }: { t: TechPlan; price: number }) {
  const sellAt = new Map(t.sell_zones.map((z) => [Math.round(z.price), z]));
  const rows: Row[] = [
    ...[...t.resistance].reverse().map((z) => ({ type: "zone" as const, z, sell: sellAt.get(Math.round(z.price)) })),
    { type: "price", price },
    ...t.support.map((z) => ({ type: "zone" as const, z })),
    ...(t.invalidation != null ? [{ type: "invalid" as const, price: t.invalidation, basis: t.invalidation_basis }] : []),
  ];
  // các vùng bán nằm ngoài 6 vùng cản đang hiện (ít gặp) vẫn phải xuất hiện
  t.sell_zones.filter((z) => !t.resistance.some((r) => Math.round(r.price) === Math.round(z.price)))
    .forEach((z) => rows.unshift({ type: "zone", z, sell: z }));
  return (
    <ol className="divide-y divide-line overflow-hidden rounded-md border border-line text-sm" aria-label="Thang giá theo kỹ thuật">
      {rows.map((r, i) => {
        if (r.type === "price") {
          return (
            <li key="price" className="flex items-center gap-3 bg-ink px-3 py-2 text-paper">
              <span className="num w-32 font-semibold">{fmtInt(r.price)}</span>
              <span className="text-xs">Giá hiện tại</span>
            </li>
          );
        }
        if (r.type === "invalid") {
          return (
            <li key="invalid" className="flex flex-wrap items-center gap-x-3 gap-y-0.5 bg-lead-soft px-3 py-2">
              <span className="num w-32 font-semibold text-lead">{fmtInt(r.price)}</span>
              <span className="text-xs text-lead">Mức vô hiệu: đóng cửa dưới đây thì giả định "đáy" sai</span>
              <span className="w-full pl-0 text-[11px] text-muted sm:ml-35 sm:w-auto">{r.basis}</span>
            </li>
          );
        }
        const z = r.z;
        const res = z.kind === "resistance";
        return (
          <li key={`${z.kind}-${i}`} className={cn("flex flex-wrap items-center gap-x-3 gap-y-0.5 px-3 py-2", r.sell && "bg-amber-soft/50")}>
            <span className="num w-32">{z.low === z.high ? fmtInt(z.price) : `${fmtInt(z.low)}–${fmtInt(z.high)}`}</span>
            <span className="flex items-center gap-2">
              <Dots n={z.strength} />
              <span className={cn("text-xs", res ? "text-amber" : "text-ok")}>{res ? "cản" : "đỡ"} {fmtPct(z.distance_pct, 1, true)}</span>
            </span>
            <span className="min-w-0 flex-1 truncate text-xs text-muted" title={z.tools.join(", ")}>{z.tools.slice(0, 4).join(" · ")}{z.tools.length > 4 ? ` +${z.tools.length - 4}` : ""}</span>
            {r.sell && (
              <span className="num w-full text-xs font-semibold sm:w-auto">
                bán {fmtInt(r.sell.sell_qty)} cp
                {r.sell.ratio_after != null && <span className="font-normal text-muted"> · ký quỹ còn {fmtPct(r.sell.ratio_after, 1)}</span>}
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}

/** Mục 6d: kế hoạch theo kỹ thuật cho một dòng. */
export function TechPlanPanel({ ev }: { ev: PositionEval }) {
  const t = ev.technical;
  if (!t) return <p className="text-sm text-muted">Chưa đủ dữ liệu nến để lập kế hoạch kỹ thuật.</p>;
  return (
    <div className="space-y-4">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <span className={cn("rounded px-2 py-0.5 text-xs font-semibold", t.stage ? STAGE_TONE[t.stage] : "border border-line text-muted")}>{t.stage_label}</span>
          <span className="text-xs text-muted">{t.bottom_label} · {t.bottom_score}/6 dấu hiệu đáy</span>
        </div>
        <p className="mt-2 text-[15px]">{maskText(t.summary)}</p>
        <p className="mt-1 text-xs text-muted">{t.stage_detail}</p>
      </div>

      <Ladder t={t} price={ev.price} />
      <p className="text-xs text-muted">Chấm đen là số nhóm công cụ cùng chỉ vào vùng đó (đường trung bình, Fibonacci, đỉnh đáy cũ, vùng khớp nhiều nhất, Bollinger). Càng nhiều chấm, vùng càng đáng tin.</p>

      <div className="grid gap-3 md:grid-cols-3">
        {t.scenarios.map((s) => (
          <article key={s.name} className={cn("rounded-md border p-3", s.name === "decline" ? "border-lead/40" : s.name === "rebound" ? "border-amber/40" : "border-line")}>
            <h4 className="font-semibold">{s.title}</h4>
            <p className="mt-1 text-xs text-muted">Khi: {maskText(s.trigger)}</p>
            <p className="mt-2 text-sm">{maskText(s.action)}</p>
          </article>
        ))}
      </div>

      <details className="group">
        <summary className="flex min-h-10 cursor-pointer list-none items-center gap-2 text-sm font-medium">
          <ChevronDown size={16} className="transition group-open:rotate-180" aria-hidden />
          Sáu dấu hiệu xác nhận đáy ({t.bottom_score}/6)
        </summary>
        <ul className="mt-2 space-y-1.5 text-sm">
          {t.bottom_checks.map((c) => (
            <li key={c.code} className="flex gap-2">
              {c.met ? <Check size={16} className="mt-0.5 shrink-0 text-ok" aria-label="đạt" /> : <X size={16} className="mt-0.5 shrink-0 text-muted" aria-label="chưa đạt" />}
              <span>{c.label} <span className="num text-xs text-muted">({c.detail})</span></span>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-xs text-muted">0–2: chưa có bằng chứng đáy. 3–4: đáy đang hình thành. 5–6: đáy được xác nhận. Kể cả khi đủ 6, nhịp tăng vẫn có thể thất bại.</p>
      </details>
    </div>
  );
}

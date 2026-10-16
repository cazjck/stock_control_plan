import { fmtInt } from "../lib/format";
import type { SourceShare } from "../lib/types";
import { cn } from "../lib/format";

/** Nguồn dữ liệu của một mã: công ty chứng khoán nào, bao nhiêu cổ phiếu ở mỗi nơi. */
export function SourceTags({ sources, showQty, className }: { sources: SourceShare[]; showQty?: boolean; className?: string }) {
  if (!sources?.length) return null;
  const qty = showQty ?? sources.length > 1;
  return (
    <ul aria-label="Nguồn dữ liệu" className={cn("flex flex-wrap gap-1", className)}>
      {sources.map((s) => (
        <li key={`${s.source}-${s.account}`} title={s.account ? `Tiểu khoản ${s.account}, giá vốn ${fmtInt(s.avg_cost)}` : undefined}
            className="inline-flex items-center gap-1 rounded-sm border border-line bg-paper px-1.5 py-px text-[11px] font-medium text-muted">
          <span className="text-ink">{s.source}</span>
          {qty && <span className="num">{fmtInt(s.quantity)}</span>}
        </li>
      ))}
    </ul>
  );
}

export function SourceTag({ source }: { source: string | null | undefined }) {
  if (!source) return <span className="text-muted">—</span>;
  return <span className="inline-flex rounded-sm border border-line bg-paper px-1.5 py-px text-[11px] font-medium">{source}</span>;
}

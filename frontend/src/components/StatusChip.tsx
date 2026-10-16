import { STATUS } from "../lib/status";
import type { PositionStatus } from "../lib/types";
import { cn } from "../lib/format";

const TONE = {
  lead: "bg-lead text-paper border-lead",
  amber: "bg-amber-soft text-amber border-amber/50",
  ok: "bg-ok-soft text-ok border-ok/40",
  sea: "bg-sea-soft text-sea border-sea/40",
  muted: "bg-transparent text-muted border-line",
} as const;

export function StatusChip({ status, className }: { status: PositionStatus; className?: string }) {
  const m = STATUS[status];
  // Hàng kẹt: viền đỏ, nền đỏ nhạt, để phân biệt với "Chạm cắt lỗ" (đặc) mà không chỉ dựa vào màu
  const tone = status === "TRAPPED" ? "bg-lead-soft text-lead border-lead" : TONE[m.tone];
  return (
    <span title={m.hint} className={cn("inline-flex items-center gap-1.5 whitespace-nowrap rounded-sm border px-2 py-0.5 text-xs font-semibold", tone, className)}>
      <span aria-hidden className="text-[10px] leading-none">{m.glyph}</span>
      {m.label}
    </span>
  );
}

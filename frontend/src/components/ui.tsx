import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "../lib/format";

export function Panel({ children, className, as: Tag = "section" }: { children: ReactNode; className?: string; as?: "section" | "div" | "article" }) {
  return <Tag className={cn("rounded-md border border-line bg-panel", className)}>{children}</Tag>;
}

export function Eyebrow({ children, className }: { children: ReactNode; className?: string }) {
  return <h2 className={cn("eyebrow", className)}>{children}</h2>;
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("animate-pulse rounded-md bg-line/60", className)} />;
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-md border border-dashed border-line px-4 py-8 text-center">
      <p className="display text-lg">{title}</p>
      {children && <p className="mx-auto mt-1 max-w-md text-sm text-muted">{children}</p>}
    </div>
  );
}

const BTN = "inline-flex min-h-10 items-center justify-center gap-2 rounded-md px-3.5 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50";
const VARIANT = {
  primary: "bg-ink text-paper hover:opacity-90",
  secondary: "border border-line bg-panel text-ink hover:bg-sea-soft",
  danger: "bg-lead text-paper hover:opacity-90",
  ghost: "text-muted hover:text-ink hover:bg-sea-soft",
} as const;

export function Button({ variant = "secondary", className, ...p }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: keyof typeof VARIANT }) {
  return <button type="button" className={cn(BTN, VARIANT[variant], className)} {...p} />;
}

export function Field({ label, hint, children, className }: { label: string; hint?: string; children: ReactNode; className?: string }) {
  return (
    <label className={cn("block text-sm", className)}>
      <span className="mb-1 block font-medium">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}

export const inputCls =
  "w-full min-h-10 rounded-md border border-line bg-paper px-3 py-2 text-sm text-ink placeholder:text-muted/70 focus:border-sea";

/** Số liệu có nhãn nhỏ: không có nền màu, không viền trái, chỉ chữ. */
export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "lead" | "ok" | "amber" }) {
  const toneCls = tone === "lead" ? "text-lead" : tone === "ok" ? "text-ok" : tone === "amber" ? "text-amber" : "text-ink";
  return (
    <div className="min-w-0">
      <p className="eyebrow">{label}</p>
      <p className={cn("display text-[1.75rem] leading-tight", toneCls)}>{value}</p>
      {sub && <p className="num text-xs text-muted">{sub}</p>}
    </div>
  );
}

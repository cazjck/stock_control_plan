import { useState } from "react";
import { QueryState } from "./QueryState";
import { Field, Panel, Eyebrow, Stat, inputCls } from "./ui";
import { cn, fmtInt, fmtMoney, fmtPct } from "../lib/format";
import { useDebounced, useSizing } from "../lib/hooks";
import type { SizingPlan, SizingTranche, SizingWarning } from "../lib/types";

const SEVERITY: Record<SizingWarning["severity"], { glyph: string; cls: string; label: string }> = {
  block: { glyph: "■", cls: "border-lead/50 bg-lead-soft text-lead", label: "Không được phép" },
  warn: { glyph: "▲", cls: "border-amber/50 bg-amber-soft text-amber", label: "Lưu ý" },
  info: { glyph: "●", cls: "border-line bg-paper text-muted", label: "Ghi chú" },
};

function Warnings({ list }: { list: SizingWarning[] }) {
  if (!list.length) return null;
  return (
    <ul className="space-y-2" aria-label="Cảnh báo khi mở vị thế">
      {list.map((w) => {
        const s = SEVERITY[w.severity];
        return (
          <li key={w.code} className={cn("flex gap-2 rounded-md border px-3 py-2 text-sm", s.cls)}>
            <span aria-hidden>{s.glyph}</span><span><span className="sr-only">{s.label}: </span>{w.message}</span>
          </li>
        );
      })}
    </ul>
  );
}

function Tranche({ t, price }: { t: SizingTranche; price: number }) {
  const empty = t.quantity === 0;
  return (
    <li className={cn("grid gap-x-4 gap-y-1 py-3 sm:grid-cols-[3.5rem_9rem_minmax(0,1fr)]", (empty || t.likely_skipped) && "opacity-60")}>
      <p className="display text-lg leading-none">Đợt {t.index}</p>
      <p className="num text-sm">
        <span className="font-medium">{empty ? "không đủ lô" : `${fmtInt(t.quantity)} cp`}</span>
        <span className="text-muted"> · {fmtPct(t.pct, 0)}</span>
        {t.index > 1 && t.trigger_price != null && <span className="block text-xs text-muted">từ giá {fmtInt(t.trigger_price)}{t.trigger_price > price ? ` (${fmtPct((t.trigger_price / price - 1) * 100, 1, true)})` : ""}</span>}
        {t.likely_skipped && <span className="block text-xs text-amber">▲ dự kiến bỏ qua</span>}
      </p>
      <p className="text-sm text-muted">{t.condition}</p>
    </li>
  );
}

export function SizingResult({ p }: { p: SizingPlan }) {
  const limitedBy = p.binding === "weight"
    ? `Bị giới hạn bởi tỷ trọng tối đa ${fmtPct(p.max_weight_pct, 0)} vốn (theo rủi ro được ${fmtInt(p.qty_by_risk)} cp)`
    : `Theo mức rủi ro ${fmtPct(p.risk_pct)} vốn (trần tỷ trọng cho phép ${fmtInt(p.qty_by_weight)} cp)`;
  return (
    <div className="space-y-4">
      {!p.allowed && (
        <p role="status" className="rounded-md border border-lead/50 bg-lead-soft px-3 py-2 text-sm font-medium text-lead">
          ■ Luật không cho mở vị thế này lúc này. Con số dưới chỉ để tham khảo.
        </p>
      )}
      <dl className={cn("grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4", !p.allowed && "opacity-70")}>
        <Stat label="Khối lượng kế hoạch" value={`${fmtInt(p.qty_plan)} cp`} sub={p.qty_plan ? `${fmtMoney(p.plan_value)} · ${fmtPct(p.plan_weight_pct, 0)} vốn` : "chưa đủ 1 lô"} />
        <Stat label="Mức cắt lỗ" value={fmtInt(p.stop_price)} sub={`cách ${fmtPct(p.stop_distance_pct)} · ${p.stop_basis}`} />
        <Stat label="Rủi ro nếu chạm cắt lỗ" value={fmtMoney(p.risk_at_stop)} sub={`tối đa ${fmtMoney(p.risk_money)} (${fmtPct(p.risk_pct)} vốn)`} />
        <Stat label="Vốn giao dịch" value={fmtMoney(p.capital)} sub="tiền mặt thực có, không tính margin" />
      </dl>
      {p.qty_plan > 0 && <p className="text-xs text-muted">{limitedBy}. Đây là tổng khối lượng cho cả 4 đợt, làm tròn lô 100.{p.held_quantity > 0 && ` Đang giữ ${fmtInt(p.held_quantity)} cp, cần mua thêm ${fmtInt(p.additional_quantity)} cp.`}</p>}
      <Warnings list={p.warnings} />
      {p.qty_plan > 0 && (
        <div>
          <p className="eyebrow">Chia 4 đợt, chỉ mua thêm khi đang lãi</p>
          <ul className="mt-1 divide-y divide-line">{p.tranches.map((t) => <Tranche key={t.index} t={t} price={p.price} />)}</ul>
          <p className="mt-1 text-xs text-muted">Giá mỗi đợt giả định đợt trước khớp đúng ở giá tối thiểu. Mức cắt lỗ tính lại theo giá vốn trung bình mới sau mỗi đợt, không bao giờ thấp hơn mức cũ.</p>
        </div>
      )}
    </div>
  );
}

/** Máy tính khối lượng mua theo luật 1,5% rủi ro. Chỉ tính, không đặt lệnh. */
export function SizingPanel({ symbol, defaultPrice }: { symbol: string; defaultPrice: number | null }) {
  const [price, setPrice] = useState(defaultPrice ? String(Math.round(defaultPrice)) : "");
  const [stop, setStop] = useState("");
  const p = useDebounced(Number(price));
  const s = useDebounced(Number(stop));
  const q = useSizing(symbol, Number.isFinite(p) ? p : 0, s > 0 ? s : undefined);
  return (
    <Panel className="p-4 sm:p-5">
      <Eyebrow>Khối lượng mua theo luật</Eyebrow>
      <div className="mt-3 grid gap-3 sm:max-w-xl sm:grid-cols-2">
        <Field label="Giá vào dự kiến"><input type="number" inputMode="decimal" min={0} step={100} value={price} onChange={(e) => setPrice(e.target.value)} className={cn(inputCls, "num")} /></Field>
        <Field label="Giá cắt lỗ dự kiến" hint="Để trống: tính theo luật (−7% hoặc 2×ATR, lấy mức gần giá hơn)">
          <input type="number" inputMode="decimal" min={0} step={100} value={stop} placeholder="Tự tính" onChange={(e) => setStop(e.target.value)} className={cn(inputCls, "num")} />
        </Field>
      </div>
      <div className="mt-5">
        {Number(price) > 0 ? <QueryState query={q}>{(d) => <SizingResult p={d} />}</QueryState> : <p className="text-sm text-muted">Nhập giá vào dự kiến để tính.</p>}
      </div>
    </Panel>
  );
}

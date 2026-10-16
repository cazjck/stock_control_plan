import { ChevronDown } from "lucide-react";
import { cn, fmtInt, fmtMoney, fmtPct } from "../lib/format";
import { maskText } from "../lib/privacy";
import { TONE_CLASS } from "../lib/status";
import type { DeleverageOverview, DeleveragePlan as Plan, DeleverageStep, Tone } from "../lib/types";
import { SourceTag } from "./SourceTags";
import { Stat } from "./ui";

const ZONE: Record<string, string> = { safe: "An toàn", watch: "Sát ngưỡng", danger: "Dưới duy trì", breach: "Dưới xử lý", unknown: "Chưa rõ" };
const KIND: Record<DeleverageStep["kind"], string> = {
  lot_rule: "Luật lô mua thêm", stop: "Thủng cắt lỗ", group_b: "Hàng kẹt nhóm B", rotation: "Đảo hàng",
  worst_loss: "Mã lỗ nặng nhất", to_zero: "Trả hết nợ",
};

/** Thanh RTT: vị trí hiện tại, sau giai đoạn 1, ngưỡng duy trì và mục tiêu. */
function RttRail({ p }: { p: Plan }) {
  if (p.ratio_pct == null || p.maintenance_pct == null || p.target_pct == null) return null;
  const after = p.deferred_symbols.length ? p.committed_ratio_after : p.safe_debt_after <= 0 ? null : p.safe_ratio_after;
  const vals = [p.ratio_pct, p.maintenance_pct, p.target_pct, p.liquidation_pct ?? p.maintenance_pct, after ?? p.target_pct];
  const lo = Math.min(...vals) * 0.9, hi = Math.max(...vals) * 1.08;
  const x = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`;
  return (
    <div className="relative mt-3 h-11" aria-hidden>
      <div className="absolute inset-x-0 top-5 h-1.5 rounded-full bg-line" />
      {p.liquidation_pct != null && <div className="absolute top-5 h-1.5 rounded-l-full bg-lead/60" style={{ left: 0, width: x(p.liquidation_pct) }} />}
      <div className="absolute top-5 h-1.5 bg-amber-soft" style={{ left: x(p.liquidation_pct ?? lo), width: `calc(${x(p.maintenance_pct)} - ${x(p.liquidation_pct ?? lo)})` }} />
      <div className="absolute top-5 h-1.5 rounded-r-full bg-ok/40" style={{ left: x(p.target_pct), right: 0 }} />
      {[[p.maintenance_pct, "duy trì"], [p.target_pct, "an toàn"]].map(([v, l]) => (
        <span key={l as string} className="absolute top-4 flex -translate-x-1/2 flex-col items-center" style={{ left: x(v as number) }}>
          <span className="block h-3.5 w-px bg-muted" />
          <span className="num whitespace-nowrap text-[10px] text-muted">{l} {fmtPct(v as number, 0)}</span>
        </span>
      ))}
      <span className="absolute top-0 -translate-x-1/2" style={{ left: x(p.ratio_pct) }}>
        <span className="num block whitespace-nowrap rounded bg-ink px-1 text-[10px] leading-4 text-paper">nay {fmtPct(p.ratio_pct, 1)}</span>
      </span>
      {after != null && after !== p.ratio_pct && (
        <span className="absolute top-0 -translate-x-1/2" style={{ left: x(after) }}>
          <span className="num block whitespace-nowrap rounded bg-ok px-1 text-[10px] leading-4 text-paper">sau {fmtPct(after, 1)}</span>
        </span>
      )}
    </div>
  );
}

function Steps({ steps, caption }: { steps: DeleverageStep[]; caption: string }) {
  return (
    <div className="scroll-x rounded-md border border-line">
      <table className="w-full min-w-[44rem] text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead><tr className="border-b border-line text-left">
          {["", "Bán", "Số lượng", "Giá", "Tiền về", "RTT sau", "Lãi/ngày sau", "Vì sao"].map((h, i) => (
            <th key={h || i} scope="col" className={cn("eyebrow px-3 py-2 font-normal", i >= 2 && i <= 6 && "text-right")}>{h}</th>
          ))}
        </tr></thead>
        <tbody className="divide-y divide-line">
          {steps.map((s, i) => (
            <tr key={`${s.row_id}-${s.kind}-${i}`} className={cn(s.deferred ? "text-muted" : s.reaches_target && i === steps.findIndex((x) => x.reaches_target) && "bg-ok-soft/40")}>
              <td className="num px-3 py-2 text-muted">{i + 1}</td>
              <td className="px-3 py-2 font-semibold">{s.symbol}{s.deferred && <span className="ml-1.5 rounded bg-sea-soft px-1 text-[10px] font-medium text-ink">hoãn: đang gồng</span>}</td>
              <td className="num px-3 py-2 text-right">{fmtInt(s.quantity)}</td>
              <td className="num px-3 py-2 text-right">{fmtInt(s.price)}</td>
              <td className="num px-3 py-2 text-right">{fmtMoney(s.proceeds)}</td>
              <td className="num px-3 py-2 text-right">{s.ratio_after != null ? fmtPct(s.ratio_after, 1) : "hết nợ"}</td>
              <td className="num px-3 py-2 text-right">{fmtMoney(s.interest_per_day_after)}</td>
              <td className="px-3 py-2 text-xs"><span className="font-medium">{KIND[s.kind]}</span><span className="text-muted"> · {maskText(s.reason)}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PlanCard({ p }: { p: Plan }) {
  const tone = (p.zone in TONE_CLASS ? p.zone : "unknown") as Tone;
  return (
    <article className="rounded-md border border-line bg-panel p-4 sm:p-5">
      <header className="flex flex-wrap items-center gap-2">
        <SourceTag source={p.source} />
        <h3 className="font-semibold">{p.label}</h3>
        <span className={cn("text-sm font-medium", TONE_CLASS[tone])}>{ZONE[p.zone] ?? p.zone}</span>
        <span className="num ml-auto text-sm text-muted">nợ {fmtMoney(p.debt)} · lãi {fmtMoney(p.interest_per_day)}/ngày</span>
      </header>
      <RttRail p={p} />
      <p className="mt-3 text-[15px]">{maskText(p.headline)}</p>

      {p.safe_steps.length > 0 && (
        <section className="mt-4">
          <h4 className="eyebrow mb-2">Giai đoạn 1 · làm phiên kế tiếp</h4>
          <Steps steps={p.safe_steps} caption={`Các lệnh bán để ${p.label} về vùng an toàn`} />
        </section>
      )}
      {p.cash_alternative != null && p.cash_alternative > 0 && (
        <p className="mt-2 text-sm text-muted">Thay cho phần bán mã lỗ nặng nhất, có thể nộp thêm khoảng <span className="num text-ink">{fmtMoney(p.cash_alternative)}</span> vào tài khoản này.</p>
      )}
      {p.notes.length > 0 && (
        <ul className="mt-3 space-y-1 text-sm">
          {p.notes.map((n) => <li key={n} className="rounded-md bg-amber-soft px-3 py-1.5 text-amber">{maskText(n)}</li>)}
        </ul>
      )}
      {p.zero_steps.length > 0 && (
        <details className="group mt-4">
          <summary className="flex min-h-10 cursor-pointer list-none items-center gap-2 text-sm font-medium">
            <ChevronDown size={16} className="transition group-open:rotate-180" aria-hidden />
            Giai đoạn 2 · bán tiếp để hết nợ ({p.zero_steps.length} lệnh, tiết kiệm thêm {fmtMoney(p.zero_interest_saved)}/ngày)
          </summary>
          <div className="mt-2"><Steps steps={p.zero_steps} caption={`Các lệnh bán để ${p.label} hết nợ`} /></div>
        </details>
      )}
    </article>
  );
}

/** Mục 5b: lộ trình hạ margin của từng tài khoản. Chỉ khuyến nghị; lệnh đặt ở công ty chứng khoán. */
export function DeleveragePlanView({ o }: { o: DeleverageOverview }) {
  if (!o.plans.length) return <p className="text-sm text-muted">Không có tài khoản nào đang vay margin.</p>;
  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-2 gap-x-6 gap-y-4 lg:grid-cols-4">
        <Stat label="Tài khoản sát ngưỡng" value={`${o.accounts_unsafe}/${o.plans.length}`} tone={o.accounts_unsafe ? "amber" : "ok"} />
        <Stat label="Giai đoạn 1 cần bán" value={fmtMoney(o.safe_sell_value)}
          sub={o.deferred_sell_value ? `hoãn ${fmtMoney(o.deferred_sell_value)} vì đang gồng` : `tiền về ${fmtMoney(o.safe_proceeds)} sau phí, thuế`} />
        <Stat label="Lãi mỗi ngày" value={fmtMoney(o.interest_per_day)} sub={`còn ${fmtMoney(o.interest_after_safe)} sau các lệnh không hoãn`} tone="lead" />
        <Stat label="Tiết kiệm mỗi tháng" value={fmtMoney((o.interest_per_day - o.interest_after_safe) * 30)} sub="nếu làm xong giai đoạn 1" tone="ok" />
      </dl>
      {o.plans.map((p) => <PlanCard key={p.bucket_id} p={p} />)}
      <p className="text-xs text-muted">
        Thứ tự bán theo mục 5b của bộ luật: lô mua thêm tới luật bán, thủng cắt lỗ, hàng kẹt nhóm B, phần đảo hàng, rồi mã lỗ nặng nhất vừa đủ về vùng an toàn.
        Tiền bán trừ khoảng 0,25% phí và thuế rồi trả khoản lãi cao nhất trước. Mỗi công ty tính ký quỹ riêng. Đây là khuyến nghị theo luật bạn đã duyệt, không phải tư vấn đầu tư.
      </p>
    </div>
  );
}

import { QueryState } from "../components/QueryState";
import { SourceTag } from "../components/SourceTags";
import { Empty, Eyebrow, Panel, Stat } from "../components/ui";
import { cn, daysUntil, fmtDate, fmtMoney, fmtPct } from "../lib/format";
import { useMargin, useMarginPlan } from "../lib/hooks";
import { DeleveragePlanView } from "../components/DeleveragePlan";
import { TONE_CLASS } from "../lib/status";
import type { MarginOverview } from "../lib/types";

const ZONE_LABEL: Record<string, string> = { safe: "An toàn", watch: "Theo dõi", danger: "Dưới duy trì", breach: "Dưới giải chấp", unknown: "Chưa rõ" };

const KIND_NOTE: Record<string, string> = {
  collateral_over_debt: "RTT của TCBS = tài sản đảm bảo / dư nợ. Tài sản đảm bảo là tổng số lượng × tỷ lệ tính tài sản × giá tính tài sản (giá thấp hơn giữa giá tham chiếu và giá trần cho vay) của từng mã. Dư nợ là nợ đã giải ngân cộng nợ phí và nợ chờ giải ngân, trừ tiền mặt và tiền chờ về. Ngưỡng: ban đầu 100%, duy trì 85%, xử lý tài sản 80%. Dưới 85% ba ngày làm việc liên tiếp thì bị bán vào ngày thứ ba kể từ thông báo gọi ký quỹ; dưới 80% thì bị bán vào ngày làm việc kế tiếp. Cột giảm tới gọi ký quỹ giả định tài sản đảm bảo giảm đều theo giá; mã đang trên giá trần cho vay thì thực tế còn xa hơn. Cột cần nộp dùng dư nợ gồm cả lãi dồn, nên hơi cao hơn thực tế để an toàn.",
  equity_over_value: "RTT ở đây là vốn chủ trên giá trị tài sản: (giá trị tài sản − nợ) / giá trị tài sản. Cột giảm tới gọi ký quỹ giả định cả nhóm giảm đều theo giá.",
};

function Buckets({ m }: { m: MarginOverview }) {
  if (!m.buckets.length) return <Empty title="Không có nhóm ký quỹ">Tiểu khoản này không có nợ margin, hoặc broker chưa trả về tỷ lệ ký quỹ.</Empty>;
  const kinds = [...new Set(m.buckets.map((x) => x.bucket.ratio_kind))];
  return (
    <>
    <div className="scroll-x rounded-md border border-line bg-panel">
      <table className="w-full min-w-[50rem] text-sm">
        <caption className="sr-only">Tỷ lệ ký quỹ theo nhóm</caption>
        <thead><tr className="border-b border-line text-left">
          {["Nhóm", "Nguồn", "RTT", "Duy trì", "Giải chấp", "Giảm tới gọi ký quỹ", "Cần nộp", "Vùng"].map((h, i) => (
            <th key={h} scope="col" className={cn("eyebrow px-3 py-2.5 font-normal", i > 1 && i < 7 && "text-right")}>{h}</th>
          ))}
        </tr></thead>
        <tbody className="divide-y divide-line">
          {m.buckets.map((x) => (
            <tr key={x.bucket.id}>
              <td className="px-3 py-2.5"><span className="font-medium">{x.bucket.label}</span>
                {x.bucket.scope === "deal" && <span className="eyebrow ml-2">Deal</span>}</td>
              <td className="px-3 py-2.5"><SourceTag source={x.bucket.source} /></td>
              <td className={cn("num px-3 py-2.5 text-right font-medium", TONE_CLASS[x.zone])}>{fmtPct(x.bucket.ratio_pct)}</td>
              <td className="num px-3 py-2.5 text-right">{fmtPct(x.bucket.maintenance_pct, 0)}</td>
              <td className="num px-3 py-2.5 text-right">{fmtPct(x.bucket.liquidation_pct, 0)}</td>
              <td className="num px-3 py-2.5 text-right">{fmtPct(x.drop_to_maintenance_pct)}</td>
              <td className="num px-3 py-2.5 text-right">{x.cash_to_safe ? fmtMoney(x.cash_to_safe) : "—"}</td>
              <td className={cn("px-3 py-2.5", TONE_CLASS[x.zone])}>{ZONE_LABEL[x.zone]}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    <p className="mt-2 max-w-3xl text-xs text-muted">{kinds.map((k) => KIND_NOTE[k]).join(" ")}</p>
    </>
  );
}

function DebtStats({ m }: { m: MarginOverview }) {
  const st = m.stats;
  if (!st) return null;
  const cashToSafe = m.buckets.reduce((x, b) => x + (b.cash_to_safe ?? 0), 0);
  const dueIn = daysUntil(st.next_due_date);
  return (
    <section aria-labelledby="debt" className="space-y-4">
      <h2 id="debt" className="eyebrow">Nợ và lãi</h2>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-5 lg:grid-cols-4">
        <Stat label="Dư nợ gốc" value={fmtMoney(st.principal_remaining)}
              sub={`đã giải ngân ${fmtMoney(st.principal_disbursed)} · đã trả gốc ${fmtMoney(st.principal_paid)}`} />
        <Stat label="Lãi tạm tính đến hôm nay" value={fmtMoney(st.accrued_interest)} sub={`${st.count} khoản vay đang mở`} />
        <Stat label="Tất toán hôm nay" value={fmtMoney(st.payoff_today)} sub="gốc + lãi tạm tính" />
        <Stat label="Tiền cần nộp để an toàn" value={fmtMoney(cashToSafe)} sub="để mọi nhóm ký quỹ về vùng an toàn" />
        <Stat label="Lãi mỗi ngày" value={fmtMoney(st.interest_per_day)}
              sub={st.avg_rate_pct != null ? `lãi suất bình quân ${fmtPct(st.avg_rate_pct)}/năm` : undefined} />
        <Stat label="Lãi mỗi tháng" value={fmtMoney(st.interest_per_month)}
              sub={m.interest_pct_nav_monthly != null ? `bằng ${fmtPct(m.interest_pct_nav_monthly, 2)} tài sản ròng` : "30 ngày, nếu giữ nguyên dư nợ"} />
        <Stat label="Lãi mỗi năm" value={fmtMoney(st.interest_per_year)} sub="nếu giữ nguyên dư nợ" />
        <Stat label="Lãi từ nay tới đáo hạn" value={fmtMoney(st.interest_to_maturity)}
              sub={st.loans_without_due_date ? `chưa tính ${st.loans_without_due_date} khoản chưa có ngày đáo hạn` : "cộng thêm vào lãi tạm tính"} />
        <Stat label="Phải tăng mỗi tháng để bù lãi" tone={(m.breakeven_monthly_pct ?? 0) >= 1 ? "amber" : undefined}
              value={m.breakeven_monthly_pct != null ? fmtPct(m.breakeven_monthly_pct, 2) : "—"}
              sub="cổ phiếu đứng giá là bạn đang lỗ dần phần này" />
        <Stat label="Đáo hạn gần nhất" value={st.next_due_date ? fmtDate(st.next_due_date) : "—"}
              sub={st.next_due_amount != null ? `${fmtMoney(st.next_due_amount)}${dueIn != null ? ` · còn ${dueIn} ngày` : ""}` : undefined} />
        <Stat label="Số ngày vay bình quân" value={st.avg_days_borrowed != null ? `${Math.round(st.avg_days_borrowed)} ngày` : "—"}
              sub="tính theo dư nợ" />
      </dl>
      {m.stats_by_source.length > 1 && <BySource m={m} />}
    </section>
  );
}

/** Số liệu nợ tách theo từng công ty chứng khoán, để biết nên dồn tiền trả nợ ở đâu trước. */
function BySource({ m }: { m: MarginOverview }) {
  const rows = [...m.stats_by_source].sort((a, b) => b.principal_remaining - a.principal_remaining);
  const head = ["Nguồn", "Dư nợ gốc", "Lãi tạm tính", "Tất toán hôm nay", "Lãi mỗi ngày", "Lãi mỗi tháng", "Lãi suất BQ", "Lãi tới đáo hạn", "Đáo hạn gần nhất"];
  return (
    <div className="scroll-x rounded-md border border-line bg-panel">
      <table className="w-full min-w-[60rem] text-sm">
        <caption className="sr-only">Nợ và lãi theo nguồn</caption>
        <thead><tr className="border-b border-line text-left">
          {head.map((h, i) => <th key={h} scope="col" className={cn("eyebrow px-3 py-2.5 font-normal", i > 0 && i < 8 && "text-right")}>{h}</th>)}
        </tr></thead>
        <tbody className="divide-y divide-line">
          {rows.map((r) => (
            <tr key={r.source ?? "?"}>
              <td className="whitespace-nowrap px-3 py-2.5"><SourceTag source={r.source} /> <span className="ml-1 text-xs text-muted">{r.count} khoản</span></td>
              <td className="num whitespace-nowrap px-3 py-2.5 text-right">{fmtMoney(r.principal_remaining)}</td>
              <td className="num whitespace-nowrap px-3 py-2.5 text-right">{fmtMoney(r.accrued_interest)}</td>
              <td className="num whitespace-nowrap px-3 py-2.5 text-right">{fmtMoney(r.payoff_today)}</td>
              <td className="num whitespace-nowrap px-3 py-2.5 text-right">{fmtMoney(r.interest_per_day)}</td>
              <td className="num whitespace-nowrap px-3 py-2.5 text-right">{fmtMoney(r.interest_per_month)}</td>
              <td className="num whitespace-nowrap px-3 py-2.5 text-right">{r.avg_rate_pct != null ? fmtPct(r.avg_rate_pct) : "—"}</td>
              <td className="num whitespace-nowrap px-3 py-2.5 text-right">{fmtMoney(r.interest_to_maturity)}</td>
              <td className="num whitespace-nowrap px-3 py-2.5">{r.next_due_date ? `${fmtDate(r.next_due_date)} · ${fmtMoney(r.next_due_amount)}` : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DueBadge({ date }: { date: string | null | undefined }) {
  const d = daysUntil(date);
  if (d == null) return <span className="text-muted">—</span>;
  const cls = d < 0 ? "bg-lead text-paper" : d <= 1 ? "bg-lead text-paper" : d <= 7 ? "bg-amber-soft text-amber" : "bg-transparent text-muted";
  return <span className={cn("num rounded-sm px-1.5 py-0.5 text-xs font-medium", cls)}>{d < 0 ? `quá ${-d} ngày` : d === 0 ? "hôm nay" : `còn ${d} ngày`}</span>;
}

function Loans({ m }: { m: MarginOverview }) {
  if (!m.loans.length) return <Empty title="Không có khoản vay đang mở" />;
  return (
    <div className="scroll-x rounded-md border border-line bg-panel">
      <table className="w-full min-w-[66rem] text-sm">
        <caption className="sr-only">Các khoản vay margin, xếp theo ngày đáo hạn</caption>
        <thead><tr className="border-b border-line text-left">
          {["Nguồn", "Mã", "Giải ngân", "Đáo hạn", "Đã vay", "Nợ gốc", "Lãi dồn", "Lãi suất", "Lãi mỗi ngày", "Lãi tới đáo hạn"].map((h, i) => (
            <th key={h} scope="col" className={cn("eyebrow px-3 py-2.5 font-normal", i >= 4 && "text-right")}>{h}</th>
          ))}
        </tr></thead>
        <tbody className="divide-y divide-line">
          {m.loans.map((l) => (
            <tr key={l.id}>
              <td className="px-3 py-2.5"><SourceTag source={l.source} /></td>
              <td className="px-3 py-2.5 font-medium">{l.symbol ?? "—"}</td>
              <td className="num px-3 py-2.5">{fmtDate(l.disbursement_date)}</td>
              <td className="px-3 py-2.5">{l.due_date ? <><span className="num mr-2">{fmtDate(l.due_date)}</span><DueBadge date={l.due_date} /></> : <span className="text-muted">chưa nhập</span>}</td>
              <td className="num px-3 py-2.5 text-right">{l.days_borrowed != null ? `${l.days_borrowed} ngày` : "—"}</td>
              <td className="num px-3 py-2.5 text-right">{fmtMoney(l.remaining_principal)}</td>
              <td className="num px-3 py-2.5 text-right">{fmtMoney(l.accrued_interest)}</td>
              <td className="num px-3 py-2.5 text-right">{l.annual_rate_pct != null ? fmtPct(l.annual_rate_pct) : "—"}</td>
              <td className="num px-3 py-2.5 text-right">{fmtMoney(l.interest_per_day)}</td>
              <td className="num px-3 py-2.5 text-right">{l.interest_to_maturity != null ? fmtMoney(l.interest_to_maturity) : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Maturity({ m }: { m: MarginOverview }) {
  const max = Math.max(1, ...m.maturity.map((x) => x.amount));
  return (
    <ul className="space-y-2.5">
      {m.maturity.map((x) => (
        <li key={x.label}>
          <div className="flex items-baseline justify-between text-sm">
            <span className={cn(x.label === "Quá hạn" && x.count > 0 && "font-medium text-lead")}>{x.label}</span>
            <span className="num text-muted">{x.count > 0 ? `${x.count} khoản · ${fmtMoney(x.amount)}` : "—"}</span>
          </div>
          <div className="mt-1 h-2 rounded-full bg-line" aria-hidden>
            <div className={cn("h-full rounded-full", x.label === "Quá hạn" ? "bg-lead" : x.label === "Trong 7 ngày" ? "bg-amber-fill" : "bg-sea")}
                 style={{ width: `${(x.amount / max) * 100}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

function PlanSection() {
  const q = useMarginPlan();
  return (
    <section aria-labelledby="plan">
      <h2 id="plan" className="eyebrow mb-2">Kế hoạch hạ margin</h2>
      <QueryState query={q}>{(o) => <DeleveragePlanView o={o} />}</QueryState>
    </section>
  );
}

export default function Margin() {
  const q = useMargin();
  return (
    <>
      <h1 className="display mb-4 text-3xl">Ký quỹ và nợ</h1>
      <QueryState query={q}>
        {(m) => (
          <div className="space-y-7">
            {m.total_debt > 0 && <PlanSection />}
            {m.stats ? <DebtStats m={m} /> : (
              <dl className="grid grid-cols-2 gap-x-6 gap-y-4 lg:grid-cols-4">
                <Stat label="Tổng dư nợ" value={fmtMoney(m.total_debt)} />
                <Stat label="Tổng tiền cần nộp" value={fmtMoney(m.buckets.reduce((s, b) => s + (b.cash_to_safe ?? 0), 0))} sub="để mọi nhóm về vùng an toàn" />
              </dl>
            )}
            <section aria-labelledby="b"><Eyebrow>Tỷ lệ ký quỹ</Eyebrow><div id="b" className="mt-2"><Buckets m={m} /></div></section>
            <section aria-labelledby="l"><Eyebrow>Các khoản vay</Eyebrow><div id="l" className="mt-2"><Loans m={m} /></div></section>
            <Panel className="max-w-xl p-4 sm:p-5"><Eyebrow>Lịch đáo hạn</Eyebrow><div className="mt-3"><Maturity m={m} /></div></Panel>
          </div>
        )}
      </QueryState>
    </>
  );
}

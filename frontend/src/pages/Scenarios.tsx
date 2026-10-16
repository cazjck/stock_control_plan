import { useMemo, useState } from "react";
import { DraftGauge } from "../components/DraftGauge";
import { ErrorState, QueryState } from "../components/QueryState";
import { Button, Empty, Eyebrow, Field, Panel, Skeleton, inputCls } from "../components/ui";
import { cn, fmtInt, fmtMoney, fmtPct, fmtPnlPct, fmtSigned } from "../lib/format";
import { useDebounced, usePositions, useScenario } from "../lib/hooks";
import { mergedRows } from "../lib/group";
import { clampQty, delta, EMPTY_INPUT, focusOf, isUnchanged, toRequest, type ScenarioInput } from "../lib/scenario";
import { TONE_CLASS } from "../lib/status";
import type { PositionEval, ScenarioResult, ScenarioState } from "../lib/types";
import { verdictFor } from "../lib/verdict";

const PRESETS = [0, 5, 10, 15];

function Controls({ input, setInput, positions }: { input: ScenarioInput; setInput: (i: ScenarioInput) => void; positions: PositionEval[] }) {
  const setSell = (symbol: string, q: number) => setInput({ ...input, sells: { ...input.sells, [symbol]: q } });
  return (
    <div className="space-y-6">
      <section aria-labelledby="drop">
        <div className="flex items-baseline justify-between">
          <Eyebrow>Thị trường giảm</Eyebrow>
          <output id="drop" htmlFor="drop-range" className="display text-3xl leading-none text-lead">
            {input.dropPct > 0 ? `−${input.dropPct}%` : "Không giảm"}
          </output>
        </div>
        <input id="drop-range" type="range" min={0} max={30} step={1} value={input.dropPct} aria-labelledby="drop"
               aria-valuetext={input.dropPct > 0 ? `giảm ${input.dropPct} phần trăm` : "không giảm"}
               onChange={(e) => setInput({ ...input, dropPct: Number(e.target.value) })}
               className="mt-3 h-10 w-full cursor-pointer accent-sea" />
        <div role="group" aria-label="Mức giảm có sẵn" className="mt-1 flex gap-2">
          {PRESETS.map((p) => (
            <button key={p} type="button" aria-pressed={input.dropPct === p} onClick={() => setInput({ ...input, dropPct: p })}
              className={cn("num min-h-10 flex-1 rounded-md border text-sm font-medium", input.dropPct === p ? "border-ink bg-ink text-paper" : "border-line bg-panel hover:bg-sea-soft")}>
              {p === 0 ? "Không" : `−${p}%`}
            </button>
          ))}
        </div>
        <p className="mt-2 text-xs text-muted">Mọi mã giảm cùng mức. Chưa tính biên độ ±7% mỗi phiên của HOSE.</p>
      </section>

      <section aria-labelledby="sell">
        <Eyebrow>Bán thử</Eyebrow>
        {positions.length === 0 ? (
          <p id="sell" className="mt-2 text-sm text-muted">Tài khoản không có cổ phiếu để bán thử.</p>
        ) : (
          <ul id="sell" className="mt-2 divide-y divide-line rounded-md border border-line bg-panel">
            {positions.map((p) => {
              const q = input.sells[p.symbol] ?? 0;
              return (
                <li key={p.symbol} className="flex items-center gap-2 px-3 py-2">
                  <div className="min-w-0 flex-1">
                    <p className="display text-lg leading-none">{p.symbol}</p>
                    <p className="num text-xs text-muted">giữ {fmtInt(p.quantity)} · {fmtPnlPct(p.pnl_pct)}</p>
                  </div>
                  <input type="number" inputMode="numeric" min={0} max={p.quantity} step={100} value={q || ""} placeholder="0"
                         aria-label={`Số cổ phiếu ${p.symbol} bán thử`} className={cn(inputCls, "num w-24! text-right")}
                         onChange={(e) => setSell(p.symbol, clampQty(Number(e.target.value), p.quantity))} />
                  <Button variant="ghost" className="min-w-14 px-2" aria-pressed={q === p.quantity} aria-label={`Bán hết ${p.symbol}`}
                          onClick={() => setSell(p.symbol, q === p.quantity ? 0 : p.quantity)}>Hết</Button>
                </li>
              );
            })}
          </ul>
        )}
        <p className="mt-2 text-xs text-muted">Bán ở giá sau khi giảm. Tiền bán dùng trả nợ margin, bỏ qua phí và thuế.</p>
      </section>

      <section>
        <Field label="Nộp thêm tiền (triệu đồng)" hint="Dùng trả nợ margin, ưu tiên nhóm cần nhiều tiền nhất để về vùng an toàn.">
          <input type="number" inputMode="decimal" min={0} step={5} value={input.cashMillions || ""} placeholder="0" className={cn(inputCls, "num max-w-48")}
                 onChange={(e) => setInput({ ...input, cashMillions: Math.max(0, Number(e.target.value)) })} />
        </Field>
      </section>

      <Button onClick={() => setInput(EMPTY_INPUT)} disabled={isUnchanged(input)}>Đặt lại về hiện tại</Button>
    </div>
  );
}

function GaugeColumn({ title, state }: { title: string; state: ScenarioState }) {
  const f = focusOf(state);
  const b = f?.bucket;
  return (
    <div className="flex flex-col items-center">
      <p className="eyebrow mb-1">{title}</p>
      <DraftGauge ratio={b?.ratio_pct} maintenance={b?.maintenance_pct} liquidation={b?.liquidation_pct} liquidationLabel={b?.ratio_kind === "collateral_over_debt" ? "xử lý" : "giải chấp"} safeTarget={f?.safe_target_pct} height={260} />
    </div>
  );
}

type Row = { label: string; before: string; after: string; change: string | null; good?: "up" | "down" | null; d: number | null };

function rows(r: ScenarioResult): Row[] {
  const bf = focusOf(r.before), af = focusOf(r.after);
  const money = (n: number | null | undefined) => fmtMoney(n);
  const out: Row[] = [
    { label: "RTT nhóm sát ngưỡng", before: fmtPct(bf?.bucket.ratio_pct), after: fmtPct(af?.bucket.ratio_pct), good: "up",
      d: delta(bf?.bucket.ratio_pct, af?.bucket.ratio_pct), change: null },
    { label: "Giảm bao nhiêu nữa thì bị gọi ký quỹ", before: fmtPct(bf?.drop_to_maintenance_pct), after: fmtPct(af?.drop_to_maintenance_pct), good: "up",
      d: delta(bf?.drop_to_maintenance_pct, af?.drop_to_maintenance_pct), change: null },
    { label: "Tiền còn cần nộp để an toàn", before: r.before.cash_needed ? money(r.before.cash_needed) : "Không cần", after: r.after.cash_needed ? money(r.after.cash_needed) : "Không cần",
      good: "down", d: delta(r.before.cash_needed, r.after.cash_needed), change: null },
    { label: "Lãi lỗ chưa thực hiện", before: fmtSigned(r.before.unrealized_pnl), after: fmtSigned(r.after.unrealized_pnl), good: "up",
      d: delta(r.before.unrealized_pnl, r.after.unrealized_pnl), change: null },
    { label: "Lãi lỗ đã thực hiện (phần bán thử)", before: "—", after: fmtSigned(r.realized_pnl), good: null, d: null, change: null },
    { label: "Lãi vay mỗi ngày", before: money(r.before.interest_per_day), after: money(r.after.interest_per_day), good: "down",
      d: delta(r.before.interest_per_day, r.after.interest_per_day), change: null },
    { label: "Dư nợ", before: money(r.before.debt), after: money(r.after.debt), good: "down", d: delta(r.before.debt, r.after.debt), change: null },
    { label: "Tài sản ròng (NAV)", before: money(r.before.nav), after: money(r.after.nav), good: "up", d: delta(r.before.nav, r.after.nav), change: null },
  ];
  return out.map((x) => ({
    ...x,
    change: x.d == null || Math.abs(x.d) < 1e-9 ? null
      : x.label.startsWith("RTT") || x.label.startsWith("Giảm bao nhiêu") ? fmtPct(x.d, 1, true).replace("%", " điểm") : fmtSigned(x.d),
  }));
}

function Comparison({ r }: { r: ScenarioResult }) {
  return (
    <div className="scroll-x rounded-md border border-line bg-panel">
      <table className="w-full min-w-[30rem] text-sm">
        <caption className="sr-only">So sánh trước và sau kịch bản</caption>
        <thead><tr className="border-b border-line text-left">
          <th scope="col" className="eyebrow px-3 py-2.5 font-normal">Chỉ số</th>
          {["Trước", "Sau", "Chênh"].map((h) => <th key={h} scope="col" className="eyebrow px-3 py-2.5 text-right font-normal">{h}</th>)}
        </tr></thead>
        <tbody className="divide-y divide-line">
          {rows(r).map((x) => {
            const better = x.d == null || x.d === 0 || !x.good ? null : (x.d > 0) === (x.good === "up");
            return (
              <tr key={x.label}>
                <th scope="row" className="px-3 py-2.5 text-left font-normal">{x.label}</th>
                <td className="num px-3 py-2.5 text-right text-muted">{x.before}</td>
                <td className="num px-3 py-2.5 text-right font-medium">{x.after}</td>
                <td className={cn("num px-3 py-2.5 text-right text-xs", better == null ? "text-muted" : better ? "text-ok" : "text-lead")}>
                  {x.change == null ? "—" : `${better == null ? "" : better ? "▲ " : "▼ "}${x.change}`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function OtherBuckets({ r }: { r: ScenarioResult }) {
  if (r.after.buckets.length < 2) return null;
  const before = new Map(r.before.buckets.map((m) => [m.bucket.id, m]));
  return (
    <div className="mt-5 border-t border-line pt-4">
      <p className="eyebrow mb-2">Từng nhóm ký quỹ ({r.after.buckets.length})</p>
      <ul className="divide-y divide-line text-sm">
        {r.after.buckets.map((m) => (
          <li key={m.bucket.id} className="flex items-center justify-between gap-3 py-1.5">
            <span className="truncate">{m.bucket.label}</span>
            <span className={cn("num shrink-0", TONE_CLASS[m.zone])}>{fmtPct(before.get(m.bucket.id)?.bucket.ratio_pct)} → {fmtPct(m.bucket.ratio_pct)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ScenarioResults({ r, pending }: { r: ScenarioResult; pending: boolean }) {
  const v = verdictFor(focusOf(r.after));
  const hasMargin = r.after.buckets.length > 0;
  return (
    <div className={cn("space-y-5 transition-opacity", pending && "opacity-60")} aria-busy={pending}>
      <Panel className="p-4 sm:p-6">
        {hasMargin ? (
          <div className="flex flex-col gap-6 sm:flex-row sm:items-start">
            <div className="flex flex-wrap justify-center gap-x-4 gap-y-2 sm:gap-x-6">
              <GaugeColumn title="Trước" state={r.before} />
              <GaugeColumn title="Sau" state={r.after} />
            </div>
            <div className="min-w-0 flex-1" aria-live="polite">
              <Eyebrow>Kết quả</Eyebrow>
              <p className={cn("display mt-1 text-[2rem] leading-[1.05] sm:text-4xl", TONE_CLASS[v.tone])}>{v.headline}</p>
              <p className="mt-3 max-w-prose text-[15px]">{v.detail}</p>
            </div>
          </div>
        ) : (
          <Empty title="Tài khoản này không có nợ margin">Không có RTT để mô phỏng. Bảng dưới vẫn cho thấy lãi lỗ và tài sản ròng sau kịch bản.</Empty>
        )}
        <OtherBuckets r={r} />
      </Panel>

      {r.warnings.length > 0 && (
        <ul className="space-y-2" aria-label="Cảnh báo của kịch bản">
          {r.warnings.map((w) => (
            <li key={w} className="flex gap-2 rounded-md border border-amber/50 bg-amber-soft px-3 py-2 text-sm text-amber"><span aria-hidden>▲</span><span>{w}</span></li>
          ))}
        </ul>
      )}
      <Comparison r={r} />
      <p className="text-xs text-muted">
        Chỉ tính toán trên số liệu hiện có, không gọi broker và không lưu gì. RTT tính đúng cách đo của từng công ty như trang Ký quỹ: TCBS là tài sản đảm bảo / dư nợ, SSI và VPS là (giá trị cổ phiếu − nợ) / giá trị cổ phiếu.
      </p>
    </div>
  );
}

export default function Scenarios() {
  const [input, setInput] = useState<ScenarioInput>(EMPTY_INPUT);
  const positions = usePositions();
  const body = useDebounced(useMemo(() => toRequest(input), [input]));
  const q = useScenario(body);
  return (
    <>
      <h1 className="display mb-1 text-3xl">Kịch bản giả định</h1>
      <p className="mb-5 max-w-2xl text-sm text-muted">Thử trước khi chuyện xảy ra: thị trường giảm, bán bớt một mã, hay nộp thêm tiền thì RTT và lãi vay thay đổi thế nào. Chỉ tính toán, không đặt lệnh.</p>
      <div className="grid gap-6 lg:grid-cols-[21rem_minmax(0,1fr)]">
        <Panel className="p-4 sm:p-5">
          <QueryState query={positions} skeleton={<Skeleton className="h-96" />}>
            {(d) => <Controls input={input} setInput={setInput} positions={mergedRows(d.positions).sort((a, b) => b.market_value - a.market_value)} />}
          </QueryState>
        </Panel>
        <div className="min-w-0">
          {q.isError && !q.data ? <ErrorState error={q.error} onRetry={() => void q.refetch()} />
            : q.data ? (
              <>
                {q.isError && <p role="alert" className="mb-3 rounded-md border border-lead/50 bg-lead-soft px-3 py-2 text-sm text-lead">{q.error.message}</p>}
                <ScenarioResults r={q.data} pending={q.isFetching || JSON.stringify(body) !== JSON.stringify(toRequest(input))} />
              </>
            )
            : <div className="space-y-3"><Skeleton className="h-72" /><Skeleton className="h-56" /></div>}
        </div>
      </div>
    </>
  );
}

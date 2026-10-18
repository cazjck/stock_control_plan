import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { ChartPanel } from "../components/ChartPanel";
import { PlanForm } from "../components/PlanForm";
import { QueryState } from "../components/QueryState";
import { SizingPanel } from "../components/SizingPanel";
import { SourceTags } from "../components/SourceTags";
import { StatusChip } from "../components/StatusChip";
import { TakeProfitPanel } from "../components/TakeProfitPanel";
import { LotsPanel } from "../components/LotsPanel";
import { RotationPanel } from "../components/RotationPanel";
import { HoldPanel } from "../components/HoldPanel";
import { TechPlanPanel } from "../components/TechPlanPanel";
import { useSelection } from "../lib/selection";
import { Eyebrow, Panel, Stat } from "../components/ui";
import { cn, fmtInt, fmtMoney, fmtPct, fmtPnlPct, fmtSigned, pnlStatTone, pnlTone } from "../lib/format";
import { maskText } from "../lib/privacy";
import { useChart } from "../lib/hooks";
import { groupBySymbol } from "../lib/group";
import type { ChartResponse, PositionEval } from "../lib/types";

function Indicators({ ev }: { ev: PositionEval }) {
  const i = ev.indicators;
  const rows: [string, string, boolean?][] = [
    ["RSI14", i.rsi14 != null ? i.rsi14.toFixed(0) : "—", (i.rsi14 ?? 50) < 40],
    ["Cách SMA20", fmtPct(i.close_vs_sma20_pct, 1, true), (i.close_vs_sma20_pct ?? 0) < 0],
    ["ATR14", i.atr14_pct != null ? fmtPct(i.atr14_pct) + " giá" : "—"],
    ["SMA20", fmtInt(i.sma20)], ["SMA50", fmtInt(i.sma50)],
    ["MACD histogram", i.macd_hist != null ? i.macd_hist.toFixed(2) : "—", (i.macd_hist ?? 0) < 0],
    ["KL so với TB20", i.volume_ratio != null ? `${i.volume_ratio.toFixed(2)}×` : "—"],
    ["Đáy 20 phiên", fmtInt(i.low20)], ["Đỉnh 20 phiên", fmtInt(i.high20)],
  ];
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
      {rows.map(([k, v, warn]) => (
        <div key={k}><dt className="eyebrow">{k}</dt><dd className={cn("num text-base", warn && "text-amber")}>{v}</dd></div>
      ))}
    </dl>
  );
}

function SourceTabs({ rows, current }: { rows: PositionEval[]; current: string }) {
  const [, setParams] = useSearchParams();
  const g = groupBySymbol(rows)[0];
  return (
    <div className="mt-3 space-y-2">
      <p className="num text-sm text-muted">
        Nắm ở {rows.length} nguồn, cộng {fmtInt(g.quantity)} cp · vốn bình quân {fmtInt(g.avg_cost)} ·{" "}
        <span className={pnlTone(g.pnl)}>{fmtPnlPct(g.pnl_pct ?? 0)}</span>{" "}
        · {fmtPct(g.weight_pct, 0)} danh mục
      </p>
      <div role="tablist" aria-label="Xem theo nguồn" className="flex flex-wrap gap-1.5">
        {rows.map((p) => {
          const on = p.row_id === current;
          return (
            <button key={p.row_id} type="button" role="tab" aria-selected={on}
              onClick={() => setParams({ row: p.row_id }, { replace: true })}
              className={cn("min-h-9 rounded-md border px-3 text-sm font-medium", on ? "border-ink bg-ink text-paper" : "border-line bg-panel")}>
              {p.source ?? p.row_id} <span className="num font-normal opacity-80">{fmtInt(p.quantity)} cp · {fmtPnlPct(p.pnl_pct)}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function Body({ symbol, data, interval, setInterval }: { symbol: string; data: ChartResponse; interval: string; setInterval: (s: string) => void }) {
  const ev = data.evaluation;
  const { sel } = useSelection();
  const broker = sel.broker;
  const pnlTone = pnlStatTone(ev?.pnl);
  return (
    <div className="space-y-6">
      <div>
        <Link to="/positions" className="mb-2 inline-flex min-h-9 items-center gap-1.5 text-sm text-muted hover:text-ink"><ArrowLeft size={15} aria-hidden /> Danh mục</Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="display text-5xl leading-none">{symbol}</h1>
          {ev && <StatusChip status={ev.status} className="text-sm" />}
          {ev?.mode === "dca" && <span className="eyebrow">DCA</span>}
        </div>
        {ev && (data.evaluations?.length ?? 0) > 1
          ? <SourceTabs rows={data.evaluations!} current={ev.row_id} />
          : ev && <SourceTags sources={ev.sources} showQty className="mt-2" />}
        {ev ? (
          <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
            <Stat label="Giá" value={fmtInt(ev.price)} sub={`vốn ${fmtInt(ev.avg_cost)}`} />
            <Stat label="Lãi lỗ" value={fmtPnlPct(ev.pnl_pct)} sub={fmtSigned(ev.pnl)} tone={pnlTone} />
            <Stat label="Giá trị" value={fmtMoney(ev.market_value)} sub={`${fmtInt(ev.quantity)} cp · ${fmtPct(ev.weight_pct, 0)} danh mục`} />
            <Stat label="Rủi ro tới mức cắt lỗ" value={ev.risk_to_stop_value != null ? fmtMoney(ev.risk_to_stop_value) : "—"} sub={ev.distance_to_stop_pct != null ? `cách ${fmtPct(ev.distance_to_stop_pct)}` : "chưa có mức cắt lỗ"} />
          </dl>
        ) : <p className="mt-2 text-sm text-muted">Mã này không nằm trong danh mục hiện tại, chỉ xem biểu đồ.</p>}
        {ev?.margin_call_price != null && (
          <p className={cn("mt-3 rounded-md px-3 py-2 text-sm", (ev.margin_call_distance_pct ?? -100) > -5 ? "bg-lead-soft text-lead" : "bg-sea-soft/50")}>
            Tài khoản{ev.source ? ` ${ev.source}` : ""} bị gọi ký quỹ nếu {symbol} đóng cửa dưới{" "}
            <span className="num font-semibold">{fmtInt(ev.margin_call_price)}</span> ({fmtPct(ev.margin_call_distance_pct ?? 0, 1, true)})
            {ev.liquidation_price != null && <>, bị bán xử lý dưới <span className="num font-semibold">{fmtInt(ev.liquidation_price)}</span></>}.
            <span className="block text-xs opacity-80">Giả định các mã khác trong tài khoản đứng giá.</span>
          </p>
        )}
      </div>

      <Panel className="p-3 sm:p-4">
        <div className="mb-2 flex items-center justify-between">
          <Eyebrow>Biểu đồ</Eyebrow>
          <div role="group" aria-label="Khung thời gian" className="flex gap-1">
            {[["1D", "Ngày"], ["1W", "Tuần"]].map(([v, l]) => (
              <button key={v} type="button" aria-pressed={interval === v} onClick={() => setInterval(v)}
                className={cn("min-h-9 rounded-md border px-3 text-sm font-medium", interval === v ? "border-ink bg-ink text-paper" : "border-line")}>{l}</button>
            ))}
          </div>
        </div>
        <ChartPanel data={data} levels={[
          ...(ev?.technical?.sell_zones ?? []).map((z, i) => ({ price: z.low, title: `Bán đợt ${i + 1}`, kind: "sell" as const })),
          ...(ev?.technical?.invalidation != null ? [{ price: ev.technical.invalidation, title: "Vô hiệu", kind: "invalid" as const }] : []),
        ]} />
      </Panel>

      {ev?.technical && (
        <Panel className="p-4 sm:p-5"><Eyebrow>Dự định theo kỹ thuật</Eyebrow><div className="mt-2"><TechPlanPanel ev={ev} /></div></Panel>
      )}

      {ev && (ev.hold || ev.pnl_pct < 0) && (
        <Panel className="p-4 sm:p-5"><Eyebrow>Quyết định gồng</Eyebrow><div className="mt-2"><HoldPanel key={ev.row_id} ev={ev} /></div></Panel>
      )}

      {ev?.rotation && (
        <Panel className="p-4 sm:p-5"><Eyebrow>Đảo hàng khi hồi</Eyebrow><div className="mt-2"><RotationPanel key={ev.row_id} ev={ev} /></div></Panel>
      )}

      {ev && (
        <Panel className="p-4 sm:p-5"><Eyebrow>Các lần mua</Eyebrow><div className="mt-2"><LotsPanel key={ev.row_id} ev={ev} broker={broker} /></div></Panel>
      )}

      <SizingPanel key={symbol} symbol={symbol} defaultPrice={ev?.price ?? data.candles.at(-1)?.close ?? null} />


      {ev && (
        <div className="grid gap-6 lg:grid-cols-2">
          <Panel className="p-4 sm:p-5">
            <Eyebrow>Việc cần làm</Eyebrow>
            <ul className="mt-2 space-y-2">{ev.actions.map((a) => <li key={a} className="text-[15px]">{maskText(a)}</li>)}</ul>
            <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 border-t border-line pt-4">
              <div><dt className="eyebrow">Mức cắt lỗ</dt><dd className="num text-lg">{ev.stop_level != null ? fmtInt(ev.stop_level) : "—"}</dd><dd className="text-xs text-muted">{ev.stop_basis}</dd></div>
              <div><dt className="eyebrow">Đỉnh lãi từng đạt</dt><dd className="num text-lg">{fmtPct(ev.peak_gain_pct, 1, true)}</dd>
                <dd className="text-xs text-muted">{ev.peak_is_proxy ? "Ước tính theo 20 phiên gần nhất. Khai báo ngày mua để chính xác hơn." : "Tính từ ngày mua đã khai báo."}</dd></div>
            </dl>
            {ev.flags.includes("intraday") && <p className="mt-3 rounded-md bg-amber-soft px-3 py-2 text-sm text-amber">Đang trong phiên. Luật cắt lỗ tính theo giá đóng cửa, chỉ bán nếu cuối phiên giá vẫn dưới mức này.</p>}
          </Panel>
          <Panel className="p-4 sm:p-5"><Eyebrow>Kế hoạch chốt lời</Eyebrow><div className="mt-2"><TakeProfitPanel plan={ev.take_profit} /></div></Panel>
          <Panel className="p-4 sm:p-5"><Eyebrow>Chỉ báo</Eyebrow><div className="mt-3"><Indicators ev={ev} /></div></Panel>
          <Panel className="p-4 sm:p-5"><Eyebrow>Kế hoạch của bạn</Eyebrow><div className="mt-3"><PlanForm key={ev.row_id} ev={ev} /></div></Panel>
        </div>
      )}
    </div>
  );
}

export default function SymbolPage() {
  const { symbol = "" } = useParams();
  const [interval, setInterval] = useState("1D");
  const [params] = useSearchParams();
  const q = useChart(symbol.toUpperCase(), interval, params.get("row") ?? undefined);
  return <QueryState query={q}>{(d) => <Body symbol={symbol.toUpperCase()} data={d} interval={interval} setInterval={setInterval} />}</QueryState>;
}

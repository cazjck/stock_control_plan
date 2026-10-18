import { Fragment, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { QueryState } from "../components/QueryState";
import { SourceTags } from "../components/SourceTags";
import { StatusChip } from "../components/StatusChip";
import { Empty, Panel } from "../components/ui";
import { cn, fmtInt, fmtMoney, fmtPct, fmtPnlPct, fmtSigned, pnlTone } from "../lib/format";
import { maskText } from "../lib/privacy";
import { usePositions } from "../lib/hooks";
import { STATUS, STATUS_ORDER } from "../lib/status";
import type { PositionEval, PositionStatus } from "../lib/types";
import { groupBySymbol, symbolLink, type SymbolGroup } from "../lib/group";

type SortKey = "urgency" | "pnl" | "weight" | "symbol";
const SORTS: Record<SortKey, { label: string; fn: (a: SymbolGroup, b: SymbolGroup) => number }> = {
  urgency: { label: "Mức khẩn", fn: (a, b) => b.urgency - a.urgency },
  pnl: { label: "Lãi lỗ thấp nhất", fn: (a, b) => (a.pnl_pct ?? 0) - (b.pnl_pct ?? 0) },
  weight: { label: "Tỷ trọng lớn nhất", fn: (a, b) => b.weight_pct - a.weight_pct },
  symbol: { label: "Mã", fn: (a, b) => a.symbol.localeCompare(b.symbol) },
};

const pnlCls = pnlTone;

function Headroom({ p }: { p: PositionEval }) {
  if (p.stop_level == null || p.distance_to_stop_pct == null) {
    return <span className="text-xs text-muted">{p.status === "TRAPPED" ? "Theo giao thức hàng kẹt" : "Chưa có mức cắt lỗ"}</span>;
  }
  const d = p.distance_to_stop_pct;
  const tone = d < 0 ? "bg-lead" : d < 3 ? "bg-lead" : d < 8 ? "bg-amber-fill" : "bg-ok";
  return (
    <div className="min-w-24">
      <div className="h-1.5 w-full rounded-full bg-line" aria-hidden>
        <div className={cn("h-full rounded-full", tone)} style={{ width: `${Math.max(3, Math.min(100, (Math.max(d, 0) / 20) * 100))}%` }} />
      </div>
      <p className="num mt-1 text-xs text-muted">
        {d < 0 ? `đã thủng ${fmtPct(-d)}` : `cách ${fmtPct(d)}`} · {fmtInt(p.stop_level)}
      </p>
    </div>
  );
}

function MarginCallHint({ p, className }: { p: PositionEval; className?: string }) {
  if (p.margin_call_price == null || p.margin_call_distance_pct == null) return null;
  const near = p.margin_call_distance_pct > -5;
  return (
    <p className={cn("num text-xs", near ? "font-semibold text-lead" : "text-muted", className)}>
      Gọi ký quỹ nếu dưới {fmtInt(p.margin_call_price)} ({fmtPct(p.margin_call_distance_pct, 1, true)})
    </p>
  );
}

function HoldHint({ p, className }: { p: PositionEval; className?: string }) {
  const h = p.hold;
  if (!h) return null;
  const exit = h.state === "exit_price" || h.state === "exit_margin" || h.state === "review";
  const label = { holding: "Đang gồng", restructure: "Gồng: tới lúc cơ cấu", review: "Gồng: tới ngày xem lại",
    exit_margin: "Gồng: chạm sàn ký quỹ", exit_price: "Gồng: thủng giá thoát" }[h.state];
  return (
    <p className={cn("text-xs font-medium", exit ? "text-lead" : "text-muted", className)}>
      {label}{h.state === "holding" && h.distance_to_exit_pct != null ? ` · cách giá thoát ${fmtPct(h.distance_to_exit_pct, 1)}` : ""}
    </p>
  );
}

function RotationHint({ p, className }: { p: PositionEval; className?: string }) {
  const r = p.rotation;
  if (!r || (r.level !== "sell" && r.level !== "rebuy")) return null;
  return (
    <p className={cn("text-xs font-medium", r.level === "sell" ? "text-amber" : "text-ok", className)}>
      Đảo hàng: {r.level === "sell" ? `bán ${fmtInt(r.sell_qty)} cp vào nhịp hồi` : `mua lại ${fmtInt(r.rebuy_qty)} cp`}
    </p>
  );
}

function NextTarget({ p, className }: { p: PositionEval; className?: string }) {
  const t = p.take_profit?.next_target;
  if (!t) return null;
  return (
    <p className={cn("num text-xs text-muted", className)}>
      Chốt lời tiếp theo {t.label}: <span className="text-ink">{fmtInt(t.price)}</span> (còn {fmtPct(t.distance_pct)})
    </p>
  );
}

function RowBody({ p }: { p: PositionEval }) {
  return (
    <>
      <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2.5">
        <div>
          <p className="eyebrow">Giá</p>
          <p className="num text-base">{fmtInt(p.price)}</p>
          <p className="num text-xs text-muted">vốn {fmtInt(p.avg_cost)} · {fmtInt(p.quantity)} cp</p>
        </div>
        <div>
          <p className="eyebrow">Lãi lỗ</p>
          <p className={cn("num text-base font-medium", pnlCls(p.pnl_pct))}>{fmtPnlPct(p.pnl_pct)}</p>
          <p className={cn("num text-xs", pnlCls(p.pnl))}>{fmtSigned(p.pnl)}</p>
        </div>
      </div>
      <div className="mt-3"><Headroom p={p} /></div>
      <NextTarget p={p} className="mt-2" />
      <RotationHint p={p} className="mt-1" />
      <HoldHint p={p} className="mt-1" />
      <MarginCallHint p={p} className="mt-1" />
      {p.status !== "SAFE" && p.actions[0] && <p className="mt-3 line-clamp-3 text-sm">{maskText(p.actions[0])}</p>}
    </>
  );
}

function Card({ g }: { g: SymbolGroup }) {
  if (g.rows.length === 1) {
    const p = g.rows[0];
    return (
      <li>
        <Link to={symbolLink(p)} className="block rounded-md border border-line bg-panel p-3.5 hover:bg-sea-soft/50">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <span className="display text-2xl leading-none">{p.symbol}</span>
              <StatusChip status={p.status} />
              {p.mode === "dca" && <span className="eyebrow">DCA</span>}
            </div>
            <span className="num text-xs text-muted">{fmtPct(p.weight_pct, 0)} danh mục</span>
          </div>
          <SourceTags sources={p.sources} className="mt-2" />
          <RowBody p={p} />
        </Link>
      </li>
    );
  }
  return (
    <li className="rounded-md border border-line bg-panel">
      <div className="p-3.5 pb-2">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <span className="display text-2xl leading-none">{g.symbol}</span>
            <span className="text-xs text-muted">{g.rows.length} nguồn</span>
          </div>
          <span className="num text-xs text-muted">{fmtPct(g.weight_pct, 0)} danh mục</span>
        </div>
        <p className="num mt-1.5 text-xs text-muted">
          Cộng {fmtInt(g.quantity)} cp · vốn bình quân {fmtInt(g.avg_cost)} ·{" "}
          <span className={pnlCls(g.pnl_pct ?? 0)}>{fmtPnlPct(g.pnl_pct ?? 0)}</span>
        </p>
      </div>
      <ul className="divide-y divide-line border-t border-line">
        {g.rows.map((p) => (
          <li key={p.row_id || p.symbol}>
            <Link to={symbolLink(p)} className="block p-3.5 hover:bg-sea-soft/50">
              <div className="flex items-center gap-2.5">
                <SourceTags sources={p.sources} />
                <StatusChip status={p.status} />
                {p.mode === "dca" && <span className="eyebrow">DCA</span>}
              </div>
              <RowBody p={p} />
            </Link>
          </li>
        ))}
      </ul>
    </li>
  );
}

function Row({ p, sub }: { p: PositionEval; sub?: boolean }) {
  return (
    <tr className="hover:bg-sea-soft/50">
      <td className={cn("px-3 py-2.5", sub && "pl-8")}>
        {sub
          ? <Link to={symbolLink(p)} className="text-sm text-muted underline-offset-2 hover:underline" aria-label={`${p.symbol} tại ${p.source ?? "nguồn này"}`}>└ {p.symbol}</Link>
          : <Link to={symbolLink(p)} className="display text-xl underline-offset-2 hover:underline">{p.symbol}</Link>}
      </td>
      <td className="px-3 py-2.5"><SourceTags sources={p.sources} /></td>
      <td className="px-3 py-2.5"><StatusChip status={p.status} /></td>
      <td className="num px-3 py-2.5 text-right">{fmtInt(p.quantity)}</td>
      <td className="num px-3 py-2.5 text-right">{fmtInt(p.avg_cost)}</td>
      <td className="num px-3 py-2.5 text-right">{sub ? "" : fmtInt(p.price)}</td>
      <td className={cn("num px-3 py-2.5 text-right", pnlCls(p.pnl))}>
        <span className="font-medium">{fmtPnlPct(p.pnl_pct)}</span><br /><span className="text-xs">{fmtSigned(p.pnl)}</span>
      </td>
      <td className={cn("num px-3 py-2.5 text-right", sub && "text-muted")}>{fmtPct(p.weight_pct, 0)}</td>
      <td className="px-3 py-2.5"><Headroom p={p} /><NextTarget p={p} className="mt-1" /><RotationHint p={p} className="mt-1" /><HoldHint p={p} className="mt-1" /><MarginCallHint p={p} className="mt-1" /></td>
      <td className={cn("num px-3 py-2.5 text-right", (p.indicators.rsi14 ?? 50) < 40 ? "text-amber" : "")}>{sub ? "" : p.indicators.rsi14 != null ? p.indicators.rsi14.toFixed(0) : "—"}</td>
    </tr>
  );
}

function Table({ list }: { list: SymbolGroup[] }) {
  return (
    <div className="scroll-x rounded-md border border-line bg-panel">
      <table className="w-full min-w-[62rem] text-sm">
        <caption className="sr-only">Danh mục nắm giữ, xếp theo mức khẩn</caption>
        <thead>
          <tr className="border-b border-line text-left">
            {["Mã", "Nguồn", "Trạng thái", "Khối lượng", "Giá vốn", "Giá", "Lãi lỗ", "Tỷ trọng", "Cắt lỗ", "RSI"].map((h, i) => (
              <th key={h} scope="col" className={cn("eyebrow px-3 py-2.5 font-normal", i >= 3 && "text-right", h === "Cắt lỗ" && "!text-left")}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {list.map((g) => g.rows.length === 1 ? <Row key={g.symbol} p={g.rows[0]} /> : (
            <Fragment key={g.symbol}>
              <tr className="bg-sea-soft/30">
                <td className="px-3 py-2.5"><Link to={`/symbol/${g.symbol}`} className="display text-xl underline-offset-2 hover:underline">{g.symbol}</Link></td>
                <td className="px-3 py-2.5 text-xs text-muted">{g.rows.length} nguồn, cộng lại</td>
                <td className="px-3 py-2.5"></td>
                <td className="num px-3 py-2.5 text-right font-medium">{fmtInt(g.quantity)}</td>
                <td className="num px-3 py-2.5 text-right" title="Giá vốn bình quân gia quyền các nguồn">{fmtInt(g.avg_cost)}</td>
                <td className="num px-3 py-2.5 text-right">{fmtInt(g.price)}</td>
                <td className={cn("num px-3 py-2.5 text-right", pnlCls(g.pnl))}>
                  <span className="font-medium">{fmtPnlPct(g.pnl_pct ?? 0)}</span><br /><span className="text-xs">{fmtSigned(g.pnl)}</span>
                </td>
                <td className="num px-3 py-2.5 text-right font-medium">{fmtPct(g.weight_pct, 0)}</td>
                <td className="px-3 py-2.5 text-xs text-muted">Mỗi nguồn có mức cắt lỗ riêng</td>
                <td className="num px-3 py-2.5 text-right">{g.rows[0].indicators.rsi14 != null ? g.rows[0].indicators.rsi14.toFixed(0) : "—"}</td>
              </tr>
              {g.rows.map((p) => <Row key={p.row_id || p.symbol} p={p} sub />)}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Positions() {
  const q = usePositions();
  const [params, setParams] = useSearchParams();
  const [sort, setSort] = useState<SortKey>("urgency");
  const filter = params.get("status") as PositionStatus | null;

  return (
    <>
      <h1 className="display mb-4 text-3xl">Danh mục</h1>
      <QueryState query={q}>
        {({ positions, notes }) => <Body positions={positions} notes={notes} filter={filter} setFilter={(s) => setParams(s ? { status: s } : {})} sort={sort} setSort={setSort} />}
      </QueryState>
    </>
  );
}

function Body({ positions, notes, filter, setFilter, sort, setSort }: {
  positions: PositionEval[]; notes: string[]; filter: PositionStatus | null; setFilter: (s: PositionStatus | null) => void; sort: SortKey; setSort: (s: SortKey) => void;
}) {
  const counts = useMemo(() => {
    const c: Partial<Record<PositionStatus, number>> = {};
    groupBySymbol(positions).forEach((g) => new Set(g.rows.map((p) => p.status)).forEach((s) => { c[s] = (c[s] ?? 0) + 1; }));
    return c;
  }, [positions]);
  const list = useMemo(
    () => groupBySymbol(positions)
      .map((g) => (filter ? { ...g, rows: g.rows.filter((p) => p.status === filter) } : g))
      .filter((g) => g.rows.length)
      .sort(SORTS[sort].fn),
    [positions, filter, sort],
  );
  const symbols = new Set(positions.map((p) => p.symbol)).size;
  const total = positions.reduce((s, p) => s + p.market_value, 0);

  if (!positions.length) return <Empty title="Chưa có cổ phiếu nào">Tiểu khoản này không nắm giữ mã nào, hoặc broker chưa trả về danh mục.</Empty>;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div role="group" aria-label="Lọc theo trạng thái" className="flex flex-wrap gap-2">
          <button type="button" aria-pressed={!filter} onClick={() => setFilter(null)}
            className={cn("min-h-9 rounded-md border px-3 text-sm font-medium", !filter ? "border-ink bg-ink text-paper" : "border-line bg-panel")}>
            Tất cả <span className="num">{symbols}</span>
          </button>
          {STATUS_ORDER.filter((s) => counts[s]).map((s) => (
            <button key={s} type="button" aria-pressed={filter === s} onClick={() => setFilter(filter === s ? null : s)}
              className={cn("min-h-9 rounded-md border px-3 text-sm font-medium", filter === s ? "border-ink bg-ink text-paper" : "border-line bg-panel")}>
              {STATUS[s].label} <span className="num">{counts[s]}</span>
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm">
          <span className="text-muted">Sắp xếp</span>
          <select className="min-h-10 rounded-md border border-line bg-panel px-2.5" value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
            {(Object.keys(SORTS) as SortKey[]).map((k) => <option key={k} value={k}>{SORTS[k].label}</option>)}
          </select>
        </label>
      </div>

      <p className="text-sm text-muted">Tổng giá trị cổ phiếu <span className="num text-ink">{fmtMoney(total)}</span>. Mã cần xử lý nhất nằm trên cùng. Mã nắm ở nhiều công ty có dòng cộng lại và từng dòng theo nguồn, vì mỗi nguồn có giá vốn và mức cắt lỗ riêng.</p>

      {list.length === 0 ? <Empty title="Không có mã nào ở trạng thái này" /> : (
        <>
          <ul className="space-y-2.5 md:hidden">{list.map((p) => <Card key={p.symbol} g={p} />)}</ul>
          <div className="hidden md:block"><Table list={list} /></div>
        </>
      )}

      {notes.length > 0 && (
        <Panel className="p-3.5" as="div">
          <p className="eyebrow mb-1">Ghi chú về dữ liệu</p>
          <ul className="list-disc space-y-0.5 pl-5 text-sm text-muted">{notes.map((n) => <li key={n}>{n}</li>)}</ul>
        </Panel>
      )}
    </div>
  );
}

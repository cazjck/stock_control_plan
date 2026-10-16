import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { QueryState } from "../components/QueryState";
import { Empty } from "../components/ui";
import { cn, fmtInt, fmtPct, fmtPnlPct, fmtTime, pnlTone } from "../lib/format";
import { useBoard } from "../lib/hooks";
import { useBoardLive, type LiveBoard } from "../lib/boardStream";
import type { BoardResponse, BoardRow } from "../lib/types";

/** Màu giá theo quy ước bảng điện Việt Nam. */
function tone(p: number | null | undefined, r: BoardRow): string {
  if (p == null || !r.ref) return "text-ink";
  if (r.ceil && p >= r.ceil) return "text-ceil";
  if (r.floor && p <= r.floor) return "text-floor";
  if (p > r.ref) return "text-ok";
  if (p < r.ref) return "text-lead";
  return "text-amber";
}

const vol = (n: number | null | undefined) => (n == null || n === 0 ? "" : n >= 1e6 ? `${(n / 1e6).toFixed(2).replace(".", ",")}tr` : fmtInt(n));

/** Ô có chớp nhẹ khi giá trị đổi giữa hai lần làm mới. */
function Flash({ value, className, children }: { value: unknown; className?: string; children: React.ReactNode }) {
  const prev = useRef(value);
  const [k, setK] = useState(0);
  useEffect(() => { if (prev.current !== value) { prev.current = value; setK((x) => x + 1); } }, [value]);
  return <span key={k} className={cn(k > 0 && "tick-flash", "rounded-sm px-0.5", className)}>{children}</span>;
}

function Row({ r }: { r: BoardRow }) {
  const td = "num px-2 py-1.5 text-right";
  const lvl = (side: "bid" | "offer", i: number) => r[side][i];
  return (
    <tr className="hover:bg-sea-soft/40">
      <th scope="row" className={cn("px-2 py-1.5 text-left", tone(r.price, r))}>
        <Link to={`/symbol/${r.symbol}`} className="display text-lg hover:underline">{r.symbol}</Link>
      </th>
      <td className={cn(td, "text-ceil")}>{fmtInt(r.ceil)}</td>
      <td className={cn(td, "text-floor")}>{fmtInt(r.floor)}</td>
      <td className={cn(td, "text-amber")}>{fmtInt(r.ref)}</td>
      {[2, 1, 0].map((i) => (
        <FragmentPair key={`b${i}`} price={lvl("bid", i)?.price} qty={lvl("bid", i)?.qty} r={r} shade />
      ))}
      <td className={cn(td, "bg-sea-soft/60 font-semibold", tone(r.price, r))}><Flash value={r.price}>{fmtInt(r.price)}</Flash></td>
      <td className={cn(td, "bg-sea-soft/60", tone(r.price, r))}>{vol(r.match_qty)}</td>
      <td className={cn(td, "bg-sea-soft/60", tone(r.price, r))}>{r.change != null ? `${r.change > 0 ? "+" : ""}${fmtInt(r.change)}` : ""}</td>
      <td className={cn(td, "bg-sea-soft/60", tone(r.price, r))}>{fmtPct(r.change_pct, 2, true)}</td>
      {[0, 1, 2].map((i) => (
        <FragmentPair key={`o${i}`} price={lvl("offer", i)?.price} qty={lvl("offer", i)?.qty} r={r} shade />
      ))}
      <td className={cn(td, tone(r.high, r))}>{fmtInt(r.high)}</td>
      <td className={cn(td, tone(r.low, r))}>{fmtInt(r.low)}</td>
      <td className={td}>{vol(r.total_vol)}</td>
      <td className={td}>{vol(r.foreign_buy)}</td>
      <td className={td}>{vol(r.foreign_sell)}</td>
      <td className={cn(td, "border-l border-line")}>{fmtInt(r.held_qty)}</td>
      <td className={td}>{fmtInt(r.avg_cost)}</td>
      <td className={cn(td, "font-semibold", pnlTone(r.pnl_pct))}>{fmtPnlPct(r.pnl_pct)}</td>
    </tr>
  );
}

function FragmentPair({ price, qty, r, shade }: { price?: number; qty?: number; r: BoardRow; shade?: boolean }) {
  const td = cn("num px-2 py-1.5 text-right", shade && "bg-paper/60");
  return (
    <>
      <td className={cn(td, tone(price, r))}><Flash value={price}>{price ? fmtInt(price) : ""}</Flash></td>
      <td className={cn(td, tone(price, r))}><Flash value={qty}>{vol(qty)}</Flash></td>
    </>
  );
}

function Desktop({ rows }: { rows: BoardRow[] }) {
  const g = "eyebrow px-2 py-1 font-normal text-center";
  const h = "eyebrow px-2 py-1 font-normal text-right";
  return (
    <div className="scroll-x rounded-md border border-line bg-panel">
      <table className="w-full min-w-[78rem] text-[13px]">
        <caption className="sr-only">Bảng giá các mã trong danh mục</caption>
        <thead>
          <tr className="border-b border-line">
            <th rowSpan={2} scope="col" className="eyebrow px-2 py-1 text-left font-normal">Mã</th>
            <th rowSpan={2} scope="col" className={h}>Trần</th>
            <th rowSpan={2} scope="col" className={h}>Sàn</th>
            <th rowSpan={2} scope="col" className={h}>TC</th>
            <th colSpan={6} scope="colgroup" className={g}>Bên mua</th>
            <th colSpan={4} scope="colgroup" className={cn(g, "bg-sea-soft/60")}>Khớp lệnh</th>
            <th colSpan={6} scope="colgroup" className={g}>Bên bán</th>
            <th rowSpan={2} scope="col" className={h}>Cao</th>
            <th rowSpan={2} scope="col" className={h}>Thấp</th>
            <th rowSpan={2} scope="col" className={h}>Tổng KL</th>
            <th colSpan={2} scope="colgroup" className={g}>Nước ngoài</th>
            <th colSpan={3} scope="colgroup" className={cn(g, "border-l border-line")}>Của bạn</th>
          </tr>
          <tr className="border-b border-line">
            {["Giá 3", "KL 3", "Giá 2", "KL 2", "Giá 1", "KL 1"].map((x) => <th key={`b${x}`} scope="col" className={h}>{x}</th>)}
            {["Giá", "KL", "+/−", "%"].map((x) => <th key={`m${x}`} scope="col" className={cn(h, "bg-sea-soft/60")}>{x}</th>)}
            {["Giá 1", "KL 1", "Giá 2", "KL 2", "Giá 3", "KL 3"].map((x) => <th key={`o${x}`} scope="col" className={h}>{x}</th>)}
            <th scope="col" className={h}>Mua</th><th scope="col" className={h}>Bán</th>
            <th scope="col" className={cn(h, "border-l border-line")}>KL giữ</th><th scope="col" className={h}>Giá vốn</th><th scope="col" className={h}>Lãi lỗ</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">{rows.map((r) => <Row key={r.symbol} r={r} />)}</tbody>
      </table>
    </div>
  );
}

function Mobile({ rows }: { rows: BoardRow[] }) {
  return (
    <ul className="divide-y divide-line rounded-md border border-line bg-panel">
      {rows.map((r) => (
        <li key={r.symbol}>
          <Link to={`/symbol/${r.symbol}`} className="grid grid-cols-[4.5rem_1fr_auto] items-center gap-x-3 px-3 py-2.5">
            <span className={cn("display text-xl", tone(r.price, r))}>{r.symbol}</span>
            <span className="min-w-0">
              <span className={cn("num block text-base font-semibold", tone(r.price, r))}><Flash value={r.price}>{fmtInt(r.price)}</Flash></span>
              <span className="num block text-[11px] text-muted">
                <span className="text-ceil">{fmtInt(r.ceil)}</span> · <span className="text-amber">{fmtInt(r.ref)}</span> · <span className="text-floor">{fmtInt(r.floor)}</span> · KL {vol(r.total_vol) || "0"}
              </span>
            </span>
            <span className="text-right">
              <span className={cn("num block text-sm font-semibold", tone(r.price, r))}>{fmtPct(r.change_pct, 2, true)}</span>
              <span className={cn("num block text-[11px]", pnlTone(r.pnl_pct))}>lãi lỗ {fmtPnlPct(r.pnl_pct)}</span>
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function LiveBadge({ live }: { live: LiveBoard }) {
  const [, force] = useState(0);
  useEffect(() => { const t = setInterval(() => force((x) => x + 1), 1000); return () => clearInterval(t); }, []);
  const age = live.lastTick ? Math.round((Date.now() - live.lastTick) / 1000) : null;
  const m = {
    live: { dot: "bg-ok", text: age == null ? "Trực tiếp" : `Trực tiếp · lệnh khớp gần nhất ${age < 2 ? "vừa xong" : `${age} giây trước`}`, cls: "text-ok" },
    connecting: { dot: "bg-amber-fill", text: "Đang kết nối giá trực tiếp…", cls: "text-amber" },
    polling: { dot: "bg-muted", text: "Làm mới mỗi 5 giây trong giờ giao dịch", cls: "text-muted" },
    auth: { dot: "bg-lead", text: live.message ?? "Cần nhập iOTP để xem giá trực tiếp", cls: "text-lead" },
    error: { dot: "bg-amber-fill", text: live.message ?? "Mất kết nối, đang thử lại", cls: "text-amber" },
  }[live.mode];
  return (
    <p role="status" className={cn("inline-flex items-center gap-2 text-xs font-medium", m.cls)}>
      <span aria-hidden className={cn("inline-block size-2 rounded-full", m.dot, live.mode === "live" && "motion-safe:animate-pulse")} />
      {m.text}
    </p>
  );
}

function Body({ b, live }: { b: BoardResponse; live: LiveBoard }) {
  if (!b.rows.length) return <Empty title="Danh mục chưa có mã nào">Bảng giá chỉ hiện các mã bạn đang nắm giữ trong danh mục đang chọn.</Empty>;
  const ix = b.index;
  const ixTone = !ix?.change ? "text-amber" : ix.change > 0 ? "text-ok" : "text-lead";
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        {ix?.value != null && (
          <p className="num text-sm">
            <span className="display mr-2 text-base">{ix.symbol}</span>
            <span className={cn("font-semibold", ixTone)}>{ix.value.toFixed(2).replace(".", ",")}</span>{" "}
            <span className={ixTone}>{ix.change != null ? `${ix.change > 0 ? "+" : ""}${ix.change.toFixed(2).replace(".", ",")}` : ""} ({fmtPct(ix.change_pct, 2, true)})</span>
          </p>
        )}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <LiveBadge live={live} />
          <p className="text-xs text-muted">Nguồn {b.source ?? "—"}{live.mode !== "live" && <> · cập nhật {fmtTime(b.as_of)}:{new Date(b.as_of).getSeconds().toString().padStart(2, "0")}</>}</p>
        </div>
      </div>
      {b.note && <p className="text-sm text-amber">{b.note}</p>}
      <div className="hidden md:block"><Desktop rows={b.rows} /></div>
      <div className="md:hidden"><Mobile rows={b.rows} /></div>
      <p className="text-xs text-muted">
        <span className="text-ceil">Tím</span> là giá trần, <span className="text-floor">xanh lam</span> là giá sàn,{" "}
        <span className="text-amber">vàng</span> là tham chiếu, <span className="text-ok">xanh lá</span> tăng, <span className="text-lead">đỏ</span> giảm.
        Giá cập nhật trực tiếp khi có lệnh khớp; nếu luồng trực tiếp lỗi thì tự làm mới mỗi 5 giây. Đây là bảng giá để xem, không đặt lệnh được.
      </p>
    </div>
  );
}

export default function Board() {
  const live = useBoardLive();
  const streaming = !!live.data && (live.mode === "live" || live.mode === "connecting");
  const q = useBoard(streaming);
  return (
    <>
      <h1 className="display mb-3 text-3xl">Bảng giá</h1>
      {streaming && live.data ? <Body b={live.data} live={live} /> : <QueryState query={q}>{(b) => <Body b={b} live={live} />}</QueryState>}
    </>
  );
}

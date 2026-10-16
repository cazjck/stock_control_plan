import { Link } from "react-router-dom";
import { CheckCircle2 } from "lucide-react";
import { AlertItem } from "../components/AlertItem";
import { DraftGauge } from "../components/DraftGauge";
import { QueryState } from "../components/QueryState";
import { StatusChip } from "../components/StatusChip";
import { Eyebrow, Panel, Stat } from "../components/ui";
import { ageText, cn, fmtInt, fmtMoney, fmtPct, fmtPnlPct, fmtSigned, fmtTime, pnlStatTone } from "../lib/format";
import { maskText } from "../lib/privacy";
import { marketSession, remainingText } from "../lib/session";
import { useSelection } from "../lib/selection";
import { useAlerts, useMarginPlan, useOverview, usePositions } from "../lib/hooks";
import { SourceTag } from "../components/SourceTags";
import { symbolLink } from "../lib/group";
import { STATUS_ORDER, TONE_CLASS } from "../lib/status";
import type { MarketInfo, MarginMetrics, Overview as OverviewData } from "../lib/types";
import { verdictFor, worstBucket } from "../lib/verdict";

const MARKET_TONE: Record<MarketInfo["state"], { cls: string; title: string }> = {
  NORMAL: { cls: "border-ok/50 bg-ok-soft text-ok", title: "Thị trường thuận lợi" },
  NO_NEW_BUYS: { cls: "border-amber/50 bg-amber-soft text-amber", title: "Không mở vị thế mới" },
  WEAK: { cls: "border-lead/50 bg-lead-soft text-lead", title: "Thị trường yếu" },
  UNKNOWN: { cls: "border-line bg-panel text-muted", title: "Chưa rõ xu hướng thị trường" },
};

function MarketBanner({ m }: { m: MarketInfo }) {
  const t = MARKET_TONE[m.state];
  return (
    <div className={cn("flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 rounded-md border px-4 py-3", t.cls)}>
      <p><span className="display text-lg">{t.title}.</span> <span className="text-sm">{m.note}</span></p>
      {m.close != null && (
        <p className="num text-xs">
          {m.index_symbol} {m.close.toFixed(0)} · SMA50 {m.sma50?.toFixed(0)} · SMA200 {m.sma200?.toFixed(0)}
        </p>
      )}
    </div>
  );
}

function Hero({ o }: { o: OverviewData }) {
  const metrics = o.margin.buckets;
  const worst = worstBucket(metrics);
  const v = verdictFor(worst);
  const b = worst?.bucket;
  const others = metrics.filter((m) => m !== worst);

  if (!worst) {
    return (
      <Panel className="p-5">
        <Eyebrow>Ký quỹ</Eyebrow>
        <p className="display mt-1 text-3xl">Tài khoản này không có nợ margin</p>
        <p className="mt-1 max-w-xl text-sm text-muted">Không có tỷ lệ ký quỹ để theo dõi. Rủi ro còn lại nằm ở từng mã trong danh mục.</p>
      </Panel>
    );
  }

  return (
    <Panel className="p-4 sm:p-6">
      <div className="flex flex-col gap-6 sm:flex-row sm:items-start">
        <div className="mx-auto sm:mx-0">
          <DraftGauge ratio={b?.ratio_pct} maintenance={b?.maintenance_pct} liquidation={b?.liquidation_pct} liquidationLabel={b?.ratio_kind === "collateral_over_debt" ? "xử lý" : "giải chấp"} safeTarget={worst.safe_target_pct} />
        </div>
        <div className="min-w-0 flex-1">
          <Eyebrow>Ký quỹ · {b?.label}</Eyebrow>
          <p className={cn("display mt-1 text-[2.1rem] leading-[1.05] sm:text-5xl", TONE_CLASS[v.tone])}>{v.headline}</p>
          <p className="mt-3 max-w-prose text-[15px]">{v.detail}</p>
          <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3">
            <Stat label="Dư nợ" value={fmtMoney(o.margin.total_debt)} />
            <Stat label="Lãi vay mỗi ngày" value={fmtMoney(o.margin.interest_per_day)}
                  sub={o.assets.interest_pct_nav_per_day != null ? `${fmtPct(o.assets.interest_pct_nav_per_day, 3)} NAV` : undefined}
                  tone={(o.assets.interest_pct_nav_per_day ?? 0) > 0.1 ? "lead" : undefined} />
            <Stat label="Cần nộp để an toàn" value={worst.cash_to_safe ? fmtMoney(worst.cash_to_safe) : "Không cần"}
                  sub={worst.safe_target_pct != null ? `đưa RTT lên ${fmtPct(worst.safe_target_pct, 0)}` : undefined} />
          </dl>
        </div>
      </div>
      {others.length > 0 && <OtherBuckets list={others} />}
    </Panel>
  );
}

function OtherBuckets({ list }: { list: MarginMetrics[] }) {
  return (
    <div className="mt-6 border-t border-line pt-4">
      <p className="eyebrow mb-2">Các nhóm ký quỹ khác ({list.length})</p>
      <ul className="divide-y divide-line text-sm">
        {list.slice(0, 5).map((m) => (
          <li key={m.bucket.id} className="flex items-center justify-between gap-3 py-1.5">
            <span className="truncate">{m.bucket.label}</span>
            <span className={cn("num shrink-0", TONE_CLASS[m.zone])}>
              {fmtPct(m.bucket.ratio_pct)} · giảm {fmtPct(m.drop_to_maintenance_pct)} là gọi ký quỹ
            </span>
          </li>
        ))}
      </ul>
      {list.length > 5 && <Link to="/margin" className="mt-2 inline-block text-sm font-medium text-sea underline underline-offset-2">Xem đủ {list.length} nhóm</Link>}
    </div>
  );
}

function Todo({ o }: { o: OverviewData }) {
  const items = o.top_alerts;
  const total = o.counts.alerts_critical + o.counts.alerts_warning;
  return (
    <section aria-labelledby="todo">
      <div className="mb-2 flex items-baseline justify-between">
        <h2 id="todo" className="eyebrow">Cần xử lý hôm nay</h2>
        <Link to="/alerts" className="text-sm font-medium text-sea underline underline-offset-2">Tất cả cảnh báo</Link>
      </div>
      {items.length === 0 ? (
        <div className="flex items-center gap-3 rounded-md border border-ok/40 bg-ok-soft px-4 py-3 text-ok">
          <CheckCircle2 size={20} aria-hidden /> <p className="text-sm font-medium">Chưa có việc nào phải xử lý. Giữ kỷ luật và không xem bảng điện ngoài khung giờ đã định.</p>
        </div>
      ) : (
        <div className="space-y-2.5">
          {items.map((a) => <AlertItem key={a.id} alert={a} />)}
          {total > items.length && <p className="text-sm text-muted">Còn {total - items.length} cảnh báo nữa trong trung tâm cảnh báo.</p>}
        </div>
      )}
    </section>
  );
}

function Connection({ o }: { o: OverviewData }) {
  const { brokers } = useSelection();
  const b = brokers.find((x) => x.name === o.broker);
  const ms = marketSession();
  const stale = o.data_age_seconds > 300 && ms.open;
  const rows: [string, string, boolean?][] = [
    ["Broker", `${b?.display_name ?? o.broker} · tiểu khoản ${o.account_id}`],
    ["Token phiên", !o.session.authenticated ? "cần đăng nhập" : o.session.expires_at ? `còn ${remainingText(o.session.expires_at)}` : "không giới hạn", !o.session.authenticated],
    ["Dữ liệu", `lúc ${fmtTime(o.as_of)} (${ageText(o.data_age_seconds)})`, stale],
    ["Thị trường", ms.label],
  ];
  return (
    <section aria-labelledby="conn">
      <h2 id="conn" className="eyebrow mb-3">Trạng thái kết nối</h2>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 lg:grid-cols-4">
        {rows.map(([k, v, warn]) => (
          <div key={k}><dt className="eyebrow">{k}</dt><dd className={cn("text-sm", warn && "font-medium text-amber")}>{v}{warn && k === "Dữ liệu" ? ". Dữ liệu đã cũ hơn 5 phút." : ""}</dd></div>
        ))}
      </dl>
    </section>
  );
}

/** Dải kỷ luật: lô mua thêm khi đang lỗ đã tới lúc phải bán. Không ẩn được tới khi bán hoặc ghi lý do. */
function DisciplineBanner() {
  const q = useAlerts("active");
  const list = (q.data ?? []).filter((a) => a.rule === "add_on_lot");
  if (!list.length) return null;
  const cost = list.reduce((s, a) => s + (Number(a.data?.delay_cost) || 0), 0);
  return (
    <section role="alert" className="rounded-md border-2 border-lead bg-lead-soft p-4">
      <p className="display text-xl text-lead">{list.length === 1 ? "Có 1 lô mua thêm phải bán" : `Có ${list.length} lô mua thêm phải bán`}</p>
      <ul className="mt-2 space-y-1.5 text-sm">
        {list.map((a) => (
          <li key={a.id}><Link to={`/symbol/${a.symbol}`} className="font-medium underline underline-offset-2">{a.symbol}</Link>: {maskText(a.message)}</li>
        ))}
      </ul>
      {cost > 0 && <p className="mt-2 text-sm font-semibold text-lead">Chần chừ tới giờ đã tốn thêm {fmtMoney(cost)}.</p>}
      <p className="mt-2 text-xs text-muted">Dải này chỉ mất khi bạn bán đúng số cổ phiếu của lô, hoặc ghi lý do không bán ở trang Cảnh báo.</p>
    </section>
  );
}

/** Mục 5b: mỗi tài khoản cần bán gì để về vùng an toàn. Chi tiết ở trang Ký quỹ. */
function MarginPlanSummary() {
  const q = useMarginPlan();
  const plans = (q.data?.plans ?? []).filter((p) => p.safe_steps.length > 0);
  const todo = (p: (typeof plans)[number]) => p.safe_steps.filter((s) => !s.deferred);
  if (!plans.length) return null;
  const o = q.data!;
  return (
    <section aria-labelledby="mp">
      <h2 id="mp" className="eyebrow mb-2">Hạ margin</h2>
      <ul className="space-y-2">
        {plans.map((p) => (
          <li key={p.bucket_id}>
            <Link to="/margin" className="flex items-start gap-3 rounded-md border border-line bg-panel p-3 hover:bg-sea-soft/50">
              <span className="w-14 shrink-0 pt-0.5"><SourceTag source={p.source} /></span>
              <span className="min-w-0 text-sm">
                {todo(p).length > 0 && <span className="font-medium">{todo(p).map((s) => `bán ${fmtInt(s.quantity)} ${s.symbol}`).join(", ")}.</span>}{" "}
                <span className="text-muted">{maskText(p.headline)}</span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-muted">
        Làm xong giai đoạn 1, lãi margin giảm từ {fmtMoney(o.interest_per_day)} còn {fmtMoney(o.interest_after_safe)} mỗi ngày.
      </p>
    </section>
  );
}

/** Mã đang có khuyến nghị chốt lời hôm nay (một phần hoặc toàn bộ). */
function ProfitTaking() {
  const q = usePositions();
  const list = (q.data?.positions ?? []).filter((p) => p.take_profit && ["partial", "full", "watch"].includes(p.take_profit.advice.level));
  if (!list.length) return null;
  return (
    <section aria-labelledby="tp">
      <h2 id="tp" className="eyebrow mb-2">Cơ hội chốt lời</h2>
      <ul className="space-y-2">
        {list.map((p) => {
          const a = p.take_profit!.advice;
          const tone = a.level === "full" ? "text-lead" : a.level === "partial" ? "text-ok" : "text-amber";
          return (
            <li key={p.row_id || p.symbol}>
              <Link to={symbolLink(p)} className="flex items-start gap-3 rounded-md border border-line bg-panel p-3 hover:bg-sea-soft/50">
                <span className="w-14 shrink-0"><span className="display block text-xl leading-tight">{p.symbol}</span>
                  {p.source && <span className="text-[11px] text-muted">{p.source}</span>}</span>
                <span className="min-w-0 text-sm">
                  <span className={cn("font-semibold", tone)}>{fmtPnlPct(p.pnl_pct)}</span> · {maskText(a.text)}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function Body({ o }: { o: OverviewData }) {
  const a = o.assets;
  const pnlTone = pnlStatTone(a.unrealized_pnl);
  return (
    <div className="space-y-6">
      <DisciplineBanner />
      <Hero o={o} />
      <MarketBanner m={o.market} />
      <Todo o={o} />
      <MarginPlanSummary />
      <ProfitTaking />

      <section aria-labelledby="assets">
        <h2 id="assets" className="eyebrow mb-3">Tài sản</h2>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-5 lg:grid-cols-4">
          <Stat label="Tài sản ròng (NAV)" value={fmtMoney(a.nav)} sub={`cổ phiếu ${fmtMoney(a.positions_value)} + tiền ${fmtMoney(a.cash)} − nợ ${fmtMoney(a.debt)}`} />
          <Stat label="Lãi lỗ chưa thực hiện" value={fmtSigned(a.unrealized_pnl)} sub={fmtPnlPct(a.unrealized_pnl_pct)} tone={pnlTone} />
          <Stat label="Giá trị cổ phiếu" value={fmtMoney(a.positions_value)} sub={`giá vốn ${fmtMoney(a.cost_value)}`} />
          <Stat label="Tiền mặt" value={fmtMoney(a.cash)} />
        </dl>
      </section>

      <section aria-labelledby="by-status">
        <h2 id="by-status" className="eyebrow mb-3">Danh mục theo trạng thái</h2>
        <ul className="flex flex-wrap gap-2">
          {STATUS_ORDER.filter((s) => (o.counts[s] ?? 0) > 0).map((s) => (
            <li key={s}>
              <Link to={`/positions?status=${s}`} className="inline-flex items-center gap-2 rounded-md border border-line bg-panel px-2.5 py-1.5 hover:bg-sea-soft">
                <StatusChip status={s} className="pointer-events-none" />
                <span className="num font-medium">{o.counts[s]}</span>
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <Connection o={o} />
    </div>
  );
}

export default function Overview() {
  const q = useOverview();
  return (
    <>
      <h1 className="sr-only">Tổng quan rủi ro</h1>
      <QueryState query={q}>{(o) => <Body o={o} />}</QueryState>
    </>
  );
}

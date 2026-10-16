import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Anchor, BellRing, BookOpen, ChartCandlestick, Eye, EyeOff, Ellipsis, FlaskConical, Landmark, Layers, Lock, RefreshCw, SlidersHorizontal } from "lucide-react";
import { api } from "../lib/api";
import { ageText, cn, fmtTime } from "../lib/format";
import { useAlerts, useOverview, useRefreshAll } from "../lib/hooks";
import { useSelection } from "../lib/selection";
import { usePrivacy } from "../lib/privacy";

const NAV = [
  { to: "/", label: "Tổng quan", icon: Anchor, end: true },
  { to: "/positions", label: "Danh mục", icon: Layers },
  { to: "/board", label: "Bảng giá", icon: ChartCandlestick },
  { to: "/margin", label: "Ký quỹ và nợ", short: "Ký quỹ", icon: Landmark },
  { to: "/scenarios", label: "Kịch bản giả định", short: "Kịch bản", icon: FlaskConical },
  { to: "/alerts", label: "Cảnh báo", icon: BellRing },
  { to: "/ledger", label: "Sổ danh mục", short: "Sổ", icon: BookOpen },
  { to: "/settings", label: "Thiết lập", icon: SlidersHorizontal },
] as const;

/** Thanh dưới trên điện thoại chỉ giữ bốn trang dùng hằng ngày; còn lại nằm trong "Thêm". */
const MOBILE_PRIMARY = ["/", "/positions", "/board", "/alerts"];

function Brand() {
  return (
    <div className="flex items-center gap-2">
      <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden>
        <rect width="32" height="32" rx="6" fill="var(--hull)" />
        <circle cx="16" cy="16" r="7" fill="none" stroke="var(--hull-text)" strokeWidth="2" />
        <path d="M6 16h20" stroke="var(--hull-text)" strokeWidth="2" />
        <path d="M4 25c4-2.5 6 2.5 12 0s8 2.5 12 0" stroke="var(--wave)" strokeWidth="2" fill="none" strokeLinecap="round" />
      </svg>
      <span className="display text-xl leading-none tracking-wide">Mớn nước</span>
    </div>
  );
}

function ReadOnlyBadge() {
  return (
    <span
      title="Ứng dụng này chỉ đọc dữ liệu. Không có chức năng đặt, sửa, hủy lệnh hay chuyển tiền."
      className="eyebrow inline-flex items-center gap-1.5 rounded-sm border border-ink/40 px-2 py-0.5 !text-ink"
    >
      <Lock size={12} aria-hidden /> Chỉ đọc
    </span>
  );
}

function Selectors() {
  const { sel, brokers, setBroker, setAccount } = useSelection();
  const accounts = useQuery({
    queryKey: ["accounts", sel.broker], queryFn: () => api.accounts(sel.broker),
    enabled: !!sel.broker, retry: false, staleTime: 60_000,
  });
  const cls = "min-h-10 rounded-md border border-line bg-panel px-2.5 text-sm";
  return (
    <div className="flex items-center gap-2">
      <select aria-label="Broker" className={cls} value={sel.broker ?? ""} onChange={(e) => setBroker(e.target.value)}>
        {brokers.map((b) => <option key={b.name} value={b.name}>{b.display_name}</option>)}
      </select>
      {accounts.data && accounts.data.length > 1 && (
        <select aria-label="Tiểu khoản" className={`${cls} num max-w-32`} value={sel.account ?? ""} onChange={(e) => setAccount(e.target.value || undefined)}>
          <option value="">Tự chọn</option>
          {accounts.data.map((a) => <option key={a.id} value={a.id}>{a.id}</option>)}
        </select>
      )}
    </div>
  );
}

function Freshness() {
  const o = useOverview();
  const refresh = useRefreshAll();
  const age = o.data?.data_age_seconds ?? 0;
  const stale = !!o.data && age > 300;
  return (
    <div className="flex items-center gap-2">
      <span className={cn("hidden text-xs sm:inline", stale ? "text-amber" : "text-muted")} aria-live="polite">
        {o.data ? `Cập nhật ${fmtTime(o.data.as_of)} · ${ageText(age)}` : ""}
      </span>
      <button
        type="button" onClick={() => refresh.mutate()} disabled={refresh.isPending} aria-label="Làm mới dữ liệu"
        className="inline-flex size-10 items-center justify-center rounded-md border border-line bg-panel hover:bg-sea-soft disabled:opacity-60"
      >
        <RefreshCw size={16} className={refresh.isPending ? "animate-spin" : ""} aria-hidden />
      </button>
    </div>
  );
}

function PrivacyToggle() {
  const [on, set] = usePrivacy();
  return (
    <button
      type="button" aria-pressed={on} onClick={() => set(!on)}
      aria-label={on ? "Hiện số tiền và lãi lỗ" : "Che số tiền và lãi lỗ"}
      title={on ? "Đang che số tiền và lãi lỗ. Bấm để hiện." : "Che số tiền và lãi lỗ"}
      className={cn("inline-flex size-10 items-center justify-center rounded-md border",
                    on ? "border-ink bg-ink text-paper" : "border-line bg-panel hover:bg-sea-soft")}
    >
      {on ? <EyeOff size={16} aria-hidden /> : <Eye size={16} aria-hidden />}
    </button>
  );
}

function AlertBadge() {
  const a = useAlerts("active");
  const n = (a.data ?? []).filter((x) => x.severity !== "info" && x.status === "open").length;
  if (!n) return null;
  return <span className="num ml-auto rounded-sm bg-lead px-1.5 text-[11px] font-semibold text-paper" aria-label={`${n} cảnh báo chưa xem`}>{n}</span>;
}

function DemoBanner() {
  const { sel } = useSelection();
  if (sel.broker !== "demo") return null;
  return (
    <div role="status" className="border-b border-amber/50 bg-amber-soft px-4 py-2 text-center text-sm text-amber">
      <strong className="font-semibold">Dữ liệu mẫu.</strong> Đây không phải tài khoản thật. Đặt BROKERS=tcbs hoặc dnse trong backend/.env để dùng dữ liệu thật.
    </div>
  );
}

function MobileNav() {
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  const ref = useRef<HTMLDivElement>(null);
  const primary = NAV.filter((n) => MOBILE_PRIMARY.includes(n.to));
  const more = NAV.filter((n) => !MOBILE_PRIMARY.includes(n.to));
  const moreActive = more.some((n) => loc.pathname.startsWith(n.to));

  useEffect(() => setOpen(false), [loc.pathname]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    const onClick = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => { document.removeEventListener("keydown", onKey); document.removeEventListener("mousedown", onClick); };
  }, [open]);

  const tab = "relative flex min-h-14 flex-col items-center justify-center gap-0.5 pt-1.5 text-[11px] font-medium";
  return (
    <div ref={ref} className="md:hidden">
      {open && (
        <nav aria-label="Trang khác" className="fixed inset-x-3 bottom-[4.25rem] z-40 rounded-md border border-line bg-panel p-1.5 shadow-lg">
          {more.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} className={({ isActive }) =>
              cn("flex min-h-12 items-center gap-3 rounded-md px-3 text-[15px] font-medium", isActive ? "bg-ink text-paper" : "hover:bg-sea-soft")}>
              <Icon size={19} aria-hidden /> {label}
            </NavLink>
          ))}
        </nav>
      )}
      <nav aria-label="Điều hướng chính" className="safe-bottom fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-line bg-panel">
        {primary.map(({ to, label, icon: Icon, ...rest }) => (
          <NavLink key={to} to={to} end={"end" in rest} className={({ isActive }) => cn(tab, isActive ? "text-ink" : "text-muted")}>
            {({ isActive }) => (
              <>
                {isActive && <span aria-hidden className="absolute inset-x-4 top-0 h-0.5 rounded-b bg-ink" />}
                <Icon size={20} aria-hidden />
                <span>{"short" in rest ? rest.short : label}</span>
                {to === "/alerts" && <span className="absolute right-3 top-1.5"><AlertBadge /></span>}
              </>
            )}
          </NavLink>
        ))}
        <button type="button" aria-expanded={open} aria-haspopup="true" onClick={() => setOpen((v) => !v)}
                className={cn(tab, open || moreActive ? "text-ink" : "text-muted")}>
          {moreActive && <span aria-hidden className="absolute inset-x-4 top-0 h-0.5 rounded-b bg-ink" />}
          <Ellipsis size={20} aria-hidden />
          <span>Thêm</span>
        </button>
      </nav>
    </div>
  );
}

/** Đổi chế độ che số thì vẽ lại toàn bộ trang để mọi con số cập nhật. */
function PrivateOutlet() {
  const [on] = usePrivacy();
  return (
    <div key={on ? "private" : "open"}>
      {on && (
        <p className="mb-3 inline-flex items-center gap-1.5 rounded-sm bg-ink px-2 py-0.5 text-xs font-medium text-paper">
          <EyeOff size={12} aria-hidden /> Đang che số tiền và lãi lỗ. Lệnh bán và mức cắt lỗ vẫn hiện đầy đủ.
        </p>
      )}
      <Outlet />
    </div>
  );
}

export function Shell() {
  return (
    <div className="min-h-dvh md:grid md:grid-cols-[13.5rem_minmax(0,1fr)]">
      <aside className="sticky top-0 hidden h-dvh flex-col gap-6 border-r border-line p-4 md:flex">
        <Brand />
        <nav aria-label="Điều hướng chính" className="flex flex-col gap-1">
          {NAV.map(({ to, label, icon: Icon, ...rest }) => (
            <NavLink key={to} to={to} end={"end" in rest} className={({ isActive }) =>
              cn("flex min-h-10 items-center gap-2.5 rounded-md px-2.5 text-sm font-medium",
                 isActive ? "bg-ink text-paper" : "text-muted hover:bg-sea-soft hover:text-ink")}>
              <Icon size={17} aria-hidden /> {label}
              {to === "/alerts" && <AlertBadge />}
            </NavLink>
          ))}
        </nav>
        <p className="mt-auto text-xs text-muted">
          Công cụ quản trị rủi ro cá nhân. Chỉ đọc dữ liệu, không đặt lệnh. Số liệu mang tính tham khảo, quyết định bán là của bạn.
        </p>
      </aside>

      <div className="flex min-w-0 flex-col">
        <DemoBanner />
        <header className="sticky top-0 z-20 border-b border-line bg-paper/92 backdrop-blur supports-[backdrop-filter]:bg-paper/80">
          <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-x-3 gap-y-2 px-4 py-2.5 md:px-8">
            <div className="flex items-center gap-3">
              <div className="md:hidden"><Brand /></div>
              <ReadOnlyBadge />
            </div>
            <div className="flex items-center gap-2">
              <Selectors />
              <PrivacyToggle />
              <Freshness />
            </div>
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl px-4 pb-28 pt-5 md:px-8 md:pb-12">
          <PrivateOutlet />
        </main>
      </div>

      <MobileNav />
    </div>
  );
}

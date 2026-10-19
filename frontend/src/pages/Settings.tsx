import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { OtpForm } from "../components/OtpForm";
import { QueryState } from "../components/QueryState";
import { TelegramSettings } from "../components/TelegramSettings";
import { DataSourceSettings } from "../components/DataSourceSettings";
import { Button, Eyebrow, Field, Panel, inputCls } from "../components/ui";
import { api, ApiError, tokenStore } from "../lib/api";
import { cn, fmtTime } from "../lib/format";
import { useRuleChanges, useRules } from "../lib/hooks";
import { useSelection } from "../lib/selection";
import { useTheme, type ThemePref } from "../lib/theme";
import type { RulesResponse } from "../lib/types";

// ---------- kết nối broker ----------

function Brokers() {
  const { brokers } = useSelection();
  return (
    <section aria-labelledby="brk" className="space-y-3">
      <Eyebrow>Kết nối broker</Eyebrow>
      <div id="brk" className="grid gap-3 lg:grid-cols-2">
        {brokers.map((b) => {
          const s = b.session;
          return (
            <Panel key={b.name} className="p-4" as="article">
              <div className="flex items-center justify-between gap-3">
                <h3 className="display text-xl">{b.display_name}</h3>
                <span className={cn("eyebrow", s.authenticated ? "!text-ok" : s.configured ? "!text-amber" : "!text-lead")}>
                  {s.authenticated ? "Đã kết nối" : s.configured ? "Cần đăng nhập" : "Chưa cấu hình"}
                </span>
              </div>
              {s.expires_at && <p className="mt-1 text-sm text-muted">Token còn hiệu lực tới {fmtTime(s.expires_at)}.</p>}
              {s.message && <p className="mt-1 text-sm text-muted">{s.message}</p>}
              {s.needs_otp && <div className="mt-3"><OtpForm broker={b.name} displayName={b.display_name} compact /></div>}
            </Panel>
          );
        })}
      </div>
      <p className="text-xs text-muted">Khóa API nằm trong backend/.env, không bao giờ gửi tới trình duyệt. Ứng dụng chỉ dùng các API đọc dữ liệu.</p>
    </section>
  );
}

// ---------- bộ luật ----------

type FieldSpec = { path: string; label: string; unit?: string; min: number; max: number; step: number; hint: string };
const GROUPS: { title: string; fields: FieldSpec[] }[] = [
  { title: "Cắt lỗ", fields: [
    { path: "stop_loss.pct", label: "Cắt lỗ từ giá vốn", unit: "%", min: 1, max: 15, step: 0.5, hint: "O'Neil 7–8%, Minervini không quá 10%." },
    { path: "stop_loss.atr_multiplier", label: "Hệ số ATR", unit: "×", min: 0.5, max: 6, step: 0.25, hint: "Mức cắt lỗ = giá vốn − hệ số × ATR14. Lấy mức gần giá hơn." },
    { path: "stop_loss.weak_market_pct", label: "Cắt lỗ khi thị trường yếu", unit: "%", min: 1, max: 15, step: 0.5, hint: "Áp dụng khi VN-Index dưới SMA200." },
    { path: "stop_loss.time_stop_sessions", label: "Cắt lỗ theo thời gian", unit: "phiên", min: 3, max: 60, step: 1, hint: "Giữ quá số phiên này mà chưa lãi đủ thì bán." },
    { path: "stop_loss.time_stop_min_gain_pct", label: "Lãi tối thiểu để tiếp tục giữ", unit: "%", min: 0, max: 20, step: 0.5, hint: "Dùng cùng với cắt lỗ theo thời gian." },
  ] },
  { title: "Chốt lời", fields: [
    { path: "take_profit.trailing.atr_multiplier", label: "Hệ số trailing Chandelier", unit: "×", min: 1, max: 6, step: 0.25, hint: "Dải thường dùng 2,5 đến 3,5." },
    { path: "take_profit.weak_market_exit_gain_pct", label: "Chốt hết khi thị trường yếu", unit: "% lãi", min: 3, max: 30, step: 1, hint: "Thị trường yếu: chốt toàn bộ ở mức lãi này." },
  ] },
  { title: "Hàng kẹt", fields: [
    { path: "trapped.loss_pct_threshold", label: "Coi là hàng kẹt khi lỗ từ", unit: "%", min: 3, max: 30, step: 0.5, hint: "Từ mức này mã chuyển sang giao thức thoát hàng kẹt." },
    { path: "trapped.group_b_sell_now_pct", label: "Nhóm B bán ngay", unit: "%", min: 10, max: 100, step: 5, hint: "Phần còn lại bán khi giá chạm SMA20 hoặc sau 10 phiên." },
    { path: "dca.catastrophe_stop_pct", label: "Ngưỡng thảm hoạ của DCA", unit: "%", min: 5, max: 60, step: 1, hint: "DCA chỉ có ngưỡng này, không có cắt lỗ thường." },
  ] },
  { title: "Ký quỹ và cảnh báo", fields: [
    { path: "margin.rtt_buffer_pct_points", label: "Biên an toàn trên ngưỡng duy trì", unit: "điểm %", min: 2, max: 30, step: 1, hint: "RTT mục tiêu = duy trì + biên này. Dùng để tính tiền cần nộp." },
    { path: "alerts.rtt_warn_points", label: "Cảnh báo RTT khi còn cách", unit: "điểm %", min: 2, max: 30, step: 1, hint: "RTT cách ngưỡng duy trì dưới mức này thì cảnh báo." },
    { path: "alerts.portfolio_loss_pct_nav", label: "Cảnh báo lỗ danh mục từ", unit: "% NAV", min: 1, max: 60, step: 1, hint: "Tính trên lỗ chưa thực hiện." },
    { path: "margin.interest_alert_pct_nav_per_day", label: "Cảnh báo lãi vay mỗi ngày từ", unit: "% NAV", min: 0.01, max: 1, step: 0.01, hint: "Lãi margin mỗi ngày so với NAV." },
  ] },
];

type Rec = Record<string, unknown>;
const getPath = (o: Rec, p: string): unknown => p.split(".").reduce<unknown>((a, k) => (a && typeof a === "object" ? (a as Rec)[k] : undefined), o);
function setPath(o: Rec, p: string, v: unknown) {
  const ks = p.split(".");
  let cur = o;
  ks.slice(0, -1).forEach((k) => { cur = (cur[k] ??= {}) as Rec; });
  cur[ks[ks.length - 1]] = v;
}

function RulesEditor({ data }: { data: RulesResponse }) {
  const qc = useQueryClient();
  const { sel } = useSelection();
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [confirm, setConfirm] = useState<string | null>(null);
  const eff = data.effective as Rec;
  const def = data.defaults as Rec;
  const val = (p: string) => draft[p] ?? String(getPath(eff, p));

  const patch = useMemo(() => {
    const out: Rec = {};
    for (const [p, v] of Object.entries(draft)) {
      const n = Number(v);
      if (v !== "" && !Number.isNaN(n) && n !== getPath(eff, p)) setPath(out, p, n);
    }
    return out;
  }, [draft, eff]);
  const dirty = Object.keys(patch).length > 0;

  const done = () => { setDraft({}); setConfirm(null); void qc.invalidateQueries(); };
  const save = useMutation({
    mutationFn: (force: boolean) => api.putRules(patch, force, sel.broker),
    onSuccess: done,
    onError: (e) => { if (e instanceof ApiError && e.code === "OPEN_POSITIONS") setConfirm(e.message); },
  });
  const reset = useMutation({ mutationFn: () => api.resetRules(sel.broker), onSuccess: done });
  const err = save.error instanceof ApiError && save.error.code !== "OPEN_POSITIONS" ? save.error.message : null;

  return (
    <section aria-labelledby="rules" className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <Eyebrow>Bộ luật giao dịch</Eyebrow>
        {data.has_overrides && <span className="text-xs text-amber">Đang dùng tham số đã chỉnh, khác mặc định.</span>}
      </div>
      <p id="rules" className="max-w-2xl text-sm text-muted">
        Chỉ đổi tham số khi không có vị thế mở, để tránh sửa luật cho hợp cảm xúc lúc đang lỗ. Mọi lần đổi đều được ghi vào nhật ký bên dưới.
        Tham số vào lệnh và chia đợt mua nằm trong docs/trading-rules.md và chưa có màn hình ở đây.
      </p>

      <form className="space-y-5" onSubmit={(e) => { e.preventDefault(); save.mutate(false); }}>
        {GROUPS.map((g) => (
          <Panel key={g.title} className="p-4">
            <h3 className="display mb-3 text-lg">{g.title}</h3>
            <div className="grid gap-x-5 gap-y-4 sm:grid-cols-2">
              {g.fields.map((f) => {
                const changed = draft[f.path] !== undefined && Number(draft[f.path]) !== getPath(eff, f.path);
                return (
                  <Field key={f.path} label={`${f.label}${f.unit ? ` (${f.unit})` : ""}`} hint={`${f.hint} Mặc định ${String(getPath(def, f.path))}.`}>
                    <input type="number" inputMode="decimal" className={cn(inputCls, "num", changed && "border-sea")} value={val(f.path)}
                           min={f.min} max={f.max} step={f.step} onChange={(e) => setDraft((d) => ({ ...d, [f.path]: e.target.value }))} />
                  </Field>
                );
              })}
            </div>
          </Panel>
        ))}

        {confirm && (
          <div role="alertdialog" aria-labelledby="cf" className="rounded-md border border-amber/60 bg-amber-soft p-4">
            <p id="cf" className="text-sm text-amber">{confirm}</p>
            <div className="mt-3 flex gap-2">
              <Button variant="primary" onClick={() => save.mutate(true)}>Vẫn lưu thay đổi</Button>
              <Button variant="ghost" onClick={() => setConfirm(null)}>Hủy</Button>
            </div>
          </div>
        )}
        {err && <p role="alert" className="text-sm text-lead">{err}</p>}
        {save.isSuccess && !dirty && <p role="status" className="text-sm text-ok">Đã lưu bộ luật.</p>}

        <div className="flex flex-wrap gap-2">
          <Button type="submit" variant="primary" disabled={!dirty || save.isPending}>{save.isPending ? "Đang lưu…" : "Lưu thay đổi"}</Button>
          <Button onClick={() => setDraft({})} disabled={!dirty}>Bỏ chỉnh sửa</Button>
          <Button variant="ghost" onClick={() => { if (window.confirm("Đưa toàn bộ tham số về mặc định?")) reset.mutate(); }} disabled={!data.has_overrides || reset.isPending}>Về mặc định</Button>
        </div>
      </form>
    </section>
  );
}

function ChangeLog() {
  const q = useRuleChanges();
  return (
    <section aria-labelledby="log" className="space-y-2">
      <Eyebrow>Nhật ký đổi luật</Eyebrow>
      <div id="log">
        <QueryState query={q}>
          {(list) => list.length === 0 ? <p className="text-sm text-muted">Chưa đổi luật lần nào.</p> : (
            <ul className="max-w-2xl divide-y divide-line rounded-md border border-line bg-panel text-sm">
              {list.map((c) => (
                <li key={c.at} className="p-3">
                  <p className="text-xs text-muted">{new Date(c.at).toLocaleString("vi-VN")}{c.had_open_positions && <span className="ml-2 text-amber">đổi khi đang có vị thế mở</span>}</p>
                  <ul className="num mt-1 text-xs">
                    {Object.entries(c.diff).map(([k, d]) => <li key={k}>{k}: {JSON.stringify(d.from)} → {JSON.stringify(d.to)}</li>)}
                  </ul>
                </li>
              ))}
            </ul>
          )}
        </QueryState>
      </div>
    </section>
  );
}

// ---------- giao diện và dữ liệu ----------

function Preferences() {
  const [theme, setTheme] = useTheme();
  const [token, setToken] = useState(tokenStore.get());
  const { sel } = useSelection();
  const qc = useQueryClient();
  const snaps = useQuery({ queryKey: ["snapshots-count", sel.broker, sel.account], queryFn: () => api.snapshots(sel, 365), enabled: !!sel.broker, retry: false });
  const run = useMutation({ mutationFn: () => api.runSnapshot(sel), onSuccess: () => void qc.invalidateQueries({ queryKey: ["snapshots-count"] }) });

  return (
    <section aria-labelledby="pref" className="grid gap-6 lg:grid-cols-2">
      <Panel className="p-4" as="div">
        <h3 id="pref" className="display mb-3 text-lg">Giao diện</h3>
        <div role="group" aria-label="Chế độ sáng tối" className="flex gap-2">
          {([["auto", "Theo hệ thống"], ["light", "Sáng"], ["dark", "Tối"]] as [ThemePref, string][]).map(([v, l]) => (
            <button key={v} type="button" aria-pressed={theme === v} onClick={() => setTheme(v)}
              className={cn("min-h-10 rounded-md border px-3 text-sm font-medium", theme === v ? "border-ink bg-ink text-paper" : "border-line")}>{l}</button>
          ))}
        </div>
        <form className="mt-5" onSubmit={(e) => { e.preventDefault(); tokenStore.set(token.trim()); void qc.invalidateQueries(); }}>
          <Field label="Mã truy cập ứng dụng" hint="Chỉ cần khi backend đặt APP_ACCESS_TOKEN. Lưu trong trình duyệt này.">
            <div className="flex gap-2">
              <input type="password" className={`${inputCls} max-w-xs`} value={token} onChange={(e) => setToken(e.target.value)} autoComplete="off" />
              <Button type="submit">Lưu</Button>
            </div>
          </Field>
        </form>
      </Panel>
      <Panel className="p-4" as="div">
        <h3 className="display mb-1 text-lg">Snapshot hằng ngày</h3>
        <p className="text-sm text-muted">Backend tự chụp danh mục, RTT và dư nợ lúc 15:15 các ngày giao dịch để lưu lịch sử. Có thể chụp tay bất cứ lúc nào.</p>
        <p className="num mt-3 text-sm">{snaps.data ? `${snaps.data.length} snapshot đã lưu` : "—"}</p>
        <Button className="mt-3" onClick={() => run.mutate()} disabled={run.isPending}>{run.isPending ? "Đang chụp…" : "Chụp snapshot ngay"}</Button>
        {run.isError && <p role="alert" className="mt-2 text-sm text-lead">Không chụp được. Kiểm tra đăng nhập broker.</p>}
      </Panel>
    </section>
  );
}

export default function Settings() {
  const rules = useRules();
  return (
    <>
      <h1 className="display mb-5 text-3xl">Thiết lập</h1>
      <div className="space-y-9">
        <Brokers />
        <DataSourceSettings />
        <TelegramSettings />
        <QueryState query={rules}>{(d) => <RulesEditor data={d} />}</QueryState>
        <ChangeLog />
        <Preferences />
      </div>
    </>
  );
}

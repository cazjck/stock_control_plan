import { useState, type FormEvent, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Pencil, Plus, RefreshCw, Trash2, X } from "lucide-react";
import { QueryState } from "../components/QueryState";
import { Button, Empty, Field, Panel, Stat, inputCls } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { cn, daysUntil, fmtDate, fmtInt, fmtMoney, fmtPct, fmtPnlPct, fmtSigned, fmtTime, parseVnNumber, pnlStatTone, pnlTone } from "../lib/format";
import { useSelection } from "../lib/selection";
import type { LedgerAccountView, LedgerDebt, LedgerPositionView, LedgerView } from "../lib/types";

const pnlCls = pnlTone;
const errText = (e: unknown) => (e instanceof ApiError ? e.message : "Không lưu được. Thử lại.");

/** Sau mọi thay đổi ở sổ: tải lại sổ và mọi màn hình đang xem sổ tổng. */
function useLedgerMutation<T>(fn: (v: T) => Promise<unknown>, onDone?: () => void) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => { void qc.invalidateQueries(); onDone?.(); },
  });
}

function MoneyInput({ value, onChange, label, placeholder, hint }: {
  value: string; onChange: (v: string) => void; label: string; placeholder?: string; hint?: string;
}) {
  const n = parseVnNumber(value);
  return (
    <Field label={label} hint={value && n == null ? "Không đọc được số này" : value && n != null && n >= 1e4 ? `= ${fmtInt(n)} đồng` : hint}>
      <input className={cn(inputCls, "num", value && n == null && "border-lead")} inputMode="decimal" value={value}
             placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
    </Field>
  );
}

// ---------- đồng bộ ----------

function SyncPanel({ view }: { view: LedgerView }) {
  const { brokers } = useSelection();
  const sources = brokers.filter((b) => b.name !== "ledger");
  const [result, setResult] = useState<string | null>(null);
  const sync = useLedgerMutation((b: string) => api.ledgerSync(b).then((r) => {
    setResult(`Đã đồng bộ ${r.accounts.length} tiểu khoản, ${r.positions} mã, ${r.debts} khoản vay lúc ${fmtTime(r.synced_at)}.`);
  }));
  const synced = view.accounts.filter((a) => a.source === "sync");
  return (
    <Panel className="p-4">
      <h2 className="display text-lg">Đồng bộ từ công ty chứng khoán có API</h2>
      <p className="mt-1 max-w-2xl text-sm text-muted">
        Chép danh mục, tiền, khoản vay và tỷ lệ ký quỹ hiện tại vào sổ. Mỗi lần đồng bộ thay toàn bộ phần đã chép trước đó.
        Phần nhập tay của SSI, VPS không bị ảnh hưởng. Đồng bộ chỉ đọc dữ liệu, không gửi lệnh nào.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        {sources.length === 0 && <p className="text-sm text-muted">Chưa bật broker nào có API trong backend/.env.</p>}
        {sources.map((b) => (
          <Button key={b.name} variant="primary" disabled={sync.isPending || !b.session.authenticated} onClick={() => { setResult(null); sync.mutate(b.name); }}
                  title={b.session.authenticated ? undefined : "Cần đăng nhập ở trang Thiết lập trước"}>
            <RefreshCw size={15} className={sync.isPending && sync.variables === b.name ? "animate-spin" : ""} aria-hidden />
            Đồng bộ từ {b.display_name}
          </Button>
        ))}
      </div>
      {sources.some((b) => !b.session.authenticated) && (
        <p className="mt-2 text-xs text-muted">Broker chưa đăng nhập thì nút bị khoá. Nhập iOTP ở trang Thiết lập.</p>
      )}
      {result && <p role="status" className="mt-2 text-sm text-ok">{result}</p>}
      {sync.isError && <p role="alert" className="mt-2 text-sm text-lead">{errText(sync.error)}</p>}
      {synced.length > 0 && (
        <p className="mt-2 text-xs text-muted">
          Lần đồng bộ gần nhất: {synced.map((a) => `${a.name} lúc ${fmtTime(a.synced_at)} ${fmtDate(a.synced_at)}`).join(" · ")}
        </p>
      )}
    </Panel>
  );
}

// ---------- thêm / cài đặt tiểu danh mục ----------

type Kind = "equity_over_value" | "collateral_over_debt";

function MarginFields({ kind, setKind, rtt, setRtt, maint, setMaint, liq, setLiq }: {
  kind: Kind; setKind: (k: Kind) => void; rtt: string; setRtt: (v: string) => void;
  maint: string; setMaint: (v: string) => void; liq: string; setLiq: (v: string) => void;
}) {
  return (
    <>
      <Field label="Công ty tính tỷ lệ ký quỹ theo cách nào?" className="sm:col-span-2"
             hint={kind === "equity_over_value"
               ? "Ứng dụng tự tính từ cổ phiếu và nợ bạn nhập. Hợp với công ty báo tỷ lệ dạng 40%, 30%."
               : "Nhập RTT đang hiện trên app. Ứng dụng quy đổi theo giá mới. Hợp với công ty báo dạng 100%, 85% như TCBS."}>
        <select className={inputCls} value={kind} onChange={(e) => setKind(e.target.value as Kind)}>
          <option value="equity_over_value">Vốn chủ trên giá trị tài sản (tự tính)</option>
          <option value="collateral_over_debt">Tài sản đảm bảo trên dư nợ (nhập RTT từ app)</option>
        </select>
      </Field>
      {kind === "collateral_over_debt" && (
        <Field label="RTT đang hiện trên app (%)"><input className={cn(inputCls, "num")} inputMode="decimal" value={rtt} onChange={(e) => setRtt(e.target.value)} placeholder="ví dụ 120" /></Field>
      )}
      <Field label="Ngưỡng duy trì (%)" hint="Dưới mức này bị gọi ký quỹ"><input className={cn(inputCls, "num")} inputMode="decimal" value={maint} onChange={(e) => setMaint(e.target.value)} /></Field>
      <Field label="Ngưỡng giải chấp (%)" hint="Dưới mức này bị bán giải chấp"><input className={cn(inputCls, "num")} inputMode="decimal" value={liq} onChange={(e) => setLiq(e.target.value)} /></Field>
    </>
  );
}

const pct = (s: string) => (s.trim() === "" ? null : parseVnNumber(s));

function NewAccount() {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [cash, setCash] = useState("");
  const [kind, setKind] = useState<Kind>("equity_over_value");
  const [rtt, setRtt] = useState(""), [maint, setMaint] = useState(""), [liq, setLiq] = useState("");
  const m = useLedgerMutation(() => api.ledgerCreate({
    name, cash: parseVnNumber(cash) ?? 0, ratio_kind: kind, ratio_pct: kind === "collateral_over_debt" ? pct(rtt) : null,
    maintenance_pct: pct(maint), liquidation_pct: pct(liq),
  }), () => { setOpen(false); setName(""); setCash(""); setRtt(""); setMaint(""); setLiq(""); });
  if (!open) return <Button onClick={() => setOpen(true)}><Plus size={16} aria-hidden /> Thêm tiểu danh mục (SSI, VPS…)</Button>;
  return (
    <Panel className="p-4">
      <form onSubmit={(e) => { e.preventDefault(); m.mutate(undefined); }} className="space-y-4">
        <h2 className="display text-lg">Tiểu danh mục mới</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Tên" hint="Thường là tên công ty chứng khoán"><input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} placeholder="SSI" required autoFocus /></Field>
          <MoneyInput label="Tiền mặt trong tài khoản" value={cash} onChange={setCash} placeholder="0" />
          <MarginFields {...{ kind, setKind, rtt, setRtt, maint, setMaint, liq, setLiq }} />
        </div>
        {m.isError && <p role="alert" className="text-sm text-lead">{errText(m.error)}</p>}
        <div className="flex gap-2">
          <Button type="submit" variant="primary" disabled={m.isPending || !name.trim()}>Tạo tiểu danh mục</Button>
          <Button variant="ghost" onClick={() => setOpen(false)}>Hủy</Button>
        </div>
      </form>
    </Panel>
  );
}

function AccountSettings({ a, onDone }: { a: LedgerAccountView; onDone: () => void }) {
  const [cash, setCash] = useState(String(a.cash ?? 0));
  const [kind, setKind] = useState<Kind>(a.ratio_kind);
  const [rtt, setRtt] = useState(a.ratio_pct != null ? String(a.ratio_pct) : "");
  const [maint, setMaint] = useState(a.maintenance_pct != null ? String(a.maintenance_pct) : "");
  const [liq, setLiq] = useState(a.liquidation_pct != null ? String(a.liquidation_pct) : "");
  const m = useLedgerMutation(() => api.ledgerUpdate(a.id, {
    cash: parseVnNumber(cash) ?? 0, ratio_kind: kind, ratio_pct: kind === "collateral_over_debt" ? pct(rtt) : null,
    maintenance_pct: pct(maint), liquidation_pct: pct(liq),
  }), onDone);
  return (
    <form onSubmit={(e) => { e.preventDefault(); m.mutate(undefined); }} className="mt-3 space-y-3 rounded-md border border-line p-3">
      <div className="grid gap-4 sm:grid-cols-2">
        <MoneyInput label="Tiền mặt trong tài khoản" value={cash} onChange={setCash} />
        <MarginFields {...{ kind, setKind, rtt, setRtt, maint, setMaint, liq, setLiq }} />
      </div>
      {m.isError && <p role="alert" className="text-sm text-lead">{errText(m.error)}</p>}
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={m.isPending}>Lưu cài đặt</Button>
        <Button variant="ghost" onClick={onDone}>Đóng</Button>
      </div>
    </form>
  );
}

// ---------- cổ phiếu ----------

function PositionRow({ p, editable }: { p: LedgerPositionView; editable: boolean }) {
  const [edit, setEdit] = useState(false);
  const [qty, setQty] = useState(String(p.quantity));
  const [cost, setCost] = useState(String(p.avg_cost));
  const [price, setPrice] = useState(p.last_price ? String(p.last_price) : "");
  const save = useLedgerMutation(() => api.ledgerUpdatePosition(p.id, {
    quantity: Math.round(parseVnNumber(qty) ?? p.quantity), avg_cost: parseVnNumber(cost) ?? p.avg_cost,
    ...(price && parseVnNumber(price) ? { last_price: parseVnNumber(price)! } : {}),
  }), () => setEdit(false));
  const del = useLedgerMutation(() => api.ledgerDeletePosition(p.id));
  const cell = "num px-3 py-2 text-right";
  if (edit) {
    return (
      <tr className="bg-sea-soft/40">
        <td className="px-3 py-2 font-medium">{p.symbol}</td>
        <td className="px-1 py-1"><input aria-label="Số lượng" className={cn(inputCls, "num text-right")} value={qty} onChange={(e) => setQty(e.target.value)} /></td>
        <td className="px-1 py-1"><input aria-label="Giá vốn" className={cn(inputCls, "num text-right")} value={cost} onChange={(e) => setCost(e.target.value)} /></td>
        <td className={cell}>—</td>
        <td className="px-1 py-1"><input aria-label="Giá tham khảo khi không có giá thị trường" className={cn(inputCls, "num text-right")} value={price} onChange={(e) => setPrice(e.target.value)} placeholder="giá tham khảo" /></td>
        <td className={cell}>{save.isError ? <span className="text-lead">{errText(save.error)}</span> : ""}</td>
        <td className="px-3 py-2 text-right whitespace-nowrap">
          <button type="button" aria-label="Lưu" onClick={() => save.mutate(undefined)} className="inline-flex size-9 items-center justify-center rounded-md hover:bg-sea-soft"><Check size={16} /></button>
          <button type="button" aria-label="Hủy" onClick={() => setEdit(false)} className="inline-flex size-9 items-center justify-center rounded-md hover:bg-sea-soft"><X size={16} /></button>
        </td>
      </tr>
    );
  }
  return (
    <tr>
      <td className="px-3 py-2 font-medium">{p.symbol}</td>
      <td className={cell}>{fmtInt(p.quantity)}</td>
      <td className={cell}>{fmtInt(p.avg_cost)}</td>
      <td className={cell}>{fmtMoney(p.cost_value)}</td>
      <td className={cell}>{fmtInt(p.price)}{p.price != null && !p.price_is_live && <span className="ml-1 text-[10px] text-muted" title="Không có giá thị trường, đang dùng giá đã ghi">ghi</span>}</td>
      <td className={cn(cell, pnlCls(p.pnl))}>{p.pnl_pct != null ? <>{fmtPnlPct(p.pnl_pct)}<br /><span className="text-xs">{fmtSigned(p.pnl)}</span></> : "—"}</td>
      <td className="px-3 py-2 text-right whitespace-nowrap">
        {editable && <>
          <button type="button" aria-label={`Sửa ${p.symbol}`} onClick={() => setEdit(true)} className="inline-flex size-9 items-center justify-center rounded-md text-muted hover:bg-sea-soft hover:text-ink"><Pencil size={15} /></button>
          <button type="button" aria-label={`Xoá ${p.symbol}`} disabled={del.isPending}
                  onClick={() => { if (window.confirm(`Xoá ${p.symbol} khỏi sổ?`)) del.mutate(undefined); }}
                  className="inline-flex size-9 items-center justify-center rounded-md text-muted hover:bg-lead-soft hover:text-lead"><Trash2 size={15} /></button>
        </>}
      </td>
    </tr>
  );
}

function PurchaseForm({ accountId }: { accountId: string }) {
  const [symbol, setSymbol] = useState("");
  const [qty, setQty] = useState("");
  const [mode, setMode] = useState<"price" | "total">("price");
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState("");
  const q = parseVnNumber(qty), v = parseVnNumber(amount);
  const avg = q && v ? (mode === "price" ? v : v / q) : null;
  const m = useLedgerMutation(() => api.ledgerPurchase(accountId, {
    symbol: symbol.trim().toUpperCase(), quantity: Math.round(q ?? 0),
    ...(mode === "price" ? { price: v ?? 0 } : { total_amount: v ?? 0 }), bought_at: date || null,
  }), () => { setSymbol(""); setQty(""); setAmount(""); setDate(""); });
  const submit = (e: FormEvent) => { e.preventDefault(); m.mutate(undefined); };
  return (
    <form onSubmit={submit} className="mt-3 rounded-md border border-dashed border-line p-3">
      <p className="mb-2 text-sm font-medium">Ghi lệnh mua</p>
      <div className="grid gap-3 sm:grid-cols-[6rem_8rem_1fr_10rem]">
        <Field label="Mã"><input className={cn(inputCls, "uppercase")} value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="HPG" maxLength={10} required /></Field>
        <Field label="Số lượng"><input className={cn(inputCls, "num")} inputMode="numeric" value={qty} onChange={(e) => setQty(e.target.value)} placeholder="1.000" required /></Field>
        <div>
          <div role="group" aria-label="Cách nhập tiền" className="mb-1 flex gap-1 text-xs">
            {([["price", "Giá mỗi cổ phiếu"], ["total", "Tổng tiền mua"]] as const).map(([k, l]) => (
              <button key={k} type="button" aria-pressed={mode === k} onClick={() => setMode(k)}
                      className={cn("rounded-sm border px-2 py-1 font-medium", mode === k ? "border-ink bg-ink text-paper" : "border-line")}>{l}</button>
            ))}
          </div>
          <input aria-label={mode === "price" ? "Giá mỗi cổ phiếu" : "Tổng tiền mua"} className={cn(inputCls, "num", amount && v == null && "border-lead")}
                 inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder={mode === "price" ? "28.000" : "28tr"} required />
          <p className="mt-1 text-xs text-muted">{avg ? `Giá vốn của lần mua này: ${fmtInt(avg)} đồng/cp` : "Gõ được 28.000, 28tr, 1,2 tỷ"}</p>
        </div>
        <Field label="Ngày mua (tuỳ chọn)"><input type="date" className={inputCls} value={date} onChange={(e) => setDate(e.target.value)} /></Field>
      </div>
      <p className="mt-2 text-xs text-muted">Mua thêm mã đã có sẽ cộng dồn số lượng và tính lại giá vốn bình quân.</p>
      {m.isError && <p role="alert" className="mt-1 text-sm text-lead">{errText(m.error)}</p>}
      <Button type="submit" variant="primary" className="mt-2" disabled={m.isPending || !symbol || !q || !v}>Ghi lệnh mua</Button>
    </form>
  );
}

// ---------- nợ margin ----------

function DebtRow({ d, editable }: { d: LedgerDebt; editable: boolean }) {
  const [edit, setEdit] = useState(false);
  const [rem, setRem] = useState(String(d.remaining_principal));
  const [intr, setIntr] = useState(String(d.accrued_interest ?? 0));
  const save = useLedgerMutation(() => api.ledgerUpdateDebt(d.id, {
    remaining_principal: parseVnNumber(rem) ?? d.remaining_principal, accrued_interest: parseVnNumber(intr) ?? 0,
  }), () => setEdit(false));
  const del = useLedgerMutation(() => api.ledgerDeleteDebt(d.id));
  const days = daysUntil(d.due_date);
  const cell = "num px-3 py-2 text-right";
  return (
    <tr className={edit ? "bg-sea-soft/40" : ""}>
      <td className="px-3 py-2">{d.symbol ?? "—"}</td>
      <td className={edit ? "px-1 py-1" : cell}>{edit ? <input aria-label="Nợ gốc còn lại" className={cn(inputCls, "num text-right")} value={rem} onChange={(e) => setRem(e.target.value)} /> : fmtMoney(d.remaining_principal)}</td>
      <td className={edit ? "px-1 py-1" : cell}>{edit ? <input aria-label="Lãi dồn" className={cn(inputCls, "num text-right")} value={intr} onChange={(e) => setIntr(e.target.value)} /> : fmtMoney(d.accrued_interest)}</td>
      <td className={cell}>{d.annual_rate_pct != null ? fmtPct(d.annual_rate_pct) : "—"}</td>
      <td className="num px-3 py-2">{fmtDate(d.due_date)}{days != null && <span className={cn("ml-2 text-xs", days <= 7 ? "text-amber" : "text-muted")}>{days < 0 ? `quá ${-days} ngày` : `còn ${days} ngày`}</span>}</td>
      <td className="px-3 py-2 text-right whitespace-nowrap">
        {editable && (edit ? <>
          <button type="button" aria-label="Lưu" onClick={() => save.mutate(undefined)} className="inline-flex size-9 items-center justify-center rounded-md hover:bg-sea-soft"><Check size={16} /></button>
          <button type="button" aria-label="Hủy" onClick={() => setEdit(false)} className="inline-flex size-9 items-center justify-center rounded-md hover:bg-sea-soft"><X size={16} /></button>
        </> : <>
          <button type="button" aria-label="Sửa khoản nợ" onClick={() => setEdit(true)} className="inline-flex size-9 items-center justify-center rounded-md text-muted hover:bg-sea-soft hover:text-ink"><Pencil size={15} /></button>
          <button type="button" aria-label="Xoá khoản nợ" onClick={() => { if (window.confirm("Xoá khoản nợ này?")) del.mutate(undefined); }}
                  className="inline-flex size-9 items-center justify-center rounded-md text-muted hover:bg-lead-soft hover:text-lead"><Trash2 size={15} /></button>
        </>)}
      </td>
    </tr>
  );
}

function DebtForm({ accountId }: { accountId: string }) {
  const [principal, setPrincipal] = useState("");
  const [rate, setRate] = useState("");
  const [due, setDue] = useState("");
  const [symbol, setSymbol] = useState("");
  const p = parseVnNumber(principal);
  const m = useLedgerMutation(() => api.ledgerAddDebt(accountId, {
    principal: p ?? 0, annual_rate_pct: rate ? parseVnNumber(rate) : null, due_date: due || null,
    symbol: symbol.trim().toUpperCase() || null,
  }), () => { setPrincipal(""); setRate(""); setDue(""); setSymbol(""); });
  return (
    <form onSubmit={(e) => { e.preventDefault(); m.mutate(undefined); }} className="mt-3 rounded-md border border-dashed border-line p-3">
      <p className="mb-2 text-sm font-medium">Thêm khoản nợ margin</p>
      <div className="grid gap-3 sm:grid-cols-4">
        <MoneyInput label="Nợ gốc" value={principal} onChange={setPrincipal} placeholder="150tr" />
        <Field label="Lãi suất (%/năm)"><input className={cn(inputCls, "num")} inputMode="decimal" value={rate} onChange={(e) => setRate(e.target.value)} placeholder="13,5" /></Field>
        <Field label="Ngày đáo hạn"><input type="date" className={inputCls} value={due} onChange={(e) => setDue(e.target.value)} /></Field>
        <Field label="Mã vay (tuỳ chọn)"><input className={cn(inputCls, "uppercase")} value={symbol} onChange={(e) => setSymbol(e.target.value)} maxLength={10} /></Field>
      </div>
      <p className="mt-2 text-xs text-muted">Nếu app chỉ hiện tổng dư nợ, nhập một khoản bằng tổng đó là đủ để tính tỷ lệ ký quỹ và lãi mỗi ngày.</p>
      {m.isError && <p role="alert" className="mt-1 text-sm text-lead">{errText(m.error)}</p>}
      <Button type="submit" variant="primary" className="mt-2" disabled={m.isPending || !p}>Thêm khoản nợ</Button>
    </form>
  );
}

// ---------- một tiểu danh mục ----------

function Table({ head, children, caption, min }: { head: string[]; children: ReactNode; caption: string; min: string }) {
  return (
    <div className="scroll-x mt-2 rounded-md border border-line">
      <table className={cn("w-full text-sm", min)}>
        <caption className="sr-only">{caption}</caption>
        <thead><tr className="border-b border-line text-left">
          {head.map((h, i) => <th key={h || i} scope="col" className={cn("eyebrow px-3 py-2 font-normal", i > 0 && i < head.length - 1 && "text-right")}>{h}</th>)}
        </tr></thead>
        <tbody className="divide-y divide-line">{children}</tbody>
      </table>
    </div>
  );
}

function AccountCard({ a }: { a: LedgerAccountView }) {
  const [settings, setSettings] = useState(false);
  const manual = a.source === "manual";
  const del = useLedgerMutation(() => api.ledgerDelete(a.id));
  const t = a.totals;
  return (
    <Panel className="p-4 sm:p-5" as="article">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="display text-2xl leading-tight">{a.name}</h3>
          <p className="text-xs text-muted">
            {manual ? "Nhập tay" : `Đồng bộ từ ${a.source_broker?.toUpperCase()} lúc ${fmtTime(a.synced_at)} ${fmtDate(a.synced_at)}. Muốn cập nhật thì đồng bộ lại.`}
            {a.maintenance_pct != null && ` · duy trì ${fmtPct(a.maintenance_pct, 0)}`}
            {a.liquidation_pct != null && ` · giải chấp ${fmtPct(a.liquidation_pct, 0)}`}
            {a.ratio_kind === "collateral_over_debt" && a.ratio_pct != null && ` · RTT ghi nhận ${fmtPct(a.ratio_pct)}`}
          </p>
        </div>
        <div className="flex gap-1">
          {manual && <Button variant="ghost" onClick={() => setSettings((v) => !v)}>Cài đặt ký quỹ</Button>}
          <Button variant="ghost" onClick={() => { if (window.confirm(`Xoá "${a.name}" cùng toàn bộ cổ phiếu và khoản nợ trong đó?`)) del.mutate(undefined); }}>
            <Trash2 size={15} aria-hidden /> Xoá
          </Button>
        </div>
      </div>
      {settings && <AccountSettings a={a} onDone={() => setSettings(false)} />}

      <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-5">
        <Stat label="Giá trị cổ phiếu" value={fmtMoney(t.value)} />
        <Stat label="Giá vốn" value={fmtMoney(t.cost)} />
        <Stat label="Lãi lỗ" value={fmtSigned(t.pnl)} tone={pnlStatTone(t.pnl)}
              sub={t.cost ? fmtPnlPct(((t.pnl ?? 0) / t.cost) * 100) : undefined} />
        <Stat label="Nợ margin" value={fmtMoney(t.debt)} />
        <Stat label="Tiền mặt" value={fmtMoney(t.cash)} />
      </dl>

      <h4 className="eyebrow mt-5">Cổ phiếu</h4>
      {a.positions.length === 0 ? <p className="mt-1 text-sm text-muted">Chưa có mã nào.</p> : (
        <Table caption={`Cổ phiếu trong ${a.name}`} min="min-w-[44rem]" head={["Mã", "Số lượng", "Giá vốn", "Tổng vốn", "Giá hiện tại", "Lãi lỗ", ""]}>
          {a.positions.map((p) => <PositionRow key={p.id} p={p} editable={manual} />)}
        </Table>
      )}
      {manual && <PurchaseForm accountId={a.id} />}

      <h4 className="eyebrow mt-5">Nợ margin</h4>
      {a.debts.length === 0 ? <p className="mt-1 text-sm text-muted">Không có khoản nợ.</p> : (
        <Table caption={`Nợ margin của ${a.name}`} min="min-w-[40rem]" head={["Mã", "Nợ gốc còn lại", "Lãi dồn", "Lãi suất", "Đáo hạn", ""]}>
          {a.debts.map((d) => <DebtRow key={d.id} d={d} editable={manual} />)}
        </Table>
      )}
      {manual && <DebtForm accountId={a.id} />}
    </Panel>
  );
}

// ---------- trang ----------

export default function Ledger() {
  const q = useQuery({ queryKey: ["ledger"], queryFn: api.ledger });
  const { setBroker, brokers } = useSelection();
  const nav = useNavigate();
  const hasLedger = brokers.some((b) => b.name === "ledger");
  return (
    <>
      <h1 className="display text-3xl">Sổ danh mục</h1>
      <p className="mt-1 max-w-2xl text-sm text-muted">
        Gom mọi tài khoản về một chỗ để dồn nguồn lực vào chỗ rủi ro nhất. Công ty chưa có API như SSI, VPS thì nhập tay.
        TCBS thì đồng bộ. Sổ chỉ ghi trên máy của bạn, không gửi lệnh tới công ty nào.
      </p>
      <div className="mt-5">
        <QueryState query={q}>
          {(v) => (
            <div className="space-y-6">
              <Panel className="p-4 sm:p-5">
                <div className="flex flex-wrap items-end justify-between gap-4">
                  <dl className="grid flex-1 grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
                    <Stat label="Tổng giá trị cổ phiếu" value={fmtMoney(v.totals.value)} />
                    <Stat label="Tổng lãi lỗ" value={fmtSigned(v.totals.pnl)} tone={pnlStatTone(v.totals.pnl)}
                          sub={v.totals.cost ? fmtPnlPct(((v.totals.pnl ?? 0) / v.totals.cost) * 100) : undefined} />
                    <Stat label="Tổng nợ margin" value={fmtMoney(v.totals.debt)} />
                    <Stat label="Tài sản ròng" value={fmtMoney(v.totals.nav)} />
                  </dl>
                  {hasLedger && v.accounts.length > 0 && (
                    <Button variant="primary" onClick={() => { setBroker("ledger"); nav("/"); }}>Xem rủi ro của sổ tổng</Button>
                  )}
                </div>
                <p className="mt-3 text-xs text-muted">
                  {v.price_source ? `Giá thị trường lấy từ ${v.price_source}.` : "Chưa có nguồn giá thị trường: đăng nhập TCBS để cập nhật giá. Hiện dùng giá đã ghi trong sổ."}
                </p>
              </Panel>
              <SyncPanel view={v} />
              <NewAccount />
              {v.accounts.length === 0
                ? <Empty title="Sổ còn trống">Bấm đồng bộ để chép danh mục TCBS, hoặc thêm tiểu danh mục SSI, VPS rồi ghi lệnh mua.</Empty>
                : v.accounts.map((a) => <AccountCard key={a.id} a={a} />)}
            </div>
          )}
        </QueryState>
      </div>
    </>
  );
}

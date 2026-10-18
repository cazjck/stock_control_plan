import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Check, CircleAlert, Info, X } from "lucide-react";
import { Button, Field, Panel, Stat, inputCls } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { cn, fmtInt, fmtMoney, fmtPct, parseVnNumber } from "../lib/format";
import { useMargin } from "../lib/hooks";
import { maskText } from "../lib/privacy";
import { useSelection } from "../lib/selection";
import type { PreTradeCheck, PreTradeItem } from "../lib/types";

const VERDICT = {
  blocked: { label: "Không nên mua", cls: "border-lead bg-lead-soft text-lead" },
  caution: { label: "Cân nhắc", cls: "border-amber bg-amber-soft text-amber" },
  ok: { label: "Được mua theo luật", cls: "border-ok bg-ok-soft text-ok" },
} as const;

function ItemIcon({ s }: { s: PreTradeItem["status"] }) {
  if (s === "pass") return <Check size={16} className="mt-0.5 shrink-0 text-ok" aria-label="đạt" />;
  if (s === "fail") return <X size={16} className="mt-0.5 shrink-0 text-lead" aria-label="không đạt" />;
  if (s === "warn") return <CircleAlert size={16} className="mt-0.5 shrink-0 text-amber" aria-label="cần cân nhắc" />;
  return <Info size={16} className="mt-0.5 shrink-0 text-muted" aria-label="thông tin" />;
}

function Result({ c }: { c: PreTradeCheck }) {
  const v = VERDICT[c.verdict];
  const order = { fail: 0, warn: 1, info: 2, pass: 3 } as const;
  const items = [...c.items].sort((a, b) => order[a.status] - order[b.status]);
  return (
    <div className="space-y-4">
      <div className={cn("rounded-md border-2 p-4", v.cls)}>
        <p className="display text-2xl">{v.label}</p>
        <p className="mt-1 text-[15px] text-ink">{maskText(c.headline)}</p>
        <p className="num mt-1 text-sm text-muted">{c.symbol}: {fmtInt(c.quantity)} cp × {fmtInt(c.price)} = {fmtMoney(c.value)}</p>
      </div>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
        <Stat label="Tối đa theo luật" value={`${fmtInt(c.max_qty)} cp`} sub="theo rủi ro 1R và tỷ trọng" />
        <Stat label="Cắt lỗ nếu mua" value={fmtInt(c.stop_price)} />
        {c.margin && <Stat label="Tỷ lệ ký quỹ nếu mua bằng tiền vay" value={c.margin.ratio_after != null ? fmtPct(c.margin.ratio_after, 1) : "—"}
          sub={`hiện ${c.margin.ratio_before != null ? fmtPct(c.margin.ratio_before, 1) : "—"}, duy trì ${c.margin.maintenance_pct ?? "—"}%`} tone="lead" />}
        {c.margin && <Stat label="Nếu dùng tiền đó trả nợ" value={`−${fmtMoney(c.margin.interest_saved_if_repay)}/ngày`} sub="tiền lãi margin" tone="ok" />}
      </dl>
      <ul className="divide-y divide-line rounded-md border border-line" aria-label="Các kiểm tra">
        {items.map((i) => (
          <li key={i.code} className="flex gap-2.5 px-3 py-2 text-sm">
            <ItemIcon s={i.status} />
            <span className="min-w-0">
              <span className="font-medium">{i.label}</span>{i.rule && <span className="text-xs text-muted"> · mục {i.rule}</span>}
              <span className="block text-muted">{maskText(i.detail)}</span>
            </span>
          </li>
        ))}
      </ul>
      {c.suggestion && <p className="rounded-md bg-sea-soft/60 px-3 py-2 text-[15px]">{maskText(c.suggestion)}</p>}
    </div>
  );
}

/** Bảng kiểm trước khi mua: đối chiếu lệnh mua dự định với bộ luật. Chỉ tính toán, không đặt lệnh. */
export default function PreTrade() {
  const { sel } = useSelection();
  const [params] = useSearchParams();
  const margin = useMargin();
  const [symbol, setSymbol] = useState(params.get("symbol") ?? "");
  const [qty, setQty] = useState("");
  const [price, setPrice] = useState("");
  const [account, setAccount] = useState("");
  const buckets = margin.data?.buckets ?? [];
  const m = useMutation({
    mutationFn: () => api.pretrade(sel, {
      symbol: symbol.trim().toUpperCase(), qty: parseVnNumber(qty) || undefined, price: parseVnNumber(price) || undefined,
      row_account: account || undefined,
    }),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); if (symbol.trim()) m.mutate(); };
  return (
    <>
      <h1 className="display mb-2 text-3xl">Trước khi mua</h1>
      <p className="mb-5 max-w-2xl text-sm text-muted">
        Nhập mã định mua. App đối chiếu với bộ luật đã duyệt: thị trường, vốn, số mã, mua bình quân giá xuống, ký quỹ, giai đoạn xu hướng,
        tín hiệu vào lệnh và giới hạn số lệnh mỗi ngày. Trên Telegram dùng lệnh /kiemtra MÃ SỐ_LƯỢNG.
      </p>
      <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
        <Panel className="h-fit p-4" as="div">
          <form onSubmit={submit} className="space-y-3">
            <Field label="Mã"><input className={cn(inputCls, "uppercase")} value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="PDR" required /></Field>
            <Field label="Số lượng" hint="Để trống: lấy khối lượng tối đa theo luật"><input className={cn(inputCls, "num")} inputMode="numeric" value={qty} onChange={(e) => setQty(e.target.value)} placeholder="2.000" /></Field>
            <Field label="Giá" hint="Để trống: giá hiện tại"><input className={cn(inputCls, "num")} inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} /></Field>
            {buckets.length > 1 && (
              <Field label="Mua ở tài khoản">
                <select className={inputCls} value={account} onChange={(e) => setAccount(e.target.value)}>
                  <option value="">Nơi đang giữ mã này</option>
                  {buckets.map((b) => <option key={b.bucket.id} value={b.bucket.id}>{b.bucket.source || b.bucket.label}</option>)}
                </select>
              </Field>
            )}
            <Button type="submit" variant="primary" disabled={m.isPending || !symbol.trim()}>{m.isPending ? "Đang kiểm tra…" : "Kiểm tra"}</Button>
            {m.isError && <p role="alert" className="text-sm text-lead">{m.error instanceof ApiError ? m.error.message : "Không kiểm tra được."}</p>}
          </form>
        </Panel>
        <div>{m.data ? <Result c={m.data} /> : <p className="text-sm text-muted">Kết quả hiện ở đây.</p>}</div>
      </div>
    </>
  );
}

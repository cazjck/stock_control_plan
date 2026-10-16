import { isPrivate, MASK } from "./privacy";

const nf0 = new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 0 });
const nf = (d: number) => new Intl.NumberFormat("vi-VN", { minimumFractionDigits: d, maximumFractionDigits: d });
const MINUS = "−";
const fixMinus = (s: string) => s.replace(/^-/, MINUS);

export const fmtInt = (n: number | null | undefined): string =>
  n == null || Number.isNaN(n) ? "—" : fixMinus(nf0.format(Math.round(n)));

/** Giá cổ phiếu, ví dụ 126.500 */
export const fmtPrice = fmtInt;

export function fmtPct(n: number | null | undefined, digits = 1, signed = false): string {
  if (n == null || Number.isNaN(n)) return "—";
  const s = fixMinus(nf(digits).format(n));
  return `${signed && n > 0 ? "+" : ""}${s}%`;
}

/** Số tiền gọn: 1,25 tỷ · 198,8 tr · 67,8 nghìn */
export function fmtMoney(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  if (isPrivate()) return MASK;
  const a = Math.abs(n);
  const sign = n < 0 ? MINUS : "";
  if (a >= 1e9) return `${sign}${nf(2).format(a / 1e9)} tỷ`;
  if (a >= 1e6) return `${sign}${nf(1).format(a / 1e6)} tr`;
  if (a >= 1e4) return `${sign}${nf(1).format(a / 1e3)} nghìn`;
  return fixMinus(nf0.format(n));
}

export function fmtSigned(n: number | null | undefined, f: (x: number) => string = fmtMoney): string {
  if (n == null || Number.isNaN(n)) return "—";
  if (isPrivate()) return MASK;
  return `${n > 0 ? "+" : ""}${f(n)}`;
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso.length <= 10 ? `${iso}T00:00:00` : iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric" }).format(d);
}

export function fmtTime(iso: string | Date | null | undefined): string {
  if (!iso) return "—";
  const d = typeof iso === "string" ? new Date(iso) : iso;
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("vi-VN", { hour: "2-digit", minute: "2-digit" }).format(d);
}

export function daysUntil(isoDate: string | null | undefined, today = new Date()): number | null {
  if (!isoDate) return null;
  const d = new Date(`${isoDate}T00:00:00`);
  const t = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((d.getTime() - t.getTime()) / 86_400_000);
}

export function ageText(seconds: number): string {
  if (seconds < 5) return "vừa xong";
  if (seconds < 60) return `${Math.round(seconds)} giây trước`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} phút trước`;
  return `${Math.round(seconds / 3600)} giờ trước`;
}

export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

/** Đọc số người dùng gõ theo kiểu Việt Nam: "100.000.000", "100tr", "1,2 tỷ", "25,5", "500k".
 *  Trả về null nếu không đọc được. Dấu chấm là ngăn nghìn, dấu phẩy là thập phân. */
export function parseVnNumber(input: string): number | null {
  let s = input.trim().toLowerCase().replace(/\s+/g, "");
  if (!s) return null;
  let k = 1;
  const units: [RegExp, number][] = [[/(tỷ|ty|ti|b)$/, 1e9], [/(triệu|trieu|tr|m)$/, 1e6], [/(nghìn|nghin|ngàn|ngan|k)$/, 1e3]];
  for (const [re, mul] of units) {
    if (re.test(s)) { s = s.replace(re, ""); k = mul; break; }
  }
  if (!/^[0-9.,]+$/.test(s)) return null;
  s = s.replace(/\./g, "").replace(",", ".");
  const n = Number(s);
  return Number.isFinite(n) ? n * k : null;
}

/** Phần trăm lãi lỗ: bị che khi bật chế độ che số. */
export function fmtPnlPct(n: number | null | undefined, digits = 1): string {
  if (n == null || Number.isNaN(n)) return "—";
  return isPrivate() ? MASK : fmtPct(n, digits, true);
}

/** Màu lãi lỗ: khi che số thì không tô đỏ hay xanh, để không lộ lãi hay lỗ qua màu. */
export function pnlTone(n: number | null | undefined): string {
  if (isPrivate() || n == null) return "";
  return n < 0 ? "text-lead" : n > 0 ? "text-ok" : "";
}

export function pnlStatTone(n: number | null | undefined): "lead" | "ok" | undefined {
  if (isPrivate() || !n) return undefined;
  return n < 0 ? "lead" : "ok";
}

import { useSyncExternalStore } from "react";

/** Chế độ che số tiền và lãi lỗ. Mục đích: bớt bị tác động tâm lý khi nhìn khoản lỗ,
 *  nhưng KHÔNG che những gì cần để hành động đúng luật (trạng thái, mức cắt lỗ, giá, số cổ phiếu phải bán). */
const KEY = "stockctl.privacy";
let on = (() => { try { return localStorage.getItem(KEY) === "1"; } catch { return false; } })();
const listeners = new Set<() => void>();

export const MASK = "•••";
export const isPrivate = () => on;

export function setPrivate(v: boolean) {
  on = v;
  try { v ? localStorage.setItem(KEY, "1") : localStorage.removeItem(KEY); } catch { /* bỏ qua */ }
  listeners.forEach((f) => f());
}

export function usePrivacy(): [boolean, (v: boolean) => void] {
  const v = useSyncExternalStore((cb) => { listeners.add(cb); return () => listeners.delete(cb); }, () => on, () => on);
  return [v, setPrivate];
}

const MONEY_UNIT = /[+−-]?\d[\d.]*(?:,\d+)?\s?(?:tỷ|triệu|tr|nghìn|đồng)(?![\p{L}/])/gu;
const BIG_NUMBER = /[+−-]?\d{1,3}(?:\.\d{3}){2,}(?:,\d+)?/g;          // từ 1.000.000 trở lên: số tiền
const PNL_PHRASE = /((?:lãi lỗ|đang lãi|đang lỗ|lỗ chưa thực hiện|đã lãi tới)\s)[+−-]?\d+(?:,\d+)?%/giu;
const PNL_PAREN = /\(([+−-]\d+(?:,\d+)?)%\)/g;                         // "(−11,4%)" sau tên mã
const PNL_DANG = /(đang\s)[+−-]\d+(?:,\d+)?%/giu;

/** Che số tiền và phần trăm lãi lỗ trong câu chữ từ backend; giữ giá, số cổ phiếu và ngưỡng luật. */
export function maskText(s: string | null | undefined, force?: boolean): string {
  if (!s) return s ?? "";
  if (!(force ?? on)) return s;
  return s
    .replace(PNL_PHRASE, `$1${MASK}`)
    .replace(PNL_DANG, `$1${MASK}`)
    .replace(PNL_PAREN, `(${MASK})`)
    .replace(MONEY_UNIT, MASK)
    .replace(BIG_NUMBER, MASK);
}

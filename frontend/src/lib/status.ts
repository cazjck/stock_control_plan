import type { PositionStatus, Tone } from "./types";

export interface StatusMeta {
  label: string;
  tone: "lead" | "amber" | "ok" | "sea" | "muted";
  /** ký hiệu để phân biệt trạng thái không chỉ bằng màu */
  glyph: string;
  hint: string;
}

export const STATUS: Record<PositionStatus, StatusMeta> = {
  STOP_HIT: { label: "Chạm cắt lỗ", tone: "lead", glyph: "■", hint: "Giá dưới mức cắt lỗ. Bán nếu đóng cửa dưới mức này." },
  TRAPPED: { label: "Hàng kẹt", tone: "lead", glyph: "▼", hint: "Lỗ từ 7% trở lên. Áp dụng giao thức thoát hàng kẹt." },
  TIME_STOP: { label: "Hết hạn giữ", tone: "amber", glyph: "◷", hint: "Giữ quá lâu mà chưa lãi đủ." },
  WARNING: { label: "Cảnh báo", tone: "amber", glyph: "▲", hint: "Dưới SMA20 và RSI yếu." },
  TAKE_PROFIT: { label: "Tới mốc chốt lời", tone: "ok", glyph: "◆", hint: "Đạt mốc chốt lời theo bậc." },
  SAFE: { label: "An toàn", tone: "muted", glyph: "●", hint: "Chưa chạm quy tắc nào." },
};

export const STATUS_ORDER: PositionStatus[] = ["STOP_HIT", "TRAPPED", "TIME_STOP", "WARNING", "TAKE_PROFIT", "SAFE"];

export const TONE_CLASS: Record<Tone, string> = {
  breach: "text-lead",
  danger: "text-lead",
  watch: "text-amber",
  safe: "text-ok",
  unknown: "text-muted",
};

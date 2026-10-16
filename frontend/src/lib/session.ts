/** Phiên giao dịch (thô): 9:00–15:00 các ngày thứ Hai đến thứ Sáu. Không tính ngày lễ. */
export function marketSession(now: Date = new Date()): { open: boolean; label: string } {
  const d = now.getDay();
  const h = now.getHours() + now.getMinutes() / 60;
  const weekday = d >= 1 && d <= 5;
  if (weekday && h >= 9 && h < 15) return { open: true, label: "Trong giờ giao dịch" };
  if (weekday && h < 9) return { open: false, label: "Chưa mở phiên (9:00)" };
  return { open: false, label: "Ngoài giờ giao dịch" };
}

/** "5 giờ 20 phút" hoặc "đã hết hạn". */
export function remainingText(expiresIso: string | null | undefined, now: Date = new Date()): string {
  if (!expiresIso) return "không giới hạn";
  const ms = new Date(expiresIso).getTime() - now.getTime();
  if (Number.isNaN(ms)) return "—";
  if (ms <= 0) return "đã hết hạn";
  const mins = Math.floor(ms / 60_000);
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return h > 0 ? `${h} giờ ${m} phút` : `${m} phút`;
}

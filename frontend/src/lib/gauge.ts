/** Hình học của thước mớn nước. Thuần túy để test được.
 *
 * Quy ước như vạch mớn nước thật: số TĂNG dần xuống dưới. Đỉnh thước (boong tàu) là RTT thấp, nguy hiểm.
 * Đáy thước (ky tàu) là RTT cao, an toàn. Mực nước dâng lên khi RTT giảm. */
export interface GaugeInput {
  ratio: number;
  maintenance: number;
  liquidation: number | null;
  safeTarget: number | null;
}

export interface GaugeScale {
  lo: number;
  hi: number;
  top: number;
  bottom: number;
  y: (v: number) => number;
  ticks: { v: number; major: boolean }[];
}

const floorTo = (x: number, step: number) => Math.floor(x / step) * step;
const ceilTo = (x: number, step: number) => Math.ceil(x / step) * step;

export function buildScale(g: GaugeInput, top: number, bottom: number): GaugeScale {
  const low = Math.min(g.liquidation ?? g.maintenance, g.maintenance, g.ratio);
  const high = Math.max(g.safeTarget ?? g.maintenance + 10, g.ratio);
  let lo = Math.max(0, floorTo(low - 5, 5));
  let hi = Math.min(300, ceilTo(high + 5, 5)); // RTT kiểu TCBS (tài sản đảm bảo / dư nợ) có thể vượt 100
  if (hi - lo < 20) hi = lo + 20;
  const y = (v: number) => top + ((Math.min(Math.max(v, lo), hi) - lo) / (hi - lo)) * (bottom - top);
  const ticks: { v: number; major: boolean }[] = [];
  for (let v = lo; v <= hi + 1e-9; v += 1) ticks.push({ v, major: v % 5 === 0 });
  return { lo, hi, top, bottom, y, ticks };
}

export type GaugeZone = "breach" | "danger" | "watch" | "safe";

export function zoneOf(g: GaugeInput): GaugeZone {
  if (g.liquidation != null && g.ratio <= g.liquidation) return "breach";
  if (g.ratio <= g.maintenance) return "danger";
  if (g.safeTarget != null && g.ratio <= g.safeTarget) return "watch";
  return "safe";
}

/** Đẩy các nhãn ra xa nhau để không chồng chữ, giữ trong [minY, maxY]. */
export function spreadLabels<T extends { y: number }>(
  items: T[], minGap: number, minY: number, maxY: number,
): (T & { ly: number })[] {
  const out = [...items].sort((a, b) => a.y - b.y).map((i) => ({ ...i, ly: Math.min(Math.max(i.y, minY), maxY) }));
  for (let i = 1; i < out.length; i++) {
    if (out[i].ly - out[i - 1].ly < minGap) out[i].ly = out[i - 1].ly + minGap;
  }
  for (let i = out.length - 1; i >= 0; i--) {
    const limit = maxY - (out.length - 1 - i) * minGap;
    if (out[i].ly > limit) out[i].ly = limit;
  }
  return out;
}

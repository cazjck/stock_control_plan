import type { MarginMetrics, ScenarioRequest, ScenarioState } from "./types";

/** Trạng thái các ô nhập của trang Kịch bản giả định. */
export interface ScenarioInput {
  dropPct: number;                    // thị trường giảm bao nhiêu %, số dương
  sells: Record<string, number>;      // mã → số cổ phiếu bán thử
  cashMillions: number;               // tiền nộp thêm, đơn vị triệu đồng
}

export const EMPTY_INPUT: ScenarioInput = { dropPct: 0, sells: {}, cashMillions: 0 };

const num = (x: number) => (Number.isFinite(x) ? x : 0);

export function toRequest(i: ScenarioInput): ScenarioRequest {
  return {
    market_drop_pct: Math.max(0, num(i.dropPct)),
    sell: Object.entries(i.sells)
      .filter(([, q]) => num(q) > 0)
      .map(([symbol, q]) => ({ symbol, quantity: Math.floor(q) })),
    add_cash: Math.max(0, Math.round(num(i.cashMillions) * 1_000_000)),
  };
}

export const isUnchanged = (i: ScenarioInput): boolean => {
  const r = toRequest(i);
  return r.market_drop_pct === 0 && r.sell.length === 0 && r.add_cash === 0;
};

/** Giữ số cổ phiếu bán thử trong khoảng 0 đến số đang giữ. */
export const clampQty = (raw: number, held: number): number => Math.min(Math.max(0, Math.floor(num(raw))), held);

/** Nhóm ký quỹ mà backend chọn làm đại diện (sát ngưỡng nhất) cho thước mớn nước. */
export const focusOf = (s: ScenarioState): MarginMetrics | undefined =>
  s.buckets.find((m) => m.bucket.id === s.focus_bucket_id);

/** Chênh lệch có dấu, null nếu một trong hai vế thiếu. */
export const delta = (before: number | null | undefined, after: number | null | undefined): number | null =>
  before == null || after == null ? null : after - before;

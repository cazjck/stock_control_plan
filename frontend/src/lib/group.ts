import { STATUS_ORDER } from "./status";
import type { PositionEval, PositionStatus } from "./types";

/** Một mã nắm ở nhiều nguồn: dòng nhóm để xem mức độ tập trung, các dòng con để quyết định ở từng công ty. */
export interface SymbolGroup {
  symbol: string;
  rows: PositionEval[];
  quantity: number;
  market_value: number;
  cost_value: number;
  pnl: number;
  pnl_pct: number | null;
  avg_cost: number;
  price: number;
  weight_pct: number;
  urgency: number;
  worst: PositionStatus;
}

export function groupBySymbol(rows: PositionEval[]): SymbolGroup[] {
  const by = new Map<string, PositionEval[]>();
  for (const r of rows) by.set(r.symbol, [...(by.get(r.symbol) ?? []), r]);
  return [...by.entries()].map(([symbol, rs]) => {
    const quantity = rs.reduce((s, r) => s + r.quantity, 0);
    const market_value = rs.reduce((s, r) => s + r.market_value, 0);
    const cost_value = rs.reduce((s, r) => s + r.quantity * r.avg_cost, 0);
    const pnl = market_value - cost_value;
    const sorted = [...rs].sort((a, b) => b.urgency - a.urgency);
    return {
      symbol, rows: sorted, quantity, market_value, cost_value, pnl,
      pnl_pct: cost_value ? (pnl / cost_value) * 100 : null,
      avg_cost: quantity ? cost_value / quantity : 0,
      price: rs[0].price,
      weight_pct: rs.reduce((s, r) => s + r.weight_pct, 0),
      urgency: Math.max(...rs.map((r) => r.urgency)),
      worst: STATUS_ORDER.find((s) => rs.some((r) => r.status === s)) ?? "SAFE",
    };
  });
}

/** Gộp thành một PositionEval mỗi mã, cho những chỗ làm việc theo mã (kịch bản bán thử). */
export function mergedRows(rows: PositionEval[]): PositionEval[] {
  return groupBySymbol(rows).map((g) => ({
    ...g.rows[0], quantity: g.quantity, market_value: g.market_value, avg_cost: g.avg_cost,
    pnl: g.pnl, pnl_pct: g.pnl_pct ?? 0, weight_pct: g.weight_pct,
    sources: g.rows.flatMap((r) => r.sources ?? []),
  }));
}

export const symbolLink = (r: Pick<PositionEval, "symbol" | "row_id">) =>
  r.row_id && r.row_id !== r.symbol ? `/symbol/${r.symbol}?row=${encodeURIComponent(r.row_id)}` : `/symbol/${r.symbol}`;

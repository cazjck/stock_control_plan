import { describe, expect, it } from "vitest";
import { groupBySymbol, mergedRows, symbolLink } from "./group";
import type { PositionEval } from "./types";

const row = (o: Partial<PositionEval>) => ({ symbol: "PDR", quantity: 0, avg_cost: 0, market_value: 0, weight_pct: 0, urgency: 0,
  price: 11200, status: "SAFE", sources: [], ...o }) as PositionEval;

describe("groupBySymbol", () => {
  const rows = [
    row({ row_id: "tcbs:PDR", source: "TCBS", quantity: 46_500, avg_cost: 21_400, market_value: 46_500 * 11_200, weight_pct: 40, urgency: 95, status: "TRAPPED" }),
    row({ row_id: "vps:PDR", source: "VPS", quantity: 25_800, avg_cost: 15_250, market_value: 25_800 * 11_200, weight_pct: 25, urgency: 120, status: "STOP_HIT" }),
    row({ symbol: "VIX", row_id: "vps:VIX", source: "VPS", quantity: 18_150, avg_cost: 13_934, market_value: 18_150 * 11_900, weight_pct: 20 }),
  ];
  it("gộp mã cho tổng khối lượng, tỷ trọng và giá vốn bình quân, giữ các dòng con", () => {
    const [pdr, vix] = groupBySymbol(rows);
    expect(pdr.quantity).toBe(72_300);
    expect(pdr.weight_pct).toBe(65);
    expect(pdr.avg_cost).toBeCloseTo((46_500 * 21_400 + 25_800 * 15_250) / 72_300);
    expect(pdr.rows.map((r) => r.source)).toEqual(["VPS", "TCBS"]);   // dòng khẩn nhất lên trước
    expect(pdr.worst).toBe("STOP_HIT");
    expect(vix.rows).toHaveLength(1);
  });
  it("gộp thành một dòng mỗi mã cho kịch bản", () => {
    const m = mergedRows(rows);
    expect(m.map((x) => [x.symbol, x.quantity])).toEqual([["PDR", 72_300], ["VIX", 18_150]]);
  });
  it("liên kết chi tiết mang theo nguồn", () => {
    expect(symbolLink(rows[1])).toBe("/symbol/PDR?row=vps%3APDR");
    expect(symbolLink(row({ row_id: "PDR" }))).toBe("/symbol/PDR");
  });
});

import { describe, expect, it } from "vitest";
import { mergeRow } from "./boardStream";
import type { BoardRow } from "./types";

const row = { symbol: "PDR", price: 11250, ref: 11300, held_qty: 46500, avg_cost: 21400, pnl_pct: -47.4, sources: ["TCBS"], bid: [], offer: [] } as unknown as BoardRow;

describe("mergeRow", () => {
  it("cập nhật giá và tính lại lãi lỗ theo giá mới", () => {
    const r = mergeRow(row, { price: 11500, change: 200 });
    expect(r.price).toBe(11500);
    expect(r.pnl_pct).toBeCloseTo((11500 / 21400 - 1) * 100);
  });
  it("không để cập nhật giá ghi đè các cột của bạn", () => {
    const r = mergeRow(row, { price: 11400, held_qty: 0, avg_cost: 1, sources: [] } as Partial<BoardRow>);
    expect(r.held_qty).toBe(46500);
    expect(r.avg_cost).toBe(21400);
    expect(r.sources).toEqual(["TCBS"]);
  });
});

import { describe, expect, it } from "vitest";
import { clampQty, delta, EMPTY_INPUT, focusOf, isUnchanged, toRequest } from "./scenario";
import type { ScenarioState } from "./types";

describe("toRequest", () => {
  it("đổi triệu đồng sang đồng và bỏ các dòng bán thử bằng 0", () => {
    expect(toRequest({ dropPct: 10, sells: { HPG: 3000, FPT: 0, VND: 250.7 }, cashMillions: 12.5 })).toEqual({
      market_drop_pct: 10, sell: [{ symbol: "HPG", quantity: 3000 }, { symbol: "VND", quantity: 250 }], add_cash: 12_500_000,
    });
  });
  it("không bao giờ gửi số âm hoặc không phải số", () => {
    expect(toRequest({ dropPct: -5, sells: {}, cashMillions: NaN })).toEqual({ market_drop_pct: 0, sell: [], add_cash: 0 });
    expect(toRequest({ dropPct: 5, sells: { A: -10 }, cashMillions: -3 })).toEqual({ market_drop_pct: 5, sell: [], add_cash: 0 });
  });
});

describe("isUnchanged", () => {
  it("chỉ đúng khi chưa nhập gì", () => {
    expect(isUnchanged(EMPTY_INPUT)).toBe(true);
    expect(isUnchanged({ ...EMPTY_INPUT, dropPct: 5 })).toBe(false);
    expect(isUnchanged({ ...EMPTY_INPUT, sells: { A: 100 } })).toBe(false);
    expect(isUnchanged({ ...EMPTY_INPUT, cashMillions: 1 })).toBe(false);
    expect(isUnchanged({ ...EMPTY_INPUT, sells: { A: 0 } })).toBe(true);
  });
});

describe("clampQty", () => {
  it("giữ trong khoảng 0 đến số đang giữ", () => {
    expect(clampQty(5000, 3000)).toBe(3000);
    expect(clampQty(-4, 3000)).toBe(0);
    expect(clampQty(120.9, 3000)).toBe(120);
    expect(clampQty(NaN, 3000)).toBe(0);
  });
});

describe("focusOf và delta", () => {
  const state = { focus_bucket_id: "b", buckets: [{ bucket: { id: "a" } }, { bucket: { id: "b" } }] } as unknown as ScenarioState;
  it("tìm đúng nhóm đại diện", () => {
    expect(focusOf(state)?.bucket.id).toBe("b");
    expect(focusOf({ ...state, focus_bucket_id: null })).toBeUndefined();
  });
  it("delta bỏ qua khi thiếu số", () => {
    expect(delta(44.6, 50.4)).toBeCloseTo(5.8);
    expect(delta(null, 3)).toBeNull();
  });
});

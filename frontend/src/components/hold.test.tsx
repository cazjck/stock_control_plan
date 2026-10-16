import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { SelectionProvider } from "../lib/selection";
import { HoldPanel } from "./HoldPanel";
import type { HoldStatus, PositionEval } from "../lib/types";

function wrap(hold: HoldStatus | null) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, enabled: false } } });
  return render(
    <QueryClientProvider client={qc}><MemoryRouter><SelectionProvider>
      <HoldPanel ev={{ symbol: "DXG", price: 10_000, pnl_pct: -39, account_id: "ssi", row_id: "ssi:DXG",
        indicators: { low20: 9_300 }, hold } as unknown as PositionEval} />
    </SelectionProvider></MemoryRouter></QueryClientProvider>,
  );
}

const decision = { id: 1, broker: "ledger", account_id: "ssi", symbol: "DXG", decided_at: "2026-10-16", exit_close_below: 9_020,
  ratio_floor_pct: null, review_on: "2026-11-15", reason: "Ngành bất động sản đang ở đáy chu kỳ" };

describe("HoldPanel", () => {
  it("chưa có quyết định: gợi ý giá thoát từ đáy 20 phiên trừ 3%", () => {
    wrap(null);
    expect((screen.getByLabelText(/^Giá thoát \(đóng cửa dưới\)/) as HTMLInputElement).value).toBe("9020");
    expect(screen.getByText(/Gợi ý 9.020: đáy 20 phiên 9.300 trừ 3%/)).toBeTruthy();   // chưa có kế hoạch kỹ thuật
    expect(screen.getByRole("button", { name: "Ghi quyết định gồng" })).toBeTruthy();
  });
  it("đang gồng: hiện số ngày, lãi đã trả, khoảng cách tới giá thoát và lý do", () => {
    wrap({ decision, state: "holding", text: "Đang gồng 5 ngày theo quyết định 16/10.", days_held: 5, interest_cost: 744_000,
      interest_per_day: 148_800, distance_to_exit_pct: 10.9, ratio_pct: 37.5, ratio_floor_pct: 35 });
    expect(screen.getByText("Đang gồng")).toBeTruthy();
    expect(screen.getByText("5 ngày")).toBeTruthy();
    expect(screen.getByText(/còn cách 10,9%/)).toBeTruthy();
    expect(screen.getByText(/Lý do đã ghi: Ngành bất động sản/)).toBeTruthy();
  });
  it("thủng giá thoát: nhãn kết thúc gồng", () => {
    wrap({ decision, state: "exit_price", text: "Giá đóng cửa đã thủng giá thoát.", days_held: 9, interest_cost: 1, interest_per_day: 1,
      distance_to_exit_pct: -1, ratio_pct: 37, ratio_floor_pct: 35 });
    expect(screen.getByText("Thủng giá thoát: kết thúc gồng")).toBeTruthy();
  });
});

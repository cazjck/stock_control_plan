import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { SelectionProvider } from "../lib/selection";
import { LotsPanel } from "./LotsPanel";
import type { LotEval, PositionEval } from "../lib/types";

const base: LotEval = {
  id: 1, broker: "tcbs", account_id: "0001", symbol: "PDR", buy_date: "2026-10-12", quantity: 2000, remaining: 2000,
  price: 11000, source: "manual", add_on_loss: true, stop_price: 10450, trigger_date: "2026-10-14", trigger_price: 10400,
  estimated: false, note: null, source_label: "TCBS", current_price: 10200, pnl_pct: -7.27, pnl_value: -1_600_000,
  sessions_held: 4, sellable_from: "2026-10-14", sellable: true, deadline: "2026-10-19", rule_status: "stop",
  action: "Lô mua ngày 12/10 (2.000 cp, giá 11.000) đã thủng mức cắt lỗ 10.450: bán 2.000 cp bằng ATO phiên kế tiếp. Không chờ hồi.",
  delay_sessions: 2, delay_cost: 400_000,
};

function wrap(ev: Partial<PositionEval>) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, enabled: false } } });
  return render(
    <QueryClientProvider client={qc}><MemoryRouter><SelectionProvider>
      <LotsPanel ev={{ symbol: "PDR", price: 10200, avg_cost: 23000, lots: [base], unknown_lot: { quantity: 40000, avg_cost: 24000 }, ...ev } as PositionEval} broker="tcbs" />
    </SelectionProvider></MemoryRouter></QueryClientProvider>,
  );
}

describe("LotsPanel", () => {
  it("hiện ngày mua, lãi lỗ của lô và phần chưa rõ ngày", () => {
    const { container } = wrap({});
    const t = container.textContent ?? "";
    expect(t).toContain("12/10/2026");
    expect(t).toContain("−7,3%");
    expect(t).toContain("Chưa rõ ngày");
    expect(t).toContain("40.000");
  });
  it("lô phải bán hiện hành động và chi phí chần chừ", () => {
    wrap({});
    expect(screen.getByText(/bán 2.000 cp bằng ATO/)).toBeTruthy();
    expect(screen.getByText(/Đã chần chừ 2 phiên, mất thêm 400,0 nghìn/)).toBeTruthy();
  });
  it("chưa có lô thì hướng dẫn cách có dữ liệu", () => {
    wrap({ lots: [], unknown_lot: null });
    expect(screen.getByText(/Chưa có lịch sử từng lần mua/)).toBeTruthy();
    expect(screen.getByText("Ghi một lần mua trong quá khứ")).toBeTruthy();
  });
});

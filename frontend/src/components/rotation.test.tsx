import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { SelectionProvider } from "../lib/selection";
import { RotationPanel } from "./RotationPanel";
import type { PositionEval, RotationPlan } from "../lib/types";

const plan: RotationPlan = {
  phase: "sell_zone", phase_label: "Vùng bán", level: "sell",
  text: "Nhịp hồi 12,0% từ đáy 10.000: bán 7.700 cổ phiếu (đợt 1, cộng dồn 30% lượng gốc 25.800).",
  sell_qty: 7700, rebuy_qty: 0, rebuy_allowed: false, low: 10000, high: 15000, rebound_pct: 12, retrace_pct: 24,
  tier_prices: [11000, 12000], tier_qtys: [7700, 5500], rebuy_below: null, floor: null, base_qty: 25800, sold_qty: 0, sold_avg: null,
  bought_qty: 0, open_qty: 0, sessions_since_sell: null, sessions_left: null, checks: [], trades: [],
};

function wrap(r: RotationPlan | null) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, enabled: false } } });
  return render(
    <QueryClientProvider client={qc}><MemoryRouter><SelectionProvider>
      <RotationPanel ev={{ symbol: "PDR", price: 11200, avg_cost: 15250, account_id: "vps", row_id: "vps:PDR", rotation: r } as PositionEval} />
    </SelectionProvider></MemoryRouter></QueryClientProvider>,
  );
}

describe("RotationPanel", () => {
  it("vùng bán: hiện số cổ phiếu cần bán, thước giá và điền sẵn khối lượng", () => {
    const { container } = wrap(plan);
    expect(screen.getByText("Vùng bán")).toBeTruthy();
    expect(screen.getByText(/bán 7.700 cổ phiếu/)).toBeTruthy();
    const steps = container.querySelector("ol")!.textContent ?? "";
    expect(steps).toContain("Đợt 1Khi giá lên 11.000 trở lên → bán 7.700 cổ phiếuđã tới giá: bán");
    expect(steps).toContain("Đợt 2Khi giá lên 12.000 trở lên → bán thêm 5.500 cổ phiếucòn +7,1%");
    expect((screen.getByLabelText("Số lượng") as HTMLInputElement).value).toBe("7700");
    expect((screen.getByRole("option", { name: "Mua lại" }) as HTMLOptionElement).disabled).toBe(true);
  });
  it("chờ mua lại: liệt kê điều kiện đạt và chưa đạt, chọn sẵn mua lại", () => {
    wrap({
      ...plan, phase: "wait_rebuy", phase_label: "Chờ mua lại", level: "watch", sell_qty: 0, open_qty: 3000, sold_qty: 3000,
      sold_avg: 12500, rebuy_below: 11625, floor: 10000, sessions_left: 15,
      checks: [
        { code: "below_sell", label: "Giá thấp hơn giá bán bình quân từ 7%", met: true, detail: "giá 11.200" },
        { code: "reversal", label: "Có phiên đảo chiều", met: false, detail: "chưa" },
      ],
      trades: [{ id: 1, broker: "ledger", account_id: "vps", symbol: "PDR", side: "sell", trade_date: "2026-10-10", quantity: 3000, price: 12500, note: null }],
    });
    expect(screen.getByLabelText("đạt")).toBeTruthy();
    expect(screen.getByLabelText("chưa đạt")).toBeTruthy();
    expect(screen.getByText(/3.000 cp × 12.500/)).toBeTruthy();
    expect((screen.getByLabelText("Loại") as HTMLSelectElement).value).toBe("buy");
    expect(document.querySelector("ol")!.textContent).not.toContain("đã bán");   // mới bán 3.000, chưa đủ 7.700 của đợt 1
    expect(document.body.textContent).toContain("Khi giá về 11.625 trở xuống, vẫn trên đáy 10.000 → mua lại 3.000 cổ phiếu");
  });
  it("không áp dụng thì nói rõ vì sao", () => {
    wrap(null);
    expect(screen.getByText(/Chỉ áp dụng cho mã đang lỗ/)).toBeTruthy();
  });
});

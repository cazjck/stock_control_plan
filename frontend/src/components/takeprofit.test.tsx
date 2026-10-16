import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { TakeProfitPanel } from "./TakeProfitPanel";
import type { TakeProfitPlan } from "../lib/types";

const plan: TakeProfitPlan = {
  r_value: 2400, r_multiple: 5.4, original_qty: 1000,
  targets: [
    { label: "+10%", kind: "ladder", price: 123200, distance_pct: -2.6, sell_pct_of_original: 25, sell_qty: 200, reached: true, executed: false, suspended: false },
    { label: "+15%", kind: "ladder", price: 128800, distance_pct: 1.8, sell_pct_of_original: 25, sell_qty: 200, reached: false, executed: false, suspended: false },
    { label: "2R", kind: "r", price: 116800, distance_pct: -7.7, reached: true, executed: false, suspended: false },
  ],
  signals: [
    { code: "climax_run", group: "strength", label: "Tăng từ 25% trở lên trong 15 phiên", met: true, detail: "+28,0% so với đáy 15 phiên" },
    { code: "up_streak", group: "strength", label: "Ít nhất 7/8 phiên gần nhất là phiên tăng", met: false, detail: "5/8 phiên tăng" },
    { code: "below_sma50", group: "weakness", label: "Đóng cửa dưới SMA50", met: false, detail: "đóng cửa 126.500, SMA50 121.533" },
  ],
  advice: { level: "partial", text: "Đạt mốc +10%: bán 25% khối lượng ban đầu (khoảng 200 cổ phiếu, giá từ 123.200).", sell_qty: 200, reason_codes: ["ladder"] },
  next_target: null,
};

describe("TakeProfitPanel", () => {
  it("hiện khuyến nghị kèm số cổ phiếu cần bán", () => {
    render(<TakeProfitPanel plan={plan} />);
    expect(screen.getByRole("status").textContent).toContain("Chốt một phần · 200 cp");
  });
  it("hiện giá mục tiêu, trạng thái từng bậc và tham chiếu R", () => {
    const { container } = render(<TakeProfitPanel plan={plan} />);
    const t = container.textContent ?? "";
    expect(t).toContain("123.200");
    expect(t).toContain("Đã tới, cần bán");
    expect(t).toContain("còn 1,8%");
    expect(t).toContain("2R 116.800");
  });
  it("bảng kiểm phân biệt dấu hiệu đạt và chưa đạt, kèm số liệu", () => {
    render(<TakeProfitPanel plan={plan} />);
    expect(screen.getAllByLabelText("Đạt")).toHaveLength(1);
    expect(screen.getAllByLabelText("Chưa đạt")).toHaveLength(2);
    expect(screen.getByText("+28,0% so với đáy 15 phiên")).toBeTruthy();
  });
  it("không có kế hoạch thì giải thích lý do", () => {
    render(<TakeProfitPanel plan={null} />);
    expect(screen.getByText(/không có kế hoạch chốt lời/)).toBeTruthy();
  });
});

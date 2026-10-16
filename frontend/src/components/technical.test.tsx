import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { TechPlanPanel } from "./TechPlanPanel";
import type { PositionEval, TechPlan, TechZone } from "../lib/types";

const z = (o: Partial<TechZone>): TechZone => ({ price: 11_300, low: 11_292, high: 11_400, kind: "resistance", tools: ["SMA20", "Đáy 16/09"],
  strength: 2, distance_pct: 1.1, sell_pct: 0, sell_qty: 0, cum_pct: 0, ratio_after: null, margin_sized: false, ...o });
const plan: TechPlan = {
  stage: 4, stage_label: "Giai đoạn 4: đang giảm", stage_detail: "giá dưới đường 30 tuần",
  resistance: [z({}), z({ price: 11_700, low: 11_641, high: 11_800, tools: ["SMA50", "Bollinger trên", "Đáy 07/08"], strength: 3, distance_pct: 4.7 })],
  support: [z({ price: 10_475, low: 10_400, high: 10_550, kind: "support", tools: ["Đáy 28/07", "Đáy 28/09"], strength: 1, distance_pct: -6.5 })],
  sell_zones: [z({ sell_pct: 10, sell_qty: 4_100, cum_pct: 10, ratio_after: 95.3 })],
  invalidation: 10_232, invalidation_basis: "đáy 60 phiên 10.400 trừ 0,5×ATR14",
  bottom_checks: [{ code: "rsi50", label: "RSI14 trên 50", met: false, detail: "RSI14 40" }, { code: "divergence", label: "MACD dương", met: true, detail: "34" }],
  bottom_score: 2, bottom_label: "Chưa có bằng chứng đáy",
  scenarios: [
    { name: "rebound", title: "Nếu hồi", trigger: "Giá lên 11.292–11.400", action: "Bán 4.100 cp" },
    { name: "sideways", title: "Nếu đi ngang", trigger: "Dao động", action: "Xem lại sau 20 phiên" },
    { name: "decline", title: "Nếu giảm", trigger: "Đóng cửa dưới 10.232", action: "Làm theo kế hoạch hạ margin" },
  ],
  summary: "Giai đoạn 4: đang giảm. Chưa có bằng chứng đáy (2/6 dấu hiệu).",
};

describe("TechPlanPanel", () => {
  it("thang giá xếp từ cao xuống thấp: cản, giá hiện tại, đỡ, mức vô hiệu", () => {
    render(<TechPlanPanel ev={{ price: 11_200, technical: plan } as unknown as PositionEval} />);
    const items = [...screen.getByLabelText("Thang giá theo kỹ thuật").querySelectorAll("li")].map((li) => li.textContent ?? "");
    expect(items[0]).toContain("11.641–11.800");
    expect(items[1]).toContain("11.292–11.400");
    expect(items[1]).toContain("bán 4.100 cp");
    expect(items[1]).toContain("ký quỹ còn 95,3%");
    expect(items[2]).toContain("Giá hiện tại");
    expect(items[3]).toContain("10.400–10.550");
    expect(items[4]).toContain("Mức vô hiệu");
  });
  it("ba kịch bản và nhãn giai đoạn", () => {
    render(<TechPlanPanel ev={{ price: 11_200, technical: plan } as unknown as PositionEval} />);
    expect(screen.getByText("Giai đoạn 4: đang giảm")).toBeTruthy();
    expect(screen.getByText("Nếu hồi")).toBeTruthy();
    expect(screen.getByText("Nếu đi ngang")).toBeTruthy();
    expect(screen.getByText("Nếu giảm")).toBeTruthy();
    expect(screen.getByText(/Sáu dấu hiệu xác nhận đáy \(2\/6\)/)).toBeTruthy();
  });
});

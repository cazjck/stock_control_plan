import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DeleveragePlanView } from "./DeleveragePlan";
import type { DeleverageOverview, DeleveragePlan, DeleverageStep } from "../lib/types";

const step = (o: Partial<DeleverageStep>): DeleverageStep => ({
  kind: "worst_loss", symbol: "DXG", row_id: "ssi:DXG", quantity: 11700, price: 10150, proceeds: 118_300_000,
  reason: "lỗ −41,0%, vừa đủ đưa RTT lên 45%", ratio_after: 45.01, debt_after: 284_000_000,
  interest_per_day_after: 109_400, reaches_target: true, deferred: false, ...o,
});
const plan: DeleveragePlan = {
  bucket_id: "ssi", label: "SSI", source: "SSI", ratio_kind: "equity_over_value", ratio_pct: 37.46, maintenance_pct: 35,
  liquidation_pct: 25, target_pct: 45, zone: "watch", market_value: 649_600_000, debt: 402_300_000, interest_per_day: 148_800,
  cash_alternative: 48_700_000, safe_steps: [step({})], safe_ratio_after: 45.01, safe_debt_after: 284_000_000,
  safe_interest_after: 109_400, safe_reached: true, committed_ratio_after: 45.01, committed_interest_after: 109_400, deferred_symbols: [], zero_steps: [step({ kind: "to_zero", quantity: 29000, ratio_after: null, debt_after: 0, interest_per_day_after: 0 })],
  zero_shortfall: 0, zero_interest_saved: 109_400, due_30d_amount: 9_850_000, due_30d_first: "2026-11-09", due_30d_count: 1,
  headline: "Bán 1 lệnh, tổng khoảng 118.600.000: RTT từ 37,5% lên 45,0%.",
  notes: ["1 khoản vay đáo hạn trong 30 ngày, sớm nhất 09/11: cần 9.850.000 gốc và lãi."],
};
const o: DeleverageOverview = { plans: [plan], total_debt: plan.debt, interest_per_day: 148_800, interest_after_safe: 109_400,
  safe_sell_value: 118_600_000, safe_proceeds: 118_300_000, accounts_unsafe: 1, deferred_sell_value: 0 };

describe("DeleveragePlanView", () => {
  it("liệt kê lệnh bán giai đoạn 1 với RTT sau và tiền lãi sau", () => {
    const { container } = render(<DeleveragePlanView o={o} />);
    const rows = container.querySelectorAll("table")[0].querySelectorAll("tbody tr");
    expect(rows).toHaveLength(1);
    expect(rows[0].textContent).toContain("DXG");
    expect(rows[0].textContent).toContain("11.700");
    expect(rows[0].textContent).toContain("45,0%");
    expect(screen.getByText(/Giai đoạn 1 · làm phiên kế tiếp/)).toBeTruthy();
    expect(screen.getByText(/đáo hạn trong 30 ngày/)).toBeTruthy();
    expect(screen.getByText(/có thể nộp thêm khoảng/)).toBeTruthy();
    expect(screen.getByText(/Giai đoạn 2 · bán tiếp để hết nợ/)).toBeTruthy();
  });
  it("mã đang gồng: lệnh ghi là hoãn, số cần bán không tính phần hoãn", () => {
    const held = { ...plan, safe_steps: [step({ deferred: true })], deferred_symbols: ["DXG"], committed_ratio_after: 37.46 };
    const { container } = render(<DeleveragePlanView o={{ ...o, plans: [held], safe_sell_value: 0, deferred_sell_value: 118_600_000 }} />);
    expect(screen.getByText("hoãn: đang gồng")).toBeTruthy();
    expect(container.textContent).toContain("hoãn 118,6 tr vì đang gồng");
  });
  it("không có nợ thì nói rõ", () => {
    render(<DeleveragePlanView o={{ ...o, plans: [] }} />);
    expect(screen.getByText(/Không có tài khoản nào đang vay margin/)).toBeTruthy();
  });
});

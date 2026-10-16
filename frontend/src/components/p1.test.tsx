import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { SizingResult } from "./SizingPanel";
import { ScenarioResults } from "../pages/Scenarios";
import type { MarginMetrics, ScenarioResult, ScenarioState, SizingPlan } from "../lib/types";

const metrics = (ratio: number, zone: MarginMetrics["zone"], drop: number, cash: number): MarginMetrics => ({
  bucket: { id: "b", scope: "account", ratio_kind: "equity_over_value", label: "Tài khoản demo", symbols: [], ratio_pct: ratio, maintenance_pct: 40, liquidation_pct: 35, initial_pct: 50, market_value: 1e8, debt: 5e7, raw: {} },
  drop_to_maintenance_pct: drop, drop_to_liquidation_pct: null, cash_to_safe: cash, safe_target_pct: 50, zone,
} as MarginMetrics);

const state = (m: MarginMetrics, over: Partial<ScenarioState> = {}): ScenarioState => ({
  positions_value: 358_850_000, cash: 12_300_000, debt: 198_800_000, nav: 172_350_000, unrealized_pnl: -7_750_000, unrealized_pnl_pct: -2.1,
  interest_per_day: 67_753, buckets: [m], focus_bucket_id: "b", cash_needed: m.cash_to_safe ?? 0, ...over,
});

describe("ScenarioResults", () => {
  const r: ScenarioResult = {
    request: { market_drop_pct: 10, sell: [], add_cash: 0 },
    before: state(metrics(44.6, "watch", 7.7, 19_375_000)),
    after: state(metrics(38.2, "danger", 0, 31_000_000), { unrealized_pnl: -26_000_000, interest_per_day: 50_000 }),
    sale_proceeds: 0, realized_pnl: 0, debt_repaid: 0,
    warnings: ["Tài khoản demo: RTT 38,2% dưới ngưỡng duy trì 40%, sẽ bị gọi ký quỹ"],
  };
  it("vẽ hai thước mớn nước, trước và sau", () => {
    render(<ScenarioResults r={r} pending={false} />);
    const labels = screen.getAllByRole("img").map((e) => e.getAttribute("aria-label"));
    expect(labels).toHaveLength(2);
    expect(labels[0]).toContain("44,6%");
    expect(labels[1]).toContain("38,2%");
    expect(labels[1]).toContain("đã dưới ngưỡng duy trì");
  });
  it("hiện kết luận, cảnh báo và bảng trước/sau với số kiểu Việt Nam", () => {
    const { container } = render(<ScenarioResults r={r} pending={false} />);
    const text = container.textContent ?? "";
    expect(text).toContain("Đã dưới ngưỡng duy trì");
    expect(text).toContain("sẽ bị gọi ký quỹ");
    expect(text).toContain("19,4 tr");
    expect(text).toContain("31,0 tr");
    expect(text).toContain("−6,4 điểm");   // 38,2 − 44,6
    expect(screen.getByRole("table").textContent).toContain("−26,0 tr");
  });
  it("tài khoản không có nợ margin vẫn có bảng so sánh, không có thước", () => {
    const none: ScenarioResult = { ...r, before: state(metrics(0, "unknown", 0, 0), { buckets: [], focus_bucket_id: null }), after: state(metrics(0, "unknown", 0, 0), { buckets: [], focus_bucket_id: null }) };
    render(<ScenarioResults r={none} pending={false} />);
    expect(screen.queryAllByRole("img")).toHaveLength(0);
    expect(screen.getByText("Tài khoản này không có nợ margin")).toBeTruthy();
    expect(screen.getByRole("table")).toBeTruthy();
  });
});

describe("SizingResult", () => {
  const plan: SizingPlan = {
    symbol: "AAA", price: 40_000, stop_price: 37_000, stop_basis: "Giá cắt lỗ do bạn nhập", stop_distance: 3_000, stop_distance_pct: 7.5, atr14: null,
    capital: 200_000_000, risk_pct: 1.5, risk_money: 3_000_000, max_weight_pct: 20, qty_by_risk: 1000, qty_by_weight: 1000, qty_plan: 1000, binding: "risk",
    plan_value: 40_000_000, plan_weight_pct: 20, risk_at_stop: 3_000_000, held_quantity: 0, additional_quantity: 1000, positions_count: 2, max_positions: 5,
    market: { state: "NORMAL", index_symbol: "VNINDEX" } as SizingPlan["market"], allowed: true, warnings: [],
    tranches: [200, 200, 300, 300].map((q, i) => ({ index: i + 1, pct: 25, quantity: q, value: q * 40_000, trigger_price: 40_000 * 1.03 ** i, condition: `điều kiện ${i + 1}`, likely_skipped: false })),
  };
  it("hiện khối lượng, cắt lỗ và bốn đợt", () => {
    const { container } = render(<SizingResult p={plan} />);
    const t = container.textContent ?? "";
    expect(t).toContain("1.000 cp");
    expect(t).toContain("37.000");
    expect(t).toContain("tiền mặt thực có, không tính margin");
    ["Đợt 1", "Đợt 2", "Đợt 3", "Đợt 4"].forEach((d) => expect(t).toContain(d));
    expect(t).toContain("300 cp");
    expect(screen.queryByRole("status")).toBeNull();
  });
  it("khi luật cấm: banner rõ ràng, cảnh báo có ký hiệu và chữ cho trình đọc màn hình", () => {
    const blocked: SizingPlan = { ...plan, allowed: false, warnings: [
      { code: "MARKET_NO_NEW_BUYS", severity: "block", message: "VNINDEX dưới SMA50: luật không cho mở vị thế swing mới." },
      { code: "MAX_POSITIONS", severity: "block", message: "Đang giữ 5 mã, đã tới giới hạn 5 mã." },
    ] };
    render(<SizingResult p={blocked} />);
    expect(screen.getByRole("status").textContent).toContain("Luật không cho mở vị thế này");
    const items = screen.getAllByRole("listitem").filter((li) => li.textContent?.includes("giới hạn 5 mã") || li.textContent?.includes("SMA50"));
    expect(items).toHaveLength(2);
    expect(items[0].textContent).toContain("Không được phép");
    expect(items[0].querySelector("[aria-hidden]")?.textContent).toBe("■");
  });
  it("kế hoạch bằng 0 thì không liệt kê các đợt", () => {
    render(<SizingResult p={{ ...plan, qty_plan: 0, qty_by_risk: 0, allowed: false, tranches: plan.tranches.map((t) => ({ ...t, quantity: 0 })),
      warnings: [{ code: "QTY_ZERO", severity: "block", message: "Vốn chưa đủ mua 1 lô" }] }} />);
    expect(screen.queryByText("Đợt 1")).toBeNull();
    expect(screen.getByText("chưa đủ 1 lô")).toBeTruthy();
  });
  it("nói rõ khi bị giới hạn bởi tỷ trọng", () => {
    const { container } = render(<SizingResult p={{ ...plan, binding: "weight", qty_by_risk: 1500 }} />);
    expect(container.textContent).toContain("Bị giới hạn bởi tỷ trọng tối đa 20% vốn (theo rủi ro được 1.500 cp)");
  });
});

import { describe, expect, it } from "vitest";
import { verdictFor, worstBucket } from "./verdict";
import type { MarginMetrics } from "./types";

const m = (zone: MarginMetrics["zone"], ratio: number, drop: number | null, cash: number | null = 0): MarginMetrics => ({
  bucket: { id: zone + ratio, scope: "account", ratio_kind: "equity_over_value", label: zone, symbols: [], ratio_pct: ratio, maintenance_pct: 40, liquidation_pct: 35, initial_pct: 50, market_value: 1e8, debt: 5e7, raw: {} },
  drop_to_maintenance_pct: drop, drop_to_liquidation_pct: null, cash_to_safe: cash, safe_target_pct: 50, zone,
} as MarginMetrics);

describe("verdictFor", () => {
  it("vùng theo dõi nói rõ phải giảm bao nhiêu % thì bị gọi ký quỹ", () => {
    const v = verdictFor(m("watch", 44.6, 7.7, 19_375_000));
    expect(v.tone).toBe("watch");
    expect(v.headline).toBe("Giảm thêm 7,7% là bị gọi ký quỹ");
    expect(v.detail).toContain("19,4 tr");
  });
  it("dưới duy trì và dưới giải chấp là hai mức khác nhau", () => {
    expect(verdictFor(m("danger", 38, 0, 6e6)).headline).toMatch(/dưới ngưỡng duy trì/);
    expect(verdictFor(m("breach", 33, 0, 9e6)).headline).toMatch(/giải chấp/);
  });
  it("vùng an toàn không đòi nộp tiền", () => {
    const v = verdictFor(m("safe", 70, 31.5, 0));
    expect(v.tone).toBe("safe");
    expect(v.detail).not.toContain("Cần nộp");
  });
  it("thiếu dữ liệu thì nói thẳng", () => expect(verdictFor(undefined).tone).toBe("unknown"));
});

describe("worstBucket", () => {
  it("chọn nhóm nguy hiểm nhất, hòa thì chọn nhóm gần ngưỡng hơn", () => {
    const list = [m("safe", 70, 31), m("watch", 48, 12), m("watch", 44, 6), m("danger", 38, 0)];
    expect(worstBucket(list)?.zone).toBe("danger");
    expect(worstBucket(list.slice(0, 3))?.bucket.ratio_pct).toBe(44);
    expect(worstBucket([])).toBeUndefined();
  });
});

describe("verdictFor với RTT kiểu TCBS", () => {
  const tcbs = { ...m("watch", 88.2, 2.0, 26_900_000), bucket: { ...m("watch", 88.2, 2.0).bucket, ratio_kind: "collateral_over_debt" as const, maintenance_pct: 85, liquidation_pct: 80 } };
  it("nói rõ tiền nộp được trừ thẳng vào dư nợ khi tính RTT", () => {
    const v = verdictFor(tcbs as MarginTypes);
    expect(v.headline).toBe("Giảm thêm 2,0% là bị gọi ký quỹ");
    expect(v.detail).toContain("trừ thẳng vào dư nợ");
    expect(v.detail).toContain("26,9 tr");
  });
  it("dưới duy trì và dưới xử lý tài sản nêu đúng mốc bán của TCBS", () => {
    const danger = verdictFor({ ...tcbs, zone: "danger", bucket: { ...tcbs.bucket, ratio_pct: 83 } } as MarginTypes);
    expect(danger.detail).toContain("3 ngày làm việc liên tiếp");
    const breach = verdictFor({ ...tcbs, zone: "breach", bucket: { ...tcbs.bucket, ratio_pct: 79 } } as MarginTypes);
    expect(breach.detail).toContain("tỷ lệ xử lý tài sản 80,0%");
    expect(breach.detail).toContain("ngày làm việc kế tiếp");
  });
});
type MarginTypes = Parameters<typeof verdictFor>[0] & object;

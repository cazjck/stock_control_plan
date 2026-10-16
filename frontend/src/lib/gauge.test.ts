import { describe, expect, it } from "vitest";
import { buildScale, spreadLabels, zoneOf } from "./gauge";

describe("buildScale", () => {
  const g = { ratio: 44.6, maintenance: 40, liquidation: 35, safeTarget: 50 };
  it("số tăng dần xuống dưới như vạch mớn nước", () => {
    const s = buildScale(g, 10, 290);
    expect(s.y(35)).toBeLessThan(s.y(40));
    expect(s.y(40)).toBeLessThan(s.y(44.6));
    expect(s.y(44.6)).toBeLessThan(s.y(50));
  });
  it("miền nằm trong 0..100 và đủ chứa mọi ngưỡng", () => {
    const s = buildScale(g, 10, 290);
    expect(s.lo).toBeLessThanOrEqual(35);
    expect(s.hi).toBeGreaterThanOrEqual(50);
    expect(s.lo).toBeGreaterThanOrEqual(0);
    expect(s.hi).toBeLessThanOrEqual(100);
  });
  it("giá trị ngoài miền được kẹp, không tràn thước", () => {
    const s = buildScale(g, 10, 290);
    expect(s.y(-50)).toBe(10);
    expect(s.y(500)).toBe(290);
  });
  it("RTT dưới ngưỡng giải chấp vẫn nằm trong thước", () => {
    const s = buildScale({ ...g, ratio: 22 }, 10, 290);
    expect(s.y(22)).toBeGreaterThanOrEqual(10);
    expect(s.lo).toBeLessThanOrEqual(22);
  });
  it("vạch lớn mỗi 5 điểm", () => {
    const majors = buildScale(g, 0, 100).ticks.filter((t) => t.major).map((t) => t.v);
    expect(majors.every((v) => v % 5 === 0)).toBe(true);
  });
});

describe("buildScale với RTT kiểu TCBS (tài sản đảm bảo / dư nợ)", () => {
  const g = { ratio: 88.2, maintenance: 85, liquidation: 80, safeTarget: 95 };
  it("thước ôm trọn các ngưỡng 80, 85, 95", () => {
    const s = buildScale(g, 10, 290);
    expect(s.lo).toBeLessThanOrEqual(80);
    expect(s.hi).toBeGreaterThanOrEqual(95);
    expect(s.y(80)).toBeLessThan(s.y(85));
    expect(s.y(85)).toBeLessThan(s.y(88.2));
  });
  it("RTT trên 100 vẫn nằm trong thước", () => {
    const s = buildScale({ ratio: 140, maintenance: 85, liquidation: 80, safeTarget: 95 }, 10, 290);
    expect(s.hi).toBeGreaterThanOrEqual(140);
    expect(s.y(140)).toBeLessThanOrEqual(290);
  });
});

describe("zoneOf", () => {
  const base = { maintenance: 40, liquidation: 35, safeTarget: 50 };
  it.each([[70, "safe"], [48, "watch"], [38, "danger"], [34, "breach"]])("ratio %s -> %s", (ratio, zone) => {
    expect(zoneOf({ ratio, ...base })).toBe(zone);
  });
  it("không có ngưỡng giải chấp thì chỉ còn danger", () => {
    expect(zoneOf({ ratio: 20, maintenance: 40, liquidation: null, safeTarget: null })).toBe("danger");
  });
});

describe("spreadLabels", () => {
  it("không để hai nhãn gần hơn khoảng tối thiểu", () => {
    const out = spreadLabels([{ y: 100 }, { y: 104 }, { y: 108 }], 30, 0, 300);
    for (let i = 1; i < out.length; i++) expect(out[i].ly - out[i - 1].ly).toBeGreaterThanOrEqual(30);
  });
  it("giữ nhãn trong khung khi chen sát đáy", () => {
    const out = spreadLabels([{ y: 280 }, { y: 285 }, { y: 290 }], 30, 0, 295);
    expect(Math.max(...out.map((o) => o.ly))).toBeLessThanOrEqual(295);
    for (let i = 1; i < out.length; i++) expect(out[i].ly - out[i - 1].ly).toBeGreaterThanOrEqual(30 - 1e-9);
  });
  it("giữ nguyên vị trí khi đã đủ xa", () => {
    const out = spreadLabels([{ y: 50 }, { y: 120 }], 30, 0, 300);
    expect(out.map((o) => o.ly)).toEqual([50, 120]);
  });
});

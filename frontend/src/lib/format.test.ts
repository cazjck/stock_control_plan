import { describe, expect, it } from "vitest";
import { ageText, daysUntil, fmtInt, fmtMoney, fmtPct, fmtSigned, parseVnNumber } from "./format";

describe("định dạng số kiểu Việt Nam", () => {
  it("giá có dấu chấm ngăn nghìn", () => expect(fmtInt(126500)).toBe("126.500"));
  it("phần trăm dùng dấu phẩy thập phân", () => expect(fmtPct(12.94)).toBe("12,9%"));
  it("phần trăm có dấu cộng khi yêu cầu", () => {
    expect(fmtPct(5.2, 1, true)).toBe("+5,2%");
    expect(fmtPct(-5.2, 1, true)).toBe("−5,2%");
  });
  it("tiền gọn theo tỷ, triệu, nghìn", () => {
    expect(fmtMoney(1_250_000_000)).toBe("1,25 tỷ");
    expect(fmtMoney(198_800_000)).toBe("198,8 tr");
    expect(fmtMoney(67_753)).toBe("67,8 nghìn");
    expect(fmtMoney(950)).toBe("950");
    expect(fmtMoney(-19_375_000)).toBe("−19,4 tr");
  });
  it("giá trị thiếu hiện dấu gạch", () => {
    expect(fmtInt(null)).toBe("—");
    expect(fmtPct(undefined)).toBe("—");
    expect(fmtSigned(null)).toBe("—");
  });
  it("tính số ngày còn lại", () => {
    expect(daysUntil("2026-10-21", new Date(2026, 9, 16, 15))).toBe(5);
    expect(daysUntil("2026-10-14", new Date(2026, 9, 16))).toBe(-2);
    expect(daysUntil(null)).toBeNull();
  });
  it("tuổi dữ liệu dễ đọc", () => {
    expect(ageText(2)).toBe("vừa xong");
    expect(ageText(90)).toBe("2 phút trước");
  });
});

describe("parseVnNumber", () => {
  it.each([
    ["100.000.000", 100_000_000], ["100tr", 100_000_000], ["1,2 tỷ", 1_200_000_000], ["1,2ty", 1_200_000_000],
    ["25,5", 25.5], ["500k", 500_000], ["28000", 28_000], ["13,5", 13.5], [" 3 triệu ", 3_000_000],
  ])("%s -> %s", (s, n) => expect(parseVnNumber(s)).toBeCloseTo(n as number));
  it.each(["", "abc", "-5", "1tr2"])("không đọc được '%s'", (s) => expect(parseVnNumber(s)).toBeNull());
});

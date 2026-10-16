import { afterEach, describe, expect, it } from "vitest";
import { fmtInt, fmtMoney, fmtPct, fmtPnlPct, fmtSigned, pnlTone } from "./format";
import { MASK, maskText, setPrivate } from "./privacy";

afterEach(() => setPrivate(false));

describe("chế độ che số", () => {
  it("che tiền và phần trăm lãi lỗ, giữ giá và tỷ lệ", () => {
    setPrivate(true);
    expect(fmtMoney(198_800_000)).toBe(MASK);
    expect(fmtSigned(-7_800_000)).toBe(MASK);
    expect(fmtPnlPct(-51.3)).toBe(MASK);
    expect(pnlTone(-51.3)).toBe("");
    expect(fmtInt(126_500)).toBe("126.500");       // giá, khối lượng: giữ
    expect(fmtPct(86.7)).toBe("86,7%");             // tỷ lệ ký quỹ: giữ
  });
  it("tắt thì hiện bình thường", () => {
    expect(fmtMoney(198_800_000)).toBe("198,8 tr");
    expect(fmtPnlPct(-51.3)).toBe("−51,3%");
    expect(pnlTone(-51.3)).toBe("text-lead");
  });
});

describe("maskText", () => {
  const on = (s: string) => maskText(s, true);
  it("che số tiền có đơn vị và số lớn, giữ số cổ phiếu và giá", () => {
    expect(on("Cần nộp khoảng 19,4 tr để về vùng an toàn")).toBe(`Cần nộp khoảng ${MASK} để về vùng an toàn`);
    expect(on("Lỗ 492.810.600 đã vượt ngưỡng 10% NAV.")).toBe(`Lỗ ${MASK} đã vượt ngưỡng 10% NAV.`);
    expect(on("bán 2.000 cp bằng ATO, giá 18.900")).toBe("bán 2.000 cp bằng ATO, giá 18.900");
    expect(on("mất thêm 400.000 đồng.")).toBe(`mất thêm ${MASK}.`);
  });
  it("che phần trăm lãi lỗ, giữ ngưỡng của luật", () => {
    expect(on("PDR là hàng kẹt (−51,3%)")).toBe(`PDR là hàng kẹt (${MASK})`);
    expect(on("Giá 18.600 dưới mức cắt lỗ 18.677. Lãi lỗ −4,1%.")).toBe(`Giá 18.600 dưới mức cắt lỗ 18.677. Lãi lỗ ${MASK}.`);
    expect(on("Lỗ chưa thực hiện 252,2% NAV")).toBe(`Lỗ chưa thực hiện ${MASK} NAV`);
    expect(on("sau 6 phiên chưa lãi 3% (đang +1,0%)")).toBe(`sau 6 phiên chưa lãi 3% (đang ${MASK})`);
    expect(on("Cắt lỗ ban đầu −7% giá vốn")).toBe("Cắt lỗ ban đầu −7% giá vốn");
    expect(on("Đạt mốc +10%: bán 25% khối lượng ban đầu")).toBe("Đạt mốc +10%: bán 25% khối lượng ban đầu");
  });
  it("không bật thì giữ nguyên", () => {
    expect(maskText("Lỗ 492.810.600")).toBe("Lỗ 492.810.600");
  });
});

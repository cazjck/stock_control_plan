import { describe, expect, it } from "vitest";
import { marketSession, remainingText } from "./session";

describe("marketSession", () => {
  it("thứ Sáu 10:30 là trong giờ", () => expect(marketSession(new Date(2026, 9, 16, 10, 30)).open).toBe(true));
  it("thứ Sáu 15:00 đã đóng", () => expect(marketSession(new Date(2026, 9, 16, 15, 0)).open).toBe(false));
  it("sáng sớm chưa mở", () => expect(marketSession(new Date(2026, 9, 16, 8, 0)).label).toMatch(/Chưa mở/));
  it("thứ Bảy luôn ngoài giờ", () => expect(marketSession(new Date(2026, 9, 17, 10, 0)).open).toBe(false));
});

describe("remainingText", () => {
  const now = new Date("2026-10-16T08:00:00+07:00");
  it("tính giờ và phút còn lại", () => expect(remainingText("2026-10-16T13:20:00+07:00", now)).toBe("5 giờ 20 phút"));
  it("dưới một giờ chỉ hiện phút", () => expect(remainingText("2026-10-16T08:45:00+07:00", now)).toBe("45 phút"));
  it("quá hạn", () => expect(remainingText("2026-10-16T07:00:00+07:00", now)).toBe("đã hết hạn"));
  it("DNSE không có hạn", () => expect(remainingText(null, now)).toBe("không giới hạn"));
});

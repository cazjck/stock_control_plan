import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DraftGauge } from "./DraftGauge";
import { StatusChip } from "./StatusChip";

describe("DraftGauge", () => {
  it("mô tả đầy đủ bằng lời cho trình đọc màn hình", () => {
    render(<DraftGauge ratio={44.6} maintenance={40} liquidation={35} safeTarget={50} />);
    const img = screen.getByRole("img");
    expect(img.getAttribute("aria-label")).toBe(
      "Tỷ lệ ký quỹ hiện tại 44,6%, đang trong vùng theo dõi. Ngưỡng duy trì 40%, ngưỡng giải chấp 35%.");
  });
  it("hiện các nhãn ngưỡng", () => {
    const { container } = render(<DraftGauge ratio={44.6} maintenance={40} liquidation={35} safeTarget={50} />);
    const text = container.textContent ?? "";
    ["GIẢI CHẤP", "DUY TRÌ", "AN TOÀN", "HIỆN TẠI"].forEach((t) => expect(text).toContain(t));
  });
  it("báo vùng nguy hiểm khi RTT dưới ngưỡng duy trì", () => {
    render(<DraftGauge ratio={37} maintenance={40} liquidation={35} safeTarget={50} />);
    expect(screen.getByRole("img").getAttribute("aria-label")).toContain("đã dưới ngưỡng duy trì");
  });
  it("không có dữ liệu thì hiện thông báo thay vì thước rỗng", () => {
    render(<DraftGauge ratio={null} maintenance={null} />);
    expect(screen.getByText("Chưa có tỷ lệ ký quỹ")).toBeTruthy();
  });
});

describe("StatusChip", () => {
  it.each([
    ["STOP_HIT", "Chạm cắt lỗ"], ["TRAPPED", "Hàng kẹt"], ["WARNING", "Cảnh báo"],
    ["TAKE_PROFIT", "Tới mốc chốt lời"], ["TIME_STOP", "Hết hạn giữ"], ["SAFE", "An toàn"],
  ] as const)("%s hiện nhãn tiếng Việt kèm ký hiệu", (status, label) => {
    const { container } = render(<StatusChip status={status} />);
    expect(container.textContent).toContain(label);
    expect(container.querySelector("[aria-hidden]")?.textContent?.length).toBeGreaterThan(0); // ký hiệu, không chỉ dựa vào màu
  });
});

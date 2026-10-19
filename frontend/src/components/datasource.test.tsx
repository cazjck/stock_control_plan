import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DataSourceSettings } from "./DataSourceSettings";
import { api, type DataSourceView } from "../lib/api";

afterEach(() => vi.restoreAllMocks());

const view = (o: Partial<DataSourceView> = {}): DataSourceView => ({
  primary: "tcbs", fallback: true, order: ["tcbs", "dnse", "demo"], active: "dnse", active_label: "DNSE LightSpeed",
  sources: [
    { name: "tcbs", label: "TCBS iFlash", enabled: true, available: false, expires_at: null, message: "Cần nhập iOTP", realtime: true, note: "Có bảng giá realtime." },
    { name: "dnse", label: "DNSE LightSpeed", enabled: true, available: true, expires_at: null, message: null, realtime: false, note: "Chỉ cần khoá API." },
  ], ...o,
});

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><DataSourceSettings /></QueryClientProvider>);
}

describe("DataSourceSettings", () => {
  it("báo đang dùng nguồn dự phòng khi nguồn chính hết phiên", async () => {
    vi.spyOn(api, "dataSource").mockResolvedValue(view());
    wrap();
    expect(await screen.findByText(/nguồn chính chưa dùng được nên đang dùng dự phòng/)).toBeTruthy();
    expect(screen.getByText("Cần nhập iOTP")).toBeTruthy();
  });
  it("chọn DNSE làm nguồn chính thì gửi lựa chọn, giữ nguyên dự phòng", async () => {
    vi.spyOn(api, "dataSource").mockResolvedValue(view());
    const spy = vi.spyOn(api, "setDataSource").mockResolvedValue(view({ primary: "dnse" }));
    wrap();
    const radios = await screen.findAllByRole("radio");
    fireEvent.click(radios[1]);
    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(spy.mock.calls[0][0]).toEqual({ primary: "dnse", fallback: true });
  });
});

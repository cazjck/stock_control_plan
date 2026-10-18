import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { SelectionProvider } from "../lib/selection";
import PreTrade from "./PreTrade";
import { api } from "../lib/api";
import type { PreTradeCheck } from "../lib/types";

afterEach(() => vi.restoreAllMocks());

const check: PreTradeCheck = {
  symbol: "PDR", quantity: 2000, price: 11200, value: 22_400_000, verdict: "blocked",
  headline: "Không nên mua PDR: 3 luật không cho phép (mua bình quân giá xuống, đang vay margin).",
  items: [
    { code: "buys_today", label: "Tối đa 1 lệnh mua mỗi ngày", status: "pass", detail: "hôm nay đã ghi 0 lần mua", rule: "7" },
    { code: "averaging_down", label: "Mua bình quân giá xuống", status: "fail", detail: "Đang giữ PDR ở giá thấp hơn giá vốn", rule: "2.1" },
  ],
  max_qty: 0, stop_price: 10_416,
  margin: { account_label: "TCBS", ratio_before: 88.2, ratio_after: 84.1, maintenance_pct: 85, drop_before: 3.6, drop_after: null, interest_saved_if_repay: 8_285 },
  suggestion: "Số tiền 22.400.000 nếu dùng trả nợ TCBS sẽ bớt 8.285 lãi mỗi ngày.",
};

describe("PreTrade", () => {
  it("điền mã từ đường dẫn, gửi kiểm tra và xếp dòng không đạt lên trước", async () => {
    vi.spyOn(api, "margin").mockResolvedValue({ buckets: [] } as never);
    const spy = vi.spyOn(api, "pretrade").mockResolvedValue(check);
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={qc}><MemoryRouter initialEntries={["/check?symbol=PDR"]}><SelectionProvider><PreTrade /></SelectionProvider></MemoryRouter></QueryClientProvider>);
    expect((screen.getByLabelText("Mã") as HTMLInputElement).value).toBe("PDR");
    fireEvent.change(screen.getByLabelText(/^Số lượng/), { target: { value: "2.000" } });
    fireEvent.click(screen.getByRole("button", { name: "Kiểm tra" }));
    expect(await screen.findByText("Không nên mua")).toBeTruthy();
    expect(spy.mock.calls[0][1]).toMatchObject({ symbol: "PDR", qty: 2000 });
    const rows = [...screen.getByLabelText("Các kiểm tra").querySelectorAll("li")].map((li) => li.textContent ?? "");
    expect(rows[0]).toContain("Mua bình quân giá xuống");
    expect(screen.getByText(/bớt 8.285 lãi mỗi ngày/)).toBeTruthy();
  });
});

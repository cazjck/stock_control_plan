import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TelegramSettings } from "./TelegramSettings";
import { api } from "../lib/api";

afterEach(() => vi.restoreAllMocks());

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><TelegramSettings /></QueryClientProvider>);
}

describe("TelegramSettings", () => {
  it("chưa cài: hướng dẫn BotFather, chưa cho gửi thử", async () => {
    vi.spyOn(api, "notifyStatus").mockResolvedValue({ configured: false, enabled: false, token_masked: null, chat_id: null, chat_title: null,
      min_severity: "warning", app_url: null, last_sent_at: null, last_error: null, last_run_at: null });
    wrap();
    expect(await screen.findByText("Chưa cài")).toBeTruthy();
    expect(screen.getByText("@BotFather")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Gửi tin thử" })).toBeNull();
  });
  it("đã cài: hiện bot đã che mã, nơi nhận và lỗi gần nhất", async () => {
    vi.spyOn(api, "notifyStatus").mockResolvedValue({ configured: true, enabled: true, token_masked: "123456:••••-xyz", chat_id: 42,
      chat_title: "Khánh", min_severity: "warning", app_url: "https://stock.pdk.one", last_sent_at: null, last_error: "Telegram từ chối: Unauthorized", last_run_at: null });
    wrap();
    await waitFor(() => expect(screen.getByText("Đang gửi")).toBeTruthy());
    expect(screen.getByText("123456:••••-xyz")).toBeTruthy();
    expect(screen.getByText("Khánh")).toBeTruthy();
    expect(screen.getByText(/Unauthorized/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Gửi tin thử" })).toBeTruthy();
  });
});

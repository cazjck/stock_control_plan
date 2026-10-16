import { useEffect, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "./api";
import { useSelection } from "./selection";
import type { ScenarioRequest } from "./types";

/** Giá trị trễ `ms` mili giây, để không gọi API mỗi lần kéo thanh trượt hay gõ phím. */
export function useDebounced<T>(value: T, ms = 350): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** Trong giờ giao dịch làm mới nhanh hơn, ngoài giờ thì thưa. */
function pollMs(): number {
  const now = new Date();
  const d = now.getDay();
  const h = now.getHours() + now.getMinutes() / 60;
  const inSession = d >= 1 && d <= 5 && h >= 9 && h <= 15;
  return inSession ? 20_000 : 120_000;
}

export function useOverview() {
  const { sel, ready } = useSelection();
  return useQuery({
    queryKey: ["overview", sel.broker, sel.account], queryFn: () => api.overview(sel),
    enabled: ready && !!sel.broker, refetchInterval: pollMs(),
  });
}

export function usePositions() {
  const { sel, ready } = useSelection();
  return useQuery({
    queryKey: ["positions", sel.broker, sel.account], queryFn: () => api.positions(sel),
    enabled: ready && !!sel.broker, refetchInterval: pollMs(),
  });
}

export function useMarginPlan() {
  const { sel, ready } = useSelection();
  return useQuery({
    queryKey: ["margin-plan", sel.broker, sel.account], queryFn: () => api.marginPlan(sel),
    enabled: ready && !!sel.broker, refetchInterval: pollMs(),
  });
}

export function useMargin() {
  const { sel, ready } = useSelection();
  return useQuery({
    queryKey: ["margin", sel.broker, sel.account], queryFn: () => api.margin(sel),
    enabled: ready && !!sel.broker, refetchInterval: pollMs(),
  });
}

/** Kịch bản giả định. Là truy vấn (không phải mutation) vì chỉ tính toán, gọi lại bao nhiêu lần cũng không đổi gì. */
export function useScenario(body: ScenarioRequest) {
  const { sel, ready } = useSelection();
  return useQuery({
    queryKey: ["scenario", sel.broker, sel.account, body], queryFn: () => api.runScenario(body, sel),
    enabled: ready && !!sel.broker, placeholderData: keepPreviousData, staleTime: 5_000, retry: false,
  });
}

export function useSizing(symbol: string, price: number, stop: number | undefined) {
  const { sel, ready } = useSelection();
  return useQuery({
    queryKey: ["sizing", sel.broker, sel.account, symbol, price, stop], queryFn: () => api.sizing(symbol, price, stop, sel),
    enabled: ready && !!sel.broker && !!symbol && price > 0, placeholderData: keepPreviousData, staleTime: 10_000, retry: false,
  });
}

export function useChart(symbol: string, interval: string, row?: string) {
  const { sel, ready } = useSelection();
  return useQuery({
    queryKey: ["chart", sel.broker, sel.account, symbol, interval, row], queryFn: () => api.chart(symbol, sel, interval, 250, row),
    enabled: ready && !!sel.broker && !!symbol, staleTime: 60_000,
  });
}

export function useAlerts(status: "active" | "all") {
  const { sel, ready } = useSelection();
  return useQuery({
    queryKey: ["alerts", sel.broker, sel.account, status], queryFn: () => api.alerts(status, sel),
    enabled: ready && !!sel.broker, refetchInterval: pollMs(),
  });
}

export function useRules() {
  return useQuery({ queryKey: ["rules"], queryFn: api.rules });
}

export function useRuleChanges() {
  return useQuery({ queryKey: ["rule-changes"], queryFn: api.ruleChanges });
}

export function useSnapshots(days = 30) {
  const { sel, ready } = useSelection();
  return useQuery({
    queryKey: ["snapshots", sel.broker, sel.account, days], queryFn: () => api.snapshots(sel, days),
    enabled: ready && !!sel.broker,
  });
}

export function useRefreshAll() {
  const qc = useQueryClient();
  const { sel } = useSelection();
  return useMutation({
    mutationFn: () => api.overview(sel, true),
    onSuccess: () => qc.invalidateQueries(),
  });
}

export const isAuthRequired = (e: unknown): e is ApiError => e instanceof ApiError && e.code === "AUTH_REQUIRED";
export const isAppToken = (e: unknown): e is ApiError => e instanceof ApiError && e.code === "APP_TOKEN";

/** Bảng giá: trong giờ giao dịch làm mới mỗi 5 giây. `paused` khi đang nhận luồng trực tiếp. */
export function useBoard(paused = false) {
  const { sel, ready } = useSelection();
  const now = new Date();
  const h = now.getHours() + now.getMinutes() / 60;
  const live = now.getDay() >= 1 && now.getDay() <= 5 && h >= 8.75 && h <= 15.05;
  return useQuery({
    queryKey: ["board", sel.broker, sel.account], queryFn: () => api.board(sel),
    enabled: ready && !!sel.broker, refetchInterval: paused ? false : live ? 5_000 : 60_000, refetchIntervalInBackground: false,
  });
}

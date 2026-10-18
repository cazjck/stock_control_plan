export type Severity = "info" | "warning" | "critical";
export interface TelegramStatus {
  configured: boolean; enabled: boolean; token_masked: string | null; chat_id: number | string | null; chat_title: string | null;
  min_severity: Severity; app_url: string | null; last_sent_at: string | null; last_error: string | null; last_run_at: string | null;
}

import type {
  BoardResponse, DeleverageOverview, HoldDecision, Lot, RotationTrade, LedgerAccount, LedgerAccountIn, LedgerDebt, LedgerDebtIn, LedgerPurchaseIn, LedgerView,
  Account, AlertRecord, BrokerStatus, ChartResponse, MarginOverview, Overview, PositionPlan, PositionsResponse,
  RuleChange, RulesResponse, ScenarioRequest, ScenarioResult, SessionInfo, Snapshot, SizingPlan,
} from "./types";

const TOKEN_KEY = "stockctl.token";

export const tokenStore = {
  get: (): string => {
    try { return localStorage.getItem(TOKEN_KEY) ?? ""; } catch { return ""; }
  },
  set: (v: string) => {
    try { v ? localStorage.setItem(TOKEN_KEY, v) : localStorage.removeItem(TOKEN_KEY); } catch { /* bộ nhớ bị chặn */ }
  },
};

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public detail?: unknown) {
    super(message);
  }
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const t = tokenStore.get();
  if (t) headers["X-App-Token"] = t;
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "NETWORK", "Không kết nối được tới máy chủ. Kiểm tra backend đang chạy (cổng 8000).");
  }
  if (!res.ok) {
    let code = "HTTP_" + res.status;
    let message = res.statusText;
    let detail: unknown;
    try {
      const j = await res.json();
      detail = j.detail;
      if (j.detail && typeof j.detail === "object" && !Array.isArray(j.detail)) {
        code = j.detail.code ?? code;
        message = j.detail.message ?? message;
      } else if (typeof j.detail === "string") {
        message = j.detail;
      } else if (Array.isArray(j.detail)) {
        message = j.detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join("; ");
      }
    } catch { /* thân phản hồi không phải JSON */ }
    throw new ApiError(res.status, code, message, detail);
  }
  return (await res.json()) as T;
}

export interface Sel { broker?: string; account?: string }

const qs = (o: Record<string, string | number | boolean | undefined>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(o)) if (v !== undefined && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
};
const sel = (s: Sel) => ({ broker: s.broker, account: s.account });

export const api = {
  health: () => req<{ ok: boolean; read_only: boolean; brokers: string[]; protected: boolean }>("GET", "/health"),
  brokers: () => req<BrokerStatus[]>("GET", "/brokers"),
  auth: (name: string, otp: string) => req<SessionInfo>("POST", `/brokers/${name}/auth`, { otp }),
  accounts: (broker?: string) => req<Account[]>("GET", `/accounts${qs({ broker })}`),
  overview: (s: Sel, refresh = false) => req<Overview>("GET", `/overview${qs({ ...sel(s), refresh })}`),
  positions: (s: Sel) => req<PositionsResponse>("GET", `/positions${qs(sel(s))}`),
  chart: (symbol: string, s: Sel, interval = "1D", count = 250, row?: string) =>
    req<ChartResponse>("GET", `/symbols/${encodeURIComponent(symbol)}/chart${qs({ ...sel(s), interval, count, row })}`),
  /** POST chỉ vì có thân yêu cầu: backend chỉ tính, không ghi gì và không gọi broker. */
  runScenario: (body: ScenarioRequest, s: Sel) => req<ScenarioResult>("POST", `/scenarios/run${qs(sel(s))}`, body),
  sizing: (symbol: string, price: number, stop: number | undefined, s: Sel) =>
    req<SizingPlan>("GET", `/sizing${qs({ symbol, price, stop, ...sel(s) })}`),
  margin: (s: Sel) => req<MarginOverview>("GET", `/margin${qs(sel(s))}`),
  marginPlan: (s: Sel) => req<DeleverageOverview>("GET", `/margin/plan${qs(sel(s))}`),
  board: (s: Sel) => req<BoardResponse>("GET", `/board${qs(sel(s))}`),
  alerts: (status: string, s: Sel) => req<AlertRecord[]>("GET", `/alerts${qs({ status, ...sel(s) })}`),
  ack: (id: number) => req<AlertRecord>("POST", `/alerts/${id}/ack`),
  resolve: (id: number, note: string) => req<AlertRecord>("POST", `/alerts/${id}/resolve`, { note }),
  plans: (s: Sel) => req<PositionPlan[]>("GET", `/plans${qs(sel(s))}`),
  putPlan: (symbol: string, s: Sel, body: Omit<PositionPlan, "broker" | "account_id" | "symbol">) =>
    req<PositionPlan>("PUT", `/plans/${encodeURIComponent(symbol)}${qs(sel(s))}`, body),
  rules: () => req<RulesResponse>("GET", "/settings/rules"),
  putRules: (patch: Record<string, unknown>, confirm: boolean, broker?: string) =>
    req<RulesResponse>("PUT", `/settings/rules${qs({ broker })}`, { patch, confirm_open_positions: confirm }),
  resetRules: (broker?: string) => req<RulesResponse>("DELETE", `/settings/rules${qs({ broker })}`),
  ruleChanges: () => req<RuleChange[]>("GET", "/settings/rule-changes"),
  snapshots: (s: Sel, days = 30) => req<Snapshot[]>("GET", `/snapshots${qs({ ...sel(s), days })}`),
  runSnapshot: (s: Sel) => req<{ nav: number }>("POST", `/snapshots/run${qs(sel(s))}`),

  // sổ danh mục tổng: chỉ ghi vào cơ sở dữ liệu của ứng dụng, không gửi gì tới broker
  ledger: () => req<LedgerView>("GET", "/ledger"),
  ledgerCreate: (body: LedgerAccountIn) => req<LedgerAccount>("POST", "/ledger/accounts", body),
  ledgerUpdate: (id: string, body: LedgerAccountIn) => req<LedgerAccount>("PUT", `/ledger/accounts/${encodeURIComponent(id)}`, body),
  ledgerDelete: (id: string) => req<{ ok: boolean }>("DELETE", `/ledger/accounts/${encodeURIComponent(id)}`),
  ledgerPurchase: (id: string, body: LedgerPurchaseIn) => req<unknown>("POST", `/ledger/accounts/${encodeURIComponent(id)}/purchases`, body),
  ledgerUpdatePosition: (pid: number, body: { quantity?: number; avg_cost?: number; last_price?: number }) =>
    req<unknown>("PUT", `/ledger/positions/${pid}`, body),
  ledgerDeletePosition: (pid: number) => req<{ ok: boolean }>("DELETE", `/ledger/positions/${pid}`),
  ledgerAddDebt: (id: string, body: LedgerDebtIn) => req<LedgerDebt>("POST", `/ledger/accounts/${encodeURIComponent(id)}/debts`, body),
  ledgerUpdateDebt: (did: number, body: LedgerDebtIn) => req<LedgerDebt>("PUT", `/ledger/debts/${did}`, body),
  ledgerDeleteDebt: (did: number) => req<{ ok: boolean }>("DELETE", `/ledger/debts/${did}`),
  // từng lần mua (lô): chỉ ghi vào cơ sở dữ liệu của ứng dụng
  lotAdd: (s: Sel, body: { symbol: string; buy_date: string; quantity: number; price: number; stop_price?: number | null; add_on_loss?: boolean | null }) =>
    req<Lot>("POST", `/lots${qs(sel(s))}`, body),
  lotUpdate: (id: number, body: { stop_price?: number | null; add_on_loss?: boolean; note?: string | null; buy_date?: string; price?: number; quantity?: number }) =>
    req<Lot>("PUT", `/lots/${id}`, body),
  lotDelete: (id: number) => req<{ ok: boolean }>("DELETE", `/lots/${id}`),
  rotationAdd: (s: Sel, body: { symbol: string; side: "sell" | "buy"; trade_date: string; quantity: number; price: number; note?: string | null }) =>
    req<RotationTrade>("POST", `/rotations${qs(sel(s))}`, body),
  rotationDelete: (id: number) => req<{ ok: boolean }>("DELETE", `/rotations/${id}`),
  holdPut: (s: Sel, body: { symbol: string; reason: string; exit_close_below?: number | null; ratio_floor_pct?: number | null; review_on?: string | null }) =>
    req<HoldDecision>("PUT", `/holds${qs(sel(s))}`, body),
  holdDelete: (id: number) => req<{ ok: boolean }>("DELETE", `/holds/${id}`),
  notifyStatus: () => req<TelegramStatus>("GET", "/notify/telegram"),
  notifySave: (body: Partial<{ token: string; chat_id: number | string; chat_title: string; enabled: boolean; min_severity: Severity; app_url: string }>) =>
    req<TelegramStatus>("PUT", "/notify/telegram", body),
  notifyDiscover: (token?: string) => req<{ bot: string; chats: { id: number; type: string; title: string }[] }>("POST", "/notify/telegram/discover", { token: token || null }),
  notifyTest: () => req<TelegramStatus>("POST", "/notify/telegram/test"),
  notifyRun: () => req<TelegramStatus & { sent: number }>("POST", "/notify/run"),
  ledgerSync: (broker: string) =>
    req<{ broker: string; synced_at: string; accounts: string[]; positions: number; debts: number }>("POST", `/ledger/sync/${broker}`),
};

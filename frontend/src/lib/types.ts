import type { components } from "./schema";

type S = components["schemas"];
export type Overview = S["OverviewResponse"];
export type PositionEval = S["PositionEval"];
export type PositionsResponse = S["PositionsResponse"];
export type MarginOverview = S["MarginOverview"];
export type MarginMetrics = S["MarginMetrics"];
export type MarginBucket = S["MarginBucket"];
export type Loan = S["LoanDetail"];
export type LoanStats = S["LoanStats"];
export type AlertRecord = S["AlertRecord"];
export type PositionPlan = S["PositionPlan"];
export type SessionInfo = S["SessionInfo"];
export type Account = S["Account"];
export type MarketInfo = S["MarketInfo"];
export type BrokerStatus = S["BrokerStatus"];
export type PositionStatus = S["PositionStatus"];
export type RulesResponse = S["RulesResponse"];
export type LadderStatus = S["LadderStatus"];
export type Indicators = S["Indicators"];
export type ScenarioRequest = S["ScenarioRequest"];
export type ScenarioResult = S["ScenarioResult"];
export type ScenarioState = S["ScenarioState"];
export type SizingPlan = S["SizingPlan"];
export type SizingTranche = S["SizingTranche"];
export type SizingWarning = S["SizingWarning"];

export interface SeriesPoint { time: string | number; value: number }
export interface CandlePoint { time: string | number; open: number; high: number; low: number; close: number; volume: number }
export interface ChartResponse {
  symbol: string;
  interval: string;
  candles: CandlePoint[];
  sma20: SeriesPoint[];
  sma50: SeriesPoint[];
  ema20: SeriesPoint[];
  rsi14: SeriesPoint[];
  macd: SeriesPoint[];
  macd_signal: SeriesPoint[];
  macd_hist: SeriesPoint[];
  atr14: SeriesPoint[];
  avg_cost: number | null;
  stop_level: number | null;
  stop_basis: string | null;
  evaluation: PositionEval | null;
  evaluations?: PositionEval[];
}

export interface Snapshot {
  day: string;
  nav: number;
  positions_value: number;
  cash: number;
  debt: number;
  interest_per_day: number;
  min_rtt_gap: number | null;
}

export interface RuleChange {
  at: string;
  diff: Record<string, { from: unknown; to: unknown }>;
  had_open_positions: boolean;
}

export type Tone = "safe" | "watch" | "danger" | "breach" | "unknown";

export type LedgerView = S["LedgerView"];
export type LedgerAccountView = S["AccountView"];
export type LedgerPositionView = S["PositionView"];
export type LedgerDebt = S["LedgerDebt"];
export type LedgerAccount = S["LedgerAccount"];
export type LedgerAccountIn = S["AccountIn"];
export type LedgerDebtIn = S["DebtIn"];
export type LedgerPurchaseIn = Omit<S["PurchaseIn"], "record_lot"> & { record_lot?: boolean };
export type SourceShare = S["SourceShare"];
export type TakeProfitPlan = S["TakeProfitPlan"];
export type TakeProfitSignal = S["TakeProfitSignal"];
export type TakeProfitTarget = S["TakeProfitTarget"];
export type LotEval = S["LotEval"];
export type UnknownLot = S["UnknownLot"];
export type Lot = S["Lot"];
export type BoardResponse = S["BoardResponse"];
export type BoardRow = S["BoardRow"];

export type RotationPlan = S["RotationPlan"];
export type RotationTrade = S["RotationTrade"];
export type RotationCheck = S["RotationCheck"];
export type DeleverageOverview = S["DeleverageOverview"];
export type DeleveragePlan = S["DeleveragePlan"];
export type DeleverageStep = S["DeleverageStep"];
export type HoldDecision = S["HoldDecision"];
export type HoldStatus = S["HoldStatus"];
export type TechPlan = S["TechPlan"];
export type TechZone = S["TechZone"];
export type PreTradeCheck = S["PreTradeCheck"];
export type PreTradeItem = S["PreTradeItem"];

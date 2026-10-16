"""Nạp và kiểm tra bộ luật. rules/default.yaml là nguồn sự thật; người dùng ghi đè từng tham số
qua màn hình Thiết lập (lưu SQLite), và mọi lần đổi đều được ghi vào nhật ký."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "rules" / "default.yaml"


class MarketFilter(BaseModel):
    index: str
    fast_ma: int = Field(ge=5)
    slow_ma: int = Field(ge=20)


class EntryRules(BaseModel):
    tranches: list[float]
    add_only_if_up_pct: float
    add_only_if_up_atr_mult: float
    skip_tranche_if_above_avg_pct: float
    rsi_min: float
    rsi_max: float
    volume_ratio_min: float
    max_distance_to_sma20_pct: float
    no_buy_if_day_gain_pct_above: float
    market_filter: MarketFilter


class DcaRules(BaseModel):
    tranches: list[float]
    interval_days: int
    skip_if_above_avg_enabled: bool
    skip_if_above_avg_pct: float
    catastrophe_stop_pct: float = Field(gt=0, le=90)


class StopLossRules(BaseModel):
    pct: float = Field(gt=0, le=15)  # trần 15%: Minervini không quá 10%, cho thêm biên
    atr_multiplier: float = Field(gt=0, le=6)
    atr_period: int
    trigger: str
    minervini_autotune_enabled: bool
    minervini_min_trades: int
    time_stop_sessions: int
    time_stop_min_gain_pct: float
    weak_market_pct: float = Field(gt=0, le=15)


class LadderStep(BaseModel):
    gain_pct: float = Field(gt=0)
    sell_pct: float = Field(ge=0, le=100)
    move_stop_to_gain_pct: float | None = None


class EightWeek(BaseModel):
    enabled: bool
    gain_pct: float
    within_sessions: int
    hold_sessions: int


class Trailing(BaseModel):
    atr_period: int
    atr_multiplier: float = Field(gt=0, le=6)
    floor_sma: int


class ClimaxRules(BaseModel):
    """Dấu hiệu tăng cao trào (O'Neil/IBD climax top): bán vào sức mạnh."""
    gain_pct: float = 25              # tăng từ mức thấp nhất trong cửa sổ
    within_sessions: int = 15         # khoảng 3 tuần
    up_days: int = 7                  # số phiên tăng trong cửa sổ up_days_window
    up_days_window: int = 8
    lookback_sessions: int = 60       # phiên tăng mạnh nhất kể từ đầu sóng
    volume_ratio: float = 2.0         # khối lượng cao trào so với TB20
    exhaustion_gap_min_gain_pct: float = 20
    extension_above_sma50_pct: float = 25
    rsi_overbought: float = 80        # chỉ là tín hiệu phụ
    min_signals_partial: int = 2
    sell_fraction: float = Field(default=0.5, gt=0, le=1)


class WeaknessRules(BaseModel):
    """Bán khi yếu đi để giữ lãi (IBD): thủng EMA21 với khối lượng lớn, đóng cửa dưới SMA50."""
    min_gain_pct: float = 5           # chỉ áp dụng khi đang lãi từ mức này
    ema_period: int = 21
    heavy_volume_ratio: float = 1.5
    ema_sell_fraction: float = Field(default=0.5, gt=0, le=1)
    sma_exit: int = 50


class TakeProfitRules(BaseModel):
    ladder: list[LadderStep]
    weak_market_exit_gain_pct: float
    eight_week_rule: EightWeek
    trailing: Trailing
    r_targets: list[float] = [2, 3]
    climax: ClimaxRules = ClimaxRules()
    weakness: WeaknessRules = WeaknessRules()

    @model_validator(mode="after")
    def _ladder_sorted(self):
        gains = [s.gain_pct for s in self.ladder]
        if gains != sorted(gains):
            raise ValueError("ladder phải xếp theo gain_pct tăng dần")
        if sum(s.sell_pct for s in self.ladder) > 100:
            raise ValueError("tổng sell_pct của ladder không được quá 100")
        return self


class TrappedRules(BaseModel):
    loss_pct_threshold: float
    group_b_sell_now_pct: float
    group_b_sell_rest_after_sessions: int
    group_a_stop_from_price_pct: float
    group_a_stop_below_low20_pct: float


class AddOnLotRules(BaseModel):
    stop_below_buy_day_low_pct: float = 1
    stop_from_price_pct: float = Field(default=5, gt=0, le=20)
    settle_sessions: int = 2
    time_stop_sessions_after_settle: int = 3
    time_stop_min_gain_pct: float = 3


class RotationTier(BaseModel):
    rebound_pct: float = Field(gt=0)
    retrace_pct: float = Field(gt=0, lt=100)
    sell_pct: float = Field(gt=0, le=100)


class RotationRules(BaseModel):
    """Đảo hàng khi hồi (mục 6b)."""
    enabled: bool = True
    low_lookback_sessions: int = Field(default=20, ge=5)
    high_lookback_sessions: int = Field(default=60, ge=10)
    min_rebound_pct: float = 5
    sell_tiers: list[RotationTier] = [RotationTier(rebound_pct=10, retrace_pct=38.2, sell_pct=30),
                                      RotationTier(rebound_pct=20, retrace_pct=50, sell_pct=20)]
    bear_rsi_ceiling: float = 60
    trend_change_retrace_pct: float = 61.8
    max_rotation_pct: float = Field(default=50, gt=0, le=50)   # không bao giờ đảo quá một nửa
    rebuy_drop_pct: float = Field(default=7, gt=0)
    rebuy_min_sessions: int = Field(default=3, ge=3)            # tiền bán về sau T+2
    rebuy_window_sessions: int = Field(default=20, ge=5)
    no_chase_above_sell_pct: float = 5


class TechnicalRules(BaseModel):
    """Kế hoạch theo kỹ thuật (mục 6d)."""
    stage_ma: int = Field(default=150, ge=20)
    stage_slope_sessions: int = Field(default=20, ge=5)
    stage_flat_pct: float = 0.5
    lookback: int = Field(default=120, ge=30)
    pivot_bars: int = Field(default=3, ge=1, le=10)
    merge_atr: float = Field(default=0.5, gt=0)
    max_zone_distance_pct: float = 40
    min_strength: int = Field(default=2, ge=1)
    max_zones: int = Field(default=3, ge=1, le=5)
    sell_pct_per_zone: float = Field(default=10, gt=0, le=50)
    max_total_pct: float = Field(default=30, gt=0, le=50)
    margin_max_total_pct: float = Field(default=50, gt=0, le=50)
    invalidation_atr: float = 0.5
    ftd_min_gain_pct: float = 1.25
    ftd_window: int = 25


class MarginRules(BaseModel):
    new_positions: str
    rtt_buffer_pct_points: float
    interest_alert_pct_nav_per_day: float
    sell_cost_pct: float = Field(default=0.25, ge=0, le=2)


class AlertRules(BaseModel):
    rtt_warn_points: float
    loan_due_days: list[int]
    portfolio_loss_pct_nav: float
    stale_quote_minutes: int


class BehaviorRules(BaseModel):
    max_new_buys_per_day: int
    max_new_symbols_per_week: int
    cooldown_after_consecutive_stops: dict[str, int]
    review_after_trades: int


class Rules(BaseModel):
    capital_mode: str
    risk_per_trade_pct: float = Field(gt=0, le=3)  # Elder: trần 2%, cho biên đến 3%
    max_weight_pct: float = Field(gt=0, le=100)
    max_positions: int
    monthly_risk_budget_pct: float
    entry: EntryRules
    dca: DcaRules
    stop_loss: StopLossRules
    take_profit: TakeProfitRules
    trapped: TrappedRules
    add_on_lots: AddOnLotRules = AddOnLotRules()
    rotation: RotationRules = RotationRules()
    technical: TechnicalRules = TechnicalRules()
    margin: MarginRules
    alerts: AlertRules
    behavior: BehaviorRules


def load_defaults() -> dict[str, Any]:
    return yaml.safe_load(DEFAULT_PATH.read_text())


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)  # danh sách được thay nguyên khối
    return out


def build_rules(overrides: dict[str, Any] | None = None) -> Rules:
    return Rules.model_validate(deep_merge(load_defaults(), overrides or {}))

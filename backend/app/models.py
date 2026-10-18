"""Model chuẩn hoá. Risk engine và API chỉ nhìn thấy các model này,
không bao giờ thấy JSON thô của từng broker."""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field


class Interval(str, Enum):
    M15 = "15m"
    H1 = "1h"
    D1 = "1D"
    W1 = "1W"


# ---------- Phiên và kết nối ----------

class SessionInfo(BaseModel):
    broker: str
    configured: bool
    authenticated: bool
    needs_otp: bool
    expires_at: datetime | None = None
    message: str | None = None


# ---------- Tài khoản ----------

class Account(BaseModel):
    broker: str
    id: str
    name: str | None = None
    kind: Literal["margin", "normal", "other"] = "other"
    custody_code: str | None = None
    margin_limit: float | None = None


class SourceShare(BaseModel):
    """Phần nắm giữ của một mã tại một nguồn (công ty chứng khoán hoặc tiểu danh mục)."""

    source: str                 # "TCBS", "SSI", "VPS"...
    account: str | None = None
    quantity: int
    avg_cost: float


class Position(BaseModel):
    broker: str
    account_id: str
    symbol: str
    quantity: int
    avg_cost: float
    price: float | None = None
    market_value: float = 0.0
    external_id: str | None = None
    loan_package_id: int | None = None
    sources: list[SourceShare] = []
    row_id: str | None = None   # khoá dòng: mã cho broker thật, "tiểu danh mục:mã" cho sổ tổng

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cost_value(self) -> float:
        return self.quantity * self.avg_cost

    @computed_field  # type: ignore[prop-decorator]
    @property
    def pnl(self) -> float:
        return self.market_value - self.cost_value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def pnl_pct(self) -> float | None:
        return (self.pnl / self.cost_value * 100) if self.cost_value else None


class CashBalance(BaseModel):
    account_id: str
    cash: float = 0.0
    available_cash: float | None = None
    reported_debt: float | None = None


class MarginBucket(BaseModel):
    """Một nhóm ký quỹ. TCBS trả 1 bucket cho cả tài khoản, DNSE trả 1 bucket cho mỗi Deal."""

    id: str
    scope: Literal["account", "deal"]
    label: str
    symbols: list[str] = []
    # Cách đo tỷ lệ khác nhau giữa các broker:
    #  "equity_over_value": (giá trị tài sản − nợ) / giá trị tài sản (DNSE, dữ liệu demo)
    #  "collateral_over_debt": tài sản đảm bảo / dư nợ (RTT của TCBS: duy trì 85, giải chấp 80, ban đầu 100)
    ratio_kind: Literal["equity_over_value", "collateral_over_debt"] = "equity_over_value"
    ratio_pct: float | None = None  # đơn vị %
    initial_pct: float | None = None
    maintenance_pct: float | None = None
    liquidation_pct: float | None = None
    market_value: float | None = None
    debt: float | None = None  # gốc + lãi dồn
    status_text: str | None = None
    source: str | None = None   # công ty chứng khoán của nhóm ký quỹ
    raw: dict[str, Any] = {}


class Loan(BaseModel):
    id: str
    symbol: str | None = None
    source: str | None = None   # công ty chứng khoán của khoản vay
    disbursement_date: date | None = None
    due_date: date | None = None
    principal: float = 0.0
    remaining_principal: float = 0.0
    accrued_interest: float = 0.0
    annual_rate_pct: float | None = None


class Candle(BaseModel):
    t: datetime  # tz-aware, giờ Việt Nam
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class Quote(BaseModel):
    symbol: str
    price: float | None = None
    ref_price: float | None = None
    change_pct: float | None = None


# ---------- Kết quả đánh giá rủi ro ----------

class MarketState(str, Enum):
    NORMAL = "NORMAL"            # VN-Index trên SMA50 và SMA200
    NO_NEW_BUYS = "NO_NEW_BUYS"  # trên SMA200, dưới SMA50
    WEAK = "WEAK"                # dưới SMA200
    UNKNOWN = "UNKNOWN"


class MarketInfo(BaseModel):
    state: MarketState
    index_symbol: str = "VNINDEX"
    close: float | None = None
    sma50: float | None = None
    sma200: float | None = None
    note: str | None = None


class PositionStatus(str, Enum):
    SAFE = "SAFE"
    WARNING = "WARNING"
    TAKE_PROFIT = "TAKE_PROFIT"
    TIME_STOP = "TIME_STOP"
    STOP_HIT = "STOP_HIT"
    TRAPPED = "TRAPPED"


class Indicators(BaseModel):
    close: float | None = None
    sma20: float | None = None
    sma50: float | None = None
    ema20: float | None = None
    rsi14: float | None = None
    atr14: float | None = None
    atr14_pct: float | None = None
    atr22: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_hist: float | None = None
    high20: float | None = None
    low20: float | None = None
    volume_ratio: float | None = None
    close_vs_sma20_pct: float | None = None


class LadderStatus(BaseModel):
    gain_pct: float
    sell_pct: float
    stop_at_gain_pct: float | None
    reached: bool          # lãi hiện tại đã chạm mốc
    executed: bool         # theo kế hoạch người dùng khai báo
    suspended: bool = False  # tạm hoãn do luật 8 tuần


class PositionPlan(BaseModel):
    """Kế hoạch do người dùng khai báo, broker không cung cấp."""

    broker: str
    account_id: str
    symbol: str
    mode: Literal["swing", "dca"] = "swing"
    entry_date: date | None = None
    has_thesis: bool | None = None  # đã viết được luận điểm 3 câu chưa
    ladder_done: int = 0            # số bậc chốt lời đã thực hiện
    note: str | None = None


class TakeProfitTarget(BaseModel):
    label: str               # "+10%", "2R"
    kind: Literal["ladder", "r"]
    price: float
    distance_pct: float      # giá hiện tại còn cách mục tiêu bao nhiêu % (âm là đã vượt)
    sell_pct_of_original: float | None = None
    sell_qty: int | None = None
    reached: bool
    executed: bool = False
    suspended: bool = False


class TakeProfitSignal(BaseModel):
    code: str
    group: Literal["strength", "weakness"]
    label: str               # mô tả điều kiện
    met: bool
    detail: str              # số liệu thực tế để người dùng tự kiểm


class TakeProfitAdvice(BaseModel):
    level: Literal["none", "watch", "partial", "full"]
    text: str
    sell_qty: int = 0
    reason_codes: list[str] = []


class TakeProfitPlan(BaseModel):
    r_value: float | None            # 1R = giá vốn − mức cắt lỗ ban đầu
    r_multiple: float | None         # lãi hiện tại tính theo R
    original_qty: int
    targets: list[TakeProfitTarget]
    signals: list[TakeProfitSignal]
    advice: TakeProfitAdvice
    next_target: TakeProfitTarget | None = None


class RotationTrade(BaseModel):
    """Một lần bán hoặc mua lại trong chu kỳ đảo hàng (mục 6b). Người dùng tự ghi; app không đặt lệnh."""
    id: int
    broker: str
    account_id: str
    symbol: str
    side: Literal["sell", "buy"]
    trade_date: date
    quantity: int
    price: float
    note: str | None = None


class RotationCheck(BaseModel):
    code: str
    label: str
    met: bool
    detail: str


class RotationPlan(BaseModel):
    """Khuyến nghị đảo hàng hôm nay cho một dòng vị thế."""
    phase: Literal["off", "falling", "rebounding", "sell_zone", "trend_change",
                   "wait_rebuy", "rebuy_zone", "broken", "missed", "expired"]
    phase_label: str
    level: Literal["none", "watch", "sell", "rebuy", "blocked"]
    text: str
    sell_qty: int = 0
    rebuy_qty: int = 0
    rebuy_allowed: bool = True          # nhóm B, margin chưa an toàn: không được mua lại
    low: float | None = None            # đáy gần nhất
    high: float | None = None           # đỉnh trước đoạn giảm
    rebound_pct: float | None = None
    retrace_pct: float | None = None
    tier_prices: list[float] = []       # giá bắt đầu vùng bán của từng bậc
    tier_qtys: list[int] = []           # số cổ phiếu bán thêm ở từng bậc (theo lượng gốc)
    rebuy_below: float | None = None    # mua lại khi giá từ mức này trở xuống
    floor: float | None = None          # đáy cũ: thủng thì không mua lại
    base_qty: int = 0                   # lượng gốc của chu kỳ = đang giữ + đã bán chưa mua lại
    sold_qty: int = 0
    sold_avg: float | None = None
    bought_qty: int = 0
    open_qty: int = 0                   # đã bán, chưa mua lại
    sessions_since_sell: int | None = None
    sessions_left: int | None = None
    checks: list[RotationCheck] = []
    trades: list[RotationTrade] = []


class TechZone(BaseModel):
    """Một vùng giá do nhiều công cụ kỹ thuật cùng chỉ ra (mục 6d)."""
    price: float
    low: float
    high: float
    kind: Literal["resistance", "support"]
    tools: list[str]
    strength: int                    # số nhóm công cụ khác nhau
    distance_pct: float              # so với giá hiện tại
    sell_pct: float = 0.0            # bán bao nhiêu % lượng đang giữ ở vùng này (vùng cản)
    sell_qty: int = 0
    cum_pct: float = 0.0
    ratio_after: float | None = None # tỷ lệ ký quỹ của tài khoản sau khi bán ở vùng này
    margin_sized: bool = False       # vùng đầu được nâng khối lượng để tài khoản về vùng an toàn


class TechCheck(BaseModel):
    code: str
    label: str
    met: bool
    detail: str


class TechScenario(BaseModel):
    name: Literal["rebound", "sideways", "decline"]
    title: str
    trigger: str
    action: str


class TechPlan(BaseModel):
    stage: int | None
    stage_label: str
    stage_detail: str
    resistance: list[TechZone] = []
    support: list[TechZone] = []
    sell_zones: list[TechZone] = []
    invalidation: float | None = None
    invalidation_basis: str = ""
    bottom_checks: list[TechCheck] = []
    bottom_score: int = 0
    bottom_label: str = ""
    scenarios: list[TechScenario] = []
    summary: str = ""


class HoldDecision(BaseModel):
    """Quyết định gồng có kế hoạch (mục 6c): người dùng chọn giữ mã lỗ, kèm ngưỡng thoát cứng."""
    id: int
    broker: str
    account_id: str
    symbol: str
    decided_at: date
    exit_close_below: float          # đóng cửa dưới giá này: giả định "đáy" sai, bán theo kế hoạch
    ratio_floor_pct: float | None    # tỷ lệ ký quỹ chạm mức này: nộp tiền hoặc bán ngay
    review_on: date
    reason: str


class HoldStatus(BaseModel):
    decision: HoldDecision
    state: Literal["holding", "restructure", "review", "exit_margin", "exit_price"]
    text: str
    days_held: int
    interest_cost: float             # lãi margin ước tính cho phần của mã này từ ngày quyết định
    interest_per_day: float
    distance_to_exit_pct: float | None
    ratio_pct: float | None
    ratio_floor_pct: float | None


class PositionEval(BaseModel):
    row_id: str = ""                 # khoá dòng; cùng mã ở nhiều nguồn thì mỗi nguồn một dòng
    source: str | None = None        # nguồn của dòng (TCBS, SSI, VPS...)
    account_id: str | None = None
    take_profit: TakeProfitPlan | None = None
    rotation: RotationPlan | None = None
    hold: HoldStatus | None = None
    margin_call_price: float | None = None     # giá mã này mà tài khoản chạm ngưỡng duy trì (các mã khác đứng giá)
    liquidation_price: float | None = None     # giá mã này mà tài khoản chạm ngưỡng xử lý / giải chấp
    margin_call_distance_pct: float | None = None
    technical: TechPlan | None = None
    lots: list["LotEval"] = []
    unknown_lot: "UnknownLot | None" = None
    sources: list[SourceShare] = []
    symbol: str
    quantity: int
    avg_cost: float
    price: float
    market_value: float
    pnl: float
    pnl_pct: float
    weight_pct: float
    mode: Literal["swing", "dca"]
    status: PositionStatus
    urgency: float
    stop_level: float | None
    stop_basis: str
    distance_to_stop_pct: float | None
    risk_to_stop_value: float | None
    peak_gain_pct: float
    peak_is_proxy: bool
    indicators: Indicators
    ladder: list[LadderStatus]
    actions: list[str]
    flags: list[str]
    plan: PositionPlan | None = None
    data_ok: bool = True


class MarginMetrics(BaseModel):
    bucket: MarginBucket
    drop_to_maintenance_pct: float | None  # thị trường giảm bao nhiêu % thì chạm maintenance
    drop_to_liquidation_pct: float | None
    cash_to_safe: float | None             # tiền cần nộp để về maintenance + biên an toàn
    safe_target_pct: float | None
    zone: Literal["safe", "watch", "danger", "breach", "unknown"]


class MaturityBucket(BaseModel):
    label: str
    days: int
    amount: float
    count: int


class LoanStats(BaseModel):
    """Số liệu nợ và lãi cho một nhóm khoản vay (toàn bộ, hoặc một nguồn như TCBS, SSI)."""

    source: str | None = None
    count: int
    principal_disbursed: float          # tổng giải ngân ban đầu
    principal_paid: float               # gốc đã trả
    principal_remaining: float          # dư nợ gốc
    accrued_interest: float             # lãi tạm tính đến hôm nay
    payoff_today: float                 # tất toán hôm nay: gốc + lãi tạm tính
    interest_per_day: float
    interest_per_month: float           # 30 ngày
    interest_per_year: float
    avg_rate_pct: float | None          # lãi suất bình quân theo dư nợ
    interest_to_maturity: float         # lãi dự kiến từ nay tới ngày đáo hạn của từng khoản
    loans_without_due_date: int = 0
    avg_days_borrowed: float | None = None   # số ngày đã vay bình quân theo dư nợ
    next_due_date: date | None = None
    next_due_amount: float | None = None


class LoanDetail(Loan):
    days_borrowed: int | None = None
    days_to_due: int | None = None
    interest_per_day: float = 0.0
    interest_to_maturity: float | None = None


class MarginOverview(BaseModel):
    buckets: list[MarginMetrics]
    loans: list[LoanDetail]
    maturity: list[MaturityBucket]
    total_debt: float
    interest_per_day: float
    interest_30d: float
    stats: LoanStats | None = None
    stats_by_source: list[LoanStats] = []
    breakeven_monthly_pct: float | None = None   # cổ phiếu phải tăng bao nhiêu %/tháng chỉ để bù lãi
    interest_pct_nav_monthly: float | None = None


class AssetOverview(BaseModel):
    positions_value: float
    cost_value: float
    cash: float
    debt: float
    nav: float
    unrealized_pnl: float
    unrealized_pnl_pct: float | None
    interest_per_day: float
    interest_pct_nav_per_day: float | None


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertCandidate(BaseModel):
    key: str
    rule: str
    severity: AlertSeverity
    title: str
    message: str
    symbol: str | None = None
    data: dict[str, Any] = {}


class AlertRecord(BaseModel):
    id: int
    key: str
    rule: str
    severity: AlertSeverity
    title: str
    message: str
    symbol: str | None
    data: dict[str, Any]
    status: Literal["open", "acked", "cleared", "resolved"]
    broker: str
    account_id: str
    first_seen: datetime
    last_seen: datetime
    resolution_note: str | None = None


class OverviewResponse(BaseModel):
    broker: str
    account_id: str
    as_of: datetime
    session: SessionInfo
    market: MarketInfo
    assets: AssetOverview
    margin: MarginOverview
    top_alerts: list[AlertRecord]
    counts: dict[str, int]
    data_age_seconds: int = 0
    read_only: bool = True


# ---------- Kịch bản giả định (chỉ tính toán, không ghi gì, không gọi broker) ----------

class ScenarioSell(BaseModel):
    symbol: str
    quantity: int = Field(gt=0)


class ScenarioRequest(BaseModel):
    market_drop_pct: float = Field(0.0, ge=0, le=90, description="Thị trường giảm bao nhiêu %, số dương: 10 nghĩa là giảm 10%")
    sell: list[ScenarioSell] = []
    add_cash: float = Field(0.0, ge=0, description="Tiền nộp thêm (VND), được dùng trả nợ margin")


class ScenarioState(BaseModel):
    """Danh mục và ký quỹ ở một thời điểm: trước hoặc sau kịch bản."""

    positions_value: float
    cash: float
    debt: float
    nav: float
    unrealized_pnl: float
    unrealized_pnl_pct: float | None
    interest_per_day: float
    buckets: list[MarginMetrics]
    focus_bucket_id: str | None   # nhóm sát ngưỡng nhất, dùng cho thước mớn nước
    cash_needed: float            # tổng tiền còn cần nộp để mọi nhóm về vùng an toàn


class ScenarioResult(BaseModel):
    request: ScenarioRequest
    before: ScenarioState
    after: ScenarioState
    sale_proceeds: float          # tiền bán thu về, tính theo giá sau khi thị trường giảm
    realized_pnl: float           # lãi lỗ đã thực hiện của phần bán thử, so với giá vốn
    debt_repaid: float            # nợ giảm đi nhờ tiền bán và tiền nộp thêm
    warnings: list[str] = []


# ---------- Máy tính khối lượng mua theo luật (mục 1 và 2 của bộ luật) ----------

class SizingTranche(BaseModel):
    index: int
    pct: float
    quantity: int
    value: float
    trigger_price: float | None   # giá đóng cửa tối thiểu để được mua đợt này (đợt 1: giá vào)
    condition: str
    likely_skipped: bool = False


class SizingWarning(BaseModel):
    code: str
    severity: Literal["block", "warn", "info"]  # block: luật không cho mở vị thế mới, hoặc kế hoạch bằng 0
    message: str


class SizingPlan(BaseModel):
    symbol: str
    price: float
    stop_price: float
    stop_basis: str
    stop_distance: float
    stop_distance_pct: float
    atr14: float | None
    capital: float                # tiền mặt thực có, không tính margin
    risk_pct: float
    risk_money: float
    max_weight_pct: float
    qty_by_risk: int              # theo rủi ro 1R, làm tròn xuống lô 100
    qty_by_weight: int            # trần theo tỷ trọng tối đa
    qty_plan: int
    binding: Literal["risk", "weight"]
    plan_value: float
    plan_weight_pct: float | None
    risk_at_stop: float           # số tiền mất nếu toàn bộ kế hoạch chạm cắt lỗ
    tranches: list[SizingTranche]
    held_quantity: int
    additional_quantity: int      # phần còn cần mua thêm nếu đang giữ mã này
    positions_count: int
    max_positions: int
    market: MarketInfo
    allowed: bool                 # false nếu có cảnh báo block
    warnings: list[SizingWarning]


# ---------- Sổ danh mục tổng (nhập tay hoặc đồng bộ từ broker thật) ----------

RatioKind = Literal["equity_over_value", "collateral_over_debt"]


class LedgerAccount(BaseModel):
    """Một tiểu danh mục trong sổ tổng: SSI, VPS nhập tay, hoặc bản chép từ TCBS."""

    id: str
    name: str
    source: Literal["manual", "sync"] = "manual"
    source_broker: str | None = None
    source_account: str | None = None
    cash: float = 0.0
    ratio_kind: RatioKind = "equity_over_value"
    ratio_pct: float | None = None         # RTT đọc từ app broker (bắt buộc với kiểu tài sản đảm bảo / dư nợ)
    ratio_ref_value: float | None = None   # giá trị cổ phiếu lúc ghi RTT, để quy đổi RTT theo giá hiện tại
    initial_pct: float | None = None
    maintenance_pct: float | None = None
    liquidation_pct: float | None = None
    synced_at: datetime | None = None
    note: str | None = None


class LedgerPosition(BaseModel):
    id: int
    account_id: str
    symbol: str
    quantity: int
    avg_cost: float
    last_price: float | None = None
    bought_at: date | None = None
    note: str | None = None


class LedgerDebt(BaseModel):
    id: int
    account_id: str
    symbol: str | None = None
    principal: float
    remaining_principal: float
    accrued_interest: float = 0.0
    annual_rate_pct: float | None = None
    disbursement_date: date | None = None
    due_date: date | None = None
    note: str | None = None


# ---------- Từng lần mua (lô) ----------

class Lot(BaseModel):
    """Một lần mua của một mã. Nguồn: tự phát hiện khi khối lượng tăng, nhập tay, hoặc lệnh mua ghi trong sổ."""

    id: int
    broker: str
    account_id: str
    symbol: str
    buy_date: date
    quantity: int            # khối lượng mua ban đầu của lô
    remaining: int           # còn lại sau khi bán (bán trừ lô mới nhất trước)
    price: float
    source: Literal["auto", "manual", "ledger"]
    add_on_loss: bool        # mua thêm khi mã đang lỗ (giá mua thấp hơn giá vốn lúc đó)
    stop_price: float | None = None
    trigger_date: date | None = None   # phiên luật lô yêu cầu bán lần đầu
    trigger_price: float | None = None
    estimated: bool = False  # giá mua là ước tính
    note: str | None = None


class LotEval(Lot):
    source_label: str | None = None
    current_price: float | None = None
    pnl_pct: float | None = None
    pnl_value: float | None = None
    sessions_held: int | None = None
    sellable_from: date | None = None
    sellable: bool = False
    deadline: date | None = None     # hạn cắt lỗ theo thời gian
    rule_status: Literal["ok", "stop", "time", "closed", "info"] = "info"
    action: str | None = None
    delay_sessions: int | None = None
    delay_cost: float | None = None  # tiền mất thêm kể từ phiên luật yêu cầu bán


class UnknownLot(BaseModel):
    quantity: int
    avg_cost: float | None    # giá vốn suy ra cho phần chưa rõ ngày mua


PositionEval.model_rebuild()


# ---------- Bảng giá ----------

class BookLevel(BaseModel):
    price: float
    qty: float


class BoardQuote(BaseModel):
    symbol: str
    ref: float | None = None
    ceil: float | None = None
    floor: float | None = None
    price: float | None = None       # giá khớp gần nhất
    change: float | None = None
    change_pct: float | None = None
    match_qty: float | None = None
    total_vol: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    avg: float | None = None
    bid: list[BookLevel] = []        # bước 1 là giá tốt nhất
    offer: list[BookLevel] = []
    foreign_buy: float | None = None
    foreign_sell: float | None = None
    room: float | None = None


class BoardRow(BoardQuote):
    held_qty: int = 0
    avg_cost: float | None = None
    pnl_pct: float | None = None
    sources: list[str] = []


class BoardIndex(BaseModel):
    symbol: str
    value: float | None = None
    change: float | None = None
    change_pct: float | None = None


class BoardResponse(BaseModel):
    as_of: datetime
    source: str | None
    rows: list[BoardRow]
    index: BoardIndex | None = None
    note: str | None = None


class DeleverageStep(BaseModel):
    """Một bước bán để hạ nợ margin. Chỉ là khuyến nghị; người dùng tự đặt lệnh."""
    kind: Literal["lot_rule", "stop", "group_b", "rotation", "worst_loss", "to_zero"]
    symbol: str
    row_id: str
    quantity: int
    price: float
    proceeds: float              # tiền về sau phí và thuế
    reason: str
    ratio_after: float | None    # RTT sau bước này
    debt_after: float
    interest_per_day_after: float
    reaches_target: bool = False
    deferred: bool = False       # mã đang gồng theo quyết định (mục 6c): hoãn, chưa bắt buộc


class DeleveragePlan(BaseModel):
    """Lộ trình hạ margin của một tài khoản ký quỹ (mục 5b)."""
    bucket_id: str
    label: str
    source: str | None = None
    ratio_kind: str
    ratio_pct: float | None
    maintenance_pct: float | None
    liquidation_pct: float | None
    target_pct: float | None
    zone: str
    market_value: float
    debt: float
    interest_per_day: float
    cash_alternative: float | None         # nộp tiền thay cho việc bán để về vùng an toàn
    safe_steps: list[DeleverageStep] = []
    safe_ratio_after: float | None = None
    safe_debt_after: float = 0.0
    safe_interest_after: float = 0.0
    safe_reached: bool = False
    committed_ratio_after: float | None = None   # RTT sau các lệnh không bị hoãn
    committed_interest_after: float = 0.0
    deferred_symbols: list[str] = []
    zero_steps: list[DeleverageStep] = []
    zero_shortfall: float = 0.0            # bán hết vẫn còn nợ
    zero_interest_saved: float = 0.0
    due_30d_amount: float = 0.0
    due_30d_first: date | None = None
    due_30d_count: int = 0
    headline: str = ""
    notes: list[str] = []


class DeleverageOverview(BaseModel):
    plans: list[DeleveragePlan]
    total_debt: float
    interest_per_day: float
    interest_after_safe: float
    safe_sell_value: float
    safe_proceeds: float
    accounts_unsafe: int
    deferred_sell_value: float = 0.0

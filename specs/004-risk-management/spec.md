# Specification: Risk Management and Operational Kill-Switch (`004-risk-management`)

**Status:** approved  
**Date:** 2026-11-11  
**Domain Area:** `src/risk/`

---

## 1. Objective
Implement a deterministic Risk Management layer (`src/risk/`) positioned strictly between the Strategy Layer (`src/strategies/`) and Order Execution / Backtesting (`src/backtest/`, future `src/execution/`), matching the decoupled pipeline defined in `PROJETO.md`. The layer protects a small retail capital base (default R$ 100.00 on B3 fractional market) from mathematical ruin, excessive drawdowns, system latency anomalies, and unintended Day Trade penalties through:
1. **Position Sizing (`PositionSizer`):** Strict integer lot calculation for B3 fractional shares (`F` market, lot size = 1) respecting the 2% risk-per-trade budget, cash availability, and B3 fees (0.03%), with an explicit opt-in minimum-lot override flag.
2. **Stop-Loss & Trailing Stop (`StopMonitor`):** Capital preservation rules limiting per-trade downside (5% default) and locking in unrealized profits (5% trailing stop active by default).
3. **Operational Kill-Switch (`KillSwitch`):** Automated fail-closed circuit breaker halting trading on excessive daily loss (2% per `PROJETO.md`, auto-resets on new trading date), excessive cumulative drawdown (10% peak-to-trough, manual reset), or degraded feed/API latency (> 500ms per `PROJETO.md`, manual reset).
4. **Pre-Trade Risk Gate & Backtest Overlay (`RiskManager`):** Unified facade validating live/simulated trades (including Swing Trade custody guard allowing emergency exits on $D_0$) and providing a close-based daily risk signal overlay compatible with `VectorizedBacktestEngine`.

---

## 2. Out of Scope
* **Direct Network / Broker Execution:** Canceling live orders via HTTP/REST or terminating the OS process via `sys.exit(1)` directly inside `src/risk/` (belongs to Phase 5 `src/execution/`, which reacts to `KillSwitch` verdicts).
* **Short Selling / Margin Leverage:** Exposure remains strictly Long/Cash (`>= 0` shares, no borrowing or margin calls).
* **Cross-Asset Portfolio Correlation / VaR Optimization:** Multi-asset covariance matrix sizing is out of scope; each asset position is sized against available account equity.
* **Intraday Tick-Level / Bar-Low Stop Simulation:** Stop evaluation in historical backtests operates strictly on daily `Close` bars fed as `{0, 1}` risk-filtered signals to `VectorizedBacktestEngine` (bar $t$ close decision -> executed at $t+1$), preserving zero changes to Phase 2 and eliminating intraday High/Low ordering assumptions.

---

## 3. Acceptance Criteria

### Criteria Derived from `PROJETO.md`
* **AC01:** **Kill-Switch Daily Loss Limit:** The `KillSwitch` must trip (`HALTED`, reason `DAILY_LOSS_LIMIT`) whenever accumulated daily loss reaches or exceeds `max_daily_loss_pct` (default `0.02`, i.e., 2% of starting day equity), and automatically reset when a strictly newer trading date begins.
* **AC02:** **Kill-Switch Latency Limit:** The `KillSwitch` must trip (`HALTED`, reason `LATENCY_LIMIT`) whenever reported market-feed or broker latency strictly exceeds `max_latency_ms` (default `500.0` ms), requiring explicit manual operator reset (`reset(confirm=True)`).
* **AC03:** **B3 Fractional Lot Sizing & Cash Guard:** `PositionSizer` must compute integer share quantities (`int >= 0`) aligned with B3 fractional market lot rules (`lot_size=1` default, configurable to `100` for standard lots), ensuring `shares * entry_price * (1 + b3_fee_pct) <= available_cash` (default fee `0.0003`, zero brokerage via RLP).
* **AC04:** **Swing Trade Custody Protection (Voluntary Exits Only):** When `allow_day_trade=False` (default per `PROJETO.md` Section 1.2), the pre-trade risk validator must reject **voluntary strategy exit** orders on the same calendar date as entry ($D_0$), while **explicitly allowing emergency exits** triggered by Stop-Loss, Trailing Stop, or Kill-Switch.

### Criteria Derived from Software Engineering Standards & Approved Risk Decisions
* **AC05:** **Strict Fixed-Fractional Risk Sizing (with Configurable Override):** Given `capital`, `entry_price`, and `stop_loss_price` (where `0 < stop_loss_price < entry_price`), `PositionSizer` must cap integer share count so maximum planned loss `(entry_price - stop_loss_price) * shares` does not exceed `capital * max_risk_per_trade_pct` (default `0.02`). If the calculated lot count is `0` under strict risk (`allow_min_lot_override=False`, default), the trade must be rejected (`shares=0`, `approved=False`). Only if `allow_min_lot_override=True` and cash suffices for `1 * lot_size` does it allow `1 * lot_size` shares.
* **AC06:** **Max Drawdown Circuit Breaker:** The `KillSwitch` must monitor cumulative peak-to-trough drawdown against `max_drawdown_pct` (default `0.10`, i.e., 10%) and trip (`HALTED`, reason `MAX_DRAWDOWN_LIMIT`) once reached or exceeded, requiring explicit manual reset (`reset(confirm=True)`).
* **AC07:** **Fixed Stop-Loss Trigger:** `StopMonitor` must trigger an exit signal (`STOP_LOSS`) whenever the evaluation price breaches the fixed stop threshold (`price <= entry_price * (1 - stop_loss_pct)`), with default `stop_loss_pct = 0.05` (5%).
* **AC08:** **Trailing Stop Trigger:** With `trailing_stop_pct = 0.05` active by default (or configurable / `None` to disable), `StopMonitor` must track the position's high-water mark price since entry and trigger an exit signal (`TRAILING_STOP`) whenever `price <= highest_price * (1 - trailing_stop_pct)`.
* **AC09:** **Kill-Switch Fail-Closed & Reset Policy:** While `KillSwitch` is `HALTED`, `RiskManager.evaluate_trade(...)` must reject all new Long entries (`approved=False`, `action="HALT"`). Latency and Max Drawdown halts must persist across dates until `reset(confirm=True)` is called; `reset(confirm=False)` must raise `RiskError` or leave the switch halted.
* **AC10:** **Input & Parameter Validation:** All risk configuration models and calculators must strictly reject invalid parameters (negative/zero capital, fee `< 0`, `stop_loss_pct <= 0` or `>= 1`, `trailing_stop_pct <= 0` or `>= 1` when set, `max_daily_loss_pct <= 0` or `>= 1`, `max_drawdown_pct <= 0` or `>= 1`, `max_latency_ms <= 0`, `lot_size < 1`, non-finite `NaN`/`Inf` prices or latency) by raising typed `RiskConfigurationError` or `InvalidRiskInputError` inheriting from `RiskError`.
* **AC11:** **Close-Based Backtest Risk Overlay & Re-Entry Guard:** A close-based overlay (`RiskManager.apply_risk_overlay(ohlcv_df, raw_signals)`) must sequentially evaluate bar-by-bar `Close` prices: honoring warm-up zeros, tracking entry price and high-water mark, exiting (`signal[t] = 0`) on `StopMonitor` or `KillSwitch` triggers (for execution at $t+1$ via `VectorizedBacktestEngine`), and suppressing re-entry after any risk exit until the raw strategy transitions back to `0` and issues a fresh `0 -> 1` signal.
* **AC12:** **B3 Universe Risk Validation:** Integration tests must evaluate EMA 9/21 across `ITUB4.SA`, `PETR4.SA`, `VALE3.SA`, and `WEGE3.SA` (`2021-11-01` to `2024-11-01`, warm-up sliced, 0.03% B3 fee) comparing baseline EMA 9/21 vs risk-managed EMA 9/21 via `VectorizedBacktestEngine`, plus validating `PositionSizer` behavior with `R$ 100.00` nominal capital on those equities.

---

## 4. Edge Cases
* **Insufficient Cash for 1 Share:** On a R$ 100 account, if `entry_price = 105.00`, `PositionSizer` must safely return `shares = 0`, `approved = False`, never negative or fractional shares.
* **Risk Budget Smaller Than 1 Share's Stop Risk:** On R$ 100 with 2% risk budget (R$ 2.00) and a R$ 55.00 stock with 5% stop (R$ 2.75 risk/share), raw risk formula yields `0.72` shares (`floor = 0`). With default `allow_min_lot_override=False`, returns `shares=0`, `approved=False` with clear reason citing risk budget violation.
* **Entry Price <= Stop Price:** Invalid long stop configuration (`stop_price >= entry_price` or `stop_price <= 0`); must raise `InvalidRiskInputError`.
* **Zero / Negative / NaN Price or Latency:** Must fail closed (`InvalidRiskInputError` on pricing inputs; immediate `KillSwitch` halt or exception on corrupted latency/equity telemetry).
* **Exact Boundary Values:** Daily loss `>= 0.02` trips daily circuit breaker; cumulative drawdown `>= 0.10` trips drawdown circuit breaker; latency strictly `> 500.0` ms (`<= 500.0` ms passes) trips latency circuit breaker (matching `PROJETO.md`: *"latência subir além de 500ms"*).
* **Zero Trades / Flat Equity:** Drawdown and daily loss remain `0.0%`; Kill-Switch stays `ACTIVE`.
* **Same-Day Exit Attempt (`allow_day_trade=False`):** Voluntary exit on `entry_date == current_date` is rejected (`approved=False`), whereas an emergency exit (`is_emergency=True` from stop/kill-switch) on `entry_date == current_date` is approved (`approved=True`).

---

## 5. Contracts and Data Models

```python
class RiskStatus(str, Enum):
    ACTIVE = "ACTIVE"
    HALTED = "HALTED"


class HaltReason(str, Enum):
    NONE = "NONE"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    MAX_DRAWDOWN_LIMIT = "MAX_DRAWDOWN_LIMIT"
    LATENCY_LIMIT = "LATENCY_LIMIT"


@dataclass(frozen=True)
class RiskConfig:
    initial_capital: float = 100.0
    b3_fee_pct: float = 0.0003
    lot_size: int = 1  # 1 = B3 fractional ('F'), 100 = standard lot
    max_risk_per_trade_pct: float = 0.02  # 2% strict risk per trade
    max_position_pct: float = 1.0  # Max portfolio fraction allocated to 1 trade
    allow_min_lot_override: bool = False  # Strict risk gate by default
    stop_loss_pct: float = 0.05  # 5% fixed stop-loss
    trailing_stop_pct: float | None = 0.05  # 5% trailing stop active by default
    max_daily_loss_pct: float = 0.02  # 2% daily Kill-Switch (PROJETO.md)
    max_drawdown_pct: float = 0.10  # 10% total peak-to-trough Kill-Switch
    max_latency_ms: float = 500.0  # 500ms latency Kill-Switch (PROJETO.md)
    allow_day_trade: bool = False  # Enforces Swing Trade rule (PROJETO.md)


@dataclass(frozen=True)
class PositionSizeResult:
    shares: int
    notional_value: float
    estimated_fee: float
    risk_amount: float
    allocation_pct: float
    approved: bool
    reason: str


@dataclass(frozen=True)
class KillSwitchState:
    status: RiskStatus
    reason: HaltReason
    tripped_at_date: date | None
    daily_pnl_pct: float
    drawdown_pct: float
    last_latency_ms: float
    message: str


@dataclass(frozen=True)
class RiskVerdict:
    approved: bool
    action: Literal["BUY", "HOLD", "EXIT", "HALT"]
    shares: int
    weight: float  # Normalized [0.0, 1.0] for VectorizedBacktestEngine
    kill_switch_state: KillSwitchState
    reason: str
```

---

## 6. Abuse and Security Risks
* **Bypassing Kill-Switch (Fail-Open Bug):** If exceptions or `NaN` values silently pass validation, the bot could keep trading during an API outage or flash crash. Mitigated by fail-closed defaults: malformed telemetry (`NaN`/`Inf` equity or negative latency) rejects trades or raises explicit errors.
* **Integer/Float Rounding Bypass:** Using `round()` instead of `math.floor()` when sizing shares could exceed available R$ 100 capital and trigger margin borrowing / broker rejection. Mitigated by strict `math.floor` with B3 fee buffer included.
* **Look-Ahead Bias in Risk Overlay:** Evaluating intraday `Low`/`High` on `1d` bars or executing stop exits retroactively on bar $t$ leaks future price knowledge. Mitigated by close-based evaluation on bar $t$ feeding $\{0, 1\}$ signals into `VectorizedBacktestEngine` (`.shift(1)` -> bar $t+1$ execution).
* **No Process Exit Side Effects in Library:** `src/risk/` will never call `sys.exit()` directly; Phase 5 handles OS termination upon receiving `RiskStatus.HALTED`.

---

## 7. Open Questions
* *None. All open questions were resolved by explicit user decisions on 2026-11-11.*

---

## 8. Assumptions Made & Architecture Decisions Log
1. **Decision on R$ 100 Position Sizing:** Strict 2% risk-per-trade gate (`max_risk_per_trade_pct=0.02`, `allow_min_lot_override=False`) rejects orders (`shares=0`, `approved=False`) when 1 integer share exceeds the 2% risk budget; override flag remains configurable.
2. **Decision on Stop-Loss Execution Model:** Close-based risk signal overlay evaluates Stop-Loss and Trailing Stop at daily `Close` of bar $t$, forcing `signal[t] = 0` and feeding `VectorizedBacktestEngine` (`t+1` execution) without modifying Phase 2.
3. **Decision on Default Risk Parameters:** Fixed `stop_loss_pct=0.05` (5%), `trailing_stop_pct=0.05` (5% active by default), and `max_drawdown_pct=0.10` (10% peak-to-trough circuit breaker).
4. **Decision on Swing Trade Custody Guard:** `allow_day_trade=False` blocks voluntary strategy exits on entry calendar date $D_0$, while explicitly permitting emergency exits from Stop-Loss, Trailing Stop, or Kill-Switch.
5. **Decision on Kill-Switch Reset Policy:** `DAILY_LOSS_LIMIT` auto-resets when a strictly newer trading calendar date is observed; `LATENCY_LIMIT` and `MAX_DRAWDOWN_LIMIT` persist across dates until explicit manual `reset(confirm=True)`.
6. **Decision on `sys.exit(1)` Boundary:** `src/risk/` remains a pure/testable Python module returning `RiskStatus.HALTED` / raising typed exceptions; OS process exit and broker order cancellation belong to Phase 5 (`src/execution/`).

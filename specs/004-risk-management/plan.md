# Architecture Plan: Risk Management and Operational Kill-Switch (`004-risk-management`)

**Status:** approved  
**Date:** 2026-11-11  

---

## 1. Architectural Decisions

* **Decoupled Pipeline Gate (`RiskManager`):** Following `PROJETO.md` Section 3, `src/risk/` acts as an independent verification layer between `src/strategies/` (raw bias) and `src/backtest/` or `src/execution/` (order execution). It never invokes network requests or `sys.exit()` directly.
* **Compositional Components:** Split responsibilities into small, single-purpose units:
  1. `exceptions.py`: Typed hierarchy (`RiskError`, `RiskConfigurationError`, `InvalidRiskInputError`, `KillSwitchTriggeredError`).
  2. `models.py`: Immutable frozen dataclasses (`RiskConfig`, `PositionSizeResult`, `RiskVerdict`, `KillSwitchState`, `RiskStatus`, `HaltReason`).
  3. `sizing.py`: `PositionSizer` handling B3 fractional lot rounding (`math.floor`), B3 fee buffer (`0.03%`), cash guard, and strict 2% risk-per-trade sizing (`allow_min_lot_override=False` default).
  4. `stops.py`: `StopMonitor` tracking entry price, peak high-water mark, 5% fixed stop-loss, and 5% trailing stop thresholds.
  5. `kill_switch.py`: `KillSwitch` tracking daily PnL % (`>= 2%` auto-resetting on new date), cumulative peak drawdown % (`>= 10%` requiring manual reset), and telemetry latency (`> 500ms` requiring manual reset).
  6. `manager.py`: `RiskManager` unifying pre-trade validation (Kill-Switch + Swing Trade day guard allowing emergency exits + StopMonitor + PositionSizer) and providing a close-based daily risk overlay (`apply_risk_overlay`) compatible with Phase 2/3 (`VectorizedBacktestEngine`).
* **Close-Based Daily Overlay (`Close -> t+1`):** Historical backtests evaluate stop/drawdown conditions sequentially on bar $t$ `Close` prices, overriding `signal[t] = 0` and suppressing re-entry until a fresh raw `0 -> 1` crossover, preserving 100% compatibility with `VectorizedBacktestEngine` and eliminating intraday look-ahead assumptions.
* **Strict Fail-Closed Validation:** Any `NaN`, `Inf`, negative price, or corrupted equity telemetry triggers an explicit typed exception or immediate `HALTED` verdict rather than passing silently.

---

## 2. Alternatives Discarded

* **Embedding Risk Logic inside `BaseStrategy`:** Rejected because mixing entry alpha logic with capital allocation violates separation of concerns (`PROJETO.md` Section 3) and prevents testing strategies independently of risk rules.
* **Embedding `sys.exit(1)` inside `KillSwitch`:** Rejected because terminating the Python interpreter inside a domain library prevents unit testing, dashboard rendering (Phase 6), and graceful broker order cancellation (Phase 5).
* **Intraday Bar-by-Bar `Low` Stop Simulator:** Rejected to keep Phase 2 `VectorizedBacktestEngine` unmodified and avoid arbitrary assumptions about whether daily `High` occurred before or after daily `Low`.
* **Minimum 1-Share Override by Default on R$ 100:** Rejected as default behavior because risking R$ 2.75+ on a R$ 55+ share violates the strict 2% capital-preservation budget (kept available via explicit `allow_min_lot_override=True`).

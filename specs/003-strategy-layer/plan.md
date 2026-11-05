# Architecture Plan: Strategy Layer and EMA Crossover (`003-strategy-layer`)

**Status:** draft  

---

## 1. Architectural Decisions
* **Pure Functional Strategy Interface:** Strategies are modeled as pure functions encapsulated in classes (`generate_signals(df) -> Series`). They maintain no mutable internal state across calls, enabling thread-safe parallel simulations and deterministic testability.
* **Separation of Signal from Execution:** Strategies are decoupled from order management, position sizing, execution lag, and transaction costs. The strategy computes *ideal market bias* (`{0, 1}`), while the backtest engine enforces real-world execution rules ($t+1$ execution, fees).
* **Warm-Up Slicing Strategy:** To prevent benchmark drift distortion during indicator calculation, `min_periods=slow_period` is used in exponential moving average smoothing, and the backtesting evaluation period is sliced from the first bar where both indicators are established.
* **Comparative Friction Reporting:** The runner/report will compute performance both with B3 fees (0.03%) and without fees (gross) to reveal the explicit impact of portfolio turnover.

---

## 2. Alternatives Discarded
* **Event-Driven Strategy with State Callbacks (`on_bar` / `on_tick`):** Discarded at this phase to prioritize clean vectorized backtesting and avoid premature optimization before the execution layer is built.
* **Dynamic Slippage Estimator:** Discarded as out of scope; daily closing prices on large-cap B3 equities have tight fracionário spreads compared to the 0.03% B3 exchange fee.
* **Per-Ticker Parameter Tuning:** Discarded to avoid statistical overfitting (p-hacking).

# Architecture Plan: Strategy Layer and EMA Crossover (`003-strategy-layer`)

**Status:** draft  

---

## 1. Architectural Decisions
* **Pure Functional Strategy Interface:** Strategies are modeled as pure functions encapsulated in classes (`generate_signals(df) -> Series`). They maintain no mutable internal state across calls, enabling thread-safe parallel simulations and deterministic testability.
* **Separation of Signal from Execution:** Strategies are decoupled from order management, position sizing, execution lag, and transaction costs. The strategy computes *ideal market bias* (`{0, 1}`), while the backtest engine enforces real-world execution rules ($t+1$ execution, fees, slippage).
* **Package Structure:** Strategies live in `src/strategies/`, following domain isolation rules.

---

## 2. Alternatives Discarded
* **Event-Driven Strategy with State Callbacks (`on_bar` / `on_tick`):** Discarded at this phase to prioritize clean vectorized backtesting and avoid premature optimization before the execution layer is built.
* **Embedding Risk/Stop-Loss inside Strategy:** Discarded; risk controls belong in `src/risk/` to maintain the Single Responsibility Principle.

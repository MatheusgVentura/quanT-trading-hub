# Tasks: Vectorized Backtest Engine (`002-vectorized-backtest`)

**Status:** retroactive (pre-SDD)  

---

- [x] **Task 2.1:** Define backtest domain models (`BacktestConfig`, `BacktestMetrics`, `BacktestResult`) with `summary()` reporting. *(Mapped to: AC07, AC10)*
- [x] **Task 2.2:** Define backtest exceptions (`BacktestError`, `MismatchedIndexError`, `InvalidSignalError`). *(Mapped to: AC08, AC09)*
- [x] **Task 2.3:** Implement `MetricsCalculator` with CAGR, Sharpe, Sortino, Drawdown, Profit Factor, and Win Rate. *(Mapped to: AC06, AC07)*
- [x] **Task 2.4:** Implement `VectorizedBacktestEngine` with `.shift(1)` look-ahead bias protection and B3 transaction cost modeling. *(Mapped to: AC01, AC02, AC03, AC04, AC05)*
- [x] **Task 2.5:** Implement unit tests in `tests/unit/test_backtest/` covering bias prevention, fee deduction, cash strategy, and mathematical edge cases. *(Mapped to: AC01-AC10)*

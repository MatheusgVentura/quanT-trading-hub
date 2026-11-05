# Architecture Plan: Vectorized Backtest Engine (`002-vectorized-backtest`)

**Status:** retroactive (pre-SDD)  

---

## 1. Architectural Decisions
* **Vectorized Execution:** Adopted array-based vectorized calculation via pandas/NumPy for rapid iteration across multi-year histories rather than bar-by-bar looping.
* **Separation of Metrics from Engine:** Built `MetricsCalculator` as a pure static calculation service separate from `VectorizedBacktestEngine` to enable independent testing and reuse in other execution engines.
* **Immutable Result Contracts:** Encapsulated configuration and metrics into frozen dataclasses (`BacktestConfig`, `BacktestMetrics`) to protect simulation state against mutation.

---

## 2. Alternatives Discarded
* **External Framework Dependency (Backtrader / VectorBT):** Discarded to keep the hub lightweight, dependency-free, and fully tailored to specific B3 friction rules and look-ahead bias protections.

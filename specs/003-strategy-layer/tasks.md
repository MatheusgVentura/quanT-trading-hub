# Tasks: Strategy Layer and EMA Crossover (`003-strategy-layer`)

**Status:** draft  

---

- [x] **Task 3.1:** Define strategy exceptions (`StrategyError`, `InvalidParameterError`, `InsufficientDataError`) in `src/strategies/exceptions.py`. *(Mapped to: AC08, AC09, AC12)*
- [ ] **Task 3.2:** Define abstract base strategy contract `BaseStrategy` in `src/strategies/base.py`. *(Mapped to: AC06, AC07)*
- [ ] **Task 3.3:** Implement `EMACrossoverStrategy` with parameter validation ($fast \ge 2, slow > fast$), `min_periods=slow_period` EMA calculations, and `{0, 1}` signals in `src/strategies/ema_crossover.py`. *(Mapped to: AC01, AC02, AC08, AC09, AC10, AC11, AC12)*
- [ ] **Task 3.4:** Implement unit test suite in `tests/unit/test_strategies/test_ema_crossover.py` verifying criteria AC01-AC12 and edge cases (constant prices, short series, warm-up NaNs). *(Mapped to: AC01-AC12)*
- [ ] **Task 3.5:** Implement backtest runner/integration tests validating the 4 B3 assets (`ITUB4.SA`, `PETR4.SA`, `VALE3.SA`, `WEGE3.SA`) over the 3-year fixed window with warm-up slicing and dual fee reporting (net vs gross). *(Mapped to: AC03, AC04, AC05, AC13)*
- [ ] **Task 3.6:** Validate task completion with `ruff check .`, `ruff format --check .`, `mypy --strict src tests`, and `pytest --cov=src -v`.

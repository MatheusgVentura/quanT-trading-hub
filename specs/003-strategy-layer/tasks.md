# Tasks: Strategy Layer and EMA Crossover (`003-strategy-layer`)

**Status:** draft  

---

- [ ] **Task 3.1:** Define strategy exceptions (`StrategyError`, `InvalidParameterError`) in `src/strategies/exceptions.py`. *(Mapped to: AC04, AC09)*
- [ ] **Task 3.2:** Define abstract base strategy contract `BaseStrategy` in `src/strategies/base.py`. *(Mapped to: AC01, AC02)*
- [ ] **Task 3.3:** Implement `EMACrossoverStrategy` with parameter validation, fast/slow EMA calculation, and binary signal generation in `src/strategies/ema_crossover.py`. *(Mapped to: AC03, AC04, AC05, AC06, AC07, AC08)*
- [ ] **Task 3.4:** Implement unit test suite in `tests/unit/test_strategies/test_ema_crossover.py` verifying criteria AC01-AC09 and edge cases (constant prices, short series, warm-up NaNs). *(Mapped to: AC01-AC09)*
- [ ] **Task 3.5:** Validate task completion with `ruff check .`, `ruff format --check .`, `mypy --strict src tests`, and `pytest --cov=src -v`.

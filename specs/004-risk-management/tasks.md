# Tasks: Risk Management and Operational Kill-Switch (`004-risk-management`)

**Status:** approved  

---

- [x] **Task 4.1:** Define typed exception hierarchy (`RiskError`, `RiskConfigurationError`, `InvalidRiskInputError`, `KillSwitchTriggeredError`) in `src/risk/exceptions.py` with unit tests. *(Mapped to: AC09, AC10)*
- [x] **Task 4.2:** Implement validated configuration and verdict models (`RiskStatus`, `RiskConfig`, `PositionSizeResult`, `RiskVerdict`, `KillSwitchState`) in `src/risk/models.py` with boundary validation tests. *(Mapped to: AC01, AC02, AC03, AC10)*
- [ ] **Task 4.3:** Implement `PositionSizer` in `src/risk/sizing.py` supporting B3 fractional/standard lot rounding, B3 0.03% fee buffer, cash guard, and fixed-fractional risk sizing rules with unit tests. *(Mapped to: AC03, AC05, AC10)*
- [ ] **Task 4.4:** Implement `StopMonitor` in `src/risk/stops.py` supporting fixed stop-loss and trailing stop high-water mark tracking with unit tests. *(Mapped to: AC07, AC08, AC10)*
- [ ] **Task 4.5:** Implement `KillSwitch` in `src/risk/kill_switch.py` enforcing daily loss limit (`>= 2%`), latency threshold (`> 500ms`), max drawdown circuit breaker, and reset policies with unit tests. *(Mapped to: AC01, AC02, AC06, AC09, AC10)*
- [ ] **Task 4.6:** Implement `RiskManager` and backtest risk overlay in `src/risk/manager.py` (integrating Swing Trade guard, StopMonitor, KillSwitch, PositionSizer, and re-entry suppression) and export public API in `src/risk/__init__.py`. *(Mapped to: AC04, AC09, AC11)*
- [ ] **Task 4.7:** Implement integration tests in `tests/integration/test_b3_risk_backtest.py` comparing unconstrained EMA 9/21 vs risk-managed EMA 9/21 across the 4 B3 equities (`ITUB4.SA`, `PETR4.SA`, `VALE3.SA`, `WEGE3.SA`) over `2021-11-01` to `2024-11-01`. *(Mapped to: AC12)*
- [ ] **Task 4.8:** Final quality gate verification (`ruff check .`, `ruff format --check .`, `mypy --strict src tests`, `pytest --cov=src -v`) and update `PROGRESS.md`.


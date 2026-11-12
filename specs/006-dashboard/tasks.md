# Tasks: Interactive Quantitative Web Dashboard (`006-dashboard`)

**Status:** approved  

---

- [x] **Task 6.1:** Add `streamlit` and `plotly` dependencies to `requirements.txt` (and configure `mypy.ini` missing-import overrides only if required for untyped third-party stubs) and install in `venv`. *(Mapped to: AC12)*
- [ ] **Task 6.2:** Implement typed dashboard exceptions (`DashboardError`, `DashboardConfigurationError`, `DashboardDataError`, `LedgerLoadError`) in `src/dashboard/exceptions.py` and validated contracts (`PresetAsset`, `B3_PRESET_ASSETS`, `DashboardParameters`, `RiskTelemetrySnapshot`, `LoadedLedgerSummary`, `DashboardSnapshot`) in `src/dashboard/models.py` with comprehensive unit tests. *(Mapped to: AC01, AC04, AC09)*
- [ ] **Task 6.3:** Implement the intentional visual design system (`frontend-design` CSS tokens, typography, accessible reduced-motion rules, XSS-safe HTML card builders, and `apply_plotly_theme`) in `src/dashboard/theme.py` with unit tests verifying palette tokens, theme styling, and HTML escaping. *(Mapped to: AC03, AC09)*
- [ ] **Task 6.4:** Implement `DashboardService` in `src/dashboard/service.py` unifying `IDataProvider`, `StrategyBacktestRunner`, `RiskManager`, and `PaperTradingRunner`, plus safe bounded Phase 5 Ledger JSON parsing/loading (`parse_ledger_payload`, `load_ledger_json`) with mocked unit tests. *(Mapped to: AC02, AC04, AC08, AC09, AC11)*
- [ ] **Task 6.5:** Implement pure Plotly figure builders (`build_price_ema_figure`, `build_equity_comparison_figure`, `build_drawdown_figure`, `build_capital_allocation_figure`) in `src/dashboard/charts.py` with unit tests verifying traces, Kill-Switch threshold lines, fractional capital splits, and trade markers. *(Mapped to: AC05, AC06, AC07, AC11)*
- [ ] **Task 6.6:** Implement thin Streamlit UI components in `src/dashboard/components.py`, main entrypoint `src/dashboard/app.py`, and public package exports in `src/dashboard/__init__.py`, with headless Streamlit `AppTest` unit tests covering error alerts, telemetry strip, ledger upload, and downloads. *(Mapped to: AC03, AC04, AC08, AC09, AC10, AC11)*
- [ ] **Task 6.7:** Implement end-to-end integration tests in `tests/integration/test_dashboard_pipeline.py` verifying full pipeline execution (`Data -> Strategy -> Risk -> Paper Execution -> Charts & Telemetry`) and Phase 5 JSON ledger round-trip loading without network calls. *(Mapped to: AC02, AC05, AC06, AC07, AC08, AC11)*
- [ ] **Task 6.8:** Update `README.md` run instructions & Phase 6 checkbox, run final quality gates (`ruff check .`, `ruff format --check .`, `mypy --strict src tests`, `pytest --cov=src -v`), and update `PROGRESS.md`. *(Mapped to: AC12)*


# Specification: Interactive Quantitative Web Dashboard (`006-dashboard`)

**Status:** approved  
**Date:** 2026-11-11  
**Domain Area:** `src/dashboard/`  

---

## 1. Objective
Deliver a professional, intuitive, and decoupled **Interactive Quantitative Web Dashboard** (`src/dashboard/`) built with **Streamlit** and **Plotly**, uniting Phases 1 through 5 (`src/data/`, `src/backtest/`, `src/strategies/`, `src/risk/`, `src/execution/`) into a cohesive **B3 Quantitative Research & Paper Trading Desk**:
1. **Intentional Industrial/Utilitarian Visual System (`frontend-design`):** Adopt a high-contrast dark trading-desk aesthetic (*"B3 Sovereign Tape / Quantitative Obsidian Terminal"*) using explicit CSS variables, non-generic typography (`Space Grotesk`, `IBM Plex Sans`, and `JetBrains Mono` with `tabular-nums`), a persistent top **Risk & Kill-Switch Telemetry Strip**, and asymmetric Bento KPI hierarchy—eliminating generic SaaS card templates and low-contrast defaults.
2. **Intuitive 3-Workspace Information Architecture:**
   * **Workspace 1 — Strategy & Backtest Lab:** Interactive OHLCV candlestick chart overlaid with Fast/Slow EMAs and trade markers, Net (B3 0.03% fee) vs. Gross (0% fee) vs. Risk-Overlay vs. Buy & Hold equity comparison, underwater drawdown curve with the `-10%` Kill-Switch threshold, and plain-language quantitative KPI explanations.
   * **Workspace 2 — Paper Desk (`R$ 100.00` B3 Fractional Simulator):** End-to-end execution of `PaperTradingRunner` (`SimulatedPaperBroker`) showing real-world integer fractional lot constraints (`ITUB4F`, `PETR4F`, etc.), residual cash vs. invested custody timeline, realized PnL, B3 fees paid, and receipt history.
   * **Workspace 3 — Risk Telemetry & Ledger Audit:** Detailed `KillSwitch` telemetry (daily PnL vs. `-2%` limit, drawdown vs. `-10%` limit, latency vs. `500ms`, Swing Trade $D_0$ protection), step-by-step audit table, JSON ledger inspection (from Phase 5 `PaperTradingRunner.save_ledger()`), and clean CSV/JSON export.
3. **Clean Model-View-Service Separation:** Isolate input sanitization, market loading, pipeline execution, ledger parsing, and Plotly figure construction (`models.py`, `service.py`, `charts.py`, `theme.py`) from the thin Streamlit UI entrypoint (`app.py`), guaranteeing strict static typing (`mypy --strict`) and full headless unit/integration testability without requiring a browser or live network calls.

---

## 2. Out of Scope
* **Live Real-Money Brokerage Order Routing or Credential Input:** The browser UI must never accept, store, or transmit real-money broker API keys, XP credentials, or trigger live DMA orders.
* **Persistent Multi-User Authentication / Cloud Database:** Single-operator local workbench session state (`st.session_state`); no user accounts, SQL persistence, or multi-tenant RBAC.
* **Custom Strategy Code Editor / Arbitrary `eval` Execution:** Users configure validated parameters (`EMACrossoverStrategy` fast/slow windows, risk & execution settings), never executing arbitrary uploaded Python code.
* **Sub-Minute Live WebSocket Streaming Daemon:** Operates on daily (`1d`) or cached historical OHLCV bars and deterministic step simulations/ledger snapshots rather than opening background WebSocket daemons.

---

## 3. Acceptance Criteria

### Criteria Derived from `PROJETO.md`, Functional UX & `frontend-design`
* **AC01:** **Curated & Validated Parameter Controls (`DashboardParameters`):** All user controls (B3 ticker symbol, date range / period, EMA fast/slow periods, initial capital defaulting to `R$ 100.00`, B3 fee `0.03%`, slippage, risk limits, Swing Trade flag) must pass strict fail-closed domain validation in `DashboardParameters` before calling `src/data/`, `src/strategies/`, `src/risk/`, or `src/execution/`. Invalid tickers, inverted dates, `fast_period >= slow_period`, or non-positive/NaN numeric inputs must raise `DashboardConfigurationError`.
* **AC02:** **Unified Pipeline Execution (`DashboardService.run_analysis`):** Given valid `DashboardParameters` and an injectable `IDataProvider` (defaulting to `YFinanceDataProvider(DataCacheManager())`), `DashboardService` must deterministically execute:
  1. Market OHLCV fetch + indicator enrichment (`EMA_Fast`, `EMA_Slow`, `Signal`);
  2. Net vs. Gross comparative backtest (`StrategyBacktestRunner.run`);
  3. Risk-overlaid backtest (`RiskManager.apply_risk_overlay` + `VectorizedBacktestEngine`);
  4. Integer fractional B3 paper simulation (`PaperTradingRunner.run_simulation` + `SimulatedPaperBroker`), returning an immutable `DashboardSnapshot`.
* **AC03:** **Intentional Visual Identity & CSS Design System (`theme.py`):** `src/dashboard/theme.py` must define a centralized CSS variable palette (`--bg-void: #080B0F`, `--bg-deck: #0F141B`, `--bg-panel: #161E29`, `--accent-alpha: #00D4AA`, `--accent-warn: #F5A623`, `--accent-halt: #FF4D5A`, `--accent-bench: #6B8CAE`, `--text-primary: #EDF2F7`, `--text-muted: #8B98A8`), expressive typography (`Space Grotesk`, `IBM Plex Sans`, `JetBrains Mono` with `tabular-nums`, avoiding Inter/Roboto/Arial), accessible `prefers-reduced-motion` handling, and a reusable `apply_plotly_theme(figure)` helper applied consistently across every chart.
* **AC04:** **Signature Risk & Kill-Switch Telemetry Strip:** Every rendered view must compute and surface a `RiskTelemetrySnapshot` capturing active execution symbol (e.g., `ITUB4F`), `KillSwitch` status (`ACTIVE` vs. `HALTED`), halt reason (`NONE`, `DAILY_LOSS_LIMIT`, `MAX_DRAWDOWN_LIMIT`, `LATENCY_LIMIT`), daily PnL vs. `-2.0%` threshold, drawdown vs. `-10.0%` threshold, observed latency vs. `500ms` ceiling, and Swing Trade mode (`D0 Block: ON/OFF`).
* **AC05:** **Interactive Price, EMA & Trade Signal Chart (`build_price_ema_figure`):** Must generate a Plotly `Figure` containing OHLC candlesticks (or Close line fallback if only Close is present), Fast EMA and Slow EMA curves, and explicit execution/transition markers (`BUY`, `EXIT`, `HALT`) aligned strictly with simulation timestamps.
* **AC06:** **Interactive Multi-Curve Equity & Drawdown Charts (`build_equity_comparison_figure`, `build_drawdown_figure`):** Must plot Strategy Net vs. Strategy Gross vs. Risk-Overlaid Strategy vs. Buy & Hold curves (normalized or in BRL), plus an underwater Drawdown (%) area chart clearly marking the `-10.0%` Kill-Switch circuit-breaker threshold line.
* **AC07:** **R$ 100.00 Capital Allocation & Integer Custody Chart (`build_capital_allocation_figure`):** For the Paper Desk view, must visualize the daily split between **Residual Cash (R$)** and **Invested Custody Value (R$)** alongside total equity and integer share holdings, demonstrating why low-capital B3 accounts retain residual cash when buying whole fractional shares (`ITUB4F`, etc.).

### Criteria Derived from Security, Persistence & Engineering Standards
* **AC08:** **Safe Phase 5 Ledger JSON Ingestion (`load_ledger_json` / `parse_ledger_payload`):** Must load and validate JSON ledgers produced by `PaperTradingRunner.save_ledger()` (`schema_version == 1`), validating file size bounds (rejecting payloads `> 10 MB`), JSON structure, finite numeric fields, valid timestamps, and required keys (`equity_curve`, `receipts`, `final_account`), raising `LedgerLoadError` on malformed, corrupted, or tampered inputs.
* **AC09:** **XSS-Safe Rendering & Input Sanitization:** All user-supplied or file-loaded strings (tickers, filenames, halt messages, order messages) must be validated by allowlist/regex (`^[A-Z0-9^._=-]{1,20}$` for tickers) and HTML-escaped (`html.escape`) before interpolation into any `st.markdown(..., unsafe_allow_html=True)` layout blocks. No secrets or `.env` variables may ever be displayed or serialized in the dashboard.
* **AC10:** **Headless Streamlit UI & Responsive Intuitive Controls (`app.py`):** `src/dashboard/app.py` (with `run_dashboard()` / testable helper layout) must render cleanly under headless Streamlit testing (`streamlit.testing.v1.AppTest`), handle domain/network failures (`DataError`, `DashboardError`, `ExecutionError`) via clear non-crashing user alerts instead of raw tracebacks, include concise plain-language explanations for non-quantitative readers, and provide clean CSV/JSON download buttons for trades and curves.
* **AC11:** **Zero-Network Deterministic Tests:** Unit tests (`tests/unit/test_dashboard/`) and integration tests (`tests/integration/test_dashboard_pipeline.py`) must mock market downloads cleanly and achieve `>= 85%` coverage across `src/dashboard/` with explicit `test_acXX_*` traceability.
* **AC12:** **Quality Gate Compliance:** All Phase 6 modules, dependencies, and tests must pass `ruff check .`, `ruff format --check .`, `mypy --strict src tests`, and `pytest --cov=src -v`.

---

## 4. Edge Cases
* **Short Historical Window (`len < slow_period`):** Selecting a date range shorter than `slow_period` triggers `InsufficientDataError` from `EMACrossoverStrategy`; the service/UI must translate this into a clear actionable prompt asking for a wider date window without crashing.
* **R$ 100.00 Insufficient for 1 Share (e.g., High-Priced Stock `VALE3F` > R$ 100 or 2% Strict Risk Sizing):** When `PositionSizer` rejects entries due to insufficient capital or strict 2% risk bounds (`filled_orders == 0`), the Paper Desk must clearly explain why zero orders fired (flat curve, `R$ 100.00` cash preserved) instead of rendering empty/broken Plotly charts.
* **Kill-Switch Halted Run:** When simulated drawdown reaches `-10%` or simulated latency exceeds `500ms`, the Telemetry Strip switches to `HALTED` with carmine emphasis, and chart markers distinguish `HALT` liquidations from voluntary `EXIT`s.
* **Corrupted / Oversized Uploaded Ledger JSON:** Uploading malformed JSON, wrong `schema_version`, `NaN` values inside `equity_curve`, or payloads `> 10 MB` raises `LedgerLoadError` and surfaces a crisp error banner while keeping existing dashboard state intact.
* **Offline / Yahoo Finance Failure:** When `YFinanceDataProvider` raises `DataDownloadError` or `TickerNotFoundError`, the UI preserves inputs, shows an informative retry alert, and continues allowing Phase 5 JSON ledger inspection.
* **NaN / Missing Optional Columns in Uploaded Ledger:** Optional fields or empty `receipts`/`open_orders` lists render gracefully as empty-state notices ("Nenhuma ordem executada no período") rather than throwing `KeyError`.

---

## 5. Contracts and Data Models

```python
@dataclass(frozen=True)
class PresetAsset:
    ticker: str
    label: str
    sector: str
    default_fractional: str


@dataclass(frozen=True)
class DashboardParameters:
    ticker: str = "ITUB4.SA"
    start_date: date | None = None
    end_date: date | None = None
    period: str | None = "3y"
    fast_period: int = 9
    slow_period: int = 21
    initial_capital: float = 100.0
    b3_fee_pct: float = 0.0003
    slippage_pct: float = 0.0
    max_risk_per_trade_pct: float = 0.02
    allow_min_lot_override: bool = False
    stop_loss_pct: float = 0.05
    trailing_stop_pct: float | None = 0.05
    max_daily_loss_pct: float = 0.02
    max_drawdown_pct: float = 0.10
    max_latency_ms: float = 500.0
    allow_day_trade: bool = False
    simulated_latency_ms: float = 45.0
    use_cache: bool = True


@dataclass(frozen=True)
class RiskTelemetrySnapshot:
    ticker: str
    execution_symbol: str
    kill_switch_status: RiskStatus
    halt_reason: HaltReason
    daily_pnl_pct: float
    max_daily_loss_limit_pct: float
    current_drawdown_pct: float
    max_drawdown_limit_pct: float
    observed_latency_ms: float
    max_latency_limit_ms: float
    allow_day_trade: bool
    open_shares: int
    cash_balance: float
    total_equity: float
    last_updated: datetime


@dataclass(frozen=True)
class LoadedLedgerSummary:
    source_name: str
    schema_version: int
    ticker: str
    initial_cash: float
    final_cash: float
    final_equity: float
    total_return_pct: float
    benchmark_return_pct: float
    max_drawdown_pct: float
    realized_pnl: float
    total_fees_paid: float
    total_orders: int
    filled_orders: int
    trading_days: int
    halted: bool
    halt_count: int
    equity_curve: pd.DataFrame
    receipts: pd.DataFrame
    open_orders: pd.DataFrame
    positions: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class DashboardSnapshot:
    parameters: DashboardParameters
    ohlcv_with_indicators: pd.DataFrame
    net_backtest: BacktestResult
    comparison_report: StrategyComparisonReport
    risk_adjusted_backtest: BacktestResult
    paper_report: PaperSimulationReport
    telemetry: RiskTelemetrySnapshot
    trade_markers: pd.DataFrame
```

---

## 6. Abuse and Security Risks
* **HTML/Script Injection (XSS) via `unsafe_allow_html=True`:** Streamlit allows HTML blocks for custom CSS styling (`theme.py` / `components.py`). If unescaped ticker strings, uploaded filenames, or error messages are interpolated into HTML strings, malicious JS could execute in the operator's browser. **Mitigation:** Validate tickers with a strict allowlist regex, enforce `max_upload_bytes` (`10 MB`) on uploaded files, and wrap all dynamic text passed to HTML templates in `html.escape(..., quote=True)`.
* **Denial of Service via Giant Ledger Uploads or Extreme Parameters:** Extremely large JSON uploads or unrealistic EMA windows (`slow_period = 1_000_000`) could exhaust memory or freeze the UI thread. **Mitigation:** Enforce strict numeric upper/lower bounds (`fast_period >= 2`, `slow_period <= 252`, `initial_capital <= 10_000_000.0`) in `DashboardParameters` and hard byte limits (`10 MB`) before JSON decoding.
* **Path Traversal on Local File Inspection:** Reading arbitrary filesystem paths supplied via UI text input could expose local machine files (e.g., `.env`). **Mitigation:** For browser uploads, read strictly from uploaded in-memory bytes (`st.file_uploader`), and if selecting local ledger artifacts from disk, constrain lookups strictly inside an approved artifacts directory (`resolve().is_relative_to(allowed_dir)`), explicitly refusing dotfiles like `.env`.
* **Accidental Live Broker Execution or Secret Exposure:** Displaying environment variables (`ALPACA_API_KEY`, `ALPACA_SECRET_KEY`) or adding unguarded live order buttons inside the web app creates financial risk. **Mitigation:** Web UI runs read-only/paper simulation (`SimulatedPaperBroker`) only and never accesses or displays `.env` broker secrets.

---

## 7. Open Questions
* *None. All open questions were resolved by explicit user approval on 2026-11-11 (Português (BR) UI labels, `streamlit`/`plotly` dependencies approved, Obsidian Terminal dark theme confirmed, Read-Only + SimulatedPaperBroker safety boundary confirmed).*

---

## 8. Assumptions Made (Pending Explicit User Approval)
1. **Default UI Language = Português (BR) for user-facing labels/copy**, while strictly maintaining all Python symbols, docstrings, comments, tests, commits, and `specs/` files in English per `AGENTS.md`.
2. **Dependencies:** Adding `streamlit>=1.38.0` and `plotly>=5.22.0` to `requirements.txt` is expected since Phase 6 explicitly specifies `(Streamlit / Plotly)`.
3. **Read-Only + Paper Simulation Safety Boundary:** `SimulatedPaperBroker` (using cached/fetched market data) and Phase 5 JSON ledger files provide full empirical fidelity for R$ 100.00 B3 experimentation without exposing credentials in a web process.
4. **Pure-Python Testability First:** Every data loader, validator, service orchestrator, Plotly builder, and ledger parser will run cleanly under `pytest` and `mypy --strict` without spawning an external web server; `app.py` will also be verified via Streamlit's headless `AppTest` harness.


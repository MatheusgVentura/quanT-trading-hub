# Architecture Plan: Interactive Quantitative Web Dashboard (`006-dashboard`)

**Status:** approved  
**Date:** 2026-11-11  

---

## 1. Design Direction & DFII Evaluation (`frontend-design`)

### Purpose & Differentiation Anchor
* **Purpose:** Enable an individual B3 quantitative operator starting with `R$ 100.00` (XP RLP + Fractional `'F'` + Swing Trade) to inspect market behavior, compare strategy returns with vs. without B3 friction and risk overlays, simulate integer fractional paper trading, and audit circuit-breaker telemetry within 3 seconds of opening the interface.
* **Aesthetic Direction:** **Industrial / Utilitarian + Editorial Terminal** (*"B3 Sovereign Tape / Quantitative Obsidian Terminal"*).
* **Differentiation Anchor:** If screenshotted without any logo, the dashboard is immediately identifiable by:
  1. The **Risk & Kill-Switch Telemetry Strip** pinned at the top of the canvas displaying the fractional `'F'` ticker pill, `Kill-Switch` circuit status (`ACTIVE` / `HALTED`), live distance to the `-2.0%` daily loss and `-10.0%` drawdown thresholds, latency vs. `500ms`, and `Swing Trade D0` guard status.
  2. The **Asymmetric Bento KPI Hero** contrasting the primary Strategy/Equity metric block against secondary B3 Friction (`0.03%`), Integer Lot Utilization (`Shares` vs. `Residual Cash`), and Sharpe/Profit Factor cells in `JetBrains Mono` (`tabular-nums`).

### DFII Score (`-5` to `+15`, Target `>= 8`)
* **Aesthetic Impact:** `5/5` (Custom CSS obsidian terminal tokens, tabular financial monospace, sharp hairline borders, unified Plotly dark styling).
* **Context Fit:** `5/5` (Purpose-built for B3 quantitative trading, risk telemetry, and small-capital R$ 100.00 inspection).
* **Implementation Feasibility:** `4/5` (Achievable cleanly via Streamlit custom CSS injection + Plotly `graph_objects`, respecting Streamlit widget boundaries).
* **Performance Safety:** `5/5` (Zero heavy frontend JS bundles, respects `prefers-reduced-motion`, high WCAG contrast `#EDF2F7` on `#080B0F` / `#0F141B`).
* **Consistency Risk:** `1/5` (Centralized CSS variables and `apply_plotly_theme()` enforce uniform styling across all 3 tabs).
* **Total DFII:** `(5 + 5 + 4 + 5) - 1 = 18` → capped scale **`14 / 15` (Excellent — Execute Fully)**.

### Design System Snapshot
* **Palette (CSS Variables exclusively):**
  * `--bg-void: #080B0F` (Primary canvas)
  * `--bg-deck: #0F141B` (Elevated panel & chart canvas)
  * `--bg-panel: #161E29` (Interactive cards & subtle grid cells)
  * `--border-hairline: #233042` (1px structural grid lines)
  * `--text-primary: #EDF2F7` | `--text-muted: #8B98A8`
  * `--accent-alpha: #00D4AA` (Strategy equity, positive PnL, BUY signal)
  * `--accent-warn: #F5A623` (B3 friction, Swing Trade D0 guard, caution)
  * `--accent-halt: #FF4D5A` (Kill-Switch HALTED, Drawdown area, SELL/HALT signal)
  * `--accent-bench: #6B8CAE` (Buy & Hold reference curve)
* **Typography:**
  * Display Headers: `Space Grotesk` (distinct geometric technical voice)
  * UI Body & Explanations: `IBM Plex Sans` (high-legibility editorial clarity)
  * Financial Numerics & Ledgers: `JetBrains Mono` (`font-variant-numeric: tabular-nums`)
* **Motion Philosophy:** Restraint—single crisp panel border focus highlight and subtle entrance transition guarded by `@media (prefers-reduced-motion: reduce)`.

---

## 2. Architectural Decisions

* **Strict Pipeline Reuse (Zero Duplicated Quant Logic):**
  `src/dashboard/` is a pure presentation and orchestration consumer of existing modules:
  * Market data & Parquet cache: `YFinanceDataProvider` + `DataCacheManager` (`src/data/`)
  * Strategy signals & Net/Gross comparison: `EMACrossoverStrategy` + `StrategyBacktestRunner` (`src/strategies/`)
  * Risk overlay & Kill-Switch telemetry: `RiskConfig` + `RiskManager` (`src/risk/`)
  * Vectorized backtest engine: `VectorizedBacktestEngine` (`src/backtest/`)
  * Integer B3 paper simulation & receipts: `PaperTradingRunner` + `SimulatedPaperBroker` (`src/execution/`)
* **Compositional Module Layout (`src/dashboard/`):**
  1. `exceptions.py`: Typed exception hierarchy (`DashboardError`, `DashboardConfigurationError`, `DashboardDataError`, `LedgerLoadError`).
  2. `models.py`: Validated frozen dataclasses (`PresetAsset`, `DashboardParameters`, `RiskTelemetrySnapshot`, `LoadedLedgerSummary`, `DashboardSnapshot`) and `B3_PRESET_ASSETS` constant (`ITUB4.SA`, `PETR4.SA`, `VALE3.SA`, `WEGE3.SA`) with strict ticker regex and numeric bounds validation.
  3. `theme.py`: CSS variable stylesheet (`inject_dashboard_css`), SVG/HTML safe telemetry & KPI card markup helpers (`html.escape` on all dynamic strings), Plotly color palette constants, and `apply_plotly_theme(fig)`.
  4. `service.py`: `DashboardService` (headless, Streamlit-free) orchestrating `run_analysis(params)` and safe Phase 5 Ledger parsing (`parse_ledger_payload`, `load_ledger_json`) with 10 MB size guard and finite number checks.
  5. `charts.py`: Pure `plotly.graph_objects.Figure` factory functions (`build_price_ema_figure`, `build_equity_comparison_figure`, `build_drawdown_figure`, `build_capital_allocation_figure`), returning fully configured, interactive figures that can be unit tested deterministically without rendering a DOM.
  6. `components.py` & `app.py`: Thin Streamlit rendering components (`render_telemetry_strip`, `render_strategy_tab`, `render_paper_desk_tab`, `render_telemetry_audit_tab`, `render_dashboard_app`) kept cleanly separable for `streamlit.testing.v1.AppTest`.
* **Interactive & Intuitive UX Layout:**
  * Left Sidebar: Curated B3 Asset Presets + Custom Ticker input, Timeframe selector, Strategy (`EMA Fast/Slow`), Capital & Risk Preset (`R$ 100.00 Conservador 2%` vs. `Custom`) with an explanatory "Guia Rápido" expander.
  * Main Canvas:
    1. Top **Risk & Kill-Switch Telemetry Strip**
    2. **Tab 1 — Visão Geral & Backtest Lab** (Asymmetric KPI Hero + Candlestick/EMA/Trades chart + Multi-curve Equity & Drawdown comparison)
    3. **Tab 2 — Paper Desk (R$ 100 Fracionário B3)** (Cash vs. Custody Allocation chart + Execution Receipts table + B3 Fee & Residual Cash explainer)
    4. **Tab 3 — Telemetria de Risco & Auditoria de Ledger** (Kill-Switch gauges/progress bars + Upload/Load Phase 5 JSON Ledger + CSV/JSON exports)

---

## 3. Alternatives Discarded

* **Embedding Quant Formulas Inside Streamlit Callbacks (`app.py` monolith):** Rejected because mixing yfinance/EMA/backtest math inside UI callbacks violates `AGENTS.md` architecture separation, breaks headless unit testing, and duplicates validated logic already built in `src/backtest/`, `src/risk/`, and `src/execution/`.
* **Calling Live `RestSandboxBroker` or Accepting API Keys in Browser Inputs:** Rejected to avoid credential exposure risks in a browser session and accidental order emission while keeping `src/dashboard/` focused on research, simulated paper trading, and ledger auditing.
* **Custom React/Vite SPA:** Rejected because the repository roadmap and `README.md` explicitly standardize Phase 6 on **Streamlit / Plotly** within the existing Python 3.10+ stack.
* **Default Streamlit White/Gray Theme or Generic SaaS Purple Cards:** Rejected explicitly by `frontend-design` rules to deliver a memorable, domain-authentic quantitative trading-desk aesthetic with strict contrast and `tabular-nums`.


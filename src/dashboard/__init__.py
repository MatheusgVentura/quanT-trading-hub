"""Interactive quantitative web dashboard package (Streamlit / Plotly)."""

from src.dashboard.app import render_dashboard_app
from src.dashboard.charts import (
    build_capital_allocation_figure,
    build_drawdown_figure,
    build_equity_comparison_figure,
    build_price_ema_figure,
)
from src.dashboard.exceptions import (
    DashboardConfigurationError,
    DashboardDataError,
    DashboardError,
    LedgerLoadError,
)
from src.dashboard.models import (
    B3_PRESET_ASSETS,
    DashboardParameters,
    DashboardSnapshot,
    LoadedLedgerSummary,
    PresetAsset,
    RiskTelemetrySnapshot,
    validate_ticker_symbol,
)
from src.dashboard.service import (
    DashboardService,
    load_ledger_json,
    parse_ledger_payload,
    telemetry_from_ledger,
)
from src.dashboard.theme import THEME_TOKENS, apply_plotly_theme, build_dashboard_css

__all__ = [
    "B3_PRESET_ASSETS",
    "THEME_TOKENS",
    "DashboardConfigurationError",
    "DashboardDataError",
    "DashboardError",
    "DashboardParameters",
    "DashboardService",
    "DashboardSnapshot",
    "LedgerLoadError",
    "LoadedLedgerSummary",
    "PresetAsset",
    "RiskTelemetrySnapshot",
    "apply_plotly_theme",
    "build_capital_allocation_figure",
    "build_dashboard_css",
    "build_drawdown_figure",
    "build_equity_comparison_figure",
    "build_price_ema_figure",
    "load_ledger_json",
    "parse_ledger_payload",
    "render_dashboard_app",
    "telemetry_from_ledger",
    "validate_ticker_symbol",
]

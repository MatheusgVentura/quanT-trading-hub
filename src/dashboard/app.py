"""Thin Streamlit entrypoint for the B3 Quantitative Web Dashboard."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import streamlit as st

from src.dashboard.components import (
    render_header_and_telemetry,
    render_paper_desk_tab,
    render_sidebar_controls,
    render_strategy_tab,
    render_telemetry_audit_tab,
)
from src.dashboard.exceptions import DashboardError
from src.dashboard.models import DashboardParameters, DashboardSnapshot
from src.dashboard.service import DashboardService
from src.dashboard.theme import build_dashboard_css
from src.data.exceptions import DataError
from src.execution.exceptions import ExecutionError
from src.risk.exceptions import RiskError
from src.strategies.exceptions import StrategyError


def _configure_page() -> None:
    """Configure Streamlit page title and wide trading-desk viewport safely."""
    try:
        st.set_page_config(
            page_title="quanT · Mesa Quantitativa B3",
            page_icon="📈",
            layout="wide",
            initial_sidebar_state="expanded",
        )
    except st.errors.StreamlitAPIException:
        # Ignore duplicate calls inside AppTest or embedded harnesses.
        return


def _resolve_snapshot(
    service: DashboardService,
    params: DashboardParameters,
    *,
    force_refresh: bool,
) -> DashboardSnapshot:
    """Return cached session snapshot for identical parameters or run pipeline."""
    cached_params = st.session_state.get("qt_cached_params")
    cached_snapshot = st.session_state.get("qt_cached_snapshot")
    if (
        not force_refresh
        and cached_params == params
        and isinstance(cached_snapshot, DashboardSnapshot)
    ):
        return cached_snapshot

    snapshot = service.run_analysis(params)
    st.session_state["qt_cached_params"] = params
    st.session_state["qt_cached_snapshot"] = snapshot
    return snapshot


def render_dashboard_app(service: DashboardService | None = None) -> None:
    """Render the complete Obsidian Terminal B3 Quantitative Dashboard."""
    _configure_page()
    st.markdown(build_dashboard_css(), unsafe_allow_html=True)

    active_service = service or DashboardService()

    try:
        params, force_refresh = render_sidebar_controls()
    except DashboardError as exc:
        st.error(f"Parâmetros inválidos na barra lateral: {exc}")
        render_telemetry_audit_tab(None)
        return

    try:
        with st.spinner(f"Processando pipeline quantitativo para {params.ticker}..."):
            snapshot = _resolve_snapshot(
                active_service, params, force_refresh=force_refresh
            )
    except (DataError, StrategyError, RiskError, ExecutionError, DashboardError) as exc:
        st.error(f"Não foi possível executar a análise para {params.ticker}: {exc}")
        render_telemetry_audit_tab(None)
        return

    render_header_and_telemetry(snapshot.telemetry)
    tab_lab, tab_paper, tab_audit = st.tabs(
        [
            "Backtest & Estratégia",
            "Paper Desk (R$ 100 Fracionário)",
            "Telemetria de Risco & Ledger",
        ]
    )

    with tab_lab:
        render_strategy_tab(snapshot)
    with tab_paper:
        render_paper_desk_tab(snapshot)
    with tab_audit:
        render_telemetry_audit_tab(snapshot)


def _is_streamlit_runtime() -> bool:
    """Return True when executed inside an active Streamlit script runner context."""
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        return get_script_run_ctx() is not None
    except (ImportError, RuntimeError, AttributeError):
        return False


if __name__ == "__main__" or _is_streamlit_runtime():
    render_dashboard_app()

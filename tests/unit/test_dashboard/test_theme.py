"""Unit tests for the Obsidian Terminal design system and HTML safety."""

from datetime import datetime, timezone

import plotly.graph_objects as go

from src.dashboard.models import RiskTelemetrySnapshot
from src.dashboard.theme import (
    THEME_TOKENS,
    apply_plotly_theme,
    build_dashboard_css,
    build_explainer_banner_html,
    build_kpi_card_html,
    build_telemetry_strip_html,
    escape_html,
)
from src.risk.models import HaltReason, RiskStatus


def _sample_telemetry(*, halted: bool = False) -> RiskTelemetrySnapshot:
    return RiskTelemetrySnapshot(
        ticker="ITUB4.SA",
        execution_symbol="ITUB4F",
        kill_switch_status=RiskStatus.HALTED if halted else RiskStatus.ACTIVE,
        halt_reason=HaltReason.MAX_DRAWDOWN_LIMIT if halted else HaltReason.NONE,
        daily_pnl_pct=-0.0085,
        max_daily_loss_limit_pct=0.02,
        current_drawdown_pct=-0.105 if halted else -0.021,
        max_drawdown_limit_pct=0.10,
        observed_latency_ms=45.0,
        max_latency_limit_ms=500.0,
        allow_day_trade=False,
        open_shares=2,
        cash_balance=22.40,
        total_equity=101.60,
        last_updated=datetime(2026, 11, 11, 18, 0, tzinfo=timezone.utc),  # noqa: UP017
    )


def test_ac03_theme_tokens_and_anti_default_typography() -> None:
    """Verify required palette tokens, fonts, and absence of generic AI-default fonts."""
    assert THEME_TOKENS["bg_void"] == "#080B0F"
    assert THEME_TOKENS["bg_deck"] == "#0F141B"
    assert THEME_TOKENS["bg_panel"] == "#161E29"
    assert THEME_TOKENS["accent_alpha"] == "#00D4AA"
    assert THEME_TOKENS["accent_warn"] == "#F5A623"
    assert THEME_TOKENS["accent_halt"] == "#FF4D5A"
    assert THEME_TOKENS["accent_bench"] == "#6B8CAE"

    css = build_dashboard_css()
    assert "--bg-void: #080B0F;" in css
    assert "Space Grotesk" in css
    assert "IBM Plex Sans" in css
    assert "JetBrains Mono" in css
    assert "tabular-nums" in css
    assert "prefers-reduced-motion: reduce" in css
    assert ":focus-visible" in css

    for forbidden in ("Inter", "Roboto", "Arial"):
        assert forbidden not in css


def test_ac03_telemetry_strip_renders_active_and_halted_states() -> None:
    """Verify Telemetry Strip reflects ACTIVE vs HALTED circuit breaker states cleanly."""
    active_html = build_telemetry_strip_html(_sample_telemetry(halted=False))
    assert "ITUB4.SA" in active_html
    assert "ITUB4F" in active_html
    assert "ACTIVE" in active_html
    assert "SWING TRADE (D0 BLOQ.)" in active_html
    assert "qt-halted" not in active_html

    halted_html = build_telemetry_strip_html(_sample_telemetry(halted=True))
    assert "qt-halted" in halted_html
    assert "HALTED" in halted_html
    assert "MAX_DRAWDOWN_LIMIT" in halted_html


def test_ac09_html_builders_escape_untrusted_payloads() -> None:
    """Verify HTML template builders neutralize script/attribute injection attempts."""
    xss = '<script>alert("xss")</script>'
    assert escape_html(xss) == "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;"

    kpi_html = build_kpi_card_html(
        label=xss,
        value='R$ 100 <img src=x onerror="alert(1)">',
        subtitle="Test",
        tone="alpha",
        hero=True,
    )
    assert "<script>" not in kpi_html
    assert "<img " not in kpi_html
    assert "qt-hero" in kpi_html

    banner_html = build_explainer_banner_html(xss, "<svg onload=alert(1)>")
    assert "<script>" not in banner_html
    assert "<svg" not in banner_html


def test_ac03_apply_plotly_theme_sets_consistent_layout() -> None:
    """Verify apply_plotly_theme configures dark canvas, typography, and grid colors."""
    fig = go.Figure(data=[go.Scatter(x=[1, 2], y=[10.0, 12.0], name="Equity")])
    themed = apply_plotly_theme(
        fig, title="Equity Curve", y_title="R$", x_title="Date", height=420
    )
    assert themed.layout.paper_bgcolor == THEME_TOKENS["bg_deck"]
    assert themed.layout.plot_bgcolor == THEME_TOKENS["bg_void"]
    assert themed.layout.height == 420
    assert themed.layout.hovermode == "x unified"
    assert themed.layout.title.text == "Equity Curve"
    assert themed.layout.yaxis.title.text == "R$"
    assert themed.layout.xaxis.title.text == "Date"

"""Intentional Obsidian Terminal visual design system for the B3 dashboard."""

from __future__ import annotations

import html
from collections.abc import Mapping
from typing import Final

import plotly.graph_objects as go

from src.dashboard.models import RiskTelemetrySnapshot
from src.risk.models import RiskStatus

THEME_TOKENS: Final[dict[str, str]] = {
    "bg_void": "#080B0F",
    "bg_deck": "#0F141B",
    "bg_panel": "#161E29",
    "bg_panel_alt": "#1C2634",
    "border_hairline": "#233042",
    "border_strong": "#32445C",
    "text_primary": "#EDF2F7",
    "text_secondary": "#C5D0DC",
    "text_muted": "#8B98A8",
    "accent_alpha": "#00D4AA",
    "accent_warn": "#F5A623",
    "accent_halt": "#FF4D5A",
    "accent_bench": "#6B8CAE",
    "accent_gross": "#94A3B8",
    "grid_line": "#1A2330",
    "zero_line": "#2A394D",
    "font_display": "'Space Grotesk', 'Segoe UI Variable', system-ui, sans-serif",
    "font_body": "'IBM Plex Sans', 'Segoe UI', system-ui, sans-serif",
    "font_mono": "'JetBrains Mono', 'Cascadia Code', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
}

GOOGLE_FONTS_URL: Final[str] = (
    "https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700"
    "&family=JetBrains+Mono:wght@400;500;600;700"
    "&family=Space+Grotesk:wght@500;600;700&display=swap"
)


def escape_html(value: object) -> str:
    """Safely escape any dynamic value prior to HTML template interpolation."""
    return html.escape(str(value), quote=True)


def build_dashboard_css() -> str:
    """Build the full CSS stylesheet implementing Obsidian Terminal design tokens."""
    t = THEME_TOKENS
    return f"""
<style>
@import url('{GOOGLE_FONTS_URL}');

:root {{
    --bg-void: {t["bg_void"]};
    --bg-deck: {t["bg_deck"]};
    --bg-panel: {t["bg_panel"]};
    --bg-panel-alt: {t["bg_panel_alt"]};
    --border-hairline: {t["border_hairline"]};
    --border-strong: {t["border_strong"]};
    --text-primary: {t["text_primary"]};
    --text-secondary: {t["text_secondary"]};
    --text-muted: {t["text_muted"]};
    --accent-alpha: {t["accent_alpha"]};
    --accent-warn: {t["accent_warn"]};
    --accent-halt: {t["accent_halt"]};
    --accent-bench: {t["accent_bench"]};
    --accent-gross: {t["accent_gross"]};
    --font-display: {t["font_display"]};
    --font-body: {t["font_body"]};
    --font-mono: {t["font_mono"]};
}}

.stApp {{
    background-color: var(--bg-void);
    background-image: radial-gradient(
        ellipse 85% 35% at 50% -10%,
        rgba(0, 212, 170, 0.06),
        transparent 70%
    );
    color: var(--text-primary);
    font-family: var(--font-body);
}}

[data-testid="stHeader"] {{
    background-color: rgba(8, 11, 15, 0.88);
    border-bottom: 1px solid var(--border-hairline);
}}

[data-testid="stSidebar"] {{
    background-color: var(--bg-deck);
    border-right: 1px solid var(--border-hairline);
}}

[data-testid="stSidebar"] * {{
    font-family: var(--font-body);
}}

h1, h2, h3, .qt-display {{
    font-family: var(--font-display) !important;
    letter-spacing: -0.02em;
    color: var(--text-primary);
}}

.qt-mono, code, pre {{
    font-family: var(--font-mono) !important;
    font-variant-numeric: tabular-nums;
}}

.stTabs [data-baseweb="tab-list"] {{
    gap: 0.5rem;
    border-bottom: 1px solid var(--border-hairline);
    padding-bottom: 0.25rem;
}}

.stTabs [data-baseweb="tab"] {{
    background-color: transparent;
    color: var(--text-muted);
    font-family: var(--font-display);
    font-weight: 600;
    font-size: 0.92rem;
    padding: 0.55rem 0.95rem;
    border-radius: 6px 6px 0 0;
    border: 1px solid transparent;
}}

.stTabs [aria-selected="true"] {{
    background-color: var(--bg-panel) !important;
    color: var(--text-primary) !important;
    border-color: var(--border-hairline) !important;
    border-bottom: 2px solid var(--accent-alpha) !important;
}}

.qt-telemetry-strip {{
    display: grid;
    grid-template-columns: 1.4fr 1fr 1fr 1fr 1fr 1.15fr;
    gap: 0.65rem;
    background-color: var(--bg-deck);
    border: 1px solid var(--border-hairline);
    border-left: 3px solid var(--accent-alpha);
    border-radius: 8px;
    padding: 0.85rem 1rem;
    margin-bottom: 1rem;
    animation: qt-panel-enter 220ms ease-out both;
}}

.qt-telemetry-strip.qt-halted {{
    border-left-color: var(--accent-halt);
    background-image: linear-gradient(
        90deg,
        rgba(255, 77, 90, 0.09),
        transparent 38%
    );
}}

.qt-strip-cell {{
    display: flex;
    flex-direction: column;
    justify-content: center;
    padding-right: 0.6rem;
    border-right: 1px solid var(--border-hairline);
    min-width: 0;
}}

.qt-strip-cell:last-child {{
    border-right: none;
    padding-right: 0;
}}

.qt-label {{
    font-size: 0.68rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-muted);
    margin-bottom: 0.22rem;
    font-weight: 600;
}}

.qt-value {{
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
    font-size: 0.95rem;
    font-weight: 600;
    color: var(--text-primary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}

.qt-sub {{
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
    font-size: 0.74rem;
    color: var(--text-muted);
    margin-top: 0.12rem;
}}

.qt-pill {{
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.14rem 0.5rem;
    border-radius: 4px;
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
    font-size: 0.76rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    width: fit-content;
}}

.qt-pill-active {{
    background: rgba(0, 212, 170, 0.14);
    color: var(--accent-alpha);
    border: 1px solid rgba(0, 212, 170, 0.42);
}}

.qt-pill-warn {{
    background: rgba(245, 166, 35, 0.14);
    color: var(--accent-warn);
    border: 1px solid rgba(245, 166, 35, 0.42);
}}

.qt-pill-halted {{
    background: rgba(255, 77, 90, 0.16);
    color: var(--accent-halt);
    border: 1px solid rgba(255, 77, 90, 0.48);
}}

.qt-bento-grid {{
    display: grid;
    grid-template-columns: 1.55fr 1fr 1fr 1fr;
    gap: 0.75rem;
    margin-bottom: 1rem;
}}

.qt-kpi-card {{
    background-color: var(--bg-panel);
    border: 1px solid var(--border-hairline);
    border-radius: 8px;
    padding: 0.9rem 1rem;
    transition: border-color 140ms ease;
}}

.qt-kpi-card:hover {{
    border-color: var(--border-strong);
}}

.qt-kpi-card.qt-hero {{
    background-color: var(--bg-deck);
    border-top: 2px solid var(--accent-alpha);
}}

.qt-kpi-hero-val {{
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
    font-size: 1.78rem;
    font-weight: 700;
    color: var(--text-primary);
    line-height: 1.15;
    margin: 0.25rem 0;
}}

.qt-kpi-val {{
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
    font-size: 1.28rem;
    font-weight: 700;
    color: var(--text-primary);
    line-height: 1.2;
    margin: 0.22rem 0;
}}

.qt-explainer {{
    background-color: var(--bg-deck);
    border: 1px solid var(--border-hairline);
    border-left: 3px solid var(--accent-bench);
    border-radius: 6px;
    padding: 0.75rem 0.95rem;
    color: var(--text-secondary);
    font-size: 0.88rem;
    line-height: 1.48;
    margin: 0.45rem 0 0.85rem 0;
}}

a:focus-visible, button:focus-visible, input:focus-visible, select:focus-visible {{
    outline: 2px solid var(--accent-alpha) !important;
    outline-offset: 2px !important;
}}

@keyframes qt-panel-enter {{
    from {{
        opacity: 0;
        transform: translateY(4px);
    }}
    to {{
        opacity: 1;
        transform: translateY(0);
    }}
}}

@media (max-width: 1100px) {{
    .qt-telemetry-strip {{
        grid-template-columns: repeat(3, minmax(0, 1fr));
    }}
    .qt-bento-grid {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }}
    .qt-strip-cell {{
        border-right: none;
        border-bottom: 1px solid var(--border-hairline);
        padding-bottom: 0.45rem;
    }}
}}

@media (max-width: 640px) {{
    .qt-telemetry-strip, .qt-bento-grid {{
        grid-template-columns: 1fr;
    }}
}}

@media (prefers-reduced-motion: reduce) {{
    *, *::before, *::after {{
        animation-duration: 0.001ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.001ms !important;
    }}
}}
</style>
"""


def _tone_class(tone: str) -> str:
    """Map semantic tone token to CSS utility color inline style."""
    palette: Mapping[str, str] = {
        "alpha": THEME_TOKENS["accent_alpha"],
        "warn": THEME_TOKENS["accent_warn"],
        "halt": THEME_TOKENS["accent_halt"],
        "bench": THEME_TOKENS["accent_bench"],
        "neutral": THEME_TOKENS["text_primary"],
    }
    return palette.get(tone, THEME_TOKENS["text_primary"])


def build_telemetry_strip_html(telemetry: RiskTelemetrySnapshot) -> str:
    """Render the signature top Risk & Kill-Switch Telemetry Strip safely."""
    is_halted = telemetry.kill_switch_status == RiskStatus.HALTED
    strip_cls = "qt-telemetry-strip qt-halted" if is_halted else "qt-telemetry-strip"
    status_pill_cls = (
        "qt-pill qt-pill-halted" if is_halted else "qt-pill qt-pill-active"
    )
    status_text = (
        f"HALTED · {telemetry.halt_reason.value}"
        if is_halted
        else "ACTIVE · OPERATIONAL"
    )
    swing_pill_cls = (
        "qt-pill qt-pill-warn"
        if telemetry.allow_day_trade
        else "qt-pill qt-pill-active"
    )
    swing_text = (
        "DAY TRADE LIVRE" if telemetry.allow_day_trade else "SWING TRADE (D0 BLOQ.)"
    )
    latency_tone = (
        THEME_TOKENS["accent_halt"]
        if telemetry.observed_latency_ms > telemetry.max_latency_limit_ms
        else THEME_TOKENS["accent_alpha"]
    )

    return (
        f'<div class="{strip_cls}" role="region" aria-label="Risk and Kill-Switch Telemetry">'
        f'  <div class="qt-strip-cell">'
        f'    <span class="qt-label">Ativo / Símbolo B3</span>'
        f'    <span class="qt-value">{escape_html(telemetry.ticker)} · {escape_html(telemetry.execution_symbol)}</span>'
        f'    <span class="qt-sub">Custódia: {escape_html(telemetry.open_shares)} ações · R$ {telemetry.total_equity:,.2f}</span>'
        f"  </div>"
        f'  <div class="qt-strip-cell">'
        f'    <span class="qt-label">Kill-Switch</span>'
        f'    <span class="{status_pill_cls}">{escape_html(status_text)}</span>'
        f'    <span class="qt-sub">Atualizado {escape_html(telemetry.last_updated.strftime("%Y-%m-%d"))}</span>'
        f"  </div>"
        f'  <div class="qt-strip-cell">'
        f'    <span class="qt-label">PnL Diário / Limite</span>'
        f'    <span class="qt-value">{telemetry.daily_pnl_pct * 100.0:+.2f}%</span>'
        f'    <span class="qt-sub">Trava: -{telemetry.max_daily_loss_limit_pct * 100.0:.1f}%</span>'
        f"  </div>"
        f'  <div class="qt-strip-cell">'
        f'    <span class="qt-label">Drawdown / Disjuntor</span>'
        f'    <span class="qt-value">{telemetry.current_drawdown_pct * 100.0:.2f}%</span>'
        f'    <span class="qt-sub">Limite: -{telemetry.max_drawdown_limit_pct * 100.0:.1f}%</span>'
        f"  </div>"
        f'  <div class="qt-strip-cell">'
        f'    <span class="qt-label">Latência Feed / Teto</span>'
        f'    <span class="qt-value" style="color: {latency_tone};">{telemetry.observed_latency_ms:.1f} ms</span>'
        f'    <span class="qt-sub">Teto: {telemetry.max_latency_limit_ms:.0f} ms</span>'
        f"  </div>"
        f'  <div class="qt-strip-cell">'
        f'    <span class="qt-label">Regime Operacional</span>'
        f'    <span class="{swing_pill_cls}">{escape_html(swing_text)}</span>'
        f'    <span class="qt-sub">Caixa: R$ {telemetry.cash_balance:,.2f}</span>'
        f"  </div>"
        f"</div>"
    )


def build_kpi_card_html(
    *,
    label: str,
    value: str,
    subtitle: str,
    tone: str = "neutral",
    hero: bool = False,
) -> str:
    """Build an XSS-safe Bento KPI card block."""
    card_cls = "qt-kpi-card qt-hero" if hero else "qt-kpi-card"
    val_cls = "qt-kpi-hero-val" if hero else "qt-kpi-val"
    color = _tone_class(tone)
    return (
        f'<div class="{card_cls}">'
        f'  <div class="qt-label">{escape_html(label)}</div>'
        f'  <div class="{val_cls}" style="color: {color};">{escape_html(value)}</div>'
        f'  <div class="qt-sub">{escape_html(subtitle)}</div>'
        f"</div>"
    )


def build_explainer_banner_html(title: str, body: str) -> str:
    """Render an accessible plain-language explainer note for operational rules."""
    return (
        '<div class="qt-explainer">'
        f'<strong style="color: var(--text-primary); font-family: var(--font-display);">'
        f"{escape_html(title)}:</strong> {escape_html(body)}"
        "</div>"
    )


def apply_plotly_theme(
    figure: go.Figure,
    *,
    title: str = "",
    y_title: str = "",
    x_title: str = "",
    height: int = 400,
) -> go.Figure:
    """Apply consistent Obsidian Terminal visual styling to any Plotly Figure."""
    t = THEME_TOKENS
    figure.update_layout(
        title=(
            {
                "text": title,
                "font": {
                    "family": t["font_display"],
                    "size": 16,
                    "color": t["text_primary"],
                },
                "x": 0.01,
                "xanchor": "left",
            }
            if title
            else None
        ),
        paper_bgcolor=t["bg_deck"],
        plot_bgcolor=t["bg_void"],
        font={
            "family": t["font_body"],
            "size": 12,
            "color": t["text_secondary"],
        },
        hovermode="x unified",
        hoverlabel={
            "bgcolor": t["bg_panel"],
            "bordercolor": t["border_strong"],
            "font": {
                "family": t["font_mono"],
                "size": 12,
                "color": t["text_primary"],
            },
        },
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "right",
            "x": 1.0,
            "bgcolor": "rgba(15, 20, 27, 0.7)",
            "font": {"size": 11, "color": t["text_secondary"]},
        },
        margin={"l": 56, "r": 24, "t": 54 if title else 36, "b": 42},
        height=height,
        xaxis={
            "title": x_title or None,
            "gridcolor": t["grid_line"],
            "zerolinecolor": t["zero_line"],
            "linecolor": t["border_hairline"],
            "tickfont": {
                "family": t["font_mono"],
                "size": 11,
                "color": t["text_muted"],
            },
            "showspikes": True,
            "spikethickness": 1,
            "spikecolor": t["border_strong"],
        },
        yaxis={
            "title": y_title or None,
            "gridcolor": t["grid_line"],
            "zerolinecolor": t["zero_line"],
            "linecolor": t["border_hairline"],
            "tickfont": {
                "family": t["font_mono"],
                "size": 11,
                "color": t["text_muted"],
            },
        },
    )
    return figure

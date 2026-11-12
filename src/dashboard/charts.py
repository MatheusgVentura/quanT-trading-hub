"""Pure Plotly figure builders for the Obsidian Terminal B3 dashboard."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from src.dashboard.exceptions import DashboardDataError
from src.dashboard.theme import THEME_TOKENS, apply_plotly_theme


def _require_non_empty_df(df: object, name: str) -> pd.DataFrame:
    """Validate that a DataFrame is non-empty before plotting."""
    if not isinstance(df, pd.DataFrame) or df.empty:
        raise DashboardDataError(f"{name} must be a non-empty pandas DataFrame.")
    return df


def build_price_ema_figure(
    ohlcv_df: pd.DataFrame,
    *,
    trade_markers: pd.DataFrame | None = None,
    ticker: str = "ATIVO",
    fast_period: int = 9,
    slow_period: int = 21,
) -> go.Figure:
    """Build interactive OHLC candlestick + EMA overlay figure with execution markers."""
    df = _require_non_empty_df(ohlcv_df, "ohlcv_df")
    if "Close" not in df.columns:
        raise DashboardDataError("ohlcv_df must contain a 'Close' column.")

    fig = go.Figure()
    has_ohlc = all(col in df.columns for col in ("Open", "High", "Low", "Close"))
    if has_ohlc:
        fig.add_trace(
            go.Candlestick(
                x=df.index,
                open=df["Open"],
                high=df["High"],
                low=df["Low"],
                close=df["Close"],
                name=f"Candles ({ticker})",
                increasing_line_color=THEME_TOKENS["accent_alpha"],
                increasing_fillcolor="rgba(0, 212, 170, 0.35)",
                decreasing_line_color=THEME_TOKENS["accent_halt"],
                decreasing_fillcolor="rgba(255, 77, 90, 0.35)",
            )
        )
    else:
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["Close"],
                mode="lines",
                name=f"Fechamento ({ticker})",
                line={"color": THEME_TOKENS["text_secondary"], "width": 1.8},
            )
        )

    if "EMA_Fast" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["EMA_Fast"],
                mode="lines",
                name=f"EMA Rápida ({fast_period})",
                line={"color": THEME_TOKENS["accent_alpha"], "width": 1.8},
            )
        )

    if "EMA_Slow" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["EMA_Slow"],
                mode="lines",
                name=f"EMA Lenta ({slow_period})",
                line={"color": THEME_TOKENS["accent_warn"], "width": 1.8},
            )
        )

    if trade_markers is not None and not trade_markers.empty:
        marker_specs = (
            ("BUY", "Compra (BUY)", "triangle-up", THEME_TOKENS["accent_alpha"], 11),
            ("EXIT", "Saída (EXIT)", "triangle-down", THEME_TOKENS["accent_warn"], 11),
            ("HALT", "Disjuntor (HALT)", "x", THEME_TOKENS["accent_halt"], 12),
        )
        for action, label, symbol, color, size in marker_specs:
            subset = trade_markers[trade_markers["Action"] == action]
            if not subset.empty:
                fig.add_trace(
                    go.Scatter(
                        x=subset["Timestamp"],
                        y=subset["Close"],
                        mode="markers",
                        name=label,
                        marker={
                            "symbol": symbol,
                            "size": size,
                            "color": color,
                            "line": {"width": 1.2, "color": THEME_TOKENS["bg_void"]},
                        },
                        hovertemplate=(
                            f"<b>{label}</b><br>"
                            "Data: %{x|%Y-%m-%d}<br>"
                            "Preço: R$ %{y:.2f}<extra></extra>"
                        ),
                    )
                )

    fig.update_layout(xaxis_rangeslider_visible=False)
    return apply_plotly_theme(
        fig,
        title=f"Ação de Preço, Médias EMA ({fast_period}/{slow_period}) e Sinais — {ticker}",
        y_title="Preço (R$)",
        height=440,
    )


def _extract_brl_series(
    curve: pd.DataFrame, column: str, initial_capital: float
) -> pd.Series:
    """Convert normalized equity curve (base 1.0) into BRL series."""
    return curve[column].astype(float) * float(initial_capital)


def build_equity_comparison_figure(
    net_equity_curve: pd.DataFrame,
    *,
    risk_equity_curve: pd.DataFrame | None = None,
    gross_equity_curve: pd.DataFrame | None = None,
    initial_capital: float = 100.0,
    ticker: str = "ATIVO",
) -> go.Figure:
    """Build multi-curve BRL equity comparison (Net vs Gross vs Risk Overlay vs Buy&Hold)."""
    df = _require_non_empty_df(net_equity_curve, "net_equity_curve")
    fig = go.Figure()

    if "Curva_Estrategia" in df.columns:
        net_brl = _extract_brl_series(df, "Curva_Estrategia", initial_capital)
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=net_brl,
                mode="lines",
                name="Estratégia Líquida (B3 0,03%)",
                line={"color": THEME_TOKENS["accent_alpha"], "width": 2.3},
            )
        )

        if gross_equity_curve is not None and not gross_equity_curve.empty:
            gross_brl = _extract_brl_series(
                gross_equity_curve, "Curva_Estrategia", initial_capital
            )
            gross_x = gross_equity_curve.index
        elif {"Retorno_Estrategia", "Custos"}.issubset(df.columns):
            gross_returns = df["Retorno_Estrategia"].astype(float) + df[
                "Custos"
            ].astype(float)
            gross_brl = (1.0 + gross_returns).cumprod() * float(initial_capital)
            gross_x = df.index
        else:
            gross_brl = None
            gross_x = df.index

        if gross_brl is not None:
            fig.add_trace(
                go.Scatter(
                    x=gross_x,
                    y=gross_brl,
                    mode="lines",
                    name="Estratégia Bruta (Sem Taxas)",
                    line={
                        "color": THEME_TOKENS["accent_gross"],
                        "width": 1.6,
                        "dash": "dot",
                    },
                )
            )

        if (
            risk_equity_curve is not None
            and not risk_equity_curve.empty
            and "Curva_Estrategia" in risk_equity_curve.columns
        ):
            risk_brl = _extract_brl_series(
                risk_equity_curve, "Curva_Estrategia", initial_capital
            )
            fig.add_trace(
                go.Scatter(
                    x=risk_equity_curve.index,
                    y=risk_brl,
                    mode="lines",
                    name="Com Gestão de Risco (Stops + Kill-Switch)",
                    line={"color": THEME_TOKENS["accent_warn"], "width": 2.0},
                )
            )

        if "Curva_Benchmark" in df.columns:
            bench_brl = _extract_brl_series(df, "Curva_Benchmark", initial_capital)
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=bench_brl,
                    mode="lines",
                    name=f"Buy & Hold ({ticker})",
                    line={
                        "color": THEME_TOKENS["accent_bench"],
                        "width": 1.7,
                        "dash": "dash",
                    },
                )
            )
    elif "Equity" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["Equity"].astype(float),
                mode="lines",
                name="Patrimônio Paper (Lotes Inteiros B3)",
                line={"color": THEME_TOKENS["accent_alpha"], "width": 2.3},
            )
        )
        if "Benchmark_Equity" in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=df["Benchmark_Equity"].astype(float),
                    mode="lines",
                    name=f"Buy & Hold ({ticker})",
                    line={
                        "color": THEME_TOKENS["accent_bench"],
                        "width": 1.7,
                        "dash": "dash",
                    },
                )
            )
    else:
        raise DashboardDataError(
            "net_equity_curve must contain 'Curva_Estrategia' or 'Equity'."
        )

    fig.add_hline(
        y=float(initial_capital),
        line_dash="dot",
        line_color=THEME_TOKENS["border_strong"],
        annotation_text=f"Base R$ {initial_capital:,.2f}",
        annotation_position="bottom right",
    )

    return apply_plotly_theme(
        fig,
        title=f"Evolução Patrimonial Comparada (Base R$ {initial_capital:,.2f}) — {ticker}",
        y_title="Patrimônio (R$)",
        height=390,
    )


def build_drawdown_figure(
    equity_curve: pd.DataFrame,
    *,
    risk_equity_curve: pd.DataFrame | None = None,
    kill_switch_drawdown_pct: float = 0.10,
    drawdown_in_pct: bool = False,
    ticker: str = "ATIVO",
) -> go.Figure:
    """Build underwater Drawdown (%) curve marking the Kill-Switch threshold line."""
    df = _require_non_empty_df(equity_curve, "equity_curve")
    if "Drawdown" not in df.columns:
        raise DashboardDataError("equity_curve must contain a 'Drawdown' column.")

    scale = 1.0 if drawdown_in_pct else 100.0
    dd_series = df["Drawdown"].astype(float) * scale

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=dd_series,
            mode="lines",
            name="Drawdown Subaquático (%)",
            fill="tozeroy",
            fillcolor="rgba(255, 77, 90, 0.22)",
            line={"color": THEME_TOKENS["accent_halt"], "width": 1.8},
        )
    )

    if (
        risk_equity_curve is not None
        and not risk_equity_curve.empty
        and "Drawdown" in risk_equity_curve.columns
    ):
        risk_dd = risk_equity_curve["Drawdown"].astype(float) * scale
        fig.add_trace(
            go.Scatter(
                x=risk_equity_curve.index,
                y=risk_dd,
                mode="lines",
                name="Drawdown com Risco (%)",
                line={
                    "color": THEME_TOKENS["accent_warn"],
                    "width": 1.6,
                    "dash": "dot",
                },
            )
        )

    limit_pct = -abs(float(kill_switch_drawdown_pct) * 100.0)
    fig.add_hline(
        y=limit_pct,
        line_dash="dash",
        line_color=THEME_TOKENS["accent_halt"],
        annotation_text=f"Kill-Switch ({limit_pct:.1f}%)",
        annotation_position="bottom left",
        annotation_font={"color": THEME_TOKENS["accent_halt"], "size": 11},
    )

    return apply_plotly_theme(
        fig,
        title=f"Drawdown Subaquático e Trava do Disjuntor — {ticker}",
        y_title="Queda do Pico (%)",
        height=290,
    )


def build_capital_allocation_figure(
    paper_curve: pd.DataFrame,
    *,
    ticker: str = "ATIVO",
    execution_symbol: str = "",
) -> go.Figure:
    """Build stacked Cash vs Integer Custody allocation chart for Paper Desk."""
    df = _require_non_empty_df(paper_curve, "paper_curve")
    required_cols = {"Cash", "Position_Value", "Equity"}
    missing = sorted(required_cols - set(df.columns))
    if missing:
        raise DashboardDataError(
            f"paper_curve missing required columns: {', '.join(missing)}."
        )

    custody_label = execution_symbol.strip() or ticker
    shares_custom = (
        df["Shares"].astype(int).tolist() if "Shares" in df.columns else [0] * len(df)
    )

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["Cash"].astype(float),
            mode="lines",
            stackgroup="capital",
            name="Caixa Residual (R$)",
            line={"color": THEME_TOKENS["accent_bench"], "width": 1.2},
            fillcolor="rgba(107, 140, 174, 0.42)",
            customdata=shares_custom,
            hovertemplate=(
                "Caixa: R$ %{y:.2f}<br>Custódia: %{customdata} ações<extra></extra>"
            ),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["Position_Value"].astype(float),
            mode="lines",
            stackgroup="capital",
            name=f"Custódia {custody_label} (R$)",
            line={"color": THEME_TOKENS["accent_alpha"], "width": 1.6},
            fillcolor="rgba(0, 212, 170, 0.42)",
            customdata=shares_custom,
            hovertemplate=(
                "Posição: R$ %{y:.2f}<br>Ações em Custódia: %{customdata}<extra></extra>"
            ),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["Equity"].astype(float),
            mode="lines",
            name="Patrimônio Total (MTM)",
            line={"color": THEME_TOKENS["text_primary"], "width": 1.8},
        )
    )

    if "Benchmark_Equity" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["Benchmark_Equity"].astype(float),
                mode="lines",
                name=f"Buy & Hold ({ticker})",
                line={
                    "color": THEME_TOKENS["accent_warn"],
                    "width": 1.5,
                    "dash": "dash",
                },
            )
        )

    return apply_plotly_theme(
        fig,
        title=f"Alocação em Lotes Inteiros B3: Caixa Residual vs Custódia ({custody_label})",
        y_title="Valor (R$)",
        height=390,
    )

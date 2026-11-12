"""Unit tests for pure Plotly figure builders in src/dashboard/charts.py."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.dashboard.charts import (
    build_capital_allocation_figure,
    build_drawdown_figure,
    build_equity_comparison_figure,
    build_price_ema_figure,
)
from src.dashboard.exceptions import DashboardDataError
from src.dashboard.models import DashboardParameters
from src.dashboard.service import DashboardService
from src.data.interfaces import IDataProvider


class _ChartFakeProvider(IDataProvider):
    """In-memory OHLCV provider generating realistic B3 trending candles."""

    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df

    def fetch_ohlcv(
        self,
        ticker: str,
        start_date: str | None = None,
        end_date: str | None = None,
        period: str | None = "1y",
        interval: str = "1d",
    ) -> pd.DataFrame:
        return self._df.copy()


def _sample_ohlcv(bars: int = 80) -> pd.DataFrame:
    dates = pd.date_range("2024-01-02", periods=bars, freq="B")
    seg1 = np.linspace(38.0, 30.0, bars // 3)
    seg2 = np.linspace(30.5, 45.0, bars // 3)
    seg3 = np.linspace(44.5, 34.0, bars - len(seg1) - len(seg2))
    close = np.concatenate([seg1, seg2, seg3])
    return pd.DataFrame(
        {
            "Open": close * 0.995,
            "High": close * 1.015,
            "Low": close * 0.985,
            "Close": close,
            "Volume": np.full(bars, 1_200_000.0),
        },
        index=dates,
    )


def test_ac05_build_price_ema_figure_renders_candles_emas_and_markers() -> None:
    """Verify candlestick, EMA curves, and BUY/EXIT/HALT trade markers."""
    ohlcv = _sample_ohlcv(90)
    service = DashboardService(data_provider=_ChartFakeProvider(ohlcv))
    snapshot = service.run_analysis(
        DashboardParameters(
            ticker="ITUB4.SA",
            fast_period=5,
            slow_period=12,
            allow_min_lot_override=True,
            max_risk_per_trade_pct=0.50,
        )
    )

    fig = build_price_ema_figure(
        snapshot.ohlcv_with_indicators,
        trade_markers=snapshot.trade_markers,
        ticker="ITUB4.SA",
        fast_period=5,
        slow_period=12,
    )
    trace_types = [trace.type for trace in fig.data]
    trace_names = [trace.name for trace in fig.data]

    assert "candlestick" in trace_types
    assert "EMA Rápida (5)" in trace_names
    assert "EMA Lenta (12)" in trace_names
    assert any("BUY" in name for name in trace_names)
    assert fig.layout.xaxis.rangeslider.visible is False


def test_ac05_build_price_ema_figure_supports_close_only_fallback_and_halt_markers() -> (
    None
):
    """Verify Close-only line fallback and explicit HALT marker rendering."""
    dates = pd.date_range("2024-02-01", periods=5, freq="B")
    close_only = pd.DataFrame({"Close": [30.0, 31.0, 32.0, 28.0, 27.5]}, index=dates)
    markers = pd.DataFrame(
        [
            {"Timestamp": dates[1], "Close": 31.0, "Action": "BUY"},
            {"Timestamp": dates[3], "Close": 28.0, "Action": "HALT"},
        ]
    )
    fig = build_price_ema_figure(close_only, trade_markers=markers, ticker="PETR4.SA")
    names = [trace.name for trace in fig.data]
    assert "Fechamento (PETR4.SA)" in names
    assert "Compra (BUY)" in names
    assert "Disjuntor (HALT)" in names


def test_ac06_build_equity_and_drawdown_figures_include_all_curves_and_kill_switch_line() -> (
    None
):
    """Verify multi-curve equity comparison and -10% Kill-Switch threshold annotation."""
    ohlcv = _sample_ohlcv(90)
    service = DashboardService(data_provider=_ChartFakeProvider(ohlcv))
    snapshot = service.run_analysis(
        DashboardParameters(
            ticker="ITUB4.SA",
            fast_period=5,
            slow_period=12,
            initial_capital=100.0,
        )
    )

    eq_fig = build_equity_comparison_figure(
        snapshot.net_backtest.equity_curve,
        risk_equity_curve=snapshot.risk_adjusted_backtest.equity_curve,
        initial_capital=100.0,
        ticker="ITUB4.SA",
    )
    eq_names = [trace.name for trace in eq_fig.data]
    assert "Estratégia Líquida (B3 0,03%)" in eq_names
    assert "Estratégia Bruta (Sem Taxas)" in eq_names
    assert "Com Gestão de Risco (Stops + Kill-Switch)" in eq_names
    assert "Buy & Hold (ITUB4.SA)" in eq_names

    dd_fig = build_drawdown_figure(
        snapshot.net_backtest.equity_curve,
        risk_equity_curve=snapshot.risk_adjusted_backtest.equity_curve,
        kill_switch_drawdown_pct=0.10,
        drawdown_in_pct=False,
        ticker="ITUB4.SA",
    )
    dd_names = [trace.name for trace in dd_fig.data]
    assert "Drawdown Subaquático (%)" in dd_names
    assert "Drawdown com Risco (%)" in dd_names
    hlines = list(dd_fig.layout.shapes or ())
    assert any(getattr(s, "y0", None) == pytest.approx(-10.0) for s in hlines)


def test_ac07_build_capital_allocation_figure_shows_residual_cash_vs_custody() -> None:
    """Verify stacked Cash vs Integer Custody allocation chart preserves R$ 100 math."""
    ohlcv = _sample_ohlcv(90)
    service = DashboardService(data_provider=_ChartFakeProvider(ohlcv))
    snapshot = service.run_analysis(
        DashboardParameters(
            ticker="ITUB4.SA",
            fast_period=5,
            slow_period=12,
            initial_capital=100.0,
            allow_min_lot_override=True,
            max_risk_per_trade_pct=0.50,
        )
    )

    cap_fig = build_capital_allocation_figure(
        snapshot.paper_report.equity_curve,
        ticker="ITUB4.SA",
        execution_symbol="ITUB4F",
    )
    names = [trace.name for trace in cap_fig.data]
    assert "Caixa Residual (R$)" in names
    assert "Custódia ITUB4F (R$)" in names
    assert "Patrimônio Total (MTM)" in names
    assert "Buy & Hold (ITUB4.SA)" in names

    paper_eq_fig = build_equity_comparison_figure(
        snapshot.paper_report.equity_curve,
        initial_capital=100.0,
        ticker="ITUB4.SA",
    )
    assert any("Paper" in trace.name for trace in paper_eq_fig.data)


def test_ac05_ac07_chart_builders_fail_closed_on_invalid_dataframes() -> None:
    """Verify figure builders raise DashboardDataError on empty or malformed DataFrames."""
    empty = pd.DataFrame()
    with pytest.raises(DashboardDataError, match="non-empty"):
        build_price_ema_figure(empty)

    with pytest.raises(DashboardDataError, match="Close"):
        build_price_ema_figure(pd.DataFrame({"Open": [1.0]}))

    with pytest.raises(DashboardDataError, match="Curva_Estrategia"):
        build_equity_comparison_figure(pd.DataFrame({"Foo": [1.0]}))

    with pytest.raises(DashboardDataError, match="Drawdown"):
        build_drawdown_figure(pd.DataFrame({"Equity": [100.0]}))

    with pytest.raises(DashboardDataError, match="missing required columns"):
        build_capital_allocation_figure(pd.DataFrame({"Cash": [100.0]}))

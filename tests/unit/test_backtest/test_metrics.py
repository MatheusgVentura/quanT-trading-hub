"""Testes unitários rigorosos para a calculadora de métricas quantitativas."""

import numpy as np
import pandas as pd
from src.backtest.metrics import MetricsCalculator
from src.backtest.models import BacktestConfig


def test_metrics_empty_series():
    """Valida retorno seguro quando as séries forem vazias."""
    config = BacktestConfig()
    metrics = MetricsCalculator.calculate_metrics(
        equity_curve=pd.Series(dtype=float),
        strategy_returns=pd.Series(dtype=float),
        benchmark_returns=pd.Series(dtype=float),
        position_changes=pd.Series(dtype=float),
        config=config,
    )
    assert metrics.trading_days == 0
    assert metrics.total_return_pct == 0.0
    assert metrics.sharpe_ratio == 0.0
    assert metrics.max_drawdown_pct == 0.0


def test_metrics_drawdown_exactness():
    """Valida precisão do cálculo de Max Drawdown com queda conhecida de 20%."""
    # Curva: sobe para 100, sobe para 120 (pico), cai para 96 (queda de 20%), sobe para 110
    equity = pd.Series([1.0, 1.20, 0.96, 1.10])
    returns = equity.pct_change().fillna(0.0)
    config = BacktestConfig()

    metrics = MetricsCalculator.calculate_metrics(
        equity_curve=equity,
        strategy_returns=returns,
        benchmark_returns=returns,
        position_changes=pd.Series([0.0, 0.0, 0.0, 0.0]),
        config=config,
    )

    # Queda de 1.20 para 0.96 é exatamente (0.96 - 1.20) / 1.20 = -0.24 / 1.20 = -0.20 (-20.0%)
    assert metrics.max_drawdown_pct == -20.0


def test_metrics_cagr_doubling():
    """Valida CAGR após 252 dias úteis dobrando de valor (retorno 100%)."""
    days = 252
    config = BacktestConfig(trading_days_per_year=days)
    # 252 dias com retorno diário composto resultando em 2.0
    daily_factor = 2.0 ** (1.0 / days)
    equity = pd.Series([daily_factor**i for i in range(days)])
    returns = equity.pct_change().fillna(0.0)

    metrics = MetricsCalculator.calculate_metrics(
        equity_curve=equity,
        strategy_returns=returns,
        benchmark_returns=returns,
        position_changes=pd.Series([0.0] * days),
        config=config,
    )

    assert abs(metrics.total_return_pct - 100.0) < 1.0
    assert abs(metrics.cagr_pct - 100.0) < 1.0


def test_metrics_win_rate_and_profit_factor():
    """Valida cálculo de Win Rate e Profit Factor."""
    # 3 ganhos de 10% e 1 perda de 10%
    returns = pd.Series([0.10, 0.10, -0.10, 0.10])
    equity = (1.0 + returns).cumprod()
    config = BacktestConfig()

    metrics = MetricsCalculator.calculate_metrics(
        equity_curve=equity,
        strategy_returns=returns,
        benchmark_returns=returns,
        position_changes=pd.Series([0.0, 0.0, 0.0, 0.0]),
        config=config,
    )

    # Win rate: 3 positivos de 4 dias = 75.0%
    assert metrics.win_rate_pct == 75.0
    # Profit factor: ganhos = 0.30, perdas = 0.10 -> 3.0
    assert metrics.profit_factor == 3.0

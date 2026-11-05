"""Testes unitários para BacktestConfig, BacktestMetrics e BacktestResult."""

import pandas as pd
from src.backtest.models import BacktestConfig, BacktestMetrics, BacktestResult


def test_backtest_config_defaults():
    """Valida valores padrão da configuração alinhados com custos B3 e XP."""
    config = BacktestConfig()
    assert config.initial_capital == 100.0
    assert config.b3_fee_pct == 0.0003  # 0.03%
    assert config.brokerage_fee == 0.0  # RLP XP
    assert config.trading_days_per_year == 252


def test_backtest_result_summary():
    """Valida se o método summary() gera relatório textual legível."""
    config = BacktestConfig(initial_capital=100.0)
    metrics = BacktestMetrics(
        total_return_pct=25.50,
        benchmark_return_pct=15.00,
        cagr_pct=12.00,
        annualized_volatility_pct=18.50,
        sharpe_ratio=1.45,
        sortino_ratio=2.10,
        max_drawdown_pct=-8.20,
        profit_factor=1.80,
        win_rate_pct=58.0,
        total_trades=14,
        trading_days=252,
    )
    result = BacktestResult(
        ticker="ITUB4.SA",
        config=config,
        metrics=metrics,
        equity_curve=pd.DataFrame(),
    )
    summary_text = result.summary()

    assert "ITUB4.SA" in summary_text
    assert "+25.50%" in summary_text
    assert "1.45" in summary_text
    assert "-8.20%" in summary_text
    assert "14" in summary_text

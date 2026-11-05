"""Unit tests for StrategyBacktestRunner and StrategyComparisonReport (AC03, AC04, AC13)."""

import numpy as np
import pandas as pd
import pytest

from src.strategies.base import BaseStrategy
from src.strategies.ema_crossover import EMACrossoverStrategy
from src.strategies.exceptions import InsufficientDataError
from src.strategies.runner import StrategyBacktestRunner, StrategyComparisonReport


@pytest.fixture
def sample_daily_ohlcv() -> pd.DataFrame:
    """Creates synthetic 60-day daily OHLCV dataframe with trending movements."""
    dates = pd.date_range("2023-01-01", periods=60, freq="B")
    np.random.seed(42)
    # Generate prices that rise initially then fall to produce crossovers
    prices = 20.0 + np.sin(np.linspace(0, 3 * np.pi, 60)) * 5.0 + np.linspace(0, 3, 60)
    df = pd.DataFrame(
        {
            "Open": prices * 0.99,
            "High": prices * 1.02,
            "Low": prices * 0.98,
            "Close": prices,
            "Volume": 100_000,
        },
        index=dates,
    )
    return df


def test_ac03_ac04_runner_net_and_gross_comparison(
    sample_daily_ohlcv: pd.DataFrame,
) -> None:
    """Verifies AC03 & AC04: Dual execution (net with B3 fee vs gross without fee) and report metrics."""
    strategy = EMACrossoverStrategy(fast_period=5, slow_period=15)
    b3_fee = 0.0003  # 0.03%

    _result_net, report = StrategyBacktestRunner.run(
        sample_daily_ohlcv, strategy, ticker="PETR4.SA", b3_fee_pct=b3_fee
    )

    # AC03 & AC04: Verify report structure and fields
    assert isinstance(report, StrategyComparisonReport)
    assert report.ticker == "PETR4.SA"
    assert report.trading_days == len(sample_daily_ohlcv) - (15 - 1)
    assert report.total_trades > 0

    # Net return must be strictly less than gross return when trades occur
    assert report.net_return_pct < report.gross_return_pct
    assert report.total_friction_cost_pct > 0.0

    # Formatted summary text checks
    summary_text = report.summary()
    assert "COMPARATIVO QUANTITATIVO DE ESTRATÉGIA: PETR4.SA" in summary_text
    assert "Retorno Líquido (com B3):" in summary_text
    assert "Retorno Bruto (sem taxas):" in summary_text
    assert "Retorno Buy & Hold:" in summary_text
    assert "Custo Total B3 Pago (0.03%):" in summary_text


def test_ac13_runner_slices_warmup_period(sample_daily_ohlcv: pd.DataFrame) -> None:
    """Verifies AC13: Truncation of warm-up rows guaranteeing aligned Strategy and Benchmark windows."""
    slow_p = 21
    strategy = EMACrossoverStrategy(fast_period=9, slow_period=slow_p)

    result_net, report = StrategyBacktestRunner.run(
        sample_daily_ohlcv, strategy, ticker="ITUB4.SA"
    )

    expected_len = len(sample_daily_ohlcv) - (slow_p - 1)
    assert len(result_net.equity_curve) == expected_len
    assert report.trading_days == expected_len

    # Sliced index must start exactly at index slow_p - 1 of original series
    expected_start_date = sample_daily_ohlcv.index[slow_p - 1]
    assert result_net.equity_curve.index[0] == expected_start_date


def test_runner_insufficient_data_raises_error(
    sample_daily_ohlcv: pd.DataFrame,
) -> None:
    """Verifies that running backtest with fewer rows than slow window raises InsufficientDataError."""
    short_df = sample_daily_ohlcv.iloc[:10]
    strategy = EMACrossoverStrategy(fast_period=5, slow_period=15)

    with pytest.raises(
        InsufficientDataError, match="insuficiente para o período lento"
    ):
        StrategyBacktestRunner.run(short_df, strategy, ticker="VALE3.SA")


def test_runner_with_generic_base_strategy(sample_daily_ohlcv: pd.DataFrame) -> None:
    """Verifies that running a generic BaseStrategy without slow_period defaults window to 1."""

    class AllLongStrategy(BaseStrategy):
        def generate_signals(self, ohlcv_df: pd.DataFrame) -> pd.Series:
            return pd.Series(1.0, index=ohlcv_df.index, name="Signal")

    strategy = AllLongStrategy()
    result, report = StrategyBacktestRunner.run(
        sample_daily_ohlcv, strategy, ticker="GENERIC"
    )

    assert report.trading_days == len(sample_daily_ohlcv)
    assert len(result.equity_curve) == len(sample_daily_ohlcv)

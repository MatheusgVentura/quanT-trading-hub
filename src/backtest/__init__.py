"""Módulo de backtesting quantitativo e cálculo de métricas de risco e retorno."""

from src.backtest.engine import VectorizedBacktestEngine
from src.backtest.exceptions import (
    BacktestError,
    InvalidSignalError,
    MismatchedIndexError,
)
from src.backtest.metrics import MetricsCalculator
from src.backtest.models import BacktestConfig, BacktestMetrics, BacktestResult

__all__ = [
    "VectorizedBacktestEngine",
    "BacktestConfig",
    "BacktestMetrics",
    "BacktestResult",
    "MetricsCalculator",
    "BacktestError",
    "InvalidSignalError",
    "MismatchedIndexError",
]

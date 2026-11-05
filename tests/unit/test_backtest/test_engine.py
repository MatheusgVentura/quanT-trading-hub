"""Testes unitários para a engine de backtest vetorizada."""

import pytest
import pandas as pd
import numpy as np

from src.backtest.engine import VectorizedBacktestEngine
from src.backtest.models import BacktestConfig
from src.backtest.exceptions import (
    BacktestError,
    MismatchedIndexError,
    InvalidSignalError,
)


@pytest.fixture
def sample_ohlcv_series():
    """Gera série de preços previsível para validação de fórmulas."""
    dates = pd.date_range("2024-01-01", periods=5, freq="D")
    df = pd.DataFrame(
        {
            "Open": [10.0, 10.0, 12.0, 15.0, 15.0],
            "High": [10.5, 12.5, 15.5, 16.0, 15.5],
            "Low": [9.5, 9.8, 11.8, 14.8, 14.5],
            "Close": [10.0, 12.0, 15.0, 15.0, 12.0],  # +0%, +20%, +25%, +0%, -20%
            "Volume": [1000] * 5,
        },
        index=dates,
    )
    return df


def test_look_ahead_bias_protection(sample_ohlcv_series):
    """Testa se o sinal emitido em t só pontua retorno em t+1 (shift 1)."""
    dates = sample_ohlcv_series.index
    # Sinal de compra emitido no dia 0 (Close 10.0)
    # No dia 1 o ativo sobe para 12.0 (+20%). O sinal no dia 1 vira 0 (vende).
    # No dia 2 o ativo sobe para 15.0 (+25%).
    signals = pd.Series([1, 0, 0, 0, 0], index=dates)

    # Config com taxa zero para inspecionar retornos puros
    engine = VectorizedBacktestEngine(config=BacktestConfig(b3_fee_pct=0.0))
    result = engine.run(sample_ohlcv_series, signals, ticker="TEST4.SA")

    eq = result.equity_curve
    # No dia 0: posição deve ser 0 (pois o sinal foi gerado no fechamento de 0)
    assert eq.loc[dates[0], "Posicao"] == 0.0
    assert eq.loc[dates[0], "Retorno_Estrategia"] == 0.0

    # No dia 1: posição é 1.0 (captura a alta de +20% do dia 1)
    assert eq.loc[dates[1], "Posicao"] == 1.0
    assert pytest.approx(eq.loc[dates[1], "Retorno_Estrategia"], 0.001) == 0.20

    # No dia 2: posição volta a 0.0 (pois o sinal no dia 1 foi 0)
    # NÃO captura a alta de +25% do dia 2!
    assert eq.loc[dates[2], "Posicao"] == 0.0
    assert eq.loc[dates[2], "Retorno_Estrategia"] == 0.0


def test_b3_costs_deducted_strictly_on_position_changes(sample_ohlcv_series):
    """Valida se as taxas da B3 são debitadas somente quando há transição de posição."""
    dates = sample_ohlcv_series.index
    # Dia 0: Sinal 1 -> Gera transição em t+1 (0 -> 1)
    # Dia 1: Sinal 1 -> Mantém posição em t+2 (1 -> 1, sem giro)
    # Dia 2: Sinal 0 -> Gera transição em t+3 (1 -> 0, saída)
    signals = pd.Series([1, 1, 0, 0, 0], index=dates)

    fee = 0.0003  # 0.03%
    engine = VectorizedBacktestEngine(config=BacktestConfig(b3_fee_pct=fee, brokerage_fee=0.0))
    result = engine.run(sample_ohlcv_series, signals, ticker="TEST4.SA")

    eq = result.equity_curve
    # Dia 1: Entrada -> Paga 0.0003
    assert pytest.approx(eq.loc[dates[1], "Custos"], 1e-6) == fee
    # Dia 2: Mantém posição -> Custo ZERO
    assert eq.loc[dates[2], "Custos"] == 0.0
    # Dia 3: Encerra posição -> Paga 0.0003
    assert pytest.approx(eq.loc[dates[3], "Custos"], 1e-6) == fee

    assert result.metrics.total_trades == 2


def test_all_cash_strategy(sample_ohlcv_series):
    """Valida que sinal sempre neutro (0) resulta em retorno zero e zero trades."""
    dates = sample_ohlcv_series.index
    signals = pd.Series([0, 0, 0, 0, 0], index=dates)

    engine = VectorizedBacktestEngine()
    result = engine.run(sample_ohlcv_series, signals, ticker="TEST4.SA")

    assert result.metrics.total_return_pct == 0.0
    assert result.metrics.total_trades == 0
    assert result.metrics.max_drawdown_pct == 0.0


def test_mismatched_index_raises_error(sample_ohlcv_series):
    """Valida que índices temporais incompatíveis levantam MismatchedIndexError."""
    other_dates = pd.date_range("2025-01-01", periods=5, freq="D")
    signals = pd.Series([1, 1, 1, 1, 1], index=other_dates)

    engine = VectorizedBacktestEngine()
    with pytest.raises(MismatchedIndexError, match="não estão estritamente alinhados"):
        engine.run(sample_ohlcv_series, signals, ticker="TEST4.SA")


def test_invalid_signal_values_raises_error(sample_ohlcv_series):
    """Valida que valores de sinais fora de [-1, 1] levantam InvalidSignalError."""
    dates = sample_ohlcv_series.index
    signals = pd.Series([1, 2.5, 0, 0, 0], index=dates)  # 2.5 é inválido

    engine = VectorizedBacktestEngine()
    with pytest.raises(InvalidSignalError, match="Valores de sinal inválidos"):
        engine.run(sample_ohlcv_series, signals, ticker="TEST4.SA")


def test_empty_ohlcv_raises_backtest_error():
    """Valida que DataFrame vazio levanta BacktestError."""
    engine = VectorizedBacktestEngine()
    with pytest.raises(BacktestError, match="DataFrame OHLCV vazio"):
        engine.run(pd.DataFrame(), pd.Series(), ticker="EMPTY")

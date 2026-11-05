"""Testes unitários para o OHLCVValidator."""

import pytest
import pandas as pd
import numpy as np
from src.data.validator import OHLCVValidator
from src.data.exceptions import DataValidationError


@pytest.fixture
def sample_valid_ohlcv_df():
    """Gera um DataFrame OHLCV sintético válido para testes."""
    dates = pd.date_range("2024-01-01", periods=5, freq="D")
    data = {
        "Open": [10.0, 10.5, 11.0, 10.8, 11.2],
        "High": [10.8, 11.2, 11.5, 11.4, 11.9],
        "Low": [9.8, 10.2, 10.7, 10.5, 11.0],
        "Close": [10.5, 11.0, 10.9, 11.2, 11.8],
        "Volume": [1000, 1500, 2000, 1200, 1800],
    }
    return pd.DataFrame(data, index=dates)


def test_validator_success(sample_valid_ohlcv_df):
    """Testa validação e sanitização bem-sucedida."""
    result = OHLCVValidator.validate_and_clean(sample_valid_ohlcv_df, ticker="TEST4.SA")
    assert list(result.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(result) == 5
    assert isinstance(result.index, pd.DatetimeIndex)


def test_validator_multiindex_flattening(sample_valid_ohlcv_df):
    """Testa suporte a MultiIndex retornado pelo yfinance."""
    # Simula colunas MultiIndex: [('Open', 'ITUB4.SA'), ...]
    multi_cols = pd.MultiIndex.from_tuples(
        [(col, "ITUB4.SA") for col in sample_valid_ohlcv_df.columns],
        names=["Price", "Ticker"],
    )
    multi_df = sample_valid_ohlcv_df.copy()
    multi_df.columns = multi_cols

    result = OHLCVValidator.validate_and_clean(multi_df, ticker="ITUB4.SA")
    assert list(result.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert not isinstance(result.columns, pd.MultiIndex)


def test_validator_empty_df_raises():
    """Testa se DataFrame vazio levanta DataValidationError."""
    with pytest.raises(DataValidationError, match="vazio ou nulo"):
        OHLCVValidator.validate_and_clean(pd.DataFrame(), ticker="EMPTY")


def test_validator_missing_column(sample_valid_ohlcv_df):
    """Testa se ausência de coluna obrigatória levanta DataValidationError."""
    df_missing = sample_valid_ohlcv_df.drop(columns=["Volume"])
    with pytest.raises(DataValidationError, match="Colunas obrigatórias ausentes"):
        OHLCVValidator.validate_and_clean(df_missing, ticker="TEST4.SA")


def test_validator_high_lower_than_low(sample_valid_ohlcv_df):
    """Testa detecção de anomalia física High < Low."""
    corrupted = sample_valid_ohlcv_df.copy()
    corrupted.iloc[0, corrupted.columns.get_loc("High")] = 8.0  # Menor que Low (9.8)
    with pytest.raises(DataValidationError, match="Violação de integridade High < Low"):
        OHLCVValidator.validate_and_clean(corrupted, ticker="TEST4.SA")


def test_validator_negative_or_zero_price(sample_valid_ohlcv_df):
    """Testa detecção de preços menores ou iguais a zero."""
    corrupted = sample_valid_ohlcv_df.copy()
    corrupted.iloc[0, corrupted.columns.get_loc("Close")] = 0.0
    with pytest.raises(DataValidationError, match="Preços menores ou iguais a zero"):
        OHLCVValidator.validate_and_clean(corrupted, ticker="TEST4.SA")


def test_validator_negative_volume(sample_valid_ohlcv_df):
    """Testa detecção de volume negativo."""
    corrupted = sample_valid_ohlcv_df.copy()
    corrupted.iloc[0, corrupted.columns.get_loc("Volume")] = -100
    with pytest.raises(DataValidationError, match="Volume negativo"):
        OHLCVValidator.validate_and_clean(corrupted, ticker="TEST4.SA")


def test_validator_high_lower_than_close(sample_valid_ohlcv_df):
    """Testa se High menor que Close levanta DataValidationError."""
    corrupted = sample_valid_ohlcv_df.copy()
    corrupted.iloc[0, corrupted.columns.get_loc("Close")] = 11.5
    corrupted.iloc[0, corrupted.columns.get_loc("High")] = 10.8
    with pytest.raises(DataValidationError, match="Violação de integridade High menor que Open/Close"):
        OHLCVValidator.validate_and_clean(corrupted, ticker="TEST4.SA")


"""Testes unitários para o YFinanceDataProvider utilizando mocks."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.data.cache import DataCacheManager
from src.data.exceptions import DataDownloadError, TickerNotFoundError
from src.data.yfinance_provider import YFinanceDataProvider


@pytest.fixture
def sample_raw_yf_df() -> pd.DataFrame:
    """Gera DataFrame no formato típico do yfinance."""
    dates = pd.date_range("2024-01-01", periods=3, freq="D")
    return pd.DataFrame(
        {
            "Open": [20.0, 20.5, 21.0],
            "High": [20.8, 21.2, 21.5],
            "Low": [19.8, 20.2, 20.7],
            "Close": [20.5, 21.0, 20.9],
            "Volume": [10000, 15000, 20000],
        },
        index=dates,
    )


@patch("yfinance.download")
def test_fetch_ohlcv_success(
    mock_download: MagicMock, sample_raw_yf_df: pd.DataFrame
) -> None:
    """Testa busca com sucesso de dados do yfinance."""
    mock_download.return_value = sample_raw_yf_df
    provider = YFinanceDataProvider()

    df = provider.fetch_ohlcv(ticker="ITUB4.SA", period="1y")

    assert not df.empty
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert mock_download.called
    assert mock_download.call_args[1]["tickers"] == "ITUB4.SA"


@patch("yfinance.download")
def test_fetch_ohlcv_ticker_not_found(mock_download: MagicMock) -> None:
    """Testa erro quando ticker não retorna dados."""
    mock_download.return_value = pd.DataFrame()
    provider = YFinanceDataProvider()

    with pytest.raises(TickerNotFoundError, match="Nenhum dado retornado"):
        provider.fetch_ohlcv(ticker="INVALID.SA")


@patch("yfinance.download")
def test_fetch_ohlcv_network_failure(mock_download: MagicMock) -> None:
    """Testa erro de rede empacotado em DataDownloadError."""
    mock_download.side_effect = ConnectionError("Timeout de conexão")
    provider = YFinanceDataProvider()

    with pytest.raises(DataDownloadError, match="Falha de rede"):
        provider.fetch_ohlcv(ticker="PETR4.SA")


@patch("yfinance.download")
def test_fetch_ohlcv_cache_hit_avoids_api_call(
    mock_download: MagicMock, tmp_path: Path, sample_raw_yf_df: pd.DataFrame
) -> None:
    """Testa se cache hit previne chamada externa."""
    cache = DataCacheManager(cache_dir=str(tmp_path))
    provider = YFinanceDataProvider(cache_manager=cache)

    mock_download.return_value = sample_raw_yf_df

    # Primeira chamada: executa download e popula cache
    df1 = provider.fetch_ohlcv(ticker="WEGE3.SA", period="1y")
    assert mock_download.call_count == 1

    # Segunda chamada: deve vir do cache sem chamar yf.download novamente
    df2 = provider.fetch_ohlcv(ticker="WEGE3.SA", period="1y")
    assert mock_download.call_count == 1
    assert len(df1) == len(df2)

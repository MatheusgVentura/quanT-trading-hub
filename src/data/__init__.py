"""Módulo de ingestão, sanitização e cache de dados de mercado."""

from src.data.cache import DataCacheManager
from src.data.exceptions import (
    DataDownloadError,
    DataError,
    DataValidationError,
    TickerNotFoundError,
)
from src.data.interfaces import IDataProvider
from src.data.validator import OHLCVValidator
from src.data.yfinance_provider import YFinanceDataProvider

__all__ = [
    "DataCacheManager",
    "DataDownloadError",
    "DataError",
    "DataValidationError",
    "IDataProvider",
    "OHLCVValidator",
    "TickerNotFoundError",
    "YFinanceDataProvider",
]

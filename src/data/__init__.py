"""Módulo de ingestão, sanitização e cache de dados de mercado."""

from src.data.cache import DataCacheManager
from src.data.exceptions import (
    DataError,
    DataDownloadError,
    DataValidationError,
    TickerNotFoundError,
)
from src.data.interfaces import IDataProvider
from src.data.validator import OHLCVValidator
from src.data.yfinance_provider import YFinanceDataProvider

__all__ = [
    "IDataProvider",
    "YFinanceDataProvider",
    "OHLCVValidator",
    "DataCacheManager",
    "DataError",
    "DataDownloadError",
    "DataValidationError",
    "TickerNotFoundError",
]


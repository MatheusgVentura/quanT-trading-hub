"""Provedor concreto de dados de mercado utilizando a biblioteca yfinance."""

from typing import Optional
import pandas as pd
import yfinance as yf

from src.data.cache import DataCacheManager
from src.data.exceptions import DataDownloadError, TickerNotFoundError
from src.data.interfaces import IDataProvider
from src.data.validator import OHLCVValidator


class YFinanceDataProvider(IDataProvider):
    """Provedor de dados de mercado baseado na API do Yahoo Finance."""

    def __init__(self, cache_manager: Optional[DataCacheManager] = None):
        """Inicializa o provedor.

        Args:
            cache_manager: Gerenciador de cache local opcional para evitar requisições repetidas.
        """
        self.cache_manager = cache_manager

    def fetch_ohlcv(
        self,
        ticker: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        period: Optional[str] = "1y",
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Recupera dados OHLCV históricos sanitizados e validados.

        Args:
            ticker: Símbolo do ativo (ex: 'ITUB4.SA', 'VALE3.SA').
            start_date: Data inicial 'YYYY-MM-DD' (opcional).
            end_date: Data final 'YYYY-MM-DD' (opcional).
            period: Período caso start_date não seja definido (padrão '1y').
            interval: Frequência dos candles (padrão '1d').

        Returns:
            pd.DataFrame padronizado contendo DatetimeIndex e colunas OHLCV.

        Raises:
            TickerNotFoundError: Se nenhum registro for encontrado para o ticker.
            DataValidationError: Se os dados retornados violarem regras de integridade física.
            DataDownloadError: Se houver erro de rede ou comunicação com a API.
        """
        cache_key = ""
        if self.cache_manager is not None:
            cache_key = self.cache_manager.generate_key(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                period=period,
                interval=interval,
            )
            cached_df = self.cache_manager.get(cache_key)
            if cached_df is not None and not cached_df.empty:
                return cached_df

        try:
            if start_date:
                raw_df = yf.download(
                    tickers=ticker,
                    start=start_date,
                    end=end_date,
                    interval=interval,
                    progress=False,
                    auto_adjust=False,
                )
            else:
                raw_df = yf.download(
                    tickers=ticker,
                    period=period,
                    interval=interval,
                    progress=False,
                    auto_adjust=False,
                )
        except Exception as exc:
            raise DataDownloadError(f"Falha de rede ao baixar dados para '{ticker}': {exc}") from exc

        if raw_df is None or raw_df.empty:
            raise TickerNotFoundError(
                f"Nenhum dado retornado para o ativo '{ticker}'. "
                f"Verifique se o sufixo '.SA' foi informado para ativos da B3."
            )

        validated_df = OHLCVValidator.validate_and_clean(raw_df, ticker=ticker)

        if self.cache_manager is not None and cache_key:
            self.cache_manager.set(cache_key, validated_df)

        return validated_df


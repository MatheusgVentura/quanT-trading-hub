"""Interfaces e contratos para provedores de dados de mercado."""

from abc import ABC, abstractmethod
from typing import Optional
import pandas as pd


class IDataProvider(ABC):
    """Interface abstrata para provedores de dados de mercado (OHLCV)."""

    @abstractmethod
    def fetch_ohlcv(
        self,
        ticker: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        period: Optional[str] = "1y",
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Recupera série temporal OHLCV padronizada e validada.

        Args:
            ticker: Símbolo do ativo (ex: 'ITUB4.SA', 'PETR4.SA').
            start_date: Data inicial no formato 'YYYY-MM-DD' (opcional).
            end_date: Data final no formato 'YYYY-MM-DD' (opcional).
            period: Janela temporal (ex: '1mo', '1y', '3y', 'max') caso start_date não seja informado.
            interval: Frequência dos candles (ex: '1d', '1h', '5m').

        Returns:
            pd.DataFrame com índice DatetimeIndex ordenado cronologicamente e colunas
            estritamente tipadas: ['Open', 'High', 'Low', 'Close', 'Volume'].

        Raises:
            TickerNotFoundError: Se nenhum dado for retornado para o ativo.
            DataValidationError: Se os dados violarem regras de integridade.
            DataDownloadError: Se houver falha de rede/serviço.
        """
        pass


"""Contrato base abstrato para estratégias quantitativas."""

from abc import ABC, abstractmethod

import pandas as pd


class BaseStrategy(ABC):
    """Classe base abstrata para estratégias puras e sem estado."""

    @abstractmethod
    def generate_signals(self, ohlcv_df: pd.DataFrame) -> pd.Series:
        """Transforma uma série histórica OHLCV em sinais binários de trading.

        Args:
            ohlcv_df: DataFrame contendo dados OHLCV padronizados com DatetimeIndex.

        Returns:
            pd.Series contendo sinais {0, 1} alinhados estritamente ao índice do DataFrame.

        Raises:
            StrategyError: Se os dados de entrada forem vazios ou faltar coluna obrigatória.
            InsufficientDataError: Se o número de candles for inferior à janela exigida.
        """

"""Estratégia quantitativa de cruzamento de médias móveis exponenciais (EMA)."""

import numpy as np
import pandas as pd

from src.strategies.base import BaseStrategy
from src.strategies.exceptions import (
    InsufficientDataError,
    InvalidParameterError,
    StrategyError,
)


class EMACrossoverStrategy(BaseStrategy):
    """Estratégia de cruzamento de duas EMAs gerando sinais binários {0, 1}."""

    def __init__(self, fast_period: int = 9, slow_period: int = 21) -> None:
        """Inicializa e valida os períodos da média rápida e lenta.

        Args:
            fast_period: Período da média móvel exponencial rápida (mínimo: 2).
            slow_period: Período da média móvel exponencial lenta (deve ser estritamente maior que fast_period).

        Raises:
            InvalidParameterError: Se fast_period < 2, slow_period <= fast_period ou se não forem inteiros.
        """
        if type(fast_period) is not int or type(slow_period) is not int:
            raise InvalidParameterError(
                "Os períodos da EMA devem ser números inteiros."
            )

        if fast_period < 2:
            raise InvalidParameterError(
                f"Período rápido inválido ({fast_period}). O período rápido deve ser >= 2."
            )

        if slow_period <= fast_period:
            raise InvalidParameterError(
                f"Período lento ({slow_period}) deve ser estritamente maior que o período rápido ({fast_period})."
            )

        self.fast_period = fast_period
        self.slow_period = slow_period

    def generate_signals(self, ohlcv_df: pd.DataFrame) -> pd.Series:
        """Gera sinais discretos {0, 1} com base no cruzamento das EMAs.

        Args:
            ohlcv_df: DataFrame contendo dados de mercado com DatetimeIndex e coluna 'Close'.

        Returns:
            pd.Series com valores em {0.0, 1.0} e nome 'Signal', alinhada ao índice de ohlcv_df.

        Raises:
            StrategyError: Se o DataFrame for vazio ou não contiver a coluna 'Close'.
            InsufficientDataError: Se o DataFrame contiver menos linhas que o período lento.
        """
        if ohlcv_df is None or ohlcv_df.empty:
            raise StrategyError("DataFrame OHLCV vazio ou nulo.")

        if "Close" not in ohlcv_df.columns:
            raise StrategyError("Coluna obrigatória 'Close' ausente no DataFrame.")

        if len(ohlcv_df) < self.slow_period:
            raise InsufficientDataError(
                f"Série temporal possui {len(ohlcv_df)} candles, inferior ao período lento de {self.slow_period}."
            )

        close = ohlcv_df["Close"].astype(float)

        # Cálculo das EMAs com min_periods=slow_period para forçar NaN durante aquecimento
        ema_fast = close.ewm(
            span=self.fast_period, min_periods=self.slow_period, adjust=False
        ).mean()
        ema_slow = close.ewm(
            span=self.slow_period, min_periods=self.slow_period, adjust=False
        ).mean()

        # Condição de compra: EMA rápida estritamente maior que a lenta e ambas válidas
        condition = (ema_fast > ema_slow) & (~ema_fast.isna()) & (~ema_slow.isna())
        signals = np.where(condition, 1.0, 0.0)

        return pd.Series(signals, index=ohlcv_df.index, name="Signal", dtype=float)

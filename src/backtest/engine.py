"""Motor de simulação de backtesting vetorizado."""

from typing import Optional
import numpy as np
import pandas as pd

from src.backtest.exceptions import (
    BacktestError,
    InvalidSignalError,
    MismatchedIndexError,
)
from src.backtest.metrics import MetricsCalculator
from src.backtest.models import BacktestConfig, BacktestResult


class VectorizedBacktestEngine:
    """Motor de execução de backtests vetorizados com custos B3 e proteção contra vieses."""

    def __init__(self, config: Optional[BacktestConfig] = None):
        """Inicializa o motor com configurações de fricção e parâmetros de mercado.

        Args:
            config: Configurações do backtest. Se None, utiliza valores padrão da B3.
        """
        self.config = config or BacktestConfig()

    def run(
        self,
        ohlcv_df: pd.DataFrame,
        signals: pd.Series,
        ticker: str = "ATIVO",
    ) -> BacktestResult:
        """Executa a simulação quantitativa vetorizada.

        Args:
            ohlcv_df: DataFrame contendo ao menos a coluna 'Close' com DatetimeIndex.
            signals: Série temporal de sinais (-1 = vendido, 0 = neutro/caixa, 1 = comprado).
            ticker: Símbolo do ativo sendo simulado.

        Returns:
            BacktestResult com métricas calculadas e curvas de evolução patrimonial.

        Raises:
            BacktestError: Se os dados de entrada forem vazios ou inválidos.
            MismatchedIndexError: Se as datas do OHLCV e dos sinais não forem idênticas.
            InvalidSignalError: Se os sinais contiverem valores fora da faixa [-1, 1].
        """
        if ohlcv_df is None or ohlcv_df.empty:
            raise BacktestError(f"DataFrame OHLCV vazio ou nulo para '{ticker}'.")

        if signals is None or signals.empty:
            raise BacktestError(f"Série de sinais vazia ou nula para '{ticker}'.")

        if "Close" not in ohlcv_df.columns:
            raise BacktestError(f"Coluna 'Close' obrigatória ausente no DataFrame OHLCV de '{ticker}'.")

        # 1. Validação de alinhamento temporal
        if not ohlcv_df.index.equals(signals.index):
            raise MismatchedIndexError(
                f"O índice de datas do OHLCV ({len(ohlcv_df)}) e dos sinais ({len(signals)}) "
                f"não estão estritamente alinhados para '{ticker}'."
            )

        # 2. Validação de domínio dos sinais
        clean_signals = signals.astype(float).fillna(0.0)
        if (clean_signals < -1.0).any() or (clean_signals > 1.0).any():
            invalid_vals = clean_signals[(clean_signals < -1.0) | (clean_signals > 1.0)].unique()
            raise InvalidSignalError(
                f"Valores de sinal inválidos detectados para '{ticker}': {invalid_vals}. "
                f"Os sinais devem estar no intervalo [-1.0, 1.0]."
            )

        # 3. Retornos do Benchmark (Buy & Hold)
        benchmark_returns = ohlcv_df["Close"].pct_change().fillna(0.0)

        # 4. Proteção mandatória contra Look-Ahead Bias:
        # A decisão tomada no fechamento de t só pode ser executada em t+1
        position = clean_signals.shift(1).fillna(0.0)

        # 5. Identificação de transições de posição e cálculo de fricção
        # diff() detecta alterações: 0 -> 1 (+1), 1 -> 0 (-1), etc.
        position_changes = position.diff().abs().fillna(0.0)

        # Fricção percentual total por giro (taxas B3 + slippage + corretagem proporcional)
        fee_pct = self.config.b3_fee_pct + self.config.slippage_pct
        if self.config.initial_capital > 0 and self.config.brokerage_fee > 0:
            fee_pct += self.config.brokerage_fee / self.config.initial_capital

        costs = position_changes * fee_pct

        # 6. Retornos líquidos da estratégia
        strategy_returns = (position * benchmark_returns) - costs

        # 7. Evolução patrimonial acumulada (Base 1.0)
        curva_estrategia = (1.0 + strategy_returns).cumprod()
        curva_benchmark = (1.0 + benchmark_returns).cumprod()

        # 8. Drawdown Subaquático
        pico = curva_estrategia.cummax()
        drawdown = (curva_estrategia - pico) / pico

        # 9. Consolidação do DataFrame de Curva de Capital
        equity_df = pd.DataFrame(
            {
                "Curva_Estrategia": curva_estrategia,
                "Curva_Benchmark": curva_benchmark,
                "Drawdown": drawdown,
                "Posicao": position,
                "Sinal": clean_signals,
                "Retorno_Estrategia": strategy_returns,
                "Retorno_Benchmark": benchmark_returns,
                "Custos": costs,
            },
            index=ohlcv_df.index,
        )

        # 10. Cálculo de Métricas Quantitativas
        metrics = MetricsCalculator.calculate_metrics(
            equity_curve=curva_estrategia,
            strategy_returns=strategy_returns,
            benchmark_returns=benchmark_returns,
            position_changes=position_changes,
            config=self.config,
        )

        return BacktestResult(
            ticker=ticker,
            config=self.config,
            metrics=metrics,
            equity_curve=equity_df,
        )

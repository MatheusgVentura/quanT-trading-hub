"""Executor e orquestrador de backtests comparativos para estratégias quantitativas."""

from dataclasses import dataclass

import pandas as pd

from src.backtest.engine import VectorizedBacktestEngine
from src.backtest.models import BacktestConfig, BacktestResult
from src.strategies.base import BaseStrategy
from src.strategies.ema_crossover import EMACrossoverStrategy
from src.strategies.exceptions import InsufficientDataError


@dataclass(frozen=True)
class StrategyComparisonReport:
    """Relatório estruturado comparando performance líquida (com B3) vs bruta (sem taxas)."""

    ticker: str
    net_return_pct: float
    gross_return_pct: float
    benchmark_return_pct: float
    total_trades: int
    total_friction_cost_pct: float
    cagr_net_pct: float
    max_drawdown_pct: float
    profit_factor: float
    win_rate_pct: float
    trading_days: int

    def summary(self) -> str:
        """Gera texto institucional formatado com a comparação."""
        lines = [
            "=" * 65,
            f"      COMPARATIVO QUANTITATIVO DE ESTRATÉGIA: {self.ticker}",
            "=" * 65,
            f"Pregões Avaliados:          {self.trading_days}",
            f"Retorno Líquido (com B3):   {self.net_return_pct:+.2f}%",
            f"Retorno Bruto (sem taxas):  {self.gross_return_pct:+.2f}%",
            f"Retorno Buy & Hold:         {self.benchmark_return_pct:+.2f}%",
            "-" * 65,
            f"Total de Transações:        {self.total_trades}",
            f"Custo Total B3 Pago (0.03%): {self.total_friction_cost_pct:.2f}%",
            f"CAGR Líquido Anualizado:    {self.cagr_net_pct:+.2f}% ao ano",
            f"Max Drawdown (Pior Queda):  {self.max_drawdown_pct:.2f}%",
            f"Profit Factor Líquido:      {self.profit_factor:.2f}",
            f"Win Rate Líquido:           {self.win_rate_pct:.1f}%",
            "=" * 65,
        ]
        return "\n".join(lines)


class StrategyBacktestRunner:
    """Orquestra a execução da estratégia recortando aquecimento e comparando taxas."""

    @staticmethod
    def run(
        ohlcv_df: pd.DataFrame,
        strategy: BaseStrategy,
        ticker: str = "ATIVO",
        b3_fee_pct: float = 0.0003,
    ) -> tuple[BacktestResult, StrategyComparisonReport]:
        """Executa backtest comparativo (com e sem taxas) com recorte de aquecimento (AC13).

        Args:
            ohlcv_df: DataFrame com dados OHLCV completos.
            strategy: Instância da estratégia derivada de BaseStrategy.
            ticker: Símbolo do ativo.
            b3_fee_pct: Taxa da B3 por transação (padrão 0.03% = 0.0003).

        Returns:
            Tupla contendo (BacktestResult com taxas, StrategyComparisonReport consolidado).
        """
        # Determina ponto de início para recorte de warm-up (AC13)
        slow_window = (
            strategy.slow_period if isinstance(strategy, EMACrossoverStrategy) else 1
        )
        if len(ohlcv_df) < slow_window:
            raise InsufficientDataError(
                f"Série temporal possui {len(ohlcv_df)} candles, insuficiente para o período lento de {slow_window}."
            )

        # 1. Gera sinais brutos sobre toda a série histórica
        full_signals = strategy.generate_signals(ohlcv_df)

        # 2. Recorta o período a partir do primeiro candle com decisão calculada (AC13)
        start_idx = slow_window - 1
        sliced_ohlcv = ohlcv_df.iloc[start_idx:].copy()
        sliced_signals = full_signals.iloc[start_idx:].copy()

        # 3. Execução 1: Com taxas oficiais da B3 (Líquido)
        config_net = BacktestConfig(
            b3_fee_pct=b3_fee_pct, brokerage_fee=0.0, slippage_pct=0.0
        )
        engine_net = VectorizedBacktestEngine(config=config_net)
        result_net = engine_net.run(
            sliced_ohlcv, sliced_signals, ticker=f"{ticker} (Net)"
        )

        # 4. Execução 2: Sem taxas (Bruto)
        config_gross = BacktestConfig(
            b3_fee_pct=0.0, brokerage_fee=0.0, slippage_pct=0.0
        )
        engine_gross = VectorizedBacktestEngine(config=config_gross)
        result_gross = engine_gross.run(
            sliced_ohlcv, sliced_signals, ticker=f"{ticker} (Gross)"
        )

        # 5. Consolidação do Relatório Comparativo (AC04)
        m_net = result_net.metrics
        m_gross = result_gross.metrics
        total_friction_cost = float(result_net.equity_curve["Custos"].sum()) * 100.0

        report = StrategyComparisonReport(
            ticker=ticker,
            net_return_pct=m_net.total_return_pct,
            gross_return_pct=m_gross.total_return_pct,
            benchmark_return_pct=m_net.benchmark_return_pct,
            total_trades=m_net.total_trades,
            total_friction_cost_pct=round(total_friction_cost, 2),
            cagr_net_pct=m_net.cagr_pct,
            max_drawdown_pct=m_net.max_drawdown_pct,
            profit_factor=m_net.profit_factor,
            win_rate_pct=m_net.win_rate_pct,
            trading_days=m_net.trading_days,
        )

        return result_net, report

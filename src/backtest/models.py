"""Modelos de dados e configurações para o motor de backtest."""

from dataclasses import dataclass
import pandas as pd


@dataclass(frozen=True)
class BacktestConfig:
    """Configurações e parâmetros de mercado para a simulação do backtest."""

    initial_capital: float = 100.0
    b3_fee_pct: float = 0.0003  # 0.03% (emolumentos + liquidação B3)
    brokerage_fee: float = 0.0  # R$ 0.00 (corretagem zero XP via RLP)
    slippage_pct: float = 0.0  # Derrapagem percentual por transação
    risk_free_rate: float = 0.1075  # 10.75% a.a. (Taxa Selic/CDI referencial)
    trading_days_per_year: int = 252


@dataclass(frozen=True)
class BacktestMetrics:
    """Métricas estatísticas e quantitativas calculadas pelo backtest."""

    total_return_pct: float
    benchmark_return_pct: float
    cagr_pct: float
    annualized_volatility_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    profit_factor: float
    win_rate_pct: float
    total_trades: int
    trading_days: int


@dataclass
class BacktestResult:
    """Resultado consolidado do backtest contendo métricas e série temporal da simulação."""

    ticker: str
    config: BacktestConfig
    metrics: BacktestMetrics
    equity_curve: pd.DataFrame

    def summary(self) -> str:
        """Gera um relatório institucional formatado em texto."""
        m = self.metrics
        anos = m.trading_days / self.config.trading_days_per_year
        lines = [
            "=" * 60,
            f"          RELATÓRIO QUANTITATIVO DE PERFORMANCE: {self.ticker}",
            "=" * 60,
            f"Período Analisado:          {m.trading_days} pregões (~{anos:.1f} anos)",
            f"Capital Inicial:            R$ {self.config.initial_capital:.2f}",
            f"Patrimônio Final Estimado:  R$ {self.config.initial_capital * (1 + m.total_return_pct / 100):.2f}",
            "-" * 60,
            f"Retorno Total Estratégia:   {m.total_return_pct:+.2f}%",
            f"Retorno Total Buy & Hold:   {m.benchmark_return_pct:+.2f}%",
            f"CAGR (Retorno Anualizado):  {m.cagr_pct:+.2f}% ao ano",
            "-" * 60,
            f"Volatilidade Anualizada:    {m.annualized_volatility_pct:.2f}%",
            f"Sharpe Ratio (Rf={self.config.risk_free_rate*100:.1f}%):   {m.sharpe_ratio:.2f}",
            f"Sortino Ratio:              {m.sortino_ratio:.2f}",
            f"Max Drawdown (Pior Queda):  {m.max_drawdown_pct:.2f}%",
            "-" * 60,
            f"Profit Factor:              {m.profit_factor:.2f}",
            f"Win Rate:                   {m.win_rate_pct:.1f}%",
            f"Total de Transações (Giro): {m.total_trades}",
            "=" * 60,
        ]
        return "\n".join(lines)

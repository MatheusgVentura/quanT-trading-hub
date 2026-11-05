"""Cálculo puramente estatístico de métricas de risco e retorno."""

import numpy as np
import pandas as pd
from src.backtest.models import BacktestConfig, BacktestMetrics


class MetricsCalculator:
    """Calculadora vetorizada de métricas financeiras quantitativas."""

    @staticmethod
    def calculate_metrics(
        equity_curve: pd.Series,
        strategy_returns: pd.Series,
        benchmark_returns: pd.Series,
        position_changes: pd.Series,
        config: BacktestConfig,
    ) -> BacktestMetrics:
        """Computa métricas estatísticas da estratégia e do benchmark.

        Args:
            equity_curve: Série temporal do patrimônio acumulado da estratégia (base 1.0).
            strategy_returns: Série temporal dos retornos percentuais líquidos diários.
            benchmark_returns: Série temporal dos retornos do benchmark (Buy & Hold).
            position_changes: Série temporal de alterações absolutas de posição (giro).
            config: Configuração do backtest com taxas e parâmetros.

        Returns:
            BacktestMetrics com todas as métricas preenchidas.
        """
        trading_days = len(strategy_returns)
        if trading_days == 0:
            return BacktestMetrics(
                total_return_pct=0.0,
                benchmark_return_pct=0.0,
                cagr_pct=0.0,
                annualized_volatility_pct=0.0,
                sharpe_ratio=0.0,
                sortino_ratio=0.0,
                max_drawdown_pct=0.0,
                profit_factor=0.0,
                win_rate_pct=0.0,
                total_trades=0,
                trading_days=0,
            )

        years = trading_days / float(config.trading_days_per_year)
        final_equity = float(equity_curve.iloc[-1]) if len(equity_curve) > 0 else 1.0

        # 1. Retorno Total Acumulado
        total_return_pct = (final_equity - 1.0) * 100.0

        # Benchmark Acumulado
        benchmark_cum = (1.0 + benchmark_returns).cumprod()
        final_benchmark = float(benchmark_cum.iloc[-1]) if len(benchmark_cum) > 0 else 1.0
        benchmark_return_pct = (final_benchmark - 1.0) * 100.0

        # 2. CAGR (Compound Annual Growth Rate)
        if years > 0 and final_equity > 0:
            cagr_pct = ((final_equity ** (1.0 / years)) - 1.0) * 100.0
        elif final_equity <= 0:
            cagr_pct = -100.0
        else:
            cagr_pct = 0.0

        # 3. Volatilidade Anualizada
        daily_std = float(strategy_returns.std(ddof=1)) if len(strategy_returns) > 1 else 0.0
        if np.isnan(daily_std):
            daily_std = 0.0
        annualized_volatility_pct = daily_std * np.sqrt(config.trading_days_per_year) * 100.0

        # 4. Taxa livre de risco diária e Sharpe Ratio
        rf_daily = (1.0 + config.risk_free_rate) ** (1.0 / config.trading_days_per_year) - 1.0
        excess_returns = strategy_returns - rf_daily
        excess_mean = float(excess_returns.mean())

        if daily_std > 1e-9:
            sharpe_ratio = (excess_mean * np.sqrt(config.trading_days_per_year)) / daily_std
        else:
            sharpe_ratio = 0.0

        # 5. Sortino Ratio (Penaliza apenas downside deviation)
        negative_excess = excess_returns[excess_returns < 0]
        if len(negative_excess) > 0:
            downside_dev = float(np.sqrt(np.mean(negative_excess**2))) * np.sqrt(
                config.trading_days_per_year
            )
        else:
            downside_dev = 0.0

        if downside_dev > 1e-9:
            sortino_ratio = (excess_mean * config.trading_days_per_year) / downside_dev
        else:
            sortino_ratio = 0.0 if excess_mean <= 0 else 10.0

        # 6. Max Drawdown (Série Subaquática)
        peak = equity_curve.cummax()
        drawdown = (equity_curve - peak) / peak
        max_drawdown_pct = float(drawdown.min()) * 100.0
        if np.isnan(max_drawdown_pct):
            max_drawdown_pct = 0.0

        # 7. Profit Factor
        gains = float(strategy_returns[strategy_returns > 0].sum())
        losses = float(strategy_returns[strategy_returns < 0].abs().sum())

        if losses > 1e-9:
            profit_factor = gains / losses
        elif gains > 1e-9:
            profit_factor = 99.9  # Representa ganho infinito sem perdas
        else:
            profit_factor = 0.0

        # 8. Win Rate (Dias com retornos líquidos positivos)
        active_days = strategy_returns[strategy_returns != 0]
        if len(active_days) > 0:
            win_rate_pct = float((active_days > 0).sum() / len(active_days)) * 100.0
        else:
            win_rate_pct = 0.0

        # 9. Total Trades (Giro)
        total_trades = int(position_changes.sum())

        return BacktestMetrics(
            total_return_pct=round(total_return_pct, 2),
            benchmark_return_pct=round(benchmark_return_pct, 2),
            cagr_pct=round(cagr_pct, 2),
            annualized_volatility_pct=round(annualized_volatility_pct, 2),
            sharpe_ratio=round(sharpe_ratio, 2),
            sortino_ratio=round(sortino_ratio, 2),
            max_drawdown_pct=round(max_drawdown_pct, 2),
            profit_factor=round(profit_factor, 2),
            win_rate_pct=round(win_rate_pct, 2),
            total_trades=total_trades,
            trading_days=trading_days,
        )

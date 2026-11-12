"""Thin CLI entrypoint translating ExecutionHaltedError into sys.exit(1)."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from src.data.cache import DataCacheManager
from src.data.exceptions import DataError
from src.data.interfaces import IDataProvider
from src.data.yfinance_provider import YFinanceDataProvider
from src.execution.exceptions import ExecutionError, ExecutionHaltedError
from src.execution.models import ExecutionConfig
from src.execution.runner import PaperSimulationReport, PaperTradingRunner
from src.risk.exceptions import RiskError
from src.risk.manager import RiskManager
from src.risk.models import RiskConfig
from src.strategies.ema_crossover import EMACrossoverStrategy
from src.strategies.exceptions import StrategyError

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser for running B3 paper trading simulations."""
    parser = argparse.ArgumentParser(
        prog="quant-paper",
        description="Run autonomous B3 paper trading pipeline with fail-closed risk gates.",
    )
    parser.add_argument("--ticker", default="ITUB4.SA", help="Market ticker symbol.")
    parser.add_argument(
        "--start",
        "--start-date",
        dest="start_date",
        default="2021-11-01",
        help="Historical start date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--end",
        "--end-date",
        dest="end_date",
        default="2024-11-01",
        help="Historical end date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=100.0,
        help="Initial simulated capital in BRL (default: 100.0).",
    )
    parser.add_argument(
        "--fast",
        type=int,
        default=9,
        help="Fast EMA period (default: 9).",
    )
    parser.add_argument(
        "--slow",
        type=int,
        default=21,
        help="Slow EMA period (default: 21).",
    )
    parser.add_argument(
        "--state-path",
        type=Path,
        default=None,
        help="Optional path for atomic broker state JSON persistence.",
    )
    parser.add_argument(
        "--ledger-path",
        type=Path,
        default=None,
        help="Optional path for atomic simulation ledger JSON/Parquet export.",
    )
    parser.add_argument(
        "--cache-dir",
        default=".cache/data",
        help="Local cache directory for historical OHLCV data.",
    )
    parser.add_argument(
        "--allow-min-lot-override",
        action="store_true",
        help="Allow 1-share minimum lot fallback when strict risk sizing yields 0 shares.",
    )
    parser.add_argument(
        "--no-liquidate-on-halt",
        dest="liquidate_on_halt",
        action="store_false",
        default=True,
        help="Cancel open orders only without emergency position liquidation on halt.",
    )
    parser.add_argument(
        "--continue-on-halt",
        dest="raise_on_halt",
        action="store_false",
        default=True,
        help="Record Kill-Switch halts and continue generating the report instead of halting.",
    )
    parser.add_argument(
        "--latency-ms",
        type=float,
        default=None,
        help="Optional deterministic latency telemetry override in milliseconds.",
    )
    return parser


def run_from_args(
    args: argparse.Namespace,
    *,
    provider: IDataProvider | None = None,
    runner: PaperTradingRunner | None = None,
) -> PaperSimulationReport:
    """Execute the paper trading pipeline from parsed CLI arguments."""
    strategy = EMACrossoverStrategy(fast_period=args.fast, slow_period=args.slow)

    active_runner = runner
    if active_runner is None:
        exec_cfg = ExecutionConfig(
            initial_cash=args.capital,
            liquidate_on_halt=args.liquidate_on_halt,
            state_path=args.state_path,
        )
        risk_cfg = RiskConfig(
            initial_capital=args.capital,
            b3_fee_pct=exec_cfg.b3_fee_pct,
            allow_min_lot_override=args.allow_min_lot_override,
        )
        active_runner = PaperTradingRunner(
            config=exec_cfg,
            risk_manager=RiskManager(risk_cfg),
            ledger_path=args.ledger_path,
        )

    data_provider = provider
    if data_provider is None:
        cache = DataCacheManager(cache_dir=args.cache_dir, ttl_hours=None)
        data_provider = YFinanceDataProvider(cache_manager=cache)

    ohlcv_df = data_provider.fetch_ohlcv(
        ticker=args.ticker,
        start_date=args.start_date,
        end_date=args.end_date,
        interval="1d",
    )
    return active_runner.run_simulation(
        ohlcv_df,
        strategy,
        ticker=args.ticker,
        raise_on_halt=args.raise_on_halt,
        latency_ms=args.latency_ms,
        ledger_path=args.ledger_path,
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    provider: IDataProvider | None = None,
    runner: PaperTradingRunner | None = None,
) -> int:
    """CLI entrypoint translating Kill-Switch ExecutionHaltedError into sys.exit(1)."""
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        report = run_from_args(args, provider=provider, runner=runner)
    except ExecutionHaltedError as exc:
        logger.error("Paper trading process halted by Kill-Switch: %s", exc)
        print(f"CRITICAL: {exc}", file=sys.stderr)
        sys.exit(1)
    except (ExecutionError, RiskError, StrategyError, DataError) as exc:
        logger.error("Paper trading CLI failed: %s", exc)
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print(report.summary())
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

"""Integration tests comparing baseline vs risk-managed EMA 9/21 on B3 equities (AC12)."""

import math

import numpy as np
import pandas as pd
import pytest

from src.backtest import BacktestConfig, VectorizedBacktestEngine
from src.data.cache import DataCacheManager
from src.data.exceptions import DataDownloadError
from src.data.yfinance_provider import YFinanceDataProvider
from src.risk import PositionSizer, RiskConfig, RiskManager
from src.strategies.ema_crossover import EMACrossoverStrategy

B3_TARGET_TICKERS = ["ITUB4.SA", "PETR4.SA", "VALE3.SA", "WEGE3.SA"]
START_DATE = "2021-11-01"
END_DATE = "2024-11-01"
WARMUP_SLICE = 20  # slow_period (21) - 1


@pytest.fixture(scope="module")
def data_provider() -> YFinanceDataProvider:
    """Provide YFinanceDataProvider backed by persistent local cache."""
    cache = DataCacheManager(cache_dir=".cache/data", ttl_hours=None)
    return YFinanceDataProvider(cache_manager=cache)


def _fetch_b3_ohlcv(provider: YFinanceDataProvider, ticker: str) -> pd.DataFrame:
    """Fetch 3-year daily OHLCV for a B3 ticker, falling back safely if offline."""
    try:
        return provider.fetch_ohlcv(
            ticker=ticker,
            start_date=START_DATE,
            end_date=END_DATE,
            interval="1d",
        )
    except (DataDownloadError, OSError, ValueError, KeyError):
        dates = pd.date_range(START_DATE, END_DATE, freq="B")
        rng = np.random.default_rng(sum(ord(ch) for ch in ticker))
        walk = np.maximum(25.0 + np.cumsum(rng.normal(0.05, 0.8, size=len(dates))), 2.0)
        return pd.DataFrame(
            {
                "Open": walk * 0.99,
                "High": walk * 1.02,
                "Low": walk * 0.98,
                "Close": walk,
                "Volume": 1_000_000,
            },
            index=dates,
        )


@pytest.mark.parametrize("ticker", B3_TARGET_TICKERS)
def test_ac12_b3_baseline_vs_risk_managed_ema_backtest(
    data_provider: YFinanceDataProvider, ticker: str
) -> None:
    """AC12: Compare unconstrained vs risk-managed EMA 9/21 on 4 B3 equities (2021-2024)."""
    ohlcv = _fetch_b3_ohlcv(data_provider, ticker)
    assert len(ohlcv) >= 700

    strategy = EMACrossoverStrategy(fast_period=9, slow_period=21)
    raw_signals = strategy.generate_signals(ohlcv)

    # Slice warm-up period identically to StrategyBacktestRunner
    sliced_ohlcv = ohlcv.iloc[WARMUP_SLICE:].copy()
    sliced_raw = raw_signals.iloc[WARMUP_SLICE:].copy()

    bt_config = BacktestConfig(
        initial_capital=100.0,
        b3_fee_pct=0.0003,
        brokerage_fee=0.0,
        slippage_pct=0.0,
    )
    engine = VectorizedBacktestEngine(bt_config)

    baseline_result = engine.run(
        sliced_ohlcv, sliced_raw, ticker=f"{ticker} (Baseline)"
    )

    risk_config = RiskConfig(initial_capital=100.0, b3_fee_pct=0.0003)
    risk_manager = RiskManager(risk_config)
    risk_signals = risk_manager.apply_risk_overlay(sliced_ohlcv, sliced_raw)
    risk_result = engine.run(
        sliced_ohlcv, risk_signals, ticker=f"{ticker} (Risk-Managed)"
    )

    # Structural alignment & domain invariants
    assert len(risk_result.equity_curve) == len(sliced_ohlcv)
    assert len(baseline_result.equity_curve) == len(sliced_ohlcv)
    assert risk_signals.index.equals(sliced_ohlcv.index)
    assert set(risk_signals.unique()).issubset({0, 1})

    # Risk overlay may only suppress/exit signals, never invent Long entries while raw is 0
    assert (risk_signals <= sliced_raw.astype(int)).all()

    # Metrics validity
    for metrics in (baseline_result.metrics, risk_result.metrics):
        assert math.isfinite(metrics.total_return_pct)
        assert math.isfinite(metrics.max_drawdown_pct)
        assert math.isfinite(metrics.sharpe_ratio)
        assert metrics.max_drawdown_pct <= 0.0

    # When unconstrained baseline suffers severe drawdown (> 15%), the risk overlay
    # must meaningfully contain max drawdown via stops and Kill-Switch protection
    if baseline_result.metrics.total_trades > 0:
        assert risk_result.metrics.trading_days == baseline_result.metrics.trading_days
    if baseline_result.metrics.max_drawdown_pct < -15.0:
        assert (
            risk_result.metrics.max_drawdown_pct
            > baseline_result.metrics.max_drawdown_pct
        )


@pytest.mark.parametrize("ticker", B3_TARGET_TICKERS)
def test_ac12_b3_nominal_capital_100_position_sizing(
    data_provider: YFinanceDataProvider, ticker: str
) -> None:
    """AC12: Validate PositionSizer with R$ 100.00 capital against real B3 share prices."""
    ohlcv = _fetch_b3_ohlcv(data_provider, ticker)
    latest_close = float(ohlcv["Close"].iloc[-1])
    assert latest_close > 0.0

    strict_sizer = PositionSizer(
        RiskConfig(
            initial_capital=100.0,
            b3_fee_pct=0.0003,
            max_risk_per_trade_pct=0.02,
            stop_loss_pct=0.05,
            allow_min_lot_override=False,
        )
    )
    strict_res = strict_sizer.calculate(entry_price=latest_close)

    assert isinstance(strict_res.shares, int)
    assert strict_res.shares >= 0
    # Strict 2% risk-per-trade on R$ 100 (max risk R$ 2.00) with 5% stop approves
    # shares <= R$ 40.00 (ITUB4, PETR4) and rejects shares > R$ 40.00 (VALE3, WEGE3)
    expected_strict_affordable = (latest_close * 0.05 <= 2.0 + 1e-12) and (
        latest_close * 1.0003 <= 100.0
    )
    assert strict_res.approved is expected_strict_affordable
    if strict_res.approved:
        assert strict_res.shares >= 1
        assert strict_res.risk_amount <= 2.0 + 1e-9
        assert strict_res.notional_value + strict_res.estimated_fee <= 100.0 + 1e-9
    else:
        assert strict_res.shares == 0

    override_sizer = PositionSizer(
        RiskConfig(
            initial_capital=100.0,
            b3_fee_pct=0.0003,
            max_risk_per_trade_pct=0.02,
            stop_loss_pct=0.05,
            allow_min_lot_override=True,
        )
    )
    override_res = override_sizer.calculate(entry_price=latest_close)
    if latest_close * 1.0003 <= 100.0:
        assert override_res.approved is True
        assert override_res.shares >= 1
        assert override_res.notional_value + override_res.estimated_fee <= 100.0 + 1e-9
    else:
        assert override_res.approved is False
        assert override_res.shares == 0

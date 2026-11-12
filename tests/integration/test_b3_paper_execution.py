"""End-to-end integration tests for B3 fractional paper trading execution (AC10, AC11)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.data.cache import DataCacheManager
from src.data.exceptions import DataDownloadError
from src.data.yfinance_provider import YFinanceDataProvider
from src.execution import (
    ExecutionConfig,
    OrderRouter,
    OrderStatus,
    PaperSimulationReport,
    PaperTradingRunner,
    SimulatedPaperBroker,
)
from src.risk import RiskConfig, RiskManager
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
    """Fetch 3-year daily OHLCV for a B3 ticker with deterministic offline fallback."""
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
        walk = np.maximum(
            24.0 + np.cumsum(rng.normal(0.04, 0.75, size=len(dates))), 2.0
        )
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
def test_ac10_ac11_b3_paper_execution_end_to_end_and_state_reload(
    data_provider: YFinanceDataProvider, ticker: str, tmp_path: Path
) -> None:
    """AC10/AC11: Execute EMA 9/21 + RiskManager + OrderRouter + SimulatedPaperBroker on B3."""
    ohlcv = _fetch_b3_ohlcv(data_provider, ticker)
    assert len(ohlcv) >= 700

    state_file = tmp_path / f"{ticker.replace('.', '_')}_state.json"
    ledger_file = tmp_path / f"{ticker.replace('.', '_')}_ledger.json"

    exec_config = ExecutionConfig(
        initial_cash=100.0,
        b3_fee_pct=0.0003,
        brokerage_fee=0.0,
        slippage_pct=0.0,
        use_fractional_suffix=True,
        liquidate_on_halt=True,
        state_path=state_file,
    )
    risk_config = RiskConfig(
        initial_capital=100.0,
        b3_fee_pct=0.0003,
        max_risk_per_trade_pct=0.02,
        stop_loss_pct=0.05,
        trailing_stop_pct=0.05,
        allow_min_lot_override=True,
    )

    broker = SimulatedPaperBroker(exec_config)
    risk_manager = RiskManager(risk_config)
    router = OrderRouter(broker=broker, risk_manager=risk_manager, config=exec_config)
    runner = PaperTradingRunner(router=router, ledger_path=ledger_file)

    strategy = EMACrossoverStrategy(fast_period=9, slow_period=21)
    report = runner.run_simulation(ohlcv, strategy, ticker=ticker)

    assert isinstance(report, PaperSimulationReport)
    assert report.ticker == ticker
    assert report.initial_cash == pytest.approx(100.0)
    assert report.trading_days == len(ohlcv) - WARMUP_SLICE
    assert len(report.equity_curve) == len(ohlcv) - WARMUP_SLICE
    assert len(report.steps) == len(ohlcv) - WARMUP_SLICE

    # Spot-only integer lot and cash conservation invariants across every bar.
    curve = report.equity_curve
    assert (curve["Shares"] >= 0).all()
    assert (curve["Cash"] >= -1e-12).all()
    assert (curve["Equity"] >= 0.0).all()
    assert (curve["Drawdown"] <= 1e-12).all()
    assert math.isfinite(report.total_return_pct)
    assert math.isfinite(report.benchmark_return_pct)
    assert report.max_drawdown_pct <= 0.0

    last_close = float(ohlcv["Close"].iloc[-1])
    final_pos = report.final_account.positions.get(ticker)
    held_shares = final_pos.shares if final_pos is not None else 0
    assert report.final_cash + held_shares * last_close == pytest.approx(
        report.final_equity, abs=1e-6
    )

    # Verify B3 fractional 'F' routing and exact 0.03% fee accounting on every fill.
    expected_root = ticker[:-3].upper()
    assert report.total_fees_paid == pytest.approx(
        sum(rec.b3_fee_paid for rec in report.receipts), abs=1e-12
    )
    for rec in report.receipts:
        assert rec.ticker == ticker
        if rec.status == OrderStatus.FILLED:
            assert rec.fill_price is not None and rec.fill_price > 0.0
            assert rec.filled_shares == rec.requested_shares
            expected_symbol = (
                f"{expected_root}F"
                if rec.requested_shares % 100 != 0
                else expected_root
            )
            assert rec.execution_symbol == expected_symbol
            expected_fee = rec.filled_shares * rec.fill_price * 0.0003
            assert rec.b3_fee_paid == pytest.approx(expected_fee, abs=1e-12)

    # AC10: Reload persisted broker state and ledger JSON and verify exact identity.
    assert state_file.exists()
    assert ledger_file.exists()

    reloaded_broker = SimulatedPaperBroker(exec_config)
    reloaded_snap = reloaded_broker.get_account_snapshot(
        market_prices={ticker: last_close}
    )
    assert reloaded_snap.cash == pytest.approx(report.final_cash, abs=1e-12)
    assert reloaded_snap.equity == pytest.approx(report.final_equity, abs=1e-12)
    assert reloaded_snap.realized_pnl == pytest.approx(report.realized_pnl, abs=1e-12)
    assert reloaded_snap.total_fees_paid == pytest.approx(
        report.total_fees_paid, abs=1e-12
    )
    assert set(reloaded_snap.positions.keys()) == set(
        report.final_account.positions.keys()
    )
    for pos_ticker, expected_pos in report.final_account.positions.items():
        restored_pos = reloaded_snap.positions[pos_ticker]
        assert restored_pos.shares == expected_pos.shares
        assert restored_pos.avg_entry_price == pytest.approx(
            expected_pos.avg_entry_price, abs=1e-12
        )
        assert restored_pos.entry_date == expected_pos.entry_date

    if report.receipts:
        first_rec = report.receipts[0]
        assert (
            reloaded_broker.get_order_by_client_id(first_rec.client_order_id)
            == first_rec
        )

    ledger_payload = json.loads(ledger_file.read_text(encoding="utf-8"))
    assert ledger_payload["ticker"] == ticker
    assert ledger_payload["final_equity"] == pytest.approx(report.final_equity)
    assert len(ledger_payload["equity_curve"]) == report.trading_days


def test_ac10_ac11_b3_strict_sizing_and_multi_session_resumption(
    data_provider: YFinanceDataProvider, tmp_path: Path
) -> None:
    """AC10/AC11: Strict 2% risk-per-trade and seamless cross-restart paper resumption."""
    ohlcv = _fetch_b3_ohlcv(data_provider, "ITUB4.SA")
    state_file = tmp_path / "itub4_resume_state.json"

    exec_config = ExecutionConfig(
        initial_cash=100.0,
        b3_fee_pct=0.0003,
        use_fractional_suffix=True,
        liquidate_on_halt=True,
        state_path=state_file,
    )
    strict_risk_config = RiskConfig(
        initial_capital=100.0,
        b3_fee_pct=0.0003,
        max_risk_per_trade_pct=0.02,
        stop_loss_pct=0.05,
        trailing_stop_pct=0.05,
        allow_min_lot_override=False,
    )
    strategy = EMACrossoverStrategy(fast_period=9, slow_period=21)

    # Session 1: Run first 400 bars and persist broker state to disk.
    session1_runner = PaperTradingRunner(
        broker=SimulatedPaperBroker(exec_config),
        risk_manager=RiskManager(strict_risk_config),
        config=exec_config,
    )
    report1 = session1_runner.run_simulation(
        ohlcv.iloc[:400], strategy, ticker="ITUB4.SA"
    )
    assert state_file.exists()
    assert report1.total_orders > 0
    # Strict 2% risk budget on R$ 100 enforces odd-lot 'F' routing on ITUB4.
    for rec in report1.receipts:
        assert rec.execution_symbol == "ITUB4F"

    # Session 2: Reload persisted broker from disk cleanly and continue from bar 400.
    resumed_broker = SimulatedPaperBroker(exec_config)
    resumed_snap = resumed_broker.get_account_snapshot(
        market_prices={"ITUB4.SA": float(ohlcv["Close"].iloc[399])}
    )
    assert resumed_snap.cash == pytest.approx(report1.final_cash, abs=1e-12)
    assert resumed_snap.total_fees_paid == pytest.approx(
        report1.total_fees_paid, abs=1e-12
    )
    assert (
        resumed_broker.get_order_by_client_id(report1.receipts[0].client_order_id)
        == report1.receipts[0]
    )

    session2_runner = PaperTradingRunner(
        broker=resumed_broker,
        risk_manager=RiskManager(strict_risk_config),
        config=exec_config,
    )
    # Include the preceding 20 warm-up bars so live evaluation resumes at index 400.
    report2 = session2_runner.run_simulation(
        ohlcv.iloc[400 - WARMUP_SLICE :], strategy, ticker="ITUB4.SA"
    )
    assert report2.initial_cash == pytest.approx(report1.final_cash, abs=1e-12)
    assert report2.total_fees_paid >= report1.total_fees_paid
    assert report2.filled_orders == len(
        [r for r in report2.receipts if r.status == OrderStatus.FILLED]
    )
    assert len(resumed_broker.order_history) == len(report1.receipts) + len(
        report2.receipts
    )

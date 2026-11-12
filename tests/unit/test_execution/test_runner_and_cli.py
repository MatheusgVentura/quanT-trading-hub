"""Unit tests for PaperTradingRunner, atomic ledger export, and thin CLI entrypoint."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

import src.execution as execution_pkg
from src.data.interfaces import IDataProvider
from src.execution import (
    ExecutionConfig,
    ExecutionConfigurationError,
    ExecutionHaltedError,
    InvalidOrderError,
    OrderRouter,
    OrderType,
    PaperSimulationReport,
    PaperTradingRunner,
    SimulatedPaperBroker,
    cli_main,
)
from src.execution.cli import main as direct_cli_main
from src.risk.manager import RiskManager
from src.risk.models import HaltReason, RiskConfig
from src.strategies.base import BaseStrategy
from src.strategies.ema_crossover import EMACrossoverStrategy
from src.strategies.exceptions import InsufficientDataError


class _StaticSignalStrategy(BaseStrategy):
    """Deterministic strategy returning an explicit signal sequence."""

    def __init__(self, signals: list[int]) -> None:
        self._signals = signals

    def generate_signals(self, ohlcv_df: pd.DataFrame) -> pd.Series:
        return pd.Series(
            [float(s) for s in self._signals[: len(ohlcv_df)]],
            index=ohlcv_df.index,
            name="Signal",
            dtype=float,
        )


class _BadOutputStrategy(BaseStrategy):
    """Strategy emitting corrupted non-binary values to test fail-closed guards."""

    def generate_signals(self, ohlcv_df: pd.DataFrame) -> pd.Series:
        return pd.Series(
            [2.0] * len(ohlcv_df), index=ohlcv_df.index, name="Signal", dtype=float
        )


class _FakeDataProvider(IDataProvider):
    """Offline IDataProvider returning preconfigured OHLCV DataFrames."""

    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df
        self.calls: list[dict[str, Any]] = []

    def fetch_ohlcv(
        self,
        ticker: str,
        start_date: str | None = None,
        end_date: str | None = None,
        period: str | None = "1y",
        interval: str = "1d",
    ) -> pd.DataFrame:
        self.calls.append(
            {
                "ticker": ticker,
                "start_date": start_date,
                "end_date": end_date,
                "period": period,
                "interval": interval,
            }
        )
        return self._df.copy()


def _make_ohlcv(closes: list[float], *, start: str = "2023-01-02") -> pd.DataFrame:
    dates = pd.bdate_range(start=start, periods=len(closes))
    arr = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {
            "Open": arr * 0.995,
            "High": arr * 1.01,
            "Low": arr * 0.99,
            "Close": arr,
            "Volume": np.full(len(closes), 1_000_000, dtype=float),
        },
        index=dates,
    )


def test_ac11_public_api_exports_available_from_src_execution() -> None:
    """AC11: Package __init__ exposes runner, report, and cli_main in __all__."""
    assert "PaperTradingRunner" in execution_pkg.__all__
    assert "PaperSimulationReport" in execution_pkg.__all__
    assert "cli_main" in execution_pkg.__all__
    assert execution_pkg.PaperTradingRunner is PaperTradingRunner
    assert execution_pkg.PaperSimulationReport is PaperSimulationReport
    assert execution_pkg.cli_main is direct_cli_main


def test_ac11_runner_slices_ema_warmup_tracks_b3_fractional_fees_and_equity_curve() -> (
    None
):
    """AC11: Runner slices 20-bar EMA(9,21) warmup and executes fractional B3 lots."""
    # Downward warmup -> steady uptrend -> sharp reversal to force EMA cross in & out.
    closes = (
        [30.0 - 0.15 * i for i in range(20)]
        + [27.0 + 0.35 * i for i in range(25)]
        + [35.5 - 0.45 * i for i in range(20)]
    )
    ohlcv = _make_ohlcv(closes, start="2023-01-02")

    exec_cfg = ExecutionConfig(initial_cash=100.0, b3_fee_pct=0.0003)
    risk_cfg = RiskConfig(
        initial_capital=100.0,
        b3_fee_pct=0.0003,
        max_daily_loss_pct=0.25,
        max_drawdown_pct=0.40,
        stop_loss_pct=0.15,
        trailing_stop_pct=0.15,
        allow_min_lot_override=True,
    )
    runner = PaperTradingRunner(
        broker=SimulatedPaperBroker(exec_cfg),
        risk_manager=RiskManager(risk_cfg),
        config=exec_cfg,
    )

    report = runner.run_simulation(
        ohlcv,
        EMACrossoverStrategy(fast_period=9, slow_period=21),
        ticker="ITUB4.SA",
    )

    assert report.ticker == "ITUB4.SA"
    assert report.trading_days == len(ohlcv) - 20
    assert len(report.equity_curve) == len(ohlcv) - 20
    assert len(report.steps) == len(ohlcv) - 20
    assert report.total_orders >= 2
    assert report.filled_orders == report.total_orders
    assert all(rec.execution_symbol == "ITUB4F" for rec in report.receipts)
    assert report.total_fees_paid > 0.0
    assert report.max_drawdown_pct <= 0.0
    assert not report.halted
    assert report.halt_count == 0
    assert "PAPER TRADING SIMULATION REPORT: ITUB4.SA" in report.summary()

    serialized = json.dumps(report.to_dict())
    parsed = json.loads(serialized)
    assert parsed["schema_version"] == 1
    assert parsed["ticker"] == "ITUB4.SA"
    assert len(parsed["equity_curve"]) == report.trading_days

    short_df = _make_ohlcv([25.0] * 10)
    with pytest.raises(InsufficientDataError):
        runner.run_simulation(short_df, EMACrossoverStrategy(9, 21), ticker="ITUB4.SA")


def test_ac06_runner_step_gates_every_signal_through_risk_manager_and_updates_limit_fills() -> (
    None
):
    """AC06: Runner.step enforces RiskManager pre-trade gate and matches LIMIT fills."""
    ts0 = datetime(2024, 5, 6, 14, 0, tzinfo=timezone.utc)  # noqa: UP017
    ts1 = ts0 + timedelta(days=1)
    exec_cfg = ExecutionConfig(initial_cash=100.0, b3_fee_pct=0.0003)
    risk_cfg = RiskConfig(
        initial_capital=100.0,
        b3_fee_pct=0.0003,
        max_risk_per_trade_pct=0.02,
        stop_loss_pct=0.05,
        allow_min_lot_override=False,
    )
    broker = SimulatedPaperBroker(exec_cfg, clock=lambda: ts0)
    runner = PaperTradingRunner(
        broker=broker,
        risk_manager=RiskManager(risk_cfg),
        config=exec_cfg,
    )

    # Price R$ 60 -> 5% risk per share (R$ 3.00) > R$ 2.00 budget -> rejected, zero orders.
    blocked_step = runner.step(ticker="VALE3.SA", signal=1, price=60.0, timestamp=ts0)
    assert blocked_step.verdict.approved is False
    assert blocked_step.order_receipt is None
    assert broker.order_history == []

    # Price R$ 25 -> approved, places resting LIMIT BUY @ 24.0 while market is 25.0.
    resting_step = runner.step(
        ticker="ITUB4.SA",
        signal=1,
        price=25.0,
        timestamp=ts0,
        order_type=OrderType.LIMIT,
        limit_price=24.0,
    )
    assert resting_step.order_receipt is not None
    assert resting_step.order_receipt.execution_symbol == "ITUB4F"
    assert (
        resting_step.account.open_orders[0].client_order_id
        == resting_step.order_receipt.client_order_id
    )
    assert len(resting_step.account.positions) == 0

    # Next day market drops to 23.5 -> update_market_prices fills LIMIT order before RiskManager runs.
    with broker.temporary_clock(lambda: ts1):
        filled_step = runner.step(
            ticker="ITUB4.SA",
            signal=1,
            price=23.5,
            timestamp=ts1,
        )
    assert filled_step.order_receipt is None
    assert filled_step.account.open_orders == []
    assert filled_step.account.positions["ITUB4.SA"].shares >= 1
    assert runner.risk_manager.stop_monitor.has_open_position


def test_ac03_step_and_raise_on_halt_propagate_execution_halted_without_sys_exit() -> (
    None
):
    """AC03: Library components raise ExecutionHaltedError cleanly without terminating process."""
    ts = datetime(2024, 6, 3, 12, 0, tzinfo=timezone.utc)  # noqa: UP017
    broker = SimulatedPaperBroker(ExecutionConfig(initial_cash=100.0), clock=lambda: ts)
    runner = PaperTradingRunner(broker=broker)

    with pytest.raises(ExecutionHaltedError, match="LATENCY_LIMIT"):
        runner.step(
            ticker="PETR4.SA",
            signal=1,
            price=30.0,
            timestamp=ts,
            latency_ms=750.0,
        )

    # Now test raise_on_halt=True vs raise_on_halt=False on a 4-bar sequence.
    ohlcv = _make_ohlcv([25.0, 25.5, 26.0, 26.5])
    lat_series = pd.Series([10.0, 650.0, 10.0, 10.0], index=ohlcv.index)

    fail_fast_runner = PaperTradingRunner()
    with pytest.raises(ExecutionHaltedError, match="LATENCY_LIMIT"):
        fail_fast_runner.run_simulation(
            ohlcv,
            _StaticSignalStrategy([1, 1, 1, 1]),
            ticker="ITUB4.SA",
            raise_on_halt=True,
            latencies=lat_series,
        )

    resilient_runner = PaperTradingRunner(
        config=ExecutionConfig(initial_cash=100.0, liquidate_on_halt=True)
    )
    report = resilient_runner.run_simulation(
        ohlcv,
        _StaticSignalStrategy([1, 1, 1, 1]),
        ticker="ITUB4.SA",
        raise_on_halt=False,
        latencies=lat_series,
    )
    assert report.halted is True
    assert report.halt_count == 1
    assert len(report.equity_curve) == 4
    assert list(report.equity_curve["Action"]) == ["BUY", "HALT", "HALT", "HALT"]
    assert list(report.equity_curve["Shares"]) == [1, 0, 0, 0]
    # Both initial BUY and HALT liquidation SELL must be captured in receipts.
    assert report.total_orders == 2
    assert report.filled_orders == 2


def test_ac03_daily_loss_kill_switch_halts_day_and_auto_resets_next_session_with_suppression() -> (
    None
):
    """AC03/AC06: Daily-loss halt auto-resets next session and waits for flat reset signal."""
    # Buy 1 share @ 50.0 (max_position_pct=0.55 avoids sizing mismatch), day 1 crashes 10% (-5% equity >= 2% limit).
    ohlcv = _make_ohlcv([50.0, 45.0, 46.0, 46.5, 47.0])
    risk_cfg = RiskConfig(
        initial_capital=100.0,
        max_risk_per_trade_pct=0.05,
        max_position_pct=0.55,
        stop_loss_pct=0.05,
        trailing_stop_pct=None,
        max_daily_loss_pct=0.02,
        max_drawdown_pct=0.30,
        allow_min_lot_override=True,
    )
    runner = PaperTradingRunner(
        risk_manager=RiskManager(risk_cfg),
        config=ExecutionConfig(initial_cash=100.0, liquidate_on_halt=True),
    )
    report = runner.run_simulation(
        ohlcv,
        _StaticSignalStrategy([1, 1, 1, 0, 1]),
        ticker="ITUB4.SA",
        raise_on_halt=False,
        suppress_reentry_after_exit=True,
    )

    assert report.halted is True
    assert report.halt_count == 1
    # Bar 0: BUY; Bar 1: HALT & liquidate (DAILY_LOSS_LIMIT); Bar 2: auto-reset + suppressed to HOLD;
    # Bar 3: signal=0 clears suppression (HOLD); Bar 4: re-enters BUY cleanly.
    assert list(report.equity_curve["Action"]) == ["BUY", "HALT", "HOLD", "HOLD", "BUY"]
    assert runner.risk_manager.kill_switch.state.reason == HaltReason.NONE
    assert report.total_orders == 3


def test_ac08_runner_fail_closed_validation_on_init_step_and_corrupted_ohlcv() -> None:
    """AC08: Malformed configuration, corrupted prices, and bad OHLCV fail closed."""
    b1 = SimulatedPaperBroker()
    b2 = SimulatedPaperBroker()
    r1 = OrderRouter(broker=b1)
    runner_from_router = PaperTradingRunner(router=r1)
    assert runner_from_router.last_snapshot is None

    with pytest.raises(ExecutionConfigurationError, match="OrderRouter"):
        PaperTradingRunner(router="bad")  # type: ignore[arg-type]
    with pytest.raises(ExecutionConfigurationError, match="IBrokerAdapter"):
        PaperTradingRunner(broker="bad")  # type: ignore[arg-type]
    with pytest.raises(ExecutionConfigurationError, match="RiskManager"):
        PaperTradingRunner(risk_manager="bad")  # type: ignore[arg-type]
    with pytest.raises(ExecutionConfigurationError, match="ExecutionConfig"):
        PaperTradingRunner(config="bad")  # type: ignore[arg-type]
    with pytest.raises(ExecutionConfigurationError, match="conflicts with"):
        PaperTradingRunner(broker=b2, router=r1)
    with pytest.raises(ExecutionConfigurationError, match="risk_manager conflicts"):
        PaperTradingRunner(risk_manager=RiskManager(), router=r1)
    with pytest.raises(ExecutionConfigurationError, match="config conflicts"):
        PaperTradingRunner(config=ExecutionConfig(initial_cash=200.0), router=r1)
    with pytest.raises(ExecutionConfigurationError, match="ledger_path"):
        PaperTradingRunner(ledger_path="   ")
    with pytest.raises(ExecutionConfigurationError, match="sleep_fn"):
        PaperTradingRunner(sleep_fn=123)  # type: ignore[arg-type]
    with pytest.raises(ExecutionConfigurationError, match="clock"):
        PaperTradingRunner(clock=123)  # type: ignore[arg-type]

    runner = PaperTradingRunner(broker=b1)
    snap_before, _ = runner.sync_account()
    assert runner.last_snapshot == snap_before

    for bad_price in (float("nan"), float("inf"), 0.0, -10.0):
        with pytest.raises(InvalidOrderError):
            runner.step(ticker="ITUB4.SA", signal=1, price=bad_price)
    with pytest.raises(InvalidOrderError):
        runner.step(ticker="   ", signal=1, price=25.0)

    snap_after, _ = runner.sync_account()
    assert snap_after.cash == snap_before.cash

    valid_df = _make_ohlcv([25.0, 26.0, 27.0])
    with pytest.raises(InvalidOrderError, match="'Close' column"):
        runner.run_simulation(
            pd.DataFrame({"Open": [25.0, 26.0, 27.0]}, index=valid_df.index),
            _StaticSignalStrategy([1, 1, 1]),
            ticker="ITUB4.SA",
        )
    with pytest.raises(InvalidOrderError, match="DatetimeIndex"):
        runner.run_simulation(
            pd.DataFrame({"Close": [25.0, 26.0, 27.0]}),
            _StaticSignalStrategy([1, 1, 1]),
            ticker="ITUB4.SA",
        )
    with pytest.raises(InvalidOrderError):
        runner.run_simulation(
            _make_ohlcv([25.0, float("nan"), 27.0]),
            _StaticSignalStrategy([1, 1, 1]),
            ticker="ITUB4.SA",
        )
    unsorted = pd.DataFrame({"Close": [27.0, 26.0, 25.0]}, index=valid_df.index[::-1])
    with pytest.raises(InvalidOrderError, match="sorted chronologically"):
        runner.run_simulation(
            unsorted,
            _StaticSignalStrategy([1, 1, 1]),
            ticker="ITUB4.SA",
        )
    with pytest.raises(InvalidOrderError, match="strictly 0 or 1"):
        runner.run_simulation(valid_df, _BadOutputStrategy(), ticker="ITUB4.SA")
    with pytest.raises(InvalidOrderError, match="negative"):
        runner.run_simulation(
            valid_df,
            _StaticSignalStrategy([1, 1, 1]),
            ticker="ITUB4.SA",
            latency_ms=-1.0,
        )
    with pytest.raises(ExecutionConfigurationError, match="not both"):
        runner.run_simulation(
            valid_df,
            _StaticSignalStrategy([1, 1, 1]),
            ticker="ITUB4.SA",
            latency_ms=10.0,
            latencies=pd.Series([1.0, 1.0, 1.0], index=valid_df.index),
        )
    with pytest.raises(ExecutionConfigurationError, match="ledger_path must be"):
        runner.save_ledger(
            runner.run_simulation(
                valid_df, _StaticSignalStrategy([0, 0, 0]), ticker="ITUB4.SA"
            )
        )
    with pytest.raises(ExecutionConfigurationError, match="PaperSimulationReport"):
        runner.save_ledger("not-a-report", "out.json")  # type: ignore[arg-type]


def test_ac10_atomic_json_and_parquet_ledger_and_broker_state_persistence_with_crash_safety(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC10: Both broker state and ledger JSON/Parquet persist atomically and reload cleanly."""
    state_file = tmp_path / "broker_state.json"
    json_ledger = tmp_path / "ledger.json"
    parquet_ledger = tmp_path / "ledger.parquet"

    ohlcv = _make_ohlcv([20.0, 22.0, 24.0, 23.0])
    cfg = ExecutionConfig(initial_cash=100.0, state_path=state_file)
    runner = PaperTradingRunner(config=cfg, ledger_path=json_ledger)

    report = runner.run_simulation(
        ohlcv,
        _StaticSignalStrategy([1, 1, 0, 0]),
        ticker="PETR4.SA",
    )

    assert state_file.exists()
    assert json_ledger.exists()

    reloaded_broker = SimulatedPaperBroker(cfg)
    reloaded_snap = reloaded_broker.get_account_snapshot()
    assert reloaded_snap.cash == pytest.approx(report.final_cash)
    assert reloaded_snap.realized_pnl == pytest.approx(report.realized_pnl)
    assert reloaded_snap.total_fees_paid == pytest.approx(report.total_fees_paid)
    assert reloaded_snap.positions == {}
    assert len(reloaded_broker.order_history) == report.total_orders

    ledger_data = json.loads(json_ledger.read_text(encoding="utf-8"))
    assert ledger_data["final_equity"] == pytest.approx(report.final_equity)
    assert len(ledger_data["receipts"]) == report.total_orders
    assert len(ledger_data["equity_curve"]) == 4

    saved_pq = runner.save_ledger(report, parquet_ledger)
    assert saved_pq == parquet_ledger
    pq_df = pd.read_parquet(parquet_ledger)
    assert len(pq_df) == 4
    assert list(pq_df["Action"]) == ["BUY", "HOLD", "EXIT", "HOLD"]

    # Simulate OS replace crash -> existing ledger remains intact with no .tmp leaks.
    prior_json = json_ledger.read_text(encoding="utf-8")

    def _boom_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        raise OSError("simulated disk error")

    monkeypatch.setattr(os, "replace", _boom_replace)
    with pytest.raises(OSError, match="simulated disk error"):
        runner.save_ledger(report, json_ledger)

    assert json_ledger.read_text(encoding="utf-8") == prior_json
    assert list(tmp_path.glob("*.tmp")) == []


def test_ac03_cli_catches_execution_halted_error_and_exits_with_code_1(
    capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    """AC03: Thin CLI entrypoint translates ExecutionHaltedError to sys.exit(1)."""
    closes = [25.0 + 0.1 * i for i in range(30)]
    provider = _FakeDataProvider(_make_ohlcv(closes))

    with pytest.raises(SystemExit) as exc_info, caplog.at_level("ERROR"):
        cli_main(
            ["--ticker", "ITUB4.SA", "--latency-ms", "600"],
            provider=provider,
        )

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "CRITICAL:" in captured.err
    assert "LATENCY_LIMIT" in captured.err
    assert any("Kill-Switch" in rec.message for rec in caplog.records)


def test_ac11_cli_success_returns_zero_and_persists_state_and_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC11: CLI entrypoint runs simulation end-to-end, writes outputs, and returns 0."""
    closes = [30.0 - 0.1 * i for i in range(20)] + [28.0 + 0.25 * i for i in range(25)]
    provider = _FakeDataProvider(_make_ohlcv(closes))
    state_file = tmp_path / "cli_state.json"
    ledger_file = tmp_path / "cli_ledger.json"

    exit_code = cli_main(
        [
            "--ticker",
            "ITUB4.SA",
            "--capital",
            "100",
            "--allow-min-lot-override",
            "--continue-on-halt",
            "--state-path",
            str(state_file),
            "--ledger-path",
            str(ledger_file),
        ],
        provider=provider,
    )

    assert exit_code == 0
    assert state_file.exists()
    assert ledger_file.exists()
    out = capsys.readouterr().out
    assert "PAPER TRADING SIMULATION REPORT: ITUB4.SA" in out
    assert provider.calls[0]["ticker"] == "ITUB4.SA"

    # Invalid configuration via CLI must also exit non-zero cleanly via sys.exit(1).
    with pytest.raises(SystemExit) as bad_exit:
        cli_main(["--capital", "-50"], provider=provider)
    assert bad_exit.value.code == 1

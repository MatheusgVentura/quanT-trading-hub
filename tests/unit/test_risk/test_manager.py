"""Unit tests for RiskManager pre-trade gates and close-based risk overlay."""

import math
from datetime import date, datetime

import pandas as pd
import pytest

from src.backtest import BacktestConfig, VectorizedBacktestEngine
from src.risk import (
    HaltReason,
    InvalidRiskInputError,
    KillSwitchTriggeredError,
    RiskConfig,
    RiskManager,
    RiskStatus,
)


def _make_ohlcv(prices: list[float], dates: list[str] | None = None) -> pd.DataFrame:
    """Build a minimal valid daily OHLCV DataFrame from Close prices."""
    index = (
        pd.date_range("2026-01-05", periods=len(prices), freq="B")
        if dates is None
        else pd.DatetimeIndex(dates)
    )
    return pd.DataFrame(
        {
            "Open": prices,
            "High": [p * 1.01 for p in prices],
            "Low": [p * 0.99 for p in prices],
            "Close": prices,
            "Volume": [1000] * len(prices),
        },
        index=index,
    )


def test_ac04_swing_trade_blocks_voluntary_d0_exit_allows_d1() -> None:
    """AC04: Block voluntary D0 exits when allow_day_trade=False; allow on D1 or when enabled."""
    day0 = date(2026, 11, 11)
    day1 = date(2026, 11, 12)
    manager = RiskManager(RiskConfig(initial_capital=100.0, allow_day_trade=False))

    d0_exit = manager.evaluate_trade(
        signal=0,
        price=20.0,
        current_equity=100.0,
        current_date=day0,
        current_shares=2,
        entry_date=day0,
    )
    assert d0_exit.approved is False
    assert d0_exit.action == "HOLD"
    assert d0_exit.shares == 2
    assert d0_exit.weight == pytest.approx(0.4)
    assert "Swing Trade" in d0_exit.reason

    d1_exit = manager.evaluate_trade(
        signal=0,
        price=20.5,
        current_equity=101.0,
        current_date=day1,
        current_shares=2,
        entry_date=day0,
    )
    assert d1_exit.approved is True
    assert d1_exit.action == "EXIT"
    assert d1_exit.shares == 0
    assert d1_exit.weight == 0.0

    day_trade_mgr = RiskManager(RiskConfig(initial_capital=100.0, allow_day_trade=True))
    allowed_d0 = day_trade_mgr.evaluate_trade(
        signal=0,
        price=20.0,
        current_equity=100.0,
        current_date=day0,
        current_shares=2,
        entry_date=day0,
    )
    assert allowed_d0.approved is True
    assert allowed_d0.action == "EXIT"


def test_ac04_swing_trade_allows_emergency_d0_exits() -> None:
    """AC04: Explicitly permit D0 exits triggered by StopMonitor, KillSwitch, or emergency flag."""
    day0 = date(2026, 11, 11)

    # 1. Explicit emergency flag on D0
    mgr_flag = RiskManager(RiskConfig(initial_capital=100.0, allow_day_trade=False))
    verdict_flag = mgr_flag.evaluate_trade(
        signal=0,
        price=20.0,
        current_equity=100.0,
        current_date=day0,
        current_shares=2,
        entry_date=day0,
        is_emergency=True,
    )
    assert verdict_flag.approved is True
    assert verdict_flag.action == "EXIT"
    assert "Emergency exit" in verdict_flag.reason

    # 2. StopMonitor trigger on D0 overrides even a HOLD/BUY signal
    mgr_stop = RiskManager(
        RiskConfig(initial_capital=100.0, stop_loss_pct=0.05, allow_day_trade=False)
    )
    mgr_stop.stop_monitor.open_position(entry_price=20.0)
    verdict_stop = mgr_stop.evaluate_trade(
        signal=1,
        price=19.0,
        current_equity=99.0,
        current_date=day0,
        current_shares=1,
        entry_date=day0,
    )
    assert verdict_stop.approved is True
    assert verdict_stop.action == "EXIT"
    assert "STOP_LOSS" in verdict_stop.reason

    # 3. KillSwitch halt on D0 authorizes emergency liquidation of open position
    mgr_ks = RiskManager(RiskConfig(initial_capital=100.0, allow_day_trade=False))
    verdict_ks = mgr_ks.evaluate_trade(
        signal=0,
        price=20.0,
        current_equity=98.0,
        current_date=day0,
        current_shares=2,
        entry_date=day0,
    )
    assert verdict_ks.kill_switch_state.status == RiskStatus.HALTED
    assert verdict_ks.approved is True
    assert verdict_ks.action == "EXIT"


def test_ac09_kill_switch_halt_blocks_new_entries_until_manual_reset() -> None:
    """AC09: Reject all new Long entries with action='HALT' while KillSwitch is HALTED."""
    day1 = date(2026, 11, 11)
    day2 = date(2026, 11, 12)
    day3 = date(2026, 11, 13)
    manager = RiskManager(
        RiskConfig(
            initial_capital=100.0,
            b3_fee_pct=0.0003,
            max_risk_per_trade_pct=0.02,
            stop_loss_pct=0.05,
        )
    )

    buy_verdict = manager.evaluate_trade(
        signal=1,
        price=10.0,
        current_equity=100.0,
        current_date=day1,
    )
    assert buy_verdict.approved is True
    assert buy_verdict.action == "BUY"
    assert buy_verdict.shares == 4
    assert 0.0 < buy_verdict.weight <= 1.0

    # Latency spike while flat trips LATENCY_LIMIT -> immediate HALT
    halt_verdict = manager.evaluate_trade(
        signal=1,
        price=10.0,
        current_equity=100.0,
        current_date=day1,
        latency_ms=550.0,
    )
    assert halt_verdict.approved is False
    assert halt_verdict.action == "HALT"
    assert halt_verdict.shares == 0
    assert halt_verdict.weight == 0.0
    assert halt_verdict.kill_switch_state.reason == HaltReason.LATENCY_LIMIT

    # Next trading day with normal latency remains HALTED until manual reset
    still_halted = manager.evaluate_trade(
        signal=1,
        price=10.0,
        current_equity=100.0,
        current_date=day2,
        latency_ms=15.0,
    )
    assert still_halted.approved is False
    assert still_halted.action == "HALT"

    with pytest.raises(KillSwitchTriggeredError):
        manager.kill_switch.reset(confirm=False)
    assert manager.kill_switch.is_halted is True

    manager.kill_switch.reset(confirm=True)
    resumed = manager.evaluate_trade(
        signal=1,
        price=10.0,
        current_equity=100.0,
        current_date=day3,
        latency_ms=15.0,
    )
    assert resumed.approved is True
    assert resumed.action == "BUY"
    assert resumed.shares == 4


def test_ac09_sizing_rejection_and_flat_or_hold_paths() -> None:
    """AC09: Return unapproved HOLD on strict 2% risk-budget sizing rejection and approve normal HOLD."""
    day1 = date(2026, 11, 11)
    day2 = date(2026, 11, 12)
    manager = RiskManager(
        RiskConfig(
            initial_capital=100.0,
            max_risk_per_trade_pct=0.02,
            stop_loss_pct=0.05,
            allow_min_lot_override=False,
        )
    )

    flat_verdict = manager.evaluate_trade(
        signal=0,
        price=60.0,
        current_equity=100.0,
        current_date=day1,
    )
    assert flat_verdict.approved is True
    assert flat_verdict.action == "HOLD"
    assert flat_verdict.shares == 0

    # At R$ 60 with 5% stop (R$ 3 risk/share) and R$ 2 risk budget -> 0 shares
    rejected_buy = manager.evaluate_trade(
        signal=1,
        price=60.0,
        current_equity=100.0,
        current_date=day1,
    )
    assert rejected_buy.approved is False
    assert rejected_buy.action == "HOLD"
    assert rejected_buy.shares == 0
    assert "budget" in rejected_buy.reason

    # Open position held under normal risk limits
    hold_open = manager.evaluate_trade(
        signal=1,
        price=20.0,
        current_equity=100.0,
        current_date=day2,
        current_shares=2,
        entry_date=day1,
    )
    assert hold_open.approved is True
    assert hold_open.action == "HOLD"
    assert hold_open.shares == 2
    assert hold_open.weight == pytest.approx(0.4)


def test_ac11_overlay_warmup_trailing_stop_and_reentry_suppression() -> None:
    """AC11: Honor warm-up zeros, exit on trailing stop, suppress re-entry until fresh 0 -> 1."""
    # Prevent KillSwitch from preempting the 5% trailing stop test with strict thresholds
    config = RiskConfig(
        initial_capital=100.0,
        b3_fee_pct=0.0003,
        stop_loss_pct=0.05,
        trailing_stop_pct=0.05,
        max_daily_loss_pct=0.20,
        max_drawdown_pct=0.30,
    )
    manager = RiskManager(config)

    # Bar 0..1: warm-up 0
    # Bar 2: entry at 100.0 (raw=1 -> out=1)
    # Bar 3: climbs to 110.0 (HWM=110.0, trailing threshold=104.5 -> out=1)
    # Bar 4: drops to 104.0 <= 104.5 -> trailing stop triggers (out=0, suppressed=True)
    # Bar 5: raw stays 1 -> suppressed keeps out=0
    # Bar 6: raw flips to 0 -> clears suppression (out=0)
    # Bar 7: fresh 0 -> 1 at 105.0 -> re-entry allowed (out=1)
    # Bar 8: executes t+1 re-entry at 106.0 (out=1)
    prices = [98.0, 99.0, 100.0, 110.0, 104.0, 106.0, 104.0, 105.0, 106.0]
    raw_values = [0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 0.0, 1.0, 1.0]
    df = _make_ohlcv(prices)
    raw = pd.Series(raw_values, index=df.index, name="Signal")

    filtered = manager.apply_risk_overlay(df, raw)
    assert list(filtered.tolist()) == [0, 0, 1, 1, 0, 0, 0, 1, 1]
    assert filtered.name == "Signal"
    assert filtered.index.equals(df.index)

    # Resulting signals execute cleanly in Phase 2 VectorizedBacktestEngine (buy@3, exit@5, reenter@8)
    engine = VectorizedBacktestEngine(
        BacktestConfig(b3_fee_pct=0.0003, slippage_pct=0.0, brokerage_fee=0.0)
    )
    result = engine.run(df, filtered, ticker="TEST3.SA")
    assert result.metrics.total_trades == 3

    # Also verify enforce_position_sizing blocks entry when R$ 100 cannot afford 1 share within 2% risk
    df_expensive = _make_ohlcv([60.0, 61.0, 62.0])
    raw_expensive = pd.Series([1, 1, 0], index=df_expensive.index)
    sized_out = manager.apply_risk_overlay(
        df_expensive, raw_expensive, enforce_position_sizing=True
    )
    assert list(sized_out.tolist()) == [0, 0, 0]


def test_ac11_overlay_kill_switch_triggers_swing_guard_and_stateless_calls() -> None:
    """AC11: Trigger overlay exits on daily loss / latency / drawdown, enforce D0 guard, stay isolated."""
    # 1. Daily loss >= 2% exits and suppresses re-entry next day despite auto-reset when raw stays 1
    manager = RiskManager(
        RiskConfig(
            initial_capital=100.0,
            b3_fee_pct=0.0003,
            stop_loss_pct=0.10,
            trailing_stop_pct=None,
            max_daily_loss_pct=0.02,
            max_drawdown_pct=0.15,
        )
    )
    df_daily_ks = _make_ohlcv([100.0, 97.5, 99.0, 99.5, 100.0])
    raw_daily_ks = pd.Series([1, 1, 1, 0, 1], index=df_daily_ks.index)
    out_daily_ks = manager.apply_risk_overlay(df_daily_ks, raw_daily_ks)
    # Bar 0 enters at 100; Bar 1 falls -2.5% -> DAILY_LOSS_LIMIT -> exit;
    # Bar 2 auto-resets KS but raw stayed 1 -> suppressed; Bar 3 raw=0; Bar 4 fresh 0->1 enters
    assert list(out_daily_ks.tolist()) == [1, 0, 0, 0, 1]

    # 2. Same-calendar-date voluntary exit is blocked (D0 guard), emergency latency exits anyway
    same_day_mgr = RiskManager(
        RiskConfig(
            initial_capital=100.0,
            stop_loss_pct=0.20,
            trailing_stop_pct=None,
            max_daily_loss_pct=0.50,
            max_drawdown_pct=0.50,
            max_latency_ms=500.0,
            allow_day_trade=False,
        )
    )
    same_day_idx = pd.DatetimeIndex(
        [
            "2026-11-11 10:00",
            "2026-11-11 11:00",
            "2026-11-11 12:00",
            "2026-11-12 10:00",
        ]
    )
    df_intraday = _make_ohlcv([100.0, 101.0, 102.0, 103.0])
    df_intraday.index = same_day_idx
    raw_intraday = pd.Series([1, 0, 0, 1], index=same_day_idx)
    lat_spike = pd.Series([10.0, 10.0, 700.0, 10.0], index=same_day_idx)
    out_intraday = same_day_mgr.apply_risk_overlay(
        df_intraday, raw_intraday, latencies=lat_spike
    )
    # Bar 0 enters; Bar 1 voluntary exit on same calendar date -> blocked (stays 1);
    # Bar 2 latency spike -> emergency exit allowed (0), KS remains HALTED on Bar 3 -> 0
    assert list(out_intraday.tolist()) == [1, 1, 0, 0]

    # 3. Calling apply_risk_overlay again on a fresh asset is isolated from previous run state
    df_fresh = _make_ohlcv([50.0, 51.0, 52.0])
    raw_fresh = pd.Series([1, 1, 0], index=df_fresh.index)
    out_fresh = same_day_mgr.apply_risk_overlay(df_fresh, raw_fresh)
    assert list(out_fresh.tolist()) == [1, 1, 0]


def test_ac10_manager_and_overlay_invalid_inputs_fail_closed() -> None:
    """AC10: Reject invalid pre-trade parameters and malformed overlay inputs with InvalidRiskInputError."""
    manager = RiskManager(RiskConfig(initial_capital=100.0))
    day1 = date(2026, 11, 11)
    day0 = date(2026, 11, 10)

    for bad_sig in [-1, 2, True]:
        with pytest.raises(InvalidRiskInputError, match="signal"):
            manager.evaluate_trade(
                signal=bad_sig,
                price=10.0,
                current_equity=100.0,
                current_date=day1,
            )

    for bad_price in [0.0, -5.0, math.nan, math.inf, False]:
        with pytest.raises(InvalidRiskInputError, match="price"):
            manager.evaluate_trade(
                signal=1,
                price=bad_price,
                current_equity=100.0,
                current_date=day1,
            )

    for bad_shares in [-1, True]:
        with pytest.raises(InvalidRiskInputError, match="current_shares"):
            manager.evaluate_trade(
                signal=0,
                price=10.0,
                current_equity=100.0,
                current_date=day1,
                current_shares=bad_shares,
            )

    with pytest.raises(InvalidRiskInputError, match="entry_date"):
        manager.evaluate_trade(
            signal=0,
            price=10.0,
            current_equity=100.0,
            current_date=day0,
            current_shares=1,
            entry_date=datetime(2026, 11, 11, 9, 0),
        )

    valid_df = _make_ohlcv([10.0, 11.0, 12.0])
    valid_sig = pd.Series([0, 1, 1], index=valid_df.index)

    with pytest.raises(InvalidRiskInputError, match="empty"):
        manager.apply_risk_overlay(valid_df.iloc[0:0], valid_sig.iloc[0:0])

    with pytest.raises(InvalidRiskInputError, match="Close"):
        manager.apply_risk_overlay(valid_df.drop(columns=["Close"]), valid_sig)

    with pytest.raises(InvalidRiskInputError, match="identical"):
        manager.apply_risk_overlay(valid_df, valid_sig.iloc[1:])

    non_dt_df = valid_df.reset_index(drop=True)
    with pytest.raises(InvalidRiskInputError, match="DatetimeIndex"):
        manager.apply_risk_overlay(
            non_dt_df, pd.Series([0, 1, 1], index=non_dt_df.index)
        )

    bad_close_df = valid_df.copy()
    bad_close_df.iloc[1, bad_close_df.columns.get_loc("Close")] = math.nan
    with pytest.raises(InvalidRiskInputError, match="Close"):
        manager.apply_risk_overlay(bad_close_df, valid_sig)

    bad_sig_series = pd.Series([0, 2, 1], index=valid_df.index)
    with pytest.raises(InvalidRiskInputError, match="raw_signals"):
        manager.apply_risk_overlay(valid_df, bad_sig_series)

    bool_sig_series = pd.Series([False, True, True], index=valid_df.index)
    with pytest.raises(InvalidRiskInputError, match="boolean"):
        manager.apply_risk_overlay(valid_df, bool_sig_series)

    bad_lat_series = pd.Series([10.0, -1.0, 10.0], index=valid_df.index)
    with pytest.raises(InvalidRiskInputError, match="latencies"):
        manager.apply_risk_overlay(valid_df, valid_sig, latencies=bad_lat_series)

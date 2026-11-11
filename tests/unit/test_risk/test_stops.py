"""Unit tests for StopMonitor fixed Stop-Loss and Trailing Stop logic (AC07, AC08, AC10)."""

import math

import pytest

from src.risk.exceptions import InvalidRiskInputError
from src.risk.models import RiskConfig
from src.risk.stops import StopMonitor, StopTrigger


def test_ac07_fixed_stop_loss_trigger() -> None:
    """AC07: Trigger STOP_LOSS at exact 5% fixed stop boundary and below."""
    monitor = StopMonitor(RiskConfig(stop_loss_pct=0.05, trailing_stop_pct=0.05))
    monitor.open_position(entry_price=100.0)

    assert monitor.fixed_stop_price == pytest.approx(95.0)

    ok_res = monitor.evaluate(95.01)
    assert ok_res.triggered is False
    assert ok_res.trigger_type == StopTrigger.NONE

    boundary_res = monitor.evaluate(95.0)
    assert boundary_res.triggered is True
    assert boundary_res.trigger_type == StopTrigger.STOP_LOSS

    below_res = monitor.evaluate(92.0)
    assert below_res.triggered is True
    assert below_res.trigger_type == StopTrigger.STOP_LOSS


def test_ac08_trailing_stop_tracks_high_water_mark() -> None:
    """AC08: Trailing stop updates high-water mark upward and exits on 5% drop from peak."""
    monitor = StopMonitor(RiskConfig(stop_loss_pct=0.05, trailing_stop_pct=0.05))
    monitor.open_position(entry_price=100.0)

    # Price rallies to 120.0 -> trailing stop ratchets up to 114.0
    rally = monitor.evaluate(120.0)
    assert rally.triggered is False
    assert rally.highest_price == pytest.approx(120.0)
    assert rally.trailing_stop_price == pytest.approx(114.0)

    # Pullback to 115.0 holds position and keeps high-water mark at 120.0
    pullback = monitor.evaluate(115.0)
    assert pullback.triggered is False
    assert monitor.highest_price == pytest.approx(120.0)
    assert pullback.trailing_stop_price == pytest.approx(114.0)

    # Breach at 114.0 exits with TRAILING_STOP while fixed stop (95.0) is untouched
    exit_res = monitor.evaluate(114.0)
    assert exit_res.triggered is True
    assert exit_res.trigger_type == StopTrigger.TRAILING_STOP
    assert exit_res.fixed_stop_price == pytest.approx(95.0)


def test_ac08_trailing_stop_disabled_when_none() -> None:
    """AC08: Disable trailing stop cleanly when trailing_stop_pct is None."""
    monitor = StopMonitor(RiskConfig(stop_loss_pct=0.05, trailing_stop_pct=None))
    monitor.open_position(entry_price=100.0)

    assert monitor.trailing_stop_price is None

    monitor.evaluate(120.0)
    hold_res = monitor.evaluate(110.0)  # Would trigger 5% trailing (114), but disabled
    assert hold_res.triggered is False
    assert hold_res.trailing_stop_price is None

    stop_res = monitor.evaluate(95.0)
    assert stop_res.triggered is True
    assert stop_res.trigger_type == StopTrigger.STOP_LOSS


def test_ac07_ac08_tighter_trailing_than_fixed_triggers_trailing() -> None:
    """AC08: Trigger TRAILING_STOP when trailing threshold is tighter than fixed stop."""
    monitor = StopMonitor(RiskConfig(stop_loss_pct=0.05, trailing_stop_pct=0.03))
    monitor.open_position(entry_price=100.0)

    res = monitor.evaluate(97.0)
    assert res.triggered is True
    assert res.trigger_type == StopTrigger.TRAILING_STOP


def test_ac10_lifecycle_and_invalid_inputs() -> None:
    """AC10: Enforce lifecycle guards and reject non-positive or non-finite prices."""
    monitor = StopMonitor()
    assert monitor.has_open_position is False
    assert monitor.entry_price is None
    assert monitor.highest_price is None
    assert monitor.fixed_stop_price is None
    assert monitor.trailing_stop_price is None

    with pytest.raises(InvalidRiskInputError, match="No open position"):
        monitor.evaluate(100.0)

    for bad_price in [0.0, -10.0, math.nan, math.inf, True]:
        with pytest.raises(InvalidRiskInputError):
            monitor.open_position(bad_price)

    monitor.open_position(50.0)
    assert monitor.has_open_position is True
    assert monitor.entry_price == pytest.approx(50.0)

    with pytest.raises(InvalidRiskInputError, match="already open"):
        monitor.open_position(55.0)

    for bad_price in [0.0, -1.0, math.nan, math.inf, False]:
        with pytest.raises(InvalidRiskInputError):
            monitor.evaluate(bad_price)

    monitor.close_position()
    assert monitor.has_open_position is False
    monitor.close_position()  # Idempotent close

    monitor.open_position(30.0)
    assert monitor.highest_price == pytest.approx(30.0)
    assert monitor.fixed_stop_price == pytest.approx(28.5)

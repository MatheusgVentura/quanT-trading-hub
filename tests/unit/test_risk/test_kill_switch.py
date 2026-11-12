"""Unit tests for KillSwitch daily loss, latency, drawdown, and reset logic (AC01, AC02, AC06, AC09, AC10)."""

import math
from datetime import date, datetime

import pytest

from src.risk.exceptions import InvalidRiskInputError, KillSwitchTriggeredError
from src.risk.kill_switch import KillSwitch
from src.risk.models import HaltReason, RiskConfig, RiskStatus


def test_ac01_daily_loss_limit_trips_and_auto_resets_next_day() -> None:
    """AC01: Trip at >= 2% daily loss, stay halted same day, auto-reset next trading session."""
    day1 = date(2026, 11, 11)
    day2 = date(2026, 11, 12)
    ks = KillSwitch(RiskConfig(initial_capital=100.0, max_daily_loss_pct=0.02))

    # 1.99% loss remains active
    s1 = ks.update(current_equity=98.01, current_date=day1, latency_ms=50.0)
    assert s1.status == RiskStatus.ACTIVE
    assert ks.is_halted is False

    # Exact 2.00% daily loss trips DAILY_LOSS_LIMIT
    s2 = ks.update(current_equity=98.0, current_date=day1, latency_ms=50.0)
    assert s2.status == RiskStatus.HALTED
    assert s2.reason == HaltReason.DAILY_LOSS_LIMIT
    assert s2.tripped_at_date == day1
    assert ks.is_halted is True

    # Intraday recovery on same day still stays halted
    s3 = ks.update(current_equity=99.0, current_date=day1, latency_ms=50.0)
    assert s3.status == RiskStatus.HALTED
    assert s3.reason == HaltReason.DAILY_LOSS_LIMIT

    # Next trading day auto-resets daily halt and uses previous close (99.0) as day baseline
    s4 = ks.update(current_equity=99.0, current_date=day2, latency_ms=50.0)
    assert s4.status == RiskStatus.ACTIVE
    assert s4.reason == HaltReason.NONE
    assert s4.tripped_at_date is None

    # Exact 2.00% drop on day2 (99.0 * 0.98 = 97.02) trips again
    s5 = ks.update(current_equity=97.02, current_date=day2, latency_ms=50.0)
    assert s5.status == RiskStatus.HALTED
    assert s5.reason == HaltReason.DAILY_LOSS_LIMIT
    assert s5.tripped_at_date == day2


def test_ac02_ac09_latency_limit_boundary_and_manual_reset() -> None:
    """AC02, AC09: Trip strictly above 500ms latency and require manual reset across dates."""
    day1 = date(2026, 11, 11)
    day2 = date(2026, 11, 12)
    ks = KillSwitch(RiskConfig(initial_capital=100.0, max_latency_ms=500.0))

    # Exact boundary 500.0ms does NOT trip
    ok = ks.update(current_equity=100.0, current_date=day1, latency_ms=500.0)
    assert ok.status == RiskStatus.ACTIVE

    # Strictly above 500ms trips LATENCY_LIMIT
    halted = ks.update(current_equity=100.0, current_date=day1, latency_ms=500.01)
    assert halted.status == RiskStatus.HALTED
    assert halted.reason == HaltReason.LATENCY_LIMIT
    assert halted.last_latency_ms == pytest.approx(500.01)

    # New session with normal latency remains HALTED (manual reset required)
    next_day = ks.update(current_equity=100.0, current_date=day2, latency_ms=40.0)
    assert next_day.status == RiskStatus.HALTED
    assert next_day.reason == HaltReason.LATENCY_LIMIT

    with pytest.raises(KillSwitchTriggeredError, match="confirm=True"):
        ks.reset(confirm=False)
    assert ks.is_halted is True

    restored = ks.reset(confirm=True)
    assert restored.status == RiskStatus.ACTIVE
    assert restored.reason == HaltReason.NONE


def test_ac06_ac09_max_drawdown_breaker_and_manual_reset() -> None:
    """AC06, AC09: Trip at >= 10% drawdown across sessions and re-anchor peak on manual reset."""
    ks = KillSwitch(
        RiskConfig(
            initial_capital=100.0,
            max_daily_loss_pct=0.05,  # Keep daily limit higher to isolate multi-day DD
            max_drawdown_pct=0.10,
        )
    )
    # Rally to 120.0 peak on day 1
    ks.update(current_equity=120.0, current_date=date(2026, 11, 11))
    # Drop ~3.5% per day across multiple days without tripping 5% daily limit
    ks.update(current_equity=116.0, current_date=date(2026, 11, 12))
    s_mid = ks.update(current_equity=112.0, current_date=date(2026, 11, 13))
    assert s_mid.status == RiskStatus.ACTIVE

    # 108.0 is -10.0% from 120.0 peak -> trips MAX_DRAWDOWN_LIMIT
    s_dd = ks.update(current_equity=108.0, current_date=date(2026, 11, 14))
    assert s_dd.status == RiskStatus.HALTED
    assert s_dd.reason == HaltReason.MAX_DRAWDOWN_LIMIT
    assert s_dd.drawdown_pct == pytest.approx(-0.10)

    # Next day stays halted until manual confirmation
    s_next = ks.update(current_equity=108.0, current_date=date(2026, 11, 15))
    assert s_next.status == RiskStatus.HALTED

    # Manual reset re-anchors peak at 108.0 so trading can resume cleanly
    restored = ks.reset(confirm=True)
    assert restored.status == RiskStatus.ACTIVE
    after_reset = ks.update(current_equity=108.0, current_date=date(2026, 11, 16))
    assert after_reset.status == RiskStatus.ACTIVE
    assert after_reset.drawdown_pct == pytest.approx(0.0)


def test_ac09_severe_breach_escalates_daily_halt() -> None:
    """AC09: Escalate DAILY_LOSS_LIMIT halt to LATENCY_LIMIT so next session cannot auto-reset."""
    day1 = date(2026, 11, 11)
    day2 = date(2026, 11, 12)
    ks = KillSwitch(RiskConfig(initial_capital=100.0))

    first_halt = ks.update(current_equity=98.0, current_date=day1, latency_ms=20.0)
    assert first_halt.reason == HaltReason.DAILY_LOSS_LIMIT

    escalated = ks.update(current_equity=98.0, current_date=day1, latency_ms=700.0)
    assert escalated.reason == HaltReason.LATENCY_LIMIT

    s2 = ks.update(current_equity=98.0, current_date=day2, latency_ms=20.0)
    assert s2.status == RiskStatus.HALTED
    assert s2.reason == HaltReason.LATENCY_LIMIT


def test_ac10_invalid_inputs_and_date_validation() -> None:
    """AC10: Reject invalid equity, latency, or non-monotonic dates with InvalidRiskInputError."""
    with pytest.raises(InvalidRiskInputError, match="initial_equity"):
        KillSwitch(initial_equity=0.0)

    with pytest.raises(InvalidRiskInputError, match="initial_equity"):
        KillSwitch(initial_equity=math.nan)

    ks = KillSwitch(RiskConfig(initial_capital=100.0))

    for bad_eq in [0.0, -50.0, math.nan, math.inf, True]:
        with pytest.raises(InvalidRiskInputError, match="current_equity"):
            ks.update(current_equity=bad_eq, current_date=date(2026, 11, 11))

    for bad_lat in [-1.0, math.nan, math.inf, False]:
        with pytest.raises(InvalidRiskInputError, match="latency_ms"):
            ks.update(
                current_equity=100.0,
                current_date=date(2026, 11, 11),
                latency_ms=bad_lat,
            )

    with pytest.raises(InvalidRiskInputError, match="datetime.date"):
        ks.update(
            current_equity=100.0,
            current_date="2026-11-11",  # type: ignore[arg-type]
        )

    # Accepts datetime and normalizes to date cleanly
    ks.update(current_equity=100.0, current_date=datetime(2026, 11, 11, 15, 30))
    with pytest.raises(InvalidRiskInputError, match="precede"):
        ks.update(current_equity=100.0, current_date=date(2026, 11, 10))

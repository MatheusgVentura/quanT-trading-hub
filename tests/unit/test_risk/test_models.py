"""Unit tests for risk management data models and configuration validation (AC01, AC02, AC03, AC10)."""

import math
from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from src.risk.exceptions import RiskConfigurationError
from src.risk.models import (
    HaltReason,
    KillSwitchState,
    PositionSizeResult,
    RiskConfig,
    RiskStatus,
    RiskVerdict,
)


def test_ac01_ac02_ac03_risk_config_defaults() -> None:
    """AC01, AC02, AC03: Verify default RiskConfig reflects PROJETO.md and approved defaults."""
    cfg = RiskConfig()

    assert cfg.initial_capital == 100.0
    assert cfg.b3_fee_pct == 0.0003
    assert cfg.lot_size == 1
    assert cfg.max_risk_per_trade_pct == 0.02
    assert cfg.max_position_pct == 1.0
    assert cfg.allow_min_lot_override is False
    assert cfg.stop_loss_pct == 0.05
    assert cfg.trailing_stop_pct == 0.05
    assert cfg.max_daily_loss_pct == 0.02
    assert cfg.max_drawdown_pct == 0.10
    assert cfg.max_latency_ms == 500.0
    assert cfg.allow_day_trade is False

    with pytest.raises(FrozenInstanceError):
        cfg.initial_capital = 200.0  # type: ignore[misc]


def test_ac10_trailing_stop_disabled_and_zero_fee_allowed() -> None:
    """AC10: Verify trailing_stop_pct=None and zero fee (b3_fee_pct=0.0) are permitted."""
    cfg = RiskConfig(
        b3_fee_pct=0.0,
        trailing_stop_pct=None,
        lot_size=100,
        max_risk_per_trade_pct=1.0,
    )
    assert cfg.b3_fee_pct == 0.0
    assert cfg.trailing_stop_pct is None
    assert cfg.lot_size == 100
    assert cfg.max_risk_per_trade_pct == 1.0


@pytest.mark.parametrize(
    ("kwargs", "match_text"),
    [
        ({"initial_capital": 0.0}, "initial_capital"),
        ({"initial_capital": -100.0}, "initial_capital"),
        ({"initial_capital": math.nan}, "initial_capital"),
        ({"initial_capital": math.inf}, "initial_capital"),
        ({"initial_capital": True}, "initial_capital"),
        ({"b3_fee_pct": -0.0001}, "b3_fee_pct"),
        ({"b3_fee_pct": 1.0}, "b3_fee_pct"),
        ({"lot_size": 0}, "lot_size"),
        ({"lot_size": -1}, "lot_size"),
        ({"lot_size": 1.5}, "lot_size"),
        ({"lot_size": True}, "lot_size"),
        ({"max_risk_per_trade_pct": 0.0}, "max_risk_per_trade_pct"),
        ({"max_risk_per_trade_pct": 1.1}, "max_risk_per_trade_pct"),
        ({"max_position_pct": 0.0}, "max_position_pct"),
        ({"max_position_pct": 1.05}, "max_position_pct"),
        ({"stop_loss_pct": 0.0}, "stop_loss_pct"),
        ({"stop_loss_pct": -0.05}, "stop_loss_pct"),
        ({"stop_loss_pct": 1.0}, "stop_loss_pct"),
        ({"trailing_stop_pct": 0.0}, "trailing_stop_pct"),
        ({"trailing_stop_pct": 1.0}, "trailing_stop_pct"),
        ({"trailing_stop_pct": math.nan}, "trailing_stop_pct"),
        ({"max_daily_loss_pct": 0.0}, "max_daily_loss_pct"),
        ({"max_daily_loss_pct": 1.0}, "max_daily_loss_pct"),
        ({"max_drawdown_pct": 0.0}, "max_drawdown_pct"),
        ({"max_drawdown_pct": 1.0}, "max_drawdown_pct"),
        ({"max_latency_ms": 0.0}, "max_latency_ms"),
        ({"max_latency_ms": -10.0}, "max_latency_ms"),
        ({"max_latency_ms": math.inf}, "max_latency_ms"),
        ({"allow_min_lot_override": 1}, "allow_min_lot_override"),
        ({"allow_day_trade": "no"}, "allow_day_trade"),
    ],
)
def test_ac10_invalid_risk_config_raises_error(
    kwargs: dict[str, object], match_text: str
) -> None:
    """AC10: Verify invalid or out-of-bounds parameters raise RiskConfigurationError."""
    with pytest.raises(RiskConfigurationError, match=match_text):
        RiskConfig(**kwargs)  # type: ignore[arg-type]


def test_ac01_ac02_verdict_and_state_models() -> None:
    """AC01, AC02: Verify immutable snapshots for KillSwitchState, PositionSizeResult, and RiskVerdict."""
    size_result = PositionSizeResult(
        shares=2,
        notional_value=79.20,
        estimated_fee=0.02376,
        risk_amount=3.96,
        allocation_pct=0.792,
        approved=True,
        reason="Approved within risk and cash bounds",
    )
    ks_state = KillSwitchState(
        status=RiskStatus.ACTIVE,
        reason=HaltReason.NONE,
        tripped_at_date=None,
        daily_pnl_pct=-0.005,
        drawdown_pct=-0.01,
        last_latency_ms=120.0,
        message="Risk controls healthy",
    )
    verdict = RiskVerdict(
        approved=True,
        action="BUY",
        shares=size_result.shares,
        weight=1.0,
        kill_switch_state=ks_state,
        reason=size_result.reason,
    )

    assert verdict.approved is True
    assert verdict.action == "BUY"
    assert verdict.kill_switch_state.status == RiskStatus.ACTIVE
    assert HaltReason.DAILY_LOSS_LIMIT.value == "DAILY_LOSS_LIMIT"

    halted_state = KillSwitchState(
        status=RiskStatus.HALTED,
        reason=HaltReason.LATENCY_LIMIT,
        tripped_at_date=date(2026, 11, 11),
        daily_pnl_pct=0.0,
        drawdown_pct=0.0,
        last_latency_ms=520.0,
        message="Latency exceeded 500ms",
    )
    assert halted_state.status == RiskStatus.HALTED

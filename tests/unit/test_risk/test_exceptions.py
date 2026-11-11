"""Unit tests for risk management domain exceptions (AC09, AC10)."""

import pytest

from src.risk.exceptions import (
    InvalidRiskInputError,
    KillSwitchTriggeredError,
    RiskConfigurationError,
    RiskError,
)


def test_ac10_risk_error_base() -> None:
    """AC10: Verify RiskError acts as the catchable base exception."""
    with pytest.raises(RiskError, match="Unexpected risk failure"):
        raise RiskError("Unexpected risk failure")


def test_ac10_risk_configuration_error_inheritance() -> None:
    """AC10: Verify RiskConfigurationError inherits from RiskError."""
    err = RiskConfigurationError("stop_loss_pct must be within (0, 1)")
    assert isinstance(err, RiskError)
    assert isinstance(err, Exception)
    assert str(err) == "stop_loss_pct must be within (0, 1)"


def test_ac10_invalid_risk_input_error_inheritance() -> None:
    """AC10: Verify InvalidRiskInputError inherits from RiskError."""
    err = InvalidRiskInputError("entry_price must be positive and finite")
    assert isinstance(err, RiskError)
    assert isinstance(err, Exception)
    assert "entry_price" in str(err)


def test_ac09_kill_switch_triggered_error_inheritance() -> None:
    """AC09: Verify KillSwitchTriggeredError inherits from RiskError."""
    err = KillSwitchTriggeredError("Cannot reset Kill-Switch without confirm=True")
    assert isinstance(err, RiskError)
    assert isinstance(err, Exception)
    assert "confirm=True" in str(err)

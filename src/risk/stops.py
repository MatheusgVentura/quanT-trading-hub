"""Stop-Loss and Trailing Stop position monitoring."""

import math
from dataclasses import dataclass
from enum import Enum

from src.risk.exceptions import InvalidRiskInputError
from src.risk.models import RiskConfig, require_finite_number


class StopTrigger(str, Enum):
    """Reason for a stop exit signal."""

    NONE = "NONE"
    STOP_LOSS = "STOP_LOSS"
    TRAILING_STOP = "TRAILING_STOP"


@dataclass(frozen=True)
class StopCheckResult:
    """Immutable snapshot of a stop-loss / trailing-stop evaluation."""

    triggered: bool
    trigger_type: StopTrigger
    entry_price: float
    highest_price: float
    fixed_stop_price: float
    trailing_stop_price: float | None
    current_price: float
    reason: str


def _validate_positive_price(value: object, field_name: str) -> float:
    """Validate that a price input is numeric, finite, and strictly positive."""
    price = require_finite_number(value, field_name, InvalidRiskInputError)
    if price <= 0.0:
        raise InvalidRiskInputError(
            f"{field_name} must be strictly positive, got {price}."
        )
    return price


def _is_breached(price: float, threshold: float) -> bool:
    """Check whether price breached or matched threshold within float precision."""
    return price <= threshold or math.isclose(
        price, threshold, rel_tol=1e-12, abs_tol=0.0
    )


class StopMonitor:
    """Tracks an open long position's fixed Stop-Loss and high-water Trailing Stop."""

    def __init__(self, config: RiskConfig | None = None) -> None:
        """Initialize the StopMonitor with risk thresholds.

        Args:
            config: Risk configuration supplying stop_loss_pct and trailing_stop_pct.
        """
        self.config = config or RiskConfig()
        self._entry_price: float | None = None
        self._highest_price: float | None = None

    @property
    def has_open_position(self) -> bool:
        """Return True when a position is currently registered."""
        return self._entry_price is not None

    @property
    def entry_price(self) -> float | None:
        """Return registered entry price, or None when flat."""
        return self._entry_price

    @property
    def highest_price(self) -> float | None:
        """Return highest price observed since entry, or None when flat."""
        return self._highest_price

    @property
    def fixed_stop_price(self) -> float | None:
        """Return active fixed stop-loss price threshold, or None when flat."""
        if self._entry_price is None:
            return None
        return self._entry_price * (1.0 - self.config.stop_loss_pct)

    @property
    def trailing_stop_price(self) -> float | None:
        """Return active trailing stop price threshold, or None if disabled or flat."""
        if self._highest_price is None or self.config.trailing_stop_pct is None:
            return None
        return self._highest_price * (1.0 - self.config.trailing_stop_pct)

    def open_position(self, entry_price: float) -> None:
        """Register a new open long position and initialize high-water mark.

        Args:
            entry_price: Execution price of the new long position.

        Raises:
            InvalidRiskInputError: If entry_price is invalid or a position is already open.
        """
        if self._entry_price is not None:
            raise InvalidRiskInputError(
                "Position is already open; call close_position() before opening a new one."
            )
        price = _validate_positive_price(entry_price, "entry_price")
        self._entry_price = price
        self._highest_price = price

    def close_position(self) -> None:
        """Clear open position and high-water mark state."""
        self._entry_price = None
        self._highest_price = None

    def evaluate(self, current_price: float) -> StopCheckResult:
        """Update high-water mark and evaluate fixed and trailing stop thresholds.

        Args:
            current_price: Latest market price for the monitored asset.

        Returns:
            StopCheckResult indicating whether an exit stop triggered.

        Raises:
            InvalidRiskInputError: If no position is open or current_price is invalid.
        """
        if self._entry_price is None or self._highest_price is None:
            raise InvalidRiskInputError(
                "No open position registered to evaluate stops against."
            )

        price = _validate_positive_price(current_price, "current_price")
        self._highest_price = max(self._highest_price, price)

        fixed_stop = self._entry_price * (1.0 - self.config.stop_loss_pct)
        trailing_stop = (
            self._highest_price * (1.0 - self.config.trailing_stop_pct)
            if self.config.trailing_stop_pct is not None
            else None
        )

        if _is_breached(price, fixed_stop):
            triggered = True
            trigger_type = StopTrigger.STOP_LOSS
            reason = f"Fixed stop-loss breached ({price:.4f} <= {fixed_stop:.4f})"
        elif trailing_stop is not None and _is_breached(price, trailing_stop):
            triggered = True
            trigger_type = StopTrigger.TRAILING_STOP
            reason = f"Trailing stop breached ({price:.4f} <= {trailing_stop:.4f})"
        else:
            triggered = False
            trigger_type = StopTrigger.NONE
            reason = "Position within stop thresholds"

        return StopCheckResult(
            triggered=triggered,
            trigger_type=trigger_type,
            entry_price=self._entry_price,
            highest_price=self._highest_price,
            fixed_stop_price=fixed_stop,
            trailing_stop_price=trailing_stop,
            current_price=price,
            reason=reason,
        )

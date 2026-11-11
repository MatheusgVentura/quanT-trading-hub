"""Data models and validated configuration for risk management."""

import math
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Literal

from src.risk.exceptions import RiskConfigurationError, RiskError


class RiskStatus(str, Enum):
    """Operational state of the risk management Kill-Switch."""

    ACTIVE = "ACTIVE"
    HALTED = "HALTED"


class HaltReason(str, Enum):
    """Enumerated cause for a Kill-Switch operational halt."""

    NONE = "NONE"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    MAX_DRAWDOWN_LIMIT = "MAX_DRAWDOWN_LIMIT"
    LATENCY_LIMIT = "LATENCY_LIMIT"


def require_finite_number(
    value: object,
    field_name: str,
    exc_cls: type[RiskError] = RiskConfigurationError,
) -> float:
    """Validate that a value is a non-boolean finite float/int."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise exc_cls(f"{field_name} must be a numeric value.")
    num = float(value)
    if not math.isfinite(num):
        raise exc_cls(f"{field_name} must be finite.")
    return num


def _validate_range(
    value: object,
    field_name: str,
    *,
    min_val: float,
    max_val: float,
    min_inclusive: bool = False,
    max_inclusive: bool = False,
) -> float:
    """Validate that a numeric parameter lies within the expected interval."""
    num = require_finite_number(value, field_name)
    lower_ok = num >= min_val if min_inclusive else num > min_val
    upper_ok = num <= max_val if max_inclusive else num < max_val
    if not (lower_ok and upper_ok):
        left = "[" if min_inclusive else "("
        right = "]" if max_inclusive else ")"
        raise RiskConfigurationError(
            f"{field_name} must be in {left}{min_val}, {max_val}{right}, got {num}."
        )
    return num


@dataclass(frozen=True)
class RiskConfig:
    """Validated configuration governing position sizing, stops, and circuit breakers."""

    initial_capital: float = 100.0
    b3_fee_pct: float = 0.0003
    lot_size: int = 1
    max_risk_per_trade_pct: float = 0.02
    max_position_pct: float = 1.0
    allow_min_lot_override: bool = False
    stop_loss_pct: float = 0.05
    trailing_stop_pct: float | None = 0.05
    max_daily_loss_pct: float = 0.02
    max_drawdown_pct: float = 0.10
    max_latency_ms: float = 500.0
    allow_day_trade: bool = False

    def __post_init__(self) -> None:
        """Validate all configuration parameters on instantiation."""
        cap = require_finite_number(self.initial_capital, "initial_capital")
        if cap <= 0.0:
            raise RiskConfigurationError(
                f"initial_capital must be strictly positive, got {cap}."
            )

        _validate_range(
            self.b3_fee_pct,
            "b3_fee_pct",
            min_val=0.0,
            max_val=1.0,
            min_inclusive=True,
            max_inclusive=False,
        )

        if type(self.lot_size) is not int or self.lot_size < 1:
            raise RiskConfigurationError(
                f"lot_size must be an integer >= 1, got {self.lot_size!r}."
            )

        _validate_range(
            self.max_risk_per_trade_pct,
            "max_risk_per_trade_pct",
            min_val=0.0,
            max_val=1.0,
            min_inclusive=False,
            max_inclusive=True,
        )
        _validate_range(
            self.max_position_pct,
            "max_position_pct",
            min_val=0.0,
            max_val=1.0,
            min_inclusive=False,
            max_inclusive=True,
        )

        if type(self.allow_min_lot_override) is not bool:
            raise RiskConfigurationError("allow_min_lot_override must be a boolean.")
        if type(self.allow_day_trade) is not bool:
            raise RiskConfigurationError("allow_day_trade must be a boolean.")

        _validate_range(
            self.stop_loss_pct,
            "stop_loss_pct",
            min_val=0.0,
            max_val=1.0,
            min_inclusive=False,
            max_inclusive=False,
        )

        if self.trailing_stop_pct is not None:
            _validate_range(
                self.trailing_stop_pct,
                "trailing_stop_pct",
                min_val=0.0,
                max_val=1.0,
                min_inclusive=False,
                max_inclusive=False,
            )

        _validate_range(
            self.max_daily_loss_pct,
            "max_daily_loss_pct",
            min_val=0.0,
            max_val=1.0,
            min_inclusive=False,
            max_inclusive=False,
        )
        _validate_range(
            self.max_drawdown_pct,
            "max_drawdown_pct",
            min_val=0.0,
            max_val=1.0,
            min_inclusive=False,
            max_inclusive=False,
        )

        latency = require_finite_number(self.max_latency_ms, "max_latency_ms")
        if latency <= 0.0:
            raise RiskConfigurationError(
                f"max_latency_ms must be strictly positive, got {latency}."
            )


@dataclass(frozen=True)
class PositionSizeResult:
    """Result of position sizing computation for a prospective trade."""

    shares: int
    notional_value: float
    estimated_fee: float
    risk_amount: float
    allocation_pct: float
    approved: bool
    reason: str


@dataclass(frozen=True)
class KillSwitchState:
    """Immutable snapshot of the Kill-Switch circuit-breaker state."""

    status: RiskStatus
    reason: HaltReason
    tripped_at_date: date | None
    daily_pnl_pct: float
    drawdown_pct: float
    last_latency_ms: float
    message: str


@dataclass(frozen=True)
class RiskVerdict:
    """Unified pre-trade validation decision returned by the RiskManager."""

    approved: bool
    action: Literal["BUY", "HOLD", "EXIT", "HALT"]
    shares: int
    weight: float
    kill_switch_state: KillSwitchState
    reason: str

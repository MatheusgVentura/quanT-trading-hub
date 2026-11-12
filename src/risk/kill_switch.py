"""Operational Kill-Switch circuit breaker for daily loss, drawdown, and latency."""

import math
from datetime import date, datetime

from src.risk.exceptions import InvalidRiskInputError, KillSwitchTriggeredError
from src.risk.models import (
    HaltReason,
    KillSwitchState,
    RiskConfig,
    RiskStatus,
    require_finite_number,
)


def _is_limit_breached(loss_pct: float, limit_pct: float) -> bool:
    """Return True when loss meets or exceeds limit within float tolerance."""
    return loss_pct >= limit_pct or math.isclose(
        loss_pct, limit_pct, rel_tol=0.0, abs_tol=1e-12
    )


class KillSwitch:
    """Fail-closed circuit breaker monitoring daily PnL, drawdown, and latency."""

    def __init__(
        self,
        config: RiskConfig | None = None,
        initial_equity: float | None = None,
    ) -> None:
        """Initialize KillSwitch with risk limits and starting equity reference.

        Args:
            config: Validated RiskConfig supplying loss, drawdown, and latency limits.
            initial_equity: Optional starting equity; defaults to config.initial_capital.

        Raises:
            InvalidRiskInputError: If initial_equity is non-positive or non-finite.
        """
        self.config = config or RiskConfig()
        start_eq = (
            self.config.initial_capital
            if initial_equity is None
            else require_finite_number(
                initial_equity, "initial_equity", InvalidRiskInputError
            )
        )
        if start_eq <= 0.0:
            raise InvalidRiskInputError(
                f"initial_equity must be strictly positive, got {start_eq}."
            )

        self._peak_equity: float = start_eq
        self._day_start_equity: float = start_eq
        self._last_equity: float = start_eq
        self._last_date: date | None = None
        self._state = KillSwitchState(
            status=RiskStatus.ACTIVE,
            reason=HaltReason.NONE,
            tripped_at_date=None,
            daily_pnl_pct=0.0,
            drawdown_pct=0.0,
            last_latency_ms=0.0,
            message="Kill-Switch active",
        )

    @property
    def state(self) -> KillSwitchState:
        """Return the latest immutable KillSwitchState snapshot."""
        return self._state

    @property
    def is_halted(self) -> bool:
        """Return True when trading is currently halted."""
        return self._state.status == RiskStatus.HALTED

    def _validate_telemetry(
        self, current_equity: float, current_date: date, latency_ms: float
    ) -> tuple[float, date, float]:
        """Validate incoming equity, date monotonicity, and latency telemetry."""
        equity = require_finite_number(
            current_equity, "current_equity", InvalidRiskInputError
        )
        if equity <= 0.0:
            raise InvalidRiskInputError(
                f"current_equity must be strictly positive, got {equity}."
            )

        latency = require_finite_number(latency_ms, "latency_ms", InvalidRiskInputError)
        if latency < 0.0:
            raise InvalidRiskInputError(
                f"latency_ms cannot be negative, got {latency}."
            )

        if not isinstance(current_date, date):
            raise InvalidRiskInputError("current_date must be a datetime.date.")
        obs_date = (
            current_date.date() if isinstance(current_date, datetime) else current_date
        )
        if self._last_date is not None and obs_date < self._last_date:
            raise InvalidRiskInputError(
                f"current_date ({obs_date}) cannot precede last observed date ({self._last_date})."
            )

        return equity, obs_date, latency

    def _roll_trading_day_if_needed(self, current_date: date) -> None:
        """Roll day baseline forward and auto-reset DAILY_LOSS_LIMIT on a new date."""
        if self._last_date is None:
            self._last_date = current_date
            return

        if current_date > self._last_date:
            self._day_start_equity = self._last_equity
            self._last_date = current_date
            if (
                self._state.status == RiskStatus.HALTED
                and self._state.reason == HaltReason.DAILY_LOSS_LIMIT
            ):
                self._state = KillSwitchState(
                    status=RiskStatus.ACTIVE,
                    reason=HaltReason.NONE,
                    tripped_at_date=None,
                    daily_pnl_pct=0.0,
                    drawdown_pct=self._state.drawdown_pct,
                    last_latency_ms=self._state.last_latency_ms,
                    message=f"Auto-reset daily Kill-Switch on new session {current_date}",
                )

    def _detect_new_breach(
        self, daily_pnl_pct: float, drawdown_pct: float, latency_ms: float
    ) -> tuple[HaltReason, str] | None:
        """Check circuit-breaker limits ordered from severe/manual to auto-resettable."""
        if latency_ms > self.config.max_latency_ms:
            return (
                HaltReason.LATENCY_LIMIT,
                f"Latency ({latency_ms:.1f}ms) exceeded {self.config.max_latency_ms:.1f}ms limit",
            )
        if _is_limit_breached(-drawdown_pct, self.config.max_drawdown_pct):
            return (
                HaltReason.MAX_DRAWDOWN_LIMIT,
                f"Max drawdown ({-drawdown_pct * 100:.2f}%) breached {self.config.max_drawdown_pct * 100:.2f}% limit",
            )
        if _is_limit_breached(-daily_pnl_pct, self.config.max_daily_loss_pct):
            return (
                HaltReason.DAILY_LOSS_LIMIT,
                f"Daily loss ({-daily_pnl_pct * 100:.2f}%) breached {self.config.max_daily_loss_pct * 100:.2f}% limit",
            )
        return None

    def update(
        self,
        current_equity: float,
        current_date: date,
        latency_ms: float = 0.0,
    ) -> KillSwitchState:
        """Evaluate latest equity and latency snapshot against circuit-breaker thresholds.

        Args:
            current_equity: Current account equity mark-to-market.
            current_date: Calendar date of the observation.
            latency_ms: Latest market-feed or broker round-trip latency in milliseconds.

        Returns:
            Updated KillSwitchState snapshot.

        Raises:
            InvalidRiskInputError: If equity, date, or latency inputs are invalid.
        """
        equity, obs_date, latency = self._validate_telemetry(
            current_equity, current_date, latency_ms
        )
        self._roll_trading_day_if_needed(obs_date)

        self._peak_equity = max(self._peak_equity, equity)
        self._last_equity = equity

        daily_pnl_pct = (equity - self._day_start_equity) / self._day_start_equity
        drawdown_pct = (equity - self._peak_equity) / self._peak_equity

        breach = self._detect_new_breach(daily_pnl_pct, drawdown_pct, latency)
        if breach is not None and (
            not self.is_halted
            or (
                self._state.reason == HaltReason.DAILY_LOSS_LIMIT
                and breach[0] != HaltReason.DAILY_LOSS_LIMIT
            )
        ):
            status = RiskStatus.HALTED
            reason, message = breach
            tripped_at: date | None = obs_date
        elif self.is_halted:
            status = RiskStatus.HALTED
            reason = self._state.reason
            tripped_at = self._state.tripped_at_date
            message = self._state.message
        else:
            status = RiskStatus.ACTIVE
            reason = HaltReason.NONE
            tripped_at = None
            message = "Kill-Switch active"

        self._state = KillSwitchState(
            status=status,
            reason=reason,
            tripped_at_date=tripped_at,
            daily_pnl_pct=daily_pnl_pct,
            drawdown_pct=drawdown_pct,
            last_latency_ms=latency,
            message=message,
        )
        return self._state

    def reset(self, confirm: bool = False) -> KillSwitchState:
        """Manually reset a halted Kill-Switch with explicit operator confirmation.

        Args:
            confirm: Must be strictly True to acknowledge and clear the halt.

        Returns:
            Restored ACTIVE KillSwitchState snapshot.

        Raises:
            KillSwitchTriggeredError: If confirm is not strictly True.
        """
        if confirm is not True:
            raise KillSwitchTriggeredError(
                "Manual Kill-Switch reset requires confirm=True."
            )

        if self._state.reason == HaltReason.MAX_DRAWDOWN_LIMIT:
            self._peak_equity = self._last_equity
            self._day_start_equity = self._last_equity
        elif self._state.reason == HaltReason.DAILY_LOSS_LIMIT:
            self._day_start_equity = self._last_equity

        self._state = KillSwitchState(
            status=RiskStatus.ACTIVE,
            reason=HaltReason.NONE,
            tripped_at_date=None,
            daily_pnl_pct=0.0
            if self._state.reason
            in (HaltReason.DAILY_LOSS_LIMIT, HaltReason.MAX_DRAWDOWN_LIMIT)
            else self._state.daily_pnl_pct,
            drawdown_pct=0.0
            if self._state.reason == HaltReason.MAX_DRAWDOWN_LIMIT
            else self._state.drawdown_pct,
            last_latency_ms=self._state.last_latency_ms,
            message="Kill-Switch manually reset by operator",
        )
        return self._state

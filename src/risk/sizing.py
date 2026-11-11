"""Position sizing calculator for B3 fractional and standard lots."""

import math

from src.risk.exceptions import InvalidRiskInputError
from src.risk.models import PositionSizeResult, RiskConfig, require_finite_number


class PositionSizer:
    """Calculates discrete B3 lot sizes bounded by risk budget, allocation cap, and cash."""

    def __init__(self, config: RiskConfig | None = None) -> None:
        """Initialize the PositionSizer with validated risk rules.

        Args:
            config: Risk configuration. Defaults to B3 R$ 100 fractional settings.
        """
        self.config = config or RiskConfig()

    def _build_result(
        self,
        *,
        shares: int,
        entry_price: float,
        risk_per_share: float,
        capital: float,
        approved: bool,
        reason: str,
    ) -> PositionSizeResult:
        """Construct an immutable PositionSizeResult from discrete share count."""
        notional = shares * entry_price
        fee = notional * self.config.b3_fee_pct
        risk_amount = shares * risk_per_share
        allocation_pct = notional / capital if capital > 0.0 else 0.0
        return PositionSizeResult(
            shares=shares,
            notional_value=notional,
            estimated_fee=fee,
            risk_amount=risk_amount,
            allocation_pct=allocation_pct,
            approved=approved,
            reason=reason,
        )

    def _validate_inputs(
        self,
        entry_price: float,
        stop_loss_price: float | None,
        capital: float | None,
        available_cash: float | None,
    ) -> tuple[float, float, float, float]:
        """Validate and resolve pricing and account capital inputs."""
        entry = require_finite_number(entry_price, "entry_price", InvalidRiskInputError)
        if entry <= 0.0:
            raise InvalidRiskInputError(
                f"entry_price must be strictly positive, got {entry}."
            )

        cap = (
            self.config.initial_capital
            if capital is None
            else require_finite_number(capital, "capital", InvalidRiskInputError)
        )
        if cap <= 0.0:
            raise InvalidRiskInputError(
                f"capital must be strictly positive, got {cap}."
            )

        cash = (
            cap
            if available_cash is None
            else require_finite_number(
                available_cash, "available_cash", InvalidRiskInputError
            )
        )
        if cash < 0.0:
            raise InvalidRiskInputError(
                f"available_cash cannot be negative, got {cash}."
            )

        if stop_loss_price is None:
            stop = entry * (1.0 - self.config.stop_loss_pct)
        else:
            stop = require_finite_number(
                stop_loss_price, "stop_loss_price", InvalidRiskInputError
            )
            if stop <= 0.0 or stop >= entry:
                raise InvalidRiskInputError(
                    f"stop_loss_price ({stop}) must satisfy 0 < stop_loss_price < entry_price ({entry})."
                )

        return entry, stop, cap, cash

    @staticmethod
    def _floor_shares_for_budget(budget: float, unit_cost: float) -> int:
        """Return integer share count fitting within budget without float overshoot."""
        shares = math.floor(budget / unit_cost)
        if shares > 0 and shares * unit_cost > budget:
            shares -= 1
        return shares

    def calculate(
        self,
        entry_price: float,
        stop_loss_price: float | None = None,
        capital: float | None = None,
        available_cash: float | None = None,
    ) -> PositionSizeResult:
        """Calculate approved integer shares respecting B3 lot size, fees, cash, and risk budget.

        Args:
            entry_price: Expected execution price per share.
            stop_loss_price: Explicit stop price. If None, uses config.stop_loss_pct.
            capital: Total account equity used for risk and allocation ratios.
            available_cash: Liquid cash available to fund notional + B3 fee.

        Returns:
            PositionSizeResult with integer share count and approval decision.

        Raises:
            InvalidRiskInputError: If prices, capital, or cash violate physical bounds.
        """
        entry, stop, cap, cash = self._validate_inputs(
            entry_price, stop_loss_price, capital, available_cash
        )

        lot_size = self.config.lot_size
        cost_per_share = entry * (1.0 + self.config.b3_fee_pct)
        risk_per_share = entry - stop

        max_shares_cash = self._floor_shares_for_budget(cash, cost_per_share)
        max_shares_alloc = self._floor_shares_for_budget(
            cap * self.config.max_position_pct, cost_per_share
        )

        max_affordable_lots = min(max_shares_cash, max_shares_alloc) // lot_size
        if max_affordable_lots == 0:
            reason = (
                "Insufficient cash for 1 lot"
                if max_shares_cash < lot_size
                else "Position exceeds max_position_pct limit for 1 lot"
            )
            return self._build_result(
                shares=0,
                entry_price=entry,
                risk_per_share=risk_per_share,
                capital=cap,
                approved=False,
                reason=reason,
            )

        risk_budget = cap * self.config.max_risk_per_trade_pct
        max_shares_risk = math.floor(risk_budget / risk_per_share)
        risk_lots = max_shares_risk // lot_size

        if risk_lots == 0:
            if not self.config.allow_min_lot_override:
                return self._build_result(
                    shares=0,
                    entry_price=entry,
                    risk_per_share=risk_per_share,
                    capital=cap,
                    approved=False,
                    reason="1 lot exceeds max_risk_per_trade_pct budget",
                )
            return self._build_result(
                shares=lot_size,
                entry_price=entry,
                risk_per_share=risk_per_share,
                capital=cap,
                approved=True,
                reason="Approved via allow_min_lot_override (1 lot)",
            )

        chosen_shares = min(max_affordable_lots, risk_lots) * lot_size
        return self._build_result(
            shares=chosen_shares,
            entry_price=entry,
            risk_per_share=risk_per_share,
            capital=cap,
            approved=True,
            reason="Approved within risk and cash limits",
        )

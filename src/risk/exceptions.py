"""Domain exceptions for the risk management layer."""


class RiskError(Exception):
    """Base exception for errors in the risk management domain."""


class RiskConfigurationError(RiskError):
    """Raised when risk management configuration parameters are invalid."""


class InvalidRiskInputError(RiskError):
    """Raised when market, position, or telemetry inputs fail validation."""


class KillSwitchTriggeredError(RiskError):
    """Raised when execution is blocked by an active Kill-Switch or invalid reset."""

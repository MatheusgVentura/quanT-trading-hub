"""Domain exceptions for the execution and paper trading layer."""


class ExecutionError(Exception):
    """Base exception for errors in the execution and paper trading domain."""


class ExecutionConfigurationError(ExecutionError):
    """Raised when execution configuration parameters are invalid."""


class InvalidOrderError(ExecutionError):
    """Raised when order, price, or execution state inputs fail validation."""


class BrokerConnectionError(ExecutionError):
    """Raised when broker transport connectivity or retries are exhausted."""


class OrderRejectedError(ExecutionError):
    """Raised when an order is rejected by risk, cash constraints, or broker rules."""


class ExecutionHaltedError(ExecutionError):
    """Raised when execution is halted by an active Kill-Switch emergency event."""

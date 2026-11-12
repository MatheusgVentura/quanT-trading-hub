"""Unit tests for execution domain exceptions (AC08, AC03)."""

import pytest

from src.execution import (
    BrokerConnectionError,
    ExecutionConfigurationError,
    ExecutionError,
    ExecutionHaltedError,
    InvalidOrderError,
    OrderRejectedError,
)


def test_ac08_execution_error_base() -> None:
    """AC08: Verify ExecutionError acts as the catchable base exception."""
    with pytest.raises(ExecutionError, match="Unexpected execution failure"):
        raise ExecutionError("Unexpected execution failure")


@pytest.mark.parametrize(
    ("exc_cls", "message"),
    [
        (
            ExecutionConfigurationError,
            "max_retries must be a non-negative integer",
        ),
        (InvalidOrderError, "shares must be strictly positive"),
        (BrokerConnectionError, "Broker connection timed out after retries"),
        (OrderRejectedError, "Insufficient cash for buy fill"),
        (ExecutionHaltedError, "Kill-Switch tripped LATENCY_LIMIT"),
    ],
)
def test_ac08_execution_exception_hierarchy(
    exc_cls: type[ExecutionError], message: str
) -> None:
    """AC08: Verify all typed execution exceptions inherit from ExecutionError."""
    err = exc_cls(message)
    assert isinstance(err, ExecutionError)
    assert isinstance(err, Exception)
    assert str(err) == message

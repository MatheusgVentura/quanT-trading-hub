"""Testes unitários para a hierarquia de exceções de estratégias."""

import pytest

from src.strategies.exceptions import (
    InsufficientDataError,
    InvalidParameterError,
    StrategyError,
)


def test_ac08_invalid_parameter_error_inheritance() -> None:
    """AC08: Valida que InvalidParameterError herda de StrategyError."""
    err = InvalidParameterError("fast_period must be >= 2")
    assert isinstance(err, StrategyError)
    assert isinstance(err, Exception)
    assert str(err) == "fast_period must be >= 2"


def test_ac09_insufficient_data_error_inheritance() -> None:
    """AC09: Valida que InsufficientDataError herda de StrategyError."""
    err = InsufficientDataError("Historical series has fewer rows than slow_period")
    assert isinstance(err, StrategyError)
    assert isinstance(err, Exception)


def test_ac12_strategy_error_base() -> None:
    """AC12: Valida que StrategyError pode ser capturada como exceção base."""
    with pytest.raises(StrategyError, match="Missing Close column"):
        raise StrategyError("Missing Close column")

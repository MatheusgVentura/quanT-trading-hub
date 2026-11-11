"""Unit tests for B3 position sizing calculator (AC03, AC05, AC10)."""

import math

import pytest

from src.risk.exceptions import InvalidRiskInputError
from src.risk.models import RiskConfig
from src.risk.sizing import PositionSizer


def test_ac03_ac05_r100_fractional_sizing_itub4f_example() -> None:
    """AC03, AC05: Verify R$ 100 fractional sizing for ITUB4F (~R$ 39.60) under strict 2% risk."""
    sizer = (
        PositionSizer()
    )  # Default: R$ 100, lot_size=1, 2% risk, 5% stop, 0.03% B3 fee
    result = sizer.calculate(entry_price=39.60)

    assert result.approved is True
    assert result.shares == 1
    assert result.notional_value == pytest.approx(39.60)
    assert result.estimated_fee == pytest.approx(39.60 * 0.0003)
    assert result.notional_value + result.estimated_fee <= 100.0
    assert result.risk_amount <= 100.0 * 0.02 + 1e-12
    assert result.allocation_pct == pytest.approx(0.396)


def test_ac05_strict_2pct_risk_rejects_when_one_share_exceeds_budget() -> None:
    """AC05: Reject trade when 1 integer share exceeds R$ 2.00 risk budget under strict mode."""
    sizer = PositionSizer(
        RiskConfig(initial_capital=100.0, allow_min_lot_override=False)
    )
    # R$ 55.00 with 5% stop = R$ 2.75 risk/share (> R$ 2.00 budget)
    result = sizer.calculate(entry_price=55.00)

    assert result.approved is False
    assert result.shares == 0
    assert result.notional_value == 0.0
    assert "max_risk_per_trade_pct" in result.reason


def test_ac05_min_lot_override_allows_one_share_when_cash_suffices() -> None:
    """AC05: Allow 1 minimum lot when allow_min_lot_override=True and cash covers outlay."""
    sizer = PositionSizer(
        RiskConfig(initial_capital=100.0, allow_min_lot_override=True)
    )
    result = sizer.calculate(entry_price=55.00)

    assert result.approved is True
    assert result.shares == 1
    assert result.notional_value == pytest.approx(55.00)
    assert result.risk_amount == pytest.approx(2.75)
    assert "allow_min_lot_override" in result.reason


def test_ac03_insufficient_cash_for_one_share() -> None:
    """AC03: Reject trade safely when share price exceeds available cash, even with override."""
    sizer = PositionSizer(
        RiskConfig(initial_capital=100.0, allow_min_lot_override=True)
    )
    result = sizer.calculate(entry_price=105.00)

    assert result.approved is False
    assert result.shares == 0
    assert "Insufficient cash" in result.reason


def test_ac03_b3_fee_prevents_cash_overflow() -> None:
    """AC03: Ensure B3 0.03% fee buffer prevents buying 2 shares at R$ 50.00 on R$ 100 cash."""
    sizer = PositionSizer(
        RiskConfig(
            initial_capital=100.0,
            b3_fee_pct=0.0003,
            max_risk_per_trade_pct=0.20,
        )
    )
    result = sizer.calculate(entry_price=50.00, stop_loss_price=45.00)

    # 2 shares * 50.00 * 1.0003 = 100.03 > 100.00, so must cap at 1 share
    assert result.approved is True
    assert result.shares == 1
    assert result.notional_value + result.estimated_fee <= 100.0


def test_ac03_standard_lot_100_rounding() -> None:
    """AC03: Verify standard B3 lot rounding (lot_size=100) floors down to multiples of 100."""
    sizer = PositionSizer(
        RiskConfig(
            initial_capital=10_000.0,
            lot_size=100,
            max_risk_per_trade_pct=0.02,
            stop_loss_pct=0.02,
        )
    )
    # 10,000 * 0.02 = 200 risk budget; 39.60 * 0.02 = 0.792 risk/share -> 252 shares -> 2 lots
    result = sizer.calculate(entry_price=39.60)

    assert result.approved is True
    assert result.shares == 200
    assert result.shares % 100 == 0
    assert result.notional_value + result.estimated_fee <= 10_000.0


def test_ac05_explicit_stop_and_max_position_cap() -> None:
    """AC05: Verify explicit stop_loss_price and max_position_pct capping."""
    sizer = PositionSizer(
        RiskConfig(
            initial_capital=100.0,
            max_risk_per_trade_pct=0.02,
            max_position_pct=0.50,  # Max R$ 50 exposure
        )
    )
    # Tight stop: risk/share = 0.20 -> risk allows 10 shares (R$ 200), but alloc cap (R$ 50) caps at 2
    result = sizer.calculate(entry_price=20.00, stop_loss_price=19.80)

    assert result.approved is True
    assert result.shares == 2
    assert result.notional_value == pytest.approx(40.00)


def test_ac03_position_exceeds_max_position_pct_for_one_lot() -> None:
    """AC03: Reject trade when even 1 lot exceeds max_position_pct allocation cap."""
    sizer = PositionSizer(
        RiskConfig(
            initial_capital=100.0,
            max_position_pct=0.30,  # Max R$ 30 per position
            allow_min_lot_override=True,
        )
    )
    result = sizer.calculate(entry_price=40.00)

    assert result.approved is False
    assert result.shares == 0
    assert "max_position_pct" in result.reason


def test_ac03_available_cash_lower_than_equity() -> None:
    """AC03: Respect liquid available_cash even when total capital is higher."""
    sizer = PositionSizer(RiskConfig(initial_capital=1000.0))
    res_low_cash = sizer.calculate(
        entry_price=30.00, stop_loss_price=29.00, capital=1000.0, available_cash=40.0
    )
    assert res_low_cash.approved is True
    assert res_low_cash.shares == 1

    res_zero_cash = sizer.calculate(
        entry_price=30.00, stop_loss_price=29.00, capital=1000.0, available_cash=0.0
    )
    assert res_zero_cash.approved is False
    assert res_zero_cash.shares == 0


@pytest.mark.parametrize(
    ("kwargs", "match_text"),
    [
        ({"entry_price": 0.0}, "entry_price"),
        ({"entry_price": -10.0}, "entry_price"),
        ({"entry_price": math.nan}, "entry_price"),
        ({"entry_price": math.inf}, "entry_price"),
        ({"entry_price": True}, "entry_price"),
        ({"entry_price": 50.0, "stop_loss_price": 50.0}, "stop_loss_price"),
        ({"entry_price": 50.0, "stop_loss_price": 55.0}, "stop_loss_price"),
        ({"entry_price": 50.0, "stop_loss_price": 0.0}, "stop_loss_price"),
        ({"entry_price": 50.0, "stop_loss_price": -5.0}, "stop_loss_price"),
        ({"entry_price": 50.0, "stop_loss_price": math.nan}, "stop_loss_price"),
        ({"entry_price": 50.0, "capital": 0.0}, "capital"),
        ({"entry_price": 50.0, "capital": -100.0}, "capital"),
        ({"entry_price": 50.0, "available_cash": -0.01}, "available_cash"),
        ({"entry_price": 50.0, "available_cash": math.inf}, "available_cash"),
    ],
)
def test_ac10_invalid_sizing_inputs_raise_error(
    kwargs: dict[str, object], match_text: str
) -> None:
    """AC10: Reject invalid prices, stops, capital, or cash with InvalidRiskInputError."""
    sizer = PositionSizer()
    with pytest.raises(InvalidRiskInputError, match=match_text):
        sizer.calculate(**kwargs)  # type: ignore[arg-type]

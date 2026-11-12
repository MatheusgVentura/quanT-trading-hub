"""Unit tests for execution models, symbol formatting, and IBrokerAdapter (AC05, AC08)."""

import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from src.execution import (
    AccountSnapshot,
    ExecutionConfig,
    ExecutionConfigurationError,
    ExecutionStepResult,
    IBrokerAdapter,
    InvalidOrderError,
    OrderReceipt,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSnapshot,
    format_b3_execution_symbol,
)
from src.risk.models import HaltReason, KillSwitchState, RiskStatus, RiskVerdict


def test_ac05_execution_config_defaults_and_state_path_normalization() -> None:
    """AC05: Verify default R$ 100 B3 ExecutionConfig and string-to-Path normalization."""
    cfg = ExecutionConfig()
    assert cfg.initial_cash == 100.0
    assert cfg.b3_fee_pct == pytest.approx(0.0003)
    assert cfg.brokerage_fee == 0.0
    assert cfg.slippage_pct == 0.0
    assert cfg.use_fractional_suffix is True
    assert cfg.max_retries == 3
    assert cfg.base_backoff_seconds == pytest.approx(0.5)
    assert cfg.backoff_multiplier == pytest.approx(2.0)
    assert cfg.request_timeout_seconds == pytest.approx(5.0)
    assert cfg.liquidate_on_halt is True
    assert cfg.state_path is None

    cfg_path = ExecutionConfig(state_path=".cache/execution/state.json")  # type: ignore[arg-type]
    assert cfg_path.state_path == Path(".cache/execution/state.json")


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"initial_cash": 0.0}, "initial_cash"),
        ({"initial_cash": -100.0}, "initial_cash"),
        ({"initial_cash": math.nan}, "initial_cash"),
        ({"initial_cash": True}, "initial_cash"),
        ({"b3_fee_pct": -0.001}, "b3_fee_pct"),
        ({"b3_fee_pct": 1.0}, "b3_fee_pct"),
        ({"brokerage_fee": -1.0}, "brokerage_fee"),
        ({"slippage_pct": -0.01}, "slippage_pct"),
        ({"slippage_pct": 1.0}, "slippage_pct"),
        ({"use_fractional_suffix": 1}, "use_fractional_suffix"),
        ({"max_retries": -1}, "max_retries"),
        ({"max_retries": True}, "max_retries"),
        ({"base_backoff_seconds": -0.1}, "base_backoff_seconds"),
        ({"backoff_multiplier": 0.9}, "backoff_multiplier"),
        ({"request_timeout_seconds": 0.0}, "request_timeout_seconds"),
        ({"request_timeout_seconds": math.inf}, "request_timeout_seconds"),
        ({"liquidate_on_halt": "yes"}, "liquidate_on_halt"),
        ({"state_path": "   "}, "state_path"),
    ],
)
def test_ac08_invalid_execution_config_raises_error(
    kwargs: dict[str, Any], field: str
) -> None:
    """AC08: Reject invalid ExecutionConfig parameters with ExecutionConfigurationError."""
    with pytest.raises(ExecutionConfigurationError, match=field):
        ExecutionConfig(**kwargs)


def test_ac05_order_request_receipt_account_and_symbol_formatting() -> None:
    """AC05: Verify valid MARKET/LIMIT requests, snapshots, and B3 fractional symbol mapping."""
    now = datetime(2026, 11, 11, 15, 0, tzinfo=timezone.utc)  # noqa: UP017
    market_req = OrderRequest(
        client_order_id="cid-001",
        ticker="ITUB4.SA",
        side=OrderSide.BUY,
        shares=2,
        reference_price=30.50,
        created_at=now,
    )
    assert market_req.order_type == OrderType.MARKET
    assert market_req.limit_price is None

    limit_req = OrderRequest(
        client_order_id="cid-002",
        ticker="VALE3.SA",
        side=OrderSide.SELL,
        shares=1,
        reference_price=62.00,
        order_type=OrderType.LIMIT,
        limit_price=63.00,
        created_at=now,
        is_emergency=True,
    )
    assert limit_req.limit_price == 63.00

    assert format_b3_execution_symbol("ITUB4.SA", 2) == "ITUB4F"
    assert format_b3_execution_symbol("ITUB4.SA", 100) == "ITUB4"
    assert (
        format_b3_execution_symbol("ITUB4.SA", 2, use_fractional_suffix=False)
        == "ITUB4.SA"
    )
    assert format_b3_execution_symbol("AAPL", 5) == "AAPL"

    receipt = OrderReceipt(
        broker_order_id="brk-001",
        client_order_id="cid-001",
        ticker="ITUB4.SA",
        execution_symbol="ITUB4F",
        side=OrderSide.BUY,
        requested_shares=2,
        filled_shares=2,
        fill_price=30.50,
        b3_fee_paid=0.0183,
        status=OrderStatus.FILLED,
        submitted_at=now,
        filled_at=now,
        message="Filled",
    )
    pos = PositionSnapshot(
        ticker="ITUB4.SA",
        shares=2,
        avg_entry_price=30.50,
        entry_date=date(2026, 11, 11),
        market_price=31.00,
        unrealized_pnl=1.00,
    )
    acct = AccountSnapshot(
        cash=38.98,
        equity=100.98,
        realized_pnl=0.0,
        total_fees_paid=0.0183,
        positions={"ITUB4.SA": pos},
        open_orders=[],
        timestamp=now,
    )
    verdict = RiskVerdict(
        approved=True,
        action="BUY",
        shares=2,
        weight=0.61,
        kill_switch_state=KillSwitchState(
            status=RiskStatus.ACTIVE,
            reason=HaltReason.NONE,
            tripped_at_date=None,
            daily_pnl_pct=0.0,
            drawdown_pct=0.0,
            last_latency_ms=10.0,
            message="OK",
        ),
        reason="Approved",
    )
    step = ExecutionStepResult(
        ticker="ITUB4.SA",
        signal=1,
        verdict=verdict,
        order_receipt=receipt,
        account=acct,
        halted=False,
        cancelled_orders_count=0,
        latency_ms=12.0,
        timestamp=now,
    )
    assert step.order_receipt == receipt


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"client_order_id": ""}, "client_order_id"),
        ({"ticker": "  "}, "ticker"),
        ({"side": "BUY"}, "side"),
        ({"order_type": "STOP"}, "order_type"),
        ({"shares": 0}, "shares"),
        ({"shares": True}, "shares"),
        ({"reference_price": 0.0}, "reference_price"),
        ({"reference_price": math.nan}, "reference_price"),
        ({"order_type": OrderType.LIMIT, "limit_price": None}, "limit_price"),
        ({"order_type": OrderType.LIMIT, "limit_price": -1.0}, "limit_price"),
        ({"order_type": OrderType.MARKET, "limit_price": 10.0}, "limit_price"),
        ({"is_emergency": 1}, "is_emergency"),
    ],
)
def test_ac08_invalid_order_request_raises_error(
    kwargs: dict[str, Any], field: str
) -> None:
    """AC08: Reject invalid OrderRequest attributes with InvalidOrderError."""
    base: dict[str, Any] = {
        "client_order_id": "cid-1",
        "ticker": "ITUB4.SA",
        "side": OrderSide.BUY,
        "shares": 1,
        "reference_price": 30.0,
    }
    base.update(kwargs)
    with pytest.raises(InvalidOrderError, match=field):
        OrderRequest(**base)


def test_ac08_invalid_snapshots_and_symbol_fail_closed() -> None:
    """AC08: Reject malformed receipt, position, account, step, or ticker inputs."""
    now = datetime(2026, 11, 11, 15, 0, tzinfo=timezone.utc)  # noqa: UP017
    with pytest.raises(InvalidOrderError, match="B3 ticker root"):
        format_b3_execution_symbol(".SA", 1)

    with pytest.raises(InvalidOrderError, match="filled_shares"):
        OrderReceipt(
            broker_order_id="b1",
            client_order_id="c1",
            ticker="ITUB4.SA",
            execution_symbol="ITUB4F",
            side=OrderSide.BUY,
            requested_shares=1,
            filled_shares=2,
            fill_price=30.0,
            b3_fee_paid=0.0,
            status=OrderStatus.FILLED,
            submitted_at=now,
            filled_at=now,
            message="Bad",
        )

    with pytest.raises(InvalidOrderError, match="fill_price"):
        OrderReceipt(
            broker_order_id="b1",
            client_order_id="c1",
            ticker="ITUB4.SA",
            execution_symbol="ITUB4F",
            side=OrderSide.BUY,
            requested_shares=1,
            filled_shares=1,
            fill_price=None,
            b3_fee_paid=0.0,
            status=OrderStatus.FILLED,
            submitted_at=now,
            filled_at=now,
            message="Missing fill price",
        )

    with pytest.raises(InvalidOrderError, match="avg_entry_price"):
        PositionSnapshot(
            ticker="ITUB4.SA",
            shares=1,
            avg_entry_price=0.0,
            entry_date=date(2026, 11, 11),
            market_price=30.0,
            unrealized_pnl=0.0,
        )

    with pytest.raises(InvalidOrderError, match="cash"):
        AccountSnapshot(
            cash=-1.0,
            equity=10.0,
            realized_pnl=0.0,
            total_fees_paid=0.0,
            positions={},
            open_orders=[],
            timestamp=now,
        )


def test_ac05_ibroker_adapter_is_abstract() -> None:
    """AC05: Verify IBrokerAdapter cannot be instantiated without concrete methods."""
    with pytest.raises(TypeError, match="abstract"):
        IBrokerAdapter()  # type: ignore[abstract]

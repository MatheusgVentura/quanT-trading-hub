"""Unit tests for SimulatedPaperBroker mapped to AC04, AC05, AC07, AC08, and AC10."""

from __future__ import annotations

import json
import math
import os
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src.execution import (
    BrokerConnectionError,
    ExecutionConfig,
    ExecutionConfigurationError,
    IBrokerAdapter,
    InvalidOrderError,
    OrderRejectedError,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    SimulatedPaperBroker,
)


class _StepClock:
    """Deterministic incrementing UTC clock for broker tests."""

    def __init__(self, initial: datetime | None = None) -> None:
        self.current = initial or datetime(2024, 1, 10, 13, 0, tzinfo=timezone.utc)  # noqa: UP017

    def __call__(self) -> datetime:
        ts = self.current
        self.current = datetime.fromtimestamp(
            ts.timestamp() + 60.0,
            tz=timezone.utc,  # noqa: UP017
        )
        return ts


def _make_buy(
    cid: str,
    *,
    ticker: str = "ITUB4.SA",
    shares: int = 2,
    reference_price: float = 30.0,
    order_type: OrderType = OrderType.MARKET,
    limit_price: float | None = None,
) -> OrderRequest:
    return OrderRequest(
        client_order_id=cid,
        ticker=ticker,
        side=OrderSide.BUY,
        shares=shares,
        reference_price=reference_price,
        order_type=order_type,
        limit_price=limit_price,
    )


def _make_sell(
    cid: str,
    *,
    ticker: str = "ITUB4.SA",
    shares: int = 2,
    reference_price: float = 32.0,
    order_type: OrderType = OrderType.MARKET,
    limit_price: float | None = None,
    is_emergency: bool = False,
) -> OrderRequest:
    return OrderRequest(
        client_order_id=cid,
        ticker=ticker,
        side=OrderSide.SELL,
        shares=shares,
        reference_price=reference_price,
        order_type=order_type,
        limit_price=limit_price,
        is_emergency=is_emergency,
    )


# ---------------------------------------------------------------------------
# AC04: B3 fractional 'F' suffix, 0.03% fee / RLP zero brokerage, overdraft guard
# ---------------------------------------------------------------------------


def test_ac04_buy_2_shares_r100_fractional_suffix_and_exact_b3_fee() -> None:
    """AC04: R$ 100 fractional B3 trade maps ITUB4.SA -> ITUB4F and charges 0.03%."""
    clock = _StepClock()
    broker = SimulatedPaperBroker(ExecutionConfig(), clock=clock)
    assert isinstance(broker, IBrokerAdapter)

    receipt = broker.submit_order(_make_buy("cid-1", shares=2, reference_price=30.0))

    assert receipt.status == OrderStatus.FILLED
    assert receipt.execution_symbol == "ITUB4F"
    assert receipt.ticker == "ITUB4.SA"
    assert receipt.filled_shares == 2
    assert receipt.fill_price == pytest.approx(30.0)
    assert receipt.b3_fee_paid == pytest.approx(0.018)

    snapshot = broker.get_account_snapshot({"ITUB4.SA": 30.0})
    assert snapshot.cash == pytest.approx(39.982)
    assert snapshot.total_fees_paid == pytest.approx(0.018)
    assert snapshot.equity == pytest.approx(99.982)
    assert list(snapshot.positions.keys()) == ["ITUB4.SA"]
    assert snapshot.positions["ITUB4.SA"].shares == 2


def test_ac04_standard_lot_100_omits_f_and_suffix_flag_can_disable_mapping() -> None:
    """AC04: Multiple-of-100 lots strip .SA without 'F'; disabled flag keeps .SA."""
    lot_broker = SimulatedPaperBroker(ExecutionConfig(initial_cash=10000.0))
    lot_rec = lot_broker.submit_order(
        _make_buy("cid-lot", ticker="PETR4.SA", shares=100, reference_price=35.0)
    )
    assert lot_rec.execution_symbol == "PETR4"

    raw_broker = SimulatedPaperBroker(
        ExecutionConfig(initial_cash=500.0, use_fractional_suffix=False)
    )
    raw_rec = raw_broker.submit_order(
        _make_buy("cid-raw", ticker="ITUB4.SA", shares=3, reference_price=30.0)
    )
    assert raw_rec.execution_symbol == "ITUB4.SA"


def test_ac04_prevents_cash_overdraft_when_b3_fee_exceeds_cash() -> None:
    """AC04: Cash exhaustion including B3 0.03% fee rejects BUY without mutating cash."""
    broker = SimulatedPaperBroker(ExecutionConfig(initial_cash=60.0))

    with pytest.raises(OrderRejectedError, match="Insufficient cash"):
        broker.submit_order(_make_buy("cid-over", shares=2, reference_price=30.0))

    snap = broker.get_account_snapshot()
    assert snap.cash == pytest.approx(60.0)
    assert snap.positions == {}
    assert broker.get_order_by_client_id("cid-over") is None


def test_ac04_custom_brokerage_fee_adds_to_b3_fee() -> None:
    """AC04: Non-zero fixed brokerage fee is added accurately on fills."""
    broker = SimulatedPaperBroker(
        ExecutionConfig(initial_cash=100.0, b3_fee_pct=0.0003, brokerage_fee=2.50)
    )
    rec = broker.submit_order(_make_buy("cid-fee", shares=2, reference_price=30.0))
    assert rec.b3_fee_paid == pytest.approx(2.518)
    assert broker.get_account_snapshot().cash == pytest.approx(100.0 - 62.518)


# ---------------------------------------------------------------------------
# AC05: MARKET slippage, LIMIT lifecycle, average cost, cancellation, ping()
# ---------------------------------------------------------------------------


def test_ac05_market_round_trip_with_slippage_and_equity_conservation() -> None:
    """AC05: Adverse slippage applies on MARKET orders and closes custody cleanly."""
    clock = _StepClock()
    cfg = ExecutionConfig(initial_cash=100.0, slippage_pct=0.01)
    broker = SimulatedPaperBroker(cfg, clock=clock)

    buy_rec = broker.submit_order(_make_buy("b1", shares=2, reference_price=30.0))
    assert buy_rec.fill_price == pytest.approx(30.30)

    mid_snap = broker.get_account_snapshot({"ITUB4.SA": 35.0})
    assert mid_snap.positions["ITUB4.SA"].unrealized_pnl == pytest.approx(
        (35.0 - 30.30) * 2
    )
    assert mid_snap.equity == pytest.approx(
        cfg.initial_cash
        + mid_snap.realized_pnl
        + mid_snap.positions["ITUB4.SA"].unrealized_pnl
        - mid_snap.total_fees_paid
    )

    sell_rec = broker.submit_order(_make_sell("s1", shares=2, reference_price=35.0))
    assert sell_rec.fill_price == pytest.approx(34.65)

    end_snap = broker.get_account_snapshot()
    assert end_snap.positions == {}
    assert end_snap.realized_pnl == pytest.approx((34.65 - 30.30) * 2)
    assert end_snap.equity == pytest.approx(
        cfg.initial_cash + end_snap.realized_pnl - end_snap.total_fees_paid
    )


def test_ac05_weighted_average_entry_price_across_multiple_buys_and_partial_sell() -> (
    None
):
    """AC05: Scaling in averages entry cost; partial sell keeps remaining average cost."""
    broker = SimulatedPaperBroker(ExecutionConfig(initial_cash=500.0))
    broker.submit_order(_make_buy("b1", shares=2, reference_price=20.0))
    broker.submit_order(_make_buy("b2", shares=1, reference_price=26.0))

    snap = broker.get_account_snapshot({"ITUB4.SA": 25.0})
    pos = snap.positions["ITUB4.SA"]
    assert pos.shares == 3
    assert pos.avg_entry_price == pytest.approx(22.0)

    broker.submit_order(_make_sell("s1", shares=1, reference_price=25.0))
    after = broker.get_account_snapshot({"ITUB4.SA": 25.0})
    assert after.positions["ITUB4.SA"].shares == 2
    assert after.positions["ITUB4.SA"].avg_entry_price == pytest.approx(22.0)
    assert after.realized_pnl == pytest.approx(3.0)


def test_ac05_limit_buy_rests_reserves_buying_power_and_fills_on_price_drop() -> None:
    """AC05: Resting LIMIT BUY locks buying power until update_market_prices <= limit."""
    clock = _StepClock()
    broker = SimulatedPaperBroker(ExecutionConfig(initial_cash=100.0), clock=clock)

    resting = broker.submit_order(
        _make_buy(
            "lim-b1",
            shares=2,
            reference_price=30.0,
            order_type=OrderType.LIMIT,
            limit_price=28.0,
        )
    )
    assert resting.status == OrderStatus.SUBMITTED
    assert resting.filled_shares == 0
    assert resting.fill_price is None
    assert broker.reserved_cash == pytest.approx(2 * 28.0 * 1.0003)
    assert broker.available_cash == pytest.approx(100.0 - 2 * 28.0 * 1.0003)

    # Cannot double-spend reserved cash on a second buy.
    with pytest.raises(OrderRejectedError, match="Insufficient"):
        broker.submit_order(_make_buy("mkt-b2", shares=2, reference_price=30.0))

    # Non-matching price update keeps order resting.
    assert broker.update_market_prices({"ITUB4.SA": 29.0}) == []
    assert len(broker.get_account_snapshot().open_orders) == 1

    # Matching price update fills at updated market price and clears reservation.
    fills = broker.update_market_prices({"ITUB4.SA": 27.5})
    assert len(fills) == 1
    filled = fills[0]
    assert filled.client_order_id == "lim-b1"
    assert filled.status == OrderStatus.FILLED
    assert filled.fill_price == pytest.approx(27.5)
    assert filled.b3_fee_paid == pytest.approx(55.0 * 0.0003)
    assert broker.reserved_cash == pytest.approx(0.0)
    assert broker.get_account_snapshot().cash == pytest.approx(100.0 - 55.0 - 0.0165)


def test_ac05_limit_sell_rests_reserves_shares_and_fills_on_rally() -> None:
    """AC05: Resting LIMIT SELL locks custody shares until market_price >= limit."""
    broker = SimulatedPaperBroker(ExecutionConfig(initial_cash=100.0))
    broker.submit_order(_make_buy("b1", shares=2, reference_price=30.0))

    resting = broker.submit_order(
        _make_sell(
            "lim-s1",
            shares=2,
            reference_price=30.0,
            order_type=OrderType.LIMIT,
            limit_price=35.0,
        )
    )
    assert resting.status == OrderStatus.SUBMITTED
    assert broker.get_available_shares("ITUB4.SA") == 0

    with pytest.raises(OrderRejectedError, match="Insufficient"):
        broker.submit_order(_make_sell("dup-s", shares=1, reference_price=31.0))

    assert broker.update_market_prices({"ITUB4.SA": 34.5}) == []
    fills = broker.update_market_prices({"ITUB4.SA": 35.5})
    assert len(fills) == 1
    assert fills[0].status == OrderStatus.FILLED
    assert fills[0].fill_price == pytest.approx(35.5)
    assert broker.get_account_snapshot().positions == {}


def test_ac05_marketable_limit_orders_fill_immediately() -> None:
    """AC05: Marketable LIMIT orders execute immediately at reference_price."""
    broker = SimulatedPaperBroker(
        ExecutionConfig(initial_cash=200.0, slippage_pct=0.05)
    )
    buy_rec = broker.submit_order(
        _make_buy(
            "mb1",
            shares=2,
            reference_price=30.0,
            order_type=OrderType.LIMIT,
            limit_price=31.0,
        )
    )
    assert buy_rec.status == OrderStatus.FILLED
    assert buy_rec.fill_price == pytest.approx(30.0)

    sell_rec = broker.submit_order(
        _make_sell(
            "ms1",
            shares=2,
            reference_price=32.0,
            order_type=OrderType.LIMIT,
            limit_price=30.0,
        )
    )
    assert sell_rec.status == OrderStatus.FILLED
    assert sell_rec.fill_price == pytest.approx(32.0)


def test_ac05_cancel_all_open_orders_releases_cash_and_shares() -> None:
    """AC05: Cancelling open limit orders frees both reserved cash and custody."""
    broker = SimulatedPaperBroker(ExecutionConfig(initial_cash=200.0))
    broker.submit_order(_make_buy("b-init", shares=2, reference_price=30.0))

    broker.submit_order(
        _make_buy(
            "lim-b",
            ticker="PETR4.SA",
            shares=2,
            reference_price=40.0,
            order_type=OrderType.LIMIT,
            limit_price=35.0,
        )
    )
    broker.submit_order(
        _make_sell(
            "lim-s",
            ticker="ITUB4.SA",
            shares=2,
            reference_price=30.0,
            order_type=OrderType.LIMIT,
            limit_price=36.0,
        )
    )
    assert broker.reserved_cash > 0.0
    assert broker.get_available_shares("ITUB4.SA") == 0

    cancelled = broker.cancel_all_open_orders()
    assert [c.client_order_id for c in cancelled] == ["lim-b", "lim-s"]
    assert all(c.status == OrderStatus.CANCELLED for c in cancelled)
    assert broker.reserved_cash == pytest.approx(0.0)
    assert broker.get_available_shares("ITUB4.SA") == 2
    assert broker.get_account_snapshot().open_orders == []
    # Re-calling cancellation returns empty list with no errors.
    assert broker.cancel_all_open_orders() == []


def test_ac05_connection_state_ping_and_latency_controls() -> None:
    """AC05: Disconnected state raises BrokerConnectionError; ping reports latency."""
    broker = SimulatedPaperBroker(
        ExecutionConfig(), simulated_latency_ms=42.5, auto_connect=False
    )
    assert broker.is_connected() is False

    with pytest.raises(BrokerConnectionError):
        broker.ping()
    with pytest.raises(BrokerConnectionError):
        broker.submit_order(_make_buy("c1"))
    with pytest.raises(BrokerConnectionError):
        broker.get_order_by_client_id("c1")
    with pytest.raises(BrokerConnectionError):
        broker.cancel_all_open_orders()
    with pytest.raises(BrokerConnectionError):
        broker.get_account_snapshot()
    with pytest.raises(BrokerConnectionError):
        broker.update_market_prices({"ITUB4.SA": 30.0})

    broker.connect()
    assert broker.is_connected() is True
    assert broker.ping() == pytest.approx(42.5)
    broker.set_simulated_latency_ms(620.0)
    assert broker.ping() == pytest.approx(620.0)

    broker.disconnect()
    assert broker.is_connected() is False
    with pytest.raises(BrokerConnectionError):
        broker.ping()


# ---------------------------------------------------------------------------
# AC07: Swing Trade entry_date tracking & native client_order_id idempotency
# ---------------------------------------------------------------------------


def test_ac07_tracks_entry_date_across_buys_and_executes_d0_emergency_exit() -> None:
    """AC07: Custody records entry_date for Swing Trade gates and permits emergency D0."""
    current = datetime(2024, 1, 10, 14, 0, tzinfo=timezone.utc)  # noqa: UP017
    broker = SimulatedPaperBroker(
        ExecutionConfig(initial_cash=200.0), clock=lambda: current
    )
    broker.submit_order(_make_buy("day1", shares=1, reference_price=30.0))
    assert broker.get_account_snapshot().positions["ITUB4.SA"].entry_date == date(
        2024, 1, 10
    )

    current = datetime(2024, 1, 12, 14, 0, tzinfo=timezone.utc)  # noqa: UP017
    broker.submit_order(_make_buy("day3", shares=1, reference_price=32.0))
    assert broker.get_account_snapshot().positions["ITUB4.SA"].entry_date == date(
        2024, 1, 12
    )

    emg_sell = broker.submit_order(
        _make_sell("emg", shares=2, reference_price=31.0, is_emergency=True)
    )
    assert emg_sell.status == OrderStatus.FILLED
    assert "[EMERGENCY]" in emg_sell.message
    assert broker.get_account_snapshot().positions == {}


def test_ac07_idempotent_duplicate_client_order_id_does_not_double_spend() -> None:
    """AC07: Duplicate submit_order with same client_order_id returns cached receipt."""
    broker = SimulatedPaperBroker(ExecutionConfig(initial_cash=100.0))
    req = _make_buy("idem-1", shares=2, reference_price=30.0)

    first = broker.submit_order(req)
    second = broker.submit_order(req)

    assert second == first
    assert len(broker.order_history) == 1
    snap = broker.get_account_snapshot()
    assert snap.cash == pytest.approx(39.982)
    assert snap.positions["ITUB4.SA"].shares == 2
    assert broker.get_order_by_client_id("idem-1") == first
    assert broker.get_order_by_client_id("missing-id") is None


def test_ac07_conflicting_payload_reusing_client_order_id_is_rejected() -> None:
    """AC07: Reusing client_order_id with different parameters fails closed."""
    broker = SimulatedPaperBroker(ExecutionConfig(initial_cash=200.0))
    broker.submit_order(_make_buy("idem-1", shares=2, reference_price=30.0))

    with pytest.raises(OrderRejectedError, match="Conflicting retry"):
        broker.submit_order(_make_buy("idem-1", shares=3, reference_price=30.0))


# ---------------------------------------------------------------------------
# AC08: Fail-closed validation & boundary guards
# ---------------------------------------------------------------------------


def test_ac08_invalid_constructor_and_latency_arguments_fail_closed() -> None:
    """AC08: Malformed constructor inputs raise ExecutionConfigurationError."""
    with pytest.raises(ExecutionConfigurationError):
        SimulatedPaperBroker(config="bad")  # type: ignore[arg-type]
    with pytest.raises(ExecutionConfigurationError):
        SimulatedPaperBroker(clock="not-callable")  # type: ignore[arg-type]
    with pytest.raises(ExecutionConfigurationError):
        SimulatedPaperBroker(simulated_latency_ms=-1.0)
    with pytest.raises(ExecutionConfigurationError):
        SimulatedPaperBroker(simulated_latency_ms=math.nan)
    with pytest.raises(ExecutionConfigurationError):
        SimulatedPaperBroker(auto_connect="yes")  # type: ignore[arg-type]

    broker = SimulatedPaperBroker()
    with pytest.raises(ExecutionConfigurationError):
        broker.set_simulated_latency_ms(-5.0)


def test_ac08_invalid_order_type_short_sell_and_corrupt_prices_fail_closed() -> None:
    """AC08: Short sells, non-OrderRequest inputs, and corrupt prices fail closed."""
    broker = SimulatedPaperBroker(ExecutionConfig(initial_cash=100.0))

    with pytest.raises(InvalidOrderError):
        broker.submit_order("not-an-order")  # type: ignore[arg-type]
    with pytest.raises(InvalidOrderError):
        broker.get_order_by_client_id("   ")
    with pytest.raises(OrderRejectedError, match="Insufficient shares"):
        broker.submit_order(_make_sell("short-attempt", shares=1, reference_price=30.0))
    with pytest.raises(OrderRejectedError, match="Insufficient unencumbered shares"):
        broker.submit_order(
            _make_sell(
                "lim-short",
                shares=1,
                reference_price=29.0,
                order_type=OrderType.LIMIT,
                limit_price=35.0,
            )
        )

    broker.submit_order(_make_buy("b1", shares=2, reference_price=30.0))
    for bad_prices in [
        "bad",
        {},
        {"": 10.0},
        {"ITUB4.SA": -1.0},
        {"ITUB4.SA": math.inf},
        {"ITUB4.SA": True},
    ]:
        with pytest.raises(InvalidOrderError):
            broker.update_market_prices(bad_prices)  # type: ignore[arg-type]

    with pytest.raises(InvalidOrderError):
        broker.get_account_snapshot({"ITUB4.SA": 0.0})

    bad_clock_broker = SimulatedPaperBroker(clock=lambda: "not-a-dt")  # type: ignore[arg-type,return-value]
    with pytest.raises(InvalidOrderError):
        bad_clock_broker.submit_order(
            _make_buy("bad-clk", shares=1, reference_price=10.0)
        )


def test_ac08_sell_fee_exceeding_cash_plus_proceeds_is_rejected() -> None:
    """AC08: Prevent negative cash when brokerage fee exceeds cash + sell proceeds."""
    broker = SimulatedPaperBroker(
        ExecutionConfig(initial_cash=100.0, brokerage_fee=95.0, b3_fee_pct=0.0)
    )
    # After buying 1 @ 5 + 95 fee -> cash == 0.0; selling 1 @ 10 would yield 10 - 95 = -85!
    broker.submit_order(_make_buy("b1", shares=1, reference_price=5.0))
    assert broker.get_account_snapshot().cash == pytest.approx(0.0)

    with pytest.raises(OrderRejectedError, match="insufficient to cover sell fees"):
        broker.submit_order(_make_sell("s1", shares=1, reference_price=10.0))


# ---------------------------------------------------------------------------
# AC10: Atomic JSON persistence, reload continuity, and crash/corruption safety
# ---------------------------------------------------------------------------


def test_ac10_persists_and_reloads_cash_custody_open_orders_and_idempotency(
    tmp_path: Path,
) -> None:
    """AC10: JSON state reload restores balances, custody, limits, and idempotency."""
    state_file = tmp_path / "nested" / "paper_state.json"
    clock = _StepClock()
    cfg = ExecutionConfig(initial_cash=200.0, state_path=state_file)
    broker1 = SimulatedPaperBroker(cfg, clock=clock)

    fill_rec = broker1.submit_order(
        _make_buy("cid-fill", shares=2, reference_price=30.0)
    )
    lim_rec = broker1.submit_order(
        _make_buy(
            "cid-lim",
            ticker="PETR4.SA",
            shares=2,
            reference_price=40.0,
            order_type=OrderType.LIMIT,
            limit_price=35.0,
        )
    )
    assert state_file.exists()

    # Reload into a brand-new SimulatedPaperBroker instance.
    broker2 = SimulatedPaperBroker(cfg, clock=clock)
    snap2 = broker2.get_account_snapshot()

    assert snap2.cash == pytest.approx(200.0 - 60.0 - 0.018)
    assert snap2.total_fees_paid == pytest.approx(0.018)
    assert snap2.positions["ITUB4.SA"].shares == 2
    assert snap2.positions["ITUB4.SA"].avg_entry_price == pytest.approx(30.0)
    assert snap2.positions["ITUB4.SA"].entry_date == date(2024, 1, 10)
    assert [o.client_order_id for o in snap2.open_orders] == ["cid-lim"]
    assert broker2.reserved_cash == pytest.approx(2 * 35.0 * 1.0003)

    # Idempotency preserved across restart.
    assert (
        broker2.submit_order(_make_buy("cid-fill", shares=2, reference_price=30.0))
        == fill_rec
    )
    assert broker2.get_order_by_client_id("cid-lim") == lim_rec

    # Next order sequence does not collide and resting LIMIT matches on reload.
    fills = broker2.update_market_prices({"PETR4.SA": 34.0})
    assert len(fills) == 1
    assert fills[0].broker_order_id == lim_rec.broker_order_id
    next_rec = broker2.submit_order(
        _make_buy("cid-next", shares=1, reference_price=10.0)
    )
    assert next_rec.broker_order_id == "SIM-000003"


def test_ac10_atomic_write_preserves_prior_state_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC10: Crash during os.replace leaves prior state file uncorrupted and cleans tmp."""
    state_file = tmp_path / "state.json"
    cfg = ExecutionConfig(initial_cash=100.0, state_path=state_file)
    broker = SimulatedPaperBroker(cfg)
    broker.submit_order(_make_buy("first", shares=1, reference_price=20.0))
    prior_bytes = state_file.read_text(encoding="utf-8")

    def _boom_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        raise OSError("simulated power loss during atomic replace")

    monkeypatch.setattr(os, "replace", _boom_replace)
    with pytest.raises(OSError, match="simulated power loss"):
        broker.submit_order(_make_buy("second", shares=1, reference_price=20.0))

    assert state_file.read_text(encoding="utf-8") == prior_bytes
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize(
    "payload",
    [
        "{not-valid-json",
        json.dumps([1, 2, 3]),
        json.dumps({"schema_version": 99}),
        json.dumps(
            {
                "schema_version": 1,
                "cash": -1.0,
                "realized_pnl": 0.0,
                "total_fees_paid": 0.0,
                "next_order_seq": 1,
                "positions": {},
                "orders": [],
            }
        ),
        json.dumps(
            {
                "schema_version": 1,
                "cash": 100.0,
                "realized_pnl": 0.0,
                "total_fees_paid": -0.1,
                "next_order_seq": 1,
                "positions": {},
                "orders": [],
            }
        ),
        json.dumps(
            {
                "schema_version": 1,
                "cash": 100.0,
                "realized_pnl": 0.0,
                "total_fees_paid": 0.0,
                "next_order_seq": 1,
                "positions": {
                    "ITUB4.SA": {
                        "ticker": "PETR4.SA",
                        "shares": 1,
                        "avg_entry_price": 30.0,
                        "entry_date": "2024-01-10",
                    }
                },
                "orders": [],
            }
        ),
        json.dumps(
            {
                "schema_version": 1,
                "cash": 100.0,
                "realized_pnl": 0.0,
                "total_fees_paid": 0.0,
                "next_order_seq": 1,
                "positions": {},
                "orders": [
                    {
                        "broker_order_id": "SIM-000001",
                        "client_order_id": "cid-lim",
                        "ticker": "ITUB4.SA",
                        "execution_symbol": "ITUB4F",
                        "side": "BUY",
                        "order_type": "LIMIT",
                        "requested_shares": 1,
                        "filled_shares": 0,
                        "fill_price": None,
                        "limit_price": None,
                        "b3_fee_paid": 0.0,
                        "status": "SUBMITTED",
                        "submitted_at": "2024-01-10T10:00:00+00:00",
                        "filled_at": None,
                    }
                ],
            }
        ),
    ],
)
def test_ac10_corrupted_state_file_fails_closed(tmp_path: Path, payload: str) -> None:
    """AC10: Corrupted JSON state schemas fail closed with ExecutionConfigurationError."""
    state_file = tmp_path / "corrupt.json"
    state_file.write_text(payload, encoding="utf-8")
    with pytest.raises(ExecutionConfigurationError):
        SimulatedPaperBroker(ExecutionConfig(state_path=state_file))

"""Unit tests for OrderRouter mapped to AC01, AC02, AC03, AC06, AC07, and AC08."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

import pytest

from src.execution import (
    AccountSnapshot,
    BrokerConnectionError,
    ExecutionConfig,
    ExecutionConfigurationError,
    ExecutionHaltedError,
    IBrokerAdapter,
    InvalidOrderError,
    OrderReceipt,
    OrderRejectedError,
    OrderRequest,
    OrderRouter,
    OrderSide,
    OrderStatus,
    OrderType,
    SimulatedPaperBroker,
)
from src.risk import RiskConfig, RiskManager, RiskStatus


class _FaultyBrokerProxy(IBrokerAdapter):
    """Test wrapper around SimulatedPaperBroker injecting deterministic faults."""

    def __init__(self, inner: SimulatedPaperBroker) -> None:
        self.inner = inner
        self.connect_failures: list[Exception] = []
        self.submit_failures: list[tuple[Exception, bool]] = []
        self.lookup_failures: list[Exception] = []
        self.snapshot_failures: list[Exception] = []
        self.cancel_failures: list[Exception] = []
        self.submit_calls = 0
        self.lookup_calls = 0
        self.cancel_calls = 0
        self.snapshot_calls = 0
        self.connect_calls = 0

    def connect(self) -> None:
        self.connect_calls += 1
        if self.connect_failures:
            raise self.connect_failures.pop(0)
        self.inner.connect()

    def is_connected(self) -> bool:
        return self.inner.is_connected()

    def ping(self) -> float:
        return self.inner.ping()

    def submit_order(self, order: OrderRequest) -> OrderReceipt:
        self.submit_calls += 1
        if self.submit_failures:
            exc, execute_first = self.submit_failures.pop(0)
            if execute_first:
                self.inner.submit_order(order)
            raise exc
        return self.inner.submit_order(order)

    def get_order_by_client_id(self, client_order_id: str) -> OrderReceipt | None:
        self.lookup_calls += 1
        if self.lookup_failures:
            raise self.lookup_failures.pop(0)
        return self.inner.get_order_by_client_id(client_order_id)

    def cancel_all_open_orders(self) -> list[OrderReceipt]:
        self.cancel_calls += 1
        if self.cancel_failures:
            raise self.cancel_failures.pop(0)
        return self.inner.cancel_all_open_orders()

    def get_account_snapshot(
        self, market_prices: dict[str, float] | None = None
    ) -> AccountSnapshot:
        self.snapshot_calls += 1
        if self.snapshot_failures:
            raise self.snapshot_failures.pop(0)
        return self.inner.get_account_snapshot(market_prices=market_prices)


# ---------------------------------------------------------------------------
# AC01: Deterministic client_order_id & idempotent retry after timeout
# ---------------------------------------------------------------------------


def test_ac01_deterministic_client_order_id_varies_with_inputs() -> None:
    """AC01: Identical order tuples produce identical client_order_id keys."""
    ts = datetime(2024, 1, 10, 14, 0, tzinfo=timezone.utc)  # noqa: UP017
    cid1 = OrderRouter.build_client_order_id(
        ticker="ITUB4.SA", side=OrderSide.BUY, shares=1, timestamp=ts
    )
    cid2 = OrderRouter.build_client_order_id(
        ticker="ITUB4.SA", side=OrderSide.BUY, shares=1, timestamp=ts
    )
    cid_diff = OrderRouter.build_client_order_id(
        ticker="ITUB4.SA", side=OrderSide.SELL, shares=1, timestamp=ts
    )

    assert cid1 == cid2
    assert cid1.startswith("QTH-ITUB4-SA-BUY-")
    assert cid_diff != cid1


def test_ac01_timeout_after_acceptance_returns_existing_receipt_no_duplicate() -> None:
    """AC01: Query get_order_by_client_id first on retry and avoid double-spend."""
    ts = datetime(2024, 1, 10, 14, 0, tzinfo=timezone.utc)  # noqa: UP017
    paper = SimulatedPaperBroker(ExecutionConfig(initial_cash=100.0), clock=lambda: ts)
    proxy = _FaultyBrokerProxy(paper)
    # Broker executes first order internally then drops TCP response before caller hears.
    proxy.submit_failures = [(BrokerConnectionError("Read timeout after accept"), True)]

    sleeps: list[float] = []
    router = OrderRouter(
        proxy, RiskManager(), ExecutionConfig(), sleep_fn=sleeps.append
    )

    req = OrderRequest(
        client_order_id="cid-timeout-once",
        ticker="ITUB4.SA",
        side=OrderSide.BUY,
        shares=2,
        reference_price=30.0,
    )
    receipt = router.submit_order_idempotent(req)

    assert receipt.status == OrderStatus.FILLED
    assert receipt.filled_shares == 2
    # submit_order ran once (initial timed-out attempt), retry matched via lookup!
    assert proxy.submit_calls == 1
    assert proxy.lookup_calls == 1
    assert sleeps == [0.5]
    assert router.last_snapshot is not None
    assert router.last_snapshot.cash == pytest.approx(100.0 - 60.0 - 0.018)
    assert router.last_snapshot.positions["ITUB4.SA"].shares == 2


def test_ac01_transient_failure_before_acceptance_retries_submit_after_miss() -> None:
    """AC01: When lookup returns None after disconnect, router submits on retry."""
    ts = datetime(2024, 1, 10, 14, 0, tzinfo=timezone.utc)  # noqa: UP017
    paper = SimulatedPaperBroker(ExecutionConfig(initial_cash=100.0), clock=lambda: ts)
    proxy = _FaultyBrokerProxy(paper)
    proxy.submit_failures = [(BrokerConnectionError("Connection reset"), False)]

    sleeps: list[float] = []
    router = OrderRouter(
        proxy, RiskManager(), ExecutionConfig(), sleep_fn=sleeps.append
    )

    req = OrderRequest(
        client_order_id="cid-retry-submit",
        ticker="ITUB4.SA",
        side=OrderSide.BUY,
        shares=1,
        reference_price=30.0,
    )
    receipt = router.submit_order_idempotent(req)

    assert receipt.status == OrderStatus.FILLED
    assert proxy.lookup_calls == 1
    assert proxy.submit_calls == 2
    assert sleeps == [0.5]
    assert router.last_snapshot is not None


# ---------------------------------------------------------------------------
# AC02: Exponential backoff retries, recovery reconciliation & exhaustion
# ---------------------------------------------------------------------------


def test_ac02_exponential_backoff_reconnect_and_account_reconciliation() -> None:
    """AC02: Transient disconnects back off exponentially, reconnect, and sync."""
    ts = datetime(2024, 1, 10, 14, 0, tzinfo=timezone.utc)  # noqa: UP017
    paper = SimulatedPaperBroker(
        ExecutionConfig(initial_cash=100.0), auto_connect=False, clock=lambda: ts
    )
    proxy = _FaultyBrokerProxy(paper)
    # Fail twice on initial reconnect / lookup, succeed on 3rd attempt.
    proxy.connect_failures = [
        BrokerConnectionError("timeout #1"),
        BrokerConnectionError("timeout #2"),
    ]

    sleeps: list[float] = []
    cfg = ExecutionConfig(
        max_retries=3,
        base_backoff_seconds=0.5,
        backoff_multiplier=2.0,
    )
    router = OrderRouter(proxy, RiskManager(), cfg, sleep_fn=sleeps.append)

    snapshot, lat = router.sync_account({"ITUB4.SA": 30.0})
    assert sleeps == [0.5, 1.0]
    assert proxy.connect_calls == 3
    assert lat == pytest.approx(1.0)
    assert snapshot.cash == pytest.approx(100.0)
    assert router.last_snapshot == snapshot

    # Retry lookup error during cancel recovery as well.
    proxy.cancel_failures = [BrokerConnectionError("cancel glitch")]
    sleeps.clear()
    cancelled = router.cancel_all_open_orders_resilient()
    assert cancelled == []
    assert sleeps == [0.5]


def test_ac02_exhausted_retries_sleeps_exact_max_retries_and_raises() -> None:
    """AC02: Exhausting retries executes exact max_retries delays and raises."""
    paper = SimulatedPaperBroker(ExecutionConfig(), auto_connect=False)
    proxy = _FaultyBrokerProxy(paper)
    proxy.connect_failures = [
        BrokerConnectionError("down-0"),
        BrokerConnectionError("down-1"),
        BrokerConnectionError("down-2"),
        BrokerConnectionError("down-3"),
    ]

    sleeps: list[float] = []
    cfg = ExecutionConfig(
        max_retries=3,
        base_backoff_seconds=0.25,
        backoff_multiplier=3.0,
    )
    router = OrderRouter(proxy, RiskManager(), cfg, sleep_fn=sleeps.append)

    with pytest.raises(BrokerConnectionError, match="down-3"):
        router.sync_account()

    assert sleeps == [0.25, 0.75, 2.25]


def test_ac02_business_rejection_does_not_retry_with_backoff() -> None:
    """AC02: OrderRejectedError propagates immediately without backoff retries."""
    paper = SimulatedPaperBroker(ExecutionConfig(initial_cash=10.0))
    sleeps: list[float] = []
    router = OrderRouter(
        paper, RiskManager(), ExecutionConfig(), sleep_fn=sleeps.append
    )

    too_big = OrderRequest(
        client_order_id="cid-too-big",
        ticker="ITUB4.SA",
        side=OrderSide.BUY,
        shares=2,
        reference_price=30.0,
    )
    with pytest.raises(OrderRejectedError):
        router.submit_order_idempotent(too_big)
    assert sleeps == []


# ---------------------------------------------------------------------------
# AC03: Kill-Switch emergency reaction (cancel open orders, log ERROR, liquidate, halt)
# ---------------------------------------------------------------------------


def test_ac03_latency_kill_switch_cancels_orders_liquidates_logs_and_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC03: HALTED cancels open orders, liquidates custody, logs ERROR, raises halt."""
    ts1 = datetime(2024, 1, 10, 14, 0, tzinfo=timezone.utc)  # noqa: UP017
    paper = SimulatedPaperBroker(
        ExecutionConfig(initial_cash=200.0, liquidate_on_halt=True),
        clock=lambda: ts1,
    )
    # Seed 1 filled BUY on ITUB4.SA and 1 resting LIMIT BUY on PETR4.SA.
    paper.submit_order(
        OrderRequest(
            client_order_id="seed-pos",
            ticker="ITUB4.SA",
            side=OrderSide.BUY,
            shares=2,
            reference_price=30.0,
        )
    )
    paper.submit_order(
        OrderRequest(
            client_order_id="seed-limit",
            ticker="PETR4.SA",
            side=OrderSide.BUY,
            shares=2,
            reference_price=38.0,
            order_type=OrderType.LIMIT,
            limit_price=34.0,
        )
    )
    # Trigger latency Kill-Switch (> 500ms default limit).
    paper.set_simulated_latency_ms(620.0)

    rm = RiskManager(RiskConfig(initial_capital=200.0, max_latency_ms=500.0))
    router = OrderRouter(
        paper,
        rm,
        ExecutionConfig(initial_cash=200.0, liquidate_on_halt=True),
    )

    with (
        caplog.at_level(logging.ERROR),
        pytest.raises(ExecutionHaltedError, match="LATENCY_LIMIT"),
    ):
        router.process_signal(
            ticker="ITUB4.SA",
            signal=1,
            price=30.0,
            timestamp=ts1,
            market_prices={"ITUB4.SA": 30.0},
        )

    assert "KILL_SWITCH_HALT" in caplog.text
    assert "LATENCY_LIMIT" in caplog.text
    snap = paper.get_account_snapshot()
    assert snap.open_orders == []
    assert paper.reserved_cash == pytest.approx(0.0)
    assert snap.positions == {}
    assert rm.kill_switch.state.status == RiskStatus.HALTED
    assert rm.stop_monitor.has_open_position is False


def test_ac03_halt_without_liquidation_cancels_orders_only_and_preserves_custody(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC03: liquidate_on_halt=False cancels open orders and skips emergency sells."""
    ts1 = datetime(2024, 1, 10, 14, 0, tzinfo=timezone.utc)  # noqa: UP017
    cfg = ExecutionConfig(initial_cash=200.0, liquidate_on_halt=False)
    paper = SimulatedPaperBroker(cfg, clock=lambda: ts1)
    paper.submit_order(
        OrderRequest(
            client_order_id="seed-pos",
            ticker="ITUB4.SA",
            side=OrderSide.BUY,
            shares=2,
            reference_price=30.0,
        )
    )
    paper.submit_order(
        OrderRequest(
            client_order_id="seed-limit",
            ticker="ITUB4.SA",
            side=OrderSide.SELL,
            shares=2,
            reference_price=30.0,
            order_type=OrderType.LIMIT,
            limit_price=35.0,
        )
    )

    rm = RiskManager(RiskConfig(initial_capital=200.0, max_daily_loss_pct=0.02))
    # Initialize baseline day equity at 200.0 then shock price down so equity loss >= 2%.
    rm.kill_switch.update(current_equity=200.0, current_date=ts1.date(), latency_ms=1.0)
    router = OrderRouter(paper, rm, cfg)

    with (
        caplog.at_level(logging.ERROR),
        pytest.raises(ExecutionHaltedError, match="DAILY_LOSS_LIMIT"),
    ):
        # ITUB4 price drops to 27.0 -> position value 54 (loss -6 / 200 = -3% >= 2%).
        router.process_signal(
            ticker="ITUB4.SA",
            signal=0,
            price=27.0,
            timestamp=ts1,
        )

    assert "KILL_SWITCH_HALT" in caplog.text
    snap = paper.get_account_snapshot({"ITUB4.SA": 27.0})
    assert snap.open_orders == []
    assert snap.positions["ITUB4.SA"].shares == 2


# ---------------------------------------------------------------------------
# AC06 & AC07: Pre-trade gate enforcement & Swing Trade D0 custody rule
# ---------------------------------------------------------------------------


def test_ac06_unapproved_and_hold_signals_never_generate_broker_orders() -> None:
    """AC06: HOLD and RiskManager rejections leave broker untouched."""
    ts1 = datetime(2024, 1, 10, 14, 0, tzinfo=timezone.utc)  # noqa: UP017
    ts2 = datetime(2024, 1, 11, 14, 0, tzinfo=timezone.utc)  # noqa: UP017
    paper = SimulatedPaperBroker(ExecutionConfig(initial_cash=100.0), clock=lambda: ts1)
    proxy = _FaultyBrokerProxy(paper)
    router = OrderRouter(proxy, RiskManager(RiskConfig(initial_capital=100.0)))

    # Signal 0 while flat -> HOLD, no order sent.
    res_flat = router.process_signal(
        ticker="ITUB4.SA", signal=0, price=30.0, timestamp=ts1
    )
    assert res_flat.verdict.action == "HOLD"
    assert res_flat.order_receipt is None
    assert proxy.submit_calls == 0

    # Signal 1 at price 150 > R$ 100 -> sizing rejects, no order sent.
    res_rej = router.process_signal(
        ticker="ITUB4.SA", signal=1, price=150.0, timestamp=ts1
    )
    assert res_rej.verdict.approved is False
    assert res_rej.order_receipt is None
    assert proxy.submit_calls == 0

    # Signal 1 at price 30 -> sizing approves 1 share (2% risk of 100 / (0.05*30) = 1).
    res_buy = router.process_signal(
        ticker="ITUB4.SA", signal=1, price=30.0, timestamp=ts1
    )
    assert res_buy.order_receipt is not None
    assert res_buy.order_receipt.filled_shares == 1
    assert res_buy.order_receipt.execution_symbol == "ITUB4F"
    assert proxy.submit_calls == 1

    # Next day signal 1 while holding -> HOLD, no duplicate BUY order sent.
    res_hold = router.process_signal(
        ticker="ITUB4.SA", signal=1, price=31.0, timestamp=ts2
    )
    assert res_hold.verdict.action == "HOLD"
    assert res_hold.order_receipt is None
    assert proxy.submit_calls == 1


def test_ac06_stop_loss_triggers_emergency_market_sell_on_long_signal() -> None:
    """AC06: Breaching 5% stop triggers emergency SELL even if strategy signal is 1."""
    d0 = datetime(2024, 1, 10, 14, 0, tzinfo=timezone.utc)  # noqa: UP017
    d1 = datetime(2024, 1, 11, 14, 0, tzinfo=timezone.utc)  # noqa: UP017
    paper = SimulatedPaperBroker(ExecutionConfig(initial_cash=100.0), clock=lambda: d0)
    rm = RiskManager(
        RiskConfig(
            initial_capital=100.0,
            stop_loss_pct=0.05,
            trailing_stop_pct=0.05,
            max_daily_loss_pct=0.05,
        )
    )
    router = OrderRouter(paper, rm)

    buy_res = router.process_signal(
        ticker="ITUB4.SA", signal=1, price=30.0, timestamp=d0
    )
    assert buy_res.order_receipt is not None
    assert rm.stop_monitor.has_open_position is True

    # Day 1 drops to 28.0 (-6.67%, breaching 5% stop-loss 28.50 while KS daily < 5%).
    stop_res = router.process_signal(
        ticker="ITUB4.SA", signal=1, price=28.0, timestamp=d1
    )
    assert stop_res.order_receipt is not None
    assert stop_res.order_receipt.side == OrderSide.SELL
    assert stop_res.order_receipt.status == OrderStatus.FILLED
    assert "[EMERGENCY]" in stop_res.order_receipt.message
    assert stop_res.account.positions == {}
    assert rm.stop_monitor.has_open_position is False


def test_ac07_swing_trade_blocks_voluntary_d0_sell_and_allows_d1_or_emergency() -> None:
    """AC07: Voluntary D0 EXIT is blocked by RiskManager; D1 and emergency exits fill."""
    d0 = datetime(2024, 1, 10, 14, 0, tzinfo=timezone.utc)  # noqa: UP017
    d1 = datetime(2024, 1, 11, 14, 0, tzinfo=timezone.utc)  # noqa: UP017
    d2 = datetime(2024, 1, 12, 14, 0, tzinfo=timezone.utc)  # noqa: UP017
    current_ts = d0
    paper = SimulatedPaperBroker(
        ExecutionConfig(initial_cash=100.0), clock=lambda: current_ts
    )
    proxy = _FaultyBrokerProxy(paper)
    router = OrderRouter(
        proxy,
        RiskManager(RiskConfig(initial_capital=100.0, allow_day_trade=False)),
    )

    buy_res = router.process_signal(
        ticker="ITUB4.SA", signal=1, price=30.0, timestamp=d0
    )
    assert buy_res.order_receipt is not None
    assert proxy.submit_calls == 1

    # Voluntary exit on D0 blocked -> no sell submitted.
    d0_blocked = router.process_signal(
        ticker="ITUB4.SA", signal=0, price=30.5, timestamp=d0
    )
    assert d0_blocked.verdict.approved is False
    assert "Swing Trade" in d0_blocked.verdict.reason
    assert d0_blocked.order_receipt is None
    assert proxy.submit_calls == 1

    # Voluntary exit on D1 succeeds.
    current_ts = d1
    d1_sold = router.process_signal(
        ticker="ITUB4.SA", signal=0, price=31.0, timestamp=d1
    )
    assert d1_sold.order_receipt is not None
    assert d1_sold.order_receipt.side == OrderSide.SELL
    assert d1_sold.order_receipt.status == OrderStatus.FILLED
    assert d1_sold.account.positions == {}

    # Emergency exit on same day (d2) bypasses D0 Swing Trade block immediately.
    current_ts = d2
    d2_rebuy = router.process_signal(
        ticker="ITUB4.SA", signal=1, price=31.0, timestamp=d2
    )
    assert d2_rebuy.order_receipt is not None
    assert d2_rebuy.account.positions["ITUB4.SA"].entry_date == d2.date()
    d2_emg = router.process_signal(
        ticker="ITUB4.SA", signal=0, price=31.0, timestamp=d2, is_emergency=True
    )
    assert d2_emg.order_receipt is not None
    assert d2_emg.order_receipt.side == OrderSide.SELL
    assert "[EMERGENCY]" in d2_emg.order_receipt.message
    assert d2_emg.account.positions == {}


def test_ac06_rearms_stop_monitor_when_broker_holds_preexisting_position() -> None:
    """AC06: Fresh OrderRouter syncs StopMonitor from preexisting broker custody."""
    d0 = datetime(2024, 1, 10, 14, 0, tzinfo=timezone.utc)  # noqa: UP017
    d1 = datetime(2024, 1, 11, 14, 0, tzinfo=timezone.utc)  # noqa: UP017
    paper = SimulatedPaperBroker(ExecutionConfig(initial_cash=100.0), clock=lambda: d0)
    paper.submit_order(
        OrderRequest(
            client_order_id="preexisting",
            ticker="ITUB4.SA",
            side=OrderSide.BUY,
            shares=1,
            reference_price=30.0,
        )
    )

    fresh_rm = RiskManager(
        RiskConfig(
            initial_capital=100.0,
            stop_loss_pct=0.05,
            max_daily_loss_pct=0.05,
        )
    )
    router = OrderRouter(paper, fresh_rm)
    res = router.process_signal(ticker="ITUB4.SA", signal=1, price=28.0, timestamp=d1)
    assert res.order_receipt is not None
    assert res.order_receipt.side == OrderSide.SELL
    assert "[EMERGENCY]" in res.order_receipt.message
    assert res.account.positions == {}


# ---------------------------------------------------------------------------
# AC08: Fail-closed constructor and step input guards
# ---------------------------------------------------------------------------


def test_ac08_invalid_router_init_and_step_inputs_fail_closed() -> None:
    """AC08: Malformed constructor args and corrupt step telemetry raise typed errors."""
    paper = SimulatedPaperBroker()

    with pytest.raises(ExecutionConfigurationError):
        OrderRouter("not-a-broker")  # type: ignore[arg-type]
    with pytest.raises(ExecutionConfigurationError):
        OrderRouter(paper, risk_manager="bad")  # type: ignore[arg-type]
    with pytest.raises(ExecutionConfigurationError):
        OrderRouter(paper, config="bad")  # type: ignore[arg-type]
    with pytest.raises(ExecutionConfigurationError):
        OrderRouter(paper, sleep_fn="bad")  # type: ignore[arg-type]
    with pytest.raises(ExecutionConfigurationError):
        OrderRouter(paper, clock="bad")  # type: ignore[arg-type]

    router = OrderRouter(paper)
    ts = datetime(2024, 1, 10, 14, 0, tzinfo=timezone.utc)  # noqa: UP017

    with pytest.raises(InvalidOrderError):
        OrderRouter.build_client_order_id(
            ticker="", side=OrderSide.BUY, shares=1, timestamp=ts
        )
    with pytest.raises(InvalidOrderError):
        router.submit_order_idempotent("bad")  # type: ignore[arg-type]

    for kwargs in [
        {"ticker": " ", "signal": 1, "price": 30.0, "timestamp": ts},
        {"ticker": "ITUB4.SA", "signal": 2, "price": 30.0, "timestamp": ts},
        {"ticker": "ITUB4.SA", "signal": True, "price": 30.0, "timestamp": ts},
        {"ticker": "ITUB4.SA", "signal": 1, "price": math.nan, "timestamp": ts},
        {"ticker": "ITUB4.SA", "signal": 1, "price": -5.0, "timestamp": ts},
        {"ticker": "ITUB4.SA", "signal": 1, "price": 30.0, "timestamp": "2024-01-10"},
        {
            "ticker": "ITUB4.SA",
            "signal": 1,
            "price": 30.0,
            "timestamp": ts,
            "order_type": OrderType.LIMIT,
            "limit_price": None,
        },
        {
            "ticker": "ITUB4.SA",
            "signal": 1,
            "price": 30.0,
            "timestamp": ts,
            "latency_ms": -1.0,
        },
    ]:
        with pytest.raises(InvalidOrderError):
            router.process_signal(**kwargs)  # type: ignore[arg-type]

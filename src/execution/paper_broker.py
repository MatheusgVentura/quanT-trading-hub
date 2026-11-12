"""Simulated B3 fractional paper trading broker implementing IBrokerAdapter."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from src.execution.exceptions import (
    BrokerConnectionError,
    ExecutionConfigurationError,
    ExecutionError,
    InvalidOrderError,
    OrderRejectedError,
)
from src.execution.interfaces import IBrokerAdapter
from src.execution.models import (
    AccountSnapshot,
    ExecutionConfig,
    OrderReceipt,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSnapshot,
    _require_bool,
    _require_finite_number,
    _require_int,
    _require_non_empty_str,
    format_b3_execution_symbol,
)

_STATE_SCHEMA_VERSION = 1
_CASH_EPSILON = 1e-12


def _utc_now() -> datetime:
    """Return current UTC-aware datetime compatible with Python 3.10."""
    return datetime.now(timezone.utc)  # noqa: UP017


@dataclass
class _PositionState:
    """Mutable internal position ledger entry."""

    ticker: str
    shares: int
    avg_entry_price: float
    entry_date: date


@dataclass
class _TrackedOrder:
    """Mutable internal order record combining receipt, metadata, and locks."""

    receipt: OrderReceipt
    order_type: OrderType
    limit_price: float | None
    reserved_cash: float = 0.0
    reserved_shares: int = 0


class SimulatedPaperBroker(IBrokerAdapter):
    """In-memory and atomic-JSON-backed B3 fractional paper trading broker.

    Models a retail spot equity account (default R$ 100.00), fractional `'F'`
    execution symbols for non-multiple-of-100 `.SA` lots, `0.03%` B3 fee / RLP
    zero brokerage, configurable slippage on `MARKET` orders, resting `LIMIT`
    orders matched via `update_market_prices`, Swing Trade entry dates, native
    `client_order_id` idempotency, and optional crash-safe JSON persistence.
    """

    def __init__(
        self,
        config: ExecutionConfig | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        simulated_latency_ms: float = 1.0,
        auto_connect: bool = True,
    ) -> None:
        """Initialize the simulated paper broker and reload persisted state if present.

        Args:
            config: Validated execution parameters. Defaults to `ExecutionConfig()`.
            clock: Optional deterministic UTC/local clock callable.
            simulated_latency_ms: Initial ping latency reported in milliseconds.
            auto_connect: Whether the broker starts in a connected state.

        Raises:
            ExecutionConfigurationError: On invalid arguments or corrupted state file.
        """
        if config is not None and not isinstance(config, ExecutionConfig):
            raise ExecutionConfigurationError(
                "config must be an ExecutionConfig instance or None."
            )
        self.config = config or ExecutionConfig()

        if clock is not None and not callable(clock):
            raise ExecutionConfigurationError("clock must be callable or None.")
        self._clock: Callable[[], datetime] = clock or _utc_now

        lat = _require_finite_number(
            simulated_latency_ms,
            "simulated_latency_ms",
            ExecutionConfigurationError,
        )
        if lat < 0.0:
            raise ExecutionConfigurationError(
                f"simulated_latency_ms cannot be negative, got {lat}."
            )
        self._simulated_latency_ms = lat
        self._connected = _require_bool(
            auto_connect, "auto_connect", ExecutionConfigurationError
        )

        self._cash: float = self.config.initial_cash
        self._realized_pnl: float = 0.0
        self._total_fees_paid: float = 0.0
        self._next_order_seq: int = 1
        self._positions: dict[str, _PositionState] = {}
        self._last_prices: dict[str, float] = {}
        self._orders: dict[str, _TrackedOrder] = {}

        if self.config.state_path is not None and self.config.state_path.exists():
            self._load_state(self.config.state_path)

    # ------------------------------------------------------------------
    # IBrokerAdapter connectivity & telemetry
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Establish active simulated broker connection."""
        self._connected = True

    def disconnect(self) -> None:
        """Simulate transient broker disconnection for resilience testing."""
        self._connected = False

    def is_connected(self) -> bool:
        """Return whether the simulated broker transport is connected."""
        return self._connected

    def ping(self) -> float:
        """Return simulated round-trip heartbeat latency in milliseconds."""
        self._ensure_connected()
        return self._simulated_latency_ms

    def set_simulated_latency_ms(self, latency_ms: float) -> None:
        """Update simulated heartbeat latency reported by `ping()`."""
        lat = _require_finite_number(
            latency_ms, "latency_ms", ExecutionConfigurationError
        )
        if lat < 0.0:
            raise ExecutionConfigurationError(
                f"latency_ms cannot be negative, got {lat}."
            )
        self._simulated_latency_ms = lat

    # ------------------------------------------------------------------
    # Buying power, custody & history views
    # ------------------------------------------------------------------

    @property
    def reserved_cash(self) -> float:
        """Return total cash locked by open resting LIMIT BUY orders."""
        return sum(
            tracked.reserved_cash
            for tracked in self._orders.values()
            if tracked.receipt.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED)
        )

    @property
    def available_cash(self) -> float:
        """Return unencumbered cash available for new BUY orders."""
        return max(0.0, self._cash - self.reserved_cash)

    def get_available_shares(self, ticker: str) -> int:
        """Return held shares not reserved by resting LIMIT SELL orders."""
        clean_ticker = _require_non_empty_str(ticker, "ticker", InvalidOrderError)
        held = (
            self._positions[clean_ticker].shares
            if clean_ticker in self._positions
            else 0
        )
        reserved = sum(
            tracked.reserved_shares
            for tracked in self._orders.values()
            if tracked.receipt.ticker == clean_ticker
            and tracked.receipt.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED)
        )
        return max(0, held - reserved)

    @property
    def order_history(self) -> list[OrderReceipt]:
        """Return all tracked receipts in submission order."""
        return [tracked.receipt for tracked in self._orders.values()]

    # ------------------------------------------------------------------
    # Core IBrokerAdapter order & snapshot operations
    # ------------------------------------------------------------------

    def submit_order(self, order: OrderRequest) -> OrderReceipt:
        """Validate, route, and execute or rest an order idempotently."""
        if not isinstance(order, OrderRequest):
            raise InvalidOrderError("order must be an OrderRequest instance.")
        self._ensure_connected()

        existing = self._orders.get(order.client_order_id)
        if existing is not None:
            self._verify_idempotent_match(existing, order)
            return existing.receipt

        now = self._now()
        exec_symbol = format_b3_execution_symbol(
            order.ticker,
            order.shares,
            use_fractional_suffix=self.config.use_fractional_suffix,
        )

        if order.order_type == OrderType.MARKET:
            fill_price = self._apply_slippage(order.reference_price, order.side)
            broker_order_id = self._allocate_order_id()
            receipt = self._execute_fill(
                broker_order_id=broker_order_id,
                order=order,
                execution_symbol=exec_symbol,
                fill_price=fill_price,
                submitted_at=now,
                filled_at=now,
                mark_price=order.reference_price,
            )
            self._orders[order.client_order_id] = _TrackedOrder(
                receipt=receipt,
                order_type=order.order_type,
                limit_price=None,
            )
            self._persist_if_configured()
            return receipt

        assert order.limit_price is not None
        if self._is_limit_marketable(
            order.side, order.reference_price, order.limit_price
        ):
            broker_order_id = self._allocate_order_id()
            receipt = self._execute_fill(
                broker_order_id=broker_order_id,
                order=order,
                execution_symbol=exec_symbol,
                fill_price=order.reference_price,
                submitted_at=now,
                filled_at=now,
                mark_price=order.reference_price,
            )
            self._orders[order.client_order_id] = _TrackedOrder(
                receipt=receipt,
                order_type=order.order_type,
                limit_price=order.limit_price,
            )
            self._persist_if_configured()
            return receipt

        reserved_cash, reserved_shares = self._reserve_for_resting_limit(order)
        broker_order_id = self._allocate_order_id()
        emergency_tag = "[EMERGENCY] " if order.is_emergency else ""
        receipt = OrderReceipt(
            broker_order_id=broker_order_id,
            client_order_id=order.client_order_id,
            ticker=order.ticker,
            execution_symbol=exec_symbol,
            side=order.side,
            requested_shares=order.shares,
            filled_shares=0,
            fill_price=None,
            b3_fee_paid=0.0,
            status=OrderStatus.SUBMITTED,
            submitted_at=now,
            filled_at=None,
            message=(
                f"{emergency_tag}Resting LIMIT {order.side.value} "
                f"{order.shares} {exec_symbol} @ {order.limit_price:.4f}"
            ),
        )
        self._last_prices[order.ticker] = order.reference_price
        self._orders[order.client_order_id] = _TrackedOrder(
            receipt=receipt,
            order_type=order.order_type,
            limit_price=order.limit_price,
            reserved_cash=reserved_cash,
            reserved_shares=reserved_shares,
        )
        self._persist_if_configured()
        return receipt

    def get_order_by_client_id(self, client_order_id: str) -> OrderReceipt | None:
        """Look up an existing receipt by client idempotency key."""
        self._ensure_connected()
        clean_id = _require_non_empty_str(
            client_order_id, "client_order_id", InvalidOrderError
        )
        tracked = self._orders.get(clean_id)
        return tracked.receipt if tracked is not None else None

    def cancel_all_open_orders(self) -> list[OrderReceipt]:
        """Cancel all resting SUBMITTED/PENDING orders and release reservations."""
        self._ensure_connected()
        cancelled: list[OrderReceipt] = []
        for cid, tracked in self._orders.items():
            if tracked.receipt.status not in (
                OrderStatus.PENDING,
                OrderStatus.SUBMITTED,
            ):
                continue
            old = tracked.receipt
            updated = OrderReceipt(
                broker_order_id=old.broker_order_id,
                client_order_id=old.client_order_id,
                ticker=old.ticker,
                execution_symbol=old.execution_symbol,
                side=old.side,
                requested_shares=old.requested_shares,
                filled_shares=0,
                fill_price=None,
                b3_fee_paid=0.0,
                status=OrderStatus.CANCELLED,
                submitted_at=old.submitted_at,
                filled_at=None,
                message=f"Cancelled: {old.message}",
            )
            self._orders[cid] = _TrackedOrder(
                receipt=updated,
                order_type=tracked.order_type,
                limit_price=tracked.limit_price,
                reserved_cash=0.0,
                reserved_shares=0,
            )
            cancelled.append(updated)

        if cancelled:
            self._persist_if_configured()
        return cancelled

    def update_market_prices(
        self, market_prices: dict[str, float]
    ) -> list[OrderReceipt]:
        """Update market prices and match any resting LIMIT orders whose limit crossed."""
        self._ensure_connected()
        validated = self._validate_market_prices(market_prices, require_non_empty=True)
        now = self._now()

        held_price_changed = any(t in self._positions for t in validated)
        self._last_prices.update(validated)

        filled_now: list[OrderReceipt] = []
        for cid, tracked in list(self._orders.items()):
            receipt = tracked.receipt
            if receipt.status != OrderStatus.SUBMITTED:
                continue
            mkt_px = validated.get(receipt.ticker)
            if mkt_px is None or tracked.limit_price is None:
                continue
            if not self._is_limit_marketable(receipt.side, mkt_px, tracked.limit_price):
                continue

            # Release order reservation before executing actual fill accounting.
            tracked.reserved_cash = 0.0
            tracked.reserved_shares = 0

            synthetic_req = OrderRequest(
                client_order_id=receipt.client_order_id,
                ticker=receipt.ticker,
                side=receipt.side,
                shares=receipt.requested_shares,
                reference_price=mkt_px,
                order_type=OrderType.LIMIT,
                limit_price=tracked.limit_price,
                created_at=receipt.submitted_at,
            )
            filled_receipt = self._execute_fill(
                broker_order_id=receipt.broker_order_id,
                order=synthetic_req,
                execution_symbol=receipt.execution_symbol,
                fill_price=mkt_px,
                submitted_at=receipt.submitted_at,
                filled_at=now,
                mark_price=mkt_px,
            )
            self._orders[cid] = _TrackedOrder(
                receipt=filled_receipt,
                order_type=tracked.order_type,
                limit_price=tracked.limit_price,
                reserved_cash=0.0,
                reserved_shares=0,
            )
            filled_now.append(filled_receipt)

        if filled_now or held_price_changed:
            self._persist_if_configured()
        return filled_now

    def get_account_snapshot(
        self, market_prices: dict[str, float] | None = None
    ) -> AccountSnapshot:
        """Compute current cash, mark-to-market positions, open orders, and equity."""
        self._ensure_connected()
        validated = (
            self._validate_market_prices(market_prices, require_non_empty=False)
            if market_prices is not None
            else {}
        )

        position_snapshots: dict[str, PositionSnapshot] = {}
        positions_value = 0.0
        for ticker, pos in self._positions.items():
            mark_px = validated.get(
                ticker, self._last_prices.get(ticker, pos.avg_entry_price)
            )
            unrealized = (mark_px - pos.avg_entry_price) * pos.shares
            positions_value += pos.shares * mark_px
            position_snapshots[ticker] = PositionSnapshot(
                ticker=pos.ticker,
                shares=pos.shares,
                avg_entry_price=pos.avg_entry_price,
                entry_date=pos.entry_date,
                market_price=mark_px,
                unrealized_pnl=unrealized,
            )

        open_orders = [
            tracked.receipt
            for tracked in self._orders.values()
            if tracked.receipt.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED)
        ]

        return AccountSnapshot(
            cash=self._cash,
            equity=self._cash + positions_value,
            realized_pnl=self._realized_pnl,
            total_fees_paid=self._total_fees_paid,
            positions=position_snapshots,
            open_orders=open_orders,
            timestamp=self._now(),
        )

    def save_state(self) -> None:
        """Persist current broker state atomically when `state_path` is configured."""
        self._persist_if_configured()

    # ------------------------------------------------------------------
    # Internal execution, validation, and atomic JSON serialization
    # ------------------------------------------------------------------

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise BrokerConnectionError(
                "SimulatedPaperBroker is disconnected. Call connect() first."
            )

    def _now(self) -> datetime:
        ts = self._clock()
        if not isinstance(ts, datetime):
            raise InvalidOrderError("clock must return a datetime instance.")
        return ts

    def _allocate_order_id(self) -> str:
        order_id = f"SIM-{self._next_order_seq:06d}"
        self._next_order_seq += 1
        return order_id

    def _verify_idempotent_match(
        self, existing: _TrackedOrder, order: OrderRequest
    ) -> None:
        rec = existing.receipt
        if (
            rec.ticker != order.ticker
            or rec.side != order.side
            or rec.requested_shares != order.shares
            or existing.order_type != order.order_type
            or existing.limit_price != order.limit_price
        ):
            raise OrderRejectedError(
                f"Conflicting retry parameters for existing client_order_id "
                f"{order.client_order_id!r}."
            )

    def _apply_slippage(self, price: float, side: OrderSide) -> float:
        if side == OrderSide.BUY:
            return price * (1.0 + self.config.slippage_pct)
        return price * (1.0 - self.config.slippage_pct)

    @staticmethod
    def _is_limit_marketable(
        side: OrderSide, market_price: float, limit_price: float
    ) -> bool:
        if side == OrderSide.BUY:
            return market_price <= limit_price
        return market_price >= limit_price

    def _calculate_fee(self, notional: float) -> float:
        return notional * self.config.b3_fee_pct + self.config.brokerage_fee

    def _reserve_for_resting_limit(self, order: OrderRequest) -> tuple[float, int]:
        assert order.limit_price is not None
        if order.side == OrderSide.BUY:
            notional = order.shares * order.limit_price
            required = notional + self._calculate_fee(notional)
            avail = self.available_cash
            if required > avail + _CASH_EPSILON:
                raise OrderRejectedError(
                    f"Insufficient available buying power for LIMIT BUY {order.ticker}: "
                    f"need {required:.4f}, available {avail:.4f}."
                )
            return required, 0

        avail_shares = self.get_available_shares(order.ticker)
        if order.shares > avail_shares:
            raise OrderRejectedError(
                f"Insufficient unencumbered shares to LIMIT SELL {order.shares} of "
                f"{order.ticker}: available {avail_shares}."
            )
        return 0.0, order.shares

    def _execute_fill(
        self,
        *,
        broker_order_id: str,
        order: OrderRequest,
        execution_symbol: str,
        fill_price: float,
        submitted_at: datetime,
        filled_at: datetime,
        mark_price: float,
    ) -> OrderReceipt:
        notional = order.shares * fill_price
        fee = self._calculate_fee(notional)

        if order.side == OrderSide.BUY:
            total_cost = notional + fee
            avail = self.available_cash
            if total_cost > avail + _CASH_EPSILON:
                raise OrderRejectedError(
                    f"Insufficient cash for BUY {order.shares} {order.ticker}: "
                    f"need {total_cost:.4f}, available {avail:.4f}."
                )
            self._cash = max(0.0, self._cash - total_cost)
            self._total_fees_paid += fee
            self._add_custody(
                ticker=order.ticker,
                shares=order.shares,
                fill_price=fill_price,
                entry_date=filled_at.date(),
            )
        else:
            avail_shares = self.get_available_shares(order.ticker)
            if order.shares > avail_shares:
                raise OrderRejectedError(
                    f"Insufficient shares for SELL {order.shares} {order.ticker}: "
                    f"available {avail_shares}."
                )
            net_proceeds = notional - fee
            if self._cash + net_proceeds < -_CASH_EPSILON:
                raise OrderRejectedError(
                    f"Cash and proceeds insufficient to cover sell fees for "
                    f"{order.ticker}."
                )
            pos = self._positions[order.ticker]
            self._cash = max(0.0, self._cash + net_proceeds)
            self._total_fees_paid += fee
            self._realized_pnl += (fill_price - pos.avg_entry_price) * order.shares
            self._reduce_custody(order.ticker, order.shares)

        self._last_prices[order.ticker] = mark_price
        emergency_tag = "[EMERGENCY] " if order.is_emergency else ""
        return OrderReceipt(
            broker_order_id=broker_order_id,
            client_order_id=order.client_order_id,
            ticker=order.ticker,
            execution_symbol=execution_symbol,
            side=order.side,
            requested_shares=order.shares,
            filled_shares=order.shares,
            fill_price=fill_price,
            b3_fee_paid=fee,
            status=OrderStatus.FILLED,
            submitted_at=submitted_at,
            filled_at=filled_at,
            message=(
                f"{emergency_tag}Filled {order.order_type.value} {order.side.value} "
                f"{order.shares} {execution_symbol} @ {fill_price:.4f}"
            ),
        )

    def _add_custody(
        self, *, ticker: str, shares: int, fill_price: float, entry_date: date
    ) -> None:
        existing = self._positions.get(ticker)
        if existing is None:
            self._positions[ticker] = _PositionState(
                ticker=ticker,
                shares=shares,
                avg_entry_price=fill_price,
                entry_date=entry_date,
            )
            return
        total_shares = existing.shares + shares
        weighted_avg = (
            existing.shares * existing.avg_entry_price + shares * fill_price
        ) / total_shares
        self._positions[ticker] = _PositionState(
            ticker=ticker,
            shares=total_shares,
            avg_entry_price=weighted_avg,
            entry_date=max(existing.entry_date, entry_date),
        )

    def _reduce_custody(self, ticker: str, shares: int) -> None:
        pos = self._positions[ticker]
        remaining = pos.shares - shares
        if remaining == 0:
            del self._positions[ticker]
        else:
            self._positions[ticker] = _PositionState(
                ticker=pos.ticker,
                shares=remaining,
                avg_entry_price=pos.avg_entry_price,
                entry_date=pos.entry_date,
            )

    @staticmethod
    def _validate_market_prices(
        market_prices: object, *, require_non_empty: bool
    ) -> dict[str, float]:
        if not isinstance(market_prices, dict):
            raise InvalidOrderError(
                "market_prices must be a dict mapping ticker to price."
            )
        if require_non_empty and not market_prices:
            raise InvalidOrderError("market_prices cannot be empty.")
        cleaned: dict[str, float] = {}
        for raw_ticker, raw_price in market_prices.items():
            ticker = _require_non_empty_str(raw_ticker, "ticker", InvalidOrderError)
            price = _require_finite_number(
                raw_price, f"price[{ticker}]", InvalidOrderError
            )
            if price <= 0.0:
                raise InvalidOrderError(
                    f"market_prices[{ticker!r}] must be strictly positive, got {price}."
                )
            cleaned[ticker] = price
        return cleaned

    def _persist_if_configured(self) -> None:
        target = self.config.state_path
        if target is None:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._serialize_state(), indent=2, sort_keys=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(target.parent),
            prefix=f".{target.stem}_",
            suffix=".tmp",
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, target)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise

    def _serialize_state(self) -> dict[str, Any]:
        return {
            "schema_version": _STATE_SCHEMA_VERSION,
            "initial_cash": self.config.initial_cash,
            "cash": self._cash,
            "realized_pnl": self._realized_pnl,
            "total_fees_paid": self._total_fees_paid,
            "next_order_seq": self._next_order_seq,
            "last_prices": dict(self._last_prices),
            "positions": {
                ticker: {
                    "ticker": pos.ticker,
                    "shares": pos.shares,
                    "avg_entry_price": pos.avg_entry_price,
                    "entry_date": pos.entry_date.isoformat(),
                }
                for ticker, pos in self._positions.items()
            },
            "orders": [
                {
                    "broker_order_id": t.receipt.broker_order_id,
                    "client_order_id": t.receipt.client_order_id,
                    "ticker": t.receipt.ticker,
                    "execution_symbol": t.receipt.execution_symbol,
                    "side": t.receipt.side.value,
                    "order_type": t.order_type.value,
                    "requested_shares": t.receipt.requested_shares,
                    "filled_shares": t.receipt.filled_shares,
                    "fill_price": t.receipt.fill_price,
                    "limit_price": t.limit_price,
                    "b3_fee_paid": t.receipt.b3_fee_paid,
                    "reserved_cash": t.reserved_cash,
                    "reserved_shares": t.reserved_shares,
                    "status": t.receipt.status.value,
                    "submitted_at": t.receipt.submitted_at.isoformat(),
                    "filled_at": (
                        t.receipt.filled_at.isoformat()
                        if t.receipt.filled_at is not None
                        else None
                    ),
                    "message": t.receipt.message,
                }
                for t in self._orders.values()
            ],
        }

    def _load_state(self, path: Path) -> None:
        try:
            raw_text = path.read_text(encoding="utf-8")
            data = json.loads(raw_text)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ExecutionConfigurationError(
                f"Failed to read paper broker state from {path}: {exc}"
            ) from exc

        if not isinstance(data, dict):
            raise ExecutionConfigurationError(
                f"Corrupted paper broker state in {path}: root must be a JSON object."
            )

        try:
            version = _require_int(
                data.get("schema_version"),
                "schema_version",
                min_val=1,
                exc_cls=ExecutionConfigurationError,
            )
            if version != _STATE_SCHEMA_VERSION:
                raise ExecutionConfigurationError(
                    f"Unsupported state schema_version: {version}."
                )

            cash = _require_finite_number(
                data.get("cash"), "cash", ExecutionConfigurationError
            )
            if cash < 0.0:
                raise ExecutionConfigurationError(
                    f"Saved cash cannot be negative: {cash}."
                )

            realized_pnl = _require_finite_number(
                data.get("realized_pnl"), "realized_pnl", ExecutionConfigurationError
            )
            total_fees_paid = _require_finite_number(
                data.get("total_fees_paid"),
                "total_fees_paid",
                ExecutionConfigurationError,
            )
            if total_fees_paid < 0.0:
                raise ExecutionConfigurationError(
                    f"Saved total_fees_paid cannot be negative: {total_fees_paid}."
                )

            next_seq = _require_int(
                data.get("next_order_seq"),
                "next_order_seq",
                min_val=1,
                exc_cls=ExecutionConfigurationError,
            )

            raw_prices = data.get("last_prices", {})
            last_prices = self._validate_market_prices(
                raw_prices, require_non_empty=False
            )

            positions = self._parse_positions(data.get("positions"))
            orders = self._parse_orders(data.get("orders"))
        except ExecutionConfigurationError:
            raise
        except (ExecutionError, ValueError, TypeError, KeyError) as exc:
            raise ExecutionConfigurationError(
                f"Corrupted paper broker state schema in {path}: {exc}"
            ) from exc

        self._cash = cash
        self._realized_pnl = realized_pnl
        self._total_fees_paid = total_fees_paid
        self._next_order_seq = next_seq
        self._last_prices = last_prices
        self._positions = positions
        self._orders = orders

    @staticmethod
    def _parse_positions(raw_positions: object) -> dict[str, _PositionState]:
        if not isinstance(raw_positions, dict):
            raise ExecutionConfigurationError("positions must be a JSON object.")
        parsed: dict[str, _PositionState] = {}
        for key, raw in raw_positions.items():
            ticker_key = _require_non_empty_str(
                key, "position_key", ExecutionConfigurationError
            )
            if not isinstance(raw, dict):
                raise ExecutionConfigurationError(
                    f"Position entry {ticker_key!r} must be an object."
                )
            ticker = _require_non_empty_str(
                raw.get("ticker"), "ticker", ExecutionConfigurationError
            )
            if ticker != ticker_key:
                raise ExecutionConfigurationError(
                    f"Position key {ticker_key!r} mismatches ticker {ticker!r}."
                )
            shares = _require_int(
                raw.get("shares"),
                "shares",
                min_val=1,
                exc_cls=ExecutionConfigurationError,
            )
            avg = _require_finite_number(
                raw.get("avg_entry_price"),
                "avg_entry_price",
                ExecutionConfigurationError,
            )
            if avg <= 0.0:
                raise ExecutionConfigurationError(
                    f"avg_entry_price must be positive for {ticker}, got {avg}."
                )
            entry_date_raw = _require_non_empty_str(
                raw.get("entry_date"), "entry_date", ExecutionConfigurationError
            )
            entry_date = date.fromisoformat(entry_date_raw)
            parsed[ticker] = _PositionState(
                ticker=ticker,
                shares=shares,
                avg_entry_price=avg,
                entry_date=entry_date,
            )
        return parsed

    @staticmethod
    def _parse_orders(raw_orders: object) -> dict[str, _TrackedOrder]:
        if not isinstance(raw_orders, list):
            raise ExecutionConfigurationError("orders must be a JSON array.")
        parsed: dict[str, _TrackedOrder] = {}
        for item in raw_orders:
            if not isinstance(item, dict):
                raise ExecutionConfigurationError(
                    "Each order entry must be a JSON object."
                )

            side = OrderSide(
                _require_non_empty_str(
                    item.get("side"), "side", ExecutionConfigurationError
                )
            )
            order_type = OrderType(
                _require_non_empty_str(
                    item.get("order_type"), "order_type", ExecutionConfigurationError
                )
            )
            status = OrderStatus(
                _require_non_empty_str(
                    item.get("status"), "status", ExecutionConfigurationError
                )
            )
            submitted_str = _require_non_empty_str(
                item.get("submitted_at"), "submitted_at", ExecutionConfigurationError
            )
            submitted_at = datetime.fromisoformat(submitted_str)

            raw_filled_at = item.get("filled_at")
            filled_at: datetime | None = None
            if raw_filled_at is not None:
                filled_at_str = _require_non_empty_str(
                    raw_filled_at, "filled_at", ExecutionConfigurationError
                )
                filled_at = datetime.fromisoformat(filled_at_str)

            raw_fill_px = item.get("fill_price")
            fill_price = (
                _require_finite_number(
                    raw_fill_px, "fill_price", ExecutionConfigurationError
                )
                if raw_fill_px is not None
                else None
            )

            raw_limit_px = item.get("limit_price")
            limit_price = (
                _require_finite_number(
                    raw_limit_px, "limit_price", ExecutionConfigurationError
                )
                if raw_limit_px is not None
                else None
            )
            if limit_price is not None and limit_price <= 0.0:
                raise ExecutionConfigurationError(
                    f"limit_price must be strictly positive, got {limit_price}."
                )
            if order_type == OrderType.LIMIT and limit_price is None:
                raise ExecutionConfigurationError(
                    "LIMIT order entry in state file must include limit_price."
                )

            reserved_cash = _require_finite_number(
                item.get("reserved_cash", 0.0),
                "reserved_cash",
                ExecutionConfigurationError,
            )
            if reserved_cash < 0.0:
                raise ExecutionConfigurationError("reserved_cash cannot be negative.")
            reserved_shares = _require_int(
                item.get("reserved_shares", 0),
                "reserved_shares",
                min_val=0,
                exc_cls=ExecutionConfigurationError,
            )

            raw_message = item.get("message", "")
            if not isinstance(raw_message, str):
                raise ExecutionConfigurationError("order message must be a string.")

            receipt = OrderReceipt(
                broker_order_id=_require_non_empty_str(
                    item.get("broker_order_id"),
                    "broker_order_id",
                    ExecutionConfigurationError,
                ),
                client_order_id=_require_non_empty_str(
                    item.get("client_order_id"),
                    "client_order_id",
                    ExecutionConfigurationError,
                ),
                ticker=_require_non_empty_str(
                    item.get("ticker"), "ticker", ExecutionConfigurationError
                ),
                execution_symbol=_require_non_empty_str(
                    item.get("execution_symbol"),
                    "execution_symbol",
                    ExecutionConfigurationError,
                ),
                side=side,
                requested_shares=_require_int(
                    item.get("requested_shares"),
                    "requested_shares",
                    min_val=1,
                    exc_cls=ExecutionConfigurationError,
                ),
                filled_shares=_require_int(
                    item.get("filled_shares"),
                    "filled_shares",
                    min_val=0,
                    exc_cls=ExecutionConfigurationError,
                ),
                fill_price=fill_price,
                b3_fee_paid=_require_finite_number(
                    item.get("b3_fee_paid"), "b3_fee_paid", ExecutionConfigurationError
                ),
                status=status,
                submitted_at=submitted_at,
                filled_at=filled_at,
                message=raw_message,
            )
            if receipt.client_order_id in parsed:
                raise ExecutionConfigurationError(
                    f"Duplicate client_order_id {receipt.client_order_id!r} in state file."
                )
            parsed[receipt.client_order_id] = _TrackedOrder(
                receipt=receipt,
                order_type=order_type,
                limit_price=limit_price,
                reserved_cash=reserved_cash,
                reserved_shares=reserved_shares,
            )
        return parsed

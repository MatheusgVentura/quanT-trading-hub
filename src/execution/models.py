"""Validated data models, enums, and configuration for order execution."""

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path

from src.execution.exceptions import (
    ExecutionConfigurationError,
    ExecutionError,
    InvalidOrderError,
)
from src.risk.models import RiskVerdict


class OrderSide(str, Enum):
    """Side of a spot equity order."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Supported order execution instruction types."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(str, Enum):
    """Lifecycle status of an order tracked by the broker adapter."""

    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


def _require_finite_number(
    value: object,
    field_name: str,
    exc_cls: type[ExecutionError],
) -> float:
    """Validate that a value is a non-boolean finite float/int."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise exc_cls(f"{field_name} must be a numeric value.")
    num = float(value)
    if not math.isfinite(num):
        raise exc_cls(f"{field_name} must be finite.")
    return num


def _require_non_empty_str(
    value: object,
    field_name: str,
    exc_cls: type[ExecutionError],
) -> str:
    """Validate that a value is a non-empty string after stripping whitespace."""
    if not isinstance(value, str) or not value.strip():
        raise exc_cls(f"{field_name} must be a non-empty string.")
    return value.strip()


def _require_int(
    value: object,
    field_name: str,
    *,
    min_val: int,
    exc_cls: type[ExecutionError],
) -> int:
    """Validate a non-boolean integer respecting a minimum bound."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise exc_cls(f"{field_name} must be an integer.")
    if value < min_val:
        raise exc_cls(f"{field_name} must be >= {min_val}, got {value}.")
    return value


def _require_bool(
    value: object,
    field_name: str,
    exc_cls: type[ExecutionError],
) -> bool:
    """Validate that a flag is strictly a boolean."""
    if not isinstance(value, bool):
        raise exc_cls(f"{field_name} must be a boolean.")
    return value


def _require_unit_fraction(
    value: object,
    field_name: str,
    exc_cls: type[ExecutionError],
) -> float:
    """Validate a percentage expressed in [0.0, 1.0)."""
    num = _require_finite_number(value, field_name, exc_cls)
    if num < 0.0 or num >= 1.0:
        raise exc_cls(f"{field_name} must be in [0.0, 1.0), got {num}.")
    return num


def format_b3_execution_symbol(
    ticker: str,
    shares: int,
    *,
    use_fractional_suffix: bool = True,
) -> str:
    """Map canonical `.SA` tickers to B3 fractional `'F'` symbols for odd lots.

    Args:
        ticker: Canonical market symbol (e.g., `'ITUB4.SA'` or `'AAPL'`).
        shares: Positive integer share quantity being routed.
        use_fractional_suffix: Whether to map `.SA` tickers to B3 execution format.

    Returns:
        Formatted execution symbol (e.g., `'ITUB4F'` for 1-99 shares, `'ITUB4'` for
        multiples of 100, or unchanged `ticker` when disabled / non-`.SA`).

    Raises:
        InvalidOrderError: If `ticker` is empty or `shares` is not positive.
    """
    clean_ticker = _require_non_empty_str(ticker, "ticker", InvalidOrderError)
    qty = _require_int(shares, "shares", min_val=1, exc_cls=InvalidOrderError)
    if not use_fractional_suffix:
        return clean_ticker
    if clean_ticker.upper().endswith(".SA"):
        root = clean_ticker[:-3].upper()
        if not root:
            raise InvalidOrderError("B3 ticker root before '.SA' cannot be empty.")
        if qty % 100 != 0 and not root.endswith("F"):
            return f"{root}F"
        return root
    return clean_ticker


@dataclass(frozen=True)
class ExecutionConfig:
    """Validated configuration governing execution fees, retries, and state."""

    initial_cash: float = 100.0
    b3_fee_pct: float = 0.0003
    brokerage_fee: float = 0.0
    slippage_pct: float = 0.0
    use_fractional_suffix: bool = True
    max_retries: int = 3
    base_backoff_seconds: float = 0.5
    backoff_multiplier: float = 2.0
    request_timeout_seconds: float = 5.0
    liquidate_on_halt: bool = True
    state_path: Path | None = None

    def __post_init__(self) -> None:
        """Validate execution configuration boundaries."""
        cash = _require_finite_number(
            self.initial_cash, "initial_cash", ExecutionConfigurationError
        )
        if cash <= 0.0:
            raise ExecutionConfigurationError(
                f"initial_cash must be strictly positive, got {cash}."
            )

        _require_unit_fraction(
            self.b3_fee_pct, "b3_fee_pct", ExecutionConfigurationError
        )
        fee = _require_finite_number(
            self.brokerage_fee, "brokerage_fee", ExecutionConfigurationError
        )
        if fee < 0.0:
            raise ExecutionConfigurationError(
                f"brokerage_fee cannot be negative, got {fee}."
            )
        _require_unit_fraction(
            self.slippage_pct, "slippage_pct", ExecutionConfigurationError
        )
        _require_bool(
            self.use_fractional_suffix,
            "use_fractional_suffix",
            ExecutionConfigurationError,
        )
        _require_int(
            self.max_retries,
            "max_retries",
            min_val=0,
            exc_cls=ExecutionConfigurationError,
        )

        backoff = _require_finite_number(
            self.base_backoff_seconds,
            "base_backoff_seconds",
            ExecutionConfigurationError,
        )
        if backoff < 0.0:
            raise ExecutionConfigurationError(
                f"base_backoff_seconds cannot be negative, got {backoff}."
            )

        mult = _require_finite_number(
            self.backoff_multiplier,
            "backoff_multiplier",
            ExecutionConfigurationError,
        )
        if mult < 1.0:
            raise ExecutionConfigurationError(
                f"backoff_multiplier must be >= 1.0, got {mult}."
            )

        timeout = _require_finite_number(
            self.request_timeout_seconds,
            "request_timeout_seconds",
            ExecutionConfigurationError,
        )
        if timeout <= 0.0:
            raise ExecutionConfigurationError(
                f"request_timeout_seconds must be strictly positive, got {timeout}."
            )

        _require_bool(
            self.liquidate_on_halt, "liquidate_on_halt", ExecutionConfigurationError
        )

        if self.state_path is not None:
            if isinstance(self.state_path, str):
                cleaned = _require_non_empty_str(
                    self.state_path, "state_path", ExecutionConfigurationError
                )
                object.__setattr__(self, "state_path", Path(cleaned))
            elif (
                not isinstance(self.state_path, Path)
                or not str(self.state_path).strip()
            ):
                raise ExecutionConfigurationError(
                    "state_path must be a non-empty Path, string, or None."
                )


@dataclass(frozen=True)
class OrderRequest:
    """Validated order submission request carrying an idempotency key."""

    client_order_id: str
    ticker: str
    side: OrderSide
    shares: int
    reference_price: float
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)  # noqa: UP017
    )
    is_emergency: bool = False
    reason: str = ""

    def __post_init__(self) -> None:
        """Enforce fail-closed order invariants on creation."""
        cid = _require_non_empty_str(
            self.client_order_id, "client_order_id", InvalidOrderError
        )
        ticker = _require_non_empty_str(self.ticker, "ticker", InvalidOrderError)
        object.__setattr__(self, "client_order_id", cid)
        object.__setattr__(self, "ticker", ticker)

        if not isinstance(self.side, OrderSide):
            raise InvalidOrderError("side must be a valid OrderSide enum member.")
        if not isinstance(self.order_type, OrderType):
            raise InvalidOrderError("order_type must be a valid OrderType enum member.")

        _require_int(self.shares, "shares", min_val=1, exc_cls=InvalidOrderError)

        ref_px = _require_finite_number(
            self.reference_price, "reference_price", InvalidOrderError
        )
        if ref_px <= 0.0:
            raise InvalidOrderError(
                f"reference_price must be strictly positive, got {ref_px}."
            )

        if self.order_type == OrderType.LIMIT:
            if self.limit_price is None:
                raise InvalidOrderError(
                    "limit_price is required for LIMIT order requests."
                )
            lim_px = _require_finite_number(
                self.limit_price, "limit_price", InvalidOrderError
            )
            if lim_px <= 0.0:
                raise InvalidOrderError(
                    f"limit_price must be strictly positive, got {lim_px}."
                )
        elif self.limit_price is not None:
            raise InvalidOrderError(
                "limit_price must be None when order_type is MARKET."
            )

        if not isinstance(self.created_at, datetime):
            raise InvalidOrderError("created_at must be a datetime instance.")
        _require_bool(self.is_emergency, "is_emergency", InvalidOrderError)


@dataclass(frozen=True)
class OrderReceipt:
    """Immutable broker acknowledgment and fill report for a routed order."""

    broker_order_id: str
    client_order_id: str
    ticker: str
    execution_symbol: str
    side: OrderSide
    requested_shares: int
    filled_shares: int
    fill_price: float | None
    b3_fee_paid: float
    status: OrderStatus
    submitted_at: datetime
    filled_at: datetime | None
    message: str

    def __post_init__(self) -> None:
        """Validate receipt invariants."""
        _require_non_empty_str(
            self.broker_order_id, "broker_order_id", InvalidOrderError
        )
        _require_non_empty_str(
            self.client_order_id, "client_order_id", InvalidOrderError
        )
        _require_non_empty_str(self.ticker, "ticker", InvalidOrderError)
        _require_non_empty_str(
            self.execution_symbol, "execution_symbol", InvalidOrderError
        )
        if not isinstance(self.side, OrderSide):
            raise InvalidOrderError("side must be a valid OrderSide enum member.")
        if not isinstance(self.status, OrderStatus):
            raise InvalidOrderError("status must be a valid OrderStatus enum member.")

        req = _require_int(
            self.requested_shares,
            "requested_shares",
            min_val=1,
            exc_cls=InvalidOrderError,
        )
        filled = _require_int(
            self.filled_shares, "filled_shares", min_val=0, exc_cls=InvalidOrderError
        )
        if filled > req:
            raise InvalidOrderError(
                f"filled_shares ({filled}) cannot exceed requested_shares ({req})."
            )

        if filled > 0:
            if self.fill_price is None:
                raise InvalidOrderError(
                    "fill_price is required when filled_shares > 0."
                )
            px = _require_finite_number(
                self.fill_price, "fill_price", InvalidOrderError
            )
            if px <= 0.0:
                raise InvalidOrderError(
                    f"fill_price must be strictly positive, got {px}."
                )
        elif self.fill_price is not None:
            px = _require_finite_number(
                self.fill_price, "fill_price", InvalidOrderError
            )
            if px <= 0.0:
                raise InvalidOrderError(
                    f"fill_price must be strictly positive when provided, got {px}."
                )

        fee = _require_finite_number(self.b3_fee_paid, "b3_fee_paid", InvalidOrderError)
        if fee < 0.0:
            raise InvalidOrderError(f"b3_fee_paid cannot be negative, got {fee}.")
        if not isinstance(self.submitted_at, datetime):
            raise InvalidOrderError("submitted_at must be a datetime instance.")
        if self.filled_at is not None and not isinstance(self.filled_at, datetime):
            raise InvalidOrderError("filled_at must be a datetime instance or None.")


@dataclass(frozen=True)
class PositionSnapshot:
    """Snapshot of a held spot equity position with Swing Trade entry metadata."""

    ticker: str
    shares: int
    avg_entry_price: float
    entry_date: date
    market_price: float
    unrealized_pnl: float

    def __post_init__(self) -> None:
        """Validate custody position invariants."""
        _require_non_empty_str(self.ticker, "ticker", InvalidOrderError)
        qty = _require_int(self.shares, "shares", min_val=0, exc_cls=InvalidOrderError)
        avg = _require_finite_number(
            self.avg_entry_price, "avg_entry_price", InvalidOrderError
        )
        if qty > 0 and avg <= 0.0:
            raise InvalidOrderError(
                f"avg_entry_price must be strictly positive when shares > 0, got {avg}."
            )
        if qty == 0 and avg < 0.0:
            raise InvalidOrderError(f"avg_entry_price cannot be negative, got {avg}.")

        mkt = _require_finite_number(
            self.market_price, "market_price", InvalidOrderError
        )
        if mkt <= 0.0:
            raise InvalidOrderError(
                f"market_price must be strictly positive, got {mkt}."
            )
        _require_finite_number(self.unrealized_pnl, "unrealized_pnl", InvalidOrderError)
        if not isinstance(self.entry_date, date):
            raise InvalidOrderError("entry_date must be a datetime.date.")


@dataclass(frozen=True)
class AccountSnapshot:
    """Reconciled broker account state snapshot."""

    cash: float
    equity: float
    realized_pnl: float
    total_fees_paid: float
    positions: dict[str, PositionSnapshot]
    open_orders: list[OrderReceipt]
    timestamp: datetime

    def __post_init__(self) -> None:
        """Validate account financial totals and timestamp."""
        cash = _require_finite_number(self.cash, "cash", InvalidOrderError)
        if cash < 0.0:
            raise InvalidOrderError(f"cash cannot be negative, got {cash}.")
        equity = _require_finite_number(self.equity, "equity", InvalidOrderError)
        if equity < 0.0:
            raise InvalidOrderError(f"equity cannot be negative, got {equity}.")
        _require_finite_number(self.realized_pnl, "realized_pnl", InvalidOrderError)
        fees = _require_finite_number(
            self.total_fees_paid, "total_fees_paid", InvalidOrderError
        )
        if fees < 0.0:
            raise InvalidOrderError(f"total_fees_paid cannot be negative, got {fees}.")
        if not isinstance(self.timestamp, datetime):
            raise InvalidOrderError("timestamp must be a datetime instance.")


@dataclass(frozen=True)
class ExecutionStepResult:
    """Output of a single signal-to-order execution cycle."""

    ticker: str
    signal: int
    verdict: RiskVerdict
    order_receipt: OrderReceipt | None
    account: AccountSnapshot
    halted: bool
    cancelled_orders_count: int
    latency_ms: float
    timestamp: datetime

    def __post_init__(self) -> None:
        """Validate execution step summary metrics."""
        _require_non_empty_str(self.ticker, "ticker", InvalidOrderError)
        if (
            isinstance(self.signal, bool)
            or not isinstance(self.signal, int)
            or self.signal not in (0, 1)
        ):
            raise InvalidOrderError(
                f"signal must be binary 0 or 1, got {self.signal!r}."
            )
        _require_bool(self.halted, "halted", InvalidOrderError)
        _require_int(
            self.cancelled_orders_count,
            "cancelled_orders_count",
            min_val=0,
            exc_cls=InvalidOrderError,
        )
        lat = _require_finite_number(self.latency_ms, "latency_ms", InvalidOrderError)
        if lat < 0.0:
            raise InvalidOrderError(f"latency_ms cannot be negative, got {lat}.")
        if not isinstance(self.timestamp, datetime):
            raise InvalidOrderError("timestamp must be a datetime instance.")

"""Resilient idempotent order router integrating RiskManager gates and broker retries."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TypeVar

from src.execution.exceptions import (
    BrokerConnectionError,
    ExecutionConfigurationError,
    ExecutionHaltedError,
    InvalidOrderError,
)
from src.execution.interfaces import IBrokerAdapter
from src.execution.models import (
    AccountSnapshot,
    ExecutionConfig,
    ExecutionStepResult,
    OrderReceipt,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    _require_bool,
    _require_finite_number,
    _require_non_empty_str,
)
from src.risk.manager import RiskManager
from src.risk.models import RiskStatus, RiskVerdict

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


def _utc_now() -> datetime:
    """Return current UTC-aware datetime compatible with Python 3.10."""
    return datetime.now(timezone.utc)  # noqa: UP017


def _default_sleep(seconds: float) -> None:
    """Defer sleeping lazily using stdlib time.sleep."""
    import time

    time.sleep(seconds)


class OrderRouter:
    """Pre-trade risk-gated, idempotent, retry-capable execution router.

    Coordinates `IBrokerAdapter` connectivity, exponential-backoff recovery with
    mandatory post-reconnect state reconciliation, `client_order_id` idempotency
    on timeout/retry, `RiskManager.evaluate_trade` gating, and fail-closed
    Kill-Switch cancellation and emergency liquidation.
    """

    def __init__(
        self,
        broker: IBrokerAdapter,
        risk_manager: RiskManager | None = None,
        config: ExecutionConfig | None = None,
        *,
        sleep_fn: Callable[[float], None] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialize OrderRouter with broker adapter, risk manager, and retry config."""
        if not isinstance(broker, IBrokerAdapter):
            raise ExecutionConfigurationError(
                "broker must implement the IBrokerAdapter interface."
            )
        if risk_manager is not None and not isinstance(risk_manager, RiskManager):
            raise ExecutionConfigurationError(
                "risk_manager must be a RiskManager instance or None."
            )
        if config is not None and not isinstance(config, ExecutionConfig):
            raise ExecutionConfigurationError(
                "config must be an ExecutionConfig instance or None."
            )
        if sleep_fn is not None and not callable(sleep_fn):
            raise ExecutionConfigurationError("sleep_fn must be callable or None.")
        if clock is not None and not callable(clock):
            raise ExecutionConfigurationError("clock must be callable or None.")

        self.broker = broker
        self.risk_manager = risk_manager or RiskManager()
        self.config = config or ExecutionConfig()
        self._sleep: Callable[[float], None] = sleep_fn or _default_sleep
        self._clock: Callable[[], datetime] = clock or _utc_now
        self._last_snapshot: AccountSnapshot | None = None

    @property
    def last_snapshot(self) -> AccountSnapshot | None:
        """Return the most recently synchronized broker account snapshot, if any."""
        return self._last_snapshot

    @staticmethod
    def build_client_order_id(
        *,
        ticker: str,
        side: OrderSide,
        shares: int,
        timestamp: datetime,
        tag: str = "",
    ) -> str:
        """Build a deterministic client_order_id from canonical order parameters."""
        clean_ticker = _require_non_empty_str(ticker, "ticker", InvalidOrderError)
        if not isinstance(side, OrderSide):
            raise InvalidOrderError("side must be a valid OrderSide enum member.")
        if isinstance(shares, bool) or not isinstance(shares, int) or shares < 1:
            raise InvalidOrderError("shares must be a strictly positive integer.")
        if not isinstance(timestamp, datetime):
            raise InvalidOrderError("timestamp must be a datetime instance.")

        canonical = (
            f"{clean_ticker}|{side.value}|{shares}|{timestamp.isoformat()}|{tag}"
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
        prefix = clean_ticker.replace(".", "-")
        return f"QTH-{prefix}-{side.value}-{digest}"

    # ------------------------------------------------------------------
    # Resilient primitives (AC01 & AC02)
    # ------------------------------------------------------------------

    def sync_account(
        self, market_prices: dict[str, float] | None = None
    ) -> tuple[AccountSnapshot, float]:
        """Ensure broker connection and synchronize account snapshot and latency."""
        validated_prices = self._validate_market_prices(market_prices)

        def _fetch() -> tuple[AccountSnapshot, float]:
            latency_ms = self.broker.ping()
            snapshot = self.broker.get_account_snapshot(
                market_prices=validated_prices or None
            )
            return snapshot, latency_ms

        (snapshot, latency_ms), _ = self._execute_with_backoff(_fetch)
        self._last_snapshot = snapshot
        return snapshot, latency_ms

    def submit_order_idempotent(
        self,
        order: OrderRequest,
        *,
        market_prices: dict[str, float] | None = None,
    ) -> OrderReceipt:
        """Submit an order idempotently with exponential backoff and reconnect sync."""
        if not isinstance(order, OrderRequest):
            raise InvalidOrderError("order must be an OrderRequest instance.")
        validated_prices = self._validate_market_prices(market_prices)

        def _submit(attempt: int) -> OrderReceipt:
            if attempt > 0:
                existing = self.broker.get_order_by_client_id(order.client_order_id)
                if existing is not None:
                    logger.info(
                        "Idempotent recovery matched existing receipt client_order_id=%s status=%s",
                        order.client_order_id,
                        existing.status.value,
                    )
                    return existing
            return self.broker.submit_order(order)

        receipt, recovered = self._execute_with_backoff_attempt(_submit)
        if recovered:
            # Reconcile open orders and cash/custody state immediately upon recovery.
            self._last_snapshot = self.broker.get_account_snapshot(
                market_prices=validated_prices or None
            )
        return receipt

    def cancel_all_open_orders_resilient(
        self, *, market_prices: dict[str, float] | None = None
    ) -> list[OrderReceipt]:
        """Cancel all open orders with exponential backoff retries and recovery sync."""
        validated_prices = self._validate_market_prices(market_prices)
        cancelled, recovered = self._execute_with_backoff(
            self.broker.cancel_all_open_orders
        )
        if recovered:
            self._last_snapshot = self.broker.get_account_snapshot(
                market_prices=validated_prices or None
            )
        return cancelled

    # ------------------------------------------------------------------
    # Full gated signal-to-order orchestration (AC03, AC06, AC07)
    # ------------------------------------------------------------------

    def process_signal(
        self,
        *,
        ticker: str,
        signal: int,
        price: float,
        timestamp: datetime,
        order_type: OrderType = OrderType.MARKET,
        limit_price: float | None = None,
        stop_loss_price: float | None = None,
        is_emergency: bool = False,
        market_prices: dict[str, float] | None = None,
        client_order_id: str | None = None,
        latency_ms: float | None = None,
    ) -> ExecutionStepResult:
        """Gate a strategy signal through RiskManager and execute approved orders.

        Raises:
            InvalidOrderError: On malformed external inputs or invalid prices.
            BrokerConnectionError: When connectivity retries are exhausted.
            ExecutionHaltedError: Whenever Kill-Switch transitions to HALTED.
        """
        clean_ticker, valid_signal, valid_price = self._validate_step_inputs(
            ticker=ticker,
            signal=signal,
            price=price,
            timestamp=timestamp,
            order_type=order_type,
            limit_price=limit_price,
            is_emergency=is_emergency,
            latency_ms=latency_ms,
        )
        mtm_prices = self._validate_market_prices(market_prices)
        mtm_prices.setdefault(clean_ticker, valid_price)

        account, measured_latency = self._sync_for_step(
            mtm_prices=mtm_prices,
            latency_override=latency_ms,
        )
        pos = account.positions.get(clean_ticker)
        current_shares = pos.shares if pos is not None else 0
        entry_date = pos.entry_date if pos is not None else None
        if (
            pos is not None
            and pos.shares > 0
            and not self.risk_manager.stop_monitor.has_open_position
        ):
            self.risk_manager.stop_monitor.open_position(pos.avg_entry_price)

        verdict = self.risk_manager.evaluate_trade(
            signal=valid_signal,
            price=valid_price,
            current_equity=account.equity,
            current_date=timestamp.date(),
            latency_ms=measured_latency,
            available_cash=account.cash,
            stop_loss_price=stop_loss_price,
            current_shares=current_shares,
            entry_date=entry_date,
            is_emergency=is_emergency,
        )

        if verdict.kill_switch_state.status == RiskStatus.HALTED:
            self._handle_kill_switch_halt(
                ticker=clean_ticker,
                price=valid_price,
                timestamp=timestamp,
                account=account,
                verdict=verdict,
                mtm_prices=mtm_prices,
            )

        if not verdict.approved or verdict.action == "HOLD":
            return ExecutionStepResult(
                ticker=clean_ticker,
                signal=valid_signal,
                verdict=verdict,
                order_receipt=None,
                account=account,
                halted=False,
                cancelled_orders_count=0,
                latency_ms=measured_latency,
                timestamp=timestamp,
            )

        order = self._build_order_from_verdict(
            ticker=clean_ticker,
            verdict=verdict,
            price=valid_price,
            timestamp=timestamp,
            order_type=order_type,
            limit_price=limit_price,
            current_shares=current_shares,
            is_emergency=is_emergency,
            client_order_id=client_order_id,
        )
        receipt = self.submit_order_idempotent(order, market_prices=mtm_prices)
        updated_account = self._refresh_snapshot_after_order(mtm_prices)
        self._sync_stop_monitor_after_fill(
            ticker=clean_ticker,
            receipt=receipt,
            updated_account=updated_account,
        )

        return ExecutionStepResult(
            ticker=clean_ticker,
            signal=valid_signal,
            verdict=verdict,
            order_receipt=receipt,
            account=updated_account,
            halted=False,
            cancelled_orders_count=0,
            latency_ms=measured_latency,
            timestamp=timestamp,
        )

    # ------------------------------------------------------------------
    # Internal retry, risk-sync, and emergency halt helpers
    # ------------------------------------------------------------------

    def _sync_for_step(
        self,
        *,
        mtm_prices: dict[str, float],
        latency_override: float | None,
    ) -> tuple[AccountSnapshot, float]:
        if latency_override is None:
            return self.sync_account(market_prices=mtm_prices)

        def _fetch_account() -> AccountSnapshot:
            return self.broker.get_account_snapshot(market_prices=mtm_prices)

        account, _ = self._execute_with_backoff(_fetch_account)
        self._last_snapshot = account
        return account, float(latency_override)

    def _refresh_snapshot_after_order(
        self, mtm_prices: dict[str, float]
    ) -> AccountSnapshot:
        def _fetch() -> AccountSnapshot:
            return self.broker.get_account_snapshot(market_prices=mtm_prices)

        snapshot, _ = self._execute_with_backoff(_fetch)
        self._last_snapshot = snapshot
        return snapshot

    def _sync_stop_monitor_after_fill(
        self,
        *,
        ticker: str,
        receipt: OrderReceipt,
        updated_account: AccountSnapshot,
    ) -> None:
        if receipt.status != OrderStatus.FILLED:
            return
        if (
            receipt.side == OrderSide.BUY
            and receipt.fill_price is not None
            and not self.risk_manager.stop_monitor.has_open_position
        ):
            self.risk_manager.stop_monitor.open_position(receipt.fill_price)
        elif receipt.side == OrderSide.SELL and ticker not in updated_account.positions:
            self.risk_manager.stop_monitor.close_position()

    def _build_order_from_verdict(
        self,
        *,
        ticker: str,
        verdict: RiskVerdict,
        price: float,
        timestamp: datetime,
        order_type: OrderType,
        limit_price: float | None,
        current_shares: int,
        is_emergency: bool,
        client_order_id: str | None,
    ) -> OrderRequest:
        if verdict.action == "BUY":
            if verdict.shares < 1:
                raise InvalidOrderError(
                    f"Approved BUY verdict requires shares >= 1, got {verdict.shares}."
                )
            side = OrderSide.BUY
            qty = verdict.shares
            outgoing_type = order_type
            outgoing_limit = limit_price
            emergency = False
        elif verdict.action == "EXIT":
            if current_shares < 1:
                raise InvalidOrderError(
                    f"Cannot execute EXIT on {ticker}: current_shares is {current_shares}."
                )
            side = OrderSide.SELL
            qty = current_shares
            emergency = is_emergency or verdict.reason.startswith(
                "Emergency exit approved"
            )
            outgoing_type = OrderType.MARKET if emergency else order_type
            outgoing_limit = None if emergency else limit_price
        else:
            raise InvalidOrderError(
                f"Unsupported executable verdict action: {verdict.action!r}."
            )

        cid = (
            _require_non_empty_str(
                client_order_id, "client_order_id", InvalidOrderError
            )
            if client_order_id is not None
            else self.build_client_order_id(
                ticker=ticker,
                side=side,
                shares=qty,
                timestamp=timestamp,
                tag="EMG" if emergency else "",
            )
        )
        return OrderRequest(
            client_order_id=cid,
            ticker=ticker,
            side=side,
            shares=qty,
            reference_price=price,
            order_type=outgoing_type,
            limit_price=outgoing_limit,
            created_at=timestamp,
            is_emergency=emergency,
            reason=verdict.reason,
        )

    def _handle_kill_switch_halt(
        self,
        *,
        ticker: str,
        price: float,
        timestamp: datetime,
        account: AccountSnapshot,
        verdict: RiskVerdict,
        mtm_prices: dict[str, float],
    ) -> None:
        ks = verdict.kill_switch_state
        cancelled = self.cancel_all_open_orders_resilient(market_prices=mtm_prices)

        liquidated_tickers: list[str] = []
        if self.config.liquidate_on_halt:
            # Refresh after cancelling open SELL orders so locked custody shares free up.
            fresh_account = self._refresh_snapshot_after_order(mtm_prices)
            for pos_ticker, pos in fresh_account.positions.items():
                if pos.shares <= 0:
                    continue
                exit_price = (
                    price
                    if pos_ticker == ticker
                    else mtm_prices.get(pos_ticker, pos.market_price)
                )
                cid = self.build_client_order_id(
                    ticker=pos_ticker,
                    side=OrderSide.SELL,
                    shares=pos.shares,
                    timestamp=timestamp,
                    tag=f"HALT-{ks.reason.value}",
                )
                emg_order = OrderRequest(
                    client_order_id=cid,
                    ticker=pos_ticker,
                    side=OrderSide.SELL,
                    shares=pos.shares,
                    reference_price=exit_price,
                    order_type=OrderType.MARKET,
                    limit_price=None,
                    created_at=timestamp,
                    is_emergency=True,
                    reason=f"Kill-Switch {ks.reason.value}: {ks.message}",
                )
                self.submit_order_idempotent(emg_order, market_prices=mtm_prices)
                liquidated_tickers.append(pos_ticker)

            if liquidated_tickers:
                self._last_snapshot = self._refresh_snapshot_after_order(mtm_prices)
                self.risk_manager.stop_monitor.close_position()

        logger.error(
            "KILL_SWITCH_HALT event=halt ticker=%s reason=%s equity=%.4f "
            "daily_pnl_pct=%.4f drawdown_pct=%.4f latency_ms=%.2f "
            "cancelled_orders=%d liquidate_on_halt=%s liquidated=%s",
            ticker,
            ks.reason.value,
            account.equity,
            ks.daily_pnl_pct,
            ks.drawdown_pct,
            ks.last_latency_ms,
            len(cancelled),
            self.config.liquidate_on_halt,
            ",".join(liquidated_tickers) if liquidated_tickers else "none",
            extra={
                "execution_event": "KILL_SWITCH_HALT",
                "ticker": ticker,
                "halt_reason": ks.reason.value,
                "cancelled_orders_count": len(cancelled),
                "liquidated_tickers": liquidated_tickers,
            },
        )
        raise ExecutionHaltedError(
            f"Execution halted by Kill-Switch ({ks.reason.value}): {ks.message} "
            f"[cancelled={len(cancelled)}, liquidated={len(liquidated_tickers)}]"
        )

    def _execute_with_backoff(self, operation: Callable[[], _T]) -> tuple[_T, bool]:
        return self._execute_with_backoff_attempt(lambda _attempt: operation())

    def _execute_with_backoff_attempt(
        self, operation: Callable[[int], _T]
    ) -> tuple[_T, bool]:
        max_retries = self.config.max_retries
        last_exc: BrokerConnectionError | None = None

        for attempt in range(max_retries + 1):
            try:
                if not self.broker.is_connected():
                    self.broker.connect()
                result = operation(attempt)
                return result, attempt > 0
            except BrokerConnectionError as exc:
                last_exc = exc
                if attempt >= max_retries:
                    break
                delay = self.config.base_backoff_seconds * (
                    self.config.backoff_multiplier**attempt
                )
                logger.warning(
                    "Transient broker failure (attempt %d/%d): %s. Retrying in %.3fs.",
                    attempt + 1,
                    max_retries + 1,
                    exc,
                    delay,
                )
                self._sleep(delay)

        assert last_exc is not None
        raise last_exc

    @staticmethod
    def _validate_step_inputs(
        *,
        ticker: str,
        signal: int,
        price: float,
        timestamp: datetime,
        order_type: OrderType,
        limit_price: float | None,
        is_emergency: bool,
        latency_ms: float | None,
    ) -> tuple[str, int, float]:
        clean_ticker = _require_non_empty_str(ticker, "ticker", InvalidOrderError)
        if (
            isinstance(signal, bool)
            or not isinstance(signal, int)
            or signal not in (0, 1)
        ):
            raise InvalidOrderError(f"signal must be binary 0 or 1, got {signal!r}.")
        valid_price = _require_finite_number(price, "price", InvalidOrderError)
        if valid_price <= 0.0:
            raise InvalidOrderError(
                f"price must be strictly positive, got {valid_price}."
            )
        if not isinstance(timestamp, datetime):
            raise InvalidOrderError("timestamp must be a datetime instance.")
        if not isinstance(order_type, OrderType):
            raise InvalidOrderError("order_type must be a valid OrderType enum member.")
        if order_type == OrderType.LIMIT:
            if limit_price is None:
                raise InvalidOrderError("limit_price is required for LIMIT orders.")
            lim = _require_finite_number(limit_price, "limit_price", InvalidOrderError)
            if lim <= 0.0:
                raise InvalidOrderError(
                    f"limit_price must be strictly positive, got {lim}."
                )
        elif limit_price is not None:
            raise InvalidOrderError("limit_price must be None for MARKET orders.")

        _require_bool(is_emergency, "is_emergency", InvalidOrderError)
        if latency_ms is not None:
            lat = _require_finite_number(latency_ms, "latency_ms", InvalidOrderError)
            if lat < 0.0:
                raise InvalidOrderError(f"latency_ms cannot be negative, got {lat}.")
        return clean_ticker, signal, valid_price

    @staticmethod
    def _validate_market_prices(
        market_prices: dict[str, float] | None,
    ) -> dict[str, float]:
        if market_prices is None:
            return {}
        if not isinstance(market_prices, dict):
            raise InvalidOrderError(
                "market_prices must be a dict mapping ticker to price."
            )
        cleaned: dict[str, float] = {}
        for raw_ticker, raw_price in market_prices.items():
            clean_t = _require_non_empty_str(raw_ticker, "ticker", InvalidOrderError)
            px = _require_finite_number(
                raw_price, f"price[{clean_t}]", InvalidOrderError
            )
            if px <= 0.0:
                raise InvalidOrderError(
                    f"market_prices[{clean_t!r}] must be strictly positive, got {px}."
                )
            cleaned[clean_t] = px
        return cleaned

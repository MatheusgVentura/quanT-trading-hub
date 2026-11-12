"""Authenticated REST sandbox broker adapter using Python stdlib HTTP and HMAC-SHA256."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from src.execution.exceptions import (
    BrokerConnectionError,
    ExecutionConfigurationError,
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
    PositionSnapshot,
    _require_finite_number,
    _require_int,
    _require_non_empty_str,
    format_b3_execution_symbol,
)

logger = logging.getLogger(__name__)

_DEFAULT_SANDBOX_BASE_URL = "https://paper-api.alpaca.markets"
_DEFAULT_SANDBOX_HOSTS = frozenset(
    {
        "paper-api.alpaca.markets",
        "testnet.binance.vision",
        "demo-api.binance.com",
        "localhost",
        "127.0.0.1",
        "::1",
    }
)
_LIVE_PRODUCTION_HOSTS = frozenset(
    {
        "api.alpaca.markets",
        "broker-api.alpaca.markets",
        "data.alpaca.markets",
        "stream.data.alpaca.markets",
        "api.binance.com",
        "api.binance.us",
        "fapi.binance.com",
        "dapi.binance.com",
    }
)
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

_STATUS_MAP: dict[str, OrderStatus] = {
    "PENDING": OrderStatus.PENDING,
    "PENDING_NEW": OrderStatus.PENDING,
    "NEW": OrderStatus.SUBMITTED,
    "ACCEPTED": OrderStatus.SUBMITTED,
    "SUBMITTED": OrderStatus.SUBMITTED,
    "PARTIALLY_FILLED": OrderStatus.SUBMITTED,
    "FILLED": OrderStatus.FILLED,
    "CANCELED": OrderStatus.CANCELLED,
    "CANCELLED": OrderStatus.CANCELLED,
    "EXPIRED": OrderStatus.CANCELLED,
    "REPLACED": OrderStatus.CANCELLED,
    "REJECTED": OrderStatus.REJECTED,
    "SUSPENDED": OrderStatus.REJECTED,
}

TransportCallable = Callable[[urllib.request.Request, float], Any]


def _utc_now() -> datetime:
    """Return current UTC-aware datetime compatible with Python 3.10."""
    return datetime.now(timezone.utc)  # noqa: UP017


def _validate_sandbox_base_url(
    base_url: object,
    allowed_hosts: Iterable[str] | None = None,
) -> str:
    """Ensure base_url uses TLS (or local loopback HTTP) and targets an approved sandbox host."""
    raw = _require_non_empty_str(base_url, "base_url", ExecutionConfigurationError)
    parsed = urllib.parse.urlparse(raw)
    if parsed.username is not None or parsed.password is not None:
        raise ExecutionConfigurationError(
            "base_url must not contain embedded credentials."
        )
    if not parsed.scheme or not parsed.hostname:
        raise ExecutionConfigurationError(
            f"base_url must be an absolute URL with scheme and host, got {raw!r}."
        )

    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower()
    if host in _LIVE_PRODUCTION_HOSTS:
        raise ExecutionConfigurationError(
            f"Refusing live production host {host!r} in RestSandboxBroker."
        )

    if scheme == "http":
        if host not in _LOOPBACK_HOSTS:
            raise ExecutionConfigurationError(
                f"Non-HTTPS scheme 'http' is permitted only for loopback hosts, got {host!r}."
            )
    elif scheme != "https":
        raise ExecutionConfigurationError(
            f"Unsupported URL scheme {scheme!r}; expected 'https'."
        )

    allowlist = set(_DEFAULT_SANDBOX_HOSTS)
    if allowed_hosts is not None:
        for extra in allowed_hosts:
            clean_host = _require_non_empty_str(
                extra, "allowed_sandbox_hosts item", ExecutionConfigurationError
            ).lower()
            if clean_host in _LIVE_PRODUCTION_HOSTS:
                raise ExecutionConfigurationError(
                    f"Cannot allowlist live production host {clean_host!r}."
                )
            allowlist.add(clean_host)

    if host not in allowlist:
        raise ExecutionConfigurationError(
            f"Host {host!r} is not in the permitted sandbox host allowlist."
        )

    return raw.rstrip("/")


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse key=value pairs from a local .env file without mutating os.environ."""
    if not path.exists() or not path.is_file():
        raise ExecutionConfigurationError(
            f"Configured env_file does not exist or is not a file: {path}."
        )
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ExecutionConfigurationError(
            f"Failed to read env_file {path}: {exc}"
        ) from exc

    parsed: dict[str, str] = {}
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].strip()
        if "=" not in stripped:
            continue
        key, val = stripped.split("=", 1)
        clean_key = key.strip()
        clean_val = val.strip()
        if (
            len(clean_val) >= 2
            and clean_val[0] == clean_val[-1]
            and clean_val[0] in ("'", '"')
        ):
            clean_val = clean_val[1:-1]
        if clean_key:
            parsed[clean_key] = clean_val
    return parsed


def _load_credentials(
    *,
    api_key_env: str,
    api_secret_env: str,
    env_file: Path | None,
) -> tuple[str, str]:
    """Read sandbox API key and secret solely from environment variables / .env."""
    key_var = _require_non_empty_str(
        api_key_env, "api_key_env", ExecutionConfigurationError
    )
    secret_var = _require_non_empty_str(
        api_secret_env, "api_secret_env", ExecutionConfigurationError
    )

    file_vars = _parse_env_file(env_file) if env_file is not None else {}
    api_key = os.environ.get(key_var) or file_vars.get(key_var, "")
    api_secret = os.environ.get(secret_var) or file_vars.get(secret_var, "")

    if not api_key.strip():
        raise ExecutionConfigurationError(
            f"Missing sandbox API key in environment variable {key_var!r}."
        )
    if not api_secret.strip():
        raise ExecutionConfigurationError(
            f"Missing sandbox API secret in environment variable {secret_var!r}."
        )
    return api_key.strip(), api_secret.strip()


def _parse_iso_datetime(
    raw: object, field_name: str, *, default: datetime | None = None
) -> datetime:
    """Parse an ISO-8601 datetime string from broker JSON (normalizing trailing Z)."""
    if raw is None:
        if default is not None:
            return default
        raise InvalidOrderError(f"Missing required datetime field {field_name!r}.")
    if not isinstance(raw, str) or not raw.strip():
        raise InvalidOrderError(
            f"{field_name} must be a non-empty ISO datetime string."
        )
    normalized = raw.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise InvalidOrderError(
            f"Malformed ISO datetime in {field_name!r}: {raw!r}."
        ) from exc


def _parse_order_side(raw: object) -> OrderSide:
    """Parse broker order side string into OrderSide enum."""
    val = _require_non_empty_str(raw, "side", InvalidOrderError).upper()
    try:
        return OrderSide(val)
    except ValueError as exc:
        raise InvalidOrderError(f"Unsupported broker order side: {raw!r}.") from exc


def _parse_order_status(raw: object) -> OrderStatus:
    """Map REST sandbox order status strings onto OrderStatus enum."""
    val = _require_non_empty_str(raw, "status", InvalidOrderError).upper()
    status = _STATUS_MAP.get(val)
    if status is None:
        raise InvalidOrderError(f"Unsupported broker order status: {raw!r}.")
    return status


def _parse_int_like(value: object, field_name: str, *, min_val: int) -> int:
    """Parse non-bool integer or integer-formatted string from REST JSON."""
    if isinstance(value, bool):
        raise InvalidOrderError(f"{field_name} cannot be boolean.")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            numeric = float(value.strip())
        except ValueError as exc:
            raise InvalidOrderError(
                f"{field_name} must be an integer value, got {value!r}."
            ) from exc
        if not math.isfinite(numeric) or not numeric.is_integer():
            raise InvalidOrderError(
                f"{field_name} must represent an integer quantity, got {value!r}."
            )
        parsed = int(numeric)
    else:
        raise InvalidOrderError(
            f"{field_name} must be an integer or numeric string, got {value!r}."
        )
    return _require_int(parsed, field_name, min_val=min_val, exc_cls=InvalidOrderError)


def _parse_float_like(value: object, field_name: str) -> float:
    """Parse non-bool finite float or numeric string from REST JSON."""
    if isinstance(value, bool):
        raise InvalidOrderError(f"{field_name} cannot be boolean.")
    if isinstance(value, (int, float)):
        return _require_finite_number(value, field_name, InvalidOrderError)
    if isinstance(value, str) and value.strip():
        try:
            parsed = float(value.strip())
        except ValueError as exc:
            raise InvalidOrderError(
                f"{field_name} must be numeric, got {value!r}."
            ) from exc
        return _require_finite_number(parsed, field_name, InvalidOrderError)
    raise InvalidOrderError(f"{field_name} must be a numeric value, got {value!r}.")


def _receipt_from_payload(
    payload: object,
    *,
    fallback_ticker: str | None = None,
    fallback_exec_symbol: str | None = None,
    fallback_time: datetime,
    force_status: OrderStatus | None = None,
) -> OrderReceipt:
    """Translate and fail-closed-validate a broker JSON order object into OrderReceipt."""
    if not isinstance(payload, dict):
        raise InvalidOrderError("Broker order response must be a JSON object.")

    broker_order_id = _require_non_empty_str(
        payload.get("id", payload.get("broker_order_id")),
        "id",
        InvalidOrderError,
    )
    client_order_id = _require_non_empty_str(
        payload.get("client_order_id"),
        "client_order_id",
        InvalidOrderError,
    )
    exec_symbol = _require_non_empty_str(
        payload.get("symbol", payload.get("execution_symbol", fallback_exec_symbol)),
        "symbol",
        InvalidOrderError,
    )
    ticker = _require_non_empty_str(
        payload.get("ticker", fallback_ticker or exec_symbol),
        "ticker",
        InvalidOrderError,
    )
    side = _parse_order_side(payload.get("side"))
    requested_shares = _parse_int_like(
        payload.get("qty", payload.get("requested_shares")),
        "qty",
        min_val=1,
    )
    filled_shares = _parse_int_like(
        payload.get("filled_qty", payload.get("filled_shares", 0)),
        "filled_qty",
        min_val=0,
    )

    raw_fill_px = payload.get("filled_avg_price", payload.get("fill_price"))
    fill_price = (
        _parse_float_like(raw_fill_px, "filled_avg_price")
        if raw_fill_px is not None
        else None
    )

    raw_fee = payload.get("fee", payload.get("b3_fee_paid", 0.0))
    fee = _parse_float_like(raw_fee, "fee") if raw_fee is not None else 0.0

    status = force_status or _parse_order_status(payload.get("status"))
    submitted_at = _parse_iso_datetime(
        payload.get("submitted_at", payload.get("created_at")),
        "submitted_at",
        default=fallback_time,
    )
    raw_filled_at = payload.get("filled_at")
    filled_at = (
        _parse_iso_datetime(raw_filled_at, "filled_at")
        if raw_filled_at is not None
        else None
    )
    raw_msg = payload.get("message", f"Sandbox order {status.value}")
    message = str(raw_msg) if raw_msg is not None else ""

    return OrderReceipt(
        broker_order_id=broker_order_id,
        client_order_id=client_order_id,
        ticker=ticker,
        execution_symbol=exec_symbol,
        side=side,
        requested_shares=requested_shares,
        filled_shares=filled_shares,
        fill_price=fill_price,
        b3_fee_paid=fee,
        status=status,
        submitted_at=submitted_at,
        filled_at=filled_at,
        message=message,
    )


class RestSandboxBroker(IBrokerAdapter):
    """Stdlib-only HMAC-SHA256 REST client for external sandbox brokers.

    Reads credentials strictly from environment variables (or an explicit `.env`
    file), enforces a strict sandbox host allowlist, signs requests with
    HMAC-SHA256, applies configured request timeouts, and maps HTTP/network
    failures into typed execution exceptions without logging secrets.
    """

    def __init__(
        self,
        config: ExecutionConfig | None = None,
        *,
        base_url: str = _DEFAULT_SANDBOX_BASE_URL,
        api_key_env: str = "ALPACA_API_KEY",
        api_secret_env: str = "ALPACA_SECRET_KEY",
        env_file: Path | str | None = None,
        allowed_sandbox_hosts: Iterable[str] | None = None,
        transport: TransportCallable | None = None,
        clock: Callable[[], datetime] | None = None,
        perf_counter: Callable[[], float] | None = None,
    ) -> None:
        """Initialize RestSandboxBroker validating config, sandbox URL, and env credentials."""
        if config is not None and not isinstance(config, ExecutionConfig):
            raise ExecutionConfigurationError(
                "config must be an ExecutionConfig instance or None."
            )
        self.config = config or ExecutionConfig()

        if clock is not None and not callable(clock):
            raise ExecutionConfigurationError("clock must be callable or None.")
        self._clock: Callable[[], datetime] = clock or _utc_now

        if perf_counter is not None and not callable(perf_counter):
            raise ExecutionConfigurationError("perf_counter must be callable or None.")
        self._perf_counter: Callable[[], float] = perf_counter or time.perf_counter

        if transport is not None and not callable(transport):
            raise ExecutionConfigurationError("transport must be callable or None.")
        self._transport = transport

        self.base_url = _validate_sandbox_base_url(
            base_url, allowed_hosts=allowed_sandbox_hosts
        )

        resolved_env_file: Path | None = None
        if env_file is not None:
            if isinstance(env_file, str):
                cleaned = _require_non_empty_str(
                    env_file, "env_file", ExecutionConfigurationError
                )
                resolved_env_file = Path(cleaned)
            elif isinstance(env_file, Path):
                resolved_env_file = env_file
            else:
                raise ExecutionConfigurationError(
                    "env_file must be a Path, string, or None."
                )

        self._api_key, self._api_secret = _load_credentials(
            api_key_env=api_key_env,
            api_secret_env=api_secret_env,
            env_file=resolved_env_file,
        )
        self._connected = False
        self._last_latency_ms: float | None = None

    def __repr__(self) -> str:
        """Return safe representation excluding API credentials."""
        return (
            f"RestSandboxBroker(base_url={self.base_url!r}, "
            f"connected={self._connected})"
        )

    # ------------------------------------------------------------------
    # IBrokerAdapter implementation
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Verify sandbox reachability and credentials via account handshake."""
        _, elapsed_ms = self._request_json("GET", "/v2/account")
        self._last_latency_ms = elapsed_ms
        self._connected = True

    def disconnect(self) -> None:
        """Close logical sandbox session cleanly."""
        self._connected = False

    def is_connected(self) -> bool:
        """Return whether the sandbox adapter currently holds an active session."""
        return self._connected

    def ping(self) -> float:
        """Measure sandbox REST round-trip latency in milliseconds."""
        self._ensure_connected()
        _, elapsed_ms = self._request_json("GET", "/v2/account")
        self._last_latency_ms = elapsed_ms
        return elapsed_ms

    def submit_order(self, order: OrderRequest) -> OrderReceipt:
        """Sign and submit an order request to the REST sandbox endpoint."""
        if not isinstance(order, OrderRequest):
            raise InvalidOrderError("order must be an OrderRequest instance.")
        self._ensure_connected()

        exec_symbol = format_b3_execution_symbol(
            order.ticker,
            order.shares,
            use_fractional_suffix=self.config.use_fractional_suffix,
        )
        body: dict[str, Any] = {
            "client_order_id": order.client_order_id,
            "symbol": exec_symbol,
            "ticker": order.ticker,
            "qty": str(order.shares),
            "side": order.side.value.lower(),
            "type": order.order_type.value.lower(),
            "time_in_force": "day",
        }
        if order.limit_price is not None:
            body["limit_price"] = f"{order.limit_price:.6f}"

        payload, _ = self._request_json("POST", "/v2/orders", body=body)
        return _receipt_from_payload(
            payload,
            fallback_ticker=order.ticker,
            fallback_exec_symbol=exec_symbol,
            fallback_time=self._now(),
        )

    def get_order_by_client_id(self, client_order_id: str) -> OrderReceipt | None:
        """Query an existing order by client_order_id, returning None on HTTP 404."""
        self._ensure_connected()
        clean_id = _require_non_empty_str(
            client_order_id, "client_order_id", InvalidOrderError
        )
        encoded = urllib.parse.quote(clean_id, safe="")
        path = f"/v2/orders:by_client_order_id?client_order_id={encoded}"
        payload, _ = self._request_json("GET", path, allow_not_found=True)
        if payload is None:
            return None
        return _receipt_from_payload(payload, fallback_time=self._now())

    def cancel_all_open_orders(self) -> list[OrderReceipt]:
        """Request cancellation of all open orders on the sandbox account."""
        self._ensure_connected()
        payload, _ = self._request_json("DELETE", "/v2/orders")
        if isinstance(payload, list):
            items: object = payload
        elif isinstance(payload, dict) and isinstance(
            payload.get("orders", payload.get("cancelled")), list
        ):
            items = payload.get("orders", payload.get("cancelled"))
        else:
            raise InvalidOrderError(
                "Sandbox cancel-all response must be a JSON array or orders wrapper."
            )
        assert isinstance(items, list)
        now = self._now()
        receipts: list[OrderReceipt] = []
        for entry in items:
            raw_order = (
                entry.get("body", entry)
                if isinstance(entry, dict)
                and "body" in entry
                and isinstance(entry.get("body"), dict)
                else entry
            )
            receipts.append(
                _receipt_from_payload(
                    raw_order,
                    fallback_time=now,
                    force_status=OrderStatus.CANCELLED,
                )
            )
        return receipts

    def get_account_snapshot(
        self, market_prices: dict[str, float] | None = None
    ) -> AccountSnapshot:
        """Fetch and validate sandbox cash, equity, positions, and open orders."""
        self._ensure_connected()
        validated_prices = self._validate_market_prices(market_prices)

        acct_payload, _ = self._request_json("GET", "/v2/account")
        if not isinstance(acct_payload, dict):
            raise InvalidOrderError("Sandbox account response must be a JSON object.")

        cash = _parse_float_like(acct_payload.get("cash"), "cash")
        reported_equity = _parse_float_like(acct_payload.get("equity"), "equity")
        realized_pnl = (
            _parse_float_like(acct_payload["realized_pnl"], "realized_pnl")
            if acct_payload.get("realized_pnl") is not None
            else 0.0
        )
        total_fees = (
            _parse_float_like(acct_payload["total_fees_paid"], "total_fees_paid")
            if acct_payload.get("total_fees_paid") is not None
            else 0.0
        )

        pos_payload, _ = self._request_json("GET", "/v2/positions")
        if not isinstance(pos_payload, list):
            raise InvalidOrderError("Sandbox positions response must be a JSON array.")

        now = self._now()
        positions: dict[str, PositionSnapshot] = {}
        mtm_positions_value = 0.0
        for raw_pos in pos_payload:
            snap = self._position_from_payload(
                raw_pos, market_prices=validated_prices, fallback_date=now.date()
            )
            positions[snap.ticker] = snap
            mtm_positions_value += snap.shares * snap.market_price

        open_payload, _ = self._request_json("GET", "/v2/orders?status=open")
        if not isinstance(open_payload, list):
            raise InvalidOrderError(
                "Sandbox open orders response must be a JSON array."
            )
        open_orders = [
            _receipt_from_payload(item, fallback_time=now) for item in open_payload
        ]

        equity = cash + mtm_positions_value if validated_prices else reported_equity
        return AccountSnapshot(
            cash=cash,
            equity=equity,
            realized_pnl=realized_pnl,
            total_fees_paid=total_fees,
            positions=positions,
            open_orders=open_orders,
            timestamp=now,
        )

    # ------------------------------------------------------------------
    # HMAC-SHA256 signing and stdlib urllib HTTP transport
    # ------------------------------------------------------------------

    def compute_hmac_signature(
        self,
        *,
        method: str,
        path: str,
        body: str,
        timestamp: str,
    ) -> str:
        """Compute deterministic HMAC-SHA256 hex digest using the env secret key."""
        prehash = f"{timestamp}\n{method.upper()}\n{path}\n{body}"
        return hmac.new(
            self._api_secret.encode("utf-8"),
            prehash.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _build_signed_headers(
        self, *, method: str, path: str, body: str
    ) -> dict[str, str]:
        now = self._now()
        timestamp_ms = str(int(now.timestamp() * 1000))
        signature = self.compute_hmac_signature(
            method=method,
            path=path,
            body=body,
            timestamp=timestamp_ms,
        )
        return {
            "APCA-API-KEY-ID": self._api_key,
            "X-Sandbox-Timestamp": timestamp_ms,
            "X-Sandbox-Signature": signature,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        allow_not_found: bool = False,
    ) -> tuple[Any, float]:
        url = f"{self.base_url}{path}"
        body_str = (
            json.dumps(body, separators=(",", ":"), sort_keys=True)
            if body is not None
            else ""
        )
        data_bytes = body_str.encode("utf-8") if body is not None else None
        headers = self._build_signed_headers(method=method, path=path, body=body_str)

        request = urllib.request.Request(
            url=url,
            data=data_bytes,
            headers=headers,
            method=method.upper(),
        )
        timeout = self.config.request_timeout_seconds
        start = self._perf_counter()

        try:
            raw_code, raw_text = self._dispatch_request(request, timeout)
        except urllib.error.HTTPError as exc:
            if allow_not_found and exc.code == 404:
                elapsed_ms = max(0.0, (self._perf_counter() - start) * 1000.0)
                return None, elapsed_ms
            raise self._translate_http_error(method, path, exc) from exc
        except TimeoutError as exc:
            raise BrokerConnectionError(
                f"Sandbox request {method} {path} timed out after {timeout}s."
            ) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise BrokerConnectionError(
                    f"Sandbox request {method} {path} timed out after {timeout}s."
                ) from exc
            raise BrokerConnectionError(
                f"Sandbox connection error on {method} {path}: {exc.reason}"
            ) from exc
        except OSError as exc:
            raise BrokerConnectionError(
                f"Sandbox transport failure on {method} {path}: {exc}"
            ) from exc

        elapsed_ms = max(0.0, (self._perf_counter() - start) * 1000.0)
        logger.debug(
            "Sandbox %s %s -> HTTP %d (%.2f ms)", method, path, raw_code, elapsed_ms
        )

        if raw_code == 404 and allow_not_found:
            return None, elapsed_ms
        if raw_code in (408, 429) or 500 <= raw_code < 600:
            raise BrokerConnectionError(
                f"Sandbox API transient failure on {method} {path} (HTTP {raw_code})."
            )
        if 400 <= raw_code < 500:
            raise OrderRejectedError(
                f"Sandbox API rejected {method} {path} (HTTP {raw_code}): "
                f"{self._extract_error_message(raw_text)}"
            )

        if not raw_text.strip():
            raise InvalidOrderError(
                f"Empty JSON response returned by sandbox on {method} {path}."
            )
        try:
            return json.loads(raw_text), elapsed_ms
        except json.JSONDecodeError as exc:
            raise InvalidOrderError(
                f"Malformed JSON payload returned by sandbox on {method} {path}: {exc}"
            ) from exc

    def _dispatch_request(
        self, request: urllib.request.Request, timeout: float
    ) -> tuple[int, str]:
        if self._transport is not None:
            response = self._transport(request, timeout)
            return self._normalize_response(response)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return self._normalize_response(response)

    @staticmethod
    def _normalize_response(response: Any) -> tuple[int, str]:
        if isinstance(response, tuple) and len(response) == 2:
            code, raw_body = response
            if isinstance(code, bool) or not isinstance(code, int):
                raise InvalidOrderError("HTTP status code must be an integer.")
            if isinstance(raw_body, bytes):
                return code, raw_body.decode("utf-8", errors="replace")
            if isinstance(raw_body, str):
                return code, raw_body
            raise InvalidOrderError("Response body must be str or bytes.")

        status_attr = getattr(response, "status", None)
        if status_attr is None and callable(getattr(response, "getcode", None)):
            status_attr = response.getcode()
        if isinstance(status_attr, bool) or not isinstance(status_attr, int):
            raise InvalidOrderError("Broker HTTP response missing integer status code.")

        read_fn = getattr(response, "read", None)
        if not callable(read_fn):
            raise InvalidOrderError("Broker HTTP response missing callable read().")
        raw_bytes = read_fn()
        text = (
            raw_bytes.decode("utf-8", errors="replace")
            if isinstance(raw_bytes, bytes)
            else str(raw_bytes)
        )
        return status_attr, text

    def _translate_http_error(
        self, method: str, path: str, exc: urllib.error.HTTPError
    ) -> BrokerConnectionError | OrderRejectedError:
        body_text = ""
        try:
            raw = exc.read()
            body_text = raw.decode("utf-8", errors="replace") if raw else ""
        except (OSError, UnicodeDecodeError):
            body_text = ""

        detail = self._extract_error_message(body_text) or str(exc.reason)
        if exc.code in (408, 429) or 500 <= exc.code < 600:
            return BrokerConnectionError(
                f"Sandbox API unavailable on {method} {path} (HTTP {exc.code}): {detail}"
            )
        return OrderRejectedError(
            f"Sandbox API rejected {method} {path} (HTTP {exc.code}): {detail}"
        )

    @staticmethod
    def _extract_error_message(raw_text: str) -> str:
        if not raw_text.strip():
            return "empty error response"
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            return raw_text.strip()[:200]
        if isinstance(parsed, dict) and "message" in parsed:
            return str(parsed["message"])[:200]
        return raw_text.strip()[:200]

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise BrokerConnectionError(
                "RestSandboxBroker is not connected. Call connect() first."
            )

    def _now(self) -> datetime:
        ts = self._clock()
        if not isinstance(ts, datetime):
            raise InvalidOrderError("clock must return a datetime instance.")
        return ts

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

    @staticmethod
    def _position_from_payload(
        raw_pos: object,
        *,
        market_prices: dict[str, float],
        fallback_date: date,
    ) -> PositionSnapshot:
        if not isinstance(raw_pos, dict):
            raise InvalidOrderError(
                "Each sandbox position entry must be a JSON object."
            )
        ticker = _require_non_empty_str(
            raw_pos.get("ticker", raw_pos.get("symbol")),
            "ticker",
            InvalidOrderError,
        )
        shares = _parse_int_like(
            raw_pos.get("qty", raw_pos.get("shares")), "qty", min_val=0
        )
        avg_entry = _parse_float_like(raw_pos.get("avg_entry_price"), "avg_entry_price")
        raw_entry_date = raw_pos.get("entry_date")
        if raw_entry_date is not None:
            raw_date_str = _require_non_empty_str(
                raw_entry_date, "entry_date", InvalidOrderError
            )
            try:
                entry_dt = date.fromisoformat(raw_date_str)
            except ValueError as exc:
                raise InvalidOrderError(
                    f"Malformed entry_date {raw_entry_date!r} in sandbox position."
                ) from exc
        else:
            entry_dt = fallback_date
        raw_mkt = raw_pos.get("current_price", raw_pos.get("market_price"))
        mkt_price = (
            market_prices[ticker]
            if ticker in market_prices
            else _parse_float_like(raw_mkt, "current_price")
        )
        raw_unrl = raw_pos.get("unrealized_pl", raw_pos.get("unrealized_pnl"))
        unrealized_pnl = (
            (mkt_price - avg_entry) * shares
            if ticker in market_prices or raw_unrl is None
            else _parse_float_like(raw_unrl, "unrealized_pl")
        )
        return PositionSnapshot(
            ticker=ticker,
            shares=shares,
            avg_entry_price=avg_entry,
            entry_date=entry_dt,
            market_price=mkt_price,
            unrealized_pnl=unrealized_pnl,
        )

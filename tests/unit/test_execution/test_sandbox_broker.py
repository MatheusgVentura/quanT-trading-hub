"""Mocked unit tests for RestSandboxBroker mapped to AC08 and AC09."""

from __future__ import annotations

import hashlib
import hmac
import io
import itertools
import json
import logging
import math
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

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
    RestSandboxBroker,
)


def _set_sandbox_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    key: str = "sandbox-key-id-123",
    secret: str = "super-secret-hmac-value",
) -> None:
    monkeypatch.setenv("ALPACA_API_KEY", key)
    monkeypatch.setenv("ALPACA_SECRET_KEY", secret)


class _FakeHTTPResponse:
    """Minimal context-manager HTTP response mimicking urllib.request.urlopen output."""

    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self._raw = body.encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self) -> _FakeHTTPResponse:  # noqa: PYI034
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _http_error(url: str, code: int, body: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url=url,
        code=code,
        msg=f"HTTP {code}",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(body.encode("utf-8")),
    )


def _make_market_buy(cid: str = "cid-sb-1") -> OrderRequest:
    return OrderRequest(
        client_order_id=cid,
        ticker="ITUB4.SA",
        side=OrderSide.BUY,
        shares=2,
        reference_price=30.0,
        order_type=OrderType.MARKET,
    )


# ---------------------------------------------------------------------------
# AC08: Env-only credential hygiene, __repr__ safety, fail-closed validation
# ---------------------------------------------------------------------------


def test_ac08_missing_env_credentials_raise_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC08: Missing or whitespace env credentials fail closed immediately."""
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)

    with pytest.raises(ExecutionConfigurationError, match="ALPACA_API_KEY"):
        RestSandboxBroker()

    monkeypatch.setenv("ALPACA_API_KEY", "valid-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "   ")
    with pytest.raises(ExecutionConfigurationError, match="ALPACA_SECRET_KEY"):
        RestSandboxBroker()


def test_ac08_reads_dotenv_file_preserves_env_precedence_and_masks_repr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC08: Credentials load from explicit .env without leaking into repr or logs."""
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)

    env_path = tmp_path / ".env"
    env_path.write_text(
        "# comment line\n"
        'export ALPACA_API_KEY="file-key-999"\n'
        "ALPACA_SECRET_KEY='file-secret-abc'\n",
        encoding="utf-8",
    )

    broker_from_file = RestSandboxBroker(env_file=env_path)
    rendered = repr(broker_from_file)
    assert "file-key-999" not in rendered
    assert "file-secret-abc" not in rendered
    assert "https://paper-api.alpaca.markets" in rendered

    # Process environment variable takes precedence over file value.
    monkeypatch.setenv("ALPACA_API_KEY", "override-env-key")
    broker_override = RestSandboxBroker(
        env_file=str(env_path),
        transport=lambda req, timeout: (
            200,
            json.dumps({"cash": "100", "equity": "100"}),
        ),
    )
    seen_headers: list[dict[str, str]] = []

    def _capture_transport(
        req: urllib.request.Request, timeout: float
    ) -> tuple[int, str]:
        seen_headers.append(dict(req.header_items()))
        return 200, json.dumps({"cash": "100", "equity": "100"})

    broker_override._transport = _capture_transport
    broker_override.connect()
    assert seen_headers[0]["Apca-api-key-id"] == "override-env-key"


def test_ac08_invalid_init_params_and_missing_env_file_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC08: Non-callable hooks, missing env_file, or bad config raise ExecutionConfigurationError."""
    _set_sandbox_env(monkeypatch)

    with pytest.raises(ExecutionConfigurationError):
        RestSandboxBroker(config="bad")  # type: ignore[arg-type]
    with pytest.raises(ExecutionConfigurationError):
        RestSandboxBroker(clock="bad")  # type: ignore[arg-type]
    with pytest.raises(ExecutionConfigurationError):
        RestSandboxBroker(perf_counter="bad")  # type: ignore[arg-type]
    with pytest.raises(ExecutionConfigurationError):
        RestSandboxBroker(transport="bad")  # type: ignore[arg-type]
    with pytest.raises(ExecutionConfigurationError):
        RestSandboxBroker(env_file=tmp_path / "does_not_exist.env")
    with pytest.raises(ExecutionConfigurationError):
        RestSandboxBroker(env_file=123)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "bad_body",
    [
        "",
        "{corrupt-json",
        json.dumps([1, 2, 3]),
        json.dumps({"id": "ord-1", "client_order_id": "cid-1"}),
        json.dumps(
            {
                "id": "ord-1",
                "client_order_id": "cid-1",
                "symbol": "ITUB4F",
                "side": "BUY",
                "qty": -2,
                "status": "filled",
            }
        ),
        json.dumps(
            {
                "id": "ord-1",
                "client_order_id": "cid-1",
                "symbol": "ITUB4F",
                "side": "SHORT",
                "qty": "2",
                "status": "filled",
            }
        ),
        json.dumps(
            {
                "id": "ord-1",
                "client_order_id": "cid-1",
                "symbol": "ITUB4F",
                "side": "buy",
                "qty": "2",
                "filled_qty": "2",
                "filled_avg_price": "nan",
                "status": "filled",
            }
        ),
    ],
)
def test_ac08_corrupted_order_responses_fail_closed(
    monkeypatch: pytest.MonkeyPatch, bad_body: str
) -> None:
    """AC08: Malformed JSON or invalid order fields from sandbox raise InvalidOrderError."""
    _set_sandbox_env(monkeypatch)

    def _transport(req: urllib.request.Request, timeout: float) -> tuple[int, str]:
        if req.full_url.endswith("/v2/account"):
            return 200, json.dumps({"cash": "100.0", "equity": "100.0"})
        return 200, bad_body

    broker = RestSandboxBroker(transport=_transport)
    broker.connect()
    with pytest.raises(InvalidOrderError):
        broker.submit_order(_make_market_buy())


def test_ac08_corrupted_snapshot_and_bad_client_inputs_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC08: Negative cash, malformed entry_date, or bad client inputs raise InvalidOrderError."""
    _set_sandbox_env(monkeypatch)

    responses: dict[str, tuple[int, str]] = {
        "/v2/account": (200, json.dumps({"cash": "-10.0", "equity": "100.0"})),
        "/v2/positions": (200, json.dumps([])),
        "/v2/orders?status=open": (200, json.dumps([])),
    }

    def _transport(req: urllib.request.Request, timeout: float) -> tuple[int, str]:
        suffix = req.full_url.replace("https://paper-api.alpaca.markets", "")
        return responses[suffix]

    broker = RestSandboxBroker(transport=_transport)
    broker.connect()

    with pytest.raises(InvalidOrderError):
        broker.submit_order("not-an-order")  # type: ignore[arg-type]
    with pytest.raises(InvalidOrderError):
        broker.get_order_by_client_id("  ")
    with pytest.raises(InvalidOrderError):
        broker.get_account_snapshot({"ITUB4.SA": math.nan})

    # Negative cash in /v2/account fails AccountSnapshot validation.
    with pytest.raises(InvalidOrderError):
        broker.get_account_snapshot()

    # Valid account, corrupted entry_date in positions fails cleanly.
    responses["/v2/account"] = (200, json.dumps({"cash": "40.0", "equity": "100.0"}))
    responses["/v2/positions"] = (
        200,
        json.dumps(
            [
                {
                    "symbol": "ITUB4.SA",
                    "qty": "2",
                    "avg_entry_price": "30.0",
                    "current_price": "30.0",
                    "entry_date": "not-a-date",
                }
            ]
        ),
    )
    with pytest.raises(InvalidOrderError, match="Malformed entry_date"):
        broker.get_account_snapshot()


# ---------------------------------------------------------------------------
# AC09: Sandbox host allowlist, HMAC-SHA256 signing, timeouts & HTTP mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_url",
    [
        "https://api.alpaca.markets",
        "https://broker-api.alpaca.markets",
        "https://api.binance.com",
        "https://evil-broker.com",
        "https://paper-api.alpaca.markets.evil.com",
        "https://user:pass@paper-api.alpaca.markets",
        "http://paper-api.alpaca.markets",
        "ftp://paper-api.alpaca.markets",
        "not-a-url",
    ],
)
def test_ac09_rejects_live_and_unapproved_base_urls(
    monkeypatch: pytest.MonkeyPatch, bad_url: str
) -> None:
    """AC09: Refuse live production endpoints, unlisted hosts, and non-HTTPS remote URLs."""
    _set_sandbox_env(monkeypatch)
    with pytest.raises(ExecutionConfigurationError):
        RestSandboxBroker(base_url=bad_url)


def test_ac09_refuses_allowlisting_live_host_and_permits_valid_sandbox_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC09: Live hosts cannot be allowlisted; approved sandbox & loopback URLs pass."""
    _set_sandbox_env(monkeypatch)
    with pytest.raises(ExecutionConfigurationError, match="live production host"):
        RestSandboxBroker(
            base_url="https://api.alpaca.markets",
            allowed_sandbox_hosts=("api.alpaca.markets",),
        )

    assert RestSandboxBroker(base_url="https://paper-api.alpaca.markets").base_url == (
        "https://paper-api.alpaca.markets"
    )
    assert RestSandboxBroker(base_url="https://testnet.binance.vision/").base_url == (
        "https://testnet.binance.vision"
    )
    assert RestSandboxBroker(base_url="http://127.0.0.1:8080").base_url == (
        "http://127.0.0.1:8080"
    )
    custom = RestSandboxBroker(
        base_url="https://sandbox.quant-internal.test",
        allowed_sandbox_hosts=("sandbox.quant-internal.test",),
    )
    assert custom.base_url == "https://sandbox.quant-internal.test"


def test_ac09_signs_hmac_sha256_headers_with_timeout_and_no_secret_leak(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """AC09: Sign requests via HMAC-SHA256 using stdlib urlopen and never log secrets."""
    secret = "my-top-secret-key"
    _set_sandbox_env(monkeypatch, key="key-123", secret=secret)

    fixed_now = datetime(2024, 6, 1, 12, 30, 0, tzinfo=timezone.utc)  # noqa: UP017
    captured: dict[str, Any] = {}

    def _fake_urlopen(
        req: urllib.request.Request, *, timeout: float
    ) -> _FakeHTTPResponse:
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["timeout"] = timeout
        captured["headers"] = {k.lower(): v for k, v in req.header_items()}
        captured["body"] = (
            req.data.decode("utf-8") if isinstance(req.data, bytes) else ""
        )
        if req.full_url.endswith("/v2/account"):
            return _FakeHTTPResponse(
                200, json.dumps({"cash": "100.0", "equity": "100.0"})
            )
        return _FakeHTTPResponse(
            200,
            json.dumps(
                {
                    "id": "alp-1",
                    "client_order_id": "cid-sb-1",
                    "symbol": "ITUB4F",
                    "ticker": "ITUB4.SA",
                    "side": "buy",
                    "qty": "2",
                    "filled_qty": "2",
                    "filled_avg_price": "30.0",
                    "status": "filled",
                    "submitted_at": "2024-06-01T12:30:00Z",
                    "filled_at": "2024-06-01T12:30:00Z",
                }
            ),
        )

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    cfg = ExecutionConfig(request_timeout_seconds=3.5)
    broker = RestSandboxBroker(cfg, clock=lambda: fixed_now)
    assert isinstance(broker, IBrokerAdapter)

    with caplog.at_level(logging.DEBUG):
        broker.connect()
        receipt = broker.submit_order(_make_market_buy("cid-sb-1"))

    assert receipt.status == OrderStatus.FILLED
    assert receipt.execution_symbol == "ITUB4F"
    assert captured["timeout"] == pytest.approx(3.5)

    headers = captured["headers"]
    assert headers["apca-api-key-id"] == "key-123"
    assert all(secret not in val for val in headers.values())

    expected_ts = str(int(fixed_now.timestamp() * 1000))
    assert headers["x-sandbox-timestamp"] == expected_ts
    expected_prehash = f"{expected_ts}\nPOST\n/v2/orders\n{captured['body']}"
    expected_sig = hmac.new(
        secret.encode("utf-8"),
        expected_prehash.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    assert headers["x-sandbox-signature"] == expected_sig
    assert secret not in caplog.text
    assert "key-123" not in caplog.text


def test_ac09_lifecycle_lookup_404_cancel_snapshot_and_ping_latency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC09: Verify ping latency, LIMIT submit, 404 lookup -> None, cancel, and snapshot."""
    _set_sandbox_env(monkeypatch)
    ticks = itertools.chain([10.0, 10.025, 20.0, 20.125], itertools.repeat(30.0))
    now = datetime(2024, 6, 2, 15, 0, tzinfo=timezone.utc)  # noqa: UP017
    seen_bodies: list[dict[str, Any]] = []

    def _transport(req: urllib.request.Request, timeout: float) -> tuple[int, str]:
        path = req.full_url.replace("https://paper-api.alpaca.markets", "")
        method = req.get_method()
        if method == "GET" and path == "/v2/account":
            return 200, json.dumps(
                {"cash": "40.0", "equity": "100.0", "total_fees_paid": "0.018"}
            )
        if method == "POST" and path == "/v2/orders":
            seen_bodies.append(json.loads(req.data.decode("utf-8")))  # type: ignore[union-attr]
            return 200, json.dumps(
                {
                    "id": "alp-lim-1",
                    "client_order_id": "cid-lim",
                    "symbol": "ITUB4F",
                    "side": "buy",
                    "qty": "2",
                    "filled_qty": "0",
                    "status": "new",
                }
            )
        if method == "GET" and "client_order_id=missing" in path:
            raise _http_error(req.full_url, 404, '{"message":"order not found"}')
        if method == "GET" and "client_order_id=cid-lim" in path:
            return 200, json.dumps(
                {
                    "id": "alp-lim-1",
                    "client_order_id": "cid-lim",
                    "symbol": "ITUB4F",
                    "side": "buy",
                    "qty": "2",
                    "filled_qty": "0",
                    "status": "accepted",
                }
            )
        if method == "DELETE" and path == "/v2/orders":
            return 200, json.dumps(
                [
                    {
                        "id": "alp-lim-1",
                        "client_order_id": "cid-lim",
                        "symbol": "ITUB4F",
                        "side": "buy",
                        "qty": "2",
                        "filled_qty": "0",
                        "status": "canceled",
                    }
                ]
            )
        if method == "GET" and path == "/v2/positions":
            return 200, json.dumps(
                [
                    {
                        "ticker": "ITUB4.SA",
                        "qty": "2",
                        "avg_entry_price": "30.0",
                        "current_price": "31.0",
                        "entry_date": "2024-06-02",
                    }
                ]
            )
        if method == "GET" and path == "/v2/orders?status=open":
            return 200, json.dumps([])
        raise AssertionError(f"Unexpected request {method} {path}")

    broker = RestSandboxBroker(
        transport=_transport,
        clock=lambda: now,
        perf_counter=lambda: next(ticks),
    )
    assert broker.is_connected() is False
    with pytest.raises(BrokerConnectionError):
        broker.ping()

    broker.connect()
    assert broker.is_connected() is True
    assert broker.ping() == pytest.approx(125.0)

    lim_req = OrderRequest(
        client_order_id="cid-lim",
        ticker="ITUB4.SA",
        side=OrderSide.BUY,
        shares=2,
        reference_price=30.0,
        order_type=OrderType.LIMIT,
        limit_price=28.0,
    )
    sub_rec = broker.submit_order(lim_req)
    assert sub_rec.status == OrderStatus.SUBMITTED
    assert seen_bodies[0]["limit_price"] == "28.000000"

    assert broker.get_order_by_client_id("missing") is None
    found = broker.get_order_by_client_id("cid-lim")
    assert found is not None and found.broker_order_id == "alp-lim-1"

    cancelled = broker.cancel_all_open_orders()
    assert len(cancelled) == 1 and cancelled[0].status == OrderStatus.CANCELLED

    snap = broker.get_account_snapshot({"ITUB4.SA": 35.0})
    assert snap.cash == pytest.approx(40.0)
    assert snap.positions["ITUB4.SA"].entry_date == date(2024, 6, 2)
    assert snap.positions["ITUB4.SA"].unrealized_pnl == pytest.approx(10.0)
    assert snap.equity == pytest.approx(110.0)

    broker.disconnect()
    assert broker.is_connected() is False


@pytest.mark.parametrize(
    ("failure", "expected_exc"),
    [
        (
            _http_error(
                "https://paper-api.alpaca.markets/v2/orders",
                400,
                '{"message":"bad qty"}',
            ),
            OrderRejectedError,
        ),
        (
            _http_error(
                "https://paper-api.alpaca.markets/v2/orders",
                401,
                '{"message":"unauthorized"}',
            ),
            OrderRejectedError,
        ),
        (
            _http_error(
                "https://paper-api.alpaca.markets/v2/orders",
                422,
                '{"message":"insufficient buying power"}',
            ),
            OrderRejectedError,
        ),
        (
            _http_error(
                "https://paper-api.alpaca.markets/v2/orders", 408, "request timeout"
            ),
            BrokerConnectionError,
        ),
        (
            _http_error(
                "https://paper-api.alpaca.markets/v2/orders", 429, "rate limit"
            ),
            BrokerConnectionError,
        ),
        (
            _http_error(
                "https://paper-api.alpaca.markets/v2/orders",
                500,
                "internal server error",
            ),
            BrokerConnectionError,
        ),
        (
            _http_error(
                "https://paper-api.alpaca.markets/v2/orders", 503, "unavailable"
            ),
            BrokerConnectionError,
        ),
        (TimeoutError("timed out"), BrokerConnectionError),
        (urllib.error.URLError(TimeoutError("url timeout")), BrokerConnectionError),
        (urllib.error.URLError("dns lookup failed"), BrokerConnectionError),
        (OSError("connection reset by peer"), BrokerConnectionError),
    ],
)
def test_ac09_translates_http_4xx_5xx_timeouts_and_network_errors(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    expected_exc: type[Exception],
) -> None:
    """AC09: Map HTTP 4xx -> OrderRejectedError; 408/429/5xx/timeouts -> BrokerConnectionError."""
    _set_sandbox_env(monkeypatch)

    def _transport(req: urllib.request.Request, timeout: float) -> tuple[int, str]:
        if req.full_url.endswith("/v2/account"):
            return 200, json.dumps({"cash": "100.0", "equity": "100.0"})
        raise failure

    broker = RestSandboxBroker(transport=_transport)
    broker.connect()
    with pytest.raises(expected_exc):
        broker.submit_order(_make_market_buy())


def test_ac09_translates_non_exception_4xx_and_5xx_response_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC09: Non-exception HTTP 4xx/5xx responses also map cleanly to typed errors."""
    _set_sandbox_env(monkeypatch)
    current_response: tuple[int, str] = (422, '{"message":"invalid lot"}')

    def _transport(req: urllib.request.Request, timeout: float) -> tuple[int, str]:
        if req.full_url.endswith("/v2/account"):
            return 200, json.dumps({"cash": "100.0", "equity": "100.0"})
        return current_response

    broker = RestSandboxBroker(transport=_transport)
    broker.connect()
    with pytest.raises(OrderRejectedError, match="HTTP 422"):
        broker.submit_order(_make_market_buy())

    current_response = (502, "bad gateway")
    with pytest.raises(BrokerConnectionError, match="HTTP 502"):
        broker.submit_order(_make_market_buy())

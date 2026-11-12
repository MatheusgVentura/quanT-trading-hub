# Specification: Paper Trading and Resilient Order Execution (`005-execution-paper`)

**Status:** approved  
**Date:** 2026-11-11  
**Domain Area:** `src/execution/`

---

## 1. Objective
Implement the decoupled Order Execution and Paper Trading layer (`src/execution/`) positioned downstream of Strategy (`src/strategies/`) and Risk Management (`src/risk/`), completing the autonomous trading pipeline defined in `PROJETO.md` Section 3:
1. **Broker Contract (`IBrokerAdapter`):** Abstract interface decoupling execution orchestration from concrete broker transports, enabling deterministic simulated paper trading, authenticated REST sandbox testing (`.env`-based), and clean mocking.
2. **B3 Fractional Paper Broker (`SimulatedPaperBroker`):** Zero-cost local execution simulator modeling a R$ 100.00 retail account on B3 (fractional `'F'` ticker formatting, 0.03% B3 fee, zero RLP brokerage, configurable slippage, `MARKET` and `LIMIT` order lifecycles, custody tracking with entry dates, and native `client_order_id` idempotency).
3. **Optional REST Sandbox Client (`RestSandboxBroker`):** Stdlib-only (`urllib` + `hmac`/`hashlib`) authenticated sandbox broker adapter (supporting Alpaca Paper / HMAC-SHA256 REST endpoints configured via `.env` without introducing external HTTP library dependencies).
4. **Resilient Idempotent Router (`OrderRouter`):** Protects order delivery with deterministic idempotency keys (`client_order_id` lookup before retry), exponential-backoff reconnection and account state reconciliation on transient network failures, and fail-closed emergency Kill-Switch handling (canceling all open orders, optional emergency liquidation, structured logging, and raising `ExecutionHaltedError`).
5. **Paper Trading Runner & Persistence (`PaperTradingRunner` / `ExecutionLedger`):** Orchestrates bar-by-bar or step-by-step live/historical paper simulations (`Data -> Strategy -> RiskManager -> OrderRouter -> Broker`), optionally persisting atomic JSON/Parquet execution logs for Phase 6 Dashboard consumption, plus a thin CLI entrypoint handling process exit (`sys.exit(1)`).

---

## 2. Out of Scope
* **Live Production Real-Money Broker Routing:** Sending unguarded real-money B3 orders through proprietary XP/Clear/BTG DMA protocols (future Phase 7+ after sandbox & dashboard validation).
* **Persistent Open WebSocket Streaming Server:** Running an async multi-symbol tick ingestion daemon; connection resiliency and exponential backoff apply synchronously/deterministically across broker API operations (`connect`, `submit_order`, `cancel_all_open_orders`, `get_account_snapshot`).
* **Short Selling, Margin Accounts, or Options/Derivatives:** Strictly Long/Cash integer-lot spot equity execution (`shares >= 0`, no negative cash or short borrowing).
* **Web UI / Plotting:** Streamlit/Plotly visualization belongs strictly to Phase 6 (`src/dashboard/`), which will read persisted execution artifacts produced here.

---

## 3. Acceptance Criteria

### Criteria Derived from `PROJETO.md`
* **AC01:** **Idempotent Order Submission:** `OrderRouter` must attach a deterministic `client_order_id` to every order. When an initial `submit_order` call fails due to timeout or connection interruption (`BrokerConnectionError`), subsequent retry attempts must query `get_order_by_client_id(client_order_id)` first and return the existing receipt if already accepted by the broker instead of submitting a duplicate order.
* **AC02:** **Resilient Reconnection with Exponential Backoff & State Sync:** Transient `BrokerConnectionError` failures during order routing, cancellation, or account queries must trigger exponential backoff retries (`delay = base_backoff_seconds * (backoff_multiplier ** attempt)`, using an injectable sleep callable) up to `max_retries`; upon recovery, `OrderRouter` must reconcile open orders and account state via `get_account_snapshot()` before returning control. Exhausting retries must raise `BrokerConnectionError`.
* **AC03:** **Kill-Switch Emergency Reaction (`PROJETO.md` Section 3):** Whenever `RiskManager` reports `RiskStatus.HALTED` (e.g., daily loss `>= 2%`, drawdown `>= 10%`, or latency `> 500ms`), `OrderRouter` must immediately invoke `cancel_all_open_orders()`, emit a structured `ERROR` log entry, execute optional emergency position liquidation (`is_emergency=True`) if `liquidate_on_halt=True`, and raise `ExecutionHaltedError`. The CLI entrypoint catches `ExecutionHaltedError` and terminates with exit code `1` (`sys.exit(1)`), whereas library components never kill the host Python process directly.
* **AC04:** **B3 Fractional `'F'` Formatting & Fee Accounting:** When `use_fractional_suffix=True`, `SimulatedPaperBroker` (and order symbol formatter) must map B3 standard tickers ending in `.SA` with non-100-multiple share quantities (`0 < shares % 100 != 0`) to fractional execution symbols (`ITUB4.SA` -> `ITUB4F`), charge exact B3 fees (`round_to_cent` or exact `notional * b3_fee_pct`, default `0.0003`) plus `brokerage_fee = 0.0`, and prevent cash overdraft on buy fills.

### Criteria Derived from Engineering Standards & Pipeline Architecture
* **AC05:** **Clean Broker Abstraction (`IBrokerAdapter`) & Simulated Paper Lifecycle:** `SimulatedPaperBroker` must implement `IBrokerAdapter` supporting `MARKET` fills (with configurable `slippage_pct`), `LIMIT` order resting (`SUBMITTED`) until a price update matches (`BUY` when `market_price <= limit_price`; `SELL` when `market_price >= limit_price`), cancellation (`cancel_all_open_orders()`), cash/custody/average-cost accounting, and round-trip latency reporting (`ping()`).
* **AC06:** **Strict Pre-Trade Gate Integration (`OrderRouter` + `RiskManager`):** Every signal processed by `OrderRouter` / `PaperTradingRunner` must pass through `RiskManager.evaluate_trade(...)` before any `OrderRequest` is built or sent. Unapproved signals (`HOLD`, unapproved `BUY`, blocked $D_0$ voluntary `EXIT`) must never generate broker orders.
* **AC07:** **Swing Trade Custody Protection in Execution:** `SimulatedPaperBroker` tracks each held position's `entry_date`, supplying it to `RiskManager.evaluate_trade(...)` so voluntary $D_0$ sells are blocked by `RiskManager` when `allow_day_trade=False`, while emergency exits (`is_emergency=True`) remain executable immediately on $D_0$.
* **AC08:** **Fail-Closed Validation & Credential Hygiene:** Invalid `ExecutionConfig`, malformed `OrderRequest` inputs (`shares <= 0`, non-finite/`<= 0` prices, empty ticker or `client_order_id`), negative simulated cash, or corrupted broker responses must raise typed exceptions (`ExecutionConfigurationError`, `InvalidOrderError`, `OrderRejectedError`) inheriting from `ExecutionError`. Any REST sandbox credentials must be read solely from environment variables (`.env`), never hardcoded or logged.
* **AC09:** **REST Sandbox Adapter Contract (Stdlib HMAC-SHA256):** When enabled, `RestSandboxBroker` must sign authenticated requests using HMAC-SHA256 headers from environment credentials (`ALPACA_API_KEY` / `ALPACA_SECRET_KEY` or configured sandbox endpoints), validate non-live sandbox base URLs (refusing non-sandbox/production hosts unless explicitly allowed by sandbox safety check), enforce request timeouts, and translate HTTP 4xx/5xx/timeouts into typed `OrderRejectedError` or `BrokerConnectionError`.
* **AC10:** **Atomic Paper State & Ledger Persistence:** When `state_path` is provided, `SimulatedPaperBroker` / `PaperTradingRunner` must persist account state, receipts, and equity snapshots atomically (write temporary file + replace) without corrupting existing history on crash, enabling reload and resumption across restarts.
* **AC11:** **End-to-End B3 Paper Simulation (`R$ 100.00` Integer Lots):** `PaperTradingRunner.run_simulation(...)` must execute EMA 9/21 (`EMACrossoverStrategy` with warm-up sliced) + `RiskManager` + `OrderRouter` + `SimulatedPaperBroker` across B3 equities (`ITUB4.SA`, `PETR4.SA`, `VALE3.SA`, `WEGE3.SA` from `2021-11-01` to `2024-11-01`), modeling integer fractional shares, residual cash, B3 0.03% fees, and producing a complete `PaperSimulationReport`.
* **AC12:** **Quality Gate Compliance:** All Phase 5 modules and tests must pass `ruff check .`, `ruff format --check .`, `mypy --strict src tests`, and `pytest --cov=src -v`.

---

## 4. Edge Cases
* **Duplicate Retry After Silent Timeout:** Broker accepted order #1 on first HTTP POST, response timed out; retry #2 queries `get_order_by_client_id(cid)` and receives existing `FILLED` receipt without double-spending cash.
* **Empty Cash / Fractional Remainder:** On `R$ 100.00`, buying 2 shares of `ITUB4F` at `R$ 30.00` leaves `R$ 39.98` cash (`100 - 60 - 0.018`). Account equity equals `cash + 2 * mark_price`, never inflating to fractional shares.
* **Pending `LIMIT BUY` Open When Kill-Switch Trips:** Open limit order locks or awaits execution; when Kill-Switch triggers `HALTED`, `cancel_all_open_orders()` transitions open orders to `CANCELLED` and releases reserved buying power cleanly.
* **Exhausted Retries on Disconnected Broker:** Network stays down beyond `max_retries`; backoff executes exactly `max_retries` delays, then fails closed by raising `BrokerConnectionError`.
* **Corrupted / Negative External Telemetry:** `NaN`/`Inf`/`<= 0` price passed into `OrderRequest` or `PaperTradingRunner.step(...)` immediately fails closed (`InvalidOrderError`) without touching broker balances.
* **Resuming Persisted Account State:** Reloading `SimulatedPaperBroker` from saved JSON restores exact cash, open positions (`entry_date`, `avg_entry_price`), processed `client_order_id` registry (preserving idempotency across restarts!), and filled receipts.

---

## 5. Contracts and Data Models

```python
class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class ExecutionConfig:
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


@dataclass(frozen=True)
class OrderRequest:
    client_order_id: str
    ticker: str
    side: OrderSide
    shares: int
    order_type: OrderType = OrderType.MARKET
    reference_price: float = 0.0
    limit_price: float | None = None
    created_at: datetime = ...
    is_emergency: bool = False
    reason: str = ""


@dataclass(frozen=True)
class OrderReceipt:
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


@dataclass(frozen=True)
class PositionSnapshot:
    ticker: str
    shares: int
    avg_entry_price: float
    entry_date: date
    market_price: float
    unrealized_pnl: float


@dataclass(frozen=True)
class AccountSnapshot:
    cash: float
    equity: float
    realized_pnl: float
    total_fees_paid: float
    positions: dict[str, PositionSnapshot]
    open_orders: list[OrderReceipt]
    timestamp: datetime


class IBrokerAdapter(ABC):
    @abstractmethod
    def connect(self) -> None: ...
    @abstractmethod
    def is_connected(self) -> bool: ...
    @abstractmethod
    def ping(self) -> float: ...
    @abstractmethod
    def submit_order(self, order: OrderRequest) -> OrderReceipt: ...
    @abstractmethod
    def get_order_by_client_id(self, client_order_id: str) -> OrderReceipt | None: ...
    @abstractmethod
    def cancel_all_open_orders(self) -> list[OrderReceipt]: ...
    @abstractmethod
    def get_account_snapshot(
        self, market_prices: dict[str, float] | None = None
    ) -> AccountSnapshot: ...
```

---

## 6. Abuse and Security Risks
* **Live Production Endpoint Misconfiguration:** Passing a real-money brokerage URL (e.g., Alpaca live URL instead of `paper-api.alpaca.markets`) with valid keys could place real orders accidentally. Mitigated by enforcing an explicit sandbox-URL allowlist/guard in `RestSandboxBroker` (AC09).
* **Secret Leakage in Logs or Exceptions:** Formatting HTTP headers or `ExecutionConfig` with API keys/secrets into logs or error tracebacks exposes credentials. Mitigated by reading credentials strictly from env vars inside `RestSandboxBroker.__init__`, excluding secrets from `__repr__` and logs.
* **Duplicate Order Storm on Timeout:** Retrying REST POST without checking `get_order_by_client_id` could exhaust R$ 100 cash or create unintended short/oversized exposure. Mitigated by mandatory `client_order_id` lookup before every retry (AC01).
* **Corrupted State File Persistence:** Non-atomic writes interrupted mid-flush could corrupt JSON/Parquet state. Mitigated by write-to-temp + `os.replace` atomic swaps and schema validation on load.
* **Host Process Termination Inside Unit Tests:** Calling `sys.exit(1)` inside core classes breaks test harnesses and Phase 6 dashboards. Mitigated by raising `ExecutionHaltedError` inside `OrderRouter` / `PaperTradingRunner` and restricting `sys.exit(1)` strictly to the CLI entrypoint (`cli.py`).

---

## 7. Open Questions
* *None. All open questions were resolved by explicit user approval on 2026-11-11.*

---

## 8. Assumptions Made & Architecture Decisions Log
1. **Default Broker Strategy:** Implement `IBrokerAdapter` + `SimulatedPaperBroker` (default zero-dependency B3 simulator) + `RestSandboxBroker` (stdlib `urllib` + HMAC-SHA256 / Alpaca Paper headers, guarded strictly to sandbox hosts and verified cleanly via mocked `urlopen`/transport in automated tests).
2. **Default B3 Fractional Routing:** Enable `use_fractional_suffix=True`, mapping `ITUB4.SA` -> `ITUB4F` for non-multiple-of-100 lots on `execution_symbol` while keeping canonical `.SA` keys in `AccountSnapshot.positions`.
3. **Default Halt Liquidation:** Enable `liquidate_on_halt=True` in `ExecutionConfig` so a `KillSwitch` halt cancels all pending open orders and submits an emergency exit for any currently held position before raising `ExecutionHaltedError`.
4. **Default Persistence:** Implement atomic JSON state persistence (`AccountSnapshot` + `OrderReceipt` history + idempotency index) inside `SimulatedPaperBroker` when `state_path` is set (`None` = pure in-memory by default).
5. **No New Dependencies:** Keep `requirements.txt` unchanged using Python 3.10 stdlib HTTP/crypto primitives.


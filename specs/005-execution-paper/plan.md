# Architecture Plan: Paper Trading and Resilient Order Execution (`005-execution-paper`)

**Status:** approved  
**Date:** 2026-11-11  

---

## 1. Architectural Decisions

* **Strict Pipeline Decoupling (`PROJETO.md` Section 3):** `src/execution/` consumes signals from `src/strategies/` and mandatory verdicts from `src/risk/` (`RiskManager`), never inventing alpha logic or bypassing risk gates.
* **Compositional Module Layout:**
  1. `exceptions.py`: Typed exception hierarchy (`ExecutionError`, `ExecutionConfigurationError`, `InvalidOrderError`, `BrokerConnectionError`, `OrderRejectedError`, `ExecutionHaltedError`).
  2. `models.py`: Frozen dataclasses and enums (`OrderSide`, `OrderType`, `OrderStatus`, `ExecutionConfig`, `OrderRequest`, `OrderReceipt`, `PositionSnapshot`, `AccountSnapshot`, `ExecutionStepResult`) with fail-closed validation reusing finite numeric checks.
  3. `interfaces.py`: `IBrokerAdapter` abstract base class defining `connect`, `is_connected`, `ping`, `submit_order`, `get_order_by_client_id`, `cancel_all_open_orders`, and `get_account_snapshot`.
  4. `paper_broker.py`: `SimulatedPaperBroker` implementing B3 fractional R$ 100.00 accounting, `MARKET` and `LIMIT` order lifecycles, fractional `'F'` execution symbol formatting, idempotency registry, and atomic JSON state persistence (`temp` + `os.replace`).
  5. `sandbox_broker.py`: `RestSandboxBroker` implementing authenticated REST sandbox transport (HMAC-SHA256 / Alpaca header signing via Python stdlib `urllib.request`, `hmac`, `hashlib`) with strict non-production sandbox host allowlist enforcement.
  6. `router.py`: `OrderRouter` managing deterministic `client_order_id` generation, idempotent timeout recovery (query before retry), exponential-backoff retry with post-recovery `get_account_snapshot()` sync, and Kill-Switch emergency orchestration (`cancel_all_open_orders` + optional emergency sell + `ExecutionHaltedError`).
  7. `runner.py` & `cli.py`: `PaperTradingRunner` connecting `BaseStrategy`, `RiskManager`, and `OrderRouter` for single-step live/loop execution and historical B3 paper simulation; `cli.py` provides the thin OS boundary translating `ExecutionHaltedError` into `sys.exit(1)`.
* **Deterministic Testability:** Time, `sleep_fn`, latency measurement, and HTTP transport accept clean constructor/method injection so retry backoffs, timeouts, idempotency, and REST failures execute deterministically in milliseconds under `pytest`.

---

## 2. Alternatives Discarded

* **Adding Third-Party Async/HTTP Packages (`ccxt`, `httpx`, `alpaca-py`):** Rejected as core dependencies to preserve zero bloat, avoid breaking offline/minimal installs, and maximize portability with `urllib.request` + `hmac` in stdlib (while `IBrokerAdapter` still allows plug-in SDK adapters later).
* **Calling `sys.exit(1)` Inside `OrderRouter` or `PaperTradingRunner`:** Rejected because terminating the interpreter inside library code prevents unit testing halt paths and breaks future Phase 6 Streamlit sessions; isolated strictly to `cli.py`.
* **Modifying Phase 2 `VectorizedBacktestEngine` for Integer Share Simulation:** Rejected to preserve Phase 2 immutability; integer-share cash/custody paper simulation lives cleanly in `PaperTradingRunner` + `SimulatedPaperBroker`.
* **Non-Atomic Direct `open(..., "w")` State Saves:** Rejected because partial writes on process termination during Kill-Switch halts could corrupt ledger history.


# Tasks: Paper Trading and Resilient Order Execution (`005-execution-paper`)

**Status:** approved  

---

- [x] **Task 5.1:** Define typed exception hierarchy (`ExecutionError`, `ExecutionConfigurationError`, `InvalidOrderError`, `BrokerConnectionError`, `OrderRejectedError`, `ExecutionHaltedError`) in `src/execution/exceptions.py` with unit tests. *(Mapped to: AC08)*
- [x] **Task 5.2:** Implement validated execution contracts and models (`OrderSide`, `OrderType`, `OrderStatus`, `ExecutionConfig`, `OrderRequest`, `OrderReceipt`, `PositionSnapshot`, `AccountSnapshot`, `ExecutionStepResult`) in `src/execution/models.py` and `IBrokerAdapter` in `src/execution/interfaces.py` with boundary tests. *(Mapped to: AC05, AC08)*
- [x] **Task 5.3:** Implement `SimulatedPaperBroker` in `src/execution/paper_broker.py` supporting B3 fractional `'F'` execution symbols, `0.03%` B3 fee / RLP zero brokerage, `MARKET` & `LIMIT` fills, cash/custody accounting, idempotency, and atomic JSON state persistence with unit tests. *(Mapped to: AC04, AC05, AC07, AC08, AC10)*
- [ ] **Task 5.4:** Implement `RestSandboxBroker` in `src/execution/sandbox_broker.py` using stdlib `urllib` + HMAC-SHA256 / `.env` credentials with strict sandbox URL enforcement, timeout mapping, and mocked unit tests. *(Mapped to: AC08, AC09)*
- [ ] **Task 5.5:** Implement `OrderRouter` in `src/execution/router.py` enforcing deterministic `client_order_id` idempotency, exponential backoff retries, post-reconnect account sync, `RiskManager` gate enforcement, and Kill-Switch cancellation/halt handling with unit tests. *(Mapped to: AC01, AC02, AC03, AC06, AC07)*
- [ ] **Task 5.6:** Implement `PaperTradingRunner` in `src/execution/runner.py`, thin `sys.exit(1)` CLI entrypoint in `src/execution/cli.py`, and export public API in `src/execution/__init__.py` with unit tests. *(Mapped to: AC03, AC06, AC11)*
- [ ] **Task 5.7:** Implement end-to-end integration tests in `tests/integration/test_b3_paper_execution.py` running `EMACrossoverStrategy` 9/21 + `RiskManager` + `OrderRouter` + `SimulatedPaperBroker` across `ITUB4.SA`, `PETR4.SA`, `VALE3.SA`, and `WEGE3.SA` (`2021-11-01` to `2024-11-01`) with `R$ 100.00` nominal capital and persisted state reload verification. *(Mapped to: AC10, AC11)*
- [ ] **Task 5.8:** Final quality gate verification (`ruff check .`, `ruff format --check .`, `mypy --strict src tests`, `pytest --cov=src -v`) and update `PROGRESS.md`. *(Mapped to: AC12)*


# PROGRESS.md - Estado Atual e Rastreamento Dinâmico

Documento dinâmico contendo o estado atual, decisões ativas e próximos passos do projeto.

---

## Estado atual
* **Fases concluídas:** 000 (Setup/SDD), 001 (Data), 002 (Backtest), 003 (Strategy EMA), 004 (Risk & Kill-Switch).
* **Fase ativa:** 005 — Paper Trading & Execução Resiliente (`specs/005-execution-paper/`), Tasks 5.1–5.5 concluídas.
* **Branch:** `main` | **Qualidade:** 257 testes passando (94% de cobertura), mypy strict e ruff 100%.

## Em andamento
* Implementação da Fase 5 (`src/execution/`). Próxima tarefa: Task 5.6 (`runner.py` & `cli.py`).

## Próximos passos
1. Executar Task 5.6: implementar `PaperTradingRunner` em `src/execution/runner.py`, entrypoint thin `src/execution/cli.py` e exports em `__init__.py` + testes unitários.
2. Seguir sequencialmente Tasks 5.7 e 5.8 de `specs/005-execution-paper/tasks.md`.

## Decisões ativas
* **Metodologia:** SDD estrito (tríade `spec.md`, `plan.md`, `tasks.md` antes de qualquer código).
* **Padrão de Qualidade:** Python 3.10+, `mypy --strict`, `ruff` e testes vinculados aos ACs (`test_acXX_...`).
* **Estratégia EMA:** 9/21 diário (`1d`), sinais `{0, 1}`, taxa B3 0,03%, warm-up recortado.
* **Risco (004):** R$ 100, risco estrito 2%/trade (`allow_min_lot_override=False`), Stop/Trailing 5% no fechamento (`Close -> t+1`), Swing Trade bloqueando saídas voluntárias em $D_0$, Kill-Switch (2% diário auto-reset / >500ms e 10% DD reset manual).
* **Execução (005):** `SimulatedPaperBroker` (B3 `'F'`, 0,03% fee, JSON atômico opcional) + `RestSandboxBroker` (stdlib `urllib`/HMAC), `liquidate_on_halt=True`, zero novas deps.

## Bloqueios
* Nenhum bloqueio ativo.

## Entregas concluídas (últimas 5)
1. **Fase 5 / Task 5.1 (Execution Exceptions):** Spec 005 aprovada e hierarquia tipada em `src/execution/exceptions.py` + 6 testes unitários.
2. **Fase 5 / Task 5.2 (Models & Broker ABC):** `ExecutionConfig`, modelos de ordem/conta, `format_b3_execution_symbol` e `IBrokerAdapter` + 34 testes unitários.
3. **Fase 5 / Task 5.3 (SimulatedPaperBroker):** B3 `'F'`, taxa 0,03%, `MARKET`/`LIMIT`, reserva de caixa/custódia, idempotência e JSON atômico em `src/execution/paper_broker.py` + 26 testes unitários.
4. **Fase 5 / Task 5.4 (RestSandboxBroker):** Cliente REST stdlib `urllib` + HMAC-SHA256 / `.env`, allowlist estrita de URLs sandbox e timeouts em `src/execution/sandbox_broker.py` + 35 testes mockados.
5. **Fase 5 / Task 5.5 (OrderRouter):** Roteador idempotente (`client_order_id`), retries exponential backoff, sync pós-reconexão, gate `RiskManager` e Kill-Switch em `src/execution/router.py` + 13 testes unitários.

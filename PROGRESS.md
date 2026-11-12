# PROGRESS.md - Estado Atual e Rastreamento Dinâmico

Documento dinâmico contendo o estado atual, decisões ativas e próximos passos do projeto.

---

## Estado atual
* **Fases concluídas:** 000 (Setup/SDD), 001 (Data), 002 (Backtest), 003 (Strategy EMA), 004 (Risk & Kill-Switch).
* **Fase ativa:** 005 — Paper Trading & Execução Resiliente (`specs/005-execution-paper/`), Tasks 5.1–5.3 concluídas.
* **Branch:** `main` | **Qualidade:** 209 testes passando (95% de cobertura), mypy strict e ruff 100%.

## Em andamento
* Implementação da Fase 5 (`src/execution/`). Próxima tarefa: Task 5.4 (`sandbox_broker.py`).

## Próximos passos
1. Executar Task 5.4: implementar `RestSandboxBroker` em `src/execution/sandbox_broker.py` (`urllib` stdlib + HMAC-SHA256 / `.env`, allowlist sandbox estrita, timeouts e mocks) + testes.
2. Seguir sequencialmente Tasks 5.5 a 5.8 de `specs/005-execution-paper/tasks.md`.

## Decisões ativas
* **Metodologia:** SDD estrito (tríade `spec.md`, `plan.md`, `tasks.md` antes de qualquer código).
* **Padrão de Qualidade:** Python 3.10+, `mypy --strict`, `ruff` e testes vinculados aos ACs (`test_acXX_...`).
* **Estratégia EMA:** 9/21 diário (`1d`), sinais `{0, 1}`, taxa B3 0,03%, warm-up recortado.
* **Risco (004):** R$ 100, risco estrito 2%/trade (`allow_min_lot_override=False`), Stop/Trailing 5% no fechamento (`Close -> t+1`), Swing Trade bloqueando saídas voluntárias em $D_0$, Kill-Switch (2% diário auto-reset / >500ms e 10% DD reset manual).
* **Execução (005):** `SimulatedPaperBroker` (B3 `'F'`, 0,03% fee, JSON atômico opcional) + `RestSandboxBroker` (stdlib `urllib`/HMAC), `liquidate_on_halt=True`, zero novas deps.

## Bloqueios
* Nenhum bloqueio ativo.

## Entregas concluídas (últimas 5)
1. **Fase 4 / Task 4.7 (B3 Risk Integration):** `tests/integration/test_b3_risk_backtest.py` comparando EMA 9/21 baseline vs risk-managed + sizing R$ 100 nos 4 ativos B3 (+8 testes).
2. **Fase 4 / Task 4.8 (Fechamento Fase 004):** Quality gate final validado (`ruff`, `mypy --strict`, `143` testes, `96%` de cobertura) e AC01-AC12 100% cobertos.
3. **Fase 5 / Task 5.1 (Execution Exceptions):** Spec 005 aprovada e hierarquia tipada em `src/execution/exceptions.py` + 6 testes unitários.
4. **Fase 5 / Task 5.2 (Models & Broker ABC):** `ExecutionConfig`, modelos de ordem/conta, `format_b3_execution_symbol` e `IBrokerAdapter` + 34 testes unitários.
5. **Fase 5 / Task 5.3 (SimulatedPaperBroker):** B3 `'F'`, taxa 0,03%, `MARKET`/`LIMIT`, reserva de caixa/custódia, idempotência e JSON atômico em `src/execution/paper_broker.py` + 26 testes unitários.

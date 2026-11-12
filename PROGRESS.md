# PROGRESS.md - Estado Atual e Rastreamento Dinâmico

Documento dinâmico contendo o estado atual, decisões ativas e próximos passos do projeto.

---

## Estado atual
* **Fases concluídas:** 000 (Setup/SDD), 001 (Data), 002 (Backtest), 003 (Strategy EMA), 004 (Risk & Kill-Switch), 005 (Execution & Paper Trading).
* **Fase ativa:** `006-dashboard` (Task 6.2 concluída; próxima: Task 6.3).
* **Branch:** `main` | **Qualidade:** Suíte verde (`ruff`, `mypy --strict`, `pytest`).

## Em andamento
* Implementação da Fase 6 (`src/dashboard/`): seguindo Tasks 6.1–6.8 de `specs/006-dashboard/tasks.md`.

## Próximos passos
1. Task 6.3: Identidade visual CSS/Plotly (`src/dashboard/theme.py`) conforme `frontend-design` + testes.
2. Tasks 6.4–6.8: `DashboardService`, builders Plotly, Streamlit UI, integração e quality gate.

## Decisões ativas
* **Metodologia:** SDD estrito (tríade `spec.md`, `plan.md`, `tasks.md` antes de qualquer código).
* **Padrão de Qualidade:** Python 3.10+, `mypy --strict`, `ruff` e testes vinculados aos ACs (`test_acXX_...`).
* **Estratégia EMA:** 9/21 diário (`1d`), sinais `{0, 1}`, taxa B3 0,03%, warm-up recortado.
* **Risco (004):** R$ 100, risco estrito 2%/trade (`allow_min_lot_override=False`), Stop/Trailing 5% no fechamento (`Close -> t+1`), Swing Trade bloqueando saídas voluntárias em $D_0$, Kill-Switch (2% diário auto-reset / >500ms e 10% DD reset manual).
* **Execução (005):** `SimulatedPaperBroker` (B3 `'F'`, 0,03% fee, JSON atômico opcional) + `RestSandboxBroker` (stdlib `urllib`/HMAC), `liquidate_on_halt=True`, zero novas deps.

## Bloqueios
* Nenhum bloqueio ativo.

## Entregas concluídas (últimas 5)
1. **Fase 6 / Task 6.2 (Exceptions & Contracts):** Hierarquia `DashboardError` em `src/dashboard/exceptions.py` e contratos validados (`DashboardParameters`, `RiskTelemetrySnapshot`, `B3_PRESET_ASSETS`, etc.) em `models.py` + testes unitários.
2. **Fase 6 / Task 6.1 (Deps & Mypy):** `streamlit>=1.38.0` (`1.65.0`) e `plotly>=5.22.0` (`7.1.0`) adicionados em `requirements.txt`/instalados e `[mypy-plotly.*]` configurado em `mypy.ini`.
3. **Fase 5 / Task 5.6 (Runner, CLI & Exports):** `PaperTradingRunner`, `PaperSimulationReport` (ledger atômico JSON/Parquet) em `src/execution/runner.py`, entrypoint thin `sys.exit(1)` em `cli.py` e exports em `__init__.py` + 9 testes unitários.
4. **Fase 5 / Task 5.7 (Integração B3 Paper):** Testes end-to-end em `tests/integration/test_b3_paper_execution.py` com EMA 9/21 + `RiskManager` + `OrderRouter` + `SimulatedPaperBroker` (B3, R$ 100 e reload persistido) + 5 testes.
5. **Fase 5 / Task 5.8 (Fechamento Fase 005):** Quality gate final validado (`ruff`, `mypy --strict`, `271` testes, `94%` de cobertura), AC01–AC12 100% cobertos e Fase 5 concluída em `README.md`.

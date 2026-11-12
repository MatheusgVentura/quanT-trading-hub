# PROGRESS.md - Estado Atual e Rastreamento Dinâmico

Documento dinâmico contendo o estado atual, decisões ativas e próximos passos do projeto.

---

## Estado atual
* **Fases concluídas:** 000 (Setup/SDD), 001 (Data), 002 (Backtest), 003 (Strategy EMA).
* **Fase ativa:** 004 — Gestão de Risco e Disjuntor (`specs/004-risk-management/`), Tasks 4.1 a 4.6 concluídas.
* **Branch:** `main` | **Qualidade:** 135 testes passando (96% de cobertura), mypy strict e ruff 100%.

## Em andamento
* Implementação da Fase 4 (`src/risk/`). Próxima tarefa: Task 4.7 (`tests/integration/test_b3_risk_backtest.py`).

## Próximos passos
1. Executar Task 4.7: implementar testes de integração em `tests/integration/test_b3_risk_backtest.py` comparando EMA 9/21 baseline vs risk-managed nos 4 ativos B3 (`ITUB4.SA`, `PETR4.SA`, `VALE3.SA`, `WEGE3.SA`, `2021-11-01` a `2024-11-01`) + `PositionSizer` R$ 100.
2. Executar Task 4.8: quality gate final e fechamento da Fase 4.

## Decisões ativas
* **Metodologia:** SDD estrito (tríade `spec.md`, `plan.md`, `tasks.md` antes de qualquer código).
* **Padrão de Qualidade:** Python 3.10+, `mypy --strict`, `ruff` e testes vinculados aos ACs (`test_acXX_...`).
* **Estratégia EMA:** 9/21 diário (`1d`), sinais `{0, 1}`, taxa B3 0,03%, warm-up recortado.
* **Risco (004):** R$ 100, risco estrito 2%/trade (`allow_min_lot_override=False`), Stop/Trailing 5% no fechamento (`Close -> t+1`), Swing Trade bloqueando saídas voluntárias em $D_0$, Kill-Switch (2% diário auto-reset / >500ms e 10% DD reset manual).

## Bloqueios
* Nenhum bloqueio ativo.

## Entregas concluídas (últimas 5)
1. **Fase 4 / Task 4.2 (Risk Models):** `RiskStatus`, `HaltReason`, `RiskConfig`, `PositionSizeResult`, `KillSwitchState` e `RiskVerdict` + 33 testes unitários.
2. **Fase 4 / Task 4.3 (Position Sizing):** `PositionSizer` em `src/risk/sizing.py` (lotes B3, 0,03% fee, risco estrito 2%) + 23 testes unitários.
3. **Fase 4 / Task 4.4 (Stop Monitor):** `StopMonitor`, `StopCheckResult` e `StopTrigger` em `src/risk/stops.py` + 5 testes unitários.
4. **Fase 4 / Task 4.5 (Kill-Switch):** `KillSwitch` em `src/risk/kill_switch.py` (perda diária >= 2%, latência > 500ms, DD >= 10%, resets e escalonamento) + 5 testes unitários.
5. **Fase 4 / Task 4.6 (Risk Manager):** `RiskManager` e `apply_risk_overlay` em `src/risk/manager.py` (Swing Trade D0, stops, Kill-Switch, sizing e re-entry guard) + 7 testes unitários.

# PROGRESS.md - Estado Atual e Rastreamento Dinâmico

Documento dinâmico contendo o estado atual, decisões ativas e próximos passos do projeto.

---

## Estado atual
* **Fases concluídas:** 000 (Setup/SDD), 001 (Data), 002 (Backtest), 003 (Strategy EMA).
* **Fase ativa:** 004 — Gestão de Risco e Disjuntor (`specs/004-risk-management/`), Tasks 4.1 a 4.3 concluídas.
* **Branch:** `main` | **Qualidade:** 118 testes passando (95% de cobertura), mypy strict e ruff 100%.

## Em andamento
* Implementação da Fase 4 (`src/risk/`). Próxima tarefa: Task 4.4 (`stops.py`).

## Próximos passos
1. Executar Task 4.4: implementar `StopMonitor` em `src/risk/stops.py` (Stop-Loss fixo 5% e Trailing Stop 5% com high-water mark) + testes.
2. Seguir sequencialmente Tasks 4.5 a 4.8 de `specs/004-risk-management/tasks.md`.

## Decisões ativas
* **Metodologia:** SDD estrito (tríade `spec.md`, `plan.md`, `tasks.md` antes de qualquer código).
* **Padrão de Qualidade:** Python 3.10+, `mypy --strict`, `ruff` e testes vinculados aos ACs (`test_acXX_...`).
* **Estratégia EMA:** 9/21 diário (`1d`), sinais `{0, 1}`, taxa B3 0,03%, warm-up recortado.
* **Risco (004):** R$ 100, risco estrito 2%/trade (`allow_min_lot_override=False`), Stop/Trailing 5% no fechamento (`Close -> t+1`), Swing Trade bloqueando saídas voluntárias em $D_0$, Kill-Switch (2% diário auto-reset / >500ms e 10% DD reset manual).

## Bloqueios
* Nenhum bloqueio ativo.

## Entregas concluídas (últimas 5)
1. **Fase 2 (Backtest):** Engine vetorizada `src/backtest/` com métricas financeiras (`specs/002-vectorized-backtest/`).
2. **Fase 3 (Strategies):** `BaseStrategy`, `EMACrossoverStrategy` 9/21 e `StrategyBacktestRunner` nos 4 ativos B3 (`specs/003-strategy-layer/`).
3. **Fase 4 / Task 4.1 (Risk Exceptions):** Hierarquia tipada em `src/risk/exceptions.py` + 4 testes unitários.
4. **Fase 4 / Task 4.2 (Risk Models):** `RiskStatus`, `HaltReason`, `RiskConfig`, `PositionSizeResult`, `KillSwitchState` e `RiskVerdict` + 33 testes unitários.
5. **Fase 4 / Task 4.3 (Position Sizing):** `PositionSizer` em `src/risk/sizing.py` (lotes B3, 0,03% fee, risco estrito 2%) + 23 testes unitários.

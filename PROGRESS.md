# PROGRESS.md - Estado Atual e Rastreamento Dinâmico

Documento dinâmico contendo o estado atual, decisões ativas e próximos passos do projeto.

---

## Estado atual
* **Fases concluídas:** 000 (Setup/SDD), 001 (Data), 002 (Backtest), 003 (Strategy EMA).
* **Próxima fase:** 004 — Gestão de Risco e Disjuntor (`specs/004-risk-management/`).
* **Branch:** `main` | **Qualidade:** 58 testes passando (93% de cobertura), mypy strict e ruff 100%.

## Em andamento
* Nenhuma tarefa de código em andamento. Fase 3 concluída; aguardando início da spec da Fase 4.

## Próximos passos
1. Elaborar especificação da Fase 4 em `specs/004-risk-management/spec.md`, `plan.md` e `tasks.md`.
2. Apresentar premissas e dúvidas ao usuário e aguardar "aprovado".
3. Implementar módulo `src/risk/` via TDD (dimensionamento de posição, stops e kill-switch).

## Decisões ativas
* **Metodologia:** SDD estrito (tríade `spec.md`, `plan.md`, `tasks.md` antes de qualquer código).
* **Padrão de Qualidade:** Python 3.10+, `mypy --strict`, `ruff` e testes vinculados aos ACs (`test_acXX_...`).
* **Estratégia EMA:** 9/21 diário (`1d`), sinais discretos `{0, 1}` (Long/Caixa, sem short), taxa B3 0,03%, warm-up recortado.
* **Capital Base:** R$ 100 com modelagem de lote fracionário e fricção real (conforme PROJETO.md).

## Bloqueios
* Nenhum bloqueio ativo.

## Entregas concluídas (últimas 5)
1. **Fase 0 (Governança):** Setup de regras permanentes em AGENTS.md e PROGRESS.md.
2. **Fase 1 (Data):** Ingestão `src/data/`, cache Parquet e validação OHLCV (`specs/001-data-infrastructure/`).
3. **Fase 2 (Backtest):** Engine vetorizada `src/backtest/` com métricas financeiras (`specs/002-vectorized-backtest/`).
4. **Fase 3 (Strategy Base & EMA):** `BaseStrategy` e `EMACrossoverStrategy` (`specs/003-strategy-layer/`).
5. **Fase 3 (Runner & Validação B3):** `StrategyBacktestRunner` e validação nos 4 ativos B3 (ITUB4, PETR4, VALE3, WEGE3).

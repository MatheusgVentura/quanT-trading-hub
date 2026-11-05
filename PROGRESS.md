# PROGRESS.md - Estado Atual e Rastreamento Dinâmico

Documento dinâmico de sincronização com o estado atual, entregas recentes, bloqueios e próximos passos do projeto **quanT-trading-hub**.

---

## 1. Estado Atual
* **Fase Atual:** Fase 3 Concluída — Camada de Estratégias (`specs/003-strategy-layer/`). Próxima: Fase 4 (`specs/004-risk-management/`).
* **Branch Ativo:** `main`
* **Status Geral da Cobertura de Testes:** 58 testes passando (93% de cobertura global).
* **Bloqueios:** Nenhum.

---

## 2. Mapa de Fases do Projeto

| Código | Funcionalidade | Status |
| :--- | :--- | :--- |
| **000** | Setup de Governança, Regras e Stack Base | ✅ Concluído |
| **001** | Infraestrutura e Padronização de Dados de Mercado (`src/data/`) | ✅ Concluído (`specs/001-data-infrastructure/`) |
| **002** | Motor de Backtesting Vetorizado e Métricas (`src/backtest/`) | ✅ Concluído (`specs/002-vectorized-backtest/`) |
| **003** | Camada Base de Estratégias e Estratégia EMA (`src/strategies/`) | ✅ Concluído (`specs/003-strategy-layer/`) |
| **004** | Gestão de Risco e Disjuntor Operacional (`src/risk/`) | ⏳ Pendente de Especificação |
| **005** | Execução e Sandbox / Paper Trading (`src/execution/`) | ⏳ Pendente |
| **006** | Dashboard Web Interativo (Streamlit / Plotly) | ⏳ Pendente |

---

## 3. Log de Decisões e Entregas Recentes

### [05/11/2026] - Setup e Baseline Inicial
* Implementado módulo de ingestão `src/data/` com cache Parquet e validação física OHLCV.
* Implementada engine `src/backtest/` com métricas quantitativas institucionais e proteção contra *look-ahead bias*.

### [05/11/2026] - Adoção da Nova Governança SDD e Reestruturação
* Divisão estrita de papéis: `AGENTS.md` (somente regras estáveis) e `PROGRESS.md` (progresso e estado volátil).
* `CLAUDE.md` reduzido a `@AGENTS.md` para suportar uso eventual do Claude Code.
* Migração formal para tríades em inglês: `specs/001-data-infrastructure/` e `specs/002-vectorized-backtest/`.
* Remoção dos arquivos monolíticos obsoletos (`specs/01_...` e `specs/02_...`).

### [05/11/2026] - Conclusão da ETAPA 3: Qualidade Estrita
* `mypy --strict src tests`: 100% tipado (0 erros em 21 arquivos).
* `ruff check .` e `ruff format --check .`: 100% aprovado (0 avisos).
* `pytest --cov=src -v`: 28 testes passando com 90% de cobertura.

### [05/11/2026] - Fase 3 / Conclusão Completa (Tasks 3.1 a 3.6): Camada de Estratégias e EMA Crossover
* Implementada `EMACrossoverStrategy` com validação $fast \ge 2, slow > fast$, `min_periods=slow_period` e sinais binários $\{0, 1\}$.
* Implementado `StrategyBacktestRunner` e `StrategyComparisonReport` com recorte mandatório de warm-up e relatório dual (Líquido B3 vs Bruto).
* Execução e validação completa no universo B3 fixo (`ITUB4.SA`, `PETR4.SA`, `VALE3.SA`, `WEGE3.SA`) no período 2021-2024.
* 58 testes passando (93% de cobertura global), 100% tipagem estrita no `mypy` e 0 erros no `ruff`.

---

## 4. Próximos Passos Imediatos
1. Iniciar elaboração da Spec da Fase 4 (`specs/004-risk-management/spec.md`) cobrindo:
   - Dimensionamento de posição (Fixed Fractional / Risco R$ 100).
   - Stop-Loss e Trailing Stop.
   - Disjuntor Operacional / Kill-Switch (Max Drawdown diário e semanal).
2. Apresentar premissas e dúvidas ao usuário e aguardar aprovação explícita.

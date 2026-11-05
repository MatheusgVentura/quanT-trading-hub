# PROGRESS.md - Estado Atual e Rastreamento Dinâmico

Documento dinâmico de sincronização com o estado atual, entregas recentes, bloqueios e próximos passos do projeto **quanT-trading-hub**.

---

## 1. Estado Atual
* **Fase Atual:** Fase 3 — Camada de Estratégias (`specs/003-strategy-layer/`). Task 3.1 concluída.
* **Branch Ativo:** `main`
* **Status Geral da Cobertura de Testes:** 31 testes passando (90% de cobertura global).
* **Bloqueios:** Nenhum.

---

## 2. Mapa de Fases do Projeto

| Código | Funcionalidade | Status |
| :--- | :--- | :--- |
| **000** | Setup de Governança, Regras e Stack Base | ✅ Concluído |
| **001** | Infraestrutura e Padronização de Dados de Mercado (`src/data/`) | ✅ Concluído (`specs/001-data-infrastructure/`) |
| **002** | Motor de Backtesting Vetorizado e Métricas (`src/backtest/`) | ✅ Concluído (`specs/002-vectorized-backtest/`) |
| **003** | Camada Base de Estratégias e Estratégia EMA (`src/strategies/`) | 🔄 Em Implementação (Task 3.1 concluída) |
| **004** | Gestão de Risco e Disjuntor Operacional (`src/risk/`) | ⏳ Pendente |
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

### [05/11/2026] - Fase 3 / Task 3.1: Exceções de Estratégia
* Implementada hierarquia `StrategyError`, `InvalidParameterError`, `InsufficientDataError`.
* Testes derivados de AC08, AC09, AC12 passando com 100% de sucesso. Cobertura: 90%.

---

## 4. Próximos Passos Imediatos
1. Implementar Task 3.2: Contrato abstrato `BaseStrategy` em `src/strategies/base.py` *(AC06, AC07)*.
2. Implementar Task 3.3: `EMACrossoverStrategy` em `src/strategies/ema_crossover.py` *(AC01, AC02, AC08-AC12)*.
3. Implementar testes unitários completos em `tests/unit/test_strategies/test_ema_crossover.py`.

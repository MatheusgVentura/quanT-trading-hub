# PROGRESS.md - Estado Atual e Rastreamento Dinâmico

Documento dinâmico de sincronização com o estado atual, entregas recentes, bloqueios e próximos passos do projeto **quanT-trading-hub**.

---

## 1. Estado Atual
* **Fase Atual:** Fase 3 — Camada de Estratégias (`specs/003-strategy-layer/`). Task 3.2 concluída.
* **Branch Ativo:** `main`
* **Status Geral da Cobertura de Testes:** 34 testes passando (91% de cobertura global).
* **Bloqueios:** Nenhum.

---

## 2. Mapa de Fases do Projeto

| Código | Funcionalidade | Status |
| :--- | :--- | :--- |
| **000** | Setup de Governança, Regras e Stack Base | ✅ Concluído |
| **001** | Infraestrutura e Padronização de Dados de Mercado (`src/data/`) | ✅ Concluído (`specs/001-data-infrastructure/`) |
| **002** | Motor de Backtesting Vetorizado e Métricas (`src/backtest/`) | ✅ Concluído (`specs/002-vectorized-backtest/`) |
| **003** | Camada Base de Estratégias e Estratégia EMA (`src/strategies/`) | 🔄 Em Implementação (Tasks 3.1 e 3.2 concluídas) |
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

### [05/11/2026] - Fase 3 / Tasks 3.1 e 3.2: Camada de Estratégias
* Implementada hierarquia `StrategyError`, `InvalidParameterError`, `InsufficientDataError`.
* Implementado contrato base abstrato `BaseStrategy` e testes derivados de AC06, AC07, AC08, AC09, AC12. Cobertura: 91%.

---

## 4. Próximos Passos Imediatos
1. Implementar Task 3.3: `EMACrossoverStrategy` em `src/strategies/ema_crossover.py` *(AC01, AC02, AC08-AC12)*.
2. Implementar testes unitários para a estratégia em `tests/unit/test_strategies/test_ema_crossover.py`.
3. Implementar Task 3.5: Validação da estratégia com os 4 ativos B3 e recorte de warm-up.

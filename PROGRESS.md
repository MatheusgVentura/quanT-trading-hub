# PROGRESS.md - Estado Atual e Rastreamento Dinâmico

Documento dinâmico de sincronização com o estado atual, entregas recentes, bloqueios e próximos passos do projeto **quanT-trading-hub**.

---

## 1. Estado Atual
* **Fase Atual:** Fase 3 — Camada de Estratégias (`specs/003-strategy-layer/`). Tasks 3.1 a 3.4 concluídas.
* **Branch Ativo:** `main`
* **Status Geral da Cobertura de Testes:** 50 testes passando (91% de cobertura global).
* **Bloqueios:** Nenhum.

---

## 2. Mapa de Fases do Projeto

| Código | Funcionalidade | Status |
| :--- | :--- | :--- |
| **000** | Setup de Governança, Regras e Stack Base | ✅ Concluído |
| **001** | Infraestrutura e Padronização de Dados de Mercado (`src/data/`) | ✅ Concluído (`specs/001-data-infrastructure/`) |
| **002** | Motor de Backtesting Vetorizado e Métricas (`src/backtest/`) | ✅ Concluído (`specs/002-vectorized-backtest/`) |
| **003** | Camada Base de Estratégias e Estratégia EMA (`src/strategies/`) | 🔄 Em Implementação (Tasks 3.1 a 3.4 concluídas) |
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

### [05/11/2026] - Fase 3 / Tasks 3.1 a 3.4: Implementação da Estratégia EMA Crossover
* Implementada `EMACrossoverStrategy` com validação $fast \ge 2, slow > fast$, `min_periods=slow_period` e sinais binários $\{0, 1\}$.
* Cobertura de 100% em `src/strategies/ema_crossover.py` e 50 testes passando em toda a suíte.

---

## 4. Próximos Passos Imediatos
1. Implementar Task 3.5: Backtest runner / testes de integração comparando os 4 ativos B3 (`ITUB4.SA`, `PETR4.SA`, `VALE3.SA`, `WEGE3.SA`) com e sem taxas B3 (0,03%) e recorte de warm-up *(AC03, AC04, AC05, AC13)*.
2. Executar Task 3.6: Validação completa de qualidade (`ruff`, `mypy --strict`, `pytest`).

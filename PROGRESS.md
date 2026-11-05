# PROGRESS.md - Estado Atual e Rastreamento Dinâmico

Documento dinâmico de sincronização com o estado atual, entregas recentes, bloqueios e próximos passos do projeto **quanT-trading-hub**.

---

## 1. Estado Atual
* **Fase Atual:** ETAPA 4 — Especificação Técnica da Fase 3 elaborada (`specs/003-strategy-layer/`). Aguardando aprovação explícita.
* **Branch Ativo:** `main`
* **Status Geral da Cobertura de Testes:** 28 testes passando (90% de cobertura global).
* **Bloqueios:** Nenhum.

---

## 2. Mapa de Fases do Projeto

| Código | Funcionalidade | Status |
| :--- | :--- | :--- |
| **000** | Setup de Governança, Regras e Stack Base | ✅ Concluído |
| **001** | Infraestrutura e Padronização de Dados de Mercado (`src/data/`) | ✅ Concluído (`specs/001-data-infrastructure/`) |
| **002** | Motor de Backtesting Vetorizado e Métricas (`src/backtest/`) | ✅ Concluído (`specs/002-vectorized-backtest/`) |
| **003** | Camada Base de Estratégias e Estratégia EMA (`src/strategies/`) | 🟡 Spec em Revisão (`specs/003-strategy-layer/`) |
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

---

## 4. Próximos Passos Imediatos
1. Apresentar os resultados da ETAPA 3 e obter alinhamento do usuário.
2. Executar ETAPA 4: Elaborar a Especificação Técnica formal da Fase 3 (`specs/003-strategy-layer/spec.md`, `plan.md`, `tasks.md`) sem escrever código funcional.
3. Aguardar aprovação explícita ("aprovado") da spec 003 antes de qualquer implementação.

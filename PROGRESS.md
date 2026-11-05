# PROGRESS.md - Estado Atual e Rastreamento Dinâmico

Documento dinâmico de sincronização com o estado atual, entregas recentes, bloqueios e próximos passos do projeto **quanT-trading-hub**.

---

## 1. Estado Atual
* **Fase Atual:** ETAPA 2 — Migração Retroativa para o Padrão SDD Formal.
* **Branch Ativo:** `chore/sdd-migration`
* **Status Geral da Cobertura de Testes:** 28 testes passando (90% de cobertura global).
* **Bloqueios:** Nenhum no momento.

---

## 2. Mapa de Fases do Projeto

| Código | Funcionalidade | Status |
| :--- | :--- | :--- |
| **000** | Setup de Governança, Regras e Stack Base | ✅ Concluído |
| **001** | Infraestrutura e Padronização de Dados de Mercado (`src/data/`) | 🔄 Migração para `specs/001-data-infrastructure/` |
| **002** | Motor de Backtesting Vetorizado e Métricas (`src/backtest/`) | 🔄 Migração para `specs/002-vectorized-backtest/` |
| **003** | Camada Base de Estratégias e Estratégia EMA (`src/strategies/`) | ⏳ Pendente (Aguardando Spec) |
| **004** | Gestão de Risco e Disjuntor Operacional (`src/risk/`) | ⏳ Pendente |
| **005** | Execução e Sandbox / Paper Trading (`src/execution/`) | ⏳ Pendente |
| **006** | Dashboard Web Interativo (Streamlit / Plotly) | ⏳ Pendente |

---

## 3. Log de Decisões e Entregas Recentes

### [05/11/2026] - Setup e Baseline Inicial
* Implementado módulo de ingestão `src/data/` com cache Parquet e validação física OHLCV.
* Implementada engine `src/backtest/` com métricas quantitativas institucionais e proteção contra *look-ahead bias*.
* **Baseline medido na auditoria:**
  * `pytest`: 28 testes passando (100%).
  * `mypy --strict`: 31 erros de anotação de retorno em arquivos de teste.
  * `ruff check`: 47 avisos de import/formatação.

### [05/11/2026] - Adoção da Nova Governança SDD
* Divisão estrita de papéis: `AGENTS.md` (somente regras estáveis) e `PROGRESS.md` (progresso e estado volátil).
* `CLAUDE.md` reduzido a `@AGENTS.md` para suportar uso eventual do Claude Code.
* Migração das especificações monolíticas para a estrutura de tríade em inglês: `specs/<NNN-nome>/spec.md`, `plan.md`, `tasks.md`.

---

## 4. Próximos Passos Imediatos
1. Finalizar criação das specs retroativas `001-data-infrastructure` e `002-vectorized-backtest`.
2. Reportar divergências encontradas entre specs originais e código implementado.
3. Obter aprovação do usuário para concluir a ETAPA 2.
4. Executar ETAPA 3: ajustar tipagem estrita nos testes (`mypy --strict`) e formatação (`ruff check --fix` e manual).
5. Executar ETAPA 4: elaborar a especificação formal `specs/003-strategy-layer/`.

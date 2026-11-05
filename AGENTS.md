# AGENTS.md - Estado do Projeto, Progresso e Próximos Passos

Documento de sincronização e controle de estado para agentes e desenvolvedores do repositório **quanT-trading-hub**.

---

## 1. Visão Geral do Projeto
* **Objetivo:** Criação de um hub quantitativo modular em Python para engenharia de bots de trading, motor de backtesting com custos da B3, gerenciamento de risco e execução em sandbox/paper trading.
* **Metodologia:** Spec-Driven Development (SDD).
* **Fase Atual:** Fase 3 — Especificação Técnica da Interface Base de Estratégias e Estratégia EMA (`src/strategies/`).

---

## 2. Mapa de Fases e Backlog

| Fase | Descrição | Status |
| :--- | :--- | :--- |
| **Fase 0** | Definição de regras (SDD), inicialização de `CLAUDE.md`, `AGENTS.md` e ambiente base | ✅ Concluído |
| **Fase 1** | Especificação Técnica e Implementação do Módulo de Dados (`src/data/`) | ✅ Concluído |
| **Fase 2** | Especificação Técnica e Implementação do Motor de Backtest Vetorizado (`src/backtest/`) | ✅ Concluído |
| **Fase 3** | Especificação Técnica e Implementação da Interface Base de Estratégias e Estratégia EMA | 🟡 Especificação em Elaboração |
| **Fase 4** | Especificação Técnica e Implementação do Módulo de Gestão de Risco (`src/risk/`) | ⏳ Pendente |
| **Fase 5** | Especificação Técnica e Implementação de Paper Trading / Execução em Sandbox (`src/execution/`) | ⏳ Pendente |
| **Fase 6** | Dashboard Interativo Web (Streamlit / Plotly) | ⏳ Pendente |

---

## 3. Log de Entregas e Decisões Técnicas

### [05/11/2026] - Setup Inicial de Governança
* **Decisão:** Adoção estrita da metodologia Spec-Driven Development (SDD).
* **Ações Realizadas:**
  * Criação do [CLAUDE.md](file:///c:/Users/Matheus%20Ventura/personal/quanT-trading-hub/CLAUDE.md) com diretrizes de arquitetura, stack (Python 3.10) e comandos úteis.
  * Criação do [AGENTS.md](file:///c:/Users/Matheus%20Ventura/personal/quanT-trading-hub/AGENTS.md) com roadmap e rastreamento de entregas.
  * Validação das versões de Python disponíveis no host (Python 3.10 e 3.14 detectados).

### [05/11/2026] - Conclusão da Fase 1: Módulo de Infraestrutura de Dados (`src/data/`)
* **Especificação:** [01_data_infrastructure.md](file:///c:/Users/Matheus%20Ventura/personal/quanT-trading-hub/specs/01_data_infrastructure.md) aprovada pelo usuário.
* **Componentes Implementados:**
  * `src/data/exceptions.py`: Hierarquia de exceções (`DataError`, `DataDownloadError`, `DataValidationError`, `TickerNotFoundError`).
  * `src/data/interfaces.py`: Contrato formal `IDataProvider` para desacoplamento de fontes de dados.
  * `src/data/validator.py`: Quality gate `OHLCVValidator` com checagem de tipos, colunas, física de preços ($High \ge Low$, $Close > 0$) e volume não-negativo.
  * `src/data/cache.py`: `DataCacheManager` baseado em Parquet e TTL para otimização de requisições.
  * `src/data/yfinance_provider.py`: Implementação concreta para Yahoo Finance com suporte a ativos B3 (`.SA`).
* **Qualidade e Testes:**
  * 16 testes unitários com mocks passando com 100% de sucesso.
  * Cobertura de testes do módulo `src/data/`: 88% (acima da meta de 85%).
  * Checagem de tipagem estática `mypy src`: 0 erros.
  * Smoke test executado em produção com dados reais de `ITUB4.SA`.

### [05/11/2026] - Conclusão da Fase 2: Motor de Backtesting Vetorizado (`src/backtest/`)
* **Especificação:** [02_vectorized_backtest_engine.md](file:///c:/Users/Matheus%20Ventura/personal/quanT-trading-hub/specs/02_vectorized_backtest_engine.md) aprovada pelo usuário.
* **Componentes Implementados:**
  * `src/backtest/models.py`: Modelos imutáveis `BacktestConfig`, `BacktestMetrics` e `BacktestResult` com relatório institucional via `summary()`.
  * `src/backtest/exceptions.py`: Exceções de simulação (`BacktestError`, `MismatchedIndexError`, `InvalidSignalError`).
  * `src/backtest/metrics.py`: `MetricsCalculator` estático e puro para cálculo de Sharpe, Sortino, CAGR, Max Drawdown, Profit Factor e Win Rate.
  * `src/backtest/engine.py`: `VectorizedBacktestEngine` com proteção mandatória contra *Look-Ahead Bias* (`.shift(1)`), cálculo de fricção B3 (~0,03% por giro) e retornos líquidos.
* **Qualidade e Testes:**
  * 28 testes unitários passando com 100% de sucesso (12 novos testes em `tests/unit/test_backtest/`).
  * Cobertura de testes global: 90% (acima da meta de 85%).
  * Tipagem estática `mypy src`: 0 erros em 12 arquivos.
  * Teste end-to-end de integração executado com sucesso cruzando `YFinanceDataProvider` com a engine em dados de 2 anos de `ITUB4.SA`.

---

## 4. Próximos Passos Imediatos
1. Elaborar a **Especificação Técnica da Fase 3 (Interface Base de Estratégias e Estratégia EMA Cross em `src/strategies/`)**.
2. Apresentar a especificação ao usuário para alinhamento e aprovação prévia.
3. Após aprovação, implementar os testes e os módulos de `src/strategies/`.


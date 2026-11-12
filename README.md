# quanT-trading-hub 📈 🤖

Hub quantitativo modular em Python para engenharia de bots de trading, motor de backtesting com fricção e taxas da B3, gerenciamento de risco e execução em sandbox/paper trading.

Construído com base na metodologia **Spec-Driven Development (SDD)** e arquitetura de software limpa (*Clean Architecture* / desacoplamento por contratos).

---

## 📌 Visão Geral da Arquitetura

O projeto divide-se em pipelines desacoplados para garantir que estratégias, dados, risco e execução funcionem de forma modular e independente:

```
┌─────────────────────────────────┐
│     1. Módulo de Dados          │ ── Ingestão, sanitização OHLCV e cache Parquet
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│     2. Motor de Backtest        │ ── Simulação sem look-ahead bias e custos B3
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│     3. Gestão de Risco          │ ── Sizing, disjuntores (Kill-Switch) e limites
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│     4. Execução / Sandbox       │ ── Roteador de ordens (Paper Trading -> Real)
└─────────────────────────────────┘
```

---

## 🚀 Funcionalidades Principais

* **Ingestão e Validação Rigorosa de Dados (`src/data/`):**
  * Suporte nativo a ativos da B3 (ex: `ITUB4.SA`, `PETR4.SA`) via Yahoo Finance.
  * Quality gate de dados (`OHLCVValidator`): checagem de tipos, colunas, física de preços ($High \ge Low$, $Close > 0$) e volume não-negativo.
  * Cache local determinístico em **Parquet** com suporte a TTL (tempo de expiração).
  * Desacoplamento via interface formal (`IDataProvider`).
* **Motor de Backtesting Institucional (`src/backtest/`):**
  * Proteção nativa contra *Look-Ahead Bias* (`.shift(1)`).
  * Desconto realístico de custos da B3 (emolumentos e taxa de liquidação ~0,03% por giro).
  * Métricas quantitativas completas: CAGR, Sharpe Ratio, Volatilidade Anualizada, Max Drawdown e Profit Factor.
* **Governança com Spec-Driven Development (SDD):**
  * Especificações técnicas documentadas em [`specs/`](specs/) antes da implementação de código.
  * Testes unitários com Mocks e cobertura mínima de 85%.
  * Tipagem estática rigorosa com `mypy`.

---

## 🛠️ Stack Tecnológica

* **Linguagem:** Python 3.10+
* **Manipulação de Séries Temporais:** `pandas`, `numpy`
* **Persistência de Dados:** `pyarrow` (Parquet)
* **Coleta de Mercado:** `yfinance`
* **Qualidade e Testes:** `pytest`, `pytest-cov`, `mypy`

---

## 💻 Instalação e Execução

### 1. Clonar o repositório
```bash
git clone https://github.com/MatheusgVentura/quanT-trading-hub.git
cd quanT-trading-hub
```

### 2. Configurar o ambiente virtual
```powershell
# Windows (PowerShell)
py -3.10 -m venv venv
.\venv\Scripts\Activate.ps1
```

### 3. Instalar as dependências
```bash
pip install -r requirements.txt
```

### 4. Configurar variáveis de ambiente (Opcional)
```bash
cp .env.example .env
```

---

## 🧪 Executando os Testes e Validações

```powershell
# Executar a suíte de testes unitários com cobertura
pytest --cov=src --cov-report=term-missing

# Checagem de tipagem estática
mypy src
```

---

## 🗺️ Roadmap de Desenvolvimento

- [x] **Fase 0:** Setup de Governança (SDD, `CLAUDE.md`, `AGENTS.md`)
- [x] **Fase 1:** Módulo de Infraestrutura de Dados e Validação (`src/data/`)
- [x] **Fase 2:** Motor de Backtesting Vetorizado e Métricas de Risco (`src/backtest/`)
- [x] **Fase 3:** Interface de Estratégias e Estratégia de Médias Móveis (`src/strategies/`)
- [x] **Fase 4:** Gestão de Risco e Kill-Switch (`src/risk/`)
- [ ] **Fase 5:** Paper Trading e Execução em Sandbox (`src/execution/`) — *Em andamento (Tasks 5.1–5.2 concluídas)*
- [ ] **Fase 6:** Dashboard Interativo Web (Streamlit / Plotly)

---

## 📜 Licença

Distribuído sob a licença MIT. Veja `LICENSE` para mais informações.

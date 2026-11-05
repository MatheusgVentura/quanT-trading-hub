# CLAUDE.md - Diretrizes do Projeto e Comandos Úteis

Este documento define as regras de desenvolvimento, padrões de arquitetura e comandos essenciais para o repositório **quanT-trading-hub**.

---

## 1. Metodologia: Spec-Driven Development (SDD)

1. **Especificação Obrigatória Antes de Código:**
   * Nenhuma funcionalidade de código deve ser escrita sem uma especificação técnica prévia documentada e alinhada com o usuário.
   * O fluxo é: **Especificação Técnica -> Alinhamento/Aprovação -> Implementação dos Testes/Código -> Atualização de AGENTS.md / CLAUDE.md**.
2. **Documentação Viva:**
   * `CLAUDE.md`: Regras de negócio, convenções técnicas, ferramentas e comandos úteis.
   * `AGENTS.md`: Progresso atual, log de entregas, dívidas técnicas e próximos passos.
3. **Padrões de Engenharia de Software:**
   * Código 100% modular, desacoplado (Clean Architecture / Ports & Adapters) e tipado (`typing`).
   * Test-Driven Development (TDD) incentivado para regras de negócio e cálculo de métricas.
   * Tratamento defensivo de exceções e tolerância a falhas.

---

## 2. Stack Tecnológica e Ferramental

* **Linguagem:** Python 3.10 (recomendado para máxima estabilidade com bibliotecas numéricas)
* **Bibliotecas Centrais:**
  * Dados e Matrizes: `pandas`, `numpy`
  * Coleta de Dados: `yfinance`
  * Visualização: `matplotlib`, `seaborn`
  * Testes e Qualidade: `pytest`, `pytest-cov`, `flake8`, `mypy`, `black`
* **Ambiente de Teste / Sandbox:** APIs de Paper Trading (Binance Testnet / Alpaca)

---

## 3. Comandos Úteis (PowerShell / Windows)

### 3.1 Ambiente Virtual
```powershell
# Criação do venv com Python 3.10
py -3.10 -m venv venv

# Ativação do ambiente virtual
.\venv\Scripts\Activate.ps1
```

### 3.2 Dependências
```powershell
# Atualização do pip
python -m pip install --upgrade pip

# Instalação das dependências do projeto
pip install -r requirements.txt
```

### 3.3 Testes e Validação
```powershell
# Executar todos os testes
pytest

# Executar testes com cobertura
pytest --cov=src --cov-report=term-missing

# Checagem de tipagem estática
mypy src

# Formatação e linting
black src tests
flake8 src tests
```

---

## 4. Padrões de Código e Arquitetura

* **Separação de Camadas:**
  * `src/data/`: Ingestão, limpeza e normalização de dados históricos e em tempo real.
  * `src/strategies/`: Estratégias puras que recebem dados e emitem sinais (-1, 0, 1). Sem chamadas de API externas.
  * `src/risk/`: Dimensionamento de posição, stop loss, take profit e kill-switch.
  * `src/backtest/`: Simulação vetorizada e baseada em eventos, cálculo de fricção (emolumentos B3) e métricas (Sharpe, Drawdown, CAGR).
  * `src/execution/`: Adaptadores de envio e controle de ordens (Paper Trading / Corretora).
* **Tipagem Estrita:** Uso de `typing` (`Optional`, `Union`, `List`, `Dict`, `Callable`, `dataclass` ou `Pydantic`).
* **Proteção Quantitativa:** Prevenção ativa contra *Look-Ahead Bias* (uso de `.shift(1)`) e *Overfitting*.


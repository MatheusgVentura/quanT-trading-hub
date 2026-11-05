# Especificação Técnica 02: Motor de Backtest Vetorizado e Métricas de Risco/Retorno (`src/backtest/`)

**Status:** 🟡 Proposta / Aguardando Alinhamento do Usuário  
**Data:** 05/11/2026  
**Autor:** Antigravity & Matheus Ventura  
**Fase:** 2  

---

## 1. Visão Geral e Motivação

O objetivo da Fase 2 é transformar a lógica de simulação do `engine_quant_xp.py` (descrita no manual `PROJETO.md`) em um **motor de backtest vetorizado desacoplado, modular e com rigor estatístico**.

O motor deve simular com precisão a performance de qualquer estratégia quantitativa em séries temporais de preços, descontando os custos operacionais da bolsa brasileira (B3) e blindando o desenvolvedor contra **Look-Ahead Bias** (viés de espiar o futuro). Além disso, deve computar métricas quantitativas institucionais (Sharpe, Sortino, CAGR, Max Drawdown, Profit Factor e Win Rate) e produzir relatórios analíticos limpos.

---

## 2. Requisitos Funcionais (RF)

* **RF01 - Execução de Simulação Vetorizada:** Receber um DataFrame OHLCV validado (`src/data/`) e uma série temporal de sinais/posições gerada por qualquer estratégia, calculando os retornos acumulados de forma vetorizada com alta performance (NumPy / Pandas).
* **RF02 - Proteção Inegociável contra Look-Ahead Bias:**
  * O sinal calculado no fechamento da barra $t$ **só pode ser executado e gerar retorno a partir da abertura ou do dia $t+1$** (aplicação mandatória de `.shift(1)` no cálculo de exposição).
* **RF03 - Modelagem de Fricção e Custos B3:**
  * Desconto configurável de custos operacionais (emolumentos + taxa de liquidação da B3, default: `0.03%` = `0.0003` por transação).
  * Suporte a taxa de corretagem fixa por ordem (default: `R$ 0,00`, refletindo o RLP ativo na XP).
  * Suporte a slippage percentual configurável (derrapagem de spread na execução).
  * O custo deve ser debitado estritamente nos momentos de transição de posição ($|Posição_t - Posição_{t-1}| > 0$).
* **RF04 - Cálculo de Métricas Quantitativas Institucionais:**
  * **Retorno Total Acumulado:** Variação patrimonial total da estratégia vs *Buy & Hold* do ativo de referência.
  * **CAGR (Compound Annual Growth Rate):** Retorno anualizado composto considerando 252 dias úteis por ano.
  * **Volatilidade Anualizada:** Desvio padrão dos retornos diários multiplicado por $\sqrt{252}$.
  * **Sharpe Ratio Anualizado:** Razão entre o excesso de retorno sobre a taxa livre de risco (Selic/CDI configurável) e a volatilidade.
  * **Sortino Ratio Anualizado:** Avalia o retorno penalizando apenas a volatilidade dos retornos negativos (*downside deviation*).
  * **Max Drawdown (MDD) e Série Subaquática:** Maior percentual de perda do pico histórico até o fundo e série diária de queda.
  * **Profit Factor:** Razão entre a soma dos retornos brutos positivos e a soma absoluta dos retornos negativos ($\sum Lucros / |\sum Perdas|$).
  * **Win Rate (%):** Percentual de dias ou trades com resultado líquido positivo.
  * **Giro de Carteira (Total Trades):** Contagem total de transações de entrada e saída executadas.
* **RF05 - Formatação de Resultados e Relatório:**
  * Retorno de um objeto estruturado `BacktestResult` contendo:
    * `metrics`: Dataclass `BacktestMetrics` fortemente tipada.
    * `equity_curve`: DataFrame detalhado com `[Curva_Estrategia, Curva_Benchmark, Drawdown, Posicao, Retorno_Liquido]`.
    * `summary()`: Método que formata um relatório textual profissional em português pronto para console ou logs.

---

## 3. Requisitos Não Funcionais (RNF)

* **RNF01 - Tipagem Estrita:** 100% do código tipado (`typing`), validado sem avisos no `mypy src`.
* **RNF02 - Cobertura de Testes Unitários:** Mínimo de 85% de cobertura com `pytest`, cobrindo casos de borda matemáticos (estratégia sempre comprada, sempre líquida, alternada, sem trades e ativos com retorno negativo constante).
* **RNF03 - Desempenho Computacional:** Simulação de 10 anos de candles diários e cálculo de todas as métricas em menos de 50 milissegundos.
* **RNF04 - Imutabilidade e Pureza:** O motor de backtest não deve mutar os DataFrames de entrada; sempre operar sobre cópias ou retornar novos objetos.

---

## 4. Arquitetura e Contratos de Classes

### 4.1 Estrutura de Pastas Proposta

```text
src/
├── backtest/
│   ├── __init__.py
│   ├── exceptions.py          # BacktestError, MismatchedIndexError, InvalidSignalError
│   ├── models.py              # BacktestConfig, BacktestMetrics, BacktestResult
│   ├── metrics.py             # Calculadora de métricas de risco e retorno
│   └── engine.py              # VectorizedBacktestEngine
```

### 4.2 Definição dos Modelos e Interfaces

#### `src/backtest/models.py`
```python
from dataclasses import dataclass
from typing import Optional
import pandas as pd

@dataclass(frozen=True)
class BacktestConfig:
    """Configurações e parâmetros para a simulação do backtest."""
    initial_capital: float = 100.0
    b3_fee_pct: float = 0.0003          # 0.03% (emolumentos + liquidação B3)
    brokerage_fee: float = 0.0          # R$ 0.00 (corretagem zero XP via RLP)
    slippage_pct: float = 0.0           # Derrapagem percentual por trade
    risk_free_rate: float = 0.1075      # 10.75% a.a. (Taxa livre de risco / Selic de referência)
    trading_days_per_year: int = 252

@dataclass(frozen=True)
class BacktestMetrics:
    """Métricas estatísticas quantitativas resultantes do backtest."""
    total_return_pct: float
    benchmark_return_pct: float
    cagr_pct: float
    annualized_volatility_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    profit_factor: float
    win_rate_pct: float
    total_trades: int
    trading_days: int

@dataclass
class BacktestResult:
    """Resultado consolidado do backtest contendo métricas e curva de capital."""
    ticker: str
    config: BacktestConfig
    metrics: BacktestMetrics
    equity_curve: pd.DataFrame

    def summary(self) -> str:
        """Gera relatório institucional formatado em texto."""
        pass
```

#### `src/backtest/metrics.py`
```python
class MetricsCalculator:
    """Calculadora puramente estática e vetorizada de métricas financeiras."""

    @staticmethod
    def calculate_metrics(
        equity_curve: pd.Series,
        strategy_returns: pd.Series,
        benchmark_returns: pd.Series,
        position_changes: pd.Series,
        config: BacktestConfig,
    ) -> BacktestMetrics:
        # Cálculo vetorizado de CAGR, Volatilidade, Sharpe, Sortino, Drawdown, Profit Factor
        pass
```

#### `src/backtest/engine.py`
```python
class VectorizedBacktestEngine:
    """Motor de backtesting vetorizado."""

    def __init__(self, config: Optional[BacktestConfig] = None):
        self.config = config or BacktestConfig()

    def run(
        self,
        ohlcv_df: pd.DataFrame,
        signals: pd.Series,
        ticker: str = "ATIVO",
    ) -> BacktestResult:
        """
        Executa o backtest vetorizado:
        1. Valida alinhamento entre ohlcv_df e signals
        2. Aplica shift(1) para proteção contra Look-Ahead Bias
        3. Calcula transições de posição e custos B3 + corretagem + slippage
        4. Calcula retornos líquidos e curvas de capital acumuladas
        5. Computa métricas quantitativas via MetricsCalculator
        6. Retorna BacktestResult
        """
        pass
```

---

## 5. Plano de Testes Unitários (`tests/unit/test_backtest/`)

1. **`test_look_ahead_bias_shift`:**
   * Garantir matematicamente que o sinal emitido na data $T$ afeta apenas o retorno na data $T+1$.
2. **`test_b3_costs_application`:**
   * Validar que os custos são deduzidos rigorosamente nas transições de posição ($0 \to 1$ ou $1 \to 0$) e que dias com posição constante não pagam taxas.
3. **`test_benchmark_buy_and_hold_alignment`:**
   * Validar que se a posição for $1$ do início ao fim (sem custos adicionais de giro), o retorno da estratégia espelha o retorno do benchmark.
4. **`test_all_cash_strategy`:**
   * Validar que quando o sinal é sempre $0$ (100% líquido em caixa), o retorno da estratégia é exatamente $0\%$, sem drawdown e com zero trades.
5. **`test_sharpe_and_sortino_formulas`:**
   * Validar o cálculo com séries artificiais de retornos conhecidos e checar se `Sortino >= Sharpe` em cenários com retornos positivos.
6. **`test_max_drawdown_calculation`:**
   * Testar cálculo de queda subaquática com uma série com pico conhecido e verificar se o valor máximo de Drawdown corresponde à maior queda percentual pico-a-fundo.
7. **`test_index_mismatch_raises_error`:**
   * Testar se sinais com índices de datas diferentes do DataFrame de preços levantam `MismatchedIndexError`.

---

## 6. Critérios de Aceite para Aprovação

- [ ] A separação entre `BacktestConfig`, `BacktestMetrics`, `MetricsCalculator` e `VectorizedBacktestEngine` está clara e aderente à Clean Architecture?
- [ ] As métricas institucionais atendem ao que você precisa para avaliar seus primeiros bots?
- [ ] O modelo de desconto de taxas da B3 (~0,03%) e proteção contra *Look-Ahead Bias* atende às diretrizes do manual `PROJETO.md`?

*Aguardando validação e alinhamento do usuário antes de iniciar o código.*


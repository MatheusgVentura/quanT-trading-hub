# Specification: Strategy Layer and EMA Crossover (`003-strategy-layer`)

**Status:** draft  
**Date:** 2026-11-05  
**Domain Area:** `src/strategies/`  

---

## 1. Objective
Establish a modular, stateless quantitative strategy layer rooted in the `BaseStrategy` abstract interface and implement the dual Exponential Moving Average Crossover strategy (`EMACrossoverStrategy`) based on the foundational parameters specified in `PROJETO.md`. The strategy processes daily market data (`1d`) to emit discrete binary signals (`{0, 1}`) indicating Long exposure or Cash preservation, providing synchronized sliced time series for unbiased backtest evaluation with B3 transaction costs.

---

## 2. Out of Scope
* **Short Positions / Margin Trading:** Strictly limited to Long and Cash (`{0, 1}`) to avoid margin borrowing fees and table liquidation risks on a small retail account (as mandated by `PROJETO.md`).
* **Intraday Timeframes:** Frequencies other than daily (`1d`) such as `1m`, `5m`, `15m`, or `60m` are out of scope.
* **Slippage Modeling:** Price slippage is excluded from this phase; execution is modeled strictly at daily closing prices.
* **Continuous / Fractional Exposure Sizing:** No fractional weights (`0.5`, `0.7`); exposure is binary (`0` or `1`).
* **Per-Asset Parameter Tuning:** Hyperparameter optimization or curve-fitting across different tickers is prohibited; uniform default parameters (9/21) apply to all assets.

---

## 3. Acceptance Criteria

### Criteria Derived from `PROJETO.md`
* **AC01:** The strategy must calculate dual Exponential Moving Averages on the `Close` price series: Fast EMA with default span of 9 (`fast_period=9`) and Slow EMA with default span of 21 (`slow_period=21`).
* **AC02:** The strategy must emit binary discrete signals: `1` (Long) whenever Fast EMA is strictly greater than Slow EMA ($\text{EMA}_{fast} > \text{EMA}_{slow}$), and `0` (Cash) otherwise.
* **AC03:** The backtesting execution must apply the B3 transaction fee of 0.03% (`b3_fee_pct = 0.0003`) on each position transition ($|Pos_t - Pos_{t-1}| > 0$), representing standard B3 exchange fees (emolumentos + taxa de liquidação).
* **AC04:** The strategy validation report must display:
  * Strategy Return with B3 fees (Net Return).
  * Strategy Return without fees (Gross Return).
  * Benchmark Return (Buy & Hold).
  * Total number of transactions (turnover / giro).
  * Total transaction cost paid in percentage/currency.
* **AC05:** The strategy must be validated against the fixed B3 equity universe defined in `PROJETO.md`: `ITUB4.SA`, `PETR4.SA`, `VALE3.SA`, and `WEGE3.SA` across a fixed 3-year historical evaluation window (`2021-11-01` to `2024-11-01`).

### Criteria Derived from Software Engineering Standards (Assumptions)
* **AC06:** The strategy contract `BaseStrategy` must define an abstract method `generate_signals(self, ohlcv_df: pd.DataFrame) -> pd.Series` with output DatetimeIndex identical to input DatetimeIndex.
* **AC07:** Strategy execution must be pure and stateless: given identical inputs, `generate_signals` must return identical outputs without mutating the input DataFrame.
* **AC08:** Parameter validation: Constructor must validate that parameters are positive integers, enforcing $fast\_period \ge 2$ and $slow\_period > fast\_period$. If invalid, raise `InvalidParameterError`.
* **AC09:** History length validation: If `len(ohlcv_df) < slow_period`, `generate_signals` must raise `InsufficientDataError`.
* **AC10:** Warm-up handling: Moving averages must be computed with `min_periods=slow_period`. During the warm-up period (first $slow\_period - 1$ rows), signals must be explicitly set to `0` (Cash).
* **AC11:** Output formatting: The generated Series must have dtype integer/float compatible with the engine, have values strictly within $\{0, 1\}$, and have its name attribute set to `"Signal"`.
* **AC12:** Input validation: The strategy must raise `StrategyError` if the input DataFrame is empty or lacks the required `Close` column.
* **AC13:** Backtest warm-up alignment: When evaluating the strategy through the backtest engine, the evaluation slice must truncate rows prior to the first valid decision bar (index $\ge slow\_period - 1$), guaranteeing that Strategy and Benchmark are compared over the exact same time window.

---

## 4. Edge Cases
* **Dataframe with exactly `slow_period` bars:** Must compute the single valid point and return 0s for previous bars without error.
* **Dataframe with fewer than `slow_period` bars:** Must raise `InsufficientDataError` with descriptive message.
* **Constant price series (Zero Volatility):** Fast EMA equals Slow EMA throughout; signal must remain strictly `0` (Cash).
* **Missing `Close` column:** Must raise `StrategyError`.

---

## 5. Contracts and Data Models
```python
class BaseStrategy(ABC):
    """Abstract base class for pure, stateless quantitative trading strategies."""

    @abstractmethod
    def generate_signals(self, ohlcv_df: pd.DataFrame) -> pd.Series:
        """Transforms OHLCV historical bars into discrete trading signals {0, 1}."""
        ...


class EMACrossoverStrategy(BaseStrategy):
    """Dual Exponential Moving Average crossover strategy (Long/Cash)."""

    def __init__(self, fast_period: int = 9, slow_period: int = 21) -> None:
        """Validates fast_period >= 2 and slow_period > fast_period."""
        ...

    def generate_signals(self, ohlcv_df: pd.DataFrame) -> pd.Series:
        """Calculates Fast/Slow EMA with min_periods=slow_period and emits signals."""
        ...
```

---

## 6. Abuse and Security Risks
* **Data Snooping / Curve-Fitting:** Fitting separate EMA periods per asset invalidates statistical significance. Prevented by fixing default 9/21 across all four target tickers.
* **Warm-up Distortion:** Including warm-up bars where the strategy is forced to be in cash while the benchmark drifts creates artificial tracking error. Prevented by slicing the backtest start date to the first valid strategy decision bar (AC13).

---

## 7. Open Questions
* *None. All open questions were resolved by explicit user decisions on 2026-11-05.*

---

## 8. Assumptions Made & Architecture Decisions Log
1. **Decision on EMA Windows:** Enforced $fast \ge 2$ and $slow > fast$, with default 9/21. Input series with fewer bars than $slow$ raises `InsufficientDataError`.
2. **Decision on Warm-up:** Uses `min_periods=slow_period` in `.ewm()`, producing 0 for warmup bars. Backtest slices output to start on first valid decision bar.
3. **Decision on Timeframe & Annualization:** Timeframe is strictly daily (`1d`). Annualization metrics assume 252 business days per year.
4. **Decision on Tickers & Period:** Fixed universe (`ITUB4.SA`, `PETR4.SA`, `VALE3.SA`, `WEGE3.SA`) across 3-year window (`2021-11-01` to `2024-11-01`).
5. **Decision on Fees:** Fixed B3 fee of 0.03% (emolumentos + liquidação). Slippage is out of scope. Summary report presents both Net (with fees) and Gross (without fees) metrics alongside total trades and friction cost.

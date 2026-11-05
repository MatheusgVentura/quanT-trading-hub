# Specification: Strategy Layer and EMA Crossover (`003-strategy-layer`)

**Status:** draft  
**Date:** 2026-11-05  
**Domain Area:** `src/strategies/`  

---

## 1. Objective
Establish an isolated, modular strategy layer defined by a pure abstract contract (`BaseStrategy`) and implement the foundational quantitative strategy: an Exponential Moving Average Crossover (`EMACrossoverStrategy`). The strategy transforms standardized market price series into discrete binary trading signals (`{0, 1}`) indicating Long exposure or Cash preservation, ready for consumption by the vectorized backtest engine.

---

## 2. Out of Scope
* **Short Selling / Leveraged Short Positions:** The strategy is strictly constrained to Long/Cash (`{0, 1}`) positions, reflecting cash-account trading on Brazilian equities (B3 fracionário) with zero risk of margin liquidation.
* **Continuous / Fractional Exposure Sizing:** No continuous target weights (`[-1.0, 1.0]`) at this stage; signals are strictly binary.
* **Stateful Intraday Event-Driven Handlers:** No stateful callbacks (`on_tick`, `on_bar`) or order management logic inside the strategy.
* **Multi-Asset Portfolio Allocation:** Strategies operate on single-asset OHLCV time series.

---

## 3. Acceptance Criteria
* **AC01:** The strategy contract `BaseStrategy` must define an abstract method `generate_signals(self, ohlcv_df: pd.DataFrame) -> pd.Series` returning a Series indexed identically to `ohlcv_df.index`.
* **AC02:** All strategy implementations must be pure and stateless: given identical inputs and hyperparameters, `generate_signals` must return identical outputs without mutating the input DataFrame.
* **AC03:** `EMACrossoverStrategy` must accept configurable integer parameters `fast_period` and `slow_period`, validating that both are strictly positive integers ($> 0$) and that $fast\_period < slow\_period$.
* **AC04:** If validation fails on strategy parameters ($fast \ge slow$ or non-positive integers), the constructor must raise a typed `InvalidParameterError`.
* **AC05:** `EMACrossoverStrategy` must calculate exponential moving averages from the `Close` column using standard exponential weighting ($\text{span}=fast$ and $\text{span}=slow$).
* **AC06:** `EMACrossoverStrategy` must generate a discrete signal series where:
  * Value is `1` (Long) whenever $\text{EMA}_{fast} > \text{EMA}_{slow}$.
  * Value is `0` (Cash / Neutral) whenever $\text{EMA}_{fast} \le \text{EMA}_{slow}$.
* **AC07:** Warm-up bars and any rows where moving averages cannot be computed (NaNs) must default to `0` (Cash).
* **AC08:** The output Series must have values strictly within the set $\{0, 1\}$ and have its name attribute set to `"Signal"`.
* **AC09:** The strategy must raise a typed `StrategyError` if the input DataFrame is empty or does not contain the required `Close` column.

---

## 4. Edge Cases
* **Series Shorter than `slow_period`:** When the input DataFrame length is less than the slow moving average window, the strategy must return a Series filled entirely with `0` without throwing uncaught exceptions.
* **Flat Constant Prices:** If prices remain perfectly constant across the entire series, fast EMA equals slow EMA; the strategy must emit `0` (cash).
* **Missing `Close` column:** Must raise `StrategyError("Required column 'Close' missing")`.

---

## 5. Contracts and Data Models
```python
class BaseStrategy(ABC):
    """Abstract base class for pure, stateless quantitative trading strategies."""

    @abstractmethod
    def generate_signals(self, ohlcv_df: pd.DataFrame) -> pd.Series:
        """Transforms OHLCV historical bars into discrete trading signals.

        Args:
            ohlcv_df: Sanitized market data containing at least the 'Close' column.

        Returns:
            pd.Series containing binary signals {0, 1} with matching DatetimeIndex.
        """
        ...


class EMACrossoverStrategy(BaseStrategy):
    """Dual Exponential Moving Average crossover strategy (Long/Cash)."""

    def __init__(self, fast_period: int = 9, slow_period: int = 21) -> None: ...
    def generate_signals(self, ohlcv_df: pd.DataFrame) -> pd.Series: ...
```

---

## 6. Abuse and Security Risks
* **Look-Ahead Bias in Indicator Smoothing:** If forward-looking window functions or centered rolling windows are used, future price information leaks into past signals. Mitigated by using standard causal `pd.Series.ewm(span=..., adjust=False).mean()`.
* **In-place Input Mutation:** Inadvertently modifying columns on `ohlcv_df` passed by reference. Mitigated by operating exclusively on extracted series or deep copies.

---

## 7. Open Questions
1. **EMA Periods & Range Limits:** Should the strategy enforce minimum acceptable window sizes (e.g., $fast \ge 2$, $slow \ge 5$) to prevent degenerated 1-bar noise, or keep it open to any $fast < slow$?
2. **Warm-up Period Handling in Backtesting:** During initial warm-up bars (first $N$ bars until slow EMA stabilizes), defaulting to cash (`0`) is safe, but should the backtest engine optionally slice out the warm-up period from benchmark comparison metrics?
3. **Timeframe Support:** Although the manual `PROJETO.md` uses daily candles (`1d`), should the strategy explicitly accept intraday bars (`60m`, `15m`) without modification?
4. **Initial Benchmark Asset Universe:** Which B3 assets will be the primary target for initial strategy verification (`ITUB4.SA`, `PETR4.SA`, `VALE3.SA`)?
5. **Fee Comparison:** Should we implement an automated comparison runner that reports the strategy results with and without B3 fees (0.03%) to measure the friction drag directly?

---

## 8. Assumptions Made
* Decisions at bar $t$ are based on prices available up to the close of bar $t$.
* Lag shift ($t \to t+1$) is handled strictly and unconditionally by the downstream `VectorizedBacktestEngine` (AC02 of spec 002), keeping the strategy focused entirely on pure signal generation.
* The strategy operates exclusively in Long (`1`) or Cash (`0`) mode, aligning with individual cash-account constraints without short-selling borrowing fees.

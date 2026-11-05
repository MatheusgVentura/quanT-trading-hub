# Specification: Vectorized Backtest Engine and Metrics (`002-vectorized-backtest`)

**Status:** retroactive (pre-SDD)  
**Date:** 2026-11-05  
**Domain Area:** `src/backtest/`  

---

## 1. Objective
Build a high-performance vectorized backtesting engine that simulates trading strategy signals over standardized market series, explicitly accounts for Brazilian B3 exchange friction costs, strictly eliminates look-ahead bias via signal execution lag, and computes standard institutional quantitative risk/return metrics.

---

## 2. Out of Scope
* Intraday bar-by-bar queue / tick execution engine (event-driven engine).
* Multi-asset cross-sectional portfolio rebalancing.
* Limit order book queuing simulation and partial fills.
* Dynamic margin calls or borrow interest fees for short positions.

---

## 3. Acceptance Criteria
* **AC01:** The engine must compute asset benchmark returns (Buy & Hold) from closing prices across the entire aligned DatetimeIndex.
* **AC02:** The engine must enforce look-ahead bias prevention by lagging strategy signals by 1 period (`.shift(1)`), guaranteeing that a signal formed at the close of bar $t$ only participates in returns starting at bar $t+1$.
* **AC03:** The engine must identify position transitions ($|Position_t - Position_{t-1}| > 0$) and deduct transaction friction costs (B3 fees: default 0.03%, optional slippage, optional brokerage).
* **AC04:** Days where the position remains constant must incur zero transaction friction costs.
* **AC05:** The engine must calculate net strategy returns after transaction fees and generate cumulative equity curves for both strategy and benchmark starting from a base of 1.0.
* **AC06:** The engine must compute the underwater drawdown series and accurately calculate the peak-to-trough Maximum Drawdown percentage (MDD).
* **AC07:** The metrics calculator must compute institutional performance metrics: Total Return (%), Benchmark Return (%), CAGR (%), Annualized Volatility (%), Sharpe Ratio, Sortino Ratio, Profit Factor, Win Rate (%), and Total Trades.
* **AC08:** The engine must raise `MismatchedIndexError` when the temporal indices of the OHLCV DataFrame and the signals Series are not strictly identical.
* **AC09:** The engine must raise `InvalidSignalError` when signal values lie outside the normalized range $[-1.0, 1.0]$.
* **AC10:** The `BacktestResult` model must provide a `summary()` method formatting the quantitative performance report in clear institutional text.

---

## 4. Edge Cases
* **100% Cash Strategy (signals all 0):** Must return 0.0% total return, 0.0% drawdown, and exactly 0 trades.
* **Zero Volatility / Constant Returns:** Standard deviation equals zero; Sharpe and Sortino ratios must return 0.0 safely without dividing by zero.
* **Zero Loss Series:** Profit factor calculation must return a safe upper bound (99.9) rather than crashing on zero-division.
* **Empty Input Data:** Must raise a typed `BacktestError`.

---

## 5. Contracts and Data Models
```python
@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float = 100.0
    b3_fee_pct: float = 0.0003
    brokerage_fee: float = 0.0
    slippage_pct: float = 0.0
    risk_free_rate: float = 0.1075
    trading_days_per_year: int = 252


@dataclass(frozen=True)
class BacktestMetrics:
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


class VectorizedBacktestEngine:
    def __init__(self, config: BacktestConfig | None = None) -> None: ...
    def run(
        self, ohlcv_df: pd.DataFrame, signals: pd.Series, ticker: str = "ATIVO"
    ) -> BacktestResult: ...
```

---

## 6. Abuse and Security Risks
* **Look-Ahead Bias Leakage:** Silently incorporating future prices into current decision-making leads to catastrophic false positives. Mitigated by strict mandatory 1-lag shift on all incoming signals.
* **Unrealistic Zero-Cost Assumptions:** Underestimating friction turns losing high-frequency strategies into apparent winners. Mitigated by defaulting to standard B3 fees (0.03%).

---

## 7. Open Questions
* None (retroactive spec documenting implemented Phase 2 baseline).

---

## 8. Assumptions Made
* Standard Brazilian market trading year has 252 business days.
* Zero brokerage fee assumes RLP (Retail Liquidity Provider) active in XP for individual equity accounts.

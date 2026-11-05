# Specification: Market Data Infrastructure and Sanitization (`001-data-infrastructure`)

**Status:** retroactive (pre-SDD)  
**Date:** 2026-11-05  
**Domain Area:** `src/data/`  

---

## 1. Objective
Establish an isolated, strongly-typed data ingestion and validation layer capable of fetching historical OHLCV (Open, High, Low, Close, Volume) series for Brazilian equities (B3 `.SA` tickers) and global benchmarks, sanitizing structural anomalies, enforcing physical price consistency, and caching data locally to minimize network latency and API rate-limiting during quantitative research.

---

## 2. Out of Scope
* Real-time tick-by-tick WebSocket data streaming.
* Order book (Level 2 / Depth of Market) ingestion.
* Corporate actions adjustment calculations (relies on upstream provider data).
* Order execution and strategy evaluation.

---

## 3. Acceptance Criteria
* **AC01:** The provider must fetch historical OHLCV data for given equity tickers, supporting B3 assets with `.SA` suffix (e.g., `ITUB4.SA`) across user-specified date ranges or predefined historical periods.
* **AC02:** Multi-index column hierarchies returned by the external provider must be automatically flattened into single-level standardized title-cased column headers.
* **AC03:** The validator must raise a specific validation error if any required column (`Open`, `High`, `Low`, `Close`, `Volume`) is absent.
* **AC04:** The validator must reject series containing non-positive price records ($Price \le 0$) or negative trading volume ($Volume < 0$).
* **AC05:** The validator must reject series violating physical candle constraints: $High < Low$, $High < \max(Open, Close)$, or $Low > \min(Open, Close)$ within a floating-point tolerance of $10^{-5}$.
* **AC06:** A local file-based cache mechanism must be available to store validated DataFrames in an efficient columnar format (Parquet), preventing redundant network calls for identical queries.
* **AC07:** Data ingestion must be defined through an abstract interface (`IDataProvider`) ensuring that backtest and strategy layers remain decoupled from specific external data vendors.

---

## 4. Edge Cases
* **Non-existent or delisted ticker:** Must raise a typed `TickerNotFoundError` rather than returning an empty DataFrame or crashing downstream.
* **Unsorted or duplicate dates:** DatetimeIndex must be deduplicated (retaining latest) and sorted chronologically.
* **All-NaN series:** Deselection and dropna that result in an empty DataFrame must raise a typed `DataValidationError`.
* **Network drop or timeout:** External network exceptions must be wrapped and re-raised as `DataDownloadError`.

---

## 5. Contracts and Data Models
```python
class IDataProvider(ABC):
    @abstractmethod
    def fetch_ohlcv(
        self,
        ticker: str,
        start_date: str | None = None,
        end_date: str | None = None,
        period: str | None = "1y",
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Returns validated DataFrame with DatetimeIndex and ['Open', 'High', 'Low', 'Close', 'Volume']."""
```

---

## 6. Abuse and Security Risks
* **Path Traversal via Ticker Identifier:** Ticker strings used to construct cache file paths could theoretically include directory traversal characters (e.g. `../../`). Sanitization must strip illegal characters before file creation.
* **API Rate Limiting / IP Block:** Excessive requests to unauthenticated Yahoo Finance endpoints can result in temporary IP throttling. Local caching mitigates this risk.

---

## 7. Open Questions
* None (retroactive spec documenting implemented Phase 1 baseline).

---

## 8. Assumptions Made
* Default historical frequency is daily bars (`interval="1d"`).
* Yahoo Finance provides sufficient reliability and historical depth for initial prototyping without requiring paid data subscriptions.

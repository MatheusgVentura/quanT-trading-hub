# Architecture Plan: Market Data Infrastructure (`001-data-infrastructure`)

**Status:** retroactive (pre-SDD)  

---

## 1. Architectural Decisions
* **Interface Decoupling:** Adopted `IDataProvider` using Python's `abc.ABC` to allow future drop-in providers (e.g., MetaTrader 5, CCXT, Interactive Brokers) without breaking strategy or backtesting layers.
* **Storage Engine:** Selected Apache Parquet (`pyarrow`) for caching due to fast columnar reads, native retention of pandas DatetimeIndex and float types, and minimal disk footprint compared to CSV.
* **Validation Strategy:** Implemented `OHLCVValidator` as a pure, dedicated quality gate rather than bundling validation logic into the provider class, adhering to Single Responsibility Principle.

---

## 2. Alternatives Discarded
* **SQLite / DuckDB for Cache:** Discarded as unnecessary overhead for simple per-ticker daily time series files at this initial stage.
* **Pandas MultiIndex preservation:** Discarded because multi-ticker MultiIndex structures complicate vectorized indicator calculations in downstream strategy code.

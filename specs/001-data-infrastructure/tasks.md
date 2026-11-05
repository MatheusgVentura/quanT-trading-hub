# Tasks: Market Data Infrastructure (`001-data-infrastructure`)

**Status:** retroactive (pre-SDD)  

---

- [x] **Task 1.1:** Define domain exceptions hierarchy (`DataError`, `DataDownloadError`, `DataValidationError`, `TickerNotFoundError`). *(Mapped to: AC03, AC04, AC05)*
- [x] **Task 1.2:** Define abstract contract `IDataProvider` in `interfaces.py`. *(Mapped to: AC07)*
- [x] **Task 1.3:** Implement `OHLCVValidator` with schema checks, MultiIndex flattening, physical candle consistency, and NaN filtering. *(Mapped to: AC02, AC03, AC04, AC05)*
- [x] **Task 1.4:** Implement `DataCacheManager` with Parquet serialization and deterministic cache keys. *(Mapped to: AC06)*
- [x] **Task 1.5:** Implement concrete `YFinanceDataProvider` integrating external downloads, validation, and caching. *(Mapped to: AC01, AC06, AC07)*
- [x] **Task 1.6:** Implement comprehensive unit test suite with network mocks in `tests/unit/test_data/`. *(Mapped to: AC01-AC07)*

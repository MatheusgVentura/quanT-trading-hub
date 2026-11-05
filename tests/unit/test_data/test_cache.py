"""Testes unitários para o DataCacheManager."""

import time
from pathlib import Path

import pandas as pd

from src.data.cache import DataCacheManager


def test_cache_miss_when_empty(tmp_path: Path) -> None:
    """Testa se get retorna None quando o arquivo não existe."""
    cache = DataCacheManager(cache_dir=str(tmp_path), ttl_hours=24)
    key = cache.generate_key("PETR4.SA", period="1y")
    assert cache.get(key) is None


def test_cache_set_and_get(tmp_path: Path) -> None:
    """Testa armazenamento e recuperação de DataFrame do cache."""
    cache = DataCacheManager(cache_dir=str(tmp_path), ttl_hours=24)
    dates = pd.date_range("2024-01-01", periods=3, freq="D")
    df = pd.DataFrame({"Close": [10.0, 11.0, 12.0]}, index=dates)

    key = cache.generate_key("PETR4.SA", period="1y")
    cache.set(key, df)

    cached_df = cache.get(key)
    assert cached_df is not None
    assert len(cached_df) == 3
    assert list(cached_df["Close"]) == [10.0, 11.0, 12.0]


def test_cache_ttl_expiration(tmp_path: Path) -> None:
    """Testa expiração do cache com TTL."""
    # Instancia com TTL zero (expira imediatamente)
    cache = DataCacheManager(cache_dir=str(tmp_path), ttl_hours=0)
    dates = pd.date_range("2024-01-01", periods=2, freq="D")
    df = pd.DataFrame({"Close": [10.0, 11.0]}, index=dates)

    key = cache.generate_key("VALE3.SA", period="1mo")
    cache.set(key, df)

    time.sleep(0.01)
    assert cache.get(key) is None


def test_cache_clear(tmp_path: Path) -> None:
    """Testa limpeza total dos arquivos de cache."""
    cache = DataCacheManager(cache_dir=str(tmp_path), ttl_hours=24)
    df = pd.DataFrame({"Close": [10.0]}, index=pd.date_range("2024-01-01", periods=1))

    key1 = cache.generate_key("ITUB4.SA", period="1y")
    key2 = cache.generate_key("BBDC4.SA", period="1y")
    cache.set(key1, df)
    cache.set(key2, df)

    assert cache.get(key1) is not None
    assert cache.get(key2) is not None

    cache.clear()
    assert cache.get(key1) is None
    assert cache.get(key2) is None

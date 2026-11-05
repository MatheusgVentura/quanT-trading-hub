"""Gerenciador de cache local para séries temporais financeiras."""

from pathlib import Path
from typing import Optional
import datetime
import pandas as pd


class DataCacheManager:
    """Gerencia armazenamento e recuperação em cache local de dados OHLCV."""

    def __init__(self, cache_dir: str = ".cache/data", ttl_hours: Optional[int] = 24):
        """Inicializa o gerenciador de cache.

        Args:
            cache_dir: Diretório raiz para persistência dos arquivos parquet.
            ttl_hours: Tempo de vida do cache em horas. None desativa expiração por tempo.
        """
        self.cache_dir = Path(cache_dir)
        self.ttl_hours = ttl_hours
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def generate_key(
        self,
        ticker: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        period: Optional[str] = "1y",
        interval: str = "1d",
    ) -> str:
        """Gera uma chave determinística para o arquivo de cache."""
        clean_ticker = ticker.replace("^", "").replace(".", "_").upper()
        s_date = start_date or "none"
        e_date = end_date or "none"
        p = period or "none"
        return f"{clean_ticker}_{p}_{s_date}_{e_date}_{interval}.parquet"

    def get(self, key: str) -> Optional[pd.DataFrame]:
        """Recupera um DataFrame do cache caso exista e não esteja expirado."""
        file_path = self.cache_dir / key
        if not file_path.exists():
            return None

        # Validação de TTL
        if self.ttl_hours is not None:
            file_mtime = datetime.datetime.fromtimestamp(file_path.stat().st_mtime)
            age_hours = (datetime.datetime.now() - file_mtime).total_seconds() / 3600.0
            if age_hours > self.ttl_hours:
                return None

        try:
            df = pd.read_parquet(file_path)
            return df
        except Exception:
            return None

    def set(self, key: str, df: pd.DataFrame) -> None:
        """Salva um DataFrame no cache em formato parquet."""
        file_path = self.cache_dir / key
        try:
            df.to_parquet(file_path, engine="pyarrow")
        except Exception:
            # Fallback transparente para não travar a aplicação caso haja erro de I/O
            pass

    def clear(self) -> None:
        """Remove todos os arquivos do diretório de cache."""
        for item in self.cache_dir.glob("*.parquet"):
            try:
                item.unlink()
            except OSError:
                pass


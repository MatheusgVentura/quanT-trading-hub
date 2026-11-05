"""Validação e sanitização de dados de mercado (OHLCV)."""

from typing import ClassVar

import pandas as pd

from src.data.exceptions import DataValidationError


class OHLCVValidator:
    """Validador de qualidade e integridade para séries temporais OHLCV."""

    REQUIRED_COLUMNS: ClassVar[list[str]] = ["Open", "High", "Low", "Close", "Volume"]

    @classmethod
    def validate_and_clean(cls, df: pd.DataFrame, ticker: str = "") -> pd.DataFrame:
        """Valida e sanitiza um DataFrame contendo dados de mercado OHLCV.

        Args:
            df: DataFrame bruto obtido do provedor de dados.
            ticker: Símbolo do ativo para enriquecer mensagens de erro.

        Returns:
            pd.DataFrame padronizado com DatetimeIndex ordenado e colunas limpas.

        Raises:
            DataValidationError: Se faltarem colunas ou se os dados violarem regras de integridade física.
        """
        if df is None or df.empty:
            raise DataValidationError(
                f"DataFrame vazio ou nulo para o ativo '{ticker}'."
            )

        cleaned = df.copy()

        # 1. Tratamento de colunas MultiIndex (caso resquício do yfinance)
        if isinstance(cleaned.columns, pd.MultiIndex):
            # Se o ticker estiver no nível 1, extrai
            if ticker and ticker in cleaned.columns.get_level_values(-1):
                cleaned = cleaned.xs(ticker, axis=1, level=-1)
            else:
                cleaned.columns = cleaned.columns.get_level_values(0)

        # 2. Normalização dos nomes das colunas (Title Case)
        cleaned.columns = [str(col).strip().capitalize() for col in cleaned.columns]

        # 3. Verificação de colunas obrigatórias
        missing_cols = [
            col for col in cls.REQUIRED_COLUMNS if col not in cleaned.columns
        ]
        if missing_cols:
            raise DataValidationError(
                f"Colunas obrigatórias ausentes para '{ticker}': {missing_cols}. "
                f"Colunas encontradas: {list(cleaned.columns)}"
            )

        # Seleciona apenas as colunas requeridas na ordem padrão
        cleaned = cleaned[cls.REQUIRED_COLUMNS]

        # 4. Tratamento do índice temporal
        if not isinstance(cleaned.index, pd.DatetimeIndex):
            try:
                cleaned.index = pd.to_datetime(cleaned.index)
            except Exception as exc:
                raise DataValidationError(
                    f"Falha ao converter índice para DatetimeIndex em '{ticker}': {exc}"
                ) from exc

        # Remove fuso horário para padronização (caso exista) e remove datas duplicadas
        if cleaned.index.tz is not None:
            cleaned.index = cleaned.index.tz_localize(None)

        cleaned = cleaned[~cleaned.index.duplicated(keep="last")]
        cleaned = cleaned.sort_index()

        # 5. Conversão estrita de tipos numéricos
        for col in cls.REQUIRED_COLUMNS:
            cleaned[col] = pd.to_numeric(cleaned[col], errors="coerce")

        # 6. Remoção de registros com NaNs em preços ou volumes
        cleaned = cleaned.dropna(subset=cls.REQUIRED_COLUMNS)

        if cleaned.empty:
            raise DataValidationError(
                f"Todos os registros de '{ticker}' foram descartados por conterem valores nulos/inválidos."
            )

        # 7. Regras de integridade física dos preços
        # Preços devem ser estritamente positivos
        price_cols = ["Open", "High", "Low", "Close"]
        if (cleaned[price_cols] <= 0).any().any():
            invalid_rows = cleaned[(cleaned[price_cols] <= 0).any(axis=1)]
            raise DataValidationError(
                f"Preços menores ou iguais a zero detectados em '{ticker}': {len(invalid_rows)} linha(s)."
            )

        # High deve ser maior ou igual a Low (com tolerância de ponto flutuante de 1e-5)
        epsilon = 1e-5
        if (cleaned["High"] + epsilon < cleaned["Low"]).any():
            invalid_hl = cleaned[cleaned["High"] + epsilon < cleaned["Low"]]
            raise DataValidationError(
                f"Violação de integridade High < Low em '{ticker}': {len(invalid_hl)} linha(s)."
            )

        # High deve ser a máxima do candle (>= Open e >= Close)
        if (cleaned["High"] + epsilon < cleaned["Open"]).any() or (
            cleaned["High"] + epsilon < cleaned["Close"]
        ).any():
            invalid_h = cleaned[
                (cleaned["High"] + epsilon < cleaned["Open"])
                | (cleaned["High"] + epsilon < cleaned["Close"])
            ]
            raise DataValidationError(
                f"Violação de integridade High menor que Open/Close em '{ticker}': {len(invalid_h)} linha(s)."
            )

        # Low deve ser a mínima do candle (<= Open e <= Close)
        if (cleaned["Low"] - epsilon > cleaned["Open"]).any() or (
            cleaned["Low"] - epsilon > cleaned["Close"]
        ).any():
            invalid_l = cleaned[
                (cleaned["Low"] - epsilon > cleaned["Open"])
                | (cleaned["Low"] - epsilon > cleaned["Close"])
            ]
            raise DataValidationError(
                f"Violação de integridade Low maior que Open/Close em '{ticker}': {len(invalid_l)} linha(s)."
            )

        # Volume deve ser não-negativo
        if (cleaned["Volume"] < 0).any():
            invalid_vol = cleaned[cleaned["Volume"] < 0]
            raise DataValidationError(
                f"Volume negativo detectado em '{ticker}': {len(invalid_vol)} linha(s)."
            )

        return cleaned

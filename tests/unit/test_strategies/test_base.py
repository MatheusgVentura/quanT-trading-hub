"""Testes unitários para o contrato BaseStrategy."""

import pandas as pd
import pytest

from src.strategies.base import BaseStrategy


class DummyStrategy(BaseStrategy):
    """Implementação concreta de teste para validar o contrato BaseStrategy."""

    def generate_signals(self, ohlcv_df: pd.DataFrame) -> pd.Series:
        # Retorna série de zeros sem mutar a entrada
        return pd.Series(0, index=ohlcv_df.index, name="Signal")


def test_ac06_base_strategy_is_abstract() -> None:
    """AC06: Valida que BaseStrategy é uma classe abstrata e não pode ser instanciada."""
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        BaseStrategy()  # type: ignore[abstract]


def test_ac06_concrete_subclass_contract() -> None:
    """AC06: Valida que a subclasse concreta implementa generate_signals com o mesmo DatetimeIndex."""
    dates = pd.date_range("2024-01-01", periods=3, freq="D")
    df = pd.DataFrame({"Close": [10.0, 11.0, 12.0]}, index=dates)

    strategy = DummyStrategy()
    signals = strategy.generate_signals(df)

    assert isinstance(signals, pd.Series)
    assert signals.index.equals(df.index)
    assert signals.name == "Signal"


def test_ac07_stateless_and_immutability() -> None:
    """AC07: Valida que a execução da estratégia não muta o DataFrame de entrada."""
    dates = pd.date_range("2024-01-01", periods=3, freq="D")
    df = pd.DataFrame({"Close": [10.0, 11.0, 12.0]}, index=dates)
    df_copy = df.copy(deep=True)

    strategy = DummyStrategy()
    _ = strategy.generate_signals(df)

    pd.testing.assert_frame_equal(df, df_copy)

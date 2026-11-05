"""Testes unitários rigorosos para a estratégia EMACrossoverStrategy."""

import pandas as pd
import pytest

from src.strategies.ema_crossover import EMACrossoverStrategy
from src.strategies.exceptions import (
    InsufficientDataError,
    InvalidParameterError,
    StrategyError,
)


@pytest.fixture
def sample_ohlcv_rising() -> pd.DataFrame:
    """Gera série temporal com 30 candles em alta constante."""
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    prices = [10.0 + i * 0.5 for i in range(30)]
    return pd.DataFrame({"Close": prices}, index=dates)


def test_ac01_default_periods() -> None:
    """AC01: Valida períodos padrão 9 e 21 da estratégia conforme PROJETO.md."""
    strat = EMACrossoverStrategy()
    assert strat.fast_period == 9
    assert strat.slow_period == 21


def test_ac02_ac11_signals_are_strictly_binary_with_correct_name(
    sample_ohlcv_rising: pd.DataFrame,
) -> None:
    """AC02, AC11: Valida que a série de sinais tem apenas valores em {0.0, 1.0} e nome 'Signal'."""
    strat = EMACrossoverStrategy(fast_period=3, slow_period=7)
    signals = strat.generate_signals(sample_ohlcv_rising)

    assert isinstance(signals, pd.Series)
    assert signals.name == "Signal"
    assert set(signals.unique()).issubset({0.0, 1.0})
    assert signals.index.equals(sample_ohlcv_rising.index)


def test_ac03_valid_custom_parameters() -> None:
    """AC03: Valida instanciação com parâmetros válidos personalizados."""
    strat = EMACrossoverStrategy(fast_period=5, slow_period=15)
    assert strat.fast_period == 5
    assert strat.slow_period == 15


@pytest.mark.parametrize(
    ("fast", "slow", "match"),
    [
        (1, 21, "O período rápido deve ser >= 2"),
        (0, 21, "O período rápido deve ser >= 2"),
        (-5, 21, "O período rápido deve ser >= 2"),
        (21, 21, "deve ser estritamente maior"),
        (25, 21, "deve ser estritamente maior"),
        ("9", 21, "números inteiros"),
        (9, "21", "números inteiros"),
        (True, 21, "números inteiros"),
    ],
)
def test_ac04_ac08_invalid_parameters_raise_error(
    fast: object, slow: object, match: str
) -> None:
    """AC04, AC08: Valida rejeição estrita de parâmetros inválidos."""
    with pytest.raises(InvalidParameterError, match=match):
        EMACrossoverStrategy(fast_period=fast, slow_period=slow)  # type: ignore[arg-type]


def test_ac05_ac06_crossover_behavior() -> None:
    """AC05, AC06: Valida alternância de sinal na transição de alta para queda."""
    dates = pd.date_range("2024-01-01", periods=40, freq="D")
    # 25 dias de alta forte (EMA 3 > EMA 7 => 1), seguidos de 15 dias de queda brusca (EMA 3 < EMA 7 => 0)
    prices = [10.0 + i for i in range(25)] + [35.0 - (i * 2.0) for i in range(15)]
    df = pd.DataFrame({"Close": prices}, index=dates)

    strat = EMACrossoverStrategy(fast_period=3, slow_period=7)
    signals = strat.generate_signals(df)

    # Durante o rali (após warm-up), deve estar comprado (1.0)
    assert signals.iloc[15] == 1.0
    # Após queda acentuada, a média rápida cai abaixo da lenta (0.0)
    assert signals.iloc[-1] == 0.0


def test_ac07_ac10_warmup_emits_zeros(sample_ohlcv_rising: pd.DataFrame) -> None:
    """AC07, AC10: Valida que candles durante o aquecimento (slow - 1) emitem sinal 0."""
    slow = 10
    strat = EMACrossoverStrategy(fast_period=3, slow_period=slow)
    signals = strat.generate_signals(sample_ohlcv_rising)

    # Os primeiros slow-1 candles (0 a 8) devem ser estritamente 0.0
    warmup_signals = signals.iloc[: slow - 1]
    assert (warmup_signals == 0.0).all()

    # No candle do índice slow-1 (9º), ambas as médias estão calculadas
    assert signals.iloc[slow - 1] == 1.0


def test_ac09_insufficient_data_raises_error() -> None:
    """AC09: Valida que série com menos linhas que slow_period levanta InsufficientDataError."""
    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    short_df = pd.DataFrame({"Close": range(10)}, index=dates)

    strat = EMACrossoverStrategy(fast_period=5, slow_period=20)
    with pytest.raises(InsufficientDataError, match="inferior ao período lento de 20"):
        strat.generate_signals(short_df)


def test_ac12_empty_or_missing_close_raises_error() -> None:
    """AC12: Valida que DataFrame vazio ou sem coluna 'Close' levanta StrategyError."""
    strat = EMACrossoverStrategy()

    with pytest.raises(StrategyError, match="DataFrame OHLCV vazio ou nulo"):
        strat.generate_signals(pd.DataFrame())

    dates = pd.date_range("2024-01-01", periods=25, freq="D")
    df_no_close = pd.DataFrame({"Open": range(25)}, index=dates)
    with pytest.raises(StrategyError, match="Coluna obrigatória 'Close' ausente"):
        strat.generate_signals(df_no_close)


def test_edge_case_constant_prices_emits_cash() -> None:
    """Edge Case: Preço constante gera EMA_fast == EMA_slow; sinal deve ser 0.0."""
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    flat_df = pd.DataFrame({"Close": [20.0] * 30}, index=dates)

    strat = EMACrossoverStrategy(fast_period=5, slow_period=10)
    signals = strat.generate_signals(flat_df)

    assert (signals == 0.0).all()

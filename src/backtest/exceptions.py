"""Exceções customizadas para o módulo de backtesting."""


class BacktestError(Exception):
    """Exceção base para erros ocorridos durante o backtest."""

    pass


class MismatchedIndexError(BacktestError):
    """Lançada quando os índices temporais de preços e sinais não coincidem."""

    pass


class InvalidSignalError(BacktestError):
    """Lançada quando a série de sinais contém valores fora do domínio válido (-1, 0, 1) ou tipos incompatíveis."""

    pass

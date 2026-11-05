"""Exceções de domínio para a camada de estratégias."""


class StrategyError(Exception):
    """Exceção base para erros ocorridos na camada de estratégias."""


class InvalidParameterError(StrategyError):
    """Lançada quando os parâmetros da estratégia são matematicamente inválidos."""


class InsufficientDataError(StrategyError):
    """Lançada quando a série temporal tem menos observações do que o período exigido."""

"""Exceções customizadas para o módulo de dados."""


class DataError(Exception):
    """Exceção base para erros relacionados a dados no trading hub."""

    pass


class DataDownloadError(DataError):
    """Lançada quando ocorre uma falha de conexão ou download dos dados."""

    pass


class DataValidationError(DataError):
    """Lançada quando os dados falham nas validações de qualidade e integridade (ex: High < Low)."""

    pass


class TickerNotFoundError(DataError):
    """Lançada quando nenhum dado é retornado para o ticker solicitado."""

    pass


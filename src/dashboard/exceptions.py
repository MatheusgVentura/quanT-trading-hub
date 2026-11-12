"""Domain exceptions for the interactive quantitative dashboard layer."""


class DashboardError(Exception):
    """Base exception for errors in the quantitative dashboard domain."""


class DashboardConfigurationError(DashboardError):
    """Raised when user inputs or dashboard parameters fail validation."""


class DashboardDataError(DashboardError):
    """Raised when market data or analytics results are invalid for rendering."""


class LedgerLoadError(DashboardError):
    """Raised when an execution ledger payload fails size, schema, or type checks."""

"""Order execution, broker abstraction, and paper trading layer."""

from src.execution.cli import main as cli_main
from src.execution.exceptions import (
    BrokerConnectionError,
    ExecutionConfigurationError,
    ExecutionError,
    ExecutionHaltedError,
    InvalidOrderError,
    OrderRejectedError,
)
from src.execution.interfaces import IBrokerAdapter
from src.execution.models import (
    AccountSnapshot,
    ExecutionConfig,
    ExecutionStepResult,
    OrderReceipt,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSnapshot,
    format_b3_execution_symbol,
)
from src.execution.paper_broker import SimulatedPaperBroker
from src.execution.router import OrderRouter
from src.execution.runner import PaperSimulationReport, PaperTradingRunner
from src.execution.sandbox_broker import RestSandboxBroker

__all__ = [
    "AccountSnapshot",
    "BrokerConnectionError",
    "ExecutionConfig",
    "ExecutionConfigurationError",
    "ExecutionError",
    "ExecutionHaltedError",
    "ExecutionStepResult",
    "IBrokerAdapter",
    "InvalidOrderError",
    "OrderReceipt",
    "OrderRejectedError",
    "OrderRequest",
    "OrderRouter",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "PaperSimulationReport",
    "PaperTradingRunner",
    "PositionSnapshot",
    "RestSandboxBroker",
    "SimulatedPaperBroker",
    "cli_main",
    "format_b3_execution_symbol",
]

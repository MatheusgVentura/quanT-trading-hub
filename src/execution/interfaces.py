"""Abstract contracts for broker and sandbox execution adapters."""

from abc import ABC, abstractmethod

from src.execution.models import AccountSnapshot, OrderReceipt, OrderRequest


class IBrokerAdapter(ABC):
    """Abstract interface decoupling execution routing from broker transports."""

    @abstractmethod
    def connect(self) -> None:
        """Establish or verify transport connectivity with the broker endpoint."""

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True when the broker transport is currently connected."""

    @abstractmethod
    def ping(self) -> float:
        """Measure round-trip latency in milliseconds to the broker endpoint."""

    @abstractmethod
    def submit_order(self, order: OrderRequest) -> OrderReceipt:
        """Submit a validated OrderRequest idempotently by client_order_id."""

    @abstractmethod
    def get_order_by_client_id(self, client_order_id: str) -> OrderReceipt | None:
        """Look up an order receipt by its deterministic client_order_id."""

    @abstractmethod
    def cancel_all_open_orders(self) -> list[OrderReceipt]:
        """Cancel all currently open orders and return their updated receipts."""

    @abstractmethod
    def get_account_snapshot(
        self, market_prices: dict[str, float] | None = None
    ) -> AccountSnapshot:
        """Fetch current cash, positions, open orders, and mark-to-market equity."""

"""Paper trading runner, historical B3 simulation, and atomic ledger reporting."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.execution.exceptions import (
    ExecutionConfigurationError,
    ExecutionHaltedError,
    InvalidOrderError,
)
from src.execution.interfaces import IBrokerAdapter
from src.execution.models import (
    AccountSnapshot,
    ExecutionConfig,
    ExecutionStepResult,
    OrderReceipt,
    OrderStatus,
    OrderType,
    _atomic_write_text,
    _atomic_write_via_path,
    _require_bool,
    _require_finite_number,
    _require_non_empty_str,
)
from src.execution.paper_broker import SimulatedPaperBroker
from src.execution.router import OrderRouter
from src.risk.manager import RiskManager
from src.risk.models import HaltReason, RiskConfig, RiskVerdict
from src.strategies.base import BaseStrategy
from src.strategies.ema_crossover import EMACrossoverStrategy
from src.strategies.exceptions import InsufficientDataError

_LEDGER_SCHEMA_VERSION = 1


def _utc_now() -> datetime:
    """Return current UTC-aware datetime compatible with Python 3.10."""
    return datetime.now(timezone.utc)  # noqa: UP017


def _coerce_optional_path(value: Path | str | None, field_name: str) -> Path | None:
    """Validate and coerce an optional filesystem path."""
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = _require_non_empty_str(value, field_name, ExecutionConfigurationError)
        return Path(cleaned)
    if isinstance(value, Path):
        if not str(value).strip():
            raise ExecutionConfigurationError(f"{field_name} cannot be empty.")
        return value
    raise ExecutionConfigurationError(
        f"{field_name} must be a Path, string, or None, got {type(value).__name__}."
    )


def _validate_ohlcv_for_simulation(ohlcv_df: object) -> list[float]:
    """Validate OHLCV DataFrame structure, monotonic index, and Close prices."""
    if not isinstance(ohlcv_df, pd.DataFrame) or ohlcv_df.empty:
        raise InvalidOrderError("ohlcv_df must be a non-empty pandas DataFrame.")
    if "Close" not in ohlcv_df.columns:
        raise InvalidOrderError("ohlcv_df must contain a 'Close' column.")
    if not isinstance(ohlcv_df.index, pd.DatetimeIndex):
        raise InvalidOrderError("ohlcv_df index must be a pandas DatetimeIndex.")
    if ohlcv_df.index.isna().any():
        raise InvalidOrderError("ohlcv_df index cannot contain NaT timestamps.")
    if not ohlcv_df.index.is_monotonic_increasing:
        raise InvalidOrderError(
            "ohlcv_df index must be sorted chronologically (non-decreasing)."
        )

    close_series = ohlcv_df["Close"]
    if pd.api.types.is_bool_dtype(close_series):
        raise InvalidOrderError("Close column cannot have boolean dtype.")

    closes: list[float] = []
    for raw_px in close_series.tolist():
        px = _require_finite_number(raw_px, "Close", InvalidOrderError)
        if px <= 0.0:
            raise InvalidOrderError(
                f"Close prices must be strictly positive, got {px}."
            )
        closes.append(px)
    return closes


def _extract_binary_signals(
    raw_signals: object, expected_index: pd.Index[Any]
) -> list[int]:
    """Validate aligned strategy output as strict binary {0, 1} integers."""
    if not isinstance(raw_signals, pd.Series) or raw_signals.empty:
        raise InvalidOrderError(
            "strategy.generate_signals must return a non-empty Series."
        )
    if not raw_signals.index.equals(expected_index):
        raise InvalidOrderError("Strategy signal index does not match ohlcv_df index.")
    if pd.api.types.is_bool_dtype(raw_signals):
        raise InvalidOrderError("Strategy signals cannot have boolean dtype.")

    parsed: list[int] = []
    for raw_sig in raw_signals.tolist():
        num_sig = _require_finite_number(raw_sig, "signal", InvalidOrderError)
        if num_sig not in (0.0, 1.0):
            raise InvalidOrderError(
                f"Strategy signals must be strictly 0 or 1, got {raw_sig!r}."
            )
        parsed.append(int(num_sig))
    return parsed


def _extract_latencies(
    expected_index: pd.Index[Any],
    *,
    latency_ms: float | None,
    latencies: pd.Series | None,
) -> list[float | None]:
    """Validate optional per-bar or scalar latency telemetry."""
    if latency_ms is not None and latencies is not None:
        raise ExecutionConfigurationError(
            "Specify either latency_ms or latencies, not both."
        )
    if latencies is not None:
        if not isinstance(latencies, pd.Series):
            raise InvalidOrderError("latencies must be a pandas Series.")
        if not latencies.index.equals(expected_index):
            raise InvalidOrderError(
                "latencies index must be strictly identical to ohlcv_df index."
            )
        if pd.api.types.is_bool_dtype(latencies):
            raise InvalidOrderError("latencies cannot have boolean dtype.")
        result: list[float | None] = []
        for raw_lat in latencies.tolist():
            lat = _require_finite_number(raw_lat, "latencies", InvalidOrderError)
            if lat < 0.0:
                raise InvalidOrderError(f"latencies cannot be negative, got {lat}.")
            result.append(lat)
        return result

    if latency_ms is not None:
        lat = _require_finite_number(latency_ms, "latency_ms", InvalidOrderError)
        if lat < 0.0:
            raise InvalidOrderError(f"latency_ms cannot be negative, got {lat}.")
        return [lat] * len(expected_index)

    return [None] * len(expected_index)


def _serialize_receipt(receipt: OrderReceipt) -> dict[str, Any]:
    """Convert an OrderReceipt into a JSON-serializable dictionary."""
    return {
        "broker_order_id": receipt.broker_order_id,
        "client_order_id": receipt.client_order_id,
        "ticker": receipt.ticker,
        "execution_symbol": receipt.execution_symbol,
        "side": receipt.side.value,
        "requested_shares": receipt.requested_shares,
        "filled_shares": receipt.filled_shares,
        "fill_price": receipt.fill_price,
        "b3_fee_paid": receipt.b3_fee_paid,
        "status": receipt.status.value,
        "submitted_at": receipt.submitted_at.isoformat(),
        "filled_at": receipt.filled_at.isoformat() if receipt.filled_at else None,
        "message": receipt.message,
    }


def _serialize_account(account: AccountSnapshot) -> dict[str, Any]:
    """Convert an AccountSnapshot into a JSON-serializable dictionary."""
    return {
        "cash": account.cash,
        "equity": account.equity,
        "realized_pnl": account.realized_pnl,
        "total_fees_paid": account.total_fees_paid,
        "timestamp": account.timestamp.isoformat(),
        "positions": {
            t: {
                "ticker": pos.ticker,
                "shares": pos.shares,
                "avg_entry_price": pos.avg_entry_price,
                "entry_date": pos.entry_date.isoformat(),
                "market_price": pos.market_price,
                "unrealized_pnl": pos.unrealized_pnl,
            }
            for t, pos in account.positions.items()
        },
        "open_orders": [_serialize_receipt(order) for order in account.open_orders],
    }


def _compute_max_drawdown_pct(equities: list[float], initial_equity: float) -> float:
    """Compute non-positive maximum drawdown percentage relative to running peak."""
    if not equities:
        return 0.0
    peak = initial_equity
    worst = 0.0
    for eq in equities:
        peak = max(peak, eq)
        if peak > 0.0:
            dd = ((eq - peak) / peak) * 100.0
            worst = min(worst, dd)
    return round(worst, 2)


@dataclass(frozen=True)
class PaperSimulationReport:
    """Consolidated report and equity history of a paper trading simulation run."""

    ticker: str
    initial_cash: float
    final_cash: float
    final_equity: float
    total_return_pct: float
    benchmark_return_pct: float
    max_drawdown_pct: float
    realized_pnl: float
    total_fees_paid: float
    total_orders: int
    filled_orders: int
    trading_days: int
    halted: bool
    halt_count: int
    final_account: AccountSnapshot
    receipts: list[OrderReceipt]
    steps: list[ExecutionStepResult]
    equity_curve: pd.DataFrame

    def summary(self) -> str:
        """Return a formatted quantitative summary of the paper simulation."""
        status_label = (
            f"HALTED ({self.halt_count} halt event(s))" if self.halted else "ACTIVE"
        )
        lines = [
            "=" * 64,
            f"        PAPER TRADING SIMULATION REPORT: {self.ticker}",
            "=" * 64,
            f"Trading Days Evaluated:    {self.trading_days}",
            f"Initial Cash / Capital:    R$ {self.initial_cash:.2f}",
            f"Final Equity (MTM):        R$ {self.final_equity:.2f}",
            f"Final Residual Cash:       R$ {self.final_cash:.2f}",
            "-" * 64,
            f"Strategy Total Return:     {self.total_return_pct:+.2f}%",
            f"Buy & Hold Benchmark:      {self.benchmark_return_pct:+.2f}%",
            f"Max Drawdown:              {self.max_drawdown_pct:.2f}%",
            "-" * 64,
            f"Realized PnL:              R$ {self.realized_pnl:+.2f}",
            f"Total B3 Fees Paid:        R$ {self.total_fees_paid:.4f}",
            f"Orders (Filled / Total):   {self.filled_orders} / {self.total_orders}",
            f"Kill-Switch Status:        {status_label}",
            "=" * 64,
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serialize summary metrics, receipts, account state, and equity curve."""
        curve_records: list[dict[str, Any]] = []
        for idx, row in self.equity_curve.iterrows():
            ts_str = (
                idx.isoformat()
                if isinstance(idx, (datetime, pd.Timestamp))
                else str(idx)
            )
            curve_records.append(
                {
                    "timestamp": ts_str,
                    "close": float(row["Close"]),
                    "signal": int(row["Signal"]),
                    "action": str(row["Action"]),
                    "shares": int(row["Shares"]),
                    "cash": float(row["Cash"]),
                    "position_value": float(row["Position_Value"]),
                    "equity": float(row["Equity"]),
                    "benchmark_equity": float(row["Benchmark_Equity"]),
                    "drawdown_pct": float(row["Drawdown"]),
                    "fees_paid": float(row["Fees_Paid"]),
                    "realized_pnl": float(row["Realized_PnL"]),
                    "halted": bool(row["Halted"]),
                    "latency_ms": float(row["Latency_Ms"]),
                }
            )
        return {
            "schema_version": _LEDGER_SCHEMA_VERSION,
            "ticker": self.ticker,
            "initial_cash": self.initial_cash,
            "final_cash": self.final_cash,
            "final_equity": self.final_equity,
            "total_return_pct": self.total_return_pct,
            "benchmark_return_pct": self.benchmark_return_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
            "realized_pnl": self.realized_pnl,
            "total_fees_paid": self.total_fees_paid,
            "total_orders": self.total_orders,
            "filled_orders": self.filled_orders,
            "trading_days": self.trading_days,
            "halted": self.halted,
            "halt_count": self.halt_count,
            "final_account": _serialize_account(self.final_account),
            "receipts": [_serialize_receipt(rec) for rec in self.receipts],
            "equity_curve": curve_records,
        }


class PaperTradingRunner:
    """Orchestrates live-step and historical Strategy -> Risk -> OrderRouter runs."""

    def __init__(
        self,
        broker: IBrokerAdapter | None = None,
        risk_manager: RiskManager | None = None,
        config: ExecutionConfig | None = None,
        router: OrderRouter | None = None,
        *,
        ledger_path: Path | str | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialize PaperTradingRunner with validated execution dependencies."""
        if router is not None and not isinstance(router, OrderRouter):
            raise ExecutionConfigurationError(
                "router must be an OrderRouter instance or None."
            )
        if broker is not None and not isinstance(broker, IBrokerAdapter):
            raise ExecutionConfigurationError(
                "broker must implement the IBrokerAdapter interface or be None."
            )
        if risk_manager is not None and not isinstance(risk_manager, RiskManager):
            raise ExecutionConfigurationError(
                "risk_manager must be a RiskManager instance or None."
            )
        if config is not None and not isinstance(config, ExecutionConfig):
            raise ExecutionConfigurationError(
                "config must be an ExecutionConfig instance or None."
            )
        if sleep_fn is not None and not callable(sleep_fn):
            raise ExecutionConfigurationError("sleep_fn must be callable or None.")
        if clock is not None and not callable(clock):
            raise ExecutionConfigurationError("clock must be callable or None.")

        self.ledger_path = _coerce_optional_path(ledger_path, "ledger_path")
        self._clock: Callable[[], datetime] = clock or _utc_now

        if router is not None:
            if broker is not None and broker is not router.broker:
                raise ExecutionConfigurationError(
                    "broker conflicts with the provided router.broker instance."
                )
            if risk_manager is not None and risk_manager is not router.risk_manager:
                raise ExecutionConfigurationError(
                    "risk_manager conflicts with the provided router.risk_manager instance."
                )
            if config is not None and config != router.config:
                raise ExecutionConfigurationError(
                    "config conflicts with the provided router.config settings."
                )
            self.router = router
            self.broker = router.broker
            self.risk_manager = router.risk_manager
            self.config = router.config
            return

        resolved_config = config or ExecutionConfig()
        resolved_broker = broker or SimulatedPaperBroker(
            config=resolved_config, clock=clock
        )
        resolved_risk = risk_manager or RiskManager(
            RiskConfig(
                initial_capital=resolved_config.initial_cash,
                b3_fee_pct=resolved_config.b3_fee_pct,
            )
        )
        self.config = resolved_config
        self.broker = resolved_broker
        self.risk_manager = resolved_risk
        self.router = OrderRouter(
            broker=resolved_broker,
            risk_manager=resolved_risk,
            config=resolved_config,
            sleep_fn=sleep_fn,
            clock=clock,
        )

    @property
    def last_snapshot(self) -> AccountSnapshot | None:
        """Return the latest synchronized broker account snapshot, if any."""
        return self.router.last_snapshot

    def sync_account(
        self, market_prices: dict[str, float] | None = None
    ) -> tuple[AccountSnapshot, float]:
        """Synchronize broker account snapshot and ping latency through OrderRouter."""
        return self.router.sync_account(market_prices=market_prices)

    def step(
        self,
        *,
        ticker: str,
        signal: int,
        price: float,
        timestamp: datetime | None = None,
        order_type: OrderType = OrderType.MARKET,
        limit_price: float | None = None,
        stop_loss_price: float | None = None,
        is_emergency: bool = False,
        market_prices: dict[str, float] | None = None,
        client_order_id: str | None = None,
        latency_ms: float | None = None,
    ) -> ExecutionStepResult:
        """Execute a single live or replayed signal step strictly gated by RiskManager.

        Raises:
            InvalidOrderError: On invalid prices or malformed inputs (fail-closed).
            BrokerConnectionError: When connectivity retries are exhausted.
            ExecutionHaltedError: Whenever Kill-Switch trips to HALTED.
        """
        clean_ticker = _require_non_empty_str(ticker, "ticker", InvalidOrderError)
        valid_price = _require_finite_number(price, "price", InvalidOrderError)
        if valid_price <= 0.0:
            raise InvalidOrderError(
                f"price must be strictly positive, got {valid_price}."
            )
        validated_mtm = OrderRouter._validate_market_prices(market_prices)
        validated_mtm.setdefault(clean_ticker, valid_price)

        step_ts = self._clock() if timestamp is None else timestamp
        if isinstance(self.broker, SimulatedPaperBroker) and self.broker.is_connected():
            self.broker.update_market_prices(validated_mtm)

        return self.router.process_signal(
            ticker=clean_ticker,
            signal=signal,
            price=valid_price,
            timestamp=step_ts,
            order_type=order_type,
            limit_price=limit_price,
            stop_loss_price=stop_loss_price,
            is_emergency=is_emergency,
            market_prices=validated_mtm,
            client_order_id=client_order_id,
            latency_ms=latency_ms,
        )

    def run_simulation(
        self,
        ohlcv_df: pd.DataFrame,
        strategy: BaseStrategy,
        ticker: str = "ATIVO",
        *,
        order_type: OrderType = OrderType.MARKET,
        slice_warmup: bool = True,
        raise_on_halt: bool = False,
        suppress_reentry_after_exit: bool = True,
        latency_ms: float | None = None,
        latencies: pd.Series | None = None,
        ledger_path: Path | str | None = None,
    ) -> PaperSimulationReport:
        """Run bar-by-bar Strategy -> RiskManager -> OrderRouter paper simulation.

        Raises:
            ExecutionConfigurationError: On invalid runner or latency options.
            InvalidOrderError: On corrupted OHLCV data, prices, or signals.
            InsufficientDataError: When OHLCV length is below strategy warm-up.
            ExecutionHaltedError: When `raise_on_halt=True` and Kill-Switch trips.
        """
        clean_ticker = _require_non_empty_str(ticker, "ticker", InvalidOrderError)
        if not isinstance(strategy, BaseStrategy):
            raise ExecutionConfigurationError(
                "strategy must be a BaseStrategy subclass instance."
            )
        if not isinstance(order_type, OrderType):
            raise InvalidOrderError("order_type must be a valid OrderType enum member.")
        _require_bool(slice_warmup, "slice_warmup", ExecutionConfigurationError)
        _require_bool(raise_on_halt, "raise_on_halt", ExecutionConfigurationError)
        _require_bool(
            suppress_reentry_after_exit,
            "suppress_reentry_after_exit",
            ExecutionConfigurationError,
        )
        target_ledger = (
            _coerce_optional_path(ledger_path, "ledger_path")
            if ledger_path is not None
            else self.ledger_path
        )

        _validate_ohlcv_for_simulation(ohlcv_df)
        bar_latencies_full = _extract_latencies(
            ohlcv_df.index, latency_ms=latency_ms, latencies=latencies
        )
        raw_signals = strategy.generate_signals(ohlcv_df)
        signals_full = _extract_binary_signals(raw_signals, ohlcv_df.index)

        slow_window = (
            strategy.slow_period if isinstance(strategy, EMACrossoverStrategy) else 1
        )
        start_idx = (slow_window - 1) if slice_warmup else 0
        if start_idx >= len(ohlcv_df):
            raise InsufficientDataError(
                f"OHLCV series has {len(ohlcv_df)} rows, insufficient for warm-up {slow_window}."
            )

        sliced_ohlcv = ohlcv_df.iloc[start_idx:]
        sliced_closes = [float(px) for px in sliced_ohlcv["Close"].tolist()]
        sliced_signals = signals_full[start_idx:]
        sliced_latencies = bar_latencies_full[start_idx:]

        initial_account, _ = self.router.sync_account(
            market_prices={clean_ticker: sliced_closes[0]}
        )
        initial_cash = initial_account.cash
        initial_equity = initial_account.equity
        benchmark_start = sliced_closes[0]

        sim_clock = {"now": pd.Timestamp(sliced_ohlcv.index[0]).to_pydatetime()}
        clock_ctx: AbstractContextManager[None] = (
            self.broker.temporary_clock(lambda: sim_clock["now"])
            if isinstance(self.broker, SimulatedPaperBroker)
            and not self.broker.has_custom_clock
            else nullcontext()
        )

        receipts: list[OrderReceipt] = []
        seen_cids: set[str] = (
            {rec.client_order_id for rec in self.broker.order_history}
            if isinstance(self.broker, SimulatedPaperBroker)
            else set()
        )
        steps: list[ExecutionStepResult] = []
        rows: list[dict[str, Any]] = []

        suppressed = False
        halted = False
        permanently_halted = False
        halt_count = 0
        last_halt_date: date | None = None

        with clock_ctx:
            for ts, close_px, raw_sig, bar_lat in zip(
                sliced_ohlcv.index,
                sliced_closes,
                sliced_signals,
                sliced_latencies,
                strict=True,
            ):
                bar_dt = pd.Timestamp(ts).to_pydatetime()
                sim_clock["now"] = bar_dt
                bar_date = bar_dt.date()

                if raw_sig == 0:
                    suppressed = False

                same_day_after_halt = (
                    last_halt_date is not None and bar_date == last_halt_date
                )
                if permanently_halted or same_day_after_halt:
                    post_step, post_row = self._record_post_halt_bar(
                        ticker=clean_ticker,
                        raw_signal=raw_sig,
                        close_price=close_px,
                        bar_dt=bar_dt,
                        bar_latency=bar_lat,
                        initial_equity=initial_equity,
                        benchmark_start=benchmark_start,
                    )
                    steps.append(post_step)
                    rows.append(post_row)
                    continue

                effective_sig = (
                    0
                    if (suppress_reentry_after_exit and suppressed and raw_sig == 1)
                    else raw_sig
                )
                if (
                    isinstance(self.broker, SimulatedPaperBroker)
                    and self.broker.is_connected()
                ):
                    self.broker.update_market_prices({clean_ticker: close_px})

                try:
                    step_res = self.router.process_signal(
                        ticker=clean_ticker,
                        signal=effective_sig,
                        price=close_px,
                        timestamp=bar_dt,
                        order_type=order_type,
                        limit_price=close_px if order_type == OrderType.LIMIT else None,
                        market_prices={clean_ticker: close_px},
                        latency_ms=bar_lat,
                    )
                    self._collect_new_receipts(
                        receipts, seen_cids, step_res.order_receipt
                    )
                    if (
                        suppress_reentry_after_exit
                        and raw_sig == 1
                        and step_res.verdict.action == "EXIT"
                        and step_res.verdict.reason.startswith(
                            "Emergency exit approved"
                        )
                    ):
                        suppressed = True
                    steps.append(step_res)
                    rows.append(
                        self._build_curve_row(
                            ticker=clean_ticker,
                            raw_signal=raw_sig,
                            action=step_res.verdict.action,
                            close_price=close_px,
                            account=step_res.account,
                            halted=False,
                            latency_ms=step_res.latency_ms,
                            initial_equity=initial_equity,
                            benchmark_start=benchmark_start,
                        )
                    )
                except ExecutionHaltedError:
                    if raise_on_halt:
                        raise
                    halted = True
                    halt_count += 1
                    last_halt_date = bar_date
                    if suppress_reentry_after_exit and raw_sig == 1:
                        suppressed = True
                    ks_state = self.risk_manager.kill_switch.state
                    if ks_state.reason != HaltReason.DAILY_LOSS_LIMIT:
                        permanently_halted = True
                    self._collect_new_receipts(receipts, seen_cids, None)
                    post_step, post_row = self._record_post_halt_bar(
                        ticker=clean_ticker,
                        raw_signal=raw_sig,
                        close_price=close_px,
                        bar_dt=bar_dt,
                        bar_latency=bar_lat,
                        initial_equity=initial_equity,
                        benchmark_start=benchmark_start,
                    )
                    steps.append(post_step)
                    rows.append(post_row)

        if isinstance(self.broker, SimulatedPaperBroker):
            self.broker.save_state()

        equity_curve = self._build_equity_dataframe(
            rows=rows,
            index=sliced_ohlcv.index,
            initial_equity=initial_equity,
        )
        final_account = steps[-1].account
        final_equity = final_account.equity
        total_return_pct = (
            ((final_equity / initial_equity) - 1.0) * 100.0
            if initial_equity > 0.0
            else 0.0
        )
        benchmark_return_pct = (
            ((sliced_closes[-1] / benchmark_start) - 1.0) * 100.0
            if benchmark_start > 0.0
            else 0.0
        )
        max_dd_pct = _compute_max_drawdown_pct(
            [float(r["Equity"]) for r in rows],
            initial_equity=initial_equity,
        )
        filled_orders = sum(1 for r in receipts if r.status == OrderStatus.FILLED)

        report = PaperSimulationReport(
            ticker=clean_ticker,
            initial_cash=initial_cash,
            final_cash=final_account.cash,
            final_equity=final_equity,
            total_return_pct=round(total_return_pct, 2),
            benchmark_return_pct=round(benchmark_return_pct, 2),
            max_drawdown_pct=max_dd_pct,
            realized_pnl=final_account.realized_pnl,
            total_fees_paid=final_account.total_fees_paid,
            total_orders=len(receipts),
            filled_orders=filled_orders,
            trading_days=len(sliced_ohlcv),
            halted=halted,
            halt_count=halt_count,
            final_account=final_account,
            receipts=receipts,
            steps=steps,
            equity_curve=equity_curve,
        )
        if target_ledger is not None:
            self.save_ledger(report, target_ledger)
        return report

    def save_ledger(
        self, report: PaperSimulationReport, path: Path | str | None = None
    ) -> Path:
        """Persist simulation ledger atomically as JSON or Parquet."""
        if not isinstance(report, PaperSimulationReport):
            raise ExecutionConfigurationError(
                "report must be a PaperSimulationReport instance."
            )
        target = (
            _coerce_optional_path(path, "ledger_path")
            if path is not None
            else self.ledger_path
        )
        if target is None:
            raise ExecutionConfigurationError(
                "ledger_path must be configured or provided to save_ledger()."
            )
        if target.suffix.lower() == ".parquet":
            _atomic_write_via_path(
                target, lambda tmp: report.equity_curve.to_parquet(tmp)
            )
        else:
            payload = json.dumps(report.to_dict(), indent=2, sort_keys=True)
            _atomic_write_text(target, payload)
        return target

    # ------------------------------------------------------------------
    # Internal step/row collection helpers
    # ------------------------------------------------------------------

    def _collect_new_receipts(
        self,
        receipts: list[OrderReceipt],
        seen_cids: set[str],
        step_receipt: OrderReceipt | None,
    ) -> None:
        if isinstance(self.broker, SimulatedPaperBroker):
            for rec in self.broker.order_history:
                if rec.client_order_id not in seen_cids:
                    seen_cids.add(rec.client_order_id)
                    receipts.append(rec)
            return
        if step_receipt is not None and step_receipt.client_order_id not in seen_cids:
            seen_cids.add(step_receipt.client_order_id)
            receipts.append(step_receipt)

    def _record_post_halt_bar(
        self,
        *,
        ticker: str,
        raw_signal: int,
        close_price: float,
        bar_dt: datetime,
        bar_latency: float | None,
        initial_equity: float,
        benchmark_start: float,
    ) -> tuple[ExecutionStepResult, dict[str, Any]]:
        if isinstance(self.broker, SimulatedPaperBroker) and self.broker.is_connected():
            self.broker.update_market_prices({ticker: close_price})
        account = self.broker.get_account_snapshot(market_prices={ticker: close_price})
        ks_state = self.risk_manager.kill_switch.state
        halt_verdict = RiskVerdict(
            approved=False,
            action="HALT",
            shares=0,
            weight=0.0,
            kill_switch_state=ks_state,
            reason=f"Kill-Switch {ks_state.reason.value}: {ks_state.message}",
        )
        resolved_lat = (
            float(bar_latency)
            if bar_latency is not None
            else float(ks_state.last_latency_ms)
        )
        step = ExecutionStepResult(
            ticker=ticker,
            signal=raw_signal,
            verdict=halt_verdict,
            order_receipt=None,
            account=account,
            halted=True,
            cancelled_orders_count=0,
            latency_ms=resolved_lat,
            timestamp=bar_dt,
        )
        row = self._build_curve_row(
            ticker=ticker,
            raw_signal=raw_signal,
            action="HALT",
            close_price=close_price,
            account=account,
            halted=True,
            latency_ms=resolved_lat,
            initial_equity=initial_equity,
            benchmark_start=benchmark_start,
        )
        return step, row

    @staticmethod
    def _build_curve_row(
        *,
        ticker: str,
        raw_signal: int,
        action: str,
        close_price: float,
        account: AccountSnapshot,
        halted: bool,
        latency_ms: float,
        initial_equity: float,
        benchmark_start: float,
    ) -> dict[str, Any]:
        pos = account.positions.get(ticker)
        held_shares = pos.shares if pos is not None else 0
        pos_value = held_shares * close_price
        benchmark_eq = (
            initial_equity * (close_price / benchmark_start)
            if benchmark_start > 0.0
            else initial_equity
        )
        return {
            "Close": close_price,
            "Signal": raw_signal,
            "Action": action,
            "Shares": held_shares,
            "Cash": account.cash,
            "Position_Value": pos_value,
            "Equity": account.equity,
            "Benchmark_Equity": benchmark_eq,
            "Drawdown": 0.0,
            "Fees_Paid": account.total_fees_paid,
            "Realized_PnL": account.realized_pnl,
            "Halted": halted,
            "Latency_Ms": latency_ms,
        }

    @staticmethod
    def _build_equity_dataframe(
        *,
        rows: list[dict[str, Any]],
        index: pd.Index[Any],
        initial_equity: float,
    ) -> pd.DataFrame:
        peak = initial_equity
        for row in rows:
            eq = float(row["Equity"])
            peak = max(peak, eq)
            dd = (
                ((eq - peak) / peak) * 100.0
                if peak > 0.0 and not math.isclose(peak, 0.0)
                else 0.0
            )
            row["Drawdown"] = dd
        return pd.DataFrame(rows, index=index)

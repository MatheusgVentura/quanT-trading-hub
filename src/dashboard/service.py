"""Headless dashboard orchestration service and safe Phase 5 ledger loader."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.backtest.engine import VectorizedBacktestEngine
from src.backtest.models import BacktestConfig
from src.dashboard.exceptions import (
    DashboardDataError,
    DashboardError,
    LedgerLoadError,
)
from src.dashboard.models import (
    MAX_LEDGER_BYTES,
    DashboardParameters,
    DashboardSnapshot,
    LoadedLedgerSummary,
    RiskTelemetrySnapshot,
    validate_ticker_symbol,
)
from src.data.cache import DataCacheManager
from src.data.interfaces import IDataProvider
from src.data.yfinance_provider import YFinanceDataProvider
from src.execution.models import format_b3_execution_symbol
from src.execution.paper_broker import SimulatedPaperBroker
from src.execution.runner import PaperSimulationReport, PaperTradingRunner
from src.risk.manager import RiskManager
from src.risk.models import HaltReason, RiskStatus
from src.strategies.ema_crossover import EMACrossoverStrategy
from src.strategies.runner import StrategyBacktestRunner

_LEDGER_SCHEMA_VERSION = 1

_REQUIRED_LEDGER_CURVE_KEYS = (
    "timestamp",
    "close",
    "signal",
    "action",
    "shares",
    "cash",
    "position_value",
    "equity",
    "benchmark_equity",
    "drawdown_pct",
    "fees_paid",
    "realized_pnl",
    "halted",
    "latency_ms",
)

_RECEIPT_COLUMNS = [
    "broker_order_id",
    "client_order_id",
    "ticker",
    "execution_symbol",
    "side",
    "requested_shares",
    "filled_shares",
    "fill_price",
    "b3_fee_paid",
    "status",
    "submitted_at",
    "filled_at",
    "message",
]


def _utc_now() -> datetime:
    """Return UTC-aware timestamp compatible with Python 3.10."""
    return datetime.now(timezone.utc)  # noqa: UP017


def _reject_non_finite_json(constant: str) -> object:
    """Reject non-standard NaN/Infinity literals during JSON parsing."""
    raise LedgerLoadError(f"Non-finite JSON constant {constant!r} is not allowed.")


def _require_ledger_finite(payload: dict[str, Any], key: str) -> float:
    """Extract and validate a required non-boolean finite float from a ledger dict."""
    if key not in payload:
        raise LedgerLoadError(f"Missing required numeric ledger field: {key!r}.")
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LedgerLoadError(f"Ledger field {key!r} must be numeric.")
    num = float(value)
    if not math.isfinite(num):
        raise LedgerLoadError(f"Ledger field {key!r} must be finite.")
    return num


def _require_ledger_int(payload: dict[str, Any], key: str, *, min_val: int = 0) -> int:
    """Extract and validate a required non-boolean integer from a ledger dict."""
    if key not in payload:
        raise LedgerLoadError(f"Missing required integer ledger field: {key!r}.")
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise LedgerLoadError(f"Ledger field {key!r} must be an integer.")
    if value < min_val:
        raise LedgerLoadError(f"Ledger field {key!r} must be >= {min_val}.")
    return value


def _require_ledger_bool(payload: dict[str, Any], key: str) -> bool:
    """Extract and validate a required boolean field from a ledger dict."""
    if key not in payload:
        raise LedgerLoadError(f"Missing required boolean ledger field: {key!r}.")
    value = payload[key]
    if not isinstance(value, bool):
        raise LedgerLoadError(f"Ledger field {key!r} must be a boolean.")
    return value


def _validate_ohlcv_frame(ohlcv_df: object, ticker: str) -> pd.DataFrame:
    """Ensure fetched market DataFrame is non-empty and exposes valid Close/OHLC."""
    if not isinstance(ohlcv_df, pd.DataFrame) or ohlcv_df.empty:
        raise DashboardDataError(f"Market data for {ticker} is empty or missing.")
    if "Close" not in ohlcv_df.columns:
        raise DashboardDataError(
            f"Market data for {ticker} is missing required 'Close' column."
        )
    if not isinstance(ohlcv_df.index, pd.DatetimeIndex):
        raise DashboardDataError(
            f"Market data index for {ticker} must be a DatetimeIndex."
        )
    return ohlcv_df.sort_index()


def _build_indicators_frame(
    ohlcv_df: pd.DataFrame,
    raw_signals: pd.Series,
    *,
    fast_period: int,
    slow_period: int,
) -> pd.DataFrame:
    """Attach EMA_Fast, EMA_Slow, and Signal columns matching EMACrossoverStrategy."""
    enriched = ohlcv_df.copy()
    close = enriched["Close"].astype(float)
    enriched["EMA_Fast"] = close.ewm(
        span=fast_period, min_periods=slow_period, adjust=False
    ).mean()
    enriched["EMA_Slow"] = close.ewm(
        span=slow_period, min_periods=slow_period, adjust=False
    ).mean()
    enriched["Signal"] = raw_signals.astype(int)
    return enriched


def _extract_trade_markers(equity_curve: pd.DataFrame) -> pd.DataFrame:
    """Extract executed BUY, EXIT, and HALT events from a paper equity curve."""
    columns = ["Timestamp", "Close", "Action", "Shares", "Cash", "Equity"]
    if equity_curve.empty or "Action" not in equity_curve.columns:
        return pd.DataFrame(columns=columns)

    markers_df = equity_curve[
        equity_curve["Action"].isin(["BUY", "EXIT", "HALT"])
    ].copy()
    if markers_df.empty:
        return pd.DataFrame(columns=columns)

    markers_df = markers_df.reset_index()
    ts_col = markers_df.columns[0]
    markers_df = markers_df.rename(columns={ts_col: "Timestamp"})
    return markers_df[columns].reset_index(drop=True)


def _compute_daily_pnl_pct(paper_report: PaperSimulationReport) -> float:
    """Compute final session daily PnL percentage from paper equity curve."""
    curve = paper_report.equity_curve
    if curve.empty or "Equity" not in curve.columns:
        return 0.0
    if len(curve) < 2:
        prev_eq = paper_report.initial_cash
    else:
        prev_eq = float(curve["Equity"].iloc[-2])
    last_eq = float(curve["Equity"].iloc[-1])
    if prev_eq <= 0.0:
        return 0.0
    return (last_eq / prev_eq) - 1.0


def _build_telemetry_snapshot(
    params: DashboardParameters,
    paper_report: PaperSimulationReport,
    kill_switch_status: RiskStatus,
    halt_reason: HaltReason,
    observed_latency_ms: float,
) -> RiskTelemetrySnapshot:
    """Build consolidated Risk & Kill-Switch Telemetry Strip snapshot."""
    final_acc = paper_report.final_account
    pos = final_acc.positions.get(params.ticker)
    open_shares = pos.shares if pos is not None else 0
    exec_symbol = params.display_fractional_symbol(shares=max(1, open_shares))
    last_ts = (
        paper_report.steps[-1].timestamp if paper_report.steps else final_acc.timestamp
    )
    daily_pnl_pct = _compute_daily_pnl_pct(paper_report)
    dd_pct = paper_report.max_drawdown_pct / 100.0
    if not paper_report.equity_curve.empty and "Drawdown" in paper_report.equity_curve:
        dd_pct = float(paper_report.equity_curve["Drawdown"].iloc[-1]) / 100.0

    return RiskTelemetrySnapshot(
        ticker=params.ticker,
        execution_symbol=exec_symbol,
        kill_switch_status=kill_switch_status,
        halt_reason=halt_reason,
        daily_pnl_pct=daily_pnl_pct,
        max_daily_loss_limit_pct=params.max_daily_loss_pct,
        current_drawdown_pct=dd_pct,
        max_drawdown_limit_pct=params.max_drawdown_pct,
        observed_latency_ms=observed_latency_ms,
        max_latency_limit_ms=params.max_latency_ms,
        allow_day_trade=params.allow_day_trade,
        open_shares=open_shares,
        cash_balance=final_acc.cash,
        total_equity=final_acc.equity,
        last_updated=last_ts,
    )


def _parse_receipt_records(raw_records: object, field_name: str) -> pd.DataFrame:
    """Validate and convert serialized receipt dictionaries into a DataFrame."""
    if not isinstance(raw_records, list):
        raise LedgerLoadError(f"Ledger field {field_name!r} must be a list.")
    rows: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_records):
        if not isinstance(item, dict):
            raise LedgerLoadError(
                f"Ledger entry {field_name}[{idx}] must be an object."
            )
        req_shares = _require_ledger_int(item, "requested_shares", min_val=0)
        fill_shares = _require_ledger_int(item, "filled_shares", min_val=0)
        fee = _require_ledger_finite(item, "b3_fee_paid")
        fill_price_raw = item.get("fill_price")
        fill_price: float | None = None
        if fill_price_raw is not None:
            if isinstance(fill_price_raw, bool) or not isinstance(
                fill_price_raw, (int, float)
            ):
                raise LedgerLoadError(
                    f"Ledger entry {field_name}[{idx}].fill_price must be numeric or null."
                )
            fill_price = float(fill_price_raw)
            if not math.isfinite(fill_price) or fill_price <= 0.0:
                raise LedgerLoadError(
                    f"Ledger entry {field_name}[{idx}].fill_price must be finite and > 0."
                )
        rows.append(
            {
                "broker_order_id": str(item.get("broker_order_id", "")),
                "client_order_id": str(item.get("client_order_id", "")),
                "ticker": str(item.get("ticker", "")),
                "execution_symbol": str(item.get("execution_symbol", "")),
                "side": str(item.get("side", "")),
                "requested_shares": req_shares,
                "filled_shares": fill_shares,
                "fill_price": fill_price,
                "b3_fee_paid": fee,
                "status": str(item.get("status", "")),
                "submitted_at": str(item.get("submitted_at", "")),
                "filled_at": (
                    str(item["filled_at"]) if item.get("filled_at") is not None else ""
                ),
                "message": str(item.get("message", "")),
            }
        )
    if not rows:
        return pd.DataFrame(columns=_RECEIPT_COLUMNS)
    return pd.DataFrame(rows, columns=_RECEIPT_COLUMNS)


def _parse_equity_curve(raw_curve: object) -> pd.DataFrame:
    """Validate and convert serialized Phase 5 equity curve records to DataFrame."""
    if not isinstance(raw_curve, list) or not raw_curve:
        raise LedgerLoadError(
            "Ledger field 'equity_curve' must be a non-empty list of bar records."
        )

    parsed_rows: list[dict[str, Any]] = []
    timestamps: list[pd.Timestamp] = []
    for idx, row in enumerate(raw_curve):
        if not isinstance(row, dict):
            raise LedgerLoadError(f"equity_curve[{idx}] must be a JSON object.")
        missing = [k for k in _REQUIRED_LEDGER_CURVE_KEYS if k not in row]
        if missing:
            raise LedgerLoadError(
                f"equity_curve[{idx}] missing required keys: {', '.join(missing)}."
            )
        try:
            ts = pd.Timestamp(str(row["timestamp"]))
            if pd.isna(ts):
                raise ValueError("NaT timestamp")
        except (ValueError, TypeError) as exc:
            raise LedgerLoadError(
                f"equity_curve[{idx}] contains invalid timestamp {row['timestamp']!r}."
            ) from exc

        timestamps.append(ts)
        parsed_rows.append(
            {
                "Close": _require_ledger_finite(row, "close"),
                "Signal": _require_ledger_int(row, "signal", min_val=0),
                "Action": str(row["action"]),
                "Shares": _require_ledger_int(row, "shares", min_val=0),
                "Cash": _require_ledger_finite(row, "cash"),
                "Position_Value": _require_ledger_finite(row, "position_value"),
                "Equity": _require_ledger_finite(row, "equity"),
                "Benchmark_Equity": _require_ledger_finite(row, "benchmark_equity"),
                "Drawdown": _require_ledger_finite(row, "drawdown_pct"),
                "Fees_Paid": _require_ledger_finite(row, "fees_paid"),
                "Realized_PnL": _require_ledger_finite(row, "realized_pnl"),
                "Halted": _require_ledger_bool(row, "halted"),
                "Latency_Ms": _require_ledger_finite(row, "latency_ms"),
            }
        )

    df = pd.DataFrame(parsed_rows, index=pd.DatetimeIndex(timestamps, name="Date"))
    return df.sort_index()


def parse_ledger_payload(
    payload: object, *, source_name: str = "ledger.json"
) -> LoadedLedgerSummary:
    """Validate and construct a LoadedLedgerSummary from a decoded JSON dict."""
    if not isinstance(payload, dict):
        raise LedgerLoadError("Ledger JSON root must be a JSON object.")

    version = _require_ledger_int(payload, "schema_version", min_val=1)
    if version != _LEDGER_SCHEMA_VERSION:
        raise LedgerLoadError(
            f"Unsupported ledger schema_version={version}; expected {_LEDGER_SCHEMA_VERSION}."
        )

    try:
        clean_ticker = validate_ticker_symbol(payload.get("ticker"))
    except DashboardError as exc:
        raise LedgerLoadError(f"Invalid ledger ticker: {exc}") from exc

    initial_cash = _require_ledger_finite(payload, "initial_cash")
    final_cash = _require_ledger_finite(payload, "final_cash")
    final_equity = _require_ledger_finite(payload, "final_equity")
    if initial_cash <= 0.0 or final_cash < 0.0 or final_equity < 0.0:
        raise LedgerLoadError("Ledger cash and equity values violate domain bounds.")

    final_account = payload.get("final_account")
    if not isinstance(final_account, dict):
        raise LedgerLoadError("Ledger field 'final_account' must be a JSON object.")

    positions_raw = final_account.get("positions", {})
    if not isinstance(positions_raw, dict):
        raise LedgerLoadError("Ledger final_account.positions must be a JSON object.")

    positions: dict[str, dict[str, Any]] = {}
    for sym, pos_val in positions_raw.items():
        if not isinstance(pos_val, dict):
            raise LedgerLoadError(f"Position entry {sym!r} must be an object.")
        positions[str(sym)] = dict(pos_val)

    open_orders_df = _parse_receipt_records(
        final_account.get("open_orders", []), "final_account.open_orders"
    )
    receipts_df = _parse_receipt_records(payload.get("receipts"), "receipts")
    equity_curve_df = _parse_equity_curve(payload.get("equity_curve"))

    return LoadedLedgerSummary(
        source_name=source_name.strip() or "ledger.json",
        schema_version=version,
        ticker=clean_ticker,
        initial_cash=initial_cash,
        final_cash=final_cash,
        final_equity=final_equity,
        total_return_pct=_require_ledger_finite(payload, "total_return_pct"),
        benchmark_return_pct=_require_ledger_finite(payload, "benchmark_return_pct"),
        max_drawdown_pct=_require_ledger_finite(payload, "max_drawdown_pct"),
        realized_pnl=_require_ledger_finite(payload, "realized_pnl"),
        total_fees_paid=_require_ledger_finite(payload, "total_fees_paid"),
        total_orders=_require_ledger_int(payload, "total_orders", min_val=0),
        filled_orders=_require_ledger_int(payload, "filled_orders", min_val=0),
        trading_days=_require_ledger_int(payload, "trading_days", min_val=0),
        halted=_require_ledger_bool(payload, "halted"),
        halt_count=_require_ledger_int(payload, "halt_count", min_val=0),
        equity_curve=equity_curve_df,
        receipts=receipts_df,
        open_orders=open_orders_df,
        positions=positions,
    )


def load_ledger_json(
    source: Path | str | bytes | bytearray,
    *,
    source_name: str | None = None,
    allowed_dir: Path | None = None,
) -> LoadedLedgerSummary:
    """Load, size-check, and strictly validate a Phase 5 execution JSON ledger.

    Args:
        source: Filesystem path or raw UTF-8 JSON bytes from browser upload.
        source_name: Optional human-readable label for display.
        allowed_dir: Optional directory jail restricting local path lookups.

    Returns:
        Validated LoadedLedgerSummary ready for dashboard rendering.

    Raises:
        LedgerLoadError: On oversized payloads, path traversal, or invalid schemas.
    """
    if isinstance(source, (bytes, bytearray)):
        if len(source) > MAX_LEDGER_BYTES:
            raise LedgerLoadError(
                f"Ledger upload exceeds {MAX_LEDGER_BYTES // (1024 * 1024)} MB safety limit."
            )
        try:
            text = bytes(source).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LedgerLoadError("Ledger upload must be valid UTF-8 JSON.") from exc
        resolved_name = source_name or "uploaded_ledger.json"
    else:
        path = Path(source)
        if ".env" in path.name.lower():
            raise LedgerLoadError("Refusing access to environment secret files.")
        if allowed_dir is not None:
            resolved_path = path.resolve(strict=False)
            resolved_base = allowed_dir.resolve(strict=False)
            if not resolved_path.is_relative_to(resolved_base):
                raise LedgerLoadError(
                    f"Ledger path {path} escapes allowed directory {allowed_dir}."
                )
        if not path.exists() or not path.is_file():
            raise LedgerLoadError(f"Ledger file not found: {path}")
        size = path.stat().st_size
        if size > MAX_LEDGER_BYTES:
            raise LedgerLoadError(
                f"Ledger file exceeds {MAX_LEDGER_BYTES // (1024 * 1024)} MB safety limit."
            )
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise LedgerLoadError(f"Unable to read ledger file {path}: {exc}") from exc
        resolved_name = source_name or path.name

    try:
        payload = json.loads(text, parse_constant=_reject_non_finite_json)
    except json.JSONDecodeError as exc:
        raise LedgerLoadError(f"Invalid JSON syntax in ledger: {exc}") from exc

    return parse_ledger_payload(payload, source_name=resolved_name)


def telemetry_from_ledger(ledger: LoadedLedgerSummary) -> RiskTelemetrySnapshot:
    """Build a RiskTelemetrySnapshot from an inspected Phase 5 ledger summary."""
    pos_entry = ledger.positions.get(ledger.ticker, {})
    open_shares_raw = pos_entry.get("shares", 0)
    open_shares = open_shares_raw if isinstance(open_shares_raw, int) else 0
    exec_sym = format_b3_execution_symbol(
        ledger.ticker, shares=max(1, open_shares), use_fractional_suffix=True
    )
    curve = ledger.equity_curve
    last_ts = (
        curve.index[-1].to_pydatetime()
        if isinstance(curve.index, pd.DatetimeIndex) and not curve.empty
        else _utc_now()
    )
    last_latency = float(curve["Latency_Ms"].iloc[-1]) if not curve.empty else 0.0
    last_dd = float(curve["Drawdown"].iloc[-1]) / 100.0 if not curve.empty else 0.0
    daily_pnl_pct = 0.0
    if len(curve) >= 2 and float(curve["Equity"].iloc[-2]) > 0.0:
        daily_pnl_pct = (
            float(curve["Equity"].iloc[-1]) / float(curve["Equity"].iloc[-2])
        ) - 1.0

    return RiskTelemetrySnapshot(
        ticker=ledger.ticker,
        execution_symbol=exec_sym,
        kill_switch_status=RiskStatus.HALTED if ledger.halted else RiskStatus.ACTIVE,
        halt_reason=HaltReason.MAX_DRAWDOWN_LIMIT if ledger.halted else HaltReason.NONE,
        daily_pnl_pct=daily_pnl_pct,
        max_daily_loss_limit_pct=0.02,
        current_drawdown_pct=last_dd,
        max_drawdown_limit_pct=0.10,
        observed_latency_ms=max(0.0, last_latency),
        max_latency_limit_ms=500.0,
        allow_day_trade=False,
        open_shares=max(0, open_shares),
        cash_balance=ledger.final_cash,
        total_equity=ledger.final_equity,
        last_updated=last_ts,
    )


class DashboardService:
    """Headless analytics orchestrator unifying Data, Strategy, Risk, and Paper layers."""

    def __init__(
        self,
        data_provider: IDataProvider | None = None,
        cache_dir: str = ".cache/data",
    ) -> None:
        """Initialize service with optional injectable IDataProvider and cache path."""
        self._injected_provider = data_provider
        self._cache_dir = cache_dir

    def _resolve_provider(self, use_cache: bool) -> IDataProvider:
        if self._injected_provider is not None:
            return self._injected_provider
        cache = DataCacheManager(cache_dir=self._cache_dir) if use_cache else None
        return YFinanceDataProvider(cache_manager=cache)

    def run_analysis(self, params: DashboardParameters) -> DashboardSnapshot:
        """Execute full Strategy, Risk Overlay, and Paper Trading analytics pipeline."""
        provider = self._resolve_provider(params.use_cache)
        raw_df = provider.fetch_ohlcv(
            ticker=params.ticker,
            start_date=params.start_date.isoformat() if params.start_date else None,
            end_date=params.end_date.isoformat() if params.end_date else None,
            period=None if params.start_date is not None else params.period,
            interval="1d",
        )
        ohlcv_df = _validate_ohlcv_frame(raw_df, params.ticker)

        strategy = EMACrossoverStrategy(
            fast_period=params.fast_period,
            slow_period=params.slow_period,
        )
        raw_signals = strategy.generate_signals(ohlcv_df)
        ohlcv_with_indicators = _build_indicators_frame(
            ohlcv_df,
            raw_signals,
            fast_period=params.fast_period,
            slow_period=params.slow_period,
        )

        net_backtest, comparison_report = StrategyBacktestRunner.run(
            ohlcv_df=ohlcv_df,
            strategy=strategy,
            ticker=params.ticker,
            b3_fee_pct=params.b3_fee_pct,
        )

        start_idx = params.slow_period - 1
        sliced_ohlcv = ohlcv_df.iloc[start_idx:].copy()
        sliced_signals = raw_signals.iloc[start_idx:].copy()
        latencies = pd.Series(
            float(params.simulated_latency_ms),
            index=sliced_ohlcv.index,
            dtype=float,
        )

        risk_cfg = params.to_risk_config()
        overlay_risk_manager = RiskManager(config=risk_cfg)
        risk_signals = overlay_risk_manager.apply_risk_overlay(
            sliced_ohlcv,
            sliced_signals,
            latencies=latencies,
            enforce_position_sizing=False,
        )
        risk_engine = VectorizedBacktestEngine(
            config=BacktestConfig(
                initial_capital=params.initial_capital,
                b3_fee_pct=params.b3_fee_pct,
                brokerage_fee=0.0,
                slippage_pct=params.slippage_pct,
            )
        )
        risk_adjusted_backtest = risk_engine.run(
            sliced_ohlcv,
            risk_signals,
            ticker=f"{params.ticker} (Risk Overlay)",
        )

        exec_cfg = params.to_execution_config()
        paper_broker = SimulatedPaperBroker(config=exec_cfg)
        paper_risk_manager = RiskManager(config=risk_cfg)
        paper_runner = PaperTradingRunner(
            broker=paper_broker,
            risk_manager=paper_risk_manager,
            config=exec_cfg,
        )
        paper_report = paper_runner.run_simulation(
            ohlcv_df=ohlcv_df,
            strategy=strategy,
            ticker=params.ticker,
            latency_ms=params.simulated_latency_ms,
        )

        ks_state = paper_risk_manager.kill_switch.state
        telemetry = _build_telemetry_snapshot(
            params=params,
            paper_report=paper_report,
            kill_switch_status=ks_state.status,
            halt_reason=ks_state.reason,
            observed_latency_ms=float(params.simulated_latency_ms),
        )
        trade_markers = _extract_trade_markers(paper_report.equity_curve)

        return DashboardSnapshot(
            parameters=params,
            ohlcv_with_indicators=ohlcv_with_indicators,
            net_backtest=net_backtest,
            comparison_report=comparison_report,
            risk_adjusted_backtest=risk_adjusted_backtest,
            paper_report=paper_report,
            telemetry=telemetry,
            trade_markers=trade_markers,
        )

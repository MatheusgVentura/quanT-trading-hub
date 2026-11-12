"""Validated contracts, presets, and snapshots for the quantitative dashboard."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pandas as pd

from src.backtest.models import BacktestResult
from src.dashboard.exceptions import DashboardConfigurationError, DashboardError
from src.execution.models import (
    ExecutionConfig,
    format_b3_execution_symbol,
)
from src.execution.runner import PaperSimulationReport
from src.risk.models import HaltReason, RiskConfig, RiskStatus
from src.strategies.runner import StrategyComparisonReport

TICKER_ALLOWLIST_PATTERN = re.compile(r"^[A-Z0-9^._=-]{1,20}$")
ALLOWED_PERIODS = frozenset(
    {"1mo", "3mo", "6mo", "1y", "2y", "3y", "5y", "10y", "ytd", "max"}
)
MAX_INITIAL_CAPITAL = 10_000_000.0
MAX_EMA_SLOW_PERIOD = 252
MAX_LEDGER_BYTES = 10 * 1024 * 1024


def _require_finite(
    value: object,
    field_name: str,
    exc_cls: type[DashboardError] = DashboardConfigurationError,
) -> float:
    """Validate that a value is a non-boolean finite float or int."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise exc_cls(f"{field_name} must be a numeric value.")
    num = float(value)
    if not math.isfinite(num):
        raise exc_cls(f"{field_name} must be finite.")
    return num


def _require_int_in_range(
    value: object,
    field_name: str,
    *,
    min_val: int,
    max_val: int | None = None,
    exc_cls: type[DashboardError] = DashboardConfigurationError,
) -> int:
    """Validate a non-boolean integer within optional inclusive bounds."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise exc_cls(f"{field_name} must be an integer.")
    if value < min_val:
        raise exc_cls(f"{field_name} must be >= {min_val}, got {value}.")
    if max_val is not None and value > max_val:
        raise exc_cls(f"{field_name} must be <= {max_val}, got {value}.")
    return value


def _require_bool(
    value: object,
    field_name: str,
    exc_cls: type[DashboardError] = DashboardConfigurationError,
) -> bool:
    """Validate that a value is strictly a boolean."""
    if not isinstance(value, bool):
        raise exc_cls(f"{field_name} must be a boolean.")
    return value


def _require_fraction(
    value: object,
    field_name: str,
    *,
    min_inclusive: bool,
    max_inclusive: bool,
    exc_cls: type[DashboardError] = DashboardConfigurationError,
) -> float:
    """Validate a bounded ratio in [0, 1], (0, 1), [0, 1), or (0, 1]."""
    num = _require_finite(value, field_name, exc_cls)
    lower_ok = num >= 0.0 if min_inclusive else num > 0.0
    upper_ok = num <= 1.0 if max_inclusive else num < 1.0
    if not (lower_ok and upper_ok):
        left = "[" if min_inclusive else "("
        right = "]" if max_inclusive else ")"
        raise exc_cls(f"{field_name} must be in {left}0.0, 1.0{right}, got {num}.")
    return num


def validate_ticker_symbol(raw_ticker: object) -> str:
    """Normalize and strictly validate a market ticker against an allowlist regex.

    Args:
        raw_ticker: User-supplied ticker string (e.g., `'itub4.sa'`).

    Returns:
        Normalized uppercase ticker string.

    Raises:
        DashboardConfigurationError: If the ticker is empty or contains disallowed characters.
    """
    if not isinstance(raw_ticker, str):
        raise DashboardConfigurationError("ticker must be a string.")
    cleaned = raw_ticker.strip().upper()
    if not cleaned or not TICKER_ALLOWLIST_PATTERN.fullmatch(cleaned):
        raise DashboardConfigurationError(
            "ticker must match ^[A-Z0-9^._=-]{1,20}$ with no spaces or HTML characters."
        )
    return cleaned


@dataclass(frozen=True)
class PresetAsset:
    """Curated B3 asset entry surfaced in the dashboard quick selector."""

    ticker: str
    label: str
    sector: str
    default_fractional: str

    def __post_init__(self) -> None:
        """Validate curated asset metadata."""
        cleaned_ticker = validate_ticker_symbol(self.ticker)
        object.__setattr__(self, "ticker", cleaned_ticker)
        for field_name in ("label", "sector", "default_fractional"):
            val = getattr(self, field_name)
            if not isinstance(val, str) or not val.strip():
                raise DashboardConfigurationError(
                    f"{field_name} must be a non-empty string."
                )
            object.__setattr__(self, field_name, val.strip())


B3_PRESET_ASSETS: tuple[PresetAsset, ...] = (
    PresetAsset(
        ticker="ITUB4.SA",
        label="Itaú Unibanco PN",
        sector="Financeiro / Bancos",
        default_fractional="ITUB4F",
    ),
    PresetAsset(
        ticker="PETR4.SA",
        label="Petrobras PN",
        sector="Petróleo, Gás e Energia",
        default_fractional="PETR4F",
    ),
    PresetAsset(
        ticker="VALE3.SA",
        label="Vale ON",
        sector="Mineração e Siderurgia",
        default_fractional="VALE3F",
    ),
    PresetAsset(
        ticker="WEGE3.SA",
        label="WEG ON",
        sector="Bens Industriais",
        default_fractional="WEGE3F",
    ),
)


def _validate_date_range(
    start_date: object,
    end_date: object,
    period: object,
) -> tuple[date | None, date | None, str | None]:
    """Validate optional start/end calendar dates or yfinance lookback period."""
    if start_date is not None and (
        not isinstance(start_date, date) or isinstance(start_date, datetime)
    ):
        raise DashboardConfigurationError(
            "start_date must be a calendar datetime.date."
        )
    if end_date is not None and (
        not isinstance(end_date, date) or isinstance(end_date, datetime)
    ):
        raise DashboardConfigurationError("end_date must be a calendar datetime.date.")
    if end_date is not None and start_date is None:
        raise DashboardConfigurationError("end_date cannot be set without start_date.")
    if start_date is not None and end_date is not None and start_date >= end_date:
        raise DashboardConfigurationError(
            "start_date must be strictly before end_date."
        )

    cleaned_period: str | None = None
    if period is not None:
        if not isinstance(period, str) or period.strip() not in ALLOWED_PERIODS:
            raise DashboardConfigurationError(
                f"period must be one of {sorted(ALLOWED_PERIODS)}, got {period!r}."
            )
        cleaned_period = period.strip()

    if start_date is None and cleaned_period is None:
        raise DashboardConfigurationError(
            "Provide either start_date or a valid period window."
        )

    return start_date, end_date, cleaned_period


@dataclass(frozen=True)
class DashboardParameters:
    """Validated user configuration driving backtest, risk, and paper simulations."""

    ticker: str = "ITUB4.SA"
    start_date: date | None = None
    end_date: date | None = None
    period: str | None = "3y"
    fast_period: int = 9
    slow_period: int = 21
    initial_capital: float = 100.0
    b3_fee_pct: float = 0.0003
    slippage_pct: float = 0.0
    max_risk_per_trade_pct: float = 0.02
    allow_min_lot_override: bool = False
    stop_loss_pct: float = 0.05
    trailing_stop_pct: float | None = 0.05
    max_daily_loss_pct: float = 0.02
    max_drawdown_pct: float = 0.10
    max_latency_ms: float = 500.0
    allow_day_trade: bool = False
    simulated_latency_ms: float = 45.0
    use_cache: bool = True

    def __post_init__(self) -> None:
        """Normalize and fail-closed validate every dashboard parameter."""
        object.__setattr__(self, "ticker", validate_ticker_symbol(self.ticker))
        start, end, period = _validate_date_range(
            self.start_date, self.end_date, self.period
        )
        object.__setattr__(self, "start_date", start)
        object.__setattr__(self, "end_date", end)
        object.__setattr__(self, "period", period)

        fast = _require_int_in_range(
            self.fast_period,
            "fast_period",
            min_val=2,
            max_val=MAX_EMA_SLOW_PERIOD - 1,
        )
        slow = _require_int_in_range(
            self.slow_period,
            "slow_period",
            min_val=3,
            max_val=MAX_EMA_SLOW_PERIOD,
        )
        if fast >= slow:
            raise DashboardConfigurationError(
                f"fast_period ({fast}) must be strictly less than slow_period ({slow})."
            )

        capital = _require_finite(self.initial_capital, "initial_capital")
        if capital <= 0.0 or capital > MAX_INITIAL_CAPITAL:
            raise DashboardConfigurationError(
                f"initial_capital must be in (0.0, {MAX_INITIAL_CAPITAL:.1f}], got {capital}."
            )

        _require_fraction(
            self.b3_fee_pct,
            "b3_fee_pct",
            min_inclusive=True,
            max_inclusive=False,
        )
        _require_fraction(
            self.slippage_pct,
            "slippage_pct",
            min_inclusive=True,
            max_inclusive=False,
        )
        _require_fraction(
            self.max_risk_per_trade_pct,
            "max_risk_per_trade_pct",
            min_inclusive=False,
            max_inclusive=True,
        )
        _require_fraction(
            self.stop_loss_pct,
            "stop_loss_pct",
            min_inclusive=False,
            max_inclusive=False,
        )
        if self.trailing_stop_pct is not None:
            _require_fraction(
                self.trailing_stop_pct,
                "trailing_stop_pct",
                min_inclusive=False,
                max_inclusive=False,
            )
        _require_fraction(
            self.max_daily_loss_pct,
            "max_daily_loss_pct",
            min_inclusive=False,
            max_inclusive=False,
        )
        _require_fraction(
            self.max_drawdown_pct,
            "max_drawdown_pct",
            min_inclusive=False,
            max_inclusive=False,
        )

        max_lat = _require_finite(self.max_latency_ms, "max_latency_ms")
        if max_lat <= 0.0:
            raise DashboardConfigurationError(
                f"max_latency_ms must be strictly positive, got {max_lat}."
            )

        sim_lat = _require_finite(self.simulated_latency_ms, "simulated_latency_ms")
        if sim_lat < 0.0:
            raise DashboardConfigurationError(
                f"simulated_latency_ms cannot be negative, got {sim_lat}."
            )

        _require_bool(self.allow_min_lot_override, "allow_min_lot_override")
        _require_bool(self.allow_day_trade, "allow_day_trade")
        _require_bool(self.use_cache, "use_cache")

    def to_risk_config(self) -> RiskConfig:
        """Build a validated RiskConfig aligned with dashboard parameters."""
        return RiskConfig(
            initial_capital=float(self.initial_capital),
            b3_fee_pct=float(self.b3_fee_pct),
            lot_size=1,
            max_risk_per_trade_pct=float(self.max_risk_per_trade_pct),
            max_position_pct=1.0,
            allow_min_lot_override=self.allow_min_lot_override,
            stop_loss_pct=float(self.stop_loss_pct),
            trailing_stop_pct=(
                float(self.trailing_stop_pct)
                if self.trailing_stop_pct is not None
                else None
            ),
            max_daily_loss_pct=float(self.max_daily_loss_pct),
            max_drawdown_pct=float(self.max_drawdown_pct),
            max_latency_ms=float(self.max_latency_ms),
            allow_day_trade=self.allow_day_trade,
        )

    def to_execution_config(self) -> ExecutionConfig:
        """Build a validated ExecutionConfig aligned with dashboard parameters."""
        return ExecutionConfig(
            initial_cash=float(self.initial_capital),
            b3_fee_pct=float(self.b3_fee_pct),
            brokerage_fee=0.0,
            slippage_pct=float(self.slippage_pct),
            use_fractional_suffix=True,
            liquidate_on_halt=True,
        )

    def display_fractional_symbol(self, shares: int = 1) -> str:
        """Return B3 fractional execution symbol for display in telemetry headers."""
        return format_b3_execution_symbol(
            self.ticker,
            shares=max(1, shares),
            use_fractional_suffix=True,
        )


@dataclass(frozen=True)
class RiskTelemetrySnapshot:
    """Snapshot displayed in the top Risk & Kill-Switch Telemetry Strip."""

    ticker: str
    execution_symbol: str
    kill_switch_status: RiskStatus
    halt_reason: HaltReason
    daily_pnl_pct: float
    max_daily_loss_limit_pct: float
    current_drawdown_pct: float
    max_drawdown_limit_pct: float
    observed_latency_ms: float
    max_latency_limit_ms: float
    allow_day_trade: bool
    open_shares: int
    cash_balance: float
    total_equity: float
    last_updated: datetime

    def __post_init__(self) -> None:
        """Validate telemetry bounds and types."""
        object.__setattr__(self, "ticker", validate_ticker_symbol(self.ticker))
        if (
            not isinstance(self.execution_symbol, str)
            or not self.execution_symbol.strip()
        ):
            raise DashboardConfigurationError(
                "execution_symbol must be a non-empty string."
            )
        if not isinstance(self.kill_switch_status, RiskStatus):
            raise DashboardConfigurationError(
                "kill_switch_status must be a RiskStatus enum."
            )
        if not isinstance(self.halt_reason, HaltReason):
            raise DashboardConfigurationError("halt_reason must be a HaltReason enum.")
        _require_finite(self.daily_pnl_pct, "daily_pnl_pct")
        _require_fraction(
            self.max_daily_loss_limit_pct,
            "max_daily_loss_limit_pct",
            min_inclusive=False,
            max_inclusive=True,
        )
        _require_finite(self.current_drawdown_pct, "current_drawdown_pct")
        _require_fraction(
            self.max_drawdown_limit_pct,
            "max_drawdown_limit_pct",
            min_inclusive=False,
            max_inclusive=True,
        )
        obs_lat = _require_finite(self.observed_latency_ms, "observed_latency_ms")
        if obs_lat < 0.0:
            raise DashboardConfigurationError("observed_latency_ms cannot be negative.")
        max_lat = _require_finite(self.max_latency_limit_ms, "max_latency_limit_ms")
        if max_lat <= 0.0:
            raise DashboardConfigurationError(
                "max_latency_limit_ms must be strictly positive."
            )
        _require_bool(self.allow_day_trade, "allow_day_trade")
        _require_int_in_range(self.open_shares, "open_shares", min_val=0)
        cash = _require_finite(self.cash_balance, "cash_balance")
        equity = _require_finite(self.total_equity, "total_equity")
        if cash < 0.0 or equity < 0.0:
            raise DashboardConfigurationError(
                "cash_balance and total_equity cannot be negative."
            )
        if not isinstance(self.last_updated, datetime):
            raise DashboardConfigurationError("last_updated must be a datetime.")


@dataclass(frozen=True)
class LoadedLedgerSummary:
    """Validated summary parsed from a persisted Phase 5 execution JSON ledger."""

    source_name: str
    schema_version: int
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
    equity_curve: pd.DataFrame
    receipts: pd.DataFrame
    open_orders: pd.DataFrame
    positions: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class DashboardSnapshot:
    """Consolidated read-only analytics snapshot rendered across dashboard workspaces."""

    parameters: DashboardParameters
    ohlcv_with_indicators: pd.DataFrame
    net_backtest: BacktestResult
    comparison_report: StrategyComparisonReport
    risk_adjusted_backtest: BacktestResult
    paper_report: PaperSimulationReport
    telemetry: RiskTelemetrySnapshot
    trade_markers: pd.DataFrame

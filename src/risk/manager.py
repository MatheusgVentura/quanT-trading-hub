"""Unified RiskManager orchestrating pre-trade gates and close-based backtest overlays."""

from datetime import date, datetime

import pandas as pd

from src.risk.exceptions import InvalidRiskInputError
from src.risk.kill_switch import KillSwitch
from src.risk.models import (
    KillSwitchState,
    RiskConfig,
    RiskStatus,
    RiskVerdict,
    require_finite_number,
)
from src.risk.sizing import PositionSizer
from src.risk.stops import StopCheckResult, StopMonitor


def _normalize_date(value: object, field_name: str) -> date:
    """Validate and normalize a calendar date (converting datetime to date)."""
    if not isinstance(value, date):
        raise InvalidRiskInputError(f"{field_name} must be a datetime.date.")
    return value.date() if isinstance(value, datetime) else value


def _validate_signal_value(signal: object) -> int:
    """Validate a single pre-trade binary Long/Cash signal {0, 1}."""
    if isinstance(signal, bool) or not isinstance(signal, int) or signal not in (0, 1):
        raise InvalidRiskInputError(
            f"signal must be 0 or 1 for Long/Cash trading, got {signal!r}."
        )
    return signal


def _validate_non_negative_shares(shares: object) -> int:
    """Validate current_shares as a non-bool non-negative integer."""
    if isinstance(shares, bool) or not isinstance(shares, int) or shares < 0:
        raise InvalidRiskInputError(
            f"current_shares must be a non-negative integer, got {shares!r}."
        )
    return shares


def _validate_overlay_inputs(
    ohlcv_df: pd.DataFrame,
    raw_signals: pd.Series,
    latencies: pd.Series | None,
) -> tuple[list[float], list[date], list[int], list[float]]:
    """Validate and extract aligned Close prices, dates, binary signals, and latencies."""
    if ohlcv_df is None or ohlcv_df.empty:
        raise InvalidRiskInputError("ohlcv_df cannot be None or empty.")
    if raw_signals is None or raw_signals.empty:
        raise InvalidRiskInputError("raw_signals cannot be None or empty.")
    if "Close" not in ohlcv_df.columns:
        raise InvalidRiskInputError("ohlcv_df must contain a 'Close' column.")
    if not ohlcv_df.index.equals(raw_signals.index):
        raise InvalidRiskInputError(
            "ohlcv_df and raw_signals indexes must be strictly identical."
        )
    if not isinstance(ohlcv_df.index, pd.DatetimeIndex):
        raise InvalidRiskInputError("ohlcv_df index must be a pd.DatetimeIndex.")
    if ohlcv_df.index.isna().any():
        raise InvalidRiskInputError("ohlcv_df index cannot contain NaT values.")

    if pd.api.types.is_bool_dtype(raw_signals):
        raise InvalidRiskInputError("raw_signals cannot have boolean dtype.")

    close_series = ohlcv_df["Close"]
    if pd.api.types.is_bool_dtype(close_series):
        raise InvalidRiskInputError("Close prices cannot have boolean dtype.")

    closes: list[float] = []
    for raw_price in close_series.tolist():
        price = require_finite_number(raw_price, "Close", InvalidRiskInputError)
        if price <= 0.0:
            raise InvalidRiskInputError(
                f"Close prices must be strictly positive, got {price}."
            )
        closes.append(price)

    signals: list[int] = []
    for raw_sig in raw_signals.tolist():
        num_sig = require_finite_number(raw_sig, "raw_signals", InvalidRiskInputError)
        if num_sig not in (0.0, 1.0):
            raise InvalidRiskInputError(
                f"raw_signals values must be strictly 0 or 1, got {raw_sig!r}."
            )
        signals.append(int(num_sig))

    if latencies is None:
        latency_list = [0.0] * len(closes)
    else:
        if not ohlcv_df.index.equals(latencies.index):
            raise InvalidRiskInputError(
                "latencies index must be strictly identical to ohlcv_df index."
            )
        if pd.api.types.is_bool_dtype(latencies):
            raise InvalidRiskInputError("latencies cannot have boolean dtype.")
        latency_list = []
        for raw_lat in latencies.tolist():
            lat = require_finite_number(raw_lat, "latencies", InvalidRiskInputError)
            if lat < 0.0:
                raise InvalidRiskInputError(f"latencies cannot be negative, got {lat}.")
            latency_list.append(lat)

    dates = [ts.date() for ts in ohlcv_df.index.to_pydatetime()]
    return closes, dates, signals, latency_list


class RiskManager:
    """Facade uniting KillSwitch, StopMonitor, PositionSizer, and Swing Trade rules."""

    def __init__(self, config: RiskConfig | None = None) -> None:
        """Initialize RiskManager and its subcomponents with a validated RiskConfig."""
        self.config = config or RiskConfig()
        self.sizer = PositionSizer(self.config)
        self.stop_monitor = StopMonitor(self.config)
        self.kill_switch = KillSwitch(self.config)

    def _evaluate_open_position(
        self,
        signal: int,
        price: float,
        equity: float,
        obs_date: date,
        ks_state: KillSwitchState,
        current_shares: int,
        effective_entry_date: date | None,
        stop_result: StopCheckResult | None,
        is_emergency: bool,
    ) -> RiskVerdict:
        """Evaluate risk gates when an open Long position already exists."""
        ks_halted = ks_state.status == RiskStatus.HALTED
        stop_triggered = stop_result is not None and stop_result.triggered
        emergency = ks_halted or stop_triggered or (signal == 0 and is_emergency)

        if emergency:
            triggers: list[str] = []
            if ks_halted:
                triggers.append(f"Kill-Switch {ks_state.reason.value}")
            if stop_result is not None and stop_result.triggered:
                triggers.append(
                    f"{stop_result.trigger_type.value}: {stop_result.reason}"
                )
            if signal == 0 and is_emergency:
                triggers.append("explicit emergency exit flag")
            return RiskVerdict(
                approved=True,
                action="EXIT",
                shares=0,
                weight=0.0,
                kill_switch_state=ks_state,
                reason=f"Emergency exit approved ({'; '.join(triggers)}).",
            )

        held_weight = (
            min(1.0, (current_shares * price) / equity) if current_shares > 0 else 1.0
        )

        if signal == 0:
            if (
                not self.config.allow_day_trade
                and effective_entry_date is not None
                and effective_entry_date == obs_date
            ):
                return RiskVerdict(
                    approved=False,
                    action="HOLD",
                    shares=current_shares,
                    weight=held_weight,
                    kill_switch_state=ks_state,
                    reason=(
                        "Swing Trade guard rejected voluntary exit on entry date "
                        f"{obs_date} (allow_day_trade=False)."
                    ),
                )
            return RiskVerdict(
                approved=True,
                action="EXIT",
                shares=0,
                weight=0.0,
                kill_switch_state=ks_state,
                reason="Voluntary strategy exit approved.",
            )

        return RiskVerdict(
            approved=True,
            action="HOLD",
            shares=current_shares,
            weight=held_weight,
            kill_switch_state=ks_state,
            reason="Existing Long position maintained within risk limits.",
        )

    def evaluate_trade(
        self,
        signal: int,
        price: float,
        current_equity: float,
        current_date: date,
        latency_ms: float = 0.0,
        available_cash: float | None = None,
        stop_loss_price: float | None = None,
        current_shares: int = 0,
        entry_date: date | None = None,
        is_emergency: bool = False,
    ) -> RiskVerdict:
        """Run pre-trade risk validation across Kill-Switch, stops, Swing Trade, and sizing.

        Args:
            signal: Strategy intent (`1` for Long/stay invested, `0` for Cash/exit).
            price: Current market execution/evaluation price.
            current_equity: Current mark-to-market portfolio equity.
            current_date: Calendar date of evaluation.
            latency_ms: Observed feed/broker latency in milliseconds.
            available_cash: Optional cash balance available for new Long buys.
            stop_loss_price: Optional explicit stop price overriding `config.stop_loss_pct`.
            current_shares: Number of shares currently held (`0` when flat).
            entry_date: Calendar date when the current open position was entered.
            is_emergency: Explicit emergency exit flag bypassing Swing Trade D0 guard.

        Returns:
            Immutable RiskVerdict indicating approval, action, share count, and weight.

        Raises:
            InvalidRiskInputError: If any input fails domain, type, or monotonicity checks.
        """
        validated_signal = _validate_signal_value(signal)
        validated_price = require_finite_number(price, "price", InvalidRiskInputError)
        if validated_price <= 0.0:
            raise InvalidRiskInputError(
                f"price must be strictly positive, got {validated_price}."
            )
        shares_held = _validate_non_negative_shares(current_shares)
        obs_date = _normalize_date(current_date, "current_date")
        obs_entry_date = (
            _normalize_date(entry_date, "entry_date")
            if entry_date is not None
            else None
        )
        if obs_entry_date is not None and obs_entry_date > obs_date:
            raise InvalidRiskInputError(
                f"entry_date ({obs_entry_date}) cannot be after current_date ({obs_date})."
            )

        ks_state = self.kill_switch.update(
            current_equity=current_equity,
            current_date=obs_date,
            latency_ms=latency_ms,
        )
        valid_equity = float(current_equity)

        has_open_position = shares_held > 0 or self.stop_monitor.has_open_position
        if has_open_position:
            stop_result = (
                self.stop_monitor.evaluate(validated_price)
                if self.stop_monitor.has_open_position
                else None
            )
            return self._evaluate_open_position(
                signal=validated_signal,
                price=validated_price,
                equity=valid_equity,
                obs_date=obs_date,
                ks_state=ks_state,
                current_shares=shares_held,
                effective_entry_date=obs_entry_date,
                stop_result=stop_result,
                is_emergency=is_emergency,
            )

        if ks_state.status == RiskStatus.HALTED:
            return RiskVerdict(
                approved=False,
                action="HALT",
                shares=0,
                weight=0.0,
                kill_switch_state=ks_state,
                reason=f"Kill-Switch HALTED ({ks_state.reason.value}): {ks_state.message}",
            )

        if validated_signal == 0:
            return RiskVerdict(
                approved=True,
                action="HOLD",
                shares=0,
                weight=0.0,
                kill_switch_state=ks_state,
                reason="Flat signal (0) with no open position.",
            )

        cash_balance = valid_equity if available_cash is None else available_cash
        sizing = self.sizer.calculate(
            entry_price=validated_price,
            stop_loss_price=stop_loss_price,
            capital=valid_equity,
            available_cash=cash_balance,
        )
        if not sizing.approved:
            return RiskVerdict(
                approved=False,
                action="HOLD",
                shares=0,
                weight=0.0,
                kill_switch_state=ks_state,
                reason=sizing.reason,
            )

        return RiskVerdict(
            approved=True,
            action="BUY",
            shares=sizing.shares,
            weight=sizing.allocation_pct,
            kill_switch_state=ks_state,
            reason=sizing.reason,
        )

    def apply_risk_overlay(
        self,
        ohlcv_df: pd.DataFrame,
        raw_signals: pd.Series,
        *,
        latencies: pd.Series | None = None,
        enforce_position_sizing: bool = False,
    ) -> pd.Series:
        """Apply close-based stop, Kill-Switch, Swing Trade, and re-entry rules sequentially.

        Evaluates each bar `t` close price identically to `VectorizedBacktestEngine`
        (`t+1` execution and B3 `b3_fee_pct` turnover costs) using isolated local state so
        repeated calls across different assets remain independent.

        Args:
            ohlcv_df: Market OHLCV DataFrame with `DatetimeIndex` and `'Close'` column.
            raw_signals: Binary `{0, 1}` strategy signals aligned to `ohlcv_df.index`.
            latencies: Optional per-bar latency series in milliseconds.
            enforce_position_sizing: When True, also requires `PositionSizer` lot approval.

        Returns:
            Binary `{0, 1}` integer `pd.Series` aligned to `ohlcv_df.index`.

        Raises:
            InvalidRiskInputError: If DataFrames, indexes, prices, signals, or latencies
                fail validation or non-decreasing date order checks.
        """
        closes, dates, signals, latency_list = _validate_overlay_inputs(
            ohlcv_df=ohlcv_df,
            raw_signals=raw_signals,
            latencies=latencies,
        )

        equity = float(self.config.initial_capital)
        local_kill_switch = KillSwitch(self.config, initial_equity=equity)
        local_stop_monitor = StopMonitor(self.config)

        prev_position = 0.0
        active_position = 0.0
        in_position = False
        entry_date: date | None = None
        suppressed = False
        output_signals: list[int] = []

        for idx, (close_price, obs_date, raw_sig, lat_ms) in enumerate(
            zip(closes, dates, signals, latency_list, strict=True)
        ):
            asset_ret = (close_price / closes[idx - 1]) - 1.0 if idx > 0 else 0.0
            turnover = abs(active_position - prev_position)
            bar_ret = (active_position * asset_ret) - (
                turnover * self.config.b3_fee_pct
            )
            equity = max(equity * (1.0 + bar_ret), 1e-12)

            ks_state = local_kill_switch.update(
                current_equity=equity,
                current_date=obs_date,
                latency_ms=lat_ms,
            )

            if raw_sig == 0:
                suppressed = False

            out_sig = 0
            if in_position:
                stop_res = local_stop_monitor.evaluate(close_price)
                if stop_res.triggered or ks_state.status == RiskStatus.HALTED:
                    local_stop_monitor.close_position()
                    in_position = False
                    entry_date = None
                    if raw_sig == 1:
                        suppressed = True
                elif raw_sig == 0:
                    same_day_exit = (
                        not self.config.allow_day_trade and entry_date == obs_date
                    )
                    if same_day_exit:
                        out_sig = 1
                    else:
                        local_stop_monitor.close_position()
                        in_position = False
                        entry_date = None
                else:
                    out_sig = 1
            elif (
                raw_sig == 1 and not suppressed and ks_state.status == RiskStatus.ACTIVE
            ):
                sizing_ok = (
                    True
                    if not enforce_position_sizing
                    else self.sizer.calculate(
                        entry_price=close_price,
                        capital=equity,
                        available_cash=equity,
                    ).approved
                )
                if sizing_ok:
                    local_stop_monitor.open_position(entry_price=close_price)
                    in_position = True
                    entry_date = obs_date
                    out_sig = 1

            output_signals.append(out_sig)
            prev_position = active_position
            active_position = float(out_sig)

        return pd.Series(
            output_signals,
            index=ohlcv_df.index,
            name=raw_signals.name,
            dtype=int,
        )

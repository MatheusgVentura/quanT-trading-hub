"""Unit tests for Phase 6 dashboard exceptions and validated data contracts."""

from datetime import date, datetime, timezone

import pytest

from src.dashboard.exceptions import (
    DashboardConfigurationError,
    DashboardDataError,
    DashboardError,
    LedgerLoadError,
)
from src.dashboard.models import (
    ALLOWED_PERIODS,
    B3_PRESET_ASSETS,
    MAX_EMA_SLOW_PERIOD,
    MAX_INITIAL_CAPITAL,
    DashboardParameters,
    PresetAsset,
    RiskTelemetrySnapshot,
    validate_ticker_symbol,
)
from src.risk.models import HaltReason, RiskStatus


def test_ac01_ac09_exception_hierarchy() -> None:
    """Verify all dashboard exception subclasses inherit cleanly from DashboardError."""
    assert issubclass(DashboardConfigurationError, DashboardError)
    assert issubclass(DashboardDataError, DashboardError)
    assert issubclass(LedgerLoadError, DashboardError)


def test_ac01_preset_assets_catalog_is_valid() -> None:
    """Verify curated B3 presets contain the four canonical fractional tickers."""
    tickers = [asset.ticker for asset in B3_PRESET_ASSETS]
    assert tickers == ["ITUB4.SA", "PETR4.SA", "VALE3.SA", "WEGE3.SA"]
    fractionals = [asset.default_fractional for asset in B3_PRESET_ASSETS]
    assert fractionals == ["ITUB4F", "PETR4F", "VALE3F", "WEGE3F"]


def test_ac01_preset_asset_rejects_empty_metadata() -> None:
    """Verify PresetAsset fails closed when metadata fields are blank."""
    with pytest.raises(DashboardConfigurationError, match="label"):
        PresetAsset(
            ticker="ITUB4.SA",
            label="   ",
            sector="Bancos",
            default_fractional="ITUB4F",
        )


@pytest.mark.parametrize(
    ("raw_ticker", "expected"),
    [
        ("itub4.sa", "ITUB4.SA"),
        ("  wege3.sa ", "WEGE3.SA"),
        ("^bvsp", "^BVSP"),
        ("BRK-B", "BRK-B"),
    ],
)
def test_ac01_ac09_validate_ticker_normalizes_valid_inputs(
    raw_ticker: str, expected: str
) -> None:
    """Verify ticker validation strips whitespace and uppercases allowed symbols."""
    assert validate_ticker_symbol(raw_ticker) == expected


@pytest.mark.parametrize(
    "bad_ticker",
    [
        "",
        "   ",
        "<script>alert(1)</script>",
        "ITUB4.SA; DROP TABLE",
        "ITUB4 SA",
        "../.env",
        "A" * 21,
        123,
    ],
)
def test_ac01_ac09_validate_ticker_rejects_xss_and_malformed_inputs(
    bad_ticker: object,
) -> None:
    """Verify invalid or HTML-injected tickers fail closed with DashboardConfigurationError."""
    with pytest.raises(DashboardConfigurationError):
        validate_ticker_symbol(bad_ticker)


def test_ac01_dashboard_parameters_defaults_and_adapters() -> None:
    """Verify default R$ 100.00 configuration maps faithfully to Risk and Execution."""
    params = DashboardParameters()
    assert params.ticker == "ITUB4.SA"
    assert params.display_fractional_symbol() == "ITUB4F"
    assert params.period == "3y"
    assert params.initial_capital == 100.0

    risk_cfg = params.to_risk_config()
    assert risk_cfg.initial_capital == 100.0
    assert risk_cfg.b3_fee_pct == pytest.approx(0.0003)
    assert risk_cfg.allow_day_trade is False
    assert risk_cfg.allow_min_lot_override is False
    assert risk_cfg.max_drawdown_pct == pytest.approx(0.10)

    exec_cfg = params.to_execution_config()
    assert exec_cfg.initial_cash == 100.0
    assert exec_cfg.b3_fee_pct == pytest.approx(0.0003)
    assert exec_cfg.brokerage_fee == 0.0
    assert exec_cfg.use_fractional_suffix is True
    assert exec_cfg.liquidate_on_halt is True


def test_ac01_dashboard_parameters_date_validation() -> None:
    """Verify start_date, end_date, and period cross-validation rules."""
    valid = DashboardParameters(
        start_date=date(2022, 1, 1),
        end_date=date(2024, 1, 1),
        period=None,
    )
    assert valid.start_date == date(2022, 1, 1)
    assert valid.end_date == date(2024, 1, 1)

    with pytest.raises(DashboardConfigurationError, match="without start_date"):
        DashboardParameters(start_date=None, end_date=date(2024, 1, 1))

    with pytest.raises(DashboardConfigurationError, match="strictly before"):
        DashboardParameters(start_date=date(2024, 1, 1), end_date=date(2023, 12, 31))

    with pytest.raises(DashboardConfigurationError, match="datetime.date"):
        DashboardParameters(start_date=datetime(2023, 1, 1))

    with pytest.raises(DashboardConfigurationError, match="end_date"):
        DashboardParameters(
            start_date=date(2023, 1, 1),
            end_date=datetime(2024, 1, 1),
        )

    with pytest.raises(DashboardConfigurationError, match="period"):
        DashboardParameters(start_date=None, end_date=None, period=None)

    with pytest.raises(DashboardConfigurationError, match="period"):
        DashboardParameters(period="99y")

    assert "3y" in ALLOWED_PERIODS


@pytest.mark.parametrize(
    "kwargs",
    [
        {"fast_period": 1, "slow_period": 21},
        {"fast_period": 21, "slow_period": 21},
        {"fast_period": 25, "slow_period": 21},
        {"fast_period": 9, "slow_period": MAX_EMA_SLOW_PERIOD + 1},
        {"fast_period": True, "slow_period": 21},
        {"initial_capital": 0.0},
        {"initial_capital": -100.0},
        {"initial_capital": float("nan")},
        {"initial_capital": MAX_INITIAL_CAPITAL + 1.0},
        {"b3_fee_pct": -0.01},
        {"b3_fee_pct": 1.0},
        {"max_risk_per_trade_pct": 0.0},
        {"stop_loss_pct": 0.0},
        {"trailing_stop_pct": 1.0},
        {"max_daily_loss_pct": 1.2},
        {"max_drawdown_pct": 0.0},
        {"max_latency_ms": 0.0},
        {"simulated_latency_ms": -1.0},
        {"allow_day_trade": "no"},
        {"allow_min_lot_override": 1},
        {"use_cache": "yes"},
    ],
)
def test_ac01_dashboard_parameters_rejects_invalid_bounds(
    kwargs: dict[str, object],
) -> None:
    """Verify invalid numeric, boolean, and EMA bounds raise DashboardConfigurationError."""
    with pytest.raises(DashboardConfigurationError):
        DashboardParameters(**kwargs)  # type: ignore[arg-type]


def test_ac04_risk_telemetry_snapshot_validation() -> None:
    """Verify RiskTelemetrySnapshot enforces finite limits and valid enums."""
    now = datetime(2026, 11, 11, 15, 0, tzinfo=timezone.utc)  # noqa: UP017
    snap = RiskTelemetrySnapshot(
        ticker="ITUB4.SA",
        execution_symbol="ITUB4F",
        kill_switch_status=RiskStatus.ACTIVE,
        halt_reason=HaltReason.NONE,
        daily_pnl_pct=0.005,
        max_daily_loss_limit_pct=0.02,
        current_drawdown_pct=-0.012,
        max_drawdown_limit_pct=0.10,
        observed_latency_ms=32.5,
        max_latency_limit_ms=500.0,
        allow_day_trade=False,
        open_shares=2,
        cash_balance=20.8,
        total_equity=100.8,
        last_updated=now,
    )
    assert snap.execution_symbol == "ITUB4F"
    assert snap.kill_switch_status == RiskStatus.ACTIVE

    with pytest.raises(DashboardConfigurationError, match="observed_latency_ms"):
        RiskTelemetrySnapshot(
            ticker="ITUB4.SA",
            execution_symbol="ITUB4F",
            kill_switch_status=RiskStatus.ACTIVE,
            halt_reason=HaltReason.NONE,
            daily_pnl_pct=0.0,
            max_daily_loss_limit_pct=0.02,
            current_drawdown_pct=0.0,
            max_drawdown_limit_pct=0.10,
            observed_latency_ms=-5.0,
            max_latency_limit_ms=500.0,
            allow_day_trade=False,
            open_shares=0,
            cash_balance=100.0,
            total_equity=100.0,
            last_updated=now,
        )

    with pytest.raises(DashboardConfigurationError, match="execution_symbol"):
        RiskTelemetrySnapshot(
            ticker="ITUB4.SA",
            execution_symbol="   ",
            kill_switch_status=RiskStatus.ACTIVE,
            halt_reason=HaltReason.NONE,
            daily_pnl_pct=0.0,
            max_daily_loss_limit_pct=0.02,
            current_drawdown_pct=0.0,
            max_drawdown_limit_pct=0.10,
            observed_latency_ms=10.0,
            max_latency_limit_ms=500.0,
            allow_day_trade=False,
            open_shares=0,
            cash_balance=100.0,
            total_equity=100.0,
            last_updated=now,
        )

    with pytest.raises(DashboardConfigurationError, match="max_latency_limit_ms"):
        RiskTelemetrySnapshot(
            ticker="ITUB4.SA",
            execution_symbol="ITUB4F",
            kill_switch_status=RiskStatus.ACTIVE,
            halt_reason=HaltReason.NONE,
            daily_pnl_pct=0.0,
            max_daily_loss_limit_pct=0.02,
            current_drawdown_pct=0.0,
            max_drawdown_limit_pct=0.10,
            observed_latency_ms=10.0,
            max_latency_limit_ms=0.0,
            allow_day_trade=False,
            open_shares=0,
            cash_balance=100.0,
            total_equity=100.0,
            last_updated=now,
        )

    with pytest.raises(DashboardConfigurationError, match="cash_balance"):
        RiskTelemetrySnapshot(
            ticker="ITUB4.SA",
            execution_symbol="ITUB4F",
            kill_switch_status=RiskStatus.HALTED,
            halt_reason=HaltReason.MAX_DRAWDOWN_LIMIT,
            daily_pnl_pct=-0.01,
            max_daily_loss_limit_pct=0.02,
            current_drawdown_pct=-0.11,
            max_drawdown_limit_pct=0.10,
            observed_latency_ms=40.0,
            max_latency_limit_ms=500.0,
            allow_day_trade=False,
            open_shares=0,
            cash_balance=-1.0,
            total_equity=90.0,
            last_updated=now,
        )

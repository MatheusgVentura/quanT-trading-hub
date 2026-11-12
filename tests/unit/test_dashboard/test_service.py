"""Unit tests for DashboardService and safe Phase 5 JSON ledger ingestion."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from src.dashboard.exceptions import DashboardDataError, LedgerLoadError
from src.dashboard.models import MAX_LEDGER_BYTES, DashboardParameters
from src.dashboard.service import (
    DashboardService,
    load_ledger_json,
    parse_ledger_payload,
    telemetry_from_ledger,
)
from src.data.interfaces import IDataProvider
from src.execution.models import ExecutionConfig
from src.execution.paper_broker import SimulatedPaperBroker
from src.execution.runner import PaperTradingRunner
from src.risk.manager import RiskManager
from src.risk.models import HaltReason, RiskConfig, RiskStatus
from src.strategies.ema_crossover import EMACrossoverStrategy
from src.strategies.exceptions import InsufficientDataError


class _FakeDataProvider(IDataProvider):
    """Deterministic in-memory market data provider for unit tests."""

    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df
        self.calls: list[dict[str, Any]] = []

    def fetch_ohlcv(
        self,
        ticker: str,
        start_date: str | None = None,
        end_date: str | None = None,
        period: str | None = "1y",
        interval: str = "1d",
    ) -> pd.DataFrame:
        self.calls.append(
            {
                "ticker": ticker,
                "start_date": start_date,
                "end_date": end_date,
                "period": period,
                "interval": interval,
            }
        )
        return self._df.copy()


def _make_trending_ohlcv(bars: int = 90) -> pd.DataFrame:
    """Construct a synthetic B3 OHLCV series that triggers clean EMA crossovers."""
    dates = pd.date_range("2024-01-02", periods=bars, freq="B")
    phase1 = np.linspace(38.0, 31.0, bars // 3)
    phase2 = np.linspace(31.5, 46.0, bars // 3)
    phase3 = np.linspace(45.5, 36.0, bars - len(phase1) - len(phase2))
    close = np.concatenate([phase1, phase2, phase3])
    return pd.DataFrame(
        {
            "Open": close * 0.995,
            "High": close * 1.015,
            "Low": close * 0.985,
            "Close": close,
            "Volume": np.full(bars, 1_500_000.0),
        },
        index=dates,
    )


def _generate_phase5_ledger_file(tmp_path: Path) -> Path:
    """Create a real Phase 5 ledger JSON artifact on disk using PaperTradingRunner."""
    df = _make_trending_ohlcv(70)
    exec_cfg = ExecutionConfig(initial_cash=100.0, b3_fee_pct=0.0003)
    risk_cfg = RiskConfig(
        initial_capital=100.0,
        allow_min_lot_override=True,
        max_risk_per_trade_pct=0.50,
    )
    ledger_path = tmp_path / "itub4_ledger.json"
    runner = PaperTradingRunner(
        broker=SimulatedPaperBroker(config=exec_cfg),
        risk_manager=RiskManager(config=risk_cfg),
        config=exec_cfg,
        ledger_path=ledger_path,
    )
    runner.run_simulation(
        ohlcv_df=df,
        strategy=EMACrossoverStrategy(fast_period=5, slow_period=12),
        ticker="ITUB4.SA",
        latency_ms=35.0,
    )
    return ledger_path


def test_ac02_ac04_service_runs_full_pipeline_with_mocked_provider() -> None:
    """Verify DashboardService orchestrates Data, Strategy, Risk, and Paper layers."""
    ohlcv = _make_trending_ohlcv(95)
    provider = _FakeDataProvider(ohlcv)
    service = DashboardService(data_provider=provider)

    params = DashboardParameters(
        ticker="itub4.sa",
        period="1y",
        fast_period=5,
        slow_period=12,
        initial_capital=100.0,
        allow_min_lot_override=True,
        max_risk_per_trade_pct=0.50,
        simulated_latency_ms=42.0,
    )
    snapshot = service.run_analysis(params)

    assert len(provider.calls) == 1
    assert provider.calls[0]["ticker"] == "ITUB4.SA"
    assert {"EMA_Fast", "EMA_Slow", "Signal"}.issubset(
        snapshot.ohlcv_with_indicators.columns
    )
    assert snapshot.comparison_report.ticker == "ITUB4.SA"
    assert snapshot.paper_report.initial_cash == 100.0
    assert snapshot.paper_report.filled_orders >= 1
    assert snapshot.telemetry.ticker == "ITUB4.SA"
    assert snapshot.telemetry.execution_symbol == "ITUB4F"
    assert snapshot.telemetry.kill_switch_status == RiskStatus.ACTIVE
    assert snapshot.telemetry.observed_latency_ms == pytest.approx(42.0)
    assert not snapshot.trade_markers.empty
    assert set(snapshot.trade_markers["Action"]).issubset({"BUY", "EXIT", "HALT"})


def test_ac02_ac04_service_surfaces_kill_switch_halt_on_high_latency() -> None:
    """Verify simulated latency above 500ms trips Kill-Switch telemetry to HALTED."""
    ohlcv = _make_trending_ohlcv(60)
    service = DashboardService(data_provider=_FakeDataProvider(ohlcv))
    params = DashboardParameters(
        ticker="PETR4.SA",
        fast_period=5,
        slow_period=12,
        max_latency_ms=500.0,
        simulated_latency_ms=650.0,
    )
    snapshot = service.run_analysis(params)

    assert snapshot.paper_report.halted is True
    assert snapshot.telemetry.kill_switch_status == RiskStatus.HALTED
    assert snapshot.telemetry.halt_reason == HaltReason.LATENCY_LIMIT
    assert snapshot.telemetry.observed_latency_ms == pytest.approx(650.0)


def test_ac02_service_raises_clear_errors_on_empty_or_short_data() -> None:
    """Verify empty market data raises DashboardDataError and short windows fail loudly."""
    empty_service = DashboardService(data_provider=_FakeDataProvider(pd.DataFrame()))
    with pytest.raises(DashboardDataError, match="empty or missing"):
        empty_service.run_analysis(DashboardParameters())

    short_df = _make_trending_ohlcv(10)
    short_service = DashboardService(data_provider=_FakeDataProvider(short_df))
    with pytest.raises(InsufficientDataError):
        short_service.run_analysis(DashboardParameters(fast_period=9, slow_period=21))


def test_ac08_load_ledger_json_reads_phase5_disk_and_bytes_artifacts(
    tmp_path: Path,
) -> None:
    """Verify load_ledger_json ingests persisted Phase 5 ledgers via path and upload bytes."""
    ledger_path = _generate_phase5_ledger_file(tmp_path)

    from_disk = load_ledger_json(ledger_path, allowed_dir=tmp_path)
    assert from_disk.schema_version == 1
    assert from_disk.ticker == "ITUB4.SA"
    assert from_disk.initial_cash == pytest.approx(100.0)
    assert not from_disk.equity_curve.empty
    assert from_disk.filled_orders >= 1

    raw_bytes = ledger_path.read_bytes()
    from_bytes = load_ledger_json(raw_bytes, source_name="upload.json")
    assert from_bytes.source_name == "upload.json"
    assert from_bytes.final_equity == pytest.approx(from_disk.final_equity)
    assert len(from_bytes.receipts) == len(from_disk.receipts)

    telemetry = telemetry_from_ledger(from_bytes)
    assert telemetry.ticker == "ITUB4.SA"
    assert telemetry.execution_symbol == "ITUB4F"


def test_ac08_ac09_load_ledger_rejects_oversized_traversal_xss_and_nan(
    tmp_path: Path,
) -> None:
    """Verify ledger ingestion enforces size limits, path jail, schema, and anti-XSS."""
    oversized = b"x" * (MAX_LEDGER_BYTES + 1)
    with pytest.raises(LedgerLoadError, match="exceeds"):
        load_ledger_json(oversized)

    with pytest.raises(LedgerLoadError, match="UTF-8"):
        load_ledger_json(b"\xff\xfe\xfd")

    with pytest.raises(LedgerLoadError, match="Invalid JSON"):
        load_ledger_json(b"{not-valid-json")

    secret_env = tmp_path / ".env"
    secret_env.write_text('{"schema_version": 1}', encoding="utf-8")
    with pytest.raises(LedgerLoadError, match="environment secret"):
        load_ledger_json(secret_env, allowed_dir=tmp_path)

    outside = tmp_path.parent / "outside_ledger.json"
    allowed = tmp_path / "artifacts"
    allowed.mkdir()
    with pytest.raises(LedgerLoadError, match="escapes allowed directory"):
        load_ledger_json(outside, allowed_dir=allowed)

    nan_payload = '{"schema_version": 1, "ticker": "ITUB4.SA", "initial_cash": NaN}'
    with pytest.raises(LedgerLoadError, match="Non-finite"):
        load_ledger_json(nan_payload.encode("utf-8"))

    valid_path = _generate_phase5_ledger_file(tmp_path)
    base_payload: dict[str, Any] = json.loads(valid_path.read_text(encoding="utf-8"))

    bad_version = dict(base_payload, schema_version=99)
    with pytest.raises(LedgerLoadError, match="schema_version"):
        parse_ledger_payload(bad_version)

    xss_ticker = dict(base_payload, ticker="<script>alert(1)</script>")
    with pytest.raises(LedgerLoadError, match="Invalid ledger ticker"):
        parse_ledger_payload(xss_ticker)

    empty_curve = dict(base_payload, equity_curve=[])
    with pytest.raises(LedgerLoadError, match="non-empty list"):
        parse_ledger_payload(empty_curve)

    bad_account = dict(base_payload, final_account="invalid")
    with pytest.raises(LedgerLoadError, match="final_account"):
        parse_ledger_payload(bad_account)

    missing_file = tmp_path / "does_not_exist.json"
    with pytest.raises(LedgerLoadError, match="not found"):
        load_ledger_json(missing_file, allowed_dir=tmp_path)


def test_ac02_edge_case_zero_fills_under_strict_100_brl_sizing() -> None:
    """Verify strict 2% risk on R$ 100 produces flat equity and empty trade markers."""
    ohlcv = _make_trending_ohlcv(60)
    for col in ("Open", "High", "Low", "Close"):
        ohlcv[col] = ohlcv[col] * 2.0  # ~R$ 62-92 so 5% stop exceeds R$ 2.00 risk cap
    provider = _FakeDataProvider(ohlcv)
    service = DashboardService(data_provider=provider)
    params = DashboardParameters(
        ticker="VALE3.SA",
        fast_period=5,
        slow_period=12,
        initial_capital=100.0,
        max_risk_per_trade_pct=0.02,
        allow_min_lot_override=False,
    )
    snapshot = service.run_analysis(params)

    assert snapshot.paper_report.filled_orders == 0
    assert snapshot.paper_report.final_cash == pytest.approx(100.0)
    assert snapshot.trade_markers.empty
    assert snapshot.telemetry.open_shares == 0
    assert snapshot.telemetry.cash_balance == pytest.approx(100.0)

"""Unit and headless Streamlit AppTest tests for UI components and app entrypoint."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from src.dashboard.components import (
    build_receipts_dataframe,
    build_snapshot_json_bytes,
)
from src.dashboard.models import DashboardParameters
from src.dashboard.service import DashboardService, load_ledger_json
from src.data.exceptions import DataDownloadError
from src.data.interfaces import IDataProvider
from src.execution.models import OrderReceipt, OrderSide, OrderStatus

_APP_PATH = str(Path(__file__).resolve().parents[3] / "src" / "dashboard" / "app.py")


class _FakeDataProvider(IDataProvider):
    """Deterministic in-memory OHLCV data provider for headless AppTest runs."""

    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df
        self.call_count = 0

    def fetch_ohlcv(
        self,
        ticker: str,
        start_date: str | None = None,
        end_date: str | None = None,
        period: str | None = "1y",
        interval: str = "1d",
    ) -> pd.DataFrame:
        self.call_count += 1
        return self._df.copy()


class _FailingDataProvider(IDataProvider):
    """Data provider simulating upstream Yahoo Finance outages."""

    def fetch_ohlcv(
        self,
        ticker: str,
        start_date: str | None = None,
        end_date: str | None = None,
        period: str | None = "1y",
        interval: str = "1d",
    ) -> pd.DataFrame:
        raise DataDownloadError(f"Simulated network outage for {ticker}")


class _FakeUpload:
    """Minimal in-memory stand-in matching Streamlit UploadedFile interface."""

    def __init__(self, name: str, payload: bytes) -> None:
        self.name = name
        self._payload = payload

    def getvalue(self) -> bytes:
        return self._payload


def _make_trending_ohlcv(bars: int = 90) -> pd.DataFrame:
    """Build synthetic B3 OHLCV bars producing clean EMA crossovers."""
    dates = pd.date_range("2024-01-02", periods=bars, freq="B")
    p1 = np.linspace(38.0, 31.0, bars // 3)
    p2 = np.linspace(31.5, 46.0, bars // 3)
    p3 = np.linspace(45.5, 36.0, bars - len(p1) - len(p2))
    close = np.concatenate([p1, p2, p3])
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


def _patch_fake_yfinance(
    monkeypatch: pytest.MonkeyPatch,
    provider: IDataProvider,
    tmp_path: Path,
) -> None:
    """Redirect DashboardService provider & cache instantiation away from network."""
    cache_root = tmp_path / "cache"
    monkeypatch.setattr(
        "src.dashboard.service.YFinanceDataProvider",
        lambda cache_manager=None: provider,
    )
    monkeypatch.setattr(
        "src.dashboard.service.DataCacheManager",
        lambda cache_dir=".cache/data": cache_root,
    )


def test_ac08_build_receipts_dataframe_formats_empty_and_populated() -> None:
    """Verify receipt DataFrame handles empty lists and formats populated receipts."""
    empty_df = build_receipts_dataframe([])
    assert empty_df.empty
    assert list(empty_df.columns) == [
        "Data Envio",
        "Ativo B3",
        "Lado",
        "Qtd Solicitada",
        "Qtd Executada",
        "Preço Fill (R$)",
        "Taxa B3 (R$)",
        "Status",
        "Client Order ID",
        "Mensagem",
    ]

    ts = datetime(2024, 6, 3, tzinfo=timezone.utc)  # noqa: UP017
    receipt = OrderReceipt(
        broker_order_id="BRK-001",
        client_order_id="CLI-001",
        ticker="ITUB4.SA",
        execution_symbol="ITUB4F",
        side=OrderSide.BUY,
        requested_shares=2,
        filled_shares=2,
        fill_price=32.456,
        b3_fee_paid=0.0195,
        status=OrderStatus.FILLED,
        submitted_at=ts,
        filled_at=ts,
        message="Filled at close",
    )
    populated = build_receipts_dataframe([receipt])
    assert len(populated) == 1
    assert populated.iloc[0]["Ativo B3"] == "ITUB4F"
    assert populated.iloc[0]["Lado"] == "BUY"
    assert populated.iloc[0]["Preço Fill (R$)"] == 32.46
    assert populated.iloc[0]["Taxa B3 (R$)"] == 0.0195


def test_ac10_build_snapshot_json_bytes_round_trips_via_ledger_loader() -> None:
    """Verify exported Phase 5 ledger JSON bytes pass strict Phase 6 schema validation."""
    service = DashboardService(data_provider=_FakeDataProvider(_make_trending_ohlcv()))
    snapshot = service.run_analysis(
        DashboardParameters(
            ticker="ITUB4.SA",
            fast_period=5,
            slow_period=12,
            allow_min_lot_override=True,
        )
    )
    raw_bytes = build_snapshot_json_bytes(snapshot)
    reloaded = load_ledger_json(raw_bytes, source_name="exported_itub4.json")

    assert reloaded.ticker == "ITUB4.SA"
    assert reloaded.initial_cash == snapshot.paper_report.initial_cash
    assert reloaded.filled_orders == snapshot.paper_report.filled_orders


def test_ac03_ac08_ac11_apptest_renders_full_dashboard_and_uses_session_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Headless AppTest renders Obsidian terminal, 3 tabs, telemetry strip, and caches."""
    provider = _FakeDataProvider(_make_trending_ohlcv())
    _patch_fake_yfinance(monkeypatch, provider, tmp_path)

    at = AppTest.from_file(_APP_PATH, default_timeout=15)
    at.run()

    assert not at.exception
    assert not at.error
    assert provider.call_count == 1

    all_markdown = "\n".join(md.value for md in at.markdown)
    assert "Mesa Quantitativa" in all_markdown
    assert "ITUB4.SA" in all_markdown
    assert "ACTIVE" in all_markdown
    assert len(at.tabs) == 3

    # Rerunning without changing parameters hits session cache rather than provider
    at.run()
    assert not at.exception
    assert provider.call_count == 1

    # Clicking explicit refresh button bypasses session cache and re-runs pipeline
    at.button(key="qt_refresh_btn").click().run()
    assert not at.exception
    assert provider.call_count == 2


def test_ac04_ac08_apptest_educational_override_and_custom_inputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Switching risk profile and custom date/advanced controls runs cleanly."""
    provider = _FakeDataProvider(_make_trending_ohlcv(110))
    _patch_fake_yfinance(monkeypatch, provider, tmp_path)

    at = AppTest.from_file(_APP_PATH, default_timeout=15)
    at.run()
    assert not at.exception

    # Strict R$ 100 default often shows zero-order educational banner
    initial_md = "\n".join(md.value for md in at.markdown)
    assert "Zero Ordens" in initial_md or "Ordens Executadas" in initial_md

    # Switch to Educational 1 Fractional Lot Override -> executes fractional ITUB4F orders
    at.selectbox(key="qt_risk_profile").select(
        "Educacional 1 Lote Fracionário (Override)"
    ).run()
    assert not at.exception
    updated_md = "\n".join(md.value for md in at.markdown)
    assert "ITUB4F" in updated_md

    # Exercise custom advanced controls and custom date window
    at.radio(key="qt_window_mode").set_value("Datas Personalizadas").run()
    at.date_input(key="qt_start_date").set_value(date(2024, 1, 2)).run()
    at.date_input(key="qt_end_date").set_value(date(2024, 6, 28)).run()
    at.selectbox(key="qt_risk_profile").select("Personalizado (Avançado)").run()
    at.slider(key="qt_risk_pct").set_value(5.0).run()
    at.checkbox(key="qt_min_lot_override").check().run()
    at.slider(key="qt_stop_pct").set_value(6.0).run()
    at.slider(key="qt_ks_dd_pct").set_value(12.0).run()
    at.number_input(key="qt_sim_latency").set_value(50.0).run()
    at.checkbox(key="qt_allow_day_trade").check().run()

    assert not at.exception


def test_ac09_ac11_apptest_rejects_xss_custom_ticker_cleanly(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """XSS-like custom ticker renders friendly Brazilian alert instead of traceback."""
    provider = _FakeDataProvider(_make_trending_ohlcv())
    _patch_fake_yfinance(monkeypatch, provider, tmp_path)

    at = AppTest.from_file(_APP_PATH, default_timeout=15)
    at.run()

    at.selectbox(key="qt_asset_selector").select("Outro ticker (Custom)").run()
    at.text_input(key="qt_custom_ticker").input("<script>alert(1)</script>").run()

    assert not at.exception
    assert len(at.error) >= 1
    assert "Parâmetros inválidos na barra lateral" in at.error[0].value


def test_ac11_apptest_handles_upstream_data_download_error_gracefully(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Upstream DataDownloadError surfaces clean alert while keeping audit tab usable."""
    _patch_fake_yfinance(monkeypatch, _FailingDataProvider(), tmp_path)

    at = AppTest.from_file(_APP_PATH, default_timeout=15)
    at.run()

    assert not at.exception
    assert len(at.error) >= 1
    assert "Não foi possível executar a análise" in at.error[0].value
    # Audit uploader remains available even when data download fails
    all_markdown = "\n".join(md.value for md in at.markdown)
    assert "Inspetor Seguro de Ledger JSON" in all_markdown


@pytest.mark.parametrize(
    ("upload_payload", "expected_error_substr"),
    [
        (None, None),
        (b"{invalid json", "Falha de segurança/validação"),
    ],
)
def test_ac10_apptest_ledger_upload_renders_valid_and_rejects_corrupt_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    upload_payload: bytes | None,
    expected_error_substr: str | None,
) -> None:
    """Ledger uploader renders valid Phase 5 JSON ledgers and flags invalid files."""
    provider = _FakeDataProvider(_make_trending_ohlcv())
    _patch_fake_yfinance(monkeypatch, provider, tmp_path)

    if upload_payload is None:
        service = DashboardService(data_provider=provider)
        snap = service.run_analysis(
            DashboardParameters(
                ticker="ITUB4.SA",
                fast_period=5,
                slow_period=12,
                allow_min_lot_override=True,
            )
        )
        fake_upload: Any = _FakeUpload(
            "valid_ledger.json", build_snapshot_json_bytes(snap)
        )
    else:
        fake_upload = _FakeUpload("corrupt_ledger.json", upload_payload)

    monkeypatch.setattr(
        "src.dashboard.components.st.file_uploader",
        lambda *args, **kwargs: fake_upload,
    )

    at = AppTest.from_file(_APP_PATH, default_timeout=15)
    at.run()

    assert not at.exception
    if expected_error_substr is None:
        assert not at.error
        all_markdown = "\n".join(md.value for md in at.markdown)
        assert "valid_ledger.json" in all_markdown
    else:
        assert any(expected_error_substr in err.value for err in at.error)

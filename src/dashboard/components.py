"""Reusable Streamlit UI sections for the B3 Quantitative Obsidian dashboard."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import pandas as pd
import streamlit as st

from src.dashboard.charts import (
    build_capital_allocation_figure,
    build_drawdown_figure,
    build_equity_comparison_figure,
    build_price_ema_figure,
)
from src.dashboard.exceptions import LedgerLoadError
from src.dashboard.models import (
    B3_PRESET_ASSETS,
    DashboardParameters,
    DashboardSnapshot,
    LoadedLedgerSummary,
    RiskTelemetrySnapshot,
)
from src.dashboard.service import load_ledger_json, telemetry_from_ledger
from src.dashboard.theme import (
    build_explainer_banner_html,
    build_kpi_card_html,
    build_telemetry_strip_html,
    escape_html,
)
from src.execution.models import OrderReceipt


def build_receipts_dataframe(receipts: list[OrderReceipt]) -> pd.DataFrame:
    """Convert OrderReceipt objects into a clean tabular DataFrame for UI & CSV."""
    columns = [
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
    if not receipts:
        return pd.DataFrame(columns=columns)

    rows = [
        {
            "Data Envio": rec.submitted_at.strftime("%Y-%m-%d"),
            "Ativo B3": rec.execution_symbol,
            "Lado": rec.side.value,
            "Qtd Solicitada": rec.requested_shares,
            "Qtd Executada": rec.filled_shares,
            "Preço Fill (R$)": (
                round(rec.fill_price, 2) if rec.fill_price is not None else None
            ),
            "Taxa B3 (R$)": round(rec.b3_fee_paid, 4),
            "Status": rec.status.value,
            "Client Order ID": rec.client_order_id,
            "Mensagem": rec.message,
        }
        for rec in receipts
    ]
    return pd.DataFrame(rows, columns=columns)


def build_snapshot_json_bytes(snapshot: DashboardSnapshot) -> bytes:
    """Serialize the paper report ledger payload into clean UTF-8 JSON bytes."""
    payload: dict[str, Any] = snapshot.paper_report.to_dict()
    return json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")


def render_sidebar_controls() -> tuple[DashboardParameters, bool]:
    """Render sidebar strategy/risk inputs and return validated DashboardParameters."""
    st.sidebar.markdown(
        '<div class="qt-label" style="margin-bottom:0.4rem;">'
        "QUAN-T · CONFIGURAÇÃO DA MESA B3"
        "</div>",
        unsafe_allow_html=True,
    )

    asset_options = [
        f"{asset.ticker} — {asset.label}" for asset in B3_PRESET_ASSETS
    ] + ["Outro ticker (Custom)"]
    selected_option = st.sidebar.selectbox(
        "Ativo B3",
        options=asset_options,
        index=0,
        key="qt_asset_selector",
    )

    if selected_option == "Outro ticker (Custom)":
        ticker = st.sidebar.text_input(
            "Código do Ativo (ex: BBAS3.SA)",
            value="ITUB4.SA",
            key="qt_custom_ticker",
        )
    else:
        ticker = selected_option.split(" — ", maxsplit=1)[0]

    window_mode = st.sidebar.radio(
        "Janela Histórica",
        options=["Período Rápido", "Datas Personalizadas"],
        horizontal=True,
        key="qt_window_mode",
    )

    start_date: date | None = None
    end_date: date | None = None
    period: str | None = "3y"
    if window_mode == "Período Rápido":
        period = st.sidebar.selectbox(
            "Período",
            options=["6mo", "1y", "2y", "3y", "5y"],
            index=3,
            key="qt_period",
        )
    else:
        default_end = date.today()
        default_start = default_end - timedelta(days=365 * 3)
        raw_start = st.sidebar.date_input(
            "Data Inicial", value=default_start, key="qt_start_date"
        )
        raw_end = st.sidebar.date_input(
            "Data Final", value=default_end, key="qt_end_date"
        )
        start_date = raw_start if isinstance(raw_start, date) else default_start
        end_date = raw_end if isinstance(raw_end, date) else default_end
        period = None

    st.sidebar.markdown("---")
    fast_period = int(
        st.sidebar.number_input(
            "EMA Rápida (pregões)",
            min_value=2,
            max_value=100,
            value=9,
            step=1,
            key="qt_fast_ema",
        )
    )
    slow_period = int(
        st.sidebar.number_input(
            "EMA Lenta (pregões)",
            min_value=3,
            max_value=252,
            value=21,
            step=1,
            key="qt_slow_ema",
        )
    )

    st.sidebar.markdown("---")
    initial_capital = float(
        st.sidebar.number_input(
            "Capital Inicial (R$)",
            min_value=10.0,
            max_value=1_000_000.0,
            value=100.0,
            step=50.0,
            key="qt_initial_capital",
        )
    )

    risk_profile = st.sidebar.selectbox(
        "Perfil de Risco & Lote B3",
        options=[
            "Conservador 2% (Estrito R$ 100)",
            "Educacional 1 Lote Fracionário (Override)",
            "Personalizado (Avançado)",
        ],
        index=0,
        key="qt_risk_profile",
    )

    max_risk_per_trade_pct = 0.02
    allow_min_lot_override = False
    stop_loss_pct = 0.05
    trailing_stop_pct: float | None = 0.05
    max_daily_loss_pct = 0.02
    max_drawdown_pct = 0.10
    max_latency_ms = 500.0
    allow_day_trade = False
    simulated_latency_ms = 45.0
    b3_fee_pct = 0.0003
    slippage_pct = 0.0

    if risk_profile == "Educacional 1 Lote Fracionário (Override)":
        allow_min_lot_override = True
    elif risk_profile == "Personalizado (Avançado)":
        max_risk_per_trade_pct = (
            float(
                st.sidebar.slider(
                    "Risco Máx. por Trade (%)",
                    min_value=1.0,
                    max_value=20.0,
                    value=2.0,
                    step=0.5,
                    key="qt_risk_pct",
                )
            )
            / 100.0
        )
        allow_min_lot_override = st.sidebar.checkbox(
            "Permitir 1 lote fracionário mínimo (Override)",
            value=False,
            key="qt_min_lot_override",
        )
        stop_loss_pct = (
            float(
                st.sidebar.slider(
                    "Stop Loss (%)",
                    min_value=1.0,
                    max_value=20.0,
                    value=5.0,
                    step=0.5,
                    key="qt_stop_pct",
                )
            )
            / 100.0
        )
        trailing_stop_pct = stop_loss_pct
        max_drawdown_pct = (
            float(
                st.sidebar.slider(
                    "Limite Kill-Switch Drawdown (%)",
                    min_value=2.0,
                    max_value=30.0,
                    value=10.0,
                    step=1.0,
                    key="qt_ks_dd_pct",
                )
            )
            / 100.0
        )
        simulated_latency_ms = float(
            st.sidebar.number_input(
                "Latência Simulada (ms)",
                min_value=0.0,
                max_value=2000.0,
                value=45.0,
                step=10.0,
                key="qt_sim_latency",
            )
        )
        allow_day_trade = st.sidebar.checkbox(
            "Liberar Day Trade (Desativa trava D0)",
            value=False,
            key="qt_allow_day_trade",
        )

    use_cache = st.sidebar.checkbox(
        "Usar Cache Local Parquet", value=True, key="qt_use_cache"
    )
    force_refresh = st.sidebar.button(
        "Atualizar Análise", type="primary", width="stretch", key="qt_refresh_btn"
    )

    with st.sidebar.expander("Guia Rápido · Regras XP / B3", expanded=False):
        st.markdown(
            "- **RLP Ativo:** Corretagem `R$ 0,00` na XP para ações.\n"
            "- **Mercado Fracionário (`'F'`):** Ordens entre `1` e `99` ações usam sufixo `'F'` (`ITUB4F`).\n"
            "- **Emolumentos B3:** Taxa oficial de `~0,03%` sobre o giro financeiro.\n"
            "- **Swing Trade (Padrão):** Bloqueia saídas voluntárias em `D0` para evitar multa de zeragem compulsória da mesa.\n"
            "- **Kill-Switch:** Disjuntor dispara em perda diária `>= 2%`, drawdown `>= 10%` ou latência `> 500 ms`."
        )

    params = DashboardParameters(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        period=period,
        fast_period=fast_period,
        slow_period=slow_period,
        initial_capital=initial_capital,
        b3_fee_pct=b3_fee_pct,
        slippage_pct=slippage_pct,
        max_risk_per_trade_pct=max_risk_per_trade_pct,
        allow_min_lot_override=allow_min_lot_override,
        stop_loss_pct=stop_loss_pct,
        trailing_stop_pct=trailing_stop_pct,
        max_daily_loss_pct=max_daily_loss_pct,
        max_drawdown_pct=max_drawdown_pct,
        max_latency_ms=max_latency_ms,
        allow_day_trade=allow_day_trade,
        simulated_latency_ms=simulated_latency_ms,
        use_cache=use_cache,
    )
    return params, force_refresh


def render_header_and_telemetry(telemetry: RiskTelemetrySnapshot) -> None:
    """Render editorial desk header and signature Risk & Kill-Switch Telemetry Strip."""
    st.markdown(
        '<div style="display:flex; justify-content:space-between; align-items:flex-end; '
        'margin-bottom:0.65rem; flex-wrap:wrap; gap:0.5rem;">'
        "<div>"
        '<div class="qt-label" style="color: var(--accent-alpha);">'
        "QUANT-TRADING-HUB · B3 SOVEREIGN TERMINAL"
        "</div>"
        '<h1 style="margin:0; font-size:1.72rem; line-height:1.15;">'
        "Mesa Quantitativa &amp; Paper Trading B3"
        "</h1>"
        "</div>"
        '<div class="qt-pill qt-pill-active">'
        "RLP TAXA ZERO · FRACIONÁRIO 'F' · SWING TRADE"
        "</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown(build_telemetry_strip_html(telemetry), unsafe_allow_html=True)


def render_strategy_tab(snapshot: DashboardSnapshot) -> None:
    """Render Tab 1: Strategy & Backtest Lab with asymmetric Bento KPIs and charts."""
    comp = snapshot.comparison_report
    net_metrics = snapshot.net_backtest.metrics
    risk_metrics = snapshot.risk_adjusted_backtest.metrics
    params = snapshot.parameters

    net_tone = "alpha" if comp.net_return_pct >= 0.0 else "halt"
    dd_tone = "warn" if abs(comp.max_drawdown_pct) < 10.0 else "halt"

    bento_html = (
        '<div class="qt-bento-grid">'
        + build_kpi_card_html(
            label=f"Retorno Líquido ({comp.ticker})",
            value=f"{comp.net_return_pct:+.2f}%",
            subtitle=(
                f"Bruto {comp.gross_return_pct:+.2f}% · Buy & Hold "
                f"{comp.benchmark_return_pct:+.2f}% · CAGR {comp.cagr_net_pct:+.2f}%/ano"
            ),
            tone=net_tone,
            hero=True,
        )
        + build_kpi_card_html(
            label="Sharpe Ratio & Profit Factor",
            value=f"{net_metrics.sharpe_ratio:.2f} · PF {comp.profit_factor:.2f}",
            subtitle=(
                f"Sortino {net_metrics.sortino_ratio:.2f} · Win Rate {comp.win_rate_pct:.1f}%"
            ),
            tone="alpha" if net_metrics.sharpe_ratio >= 0.0 else "warn",
        )
        + build_kpi_card_html(
            label="Fricção B3 (0,03% / giro)",
            value=f"{comp.total_friction_cost_pct:.2f}%",
            subtitle=f"{comp.total_trades} trocas em {comp.trading_days} pregões",
            tone="warn",
        )
        + build_kpi_card_html(
            label="Max Drawdown vs Risco",
            value=f"{comp.max_drawdown_pct:.2f}%",
            subtitle=(
                f"Com Overlay Risco: {risk_metrics.max_drawdown_pct:.2f}% "
                f"(Ret {risk_metrics.total_return_pct:+.2f}%)"
            ),
            tone=dd_tone,
        )
        + "</div>"
    )
    st.markdown(bento_html, unsafe_allow_html=True)

    st.markdown(
        build_explainer_banner_html(
            "Proteção Sem Viés (Look-Ahead Bias)",
            (
                f"O sinal EMA ({params.fast_period}/{params.slow_period}) calculado no "
                "fechamento t entra apenas no pregão t+1 com recorte do aquecimento "
                "inicial e desconto oficial de emolumentos B3 (0,03%) por giro."
            ),
        ),
        unsafe_allow_html=True,
    )

    price_fig = build_price_ema_figure(
        snapshot.ohlcv_with_indicators,
        trade_markers=snapshot.trade_markers,
        ticker=params.ticker,
        fast_period=params.fast_period,
        slow_period=params.slow_period,
    )
    st.plotly_chart(price_fig, width="stretch", theme=None)

    col_eq, col_dd = st.columns((1.35, 1.0))
    with col_eq:
        eq_fig = build_equity_comparison_figure(
            snapshot.net_backtest.equity_curve,
            risk_equity_curve=snapshot.risk_adjusted_backtest.equity_curve,
            initial_capital=params.initial_capital,
            ticker=params.ticker,
        )
        st.plotly_chart(eq_fig, width="stretch", theme=None)
    with col_dd:
        dd_fig = build_drawdown_figure(
            snapshot.net_backtest.equity_curve,
            risk_equity_curve=snapshot.risk_adjusted_backtest.equity_curve,
            kill_switch_drawdown_pct=params.max_drawdown_pct,
            drawdown_in_pct=False,
            ticker=params.ticker,
        )
        st.plotly_chart(dd_fig, width="stretch", theme=None)


def render_paper_desk_tab(snapshot: DashboardSnapshot) -> None:
    """Render Tab 2: Paper Trading Desk with R$ 100 fractional B3 lot breakdown."""
    paper = snapshot.paper_report
    params = snapshot.parameters
    exec_sym = snapshot.telemetry.execution_symbol

    paper_tone = "alpha" if paper.total_return_pct >= 0.0 else "halt"
    bento_html = (
        '<div class="qt-bento-grid">'
        + build_kpi_card_html(
            label=f"Patrimônio Paper MTM ({exec_sym})",
            value=f"R$ {paper.final_equity:,.2f}",
            subtitle=(
                f"Retorno {paper.total_return_pct:+.2f}% vs Buy & Hold "
                f"{paper.benchmark_return_pct:+.2f}% · Base R$ {paper.initial_cash:,.2f}"
            ),
            tone=paper_tone,
            hero=True,
        )
        + build_kpi_card_html(
            label="Caixa Residual Livre",
            value=f"R$ {paper.final_cash:,.2f}",
            subtitle=f"Custódia atual: {snapshot.telemetry.open_shares} ação(ões)",
            tone="bench",
        )
        + build_kpi_card_html(
            label="PnL Realizado & Taxas B3",
            value=f"R$ {paper.realized_pnl:+,.2f}",
            subtitle=f"Emolumentos B3 pagos: R$ {paper.total_fees_paid:.4f}",
            tone="alpha" if paper.realized_pnl >= 0.0 else "halt",
        )
        + build_kpi_card_html(
            label="Ordens Executadas",
            value=f"{paper.filled_orders} / {paper.total_orders}",
            subtitle=(
                f"Max DD Paper {paper.max_drawdown_pct:.2f}% · "
                f"Halts: {paper.halt_count}"
            ),
            tone="neutral" if paper.filled_orders > 0 else "warn",
        )
        + "</div>"
    )
    st.markdown(bento_html, unsafe_allow_html=True)

    if paper.filled_orders == 0:
        st.markdown(
            build_explainer_banner_html(
                "Zero Ordens no Modo Risco Estrito",
                (
                    f"Com capital de R$ {params.initial_capital:,.2f} e risco máximo de "
                    f"{params.max_risk_per_trade_pct * 100.0:.1f}% por operação "
                    f"(R$ {params.initial_capital * params.max_risk_per_trade_pct:.2f}), "
                    "1 ação inteira com Stop de "
                    f"{params.stop_loss_pct * 100.0:.1f}% excedeu o limite de risco "
                    "por trade. Para visualizar compras fracionárias educacionais, "
                    "selecione 'Educacional 1 Lote Fracionário (Override)' na barra lateral."
                ),
            ),
            unsafe_allow_html=True,
        )

    alloc_fig = build_capital_allocation_figure(
        paper.equity_curve,
        ticker=params.ticker,
        execution_symbol=exec_sym,
    )
    st.plotly_chart(alloc_fig, width="stretch", theme=None)

    receipts_df = build_receipts_dataframe(paper.receipts)
    st.markdown("#### Recibos de Ordens (`OrderReceipt`)")
    if receipts_df.empty:
        st.info("Nenhuma ordem enviada nesta simulação com os filtros atuais.")
    else:
        st.dataframe(receipts_df, width="stretch", hide_index=True)
        st.download_button(
            label="Baixar Recibos Paper (CSV)",
            data=receipts_df.to_csv(index=False).encode("utf-8"),
            file_name=f"{params.ticker.lower()}_paper_receipts.csv",
            mime="text/csv",
            key="qt_dl_receipts_csv",
        )


def _render_loaded_ledger_section(ledger: LoadedLedgerSummary) -> None:
    """Render inspected Phase 5 JSON ledger summary and equity curve."""
    st.markdown(
        f"**Arquivo auditado:** `{escape_html(ledger.source_name)}` "
        f"(Schema v{ledger.schema_version} · {escape_html(ledger.ticker)})"
    )
    ledger_telemetry = telemetry_from_ledger(ledger)
    st.markdown(build_telemetry_strip_html(ledger_telemetry), unsafe_allow_html=True)
    fig = build_equity_comparison_figure(
        ledger.equity_curve,
        initial_capital=ledger.initial_cash,
        ticker=ledger.ticker,
    )
    st.plotly_chart(fig, width="stretch", theme=None)
    if ledger.receipts.empty:
        st.info("O ledger importado não possui ordens registradas.")
    else:
        st.dataframe(ledger.receipts, width="stretch", hide_index=True)


def render_telemetry_audit_tab(snapshot: DashboardSnapshot | None) -> None:
    """Render Tab 3: Kill-Switch diagnostics, exports, and safe Phase 5 Ledger audit."""
    if snapshot is not None:
        tel = snapshot.telemetry
        col1, col2, col3 = st.columns(3)
        daily_ratio = min(
            1.0,
            max(0.0, abs(min(0.0, tel.daily_pnl_pct)) / tel.max_daily_loss_limit_pct),
        )
        dd_ratio = min(
            1.0,
            max(
                0.0,
                abs(min(0.0, tel.current_drawdown_pct)) / tel.max_drawdown_limit_pct,
            ),
        )
        lat_ratio = min(
            1.0, max(0.0, tel.observed_latency_ms / tel.max_latency_limit_ms)
        )

        with col1:
            st.markdown("**Uso do Limite Diário (-2%)**")
            st.progress(daily_ratio)
            st.caption(
                f"PnL Diário: {tel.daily_pnl_pct * 100.0:+.2f}% "
                f"(Trava: -{tel.max_daily_loss_limit_pct * 100.0:.1f}%)"
            )
        with col2:
            st.markdown("**Uso do Disjuntor Drawdown (-10%)**")
            st.progress(dd_ratio)
            st.caption(
                f"Drawdown atual: {tel.current_drawdown_pct * 100.0:.2f}% "
                f"(Limite: -{tel.max_drawdown_limit_pct * 100.0:.1f}%)"
            )
        with col3:
            st.markdown("**Consumo do Teto de Latência**")
            st.progress(lat_ratio)
            st.caption(
                f"Latência observada: {tel.observed_latency_ms:.1f} ms "
                f"(Máx.: {tel.max_latency_limit_ms:.0f} ms)"
            )

        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            st.download_button(
                label="Exportar Curva Paper (CSV)",
                data=snapshot.paper_report.equity_curve.to_csv().encode("utf-8"),
                file_name=f"{snapshot.parameters.ticker.lower()}_paper_curve.csv",
                mime="text/csv",
                key="qt_dl_curve_csv",
            )
        with dl_col2:
            st.download_button(
                label="Exportar Ledger Completo Fase 5 (JSON)",
                data=build_snapshot_json_bytes(snapshot),
                file_name=f"{snapshot.parameters.ticker.lower()}_ledger.json",
                mime="application/json",
                key="qt_dl_ledger_json",
            )

        st.markdown("#### Auditoria Barra a Barra")
        st.dataframe(
            snapshot.paper_report.equity_curve.tail(150),
            width="stretch",
        )

    st.markdown("---")
    st.markdown("#### Inspetor Seguro de Ledger JSON (Fase 5)")
    uploaded = st.file_uploader(
        "Carregar arquivo ledger.json gerado pelo PaperTradingRunner (máx. 10 MB)",
        type=["json"],
        key="qt_ledger_uploader",
    )
    if uploaded is not None:
        try:
            loaded = load_ledger_json(
                uploaded.getvalue(),
                source_name=uploaded.name,
            )
            _render_loaded_ledger_section(loaded)
        except LedgerLoadError as exc:
            st.error(f"Falha de segurança/validação ao ler Ledger JSON: {exc}")

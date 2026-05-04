"""
Tab 3 — Output Dashboard
Tables and charts from a completed model run stored in st.session_state["history"].
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
import streamlit as st

from modules.wtp_model import WTPModel
from ui import charts


def _history_to_prices_df(history: list) -> pd.DataFrame:
    rows = []
    for s in history:
        for p in s.market.prices:
            rows.append({
                "year": p.year,
                "region": p.region,
                "clearing_price_usd_per_mt": p.clearing_price_usd_per_mt,
                "pricing_regime": p.pricing_regime,
                "shadow_price_usd_per_mt": p.shadow_price_usd_per_mt,
                "supply_cost_usd_per_mt": p.supply_cost_usd_per_mt,
                "transport_premium_usd_per_mt": p.transport_premium_usd_per_mt,
                "mandate_premium_usd_per_mt": p.mandate_premium_usd_per_mt,
                "carbon_offset_usd_per_mt": p.carbon_offset_usd_per_mt,
                "margin_usd_per_mt": p.margin_usd_per_mt,
            })

    # Add volume-weighted global price row per year
    _wtp_tmp = WTPModel()
    for s in history:
        if not s.market.market_balanced:
            continue
        demand_vols = s.demand.volume_by_region(s.year)
        total_vol = 0.0
        weighted_price = 0.0
        for p in s.market.prices:
            if p.pricing_regime == "wtp_priority_allocation":
                vol = demand_vols.get(p.region, 0.0)
                weighted_price += p.clearing_price_usd_per_mt * vol
                total_vol += vol
        if total_vol > 0:
            rows.append({
                "year": s.year,
                "region": "Global (vol-wtd)",
                "clearing_price_usd_per_mt": round(weighted_price / total_vol, 2),
                "pricing_regime": "volume_weighted",
                "shadow_price_usd_per_mt": 0.0,
                "supply_cost_usd_per_mt": 0.0,
                "transport_premium_usd_per_mt": 0.0,
                "mandate_premium_usd_per_mt": 0.0,
                "carbon_offset_usd_per_mt": 0.0,
                "margin_usd_per_mt": 0.0,
            })

    return pd.DataFrame(rows)


def _history_to_flows_df(history: list) -> pd.DataFrame:
    rows = []
    for s in history:
        for f in s.market.trade_flows:
            rows.append({
                "year": f.year,
                "origin_region": f.origin_region,
                "destination_region": f.destination_region,
                "volume_mt": f.volume_mt,
                "transport_cost_usd_per_mt": f.transport_cost_usd_per_mt,
            })
    return pd.DataFrame(rows)


def _history_to_capacity_df(history: list) -> pd.DataFrame:
    rows = []
    for s in history:
        for plant in s.capacity.plants:
            rows.append({
                "year": s.year,
                "region": plant.region,
                "pathway": plant.pathway,
                "total_capacity_mt_yr": round(plant.capacity_mt_yr, 4),
                "capacity_type": "Planned" if plant.is_deterministic else "Modelled",
            })
    return pd.DataFrame(rows)


def _history_to_summary_df(history: list) -> pd.DataFrame:
    rows = []
    for s in history:
        rows.append({
            "year": s.year,
            "total_demand_mt": s.demand.total_volume_mt(s.year),
            "total_produced_mt": s.market.total_saf_produced_mt,
            "total_traded_mt": s.market.total_saf_traded_mt,
            "market_balanced": s.market.market_balanced,
            "expansion_triggered": s.expansion.build_triggered,
        })
    return pd.DataFrame(rows)


def _download_csv(df: pd.DataFrame, filename: str, label: str = "Download CSV") -> None:
    csv = df.to_csv(index=False)
    st.download_button(label=label, data=csv, file_name=filename, mime="text/csv")


def render(history: Optional[list] = None) -> None:
    if history is None:
        history = st.session_state.get("history")

    if not history:
        st.info("No run results yet. Go to **▶ Run Model** to execute the model.")
        return

    st.header("Model Outputs")

    prices_df   = _history_to_prices_df(history)
    flows_df    = _history_to_flows_df(history)
    capacity_df = _history_to_capacity_df(history)
    summary_df  = _history_to_summary_df(history)

    tab_summary, tab_prices, tab_capacity, tab_trade = st.tabs([
        "📊 Market Summary", "💰 Prices", "🏭 Capacity", "🚢 Trade Flows"
    ])

    # ── Market Summary ───────────────────────────────────────────────────────
    with tab_summary:
        st.subheader("Annual Market Summary")
        st.dataframe(summary_df.style.format({
            "year": "{:.0f}",
            "total_demand_mt": "{:.3f}",
            "total_produced_mt": "{:.3f}",
            "total_traded_mt": "{:.3f}",
        }), use_container_width=True)
        _download_csv(summary_df, "market_summary.csv", "⬇ Download")

        st.plotly_chart(charts.market_balance_bar(summary_df), use_container_width=True)

    # ── Prices ───────────────────────────────────────────────────────────────
    with tab_prices:
        if prices_df.empty:
            st.warning("No price data available — some years may have had supply shortfalls.")
        else:
            # Global volume-weighted price (primary view)
            st.subheader("Global Market Price")
            st.caption("Volume-weighted average across all served regions.")
            st.plotly_chart(charts.global_price_chart(prices_df), use_container_width=True)

            # WTP multi-year trend
            st.subheader("Willingness-to-Pay by Region")
            st.caption("Final WTP (max of Case 1/2/3) per region across all model years.")
            balanced_states = [s for s in history if s.market.market_balanced]
            if balanced_states:
                _wtp_model = WTPModel()
                wtp_rows = []
                for s in balanced_states:
                    wtp_matrix = _wtp_model.compute_wtp(s.year, s.capacity)
                    for w in wtp_matrix.regional_wtps:
                        wtp_rows.append({
                            "year": s.year,
                            "region": w.region,
                            "case1_value": w.case1_value,
                            "case2_value": w.case2_value,
                            "case3_value": w.case3_value,
                            "wtp_usd_per_mt": w.wtp_usd_per_mt,
                            "binding_case": w.binding_case,
                        })
                if wtp_rows:
                    wtp_trend_df = pd.DataFrame(wtp_rows)
                    st.plotly_chart(charts.wtp_trend_chart(wtp_trend_df), use_container_width=True)

            # Supply-demand MAC curve
            st.subheader("Supply-Demand (MAC) Curve")
            st.caption("Supply bars sorted by cost ascending (cheapest supply first). Demand bars sorted by WTP descending.")
            balanced_years = sorted({s.year for s in history if s.market.market_balanced})
            if balanced_years:
                sd_year = st.selectbox("Year for S-D curve", balanced_years,
                                       index=0, key="sd_year_out")
                sd_state = next((s for s in history if s.year == sd_year), None)
                if sd_state:
                    _wtp_model2 = WTPModel()
                    demand_by_region = sd_state.demand.volume_by_region(sd_year)
                    sd_data = _wtp_model2.build_sd_curve_data(
                        sd_year, sd_state.capacity, demand_by_region
                    )
                    st.plotly_chart(
                        charts.supply_demand_curve(
                            sd_data["demand_steps"],
                            sd_data["supply_steps"],
                            sd_year,
                        ),
                        use_container_width=True,
                    )
            else:
                st.info("Supply-demand curve available only for years when market balanced.")

            # Per-region price decomposition
            with st.expander("Per-Region Price Decomposition"):
                region_prices_df = prices_df[prices_df["region"] != "Global (vol-wtd)"]
                if not region_prices_df.empty:
                    regions = sorted(region_prices_df["region"].unique())
                    sel_region = st.selectbox("Region for price decomposition", regions, key="price_region")
                    st.plotly_chart(
                        charts.price_decomposition_bar(region_prices_df, sel_region),
                        use_container_width=True,
                    )

            st.subheader("Raw Price Data")
            st.dataframe(
                prices_df.style.format({"year": "{:.0f}", "clearing_price_usd_per_mt": "{:.2f}"}),
                use_container_width=True,
            )
            _download_csv(prices_df, "prices.csv", "⬇ Download prices.csv")

    # ── Capacity ─────────────────────────────────────────────────────────────
    with tab_capacity:
        if capacity_df.empty:
            st.warning("No capacity data available.")
        else:
            # Planned vs Modelled split (primary view)
            st.plotly_chart(charts.capacity_stacked_split(capacity_df), use_container_width=True)

            col1, col2 = st.columns(2)
            with col1:
                st.plotly_chart(charts.capacity_stacked_area(capacity_df), use_container_width=True)
            with col2:
                st.plotly_chart(charts.capacity_by_pathway(capacity_df), use_container_width=True)

            st.subheader("Raw Capacity Data")
            st.dataframe(
                capacity_df.style.format({"year": "{:.0f}", "total_capacity_mt_yr": "{:.4f}"}),
                use_container_width=True,
            )
            _download_csv(capacity_df, "capacity.csv", "⬇ Download capacity.csv")

    # ── Trade Flows ──────────────────────────────────────────────────────────
    with tab_trade:
        if flows_df.empty:
            st.warning("No trade flow data available.")
        else:
            years = sorted(flows_df["year"].unique())
            sel_year = st.selectbox("Year", years, index=len(years) - 1, key="trade_year")

            col1, col2 = st.columns(2)
            with col1:
                st.plotly_chart(charts.trade_heatmap(flows_df, sel_year), use_container_width=True)
            with col2:
                st.plotly_chart(charts.trade_sankey(flows_df, sel_year), use_container_width=True)

            st.subheader("Raw Trade Flow Data")
            st.dataframe(
                flows_df[flows_df["year"] == sel_year].style.format({"year": "{:.0f}"}),
                use_container_width=True,
            )
            _download_csv(flows_df, "trade_flows.csv", "⬇ Download trade_flows.csv")

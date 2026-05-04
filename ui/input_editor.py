"""
Tab 1 — Input Editor
Editable tables for all mock CSV inputs and demand/CORSIA charts.
"""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from ui import charts

_MOCK_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "mock")


def _mock_path(filename: str) -> str:
    return os.path.join(_MOCK_DIR, filename)


def _load(filename: str) -> pd.DataFrame:
    return pd.read_csv(_mock_path(filename))


def _save(df: pd.DataFrame, filename: str) -> None:
    df.to_csv(_mock_path(filename), index=False)
    # Invalidate CORSIA cache so demand_model reloads
    try:
        import data.loaders as _loaders
        _loaders._CORSIA_CACHE = None
    except Exception:
        pass


def render() -> None:
    st.header("Model Inputs")
    st.caption(
        "Edit any table below and click **Save** to update the inputs used by the model. "
        "The original mock data is overwritten in place."
    )

    (tab_demand, tab_corsia, tab_capacity, tab_feedstock,
     tab_transport, tab_regulatory,
     tab_routes, tab_aircraft, tab_corsia_sched, tab_wtp) = st.tabs([
        "📈 Demand", "🔄 CORSIA Suppression", "🏭 Committed Capacity",
        "🌿 Feedstock Availability", "🚢 Transport Costs", "📋 Regulatory Params",
        "✈️ Airlines & Routes", "🛫 Aircraft Types", "📅 CORSIA Schedule", "💰 WTP Parameters",
    ])

    # ── Demand ──────────────────────────────────────────────────────────────
    with tab_demand:
        df = _load("demand_mock.csv")
        st.subheader("Demand Trajectories")
        st.plotly_chart(charts.demand_trajectory(df), use_container_width=True)
        st.subheader("Raw Data")
        edited = st.data_editor(df, use_container_width=True, num_rows="dynamic", key="demand_editor")
        if st.button("💾 Save Demand", key="save_demand"):
            _save(edited, "demand_mock.csv")
            st.success("demand_mock.csv saved.")

    # ── CORSIA Suppression ───────────────────────────────────────────────────
    with tab_corsia:
        df = _load("corsia_suppression.csv")
        st.subheader("CORSIA Demand Suppression Factors")
        st.caption(
            "Suppression factor ∈ (0, 1]: fraction of full demand used in voluntary-market "
            "regions during early years. EU is always 1.0 (regulated). "
            "Adjust these to model different CORSIA eligibility timelines."
        )
        st.plotly_chart(charts.corsia_suppression_chart(df), use_container_width=True)
        st.subheader("Raw Data")
        edited = st.data_editor(df, use_container_width=True, num_rows="dynamic", key="corsia_editor")
        if st.button("💾 Save CORSIA Factors", key="save_corsia"):
            _save(edited, "corsia_suppression.csv")
            st.success("corsia_suppression.csv saved.")

    # ── Committed Capacity ───────────────────────────────────────────────────
    with tab_capacity:
        df = _load("committed_capacity.csv")
        st.subheader("Committed (Deterministic) Capacity Pipeline")
        st.caption("Plants with known online dates. Endogenous expansion is built on top of these.")
        capacity_summary = df.groupby("region")["capacity_mt_yr"].sum().reset_index()
        fig = __import__("plotly.express", fromlist=["bar"]).bar(
            capacity_summary, x="region", y="capacity_mt_yr",
            title="Committed Capacity by Region (MT/yr)",
            labels={"capacity_mt_yr": "Capacity (MT/yr)"},
        )
        st.plotly_chart(fig, use_container_width=True)
        edited = st.data_editor(df, use_container_width=True, num_rows="dynamic", key="cap_editor")
        if st.button("💾 Save Committed Capacity", key="save_cap"):
            _save(edited, "committed_capacity.csv")
            st.success("committed_capacity.csv saved.")

    # ── Feedstock Availability ───────────────────────────────────────────────
    with tab_feedstock:
        df = _load("feedstock_availability.csv")
        st.subheader("Feedstock Availability")
        st.caption("Annual available feedstock in MT. CO2_green_H2 represents renewable-electricity-derived green hydrogen for the PtL pathway.")
        year_options = sorted(df["year"].unique())
        sel_year = st.selectbox("Preview year", year_options, index=0, key="fs_year")
        year_df = df[df["year"] == sel_year]
        pivot = year_df.pivot_table(index="region", columns="feedstock_type", values="max_available_mt", fill_value=0)
        st.dataframe(pivot.style.format("{:.3f}"), use_container_width=True)
        with st.expander("Edit full table"):
            edited = st.data_editor(df, use_container_width=True, num_rows="dynamic", key="fs_editor")
            if st.button("💾 Save Feedstock Availability", key="save_fs"):
                _save(edited, "feedstock_availability.csv")
                st.success("feedstock_availability.csv saved.")

    # ── Transport Costs ──────────────────────────────────────────────────────
    with tab_transport:
        df = _load("transport_costs.csv")
        st.subheader("Transport Cost Matrix (USD/MT)")
        pivot = df.pivot(index="origin", columns="destination", values="transport_cost_usd_per_mt").fillna(0)
        import plotly.express as px
        fig = px.imshow(
            pivot, text_auto=".0f", title="Transport Cost (USD/MT)",
            labels={"x": "Destination", "y": "Origin", "color": "USD/MT"},
            color_continuous_scale="YlOrRd",
        )
        st.plotly_chart(fig, use_container_width=True)
        edited = st.data_editor(df, use_container_width=True, num_rows="dynamic", key="tc_editor")
        if st.button("💾 Save Transport Costs", key="save_tc"):
            _save(edited, "transport_costs.csv")
            st.success("transport_costs.csv saved.")

    # ── Regulatory Parameters ────────────────────────────────────────────────
    with tab_regulatory:
        df = _load("regulatory_params.csv")
        st.subheader("Regulatory Parameters")
        st.caption("ReFuelEU mandate fractions, penalties, and carbon taxes by region and year.")
        eu_df = df[df["region"] == "EU"].sort_values("year")
        if "mandate_fraction" in eu_df.columns:
            import plotly.express as px
            fig = px.line(
                eu_df, x="year", y="mandate_fraction",
                title="EU ReFuelEU Mandate Fraction Over Time",
                labels={"mandate_fraction": "Mandate Fraction", "year": "Year"},
                markers=True,
            )
            st.plotly_chart(fig, use_container_width=True)
        with st.expander("Edit full table"):
            edited = st.data_editor(df, use_container_width=True, num_rows="dynamic", key="reg_editor")
            if st.button("💾 Save Regulatory Params", key="save_reg"):
                _save(edited, "regulatory_params.csv")
                st.success("regulatory_params.csv saved.")

    # ── Airlines & Routes ────────────────────────────────────────────────────
    with tab_routes:
        import plotly.express as px
        st.subheader("Airlines & Flight Routes")
        st.caption(
            "Major airlines and representative flight routes used by the bottom-up demand module. "
            "Each route row drives CORSIA SAF demand (60% origin / 40% destination attribution) "
            "and domestic mandate demand."
        )
        col_a, col_b = st.columns(2)
        with col_a:
            airlines_df = _load("airlines.csv")
            st.markdown("**Airlines**")
            edited_al = st.data_editor(airlines_df, use_container_width=True, num_rows="dynamic", key="airlines_editor")
            if st.button("💾 Save Airlines", key="save_airlines"):
                _save(edited_al, "airlines.csv")
                st.success("airlines.csv saved.")
        with col_b:
            region_counts = edited_al.groupby("home_region").size().reset_index(name="count")
            fig = px.bar(region_counts, x="home_region", y="count",
                         title="Airlines by Home Region",
                         labels={"home_region": "Region", "count": "# Airlines"})
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")
        routes_df = _load("flight_routes.csv")
        st.markdown("**Flight Routes**")
        st.caption("annual_flights_2025 × annual_growth_rate drives fuel burn projections.")

        type_counts = routes_df.groupby(["origin_region", "flight_type"]).size().reset_index(name="count")
        fig2 = px.bar(type_counts, x="origin_region", y="count", color="flight_type", barmode="stack",
                      title="Routes by Origin Region and Type",
                      labels={"origin_region": "Origin Region", "count": "# Routes"})
        st.plotly_chart(fig2, use_container_width=True)

        with st.expander("Edit routes table"):
            edited_rt = st.data_editor(routes_df, use_container_width=True, num_rows="dynamic", key="routes_editor")
            if st.button("💾 Save Routes", key="save_routes"):
                _save(edited_rt, "flight_routes.csv")
                st.success("flight_routes.csv saved.")

    # ── Aircraft Types ───────────────────────────────────────────────────────
    with tab_aircraft:
        import plotly.express as px
        st.subheader("Aircraft Fuel Efficiency")
        st.caption("Fuel efficiency in tonnes of fuel per km (whole aircraft). Efficiency improves 1.5% per year from 2025 base.")
        ac_df = _load("aircraft_types.csv")
        fig = px.bar(
            ac_df.sort_values("fuel_efficiency_t_per_km"),
            x="aircraft_type", y="fuel_efficiency_t_per_km",
            title="Aircraft Fuel Efficiency (t fuel/km)",
            labels={"aircraft_type": "Aircraft Type", "fuel_efficiency_t_per_km": "t/km"},
            color="fuel_efficiency_t_per_km",
            color_continuous_scale="RdYlGn_r",
        )
        fig.update_layout(showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
        edited_ac = st.data_editor(ac_df, use_container_width=True, num_rows="dynamic", key="aircraft_editor")
        if st.button("💾 Save Aircraft Types", key="save_aircraft"):
            _save(edited_ac, "aircraft_types.csv")
            st.success("aircraft_types.csv saved.")

    # ── CORSIA Schedule ───────────────────────────────────────────────────────
    with tab_corsia_sched:
        import plotly.express as px
        st.subheader("CORSIA Mandatory Fraction Schedule")
        st.caption(
            "mandatory_fraction: fraction of international fuel burn above 2019 baseline "
            "that airlines must offset (SAF counts as a credit). "
            "Increases sharply after 2027 (Phase 1 mandatory start)."
        )
        cs_df = _load("corsia_schedule.csv")
        fig = px.line(
            cs_df, x="year", y="mandatory_fraction",
            title="CORSIA Mandatory Fraction Over Time",
            labels={"mandatory_fraction": "Mandatory Fraction", "year": "Year"},
            markers=True,
        )
        fig.add_vline(x=2027, line_dash="dash", line_color="gray",
                      annotation_text="Phase 1 start", annotation_position="top right")
        st.plotly_chart(fig, use_container_width=True)

        col1, col2 = st.columns(2)
        with col1:
            fig2 = px.line(
                cs_df, x="year", y="carbon_credit_usd_per_tco2",
                title="CORSIA Carbon Credit Price (USD/tCO₂)",
                labels={"carbon_credit_usd_per_tco2": "USD/tCO₂", "year": "Year"},
                markers=True,
            )
            st.plotly_chart(fig2, use_container_width=True)
        with col2:
            edited_cs = st.data_editor(cs_df, use_container_width=True, num_rows="dynamic", key="corsia_sched_editor")
            if st.button("💾 Save CORSIA Schedule", key="save_corsia_sched"):
                _save(edited_cs, "corsia_schedule.csv")
                st.success("corsia_schedule.csv saved.")

    # ── WTP Parameters ────────────────────────────────────────────────────────
    with tab_wtp:
        import plotly.express as px
        st.subheader("Willingness-to-Pay Parameters")
        st.caption(
            "Per-region WTP inputs used by WTPModel. "
            "**Case 1** = jet_fuel_price + CORSIA_credit × 2.5 tCO₂/MT. "
            "**Case 2** = LCOSAF at target_irr_pct (computed from CAPEX/OPEX). "
            "**Case 3** = case3_penalty_usd_per_mt (e.g. ReFuelEU). "
            "Final WTP = max of the three cases."
        )
        wtp_df = _load("wtp_params.csv")
        year_opts = sorted(wtp_df["year"].unique())
        sel_yr = st.selectbox("Preview year", year_opts, index=0, key="wtp_year_sel")
        yr_wtp = wtp_df[wtp_df["year"] == sel_yr].copy()

        # Compute case values for preview
        from config.settings import REGIONAL_CAPEX, REGIONAL_OPEX, SAF_PATHWAYS, UTILIZATION_FACTOR, PROJECT_LIFE_YR
        from utils.economics import levelised_cost
        _CI = 2.5
        yr_wtp["case1_preview"] = yr_wtp["jet_fuel_price_usd_per_mt"] + yr_wtp["corsia_credit_usd_per_tco2"] * _CI
        yr_wtp["case3_preview"] = yr_wtp["case3_penalty_usd_per_mt"]

        def _case2(row):
            irr = float(row["target_irr_pct"]) / 100.0
            region = str(row["region"])
            r_capex = REGIONAL_CAPEX.get(region, REGIONAL_CAPEX.get("ROW", {}))
            r_opex  = REGIONAL_OPEX.get(region, REGIONAL_OPEX.get("ROW", {}))
            return min(
                levelised_cost(r_capex.get(p, 2000), r_opex.get(p, 600),
                               UTILIZATION_FACTOR, irr, PROJECT_LIFE_YR)
                for p in SAF_PATHWAYS
            )

        yr_wtp["case2_preview"] = yr_wtp.apply(_case2, axis=1)
        yr_wtp["final_wtp"]     = yr_wtp[["case1_preview", "case2_preview", "case3_preview"]].max(axis=1)

        fig = px.bar(
            yr_wtp, x="region",
            y=["case1_preview", "case2_preview", "case3_preview"],
            title=f"WTP Case Breakdown — Year {sel_yr}",
            labels={"value": "USD/MT SAF", "variable": "WTP Case", "region": "Region"},
            barmode="group",
            color_discrete_map={
                "case1_preview": "steelblue",
                "case2_preview": "seagreen",
                "case3_preview": "tomato",
            },
        )
        fig.add_scatter(x=yr_wtp["region"], y=yr_wtp["final_wtp"],
                        mode="markers", name="Final WTP",
                        marker=dict(symbol="diamond", size=10, color="black"))
        st.plotly_chart(fig, use_container_width=True)

        # ── LCOSAF heatmap & bar ──────────────────────────────────────────────
        st.subheader("LCOSAF by Region and Pathway")
        st.caption(
            "Levelised Cost of SAF = (CRF × CAPEX + OPEX) / Utilisation. "
            "OPEX includes full feedstock + processing + logistics costs."
        )
        from config.settings import REGIONS as _REGIONS, SAF_PATHWAYS as _PATHWAYS
        from ui import charts as _charts
        irr_sel = st.slider("Target IRR (%)", 8, 20, 12, key="lcosaf_irr") / 100.0
        col_h, col_b = st.columns(2)
        with col_h:
            st.plotly_chart(
                _charts.lcosaf_heatmap(
                    _REGIONS, _PATHWAYS,
                    REGIONAL_CAPEX, REGIONAL_OPEX,
                    UTILIZATION_FACTOR, irr_sel, PROJECT_LIFE_YR,
                ),
                use_container_width=True,
            )
        with col_b:
            st.plotly_chart(
                _charts.lcosaf_bar(
                    _REGIONS, _PATHWAYS,
                    REGIONAL_CAPEX, REGIONAL_OPEX,
                    UTILIZATION_FACTOR, irr_sel, PROJECT_LIFE_YR,
                ),
                use_container_width=True,
            )

        # ── Route sample fraction ─────────────────────────────────────────────
        from config.settings import ROUTE_SAMPLE_FRACTION as _RSF
        st.info(
            f"**Route sample fraction:** {_RSF:.0%} — "
            "the 64 representative routes represent this fraction of global scheduled traffic. "
            "CORSIA SAF demand is scaled by this factor; mandate demand is not. "
            "Edit `config/settings.py` → `ROUTE_SAMPLE_FRACTION` to adjust."
        )

        st.markdown("**Edit WTP Parameters**")
        with st.expander("Edit full table"):
            edited_wtp = st.data_editor(wtp_df, use_container_width=True, num_rows="dynamic", key="wtp_editor")
            if st.button("💾 Save WTP Params", key="save_wtp"):
                _save(edited_wtp, "wtp_params.csv")
                st.success("wtp_params.csv saved.")

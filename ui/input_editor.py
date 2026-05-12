"""
Tab 1 — Input Editor
Editable tables for all mock CSV inputs. The Demand Module tab consolidates
all demand building blocks as nested sub-tabs with methodology explanations.
"""

from __future__ import annotations

import os

import pandas as pd
import plotly.express as px
import streamlit as st

from ui import charts

_MOCK_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "mock")


def _mock_path(filename: str) -> str:
    return os.path.join(_MOCK_DIR, filename)


def _load(filename: str) -> pd.DataFrame:
    return pd.read_csv(_mock_path(filename))


def _save(df: pd.DataFrame, filename: str) -> None:
    df.to_csv(_mock_path(filename), index=False)
    try:
        import data.loaders as _loaders
        _loaders._CORSIA_CACHE = None
    except Exception:
        pass


def _upload_widget(filename: str, ss_key: str) -> pd.DataFrame:
    """
    Show a CSV file-uploader and return the DataFrame to use in the editor.

    Priority order:
      1. A newly uploaded file (stored in session state).
      2. A previously uploaded file still in session state (survives reruns).
      3. The on-disk mock CSV (default).

    Call _clear_upload(ss_key) after a successful save to reset to on-disk state.
    """
    uploaded = st.file_uploader(
        f"📂 Upload replacement CSV for `{filename}`",
        type="csv",
        key=f"_up_{ss_key}",
        help="Upload a CSV with the same columns as the existing table. "
             "The uploaded data will populate the editor below — review, then click Save.",
    )
    if uploaded is not None:
        try:
            st.session_state[ss_key] = pd.read_csv(uploaded)
            st.success(f"CSV loaded ({len(st.session_state[ss_key])} rows). Review below and click **Save** to apply.")
        except Exception as exc:
            st.error(f"Could not parse CSV: {exc}")
    return st.session_state.get(ss_key, _load(filename))


def _clear_upload(ss_key: str) -> None:
    """Remove uploaded data from session state after a successful save."""
    st.session_state.pop(ss_key, None)


def render() -> None:
    st.header("Model Inputs")
    st.caption(
        "Edit any table below and click **Save** to update the inputs used by the model. "
        "The original mock data is overwritten in place."
    )

    (tab_demand, tab_capacity, tab_feedstock,
     tab_transport, tab_regulatory, tab_wtp) = st.tabs([
        "✈️ Demand Module", "🏭 Committed Capacity",
        "🌿 Feedstock Availability", "🚢 Transport Costs",
        "📋 Regulatory Params", "💰 WTP Parameters",
    ])

    # ════════════════════════════════════════════════════════════════════════
    # ✈️  DEMAND MODULE — all building blocks as nested sub-tabs
    # ════════════════════════════════════════════════════════════════════════
    with tab_demand:
        st.subheader("Bottom-Up Demand Module")
        st.markdown(
            """
            SAF demand is estimated from first principles using a bottom-up flight-activity model
            rather than a simple top-down trajectory. The module combines four independent data
            streams — flight routes, aircraft fuel efficiency, CORSIA international offsetting
            obligations, and domestic blending mandates — to produce an annual regional SAF demand
            figure that responds dynamically to policy changes, fleet renewal, and traffic growth.
            The 64 representative routes in the dataset approximate **5% of global scheduled
            traffic** (`ROUTE_SAMPLE_FRACTION = 0.05`); CORSIA demand is scaled by this factor,
            while mandate demand represents absolute policy targets and is not scaled.
            """
        )

        (sub_routes, sub_airlines, sub_aircraft,
         sub_corsia_sched, sub_corsia_supp, sub_mandates) = st.tabs([
            "🗺️ Flight Routes", "🏢 Airlines", "🛫 Aircraft Efficiency",
            "📅 CORSIA Schedule", "🔄 CORSIA Suppression", "📜 Blending Mandates",
        ])

        # ── Flight Routes ─────────────────────────────────────────────────────
        with sub_routes:
            st.markdown(
                """
                ### Methodology
                Each row in this table represents a representative scheduled route operated by a
                named airline. Fuel burn for a given year is computed as:

                > **Fuel (MT) = Annual Flights × Distance (km) × Fuel Efficiency (t/km) × Efficiency Improvement Factor**

                where the efficiency improvement factor decays at **1.5% per year** from the 2025
                base to reflect progressive fleet renewal. Annual flights grow at the
                route-specific `annual_growth_rate`. For **international** routes, fuel is
                attributed 60% to the origin region and 40% to the destination region, following
                the CORSIA uplift-at-departure accounting rule. For **domestic** routes, 100% is
                attributed to the origin region and the fuel contributes only to blending mandate
                demand, not CORSIA.
                """
            )
            routes_df = _upload_widget("flight_routes.csv", "ss_flight_routes")

            col1, col2 = st.columns(2)
            with col1:
                type_counts = routes_df.groupby(
                    ["origin_region", "flight_type"]
                ).size().reset_index(name="count")
                fig = px.bar(
                    type_counts, x="origin_region", y="count", color="flight_type",
                    barmode="stack",
                    title="Routes by Origin Region and Type",
                    labels={"origin_region": "Origin Region", "count": "# Routes",
                            "flight_type": "Type"},
                )
                fig.update_layout(xaxis=dict(tickformat=""))
                st.plotly_chart(fig, use_container_width=True)
            with col2:
                dist_fig = px.histogram(
                    routes_df, x="distance_km", color="flight_type", nbins=20,
                    title="Route Distance Distribution (km)",
                    labels={"distance_km": "Distance (km)", "count": "# Routes"},
                    barmode="overlay", opacity=0.7,
                )
                st.plotly_chart(dist_fig, use_container_width=True)

            with st.expander("Edit routes table"):
                edited_rt = st.data_editor(
                    routes_df, use_container_width=True, num_rows="dynamic",
                    key="routes_editor",
                )
                if st.button("💾 Save Routes", key="save_routes"):
                    _save(edited_rt, "flight_routes.csv")
                    _clear_upload("ss_flight_routes")
                    st.success("flight_routes.csv saved.")

        # ── Airlines ─────────────────────────────────────────────────────────
        with sub_airlines:
            st.markdown(
                """
                ### Methodology
                The airlines table defines which carriers are included in the model and links each
                airline to its home region. Airlines serve as the organisational unit connecting
                flight routes to regional demand attribution. When routes are aggregated, the
                `home_region` field is used to cross-check origin attribution and to produce
                carrier-level diagnostics. In future extensions, airline-specific SAF procurement
                commitments or voluntary pledges can be added as a column here to model voluntary
                demand above the CORSIA floor.
                """
            )
            airlines_df = _upload_widget("airlines.csv", "ss_airlines")

            col_a, col_b = st.columns(2)
            with col_a:
                edited_al = st.data_editor(
                    airlines_df, use_container_width=True, num_rows="dynamic",
                    key="airlines_editor",
                )
                if st.button("💾 Save Airlines", key="save_airlines"):
                    _save(edited_al, "airlines.csv")
                    _clear_upload("ss_airlines")
                    st.success("airlines.csv saved.")
            with col_b:
                region_counts = edited_al.groupby("home_region").size().reset_index(name="count")
                fig = px.bar(
                    region_counts, x="home_region", y="count",
                    title="Airlines by Home Region",
                    labels={"home_region": "Region", "count": "# Airlines"},
                    color="count", color_continuous_scale="Blues",
                )
                fig.update_layout(showlegend=False, xaxis=dict(tickformat=""))
                st.plotly_chart(fig, use_container_width=True)

        # ── Aircraft Fuel Efficiency ──────────────────────────────────────────
        with sub_aircraft:
            st.markdown(
                """
                ### Methodology
                Fuel efficiency is expressed in **tonnes of fuel per kilometre** for the whole
                aircraft (not per seat). Each route is assigned an aircraft type from this table,
                and the base efficiency is multiplied by an annual improvement factor:

                > **Eff(year) = Eff₂₀₂₅ × (1 − 0.015)^(year − 2025)**

                The 1.5% per annum improvement rate reflects average fleet-level efficiency gains
                from new-generation aircraft (A320neo, A350, B787) entering service and retiring
                older frames. This rate can be adjusted here to test more aggressive or
                conservative technology scenarios. Heavier widebody aircraft (A380, B777) have
                lower efficiency per km in absolute terms but typically serve longer routes, so
                their contribution to total fuel burn depends heavily on route distance.
                """
            )
            ac_df = _upload_widget("aircraft_types.csv", "ss_aircraft_types")
            fig = px.bar(
                ac_df.sort_values("fuel_efficiency_t_per_km"),
                x="aircraft_type", y="fuel_efficiency_t_per_km",
                title="Aircraft Fuel Efficiency (t fuel/km)",
                labels={"aircraft_type": "Aircraft Type",
                        "fuel_efficiency_t_per_km": "t/km"},
                color="fuel_efficiency_t_per_km",
                color_continuous_scale="RdYlGn_r",
            )
            fig.update_layout(showlegend=False, xaxis=dict(tickformat=""))
            st.plotly_chart(fig, use_container_width=True)

            edited_ac = st.data_editor(
                ac_df, use_container_width=True, num_rows="dynamic",
                key="aircraft_editor",
            )
            if st.button("💾 Save Aircraft Types", key="save_aircraft"):
                _save(edited_ac, "aircraft_types.csv")
                _clear_upload("ss_aircraft_types")
                st.success("aircraft_types.csv saved.")

        # ── CORSIA Schedule ───────────────────────────────────────────────────
        with sub_corsia_sched:
            st.markdown(
                """
                ### Methodology
                CORSIA (Carbon Offsetting and Reduction Scheme for International Aviation)
                requires airlines to offset CO₂ growth above the 2019 baseline. SAF counts as
                a full credit against this obligation because its lifecycle emissions are
                substantially lower than fossil jet fuel. The **mandatory fraction** defines
                the share of international fuel burn above the 2019 baseline that must be
                covered by offsets or SAF credits in each year. CORSIA SAF demand is therefore:

                > **CORSIA SAF Demand (MT) = International Fuel Burn (MT) × mandatory_fraction**

                The carbon credit price (`carbon_credit_usd_per_tco2`) determines the value of
                a SAF credit in Case 1 of the WTP calculation:
                `Case 1 WTP = Jet Fuel Price + Credit Price × 2.5 tCO₂/MT SAF`.
                Phase 1 of mandatory CORSIA begins in 2027, at which point the mandatory fraction
                steps up sharply and SAF becomes significantly more economically attractive
                relative to conventional offsets.
                """
            )
            cs_df = _upload_widget("corsia_schedule.csv", "ss_corsia_schedule")

            col1, col2 = st.columns(2)
            with col1:
                fig1 = px.line(
                    cs_df, x="year", y="mandatory_fraction",
                    title="CORSIA Mandatory Fraction Over Time",
                    labels={"mandatory_fraction": "Mandatory Fraction", "year": "Year"},
                    markers=True,
                )
                fig1.add_vline(x=2027, line_dash="dash", line_color="gray",
                               annotation_text="Phase 1 start",
                               annotation_position="top right")
                fig1.update_layout(xaxis=dict(tickformat="d"))
                st.plotly_chart(fig1, use_container_width=True)
            with col2:
                fig2 = px.line(
                    cs_df, x="year", y="carbon_credit_usd_per_tco2",
                    title="CORSIA Carbon Credit Price (USD/tCO₂)",
                    labels={"carbon_credit_usd_per_tco2": "USD/tCO₂", "year": "Year"},
                    markers=True,
                )
                fig2.update_layout(xaxis=dict(tickformat="d"))
                st.plotly_chart(fig2, use_container_width=True)

            with st.expander("Edit CORSIA schedule"):
                edited_cs = st.data_editor(
                    cs_df, use_container_width=True, num_rows="dynamic",
                    key="corsia_sched_editor",
                )
                if st.button("💾 Save CORSIA Schedule", key="save_corsia_sched"):
                    _save(edited_cs, "corsia_schedule.csv")
                    _clear_upload("ss_corsia_schedule")
                    st.success("corsia_schedule.csv saved.")

        # ── CORSIA Suppression ────────────────────────────────────────────────
        with sub_corsia_supp:
            st.markdown(
                """
                ### Methodology
                Not all regions participate in CORSIA on the same timeline. The suppression
                factor (∈ (0, 1]) scales the effective demand in voluntary-participation
                regions to reflect the fact that airlines in those regions face a weaker
                economic incentive to purchase SAF credits during the voluntary phase
                (2021–2026). The EU is always assigned a suppression factor of **1.0** because
                ReFuelEU mandates apply independently of CORSIA voluntary status. Regions with
                suppression factors below 1.0 have their CORSIA-driven SAF demand reduced:

                > **Effective CORSIA Demand (region, year) = Raw CORSIA Demand × suppression_factor**

                As CORSIA transitions from voluntary to mandatory (post-2027), suppression
                factors for participating regions should be raised towards 1.0. This table
                allows analysts to model different CORSIA uptake scenarios — for example,
                a slow-participation scenario would keep suppression factors low through 2030.
                """
            )
            supp_df = _upload_widget("corsia_suppression.csv", "ss_corsia_suppression")
            st.plotly_chart(charts.corsia_suppression_chart(supp_df), use_container_width=True)
            with st.expander("Edit suppression factors"):
                edited_supp = st.data_editor(
                    supp_df, use_container_width=True, num_rows="dynamic",
                    key="corsia_supp_editor",
                )
                if st.button("💾 Save CORSIA Suppression", key="save_corsia_supp"):
                    _save(edited_supp, "corsia_suppression.csv")
                    _clear_upload("ss_corsia_suppression")
                    st.success("corsia_suppression.csv saved.")

        # ── Blending Mandates ─────────────────────────────────────────────────
        with sub_mandates:
            st.markdown(
                """
                ### Methodology
                National blending mandates require a minimum fraction of jet fuel sold or
                uplifted domestically to be SAF. Unlike CORSIA — which is based on growth
                above a baseline — mandates apply to the **total domestic fuel burn** in
                each year. Mandate demand is therefore:

                > **Mandate SAF Demand (MT) = Domestic Fuel Burn (MT) × mandate_fraction**

                Only domestic routes contribute to mandate demand; international routes are
                covered by CORSIA instead. The EU ReFuelEU regulation is the primary driver
                of mandate demand in this model, with fractions rising from 2% in 2025 to
                70% by 2050. Other regions may adopt similar frameworks; these can be
                added or adjusted here. Mandate demand is **not** scaled by
                `ROUTE_SAMPLE_FRACTION` because it represents an absolute policy obligation
                rather than a sample-based estimate of market activity.
                """
            )
            mandates_df = _upload_widget("national_blending_mandates.csv", "ss_national_blending_mandates")

            col1, col2 = st.columns(2)
            with col1:
                eu_mand = mandates_df[mandates_df["region"] == "EU"].sort_values("year")
                fig = px.line(
                    eu_mand, x="year", y="mandate_fraction",
                    title="EU ReFuelEU Blending Mandate Over Time",
                    labels={"mandate_fraction": "Mandate Fraction", "year": "Year"},
                    markers=True,
                )
                fig.update_layout(xaxis=dict(tickformat="d"))
                st.plotly_chart(fig, use_container_width=True)
            with col2:
                all_regions = mandates_df[mandates_df["year"] == mandates_df["year"].max()]
                fig2 = px.bar(
                    all_regions, x="region", y="mandate_fraction",
                    title=f"Mandate Fraction by Region ({int(mandates_df['year'].max())})",
                    labels={"mandate_fraction": "Mandate Fraction", "region": "Region"},
                    color="mandate_fraction", color_continuous_scale="Greens",
                )
                fig2.update_layout(showlegend=False, xaxis=dict(tickformat=""))
                st.plotly_chart(fig2, use_container_width=True)

            with st.expander("Edit mandates table"):
                edited_mand = st.data_editor(
                    mandates_df, use_container_width=True, num_rows="dynamic",
                    key="mandates_editor",
                )
                if st.button("💾 Save Blending Mandates", key="save_mandates"):
                    _save(edited_mand, "national_blending_mandates.csv")
                    _clear_upload("ss_national_blending_mandates")
                    st.success("national_blending_mandates.csv saved.")

    # ════════════════════════════════════════════════════════════════════════
    # 🏭  COMMITTED CAPACITY
    # ════════════════════════════════════════════════════════════════════════
    with tab_capacity:
        st.subheader("Committed (Deterministic) Capacity Pipeline")
        st.markdown(
            """
            ### Methodology
            Committed capacity represents SAF plants with known or announced online dates that
            will enter the model regardless of the endogenous LP expansion decision. These plants
            are flagged `is_deterministic = True` in the capacity state and are shown separately
            from LP-built capacity in all output charts. Each plant carries its own CAPEX
            (USD per MT/yr nameplate) and OPEX (USD per MT/yr nameplate, inclusive of full
            feedstock costs), which are used to compute its LCOSAF contribution to the
            supply-demand curve. Endogenous expansion — triggered when committed supply falls
            short of projected demand — is built on top of this pipeline.
            """
        )
        df = _upload_widget("committed_capacity.csv", "ss_committed_capacity")
        capacity_summary = df.groupby("region")["capacity_mt_yr"].sum().reset_index()
        col1, col2 = st.columns(2)
        with col1:
            fig = px.bar(
                capacity_summary, x="region", y="capacity_mt_yr",
                title="Committed Capacity by Region (MT/yr)",
                labels={"capacity_mt_yr": "Capacity (MT/yr)", "region": "Region"},
                color="capacity_mt_yr", color_continuous_scale="Blues",
            )
            fig.update_layout(showlegend=False, xaxis=dict(tickformat=""))
            st.plotly_chart(fig, use_container_width=True)
        with col2:
            pathway_summary = df.groupby("pathway")["capacity_mt_yr"].sum().reset_index()
            fig2 = px.pie(
                pathway_summary, names="pathway", values="capacity_mt_yr",
                title="Committed Capacity by Pathway",
            )
            st.plotly_chart(fig2, use_container_width=True)
        edited = st.data_editor(df, use_container_width=True, num_rows="dynamic", key="cap_editor")
        if st.button("💾 Save Committed Capacity", key="save_cap"):
            _save(edited, "committed_capacity.csv")
            _clear_upload("ss_committed_capacity")
            st.success("committed_capacity.csv saved.")

    # ════════════════════════════════════════════════════════════════════════
    # 🌿  FEEDSTOCK AVAILABILITY
    # ════════════════════════════════════════════════════════════════════════
    with tab_feedstock:
        st.subheader("Feedstock Availability")
        st.markdown(
            """
            ### Methodology
            Feedstock availability constrains which SAF pathways can be expanded in each region
            and year. The capacity expansion LP uses these limits as upper bounds on the total
            throughput of any pathway that relies on a given feedstock. For example, HEFA
            capacity in a region cannot exceed what the available UCO and tallow supply can
            support at the pathway's feedstock intensity (e.g. 1.25 t UCO per MT SAF).
            `CO2_green_H2` represents the renewable electricity-derived green hydrogen and
            captured CO₂ feedstock required for the Power-to-Liquid (PtL) pathway. Feedstock
            limits grow over time as collection infrastructure and agricultural co-products
            increase; these trajectories can be edited here to model supply-chain constraints
            or regional feedstock policy changes.
            """
        )
        df = _upload_widget("feedstock_availability.csv", "ss_feedstock_availability")
        year_options = sorted(df["year"].unique())
        sel_year = st.selectbox("Preview year", year_options, index=0, key="fs_year")
        year_df = df[df["year"] == sel_year]
        pivot = year_df.pivot_table(
            index="region", columns="feedstock_type",
            values="max_available_mt", fill_value=0,
        )
        st.dataframe(pivot.style.format("{:.3f}"), use_container_width=True)
        with st.expander("Edit full table"):
            edited = st.data_editor(
                df, use_container_width=True, num_rows="dynamic", key="fs_editor",
            )
            if st.button("💾 Save Feedstock Availability", key="save_fs"):
                _save(edited, "feedstock_availability.csv")
                _clear_upload("ss_feedstock_availability")
                st.success("feedstock_availability.csv saved.")

    # ════════════════════════════════════════════════════════════════════════
    # 🚢  TRANSPORT COSTS
    # ════════════════════════════════════════════════════════════════════════
    with tab_transport:
        st.subheader("Transport Cost Matrix (USD/MT)")
        st.markdown(
            """
            ### Methodology
            SAF can be produced in one region and shipped to another; the transport cost matrix
            defines the cost (USD per MT) of moving SAF between every origin-destination pair.
            These costs include blending logistics, shipping, and any re-certification costs
            at the destination airport. In the market clearing step, supply is dispatched on a
            **cheapest cost-insurance-freight (CIF)** basis: for each destination region, the
            model selects the supply source that minimises `supply_OPEX + transport_cost`,
            subject to the destination region's WTP being sufficient to cover that total cost.
            Higher transport costs therefore reduce the competitiveness of distant supply
            sources and incentivise local production. Self-supply (same-region) is represented
            by near-zero diagonal values.
            """
        )
        df = _upload_widget("transport_costs.csv", "ss_transport_costs")
        pivot = df.pivot(
            index="origin", columns="destination",
            values="transport_cost_usd_per_mt",
        ).fillna(0)
        fig = px.imshow(
            pivot, text_auto=".0f", title="Transport Cost (USD/MT)",
            labels={"x": "Destination", "y": "Origin", "color": "USD/MT"},
            color_continuous_scale="YlOrRd",
        )
        st.plotly_chart(fig, use_container_width=True)
        edited = st.data_editor(
            df, use_container_width=True, num_rows="dynamic", key="tc_editor",
        )
        if st.button("💾 Save Transport Costs", key="save_tc"):
            _save(edited, "transport_costs.csv")
            _clear_upload("ss_transport_costs")
            st.success("transport_costs.csv saved.")

    # ════════════════════════════════════════════════════════════════════════
    # 📋  REGULATORY PARAMETERS
    # ════════════════════════════════════════════════════════════════════════
    with tab_regulatory:
        st.subheader("Regulatory Parameters")
        st.markdown(
            """
            ### Methodology
            Regulatory parameters define the policy environment that shapes SAF demand and
            pricing in each region. The key levers are: `mandate_fraction` — the minimum SAF
            blend share required by law (feeds into Case 3 WTP penalty calculations);
            `non_compliance_penalty_usd_per_mt` — the fine per MT of SAF shortfall, which sets
            the ceiling on what regulated buyers will pay (the EU ReFuelEU penalty of $2,500/MT
            is a critical driver of EU WTP); and `carbon_tax_usd_per_tco2` — a carbon price
            applied to fossil jet fuel that improves SAF's relative economics. Together these
            parameters determine how much regulatory pull exists in each region and year. The
            EU is the only currently regulated region; other regions can be activated by raising
            their penalty above zero.
            """
        )
        df = _upload_widget("regulatory_params.csv", "ss_regulatory_params")
        eu_df = df[df["region"] == "EU"].sort_values("year")
        col1, col2 = st.columns(2)
        with col1:
            if "mandate_fraction" in eu_df.columns:
                fig = px.line(
                    eu_df, x="year", y="mandate_fraction",
                    title="EU ReFuelEU Mandate Fraction Over Time",
                    labels={"mandate_fraction": "Mandate Fraction", "year": "Year"},
                    markers=True,
                )
                fig.update_layout(xaxis=dict(tickformat="d"))
                st.plotly_chart(fig, use_container_width=True)
        with col2:
            if "non_compliance_penalty_usd_per_mt" in eu_df.columns:
                fig2 = px.line(
                    eu_df, x="year", y="non_compliance_penalty_usd_per_mt",
                    title="EU Non-Compliance Penalty (USD/MT SAF)",
                    labels={"non_compliance_penalty_usd_per_mt": "Penalty (USD/MT)",
                            "year": "Year"},
                    markers=True,
                )
                fig2.update_layout(xaxis=dict(tickformat="d"))
                st.plotly_chart(fig2, use_container_width=True)
        with st.expander("Edit full table"):
            edited = st.data_editor(
                df, use_container_width=True, num_rows="dynamic", key="reg_editor",
            )
            if st.button("💾 Save Regulatory Params", key="save_reg"):
                _save(edited, "regulatory_params.csv")
                _clear_upload("ss_regulatory_params")
                st.success("regulatory_params.csv saved.")

    # ════════════════════════════════════════════════════════════════════════
    # 💰  WTP PARAMETERS
    # ════════════════════════════════════════════════════════════════════════
    with tab_wtp:
        st.subheader("Willingness-to-Pay Parameters")
        st.markdown(
            """
            ### Methodology
            Willingness-to-pay (WTP) determines the maximum price each region is prepared to
            pay for SAF. It is computed as the maximum of three independent cases, each
            capturing a different economic rationale for purchasing SAF:

            - **Case 1 — Market floor (Jet + CORSIA):** The value of SAF as a drop-in
              replacement for jet fuel, augmented by the carbon credit value avoided under
              CORSIA: `WTP₁ = Jet Fuel Price + Credit Price × 2.5 tCO₂/MT SAF`
            - **Case 2 — Investment floor (LCOSAF@IRR):** The minimum price at which a
              rational investor would build new SAF capacity, using the cheapest available
              pathway: `WTP₂ = min_pathway[(CRF(IRR, 20yr) × CAPEX + OPEX) / Utilisation]`
            - **Case 3 — Policy ceiling (Penalty):** The regulatory non-compliance penalty
              that creates a hard price ceiling for regulated buyers (e.g. EU ReFuelEU):
              `WTP₃ = non_compliance_penalty_usd_per_mt`

            > **Final WTP = max(WTP₁, WTP₂, WTP₃)**

            In practice, Case 3 dominates the EU ($2,500/MT) and Case 2 dominates all other
            regions ($980–$1,200/MT at 12% IRR). The WTP drives the clearing price: each
            served region pays exactly its WTP.
            """
        )

        from config.settings import (REGIONAL_CAPEX, REGIONAL_OPEX, SAF_PATHWAYS,
                                     UTILIZATION_FACTOR, PROJECT_LIFE_YR,
                                     REGIONS as _REGIONS, ROUTE_SAMPLE_FRACTION as _RSF)
        from utils.economics import levelised_cost

        wtp_df = _upload_widget("wtp_params.csv", "ss_wtp_params")
        year_opts = sorted(wtp_df["year"].unique())
        sel_yr = st.selectbox("Preview year", year_opts, index=0, key="wtp_year_sel")
        yr_wtp = wtp_df[wtp_df["year"] == sel_yr].copy()

        _CI = 2.5
        yr_wtp["case1_preview"] = (
            yr_wtp["jet_fuel_price_usd_per_mt"]
            + yr_wtp["corsia_credit_usd_per_tco2"] * _CI
        )
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
        yr_wtp["final_wtp"] = yr_wtp[
            ["case1_preview", "case2_preview", "case3_preview"]
        ].max(axis=1)

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
        fig.add_scatter(
            x=yr_wtp["region"], y=yr_wtp["final_wtp"],
            mode="markers", name="Final WTP",
            marker=dict(symbol="diamond", size=10, color="black"),
        )
        fig.update_layout(xaxis=dict(tickformat=""))
        st.plotly_chart(fig, use_container_width=True)

        # ── LCOSAF heatmap & bar ──────────────────────────────────────────────
        st.subheader("LCOSAF by Region and Pathway")
        st.markdown(
            """
            The Levelised Cost of SAF (LCOSAF) is the minimum long-run price at which a
            producer can recover all capital and operating costs at a given required rate of
            return. It is computed as:

            > **LCOSAF = (CRF(IRR, project_life) × CAPEX + OPEX) / Utilisation**

            where OPEX includes full feedstock, processing, and logistics costs per MT of
            installed nameplate capacity per year, and CRF is the Capital Recovery Factor.
            Use the IRR slider to explore how investor return requirements shift the
            investment floor across regions and pathways.
            """
        )
        irr_sel = st.slider("Target IRR (%)", 8, 20, 12, key="lcosaf_irr") / 100.0
        col_h, col_b = st.columns(2)
        with col_h:
            st.plotly_chart(
                charts.lcosaf_heatmap(
                    _REGIONS, SAF_PATHWAYS,
                    REGIONAL_CAPEX, REGIONAL_OPEX,
                    UTILIZATION_FACTOR, irr_sel, PROJECT_LIFE_YR,
                ),
                use_container_width=True,
            )
        with col_b:
            st.plotly_chart(
                charts.lcosaf_bar(
                    _REGIONS, SAF_PATHWAYS,
                    REGIONAL_CAPEX, REGIONAL_OPEX,
                    UTILIZATION_FACTOR, irr_sel, PROJECT_LIFE_YR,
                ),
                use_container_width=True,
            )

        st.info(
            f"**Route sample fraction:** {_RSF:.0%} — "
            "the 64 representative routes represent this fraction of global scheduled traffic. "
            "CORSIA SAF demand is scaled by this factor; mandate demand is not. "
            "Edit `config/settings.py` → `ROUTE_SAMPLE_FRACTION` to adjust."
        )

        st.markdown("**Edit WTP Parameters**")
        with st.expander("Edit full table"):
            edited_wtp = st.data_editor(
                wtp_df, use_container_width=True, num_rows="dynamic", key="wtp_editor",
            )
            if st.button("💾 Save WTP Params", key="save_wtp"):
                _save(edited_wtp, "wtp_params.csv")
                _clear_upload("ss_wtp_params")
                st.success("wtp_params.csv saved.")

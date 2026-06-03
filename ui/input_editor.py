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
_TMPL_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "templates")


def _mock_path(filename: str) -> str:
    return os.path.join(_MOCK_DIR, filename)


def _tmpl_path(filename: str) -> str:
    return os.path.join(_TMPL_DIR, filename)


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
    Show a download-template button + CSV file-uploader.

    Priority order for the returned DataFrame:
      1. A newly uploaded file (stored in session state).
      2. A previously uploaded file still in session state (survives reruns).
      3. The on-disk mock CSV (default).

    Call _clear_upload(ss_key) after a successful save to reset to on-disk state.
    """
    tmpl_path = _tmpl_path(filename)
    if os.path.exists(tmpl_path):
        with open(tmpl_path, "rb") as f:
            tmpl_bytes = f.read()
        st.download_button(
            label=f"📥 Download template: `{filename}`",
            data=tmpl_bytes,
            file_name=filename,
            mime="text/csv",
            key=f"_dl_{ss_key}",
            help="Download the baseline template CSV (with example data) as a starting point.",
        )

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


def _demand_input_mtimes() -> tuple:
    """
    Modification timestamps of the four CSVs that feed the bottom-up demand
    module, plus the module file itself. Used as a cache key so the projection
    chart re-runs when any input or the module logic changes.
    """
    csv_files = (
        "flight_routes.csv", "aircraft_types.csv",
        "corsia_schedule.csv", "corsia_suppression.csv",
    )
    csv_mtimes = tuple(
        os.path.getmtime(_mock_path(f)) if os.path.exists(_mock_path(f)) else 0.0
        for f in csv_files
    )
    _HERE = os.path.dirname(os.path.abspath(__file__))
    module_path = os.path.join(_HERE, "..", "modules", "demand_bottom_up.py")
    module_mtime = os.path.getmtime(module_path) if os.path.exists(module_path) else 0.0
    return csv_mtimes + (module_mtime,)


@st.cache_data(ttl=60)
def _build_demand_projection_df(_cache_buster: tuple) -> pd.DataFrame:
    """
    Per-year, per-region projection of jet-fuel burn and CORSIA / mandate
    SAF demand under the current inputs. The _cache_buster argument is the
    tuple of input CSV mtimes; saving any of them invalidates this cache.
    """
    from modules.demand_bottom_up import BottomUpDemandModule
    from config.settings import HORIZON_YEARS

    mod = BottomUpDemandModule()
    rows = []
    for yr in HORIZON_YEARS:
        try:
            r = mod.get_intermediate_result(yr)
        except Exception:
            continue
        for region, vol in r.fuel_by_region.items():
            rows.append({
                "year": yr,
                "region": region,
                "fuel_mt":        vol,
                "corsia_saf_mt":  r.corsia_saf_demand_by_region.get(region, 0.0),
                "mandate_saf_mt": r.mandate_saf_demand_by_region.get(region, 0.0),
            })
    return pd.DataFrame(rows)


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
            CORSIA demand is estimated from first principles using a bottom-up flight-activity
            model rather than a simple top-down trajectory. The module combines four independent
            data streams — flight routes, aircraft fuel efficiency, CORSIA international
            offsetting obligations, and domestic blending mandates — to produce an annual regional
            CORSIA demand figure that responds dynamically to policy changes, fleet renewal, and
            traffic growth.
            The 64 representative routes in the dataset approximate **5% of global scheduled
            traffic** (`ROUTE_SAMPLE_FRACTION = 0.05`); all computed volumes are extrapolated
            to the full global fleet by dividing by this fraction (×20).
            """
        )

        # ── Projection panel: per-region jet-fuel burn + CORSIA SAF demand ──
        with st.expander(
            "📊 Projected jet fuel burn and CORSIA SAF demand (2025–2045)",
            expanded=True,
        ):
            try:
                proj_df = _build_demand_projection_df(_demand_input_mtimes())
            except Exception as exc:
                st.warning(f"Could not compute demand projection: {exc}")
                proj_df = pd.DataFrame()

            if proj_df.empty:
                st.info(
                    "No demand projection available yet — check that the four "
                    "underlying CSVs (flight_routes, aircraft_types, "
                    "corsia_schedule, corsia_suppression) exist and parse."
                )
            else:
                col_jf, col_corsia = st.columns(2)
                with col_jf:
                    fig_jf = px.line(
                        proj_df, x="year", y="fuel_mt", color="region",
                        title="Jet Fuel Burn by Region (Mt / yr)",
                        labels={"fuel_mt": "Fuel (Million tonnes)", "year": "Year"},
                        markers=True,
                    )
                    fig_jf.update_layout(
                        xaxis=dict(tickformat="d"),
                        hovermode="x unified",
                        legend_title="Region",
                    )
                    st.plotly_chart(fig_jf, use_container_width=True)
                with col_corsia:
                    fig_c = px.line(
                        proj_df, x="year", y="corsia_saf_mt", color="region",
                        title="CORSIA-Mandated SAF Demand by Region (Mt / yr)",
                        labels={"corsia_saf_mt": "CORSIA SAF Demand (Million tonnes)",
                                "year": "Year"},
                        markers=True,
                    )
                    fig_c.update_layout(
                        xaxis=dict(tickformat="d"),
                        hovermode="x unified",
                        legend_title="Region",
                    )
                    st.plotly_chart(fig_c, use_container_width=True)
                st.caption(
                    "Computed live from your current routes, aircraft efficiency, "
                    "CORSIA schedule, and suppression inputs via the bottom-up demand "
                    "module. Save any edits in the sub-tabs below to refresh these "
                    "charts. Volumes are in **million tonnes per year**."
                )

        # ── Demand scaling factor ─────────────────────────────────────────────
        with st.expander("⚖️ Demand Scaling Factor", expanded=False):
            st.markdown(
                "Apply a global multiplier to all bottom-up demand volumes before "
                "market clearing. The default value of **1.0** uses the computed demand "
                "as-is. Increase above 1.0 to stress-test supply under a higher-demand "
                "scenario; decrease below 1.0 to model a smaller addressable market."
            )
            st.number_input(
                "Demand scaling factor",
                min_value=0.1,
                max_value=10.0,
                value=1.0,
                step=0.1,
                format="%.2f",
                key="demand_scale_factor",
                help="Multiplier applied to all regional SAF demand volumes (CORSIA + mandate) "
                     "before capacity expansion and market clearing.",
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
                covered by offsets or SAF credits in each year. CORSIA demand is therefore:

                > **CORSIA Demand (MT) = International Fuel Burn (MT) × mandatory_fraction**

                The carbon credit price (`carbon_credit_usd_per_tco2`) determines the value of
                a SAF credit in Case 1 of the WTP calculation:
                `Case 1 WTP = Jet Fuel Price + Credit Price × 3.1 tCO₂/MT SAF`.
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
                suppression factors below 1.0 have their CORSIA demand reduced:

                > **Effective CORSIA-Mandated Demand (region, year) = Raw CORSIA-Mandated Demand × suppression_factor**

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

                > **Mandate Demand (MT) = Domestic Fuel Burn (MT) × mandate_fraction**

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

        st.divider()

        # ── Refinery throughput → co-processing cap ─────────────────────────
        st.subheader("Refinery Co-Processing Capacity Cap")
        st.markdown(
            """
            ### Methodology
            Co-processing SAF is produced by blending bio-based feedstock (e.g. hydrotreated
            vegetable oils, pyrolysis oil) into an **existing petroleum refinery's** middle-
            distillate processing units — typically the FCC, hydrotreater, or jet hydrocracker.
            Physically, the renewable feed is limited to **5–10%** of the host unit's
            throughput; beyond that share, catalyst activity, product quality, and yield
            degrade rapidly.

            The capacity-expansion LP enforces this physical limit per region:

            > **Max Co-Processing SAF (MT/yr) = Refinery Throughput (MT/yr) × Share Max (%)**

            New endogenous co-processing builds are capped at the **headroom** between the
            regional limit and any already-committed co-processing capacity in
            `committed_capacity.csv`. If a region has no row in this table, the constraint
            is disabled for that region (effectively unlimited). Other SAF pathways
            (HEFA, ATJ, FT-MSW, PtL) are not affected by this cap.
            """
        )
        rc_df = _upload_widget("refinery_capacity.csv", "ss_refinery_capacity")
        rc_calc = rc_df.copy()
        rc_calc["max_coprocessing_mt_yr"] = (
            rc_calc["refinery_throughput_mt_yr"]
            * rc_calc["coprocessing_share_max_pct"] / 100.0
        ).round(2)

        col_r1, col_r2 = st.columns(2)
        with col_r1:
            fig_rc = px.bar(
                rc_calc, x="region", y="refinery_throughput_mt_yr",
                title="Refinery Middle-Distillate Throughput by Region (MT/yr)",
                labels={"refinery_throughput_mt_yr": "Throughput (MT/yr)", "region": "Region"},
                color="refinery_throughput_mt_yr", color_continuous_scale="Greys",
            )
            fig_rc.update_layout(showlegend=False, xaxis=dict(tickformat=""))
            st.plotly_chart(fig_rc, use_container_width=True)
        with col_r2:
            fig_cp = px.bar(
                rc_calc, x="region", y="max_coprocessing_mt_yr",
                title="Implied Max Co-Processing SAF Capacity by Region (MT/yr)",
                labels={"max_coprocessing_mt_yr": "Max Co-Processing (MT/yr)", "region": "Region"},
                color="coprocessing_share_max_pct", color_continuous_scale="Oranges",
            )
            fig_cp.update_layout(xaxis=dict(tickformat=""))
            st.plotly_chart(fig_cp, use_container_width=True)

        st.markdown("**Edit refinery throughput and co-processing share**")
        edited_rc = st.data_editor(
            rc_df, use_container_width=True, num_rows="dynamic", key="refinery_editor",
            column_config={
                "refinery_throughput_mt_yr": st.column_config.NumberColumn(
                    "Refinery Throughput (MT/yr)", min_value=0.0, step=10.0, format="%.1f",
                ),
                "coprocessing_share_max_pct": st.column_config.NumberColumn(
                    "Co-Processing Share Max (%)", min_value=0.0, max_value=100.0,
                    step=0.5, format="%.1f",
                ),
            },
        )
        if st.button("💾 Save Refinery Capacity", key="save_refinery"):
            _save(edited_rc, "refinery_capacity.csv")
            _clear_upload("ss_refinery_capacity")
            st.success("refinery_capacity.csv saved.")

        st.divider()

        # ── Domestic vs Export Share ────────────────────────────────────────
        st.subheader("Domestic vs Export Share")
        st.markdown(
            """
            ### Methodology
            Each region's effective SAF supply is split into a **domestic-priority
            pool** (reserved for local demand) and an **export-eligible pool**
            (offered to the cross-region import market). The market is cleared in
            two phases:

            - **Phase 1 — Domestic clearing.** Every region uses its
              `domestic_share` pool to serve its own demand first, subject to
              `LCOSAF ≤ regional WTP`, cheapest LCOSAF first.
            - **Phase 2 — Cross-region imports.** The export pool, plus any
              unused domestic remainder, is allocated cheapest-CIF first to
              destinations sorted by WTP descending, again filtered by
              `LCOSAF + transport ≤ destination WTP`.

            A region set to **100%** behaves as full autarky-first (e.g. the EU
            under ReFuelEU). A region at **0%** offers its full supply to the
            global pool from the start. Intermediate values express softer
            domestic preference. Regions absent from the table default to 100%.
            """
        )
        dp_df = _upload_widget("domestic_supply_priority.csv", "ss_domestic_priority")
        dp_calc = dp_df.copy()
        dp_calc["domestic_share_pct"] = dp_calc["domestic_share_pct"].clip(0, 100)
        dp_calc["export_share_pct"] = 100.0 - dp_calc["domestic_share_pct"]

        share_long = dp_calc.melt(
            id_vars="region",
            value_vars=["domestic_share_pct", "export_share_pct"],
            var_name="pool", value_name="share_pct",
        )
        share_long["pool"] = share_long["pool"].map({
            "domestic_share_pct": "Domestic (Phase 1)",
            "export_share_pct":   "Export pool (Phase 2)",
        })
        fig_share = px.bar(
            share_long, x="region", y="share_pct", color="pool",
            barmode="stack",
            title="Supply Split: Domestic Priority vs Export Pool (%)",
            labels={"region": "Region", "share_pct": "Share (%)", "pool": "Pool"},
            color_discrete_map={
                "Domestic (Phase 1)":    "#2ca02c",
                "Export pool (Phase 2)": "#9ecae1",
            },
        )
        fig_share.update_layout(yaxis_range=[0, 100], xaxis=dict(tickformat=""))
        st.plotly_chart(fig_share, use_container_width=True)

        st.markdown("**Edit per-region domestic share**")
        edited_dp = st.data_editor(
            dp_df, use_container_width=True, num_rows="dynamic", key="dp_editor",
            column_config={
                "region": st.column_config.TextColumn("Region"),
                "domestic_share_pct": st.column_config.NumberColumn(
                    "Domestic Share (%)",
                    min_value=0.0, max_value=100.0, step=1.0, format="%.0f",
                    help="Share of regional supply reserved for local demand "
                         "in Phase 1 before exports are allowed.",
                ),
            },
        )
        if st.button("💾 Save Domestic Supply Priority", key="save_domestic_priority"):
            _save(edited_dp, "domestic_supply_priority.csv")
            _clear_upload("ss_domestic_priority")
            st.success("domestic_supply_priority.csv saved.")

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

        st.caption(
            "**Units convention.** `max_available_mt` is **million tonnes of raw feedstock per "
            "year** (so 0.8 = 0.8 Mt = 800,000 t — a realistic regional UCO collection rate). "
            "`cost_usd_per_mt` is the **delivered price per metric tonne of feedstock** "
            "(e.g. UCO ≈ \$350/t). The same \"MT\" suffix in this CSV is overloaded — volumes "
            "are millions of tonnes, prices are per single tonne. SAF yield per tonne of "
            "feedstock varies by pathway (HEFA ≈ 0.80, ATJ ≈ 0.40, FT ≈ 0.25, PtL ≈ 0.36, "
            "Co-processing ≈ 1.67 t SAF / t feedstock)."
        )

        year_options = sorted(df["year"].unique())
        sel_year = st.selectbox("Preview year", year_options, index=0, key="fs_year")
        year_df = df[df["year"] == sel_year]
        pivot = year_df.pivot_table(
            index="region", columns="feedstock_type",
            values="max_available_mt", fill_value=0,
        )
        st.markdown(f"**Max Feedstock Availability — {int(sel_year)} (Million tonnes / yr)**")
        st.dataframe(pivot.style.format("{:.3f}"), use_container_width=True)
        with st.expander("Edit full table"):
            edited = st.data_editor(
                df, use_container_width=True, num_rows="dynamic", key="fs_editor",
                column_config={
                    "year": st.column_config.NumberColumn("Year", format="%d"),
                    "region": st.column_config.TextColumn("Region"),
                    "feedstock_type": st.column_config.TextColumn("Feedstock Type"),
                    "max_available_mt": st.column_config.NumberColumn(
                        "Max Available (Million tonnes / yr)", min_value=0.0, format="%.3f",
                    ),
                    "cost_usd_per_mt": st.column_config.NumberColumn(
                        "Cost (USD / tonne)", min_value=0.0, format="%.0f",
                    ),
                    "notes": st.column_config.TextColumn("Notes"),
                },
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
            Regulatory parameters define the policy environment that shapes CORSIA demand and
            pricing in each region. The key levers are: `mandate_fraction` — the minimum SAF
            blend share required by law (feeds into the Case 3 Total-Market-WTP ceiling);
            `non_compliance_penalty_usd_per_mt` — the fine per MT of SAF shortfall, one of
            several drivers behind the Case 3 ceiling (the EU ReFuelEU penalty of $1,500+/MT
            is the dominant component of EU WTP, on top of $850 baseline + ~$280 ETS); and
            `carbon_tax_usd_per_tco2` — a carbon price applied to fossil jet fuel that
            improves SAF's relative economics. Every region now carries a non-zero Case 3
            (total market WTP) reflecting CORSIA + voluntary corporate premium + any local
            mandate; edit `wtp_params.csv` to tune those regional ceilings.
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
              CORSIA: `WTP₁ = Jet Fuel Price + Credit Price × 3.1 tCO₂/MT SAF`
            - **Case 2 — Investment floor (LCOSAF@IRR):** The minimum price at which a
              rational investor would build new SAF capacity, using the cheapest available
              pathway: `WTP₂ = min_pathway[(CRF(IRR, 20yr) × CAPEX + OPEX) / Utilisation]`
            - **Case 3 — Total Market WTP ceiling:** The full price airlines in the
              region will actually pay, combining jet-fuel baseline + CORSIA / ETS / LCFS
              compliance value + a regional regulatory or voluntary premium.
              `WTP₃ = case3_penalty_usd_per_mt`. Default 2025 → 2045 trajectories:
              EU $2,600 → $3,600+ (ETS + ReFuelEU penalty),
              US $1,500 → $2,200 (LCFS + Scope-3 corporate premium),
              APAC $1,300 → $1,800 (Singapore SAF levy + emerging mandates),
              MENA $1,000 → $1,300 (small flagship-carrier premium),
              LATAM / ROW $800 → $1,000 (CORSIA only, near-zero premium).

            > **Final WTP = max(WTP₁, WTP₂, WTP₃)**

            In practice Case 3 dominates almost everywhere now: airline WTP is set by the
            local market reality (mandates, ETS, LCFS, corporate buyers) rather than by
            the abstract Case-2 LCOSAF investment floor. The WTP drives the clearing
            price: each served region pays exactly its WTP. The column name
            `case3_penalty_usd_per_mt` in `wtp_params.csv` is legacy — the value now
            represents the **total market WTP ceiling**, not only a non-compliance fine.
            """
        )

        from config.settings import (FEED_INTENSITY, REGIONAL_CAPEX, REGIONAL_OPEX,
                                     SAF_PATHWAYS, UTILIZATION_FACTOR, PROJECT_LIFE_YR,
                                     REGIONS as _REGIONS, ROUTE_SAMPLE_FRACTION as _RSF)
        from utils.economics import levelised_cost

        wtp_df = _upload_widget("wtp_params.csv", "ss_wtp_params")

        # ── Jet fuel price trajectory (drives Case 1 WTP) ────────────────────
        st.subheader("Jet Fuel Price Input Trajectory")
        fig_jet = px.line(
            wtp_df, x="year", y="jet_fuel_price_usd_per_mt", color="region",
            title="Jet Fuel Price by Region (USD / metric tonne) — drives Case 1 WTP",
            labels={"jet_fuel_price_usd_per_mt": "Jet Fuel Price (USD/t)",
                    "year": "Year"},
            markers=True,
        )
        fig_jet.update_layout(
            xaxis=dict(tickformat="d"),
            hovermode="x unified",
            legend_title="Region",
        )
        st.plotly_chart(fig_jet, use_container_width=True)
        st.caption(
            "Per-region jet fuel price over the model horizon. Case 1 WTP = "
            "jet fuel price + CORSIA credit × 3.1 tCO₂ / MT SAF."
        )

        year_opts = sorted(wtp_df["year"].unique())
        sel_yr = st.selectbox("Preview year", year_opts, index=0, key="wtp_year_sel")
        yr_wtp = wtp_df[wtp_df["year"] == sel_yr].copy()

        _CI = 3.1
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

        # ── LCOSAF by Region and Pathway ─────────────────────────────────────
        st.subheader("LCOSAF by Region and Pathway")
        st.markdown(
            """
            The Levelised Cost of SAF (LCOSAF) is the minimum long-run price at which a
            producer can recover all capital and operating costs at a given required rate of
            return:

            > **LCOSAF (USD/MT SAF) = (CRF(IRR, life) × CAPEX + OPEX_eq) / Utilisation**
            >
            > where **OPEX_eq (USD/MT capacity/yr) = (Proc. OPEX + Feedstock $/t ÷ Yield) × Utilisation**

            Use the inputs below to set per-pathway, per-region **CAPEX**, **Processing OPEX**,
            **Feedstock cost per tonne of feedstock**, and **SAF Yield**. The yield converts
            per-tonne feedstock cost into per-MT-SAF cost: a HEFA plant burning UCO at $600/t
            with a yield of 0.80 MT SAF / MT UCO incurs $600 ÷ 0.80 = $750/MT SAF in feedstock
            cost. These values update the charts on this page only and do not affect a model
            run.

            - **CAPEX** — capital cost in USD per MT/yr of nameplate capacity
            - **Processing OPEX** — non-feedstock operating cost in USD per **MT SAF** produced
            - **Feedstock $/t feed** — delivered feedstock cost per **MT of raw feedstock**
            - **Yield** — MT SAF produced per **MT of raw feedstock** (e.g. HEFA ≈ 0.80,
              ATJ ≈ 0.40, FT ≈ 0.25, PtL ≈ 0.36, Co-processing ≈ 1.67)
            """
        )

        # Primary feedstock used in FEED_INTENSITY for each pathway — used to seed yields.
        _PRIMARY_FEEDSTOCK = {
            "HEFA":          "UCO",
            "ATJ":           "agricultural_residue",
            "FT-MSW":        "MSW",
            "PtL":           "CO2_green_H2",
            "Co-processing": "UCO",
        }

        def _default_yield(pathway: str) -> float:
            """MT SAF / MT raw feedstock = 1 / feedstock intensity."""
            feed = _PRIMARY_FEEDSTOCK.get(pathway)
            intensity = FEED_INTENSITY.get(pathway, {}).get(feed or "", 0.0)
            return round(1.0 / intensity, 3) if intensity > 0 else 1.0

        # Initialise grid from settings defaults on first load (75/25 feedstock/processing split,
        # then back-calculate feedstock $/t feed using the default yield).
        if "lcosaf_cost_grid" not in st.session_state:
            grid: dict = {}
            for r in _REGIONS:
                grid[r] = {}
                for p in SAF_PATHWAYS:
                    opex_cap = REGIONAL_OPEX.get(r, {}).get(p, 600)
                    opex_saf = opex_cap / UTILIZATION_FACTOR        # USD/MT SAF
                    yld     = _default_yield(p)                     # MT SAF / MT feed
                    feed_per_saf = opex_saf * 0.75                  # USD/MT SAF (legacy split)
                    grid[r][p] = {
                        "capex":            float(REGIONAL_CAPEX.get(r, {}).get(p, 2000)),
                        "proc_opex":        round(opex_saf * 0.25, 0),
                        "feedstock_per_t":  round(feed_per_saf * yld, 0),   # USD/MT feed
                        "saf_yield":        yld,                            # MT SAF / MT feed
                    }
            st.session_state["lcosaf_cost_grid"] = grid

        grid = st.session_state["lcosaf_cost_grid"]

        # Migrate any old session-state entries (without the new fields) so the UI does not crash.
        for r in _REGIONS:
            for p in SAF_PATHWAYS:
                cell = grid.setdefault(r, {}).setdefault(p, {})
                if "feedstock_per_t" not in cell or "saf_yield" not in cell:
                    yld = _default_yield(p)
                    legacy_feed_per_saf = cell.get("feedstock", 0.0)
                    cell["feedstock_per_t"] = round(legacy_feed_per_saf * yld, 0)
                    cell["saf_yield"]      = yld
                    cell.pop("feedstock", None)

        col_reset, _ = st.columns([1, 4])
        with col_reset:
            if st.button("↺ Reset to model defaults", key="lcosaf_reset"):
                st.session_state.pop("lcosaf_cost_grid", None)
                st.rerun()

        region_tabs_lc = st.tabs(_REGIONS)
        for rtab, region in zip(region_tabs_lc, _REGIONS):
            with rtab:
                hdr = st.columns([1.6, 1.3, 1.4, 1.5, 1.4])
                hdr[0].markdown("**Pathway**")
                hdr[1].markdown("**CAPEX** $/MT cap/yr")
                hdr[2].markdown("**Proc. OPEX** $/MT SAF")
                hdr[3].markdown("**Feedstock** $/MT feed")
                hdr[4].markdown("**Yield** MT SAF / MT feed")
                for pathway in SAF_PATHWAYS:
                    kp = f"lc_{region}_{pathway}"
                    row = st.columns([1.6, 1.3, 1.4, 1.5, 1.4])
                    row[0].write(pathway)
                    grid[region][pathway]["capex"] = float(row[1].number_input(
                        "capex", value=grid[region][pathway]["capex"],
                        min_value=0.0, step=50.0, key=f"{kp}_capex",
                        label_visibility="collapsed",
                    ))
                    grid[region][pathway]["proc_opex"] = float(row[2].number_input(
                        "proc_opex", value=grid[region][pathway]["proc_opex"],
                        min_value=0.0, step=10.0, key=f"{kp}_proc",
                        label_visibility="collapsed",
                    ))
                    grid[region][pathway]["feedstock_per_t"] = float(row[3].number_input(
                        "feedstock_per_t", value=grid[region][pathway]["feedstock_per_t"],
                        min_value=0.0, step=10.0, key=f"{kp}_feed_t",
                        label_visibility="collapsed",
                    ))
                    grid[region][pathway]["saf_yield"] = float(row[4].number_input(
                        "saf_yield", value=grid[region][pathway]["saf_yield"],
                        min_value=0.001, step=0.05, format="%.3f", key=f"{kp}_yield",
                        label_visibility="collapsed",
                    ))

        # Build overridden dicts for the charts.
        # OPEX_eq (USD/MT capacity/yr) = (Proc. OPEX + Feedstock $/t ÷ Yield) × Utilisation
        def _opex_eq(cell: dict) -> float:
            yld = cell["saf_yield"] if cell["saf_yield"] > 1e-6 else 1e-6
            opex_per_saf = cell["proc_opex"] + cell["feedstock_per_t"] / yld
            return opex_per_saf * UTILIZATION_FACTOR

        custom_capex = {
            r: {p: grid[r][p]["capex"] for p in SAF_PATHWAYS}
            for r in _REGIONS
        }
        custom_opex = {
            r: {p: _opex_eq(grid[r][p]) for p in SAF_PATHWAYS}
            for r in _REGIONS
        }

        st.markdown("---")
        irr_sel = st.slider("Target IRR (%)", 8, 20, 12, key="lcosaf_irr") / 100.0
        col_h, col_b = st.columns(2)
        with col_h:
            st.plotly_chart(
                charts.lcosaf_heatmap(
                    _REGIONS, SAF_PATHWAYS,
                    custom_capex, custom_opex,
                    UTILIZATION_FACTOR, irr_sel, PROJECT_LIFE_YR,
                ),
                use_container_width=True,
            )
        with col_b:
            st.plotly_chart(
                charts.lcosaf_bar(
                    _REGIONS, SAF_PATHWAYS,
                    custom_capex, custom_opex,
                    UTILIZATION_FACTOR, irr_sel, PROJECT_LIFE_YR,
                ),
                use_container_width=True,
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

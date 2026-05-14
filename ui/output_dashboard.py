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

    # Add volume-weighted global price row per year. Regions on the corsia_offset
    # regime are excluded automatically because we filter on pricing_regime, so
    # partial-supply years still produce a meaningful weighted average over the
    # regions that actually received physical SAF.
    for s in history:
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
                "pathway": getattr(f, "pathway", ""),
                "volume_mt": f.volume_mt,
                "transport_cost_usd_per_mt": f.transport_cost_usd_per_mt,
            })
    return pd.DataFrame(rows)


def _history_to_capacity_df(history: list) -> pd.DataFrame:
    """
    Build the capacity DataFrame with dispatched/undispatched split.

    For each plant, the row's `dispatched_capacity_mt_yr` is the share of regional
    pathway-level dispatched volume (from trade flows) apportioned to this plant by
    nameplate share, converted back to MT/yr equivalent via UTILIZATION_FACTOR.
    `undispatched_capacity_mt_yr` is the residual that stayed idle in the clearing
    step (typically because LCOSAF > regional WTP and demand was satisfied by
    CORSIA offsets instead).
    """
    from config.settings import UTILIZATION_FACTOR

    rows = []
    for s in history:
        # Dispatched MT (effective) by (region, pathway), summed over flows.
        dispatched_by_rp: dict = {}
        for f in s.market.trade_flows:
            key = (f.origin_region, getattr(f, "pathway", ""))
            dispatched_by_rp[key] = dispatched_by_rp.get(key, 0.0) + f.volume_mt

        # Nameplate share per plant within its (region, pathway) cohort.
        nameplate_by_rp: dict = {}
        for plant in s.capacity.plants:
            key = (plant.region, plant.pathway)
            nameplate_by_rp[key] = nameplate_by_rp.get(key, 0.0) + plant.capacity_mt_yr

        for plant in s.capacity.plants:
            key = (plant.region, plant.pathway)
            cohort_nameplate = nameplate_by_rp.get(key, 0.0)
            dispatched_eff = dispatched_by_rp.get(key, 0.0)
            if cohort_nameplate > 0:
                share = plant.capacity_mt_yr / cohort_nameplate
                # Apportion dispatched volume (MT effective) to this plant, then
                # convert effective MT back to nameplate-equivalent MT/yr.
                disp_mt_yr = (dispatched_eff * share) / UTILIZATION_FACTOR
            else:
                disp_mt_yr = 0.0
            disp_mt_yr = min(disp_mt_yr, plant.capacity_mt_yr)
            undisp_mt_yr = max(0.0, plant.capacity_mt_yr - disp_mt_yr)
            rows.append({
                "year": s.year,
                "region": plant.region,
                "pathway": plant.pathway,
                "total_capacity_mt_yr": round(plant.capacity_mt_yr, 4),
                "dispatched_capacity_mt_yr": round(disp_mt_yr, 4),
                "undispatched_capacity_mt_yr": round(undisp_mt_yr, 4),
                "capacity_type": "Planned" if plant.is_deterministic else "Modelled",
            })
    return pd.DataFrame(rows)


def _history_to_summary_df(history: list) -> pd.DataFrame:
    rows = []
    for s in history:
        offset_mt = sum(s.market.offset_demand_mt_by_region.values())
        rows.append({
            "year": s.year,
            "total_demand_mt": s.demand.total_volume_mt(s.year),
            "total_produced_mt": s.market.total_saf_produced_mt,
            "corsia_offset_demand_mt": round(offset_mt, 6),
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
        "📊 Market Summary", "💰 Prices & WTP", "🏭 Capacity", "🚢 Trade Flows"
    ])

    # ════════════════════════════════════════════════════════════════════════
    # 📊  MARKET SUMMARY
    # ════════════════════════════════════════════════════════════════════════
    with tab_summary:
        st.subheader("Annual Market Summary")
        st.markdown(
            """
            ### Methodology
            The market summary consolidates the key aggregate outcomes from each model year into
            a single view. **Total demand** is the sum of CORSIA-driven and mandate-driven SAF
            requirements across all regions, as estimated by the bottom-up demand module.
            **Total produced** is the volume of SAF actually dispatched from committed and
            endogenously-built plants during the clearing step — it equals total demand in
            balanced years and is zero in supply-shortfall years. **Total traded** is the
            subset of produced SAF that crosses a regional boundary, reflecting the inter-
            regional allocation decisions made by the cheapest-CIF clearing algorithm.

            The `market_balanced` flag is `True` when inflow to every region meets or exceeds
            its demand within a tolerance of 0.1 kt (0.0001 MT). The `expansion_triggered`
            flag indicates whether the LP solver built any new endogenous plants in that year.
            Years where the market does not balance — typically early in the horizon before
            sufficient capacity has been built — produce no price or trade-flow data.

            **Note on CORSIA demand and carbon offsets:** Total CORSIA demand reported here
            represents the full CORSIA-mandated and blending-mandate obligation. In years where
            physical SAF supply cannot meet this obligation at a cost below the regional WTP,
            the shortfall is assumed to be covered by **CORSIA-eligible carbon offset credits**
            rather than physical SAF. This offset demand appears separately in the
            Supply-Demand Curve chart.
            """
        )
        st.dataframe(summary_df.style.format({
            "year": "{:.0f}",
            "total_demand_mt": "{:.3f}",
            "total_produced_mt": "{:.3f}",
            "corsia_offset_demand_mt": "{:.3f}",
            "total_traded_mt": "{:.3f}",
        }), use_container_width=True)
        _download_csv(summary_df, "market_summary.csv", "⬇ Download")

        st.plotly_chart(charts.market_balance_bar(summary_df), use_container_width=True)

    # ════════════════════════════════════════════════════════════════════════
    # 💰  PRICES & WTP
    # ════════════════════════════════════════════════════════════════════════
    with tab_prices:
        if prices_df.empty:
            st.warning("No price data available — some years may have had supply shortfalls.")
        else:
            # ── Global volume-weighted price ──────────────────────────────────
            st.subheader("Global Market Clearing Price")
            st.markdown(
                """
                ### Methodology
                The global SAF market price is reported as the **demand-volume-weighted average**
                of all regional clearing prices across every model year. Only regions actually
                served with physical SAF (`pricing_regime = wtp_priority_allocation`) contribute
                to the weighted average; regions that fell to CORSIA offsets are excluded. This
                gives a single representative market price that reflects the relative size of
                each regional market:

                > **Global Price = Σ (Clearing Priceᵣ × Demand Volumeᵣ) / Σ Demand Volumeᵣ**

                Only regions that are fully served (`pricing_regime = wtp_priority_allocation`)
                contribute to this average; unserved regions are excluded. The global price is
                therefore a demand-side signal: it rises as high-WTP regions (particularly the
                EU under ReFuelEU) grow as a share of total demand, and falls as supply scales
                up and competition pushes clearing prices towards the investment floor (Case 2
                LCOSAF).
                """
            )
            st.plotly_chart(charts.global_price_chart(prices_df), use_container_width=True)

            # ── WTP multi-year trend ──────────────────────────────────────────
            st.subheader("Willingness-to-Pay by Region")
            st.markdown(
                """
                ### Methodology
                Willingness-to-pay (WTP) is the maximum price each region is prepared to pay for
                SAF in a given year. It is computed as the maximum of three independent cases:

                - **Case 1 (Market floor):** `Jet Fuel Price + CORSIA Credit × 2.5 tCO₂/MT SAF`
                  Reflects the value of SAF as a drop-in fuel plus the avoided cost of purchasing
                  conventional CORSIA offsets. Rising carbon credit prices over time push this
                  value upward.
                - **Case 2 (Investment floor):** `min_pathway[ (CRF(IRR, 20yr) × CAPEX + OPEX) / Utilisation ]`
                  The minimum price at which a rational investor would build new capacity, using
                  the cheapest available pathway (typically Co-processing or HEFA). This sets the
                  long-run equilibrium price floor — no new capacity is built below this level.
                - **Case 3 (Policy ceiling):** `non_compliance_penalty_usd_per_mt`
                  The regulatory penalty for failing to meet a blending mandate. For the EU this
                  is $2,500/MT under ReFuelEU, making Case 3 the binding constraint for EU
                  buyers. For non-regulated regions, Case 3 is zero and Case 2 dominates.

                > **Final WTP = max(Case 1, Case 2, Case 3)**

                The multi-year line chart shows how each region's WTP evolves as jet fuel prices,
                carbon credit prices, and technology costs change across the 2025–2045 horizon.
                """
            )
            wtp_states = list(history)
            if wtp_states:
                _wtp_model = WTPModel()
                wtp_rows = []
                for s in wtp_states:
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

            # ── Supply-demand curve ───────────────────────────────────────────
            st.subheader("Supply-Demand Curve")
            st.markdown(
                """
                ### Methodology
                The supply-demand curve visualises the market clearing equilibrium for a single
                year by plotting supply and demand as stacked bar charts along a common cumulative
                volume axis.

                **Supply side** (solid bars, sorted left-to-right by ascending LCOSAF): each bar
                represents one individual plant's effective supply — its nameplate capacity
                multiplied by the utilisation factor (0.85). Each bar is labelled by
                **region and pathway** (e.g. EU — HEFA, US — Co-processing). Bars are
                ordered cheapest-first, reflecting merit-order dispatch. The bar height is the
                plant's full LCOSAF including capital recovery:

                > **LCOSAF = (CRF(IRR, 20yr) × CAPEX + OPEX) / Utilisation**

                Dispatched plants (coloured solid) are those whose cumulative volume falls
                within the total SAF produced in the clearing step. Undispatched plants (shown
                with cross-hatching, hidden by default via the *Show Unbuilt Cap* toggle) have
                LCOSAF too high to be economically dispatched.

                **Demand side** (hatched bars, sorted left-to-right by descending WTP): each bar
                represents one region's CORSIA demand (CORSIA mandate + national blending mandate) at its WTP.
                The highest-WTP region is served first. Clearing price = WTP of each served
                region (WTP-priority allocation, not a competitive auction).

                **CORSIA Offset Demand** (grey cross-hatched bar): the portion of total CORSIA
                demand that cannot be met by physical SAF at or below the regional WTP. Airlines
                in this segment are assumed to purchase CORSIA-eligible carbon offset credits
                instead of physical SAF.
                """
            )
            sd_years = sorted({s.year for s in history})
            if sd_years:
                sd_year = st.selectbox(
                    "Year for S-D curve", sd_years, index=0, key="sd_year_out"
                )
                sd_state = next((s for s in history if s.year == sd_year), None)
                if sd_state:
                    _wtp_model2 = WTPModel()
                    demand_by_region = sd_state.demand.volume_by_region(sd_year)
                    sd_data = _wtp_model2.build_sd_curve_data(
                        sd_year, sd_state.capacity, demand_by_region,
                        market_result=sd_state.market,
                    )
                    st.plotly_chart(
                        charts.supply_demand_curve(
                            sd_data["demand_steps"],
                            sd_data["supply_steps"],
                            sd_year,
                            offset_mt=sd_data["offset_mt"],
                            max_wtp=sd_data["max_wtp"],
                        ),
                        use_container_width=True,
                    )
            else:
                st.info("No model history loaded.")

            # ── Per-region price decomposition ────────────────────────────────
            with st.expander("Per-Region Price Decomposition"):
                st.markdown(
                    """
                    The stacked bar chart decomposes the clearing price for a selected region
                    into its constituent components: **supply cost** (LCOSAF of the dispatched
                    supply source), **transport premium** (CIF cost of shipping from the origin
                    region), **mandate premium** (additional cost borne by regulated buyers),
                    **carbon offset** (value of avoided CORSIA offset purchases), and **margin**
                    (producer surplus above break-even). In the current WTP-priority clearing
                    model, the clearing price equals the region's WTP, so the sum of components
                    equals WTP by construction.
                    """
                )
                region_prices_df = prices_df[prices_df["region"] != "Global (vol-wtd)"]
                if not region_prices_df.empty:
                    regions = sorted(region_prices_df["region"].unique())
                    sel_region = st.selectbox(
                        "Region for price decomposition", regions, key="price_region"
                    )
                    st.plotly_chart(
                        charts.price_decomposition_bar(region_prices_df, sel_region),
                        use_container_width=True,
                    )

            st.subheader("Raw Price Data")
            st.dataframe(
                prices_df.style.format({
                    "year": "{:.0f}",
                    "clearing_price_usd_per_mt": "{:.2f}",
                }),
                use_container_width=True,
            )
            _download_csv(prices_df, "prices.csv", "⬇ Download prices.csv")

    # ════════════════════════════════════════════════════════════════════════
    # 🏭  CAPACITY
    # ════════════════════════════════════════════════════════════════════════
    with tab_capacity:
        if capacity_df.empty:
            st.warning("No capacity data available.")
        else:
            st.subheader("SAF Production Capacity")
            st.markdown(
                """
                ### Methodology
                Capacity is tracked as **nameplate capacity** (MT/yr) — the rated annual output
                at 100% utilisation. Effective supply available for dispatch equals nameplate
                capacity multiplied by the utilisation factor (0.85), reflecting planned
                maintenance, feedstock variability, and operational downtime.

                Capacity is split into two types:

                - **Planned (Planned):** Plants with known or announced online dates from
                  `committed_capacity.csv`. These enter the model in their specified `online_year`
                  regardless of the LP expansion decision. They represent the deterministic
                  pipeline of facilities already under construction or with confirmed final
                  investment decisions.
                - **Modelled (Modelled):** Plants built endogenously by the least-cost capacity
                  expansion LP when committed supply is insufficient to meet projected demand.
                  The LP minimises the net present value of new capacity investment subject to
                  supply-demand balance, feedstock availability, and regional capacity
                  constraints. New plants come online with a one-year construction lag.

                Capacity accumulates year-over-year: once a plant is built — whether planned or
                modelled — it remains in the capacity state for the remainder of the horizon.
                The area charts show how the regional and pathway mix evolves over 2025–2045.

                **Dispatched vs idle capacity:** the filled stacked area shows the share of
                built capacity that was actually dispatched in the clearing step, while the
                **black dashed line** traces total built capacity. The gap between them is
                capacity that stayed idle — its LCOSAF exceeded the destination region's WTP,
                so the demand it could have served was satisfied by CORSIA-eligible carbon
                offsets instead. In the Planned-vs-Modelled bar chart the same split appears
                as a hatched "(idle)" segment stacked on top of each region's solid (dispatched)
                bar.
                """
            )

            st.plotly_chart(charts.capacity_stacked_split(capacity_df), use_container_width=True)

            col1, col2 = st.columns(2)
            with col1:
                st.plotly_chart(
                    charts.capacity_stacked_area(capacity_df), use_container_width=True
                )
            with col2:
                st.plotly_chart(
                    charts.capacity_by_pathway(capacity_df), use_container_width=True
                )

            st.subheader("Raw Capacity Data")
            st.dataframe(
                capacity_df.style.format({
                    "year": "{:.0f}",
                    "total_capacity_mt_yr": "{:.4f}",
                }),
                use_container_width=True,
            )
            _download_csv(capacity_df, "capacity.csv", "⬇ Download capacity.csv")

    # ════════════════════════════════════════════════════════════════════════
    # 🚢  TRADE FLOWS
    # ════════════════════════════════════════════════════════════════════════
    with tab_trade:
        if flows_df.empty:
            st.warning("No trade flow data available.")
        else:
            st.subheader("Inter-Regional SAF Trade Flows")
            st.markdown(
                """
                ### Methodology
                SAF trade flows are produced by a **two-phase pathway-aware dispatch**:

                - **Phase 1 — Domestic clearing.** Each region's own plants supply local
                  demand first, sorted by LCOSAF ascending. Only plants whose
                  **LCOSAF ≤ regional WTP** dispatch — uneconomic plants stay idle.
                - **Phase 2 — Imports.** Residual (unmet) demand is filled by plants in
                  other regions, again subject to **LCOSAF ≤ destination WTP**, with
                  inter-regional candidates sorted by cheapest CIF:

                > **CIF Cost (origin → destination) = LCOSAF_origin + Transport Cost_origin→destination**

                Demand regions are processed in descending order of WTP, so the highest-paying
                market gets first call on the inter-regional supply pool. Demand that no plant
                can clear within the WTP filter falls to **CORSIA-eligible carbon offsets**
                (visible in the Market Summary).

                Each trade flow now carries a **pathway** label (HEFA, Co-processing, etc.) in
                addition to origin and destination, so the pathway-level chart below shows which
                production technology in which origin region serves each importing market.
                """
            )

            years = sorted(flows_df["year"].unique())
            sel_year = st.selectbox("Year", years, index=len(years) - 1, key="trade_year")

            col1, col2 = st.columns(2)
            with col1:
                st.plotly_chart(
                    charts.trade_heatmap(flows_df, sel_year), use_container_width=True
                )
            with col2:
                st.plotly_chart(
                    charts.trade_sankey(flows_df, sel_year), use_container_width=True
                )

            # ── Pathway-level trade flows ────────────────────────────────────────
            st.subheader("Pathway-Level Trade Flows")
            st.markdown(
                """
                The Sankey below splits each origin region by its **production pathway**, so the
                lines reveal exactly which technology (HEFA, FT, Co-processing, etc.) from which
                origin clears each destination's demand. The stacked bar gives the same data as
                a destination-by-destination pathway mix.
                """
            )
            col_p1, col_p2 = st.columns(2)
            with col_p1:
                st.plotly_chart(
                    charts.trade_pathway_sankey(flows_df, sel_year),
                    use_container_width=True,
                )
            with col_p2:
                st.plotly_chart(
                    charts.trade_pathway_stacked(flows_df, sel_year),
                    use_container_width=True,
                )

            st.subheader("Raw Trade Flow Data")
            st.dataframe(
                flows_df[flows_df["year"] == sel_year].style.format({"year": "{:.0f}"}),
                use_container_width=True,
            )
            _download_csv(flows_df, "trade_flows.csv", "⬇ Download trade_flows.csv")

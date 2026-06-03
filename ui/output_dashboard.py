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


def _global_price_narrative(prices_df: pd.DataFrame, history: list) -> str:
    """
    Build a data-driven explanation of the global SAF price chart profile.

    Derives key facts — first year with a clearing price, which regions are
    fully served when, where transitions occur and whether prices step down or
    up — from the actual model results so the text stays accurate under any
    input scenario.
    """
    global_df = (
        prices_df[prices_df["region"] == "Global (vol-wtd)"]
        .sort_values("year")
        .reset_index(drop=True)
    )
    served_df = (
        prices_df[prices_df["pricing_regime"] == "wtp_priority_allocation"]
        .sort_values(["year", "clearing_price_usd_per_mt"], ascending=[True, False])
    )
    all_years = sorted({s.year for s in history})

    if global_df.empty:
        return (
            "No region achieved complete SAF coverage in any modelled year. "
            "All demand was served via CORSIA carbon-offset credits throughout the "
            "simulation, so no physical clearing price appears in the chart. "
            "Consider increasing supply capacity or extending the horizon to observe "
            "the transition to physical SAF markets."
        )

    first_price_year = int(global_df["year"].iloc[0])
    no_price_years = [y for y in all_years if y < first_price_year]

    # Primary served region per year: the one with the highest clearing price
    # (allocation is WTP-priority so the highest-WTP region is served first)
    primary: dict = {}
    for _, row in served_df.iterrows():
        yr = int(row["year"])
        if yr not in primary:
            primary[yr] = (row["region"], float(row["clearing_price_usd_per_mt"]))

    # Collapse into contiguous segments sharing the same primary region
    segments = []
    prev_region = None
    seg_start = seg_prices = None
    for yr in sorted(primary):
        region, price = primary[yr]
        if region != prev_region:
            if prev_region is not None:
                segments.append((seg_start, yr - 1, prev_region, seg_prices))
            prev_region, seg_start, seg_prices = region, yr, [price]
        else:
            seg_prices.append(price)
    if prev_region is not None:
        segments.append((seg_start, max(primary), prev_region, seg_prices))

    parts = []

    # ── Pre-price period ──────────────────────────────────────────────────────
    if no_price_years:
        span = (f"{no_price_years[0]}" if len(no_price_years) == 1
                else f"{no_price_years[0]}–{no_price_years[-1]}")
        parts.append(
            f"**{span} — no physical clearing price.**  "
            "Throughout this period total SAF supply cannot fully satisfy any single "
            "region's demand; all regions remain partially covered with the shortfall "
            "met by CORSIA carbon-offset credits, so no clearing price registers."
        )

    # ── Per-segment narrative ─────────────────────────────────────────────────
    for i, (yr_s, yr_e, region, prices) in enumerate(segments):
        lo, hi = round(min(prices)), round(max(prices))
        price_range = f"~${lo:,}/MT" if lo == hi else f"~${lo:,}–${hi:,}/MT"
        yr_range = str(yr_s) if yr_s == yr_e else f"{yr_s}–{yr_e}"

        if i == 0:
            parts.append(
                f"**{yr_range} — {region} is the first fully-served region "
                f"({price_range}).**  "
                f"With supply allocated to the highest-WTP buyers first, {region} "
                f"reaches 100 % physical coverage before any other region. Its "
                f"clearing price equals the {region} regional WTP"
                + (f" and rises from ${lo:,} to ${hi:,}/MT as WTP grows year-on-year."
                   if lo != hi else ".")
            )
        else:
            prev_region_name = segments[i - 1][2]
            prev_hi = round(max(segments[i - 1][3]))
            direction = "lower" if lo < prev_hi else "higher"
            delta = abs(lo - prev_hi)
            parts.append(
                f"**{yr_range} — composition shift: {prev_region_name} → {region} "
                f"({price_range}).**  "
                f"{prev_region_name} demand growth outpaces new capacity additions, "
                f"pushing it back to partial coverage. {region} simultaneously "
                f"crosses the fully-served threshold at a {direction} regional WTP "
                f"(~${prev_hi:,} → ~${lo:,}/MT, a ${delta:,}/MT step). "
                "This is a composition change — not a movement in SAF production cost."
                + (f" The price then trends to ${hi:,}/MT by {yr_e} "
                   f"as {region}'s WTP evolves." if lo != hi else "")
            )

    parts.append(
        "*Note: in any year where only one region is fully served the global price "
        "equals that region's WTP exactly. The **Compliance Cost Curve** chart below "
        "provides a more representative picture of market-wide costs by blending "
        "physical SAF and CORSIA offset costs across all regions proportionally.*"
    )

    return "\n\n".join(parts)


def _history_to_compliance_cost_df(history: list) -> pd.DataFrame:
    """
    Per-year volume-weighted blended SAF compliance cost.

    For each region, physical SAF volume is priced at regional WTP and the
    remaining shortfall is priced at the CORSIA carbon-offset cost.  As
    physical SAF progressively replaces cheap CORSIA offsets the blended
    average rises from near the offset floor toward WTP, tracing an S-curve.
    """
    rows = []
    for s in history:
        demand_vols = s.demand.volume_by_region(s.year)
        offset_price = s.market.corsia_offset_price_usd_per_mt

        # Physical SAF actually delivered per destination region
        inflow: dict = {}
        for f in s.market.trade_flows:
            inflow[f.destination_region] = inflow.get(f.destination_region, 0.0) + f.volume_mt

        # WTP per region:
        # - fully served (wtp_priority_allocation) → clearing_price == WTP
        # - partially served / unserved (corsia_offset) → shadow_price == WTP
        wtp_by_region: dict = {}
        for p in s.market.prices:
            if p.pricing_regime == "wtp_priority_allocation":
                wtp_by_region[p.region] = p.clearing_price_usd_per_mt
            else:
                wtp_by_region[p.region] = p.shadow_price_usd_per_mt

        total_vol = weighted = 0.0
        for region, demand_vol in demand_vols.items():
            if demand_vol <= 0:
                continue
            saf_vol = min(inflow.get(region, 0.0), demand_vol)
            offset_vol = max(0.0, demand_vol - saf_vol)
            wtp = wtp_by_region.get(region, offset_price)
            weighted += saf_vol * wtp + offset_vol * offset_price
            total_vol += demand_vol

        if total_vol > 0:
            rows.append({
                "year": s.year,
                "compliance_cost_usd_per_mt": round(weighted / total_vol, 2),
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

            st.info("**Reading this chart**\n\n" + _global_price_narrative(prices_df, history))

            # ── SAF compliance cost curve (S-curve) ──────────────────────────
            st.markdown(
                """
                ### SAF Compliance Cost Curve
                The chart below shows the **volume-weighted blended compliance cost** across all
                regions. Regions that receive physical SAF are priced at their regional WTP;
                regions that cannot access physical SAF fall back to CORSIA carbon-offset credits
                (priced at `CORSIA credit × 3.1 tCO₂/MT SAF`). As modelled capacity grows and
                physical SAF progressively displaces cheap CORSIA offsets, the blended cost rises
                from the offset floor through a rapid transition to near-WTP — producing the
                expected S-shaped trajectory with an inflection where the transition is fastest and
                a plateau as the market approaches full physical-SAF coverage.
                """
            )
            compliance_df = _history_to_compliance_cost_df(history)
            st.plotly_chart(charts.saf_compliance_cost_chart(compliance_df), use_container_width=True)

            # ── WTP multi-year trend ──────────────────────────────────────────
            st.subheader("Willingness-to-Pay by Region")
            st.markdown(
                """
                ### Methodology
                Willingness-to-pay (WTP) is the maximum price each region is prepared to pay for
                SAF in a given year. It is computed as the maximum of three independent cases:

                - **Case 1 (Market floor):** `Jet Fuel Price + CORSIA Credit × 3.1 tCO₂/MT SAF`
                  Reflects the value of SAF as a drop-in fuel plus the avoided cost of purchasing
                  conventional CORSIA offsets. Rising carbon credit prices over time push this
                  value upward.
                - **Case 2 (Investment floor):** `min_pathway[ (CRF(IRR, 20yr) × CAPEX + OPEX) / Utilisation ]`
                  The minimum price at which a rational investor would build new capacity, using
                  the cheapest available pathway (typically Co-processing or HEFA). This sets the
                  long-run equilibrium price floor — no new capacity is built below this level.
                - **Case 3 (Total Market WTP ceiling):** the full market-clearing price
                  airlines in each region will actually pay. Combines jet-fuel baseline,
                  CORSIA / ETS / LCFS compliance value, and a regional premium that
                  reflects local regulatory + voluntary drivers:
                    * **EU** baseline + ETS + ReFuelEU non-compliance penalty
                      ($2,600 → $3,600+ across 2025–2045).
                    * **US** baseline + CORSIA + LCFS + corporate Scope-3 premium
                      ($1,500 → $2,200).
                    * **APAC** baseline + CORSIA + moderate mandate premium
                      ($1,300 → $1,800; Singapore SAF levy from 2026).
                    * **MENA** baseline + CORSIA + small flagship-carrier premium
                      ($1,000 → $1,300).
                    * **LATAM / ROW** baseline + CORSIA, near-zero premium
                      ($800 → $1,000) — physical SAF rarely clears domestically;
                      regional feedstocks are exported to EU/US instead.

                  Loaded from `wtp_params.csv` column `case3_penalty_usd_per_mt`. The
                  "penalty" column name is legacy — the value now represents the **total
                  market WTP ceiling**, not just a non-compliance fine.

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

                **CORSIA Offset Demand** (annotation box): when total CORSIA demand exceeds the
                dispatched physical-SAF supply, the unserved volume is already visible as the
                rightmost demand bars that extend past where the supply bars end. A summary text
                box is overlaid in that gap, stating the unserved volume and the CORSIA
                carbon-offset unit price (`corsia_credit_usd_per_tco2 × 3.1 tCO₂/MT SAF`) — the
                price airlines actually pay when they fall to CORSIA-eligible carbon offsets
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
                            offset_price_usd_per_mt=sd_data.get("offset_price_usd_per_mt", 0.0),
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
                SAF trade flows are produced by a **share-aware two-pass dispatch**.
                Each region's effective supply is split into a **domestic-priority pool**
                (size = `domestic_share × supply`) and an **export pool** (the remaining
                `1 − domestic_share`). Both shares are editable per region in the
                **Capacity → Domestic vs Export Share** input section.

                - **Phase 1 — Domestic clearing.** Every region's domestic pool is
                  dispatched to its own demand first, sorted by LCOSAF ascending and
                  filtered by **LCOSAF ≤ regional WTP**. Higher-WTP regions are tie-broken
                  first, but no region's domestic supply leaves the country until every
                  region has had a chance to clear locally.
                - **Phase 2 — Cheapest-CIF allocation.** Residual demand is filled from
                  each plant's export pool plus any unused domestic remainder. All
                  (plant → destination) pairs — **including back to the plant's own
                  region** — are evaluated and sorted globally by cheapest CIF:

                > **CIF Cost (origin → destination) = LCOSAF_origin + Transport Cost_origin→destination**

                Because own-region transport is zero, a plant's first call in Phase 2 is
                always its **own market** if that market still has unmet demand. SAF
                ships abroad only after its home market is saturated, and longer routes
                only after closer markets are filled. Demand left unserved at every CIF
                tier (because no plant has LCOSAF ≤ that region's WTP, or all near-by
                plants are exhausted) falls to **CORSIA-eligible carbon offsets** at
                `corsia_credit_usd_per_tco2 × 3.1 tCO₂/MT SAF`.

                Each trade flow carries a **pathway** label (HEFA, Co-processing, etc.) in
                addition to origin and destination, so the pathway-level chart below shows
                which production technology in which origin region serves each importing
                market.
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

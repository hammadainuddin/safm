"""
Results page — tables and charts from a completed model run stored in
st.session_state["history"].
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
import streamlit as st

from ui import components
from ui.components import plotly_chart

from modules.wtp_model import WTPModel
from ui import charts


def _history_to_prices_df(history: list) -> pd.DataFrame:
    rows = []
    for s in history:
        # CORSIA offset price for this year (credit price × lifecycle CI factor).
        # Used as the effective cost for regions not served by physical SAF.
        offset_price = s.market.corsia_offset_price_usd_per_mt

        for p in s.market.prices:
            if p.pricing_regime == "corsia_offset":
                # Completely unserved — no physical SAF reached this region.
                # Show the CORSIA credit cost as the effective cost so the
                # decomposition chart has a visible bar (Carbon Offset component).
                rows.append({
                    "year": p.year,
                    "region": p.region,
                    "clearing_price_usd_per_mt": round(offset_price, 2),
                    "pricing_regime": p.pricing_regime,
                    "shadow_price_usd_per_mt": p.shadow_price_usd_per_mt,
                    "supply_cost_usd_per_mt": 0.0,
                    "transport_premium_usd_per_mt": 0.0,
                    "mandate_premium_usd_per_mt": 0.0,
                    "carbon_offset_usd_per_mt": round(offset_price, 2),
                    "margin_usd_per_mt": 0.0,
                })
            else:
                # partial_supply and wtp_priority_allocation both carry real
                # supply cost decomposition data — pass through directly.
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

    # Volume-weighted global price per year.
    # Both fully-served (wtp_priority_allocation) and partially-served
    # (partial_supply) regions contribute — both received physical SAF with a
    # real price. Completely-unserved (corsia_offset) regions are excluded.
    # min/max across physically-served regions render the shaded range band.
    for s in history:
        demand_vols = s.demand.volume_by_region(s.year)
        total_vol = 0.0
        weighted_price = 0.0
        served_prices = []
        for p in s.market.prices:
            if p.pricing_regime in ("wtp_priority_allocation", "partial_supply"):
                vol = demand_vols.get(p.region, 0.0)
                weighted_price += p.clearing_price_usd_per_mt * vol
                total_vol += vol
                served_prices.append(p.clearing_price_usd_per_mt)
        if total_vol > 0:
            rows.append({
                "year": s.year,
                "region": "Global (vol-wtd)",
                "clearing_price_usd_per_mt": round(weighted_price / total_vol, 2),
                "min_price_usd_per_mt":      round(min(served_prices), 2),
                "max_price_usd_per_mt":      round(max(served_prices), 2),
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
            f"**{span} — no physical clearing price.**\n\n"
            "Throughout this period total SAF supply cannot fully satisfy any single "
            "region's demand. All regions remain partially covered, with the shortfall "
            "met by CORSIA carbon-offset credits, so no clearing price registers on "
            "the chart."
        )

    # ── Per-segment narrative ─────────────────────────────────────────────────
    for i, (yr_s, yr_e, region, prices) in enumerate(segments):
        lo, hi = round(min(prices)), round(max(prices))
        price_range = f"~${lo:,}/MT" if lo == hi else f"~${lo:,}–${hi:,}/MT"
        yr_range = str(yr_s) if yr_s == yr_e else f"{yr_s}–{yr_e}"

        if i == 0:
            parts.append(
                f"**{yr_range} — {region} is the first fully-served region "
                f"({price_range}).**\n\n"
                f"With supply allocated to the highest-WTP buyers first, {region} "
                f"reaches 100% physical coverage before any other region. Its "
                f"clearing price equals the {region} regional WTP"
                + (f" and rises from {lo:,} to {hi:,} USD/MT as WTP grows year-on-year."
                   if lo != hi else ".")
            )
        else:
            prev_region_name = segments[i - 1][2]
            prev_hi = round(max(segments[i - 1][3]))
            direction = "lower" if lo < prev_hi else "higher"
            delta = abs(lo - prev_hi)
            parts.append(
                f"**{yr_range} — composition shift: {prev_region_name} to "
                f"{region} ({price_range}).**\n\n"
                f"{prev_region_name} demand growth outpaces new capacity additions, "
                f"pushing it back to partial coverage. {region} simultaneously "
                f"crosses the fully-served threshold at a {direction} regional WTP "
                f"({prev_hi:,} to {lo:,} USD/MT, a {delta:,} USD/MT step). "
                "This is a composition change, not a movement in SAF production cost."
                + (f" The price then trends to {hi:,} USD/MT by {yr_e} "
                   f"as {region}'s WTP evolves." if lo != hi else "")
            )

    parts.append(
        "Note: in any year where only one region is fully served, the global average "
        "equals that region's WTP exactly. The shaded band shows the spread between "
        "the lowest- and highest-priced served regions. The Compliance Cost Curve "
        "chart below gives a fuller picture by blending physical SAF prices and "
        "CORSIA offset costs across all regions proportionally."
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
    st.download_button(label=label, data=csv, file_name=filename, mime="text/csv",
                       icon=":material/download:")


def _kpi_strip(summary_df: pd.DataFrame, prices_df: pd.DataFrame,
               capacity_df: pd.DataFrame) -> None:
    """Final-year headline metrics with delta vs the first model year."""
    first = summary_df.iloc[0]
    last = summary_df.iloc[-1]
    yr = int(last["year"])

    def _delta(v_last: float, v_first: float, unit: str) -> Optional[str]:
        d = v_last - v_first
        return f"{d:+,.2f} {unit} vs {int(first['year'])}" if abs(d) > 1e-9 else None

    demand_val = float(last["total_demand_mt"])
    traded_val = float(last["total_traded_mt"])

    yr_prices = prices_df[prices_df["year"] == yr]["clearing_price_usd_per_mt"]
    avg_price = float(yr_prices[yr_prices > 0].mean()) if not yr_prices.empty else 0.0

    cap_col = ("total_capacity_mt_yr" if "total_capacity_mt_yr" in capacity_df.columns
               else "dispatched_capacity_mt_yr")
    yr_cap = capacity_df[capacity_df["year"] == yr][cap_col].sum() if not capacity_df.empty else 0.0

    components.metric_row([
        (f"Total demand · {yr}", f"{demand_val:,.2f} MT",
         _delta(demand_val, float(first["total_demand_mt"]), "MT")),
        (f"Avg clearing price · {yr}", f"${avg_price:,.0f}/MT", None),
        (f"Capacity online · {yr}", f"{yr_cap:,.2f} MT/yr", None),
        (f"Traded volume · {yr}", f"{traded_val:,.2f} MT",
         _delta(traded_val, float(first["total_traded_mt"]), "MT")),
    ])


def _render_compare_runs() -> None:
    """Compare-runs expander: overlay metrics across persisted DuckDB runs."""
    from data import results_store

    runs = results_store.list_runs()
    with st.expander("Compare scenario runs", icon=":material/compare_arrows:",
                     expanded=False):
        if runs.empty:
            st.caption(
                "No stored runs yet. Runs are saved automatically each time the "
                "model executes (Run Model page or a Scenarios batch run)."
            )
            return

        # Build a human label per run; disambiguate duplicate scenario names.
        labels, seen = {}, {}
        for _, r in runs.iterrows():
            base = str(r["scenario"])
            seen[base] = seen.get(base, 0) + 1
            ts = str(r["ran_at"])[5:16].replace("T", " ")
            labels[r["run_id"]] = f"{base} · {ts}" if seen[base] == 1 or True else base

        st.dataframe(
            runs[["scenario", "ran_at", "start_year", "end_year", "demand_mode",
                  "include_domestic", "demand_scale_factor",
                  "efficiency_improvement_rate"]],
            use_container_width=True, hide_index=True,
        )

        chosen = st.multiselect(
            "Runs to compare",
            options=list(labels.keys()),
            format_func=lambda rid: labels[rid],
            key="compare_run_select",
        )
        if len(chosen) < 1:
            st.caption("Select one or more runs to overlay their results.")
            return

        lbl = {rid: labels[rid] for rid in chosen}

        ms = results_store.load_table("market_summary", chosen)
        cap = results_store.load_table("capacity", chosen)
        pr = results_store.load_table("prices", chosen)
        dem = results_store.load_table("demand", chosen)

        # Volume-weighted global price per run/year (served regimes only).
        price_g = pd.DataFrame()
        if not pr.empty and not dem.empty:
            served = pr[pr["pricing_regime"].isin(
                ["wtp_priority_allocation", "partial_supply"])]
            m = served.merge(dem, on=["run_id", "year", "region"], how="inner")
            if not m.empty:
                m["pv"] = m["clearing_price_usd_per_mt"] * m["demand_mt"]
                g = m.groupby(["run_id", "year"]).agg(
                    pv=("pv", "sum"), d=("demand_mt", "sum")).reset_index()
                g["value"] = g["pv"] / g["d"]
                price_g = g

        def _tag(df):
            df = df.copy()
            df["run_label"] = df["run_id"].map(lbl)
            return df

        c1, c2 = st.columns(2)
        with c1:
            if not price_g.empty:
                plotly_chart(charts.compare_runs_line(
                    _tag(price_g), "value",
                    "Volume-Weighted Global Price", "USD/MT"))
            if not ms.empty:
                plotly_chart(charts.compare_runs_line(
                    _tag(ms), "total_demand_mt", "Total SAF Demand", "MT"))
        with c2:
            if not cap.empty:
                capg = cap.groupby(["run_id", "year"])[
                    "total_capacity_mt_yr"].sum().reset_index()
                plotly_chart(charts.compare_runs_line(
                    _tag(capg), "total_capacity_mt_yr",
                    "Total Capacity Online", "MT/yr"))
            if not ms.empty:
                plotly_chart(charts.compare_runs_line(
                    _tag(ms), "total_traded_mt", "Total Traded Volume", "MT"))


def render(history: Optional[list] = None) -> None:
    if history is None:
        history = st.session_state.get("history")

    components.page_header(
        "Results",
        "Prices, capacity build-out, and trade flows from the selected model run.",
    )

    # When a batch produced several scenarios, let the user choose which one the
    # KPI strip and detail tabs below should show (defaults to the last that ran).
    histories = st.session_state.get("histories") or {}
    if len(histories) > 1:
        names = list(histories.keys())
        if st.session_state.get("results_scenario") not in names:
            st.session_state["results_scenario"] = names[-1]
        sel = st.selectbox(
            "Scenario", names, key="results_scenario",
            help="Choose which scenario from the last batch run to display below. "
                 "Use ‘Compare scenario runs’ to overlay multiple runs.",
        )
        history = histories.get(sel, history)

    # Cross-run comparison reads the DuckDB warehouse and works even with no
    # in-session run (e.g. after a restart or a batch run on the Scenarios page).
    _render_compare_runs()

    if not history:
        components.empty_state(
            "No run results yet. Start a model run to see prices, capacity, "
            "and trade flows here.",
            cta_page_key="run",
        )
        return

    prices_df   = _history_to_prices_df(history)
    flows_df    = _history_to_flows_df(history)
    capacity_df = _history_to_capacity_df(history)
    summary_df  = _history_to_summary_df(history)

    if not summary_df.empty:
        _kpi_strip(summary_df, prices_df, capacity_df)

    tab_summary, tab_prices, tab_capacity, tab_trade = st.tabs([
        "Market Summary", "Prices & WTP", "Capacity", "Trade Flows"
    ])

    # ════════════════════════════════════════════════════════════════════════
    # MARKET SUMMARY
    # ════════════════════════════════════════════════════════════════════════
    with tab_summary:
        st.subheader("Annual Market Summary")
        components.methodology(
            """
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
        _download_csv(summary_df, "market_summary.csv", "Download CSV")

        plotly_chart(charts.market_balance_bar(summary_df), use_container_width=True)

    # ════════════════════════════════════════════════════════════════════════
    # PRICES & WTP
    # ════════════════════════════════════════════════════════════════════════
    with tab_prices:
        if prices_df.empty:
            st.warning("No price data available — some years may have had supply shortfalls.")
        else:
            # ── Global volume-weighted price ──────────────────────────────────
            st.subheader("Global Market Clearing Price")
            components.methodology(
                """
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
            plotly_chart(charts.global_price_chart(prices_df), use_container_width=True)

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
            plotly_chart(charts.saf_compliance_cost_chart(compliance_df), use_container_width=True)

            # ── WTP multi-year trend ──────────────────────────────────────────
            st.subheader("Willingness-to-Pay by Region")
            components.methodology(
                """
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
                      ($2,600 → $3,600+ across 2025–2050).
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
                carbon credit prices, and technology costs change across the 2025–2050 horizon.
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
                    plotly_chart(charts.wtp_trend_chart(wtp_trend_df), use_container_width=True)

            # ── Supply-demand curve ───────────────────────────────────────────
            st.subheader("Supply-Demand Curve")
            components.methodology(
                """
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
                    plotly_chart(
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
            with st.expander("Price Decomposition", expanded=True):
                st.markdown(
                    """
                    Each bar shows the effective cost of SAF for a region in a given year.
                    Three regimes are possible:

                    **Fully served** (`wtp_priority_allocation`) — demand is completely met by
                    physical SAF. The bar decomposes into Supply Cost (LCOSAF of the dispatched
                    pathway), Transport (CIF shipping premium), Mandate Premium, Carbon Offset
                    value, and Margin (producer surplus above break-even). Clearing price = WTP.

                    **Partially served** (`partial_supply`) — some physical SAF reached the
                    region but did not fully cover demand; the shortfall fell to CORSIA offsets.
                    The bar decomposes into Supply Cost, Transport, and Margin at the region's
                    WTP — the same price basis as a fully served region.

                    **Unserved** (`corsia_offset`) — no physical SAF reached this region; the
                    entire demand was covered by CORSIA carbon credits. The bar shows only the
                    Carbon Offset cost (credit price × lifecycle CI factor).
                    """
                )
                region_prices_df = prices_df[prices_df["region"] != "Global (vol-wtd)"]
                if not region_prices_df.empty:
                    decomp_view = st.radio(
                        "View",
                        ["All regions — all years", "Single region — all years", "All regions — single year"],
                        horizontal=True,
                        key="decomp_view",
                    )

                    if decomp_view == "All regions — all years":
                        plotly_chart(
                            charts.price_decomposition_facet(region_prices_df),
                            use_container_width=True,
                        )

                    elif decomp_view == "Single region — all years":
                        regions = sorted(region_prices_df["region"].unique())
                        sel_region = st.selectbox(
                            "Region", regions, key="decomp_region"
                        )
                        plotly_chart(
                            charts.price_decomposition_bar(region_prices_df, sel_region),
                            use_container_width=True,
                        )

                    else:  # All regions — single year
                        years = sorted(region_prices_df["year"].unique())
                        sel_year = st.select_slider(
                            "Year", options=years, key="decomp_year"
                        )
                        plotly_chart(
                            charts.price_decomposition_by_year(region_prices_df, sel_year),
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
            _download_csv(prices_df, "prices.csv", "Download prices.csv")

    # ════════════════════════════════════════════════════════════════════════
    # CAPACITY
    # ════════════════════════════════════════════════════════════════════════
    with tab_capacity:
        if capacity_df.empty:
            st.warning("No capacity data available.")
        else:
            st.subheader("SAF Production Capacity")
            components.methodology(
                """
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
                The area charts show how the regional and pathway mix evolves over 2025–2050.

                **Dispatched vs idle capacity:** the bar chart shows only dispatched capacity
                by default. Use the **Show idle capacity** toggle below to split the view into
                two columns — dispatched on the left and idle on the right. Idle capacity is
                capacity that was built but stayed unused because its LCOSAF exceeded the
                destination region's WTP; that residual demand was satisfied by CORSIA-eligible
                carbon offsets instead.
                """
            )

            show_idle = st.toggle("Show idle capacity", value=False)

            if show_idle:
                col_disp, col_idle = st.columns(2)
                with col_disp:
                    plotly_chart(
                        charts.capacity_stacked_split(capacity_df), use_container_width=True
                    )
                with col_idle:
                    plotly_chart(
                        charts.idle_capacity_chart(capacity_df), use_container_width=True
                    )
            else:
                plotly_chart(
                    charts.capacity_stacked_split(capacity_df), use_container_width=True
                )

            col1, col2 = st.columns(2)
            with col1:
                plotly_chart(
                    charts.capacity_stacked_area(capacity_df), use_container_width=True
                )
            with col2:
                plotly_chart(
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
            _download_csv(capacity_df, "capacity.csv", "Download capacity.csv")

    # ════════════════════════════════════════════════════════════════════════
    # TRADE FLOWS
    # ════════════════════════════════════════════════════════════════════════
    with tab_trade:
        if flows_df.empty:
            st.warning("No trade flow data available.")
        else:
            st.subheader("Inter-Regional SAF Trade Flows")
            components.methodology(
                """
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
                plotly_chart(
                    charts.trade_heatmap(flows_df, sel_year), use_container_width=True
                )
            with col2:
                plotly_chart(
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
                plotly_chart(
                    charts.trade_pathway_sankey(flows_df, sel_year),
                    use_container_width=True,
                )
            with col_p2:
                plotly_chart(
                    charts.trade_pathway_stacked(flows_df, sel_year),
                    use_container_width=True,
                )

            st.subheader("Raw Trade Flow Data")
            st.dataframe(
                flows_df[flows_df["year"] == sel_year].style.format({"year": "{:.0f}"}),
                use_container_width=True,
            )
            _download_csv(flows_df, "trade_flows.csv", "Download trade_flows.csv")

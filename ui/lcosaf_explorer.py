"""
LCOSAF Explorer page — standalone interactive tool for exploring levelised
SAF cost assumptions. Values entered here are for scenario analysis only and
do NOT affect model runs.
"""

from __future__ import annotations

import streamlit as st

from ui import charts, components
from ui.components import plotly_chart


def render() -> None:
    components.page_header(
        "LCOSAF Explorer",
        "Standalone levelised-cost calculator for scenario analysis — values "
        "entered here do not affect model runs.",
    )

    st.info(
        "To change the cost assumptions used by the model, edit the "
        "**Costs** table on the Inputs page.",
        icon=":material/info:",
    )

    components.methodology(
        """
        The Levelised Cost of SAF (LCOSAF) is the minimum long-run price at which a
        producer can recover all capital and operating costs at a given required rate of
        return:

        > **LCOSAF (USD/MT SAF) = (CRF(IRR, life) × CAPEX + OPEX_eq) / Utilisation**
        >
        > where **OPEX_eq (USD/MT capacity/yr) = (Proc. OPEX + Feedstock $/t × Intensity) × Utilisation**

        Use the inputs below to explore how CAPEX, Processing OPEX, and Feedstock cost
        affect the levelised cost across regions and pathways.

        - **CAPEX** — capital cost in USD per MT/yr of nameplate capacity
        - **Processing OPEX** — non-feedstock operating cost in USD per **MT SAF** produced
        - **Feedstock $/t feed** — delivered feedstock cost per **MT of raw feedstock**
        - **Yield** — MT SAF per MT of raw feedstock (physical property; read-only)
        """
    )

    from config.settings import (
        FEED_INTENSITY, REGIONAL_CAPEX, REGIONAL_OPEX,
        SAF_PATHWAYS, UTILIZATION_FACTOR, PROJECT_LIFE_YR,
        REGIONS,
    )

    _PRIMARY_FEEDSTOCK = {
        "HEFA":          "UCO",
        "ATJ":           "agricultural_residue",
        "FT-MSW":        "MSW",
        "PtL":           "CO2_green_H2",
        "Co-processing": "UCO",
    }

    def _default_yield(pathway: str) -> float:
        feed = _PRIMARY_FEEDSTOCK.get(pathway)
        intensity = FEED_INTENSITY.get(pathway, {}).get(feed or "", 0.0)
        return round(1.0 / intensity, 3) if intensity > 0 else 1.0

    # Initialise session grid from settings defaults (75/25 feedstock/processing split).
    if "lcosaf_explorer_grid" not in st.session_state:
        grid: dict = {}
        for r in REGIONS:
            grid[r] = {}
            for p in SAF_PATHWAYS:
                opex_cap = REGIONAL_OPEX.get(r, {}).get(p, 600)
                opex_saf = opex_cap / UTILIZATION_FACTOR
                yld = _default_yield(p)
                feed_per_saf = opex_saf * 0.75
                grid[r][p] = {
                    "capex":           float(REGIONAL_CAPEX.get(r, {}).get(p, 2000)),
                    "proc_opex":       round(opex_saf * 0.25, 0),
                    "feedstock_per_t": round(feed_per_saf * yld, 0),
                    "saf_yield":       yld,
                }
        st.session_state["lcosaf_explorer_grid"] = grid

    grid = st.session_state["lcosaf_explorer_grid"]

    col_reset, _ = st.columns([1, 4])
    with col_reset:
        if st.button("Reset to defaults", key="lcosaf_exp_reset",
                     icon=":material/restart_alt:"):
            st.session_state.pop("lcosaf_explorer_grid", None)
            st.rerun()

    region_tabs = st.tabs(REGIONS)
    for rtab, region in zip(region_tabs, REGIONS):
        with rtab:
            hdr = st.columns([1.6, 1.3, 1.4, 1.5, 1.3])
            hdr[0].markdown("**Pathway**")
            hdr[1].markdown("**CAPEX** $/MT cap")
            hdr[2].markdown("**Proc. OPEX** $/MT SAF")
            hdr[3].markdown("**Feedstock** $/MT feed")
            hdr[4].markdown("**Yield** *(read-only)*")
            for pathway in SAF_PATHWAYS:
                kp = f"exp_{region}_{pathway}"
                row = st.columns([1.6, 1.3, 1.4, 1.5, 1.3])
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
                # Yield is read-only — sourced from FEED_INTENSITY (physical mass balance).
                row[4].markdown(f"`{grid[region][pathway]['saf_yield']:.3f}`")

    # Build effective OPEX dicts for chart functions.
    def _opex_eq(cell: dict) -> float:
        yld = cell["saf_yield"] if cell["saf_yield"] > 1e-6 else 1e-6
        opex_per_saf = cell["proc_opex"] + cell["feedstock_per_t"] / yld
        return opex_per_saf * UTILIZATION_FACTOR

    custom_capex = {r: {p: grid[r][p]["capex"] for p in SAF_PATHWAYS} for r in REGIONS}
    custom_opex  = {r: {p: _opex_eq(grid[r][p]) for p in SAF_PATHWAYS} for r in REGIONS}

    st.markdown("---")
    irr_sel = st.slider("Target IRR (%)", 8, 20, 12, key="lcosaf_exp_irr") / 100.0
    col_h, col_b = st.columns(2)
    with col_h:
        plotly_chart(
            charts.lcosaf_heatmap(
                REGIONS, SAF_PATHWAYS,
                custom_capex, custom_opex,
                UTILIZATION_FACTOR, irr_sel, PROJECT_LIFE_YR,
            ),
            use_container_width=True,
        )
    with col_b:
        plotly_chart(
            charts.lcosaf_bar(
                REGIONS, SAF_PATHWAYS,
                custom_capex, custom_opex,
                UTILIZATION_FACTOR, irr_sel, PROJECT_LIFE_YR,
            ),
            use_container_width=True,
        )

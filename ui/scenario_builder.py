"""
Scenario Builder — save, load, and export named model scenarios.

A scenario is a named snapshot of all input CSVs in data/mock/.
Scenarios are stored in scenarios/<name>/ alongside a meta.json.
The combined Excel download includes one sheet per input CSV plus
output sheets (Prices, Capacity, Trade Flows, Market Summary) when
a model run result is available.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
from datetime import datetime, timezone
from typing import List, Optional

import pandas as pd
import streamlit as st

_HERE = os.path.dirname(os.path.abspath(__file__))
_MOCK_DIR      = os.path.join(_HERE, "..", "data", "mock")
_SCENARIOS_DIR = os.path.join(_HERE, "..", "scenarios")

INPUT_CSVS = [
    "flight_routes.csv",
    "airlines.csv",
    "aircraft_types.csv",
    "corsia_schedule.csv",
    "corsia_suppression.csv",
    "national_blending_mandates.csv",
    "committed_capacity.csv",
    "refinery_capacity.csv",
    "domestic_supply_priority.csv",
    "feedstock_availability.csv",
    "transport_costs.csv",
    "regulatory_params.csv",
    "wtp_params.csv",
]

_SAFE_NAME_RE = re.compile(r"[^\w\-]")


def _safe(name: str) -> str:
    return _SAFE_NAME_RE.sub("_", name.strip())[:64]


# ─────────────────────────────────────────────────────────────────────────────
# Core scenario operations
# ─────────────────────────────────────────────────────────────────────────────

def save_scenario(name: str, meta: dict) -> str:
    dest = os.path.join(_SCENARIOS_DIR, name)
    os.makedirs(dest, exist_ok=True)
    for f in INPUT_CSVS:
        src = os.path.join(_MOCK_DIR, f)
        if os.path.exists(src):
            shutil.copy(src, dest)
    with open(os.path.join(dest, "meta.json"), "w") as fh:
        json.dump({**meta, "saved_at": datetime.now(timezone.utc).isoformat()}, fh, indent=2)
    return dest


def load_scenario(name: str) -> None:
    src_dir = os.path.join(_SCENARIOS_DIR, name)
    for f in INPUT_CSVS:
        src = os.path.join(src_dir, f)
        if os.path.exists(src):
            shutil.copy(src, _MOCK_DIR)
    # Clear any uploaded-CSV overrides from session state
    for f in INPUT_CSVS:
        key = "ss_" + f.replace(".csv", "").replace("-", "_")
        st.session_state.pop(key, None)


def list_scenarios() -> List[str]:
    if not os.path.isdir(_SCENARIOS_DIR):
        return []
    return sorted(
        d for d in os.listdir(_SCENARIOS_DIR)
        if os.path.isdir(os.path.join(_SCENARIOS_DIR, d))
        and not d.startswith(".")
    )


def _read_meta(name: str) -> dict:
    path = os.path.join(_SCENARIOS_DIR, name, "meta.json")
    if os.path.exists(path):
        with open(path) as fh:
            return json.load(fh)
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# Excel export helpers
# ─────────────────────────────────────────────────────────────────────────────

def _prices_df(history) -> pd.DataFrame:
    rows = []
    for s in history:
        for p in s.market.prices:
            rows.append({
                "Year": p.year, "Region": p.region,
                "Clearing Price (USD/MT)": round(p.clearing_price_usd_per_mt, 2),
                "Regime": p.pricing_regime,
                "Supply Cost (USD/MT)": round(p.supply_cost_usd_per_mt, 2),
                "Transport Premium (USD/MT)": round(p.transport_premium_usd_per_mt, 2),
                "Margin (USD/MT)": round(p.margin_usd_per_mt, 2),
            })
    return pd.DataFrame(rows)


def _capacity_df(history) -> pd.DataFrame:
    rows = []
    for s in history:
        for plant in s.capacity.plants:
            rows.append({
                "Year": s.year, "Region": plant.region, "Pathway": plant.pathway,
                "Capacity (MT/yr)": round(plant.capacity_mt_yr, 4),
                "Type": "Planned" if plant.is_deterministic else "Modelled",
            })
    return pd.DataFrame(rows)


def _trade_df(history) -> pd.DataFrame:
    rows = []
    for s in history:
        for f in s.market.trade_flows:
            if f.volume_mt > 1e-5:
                rows.append({
                    "Year": f.year, "Origin": f.origin_region,
                    "Destination": f.destination_region,
                    "Pathway": getattr(f, "pathway", ""),
                    "Volume (MT)": round(f.volume_mt, 4),
                    "Transport Cost (USD/MT)": f.transport_cost_usd_per_mt,
                })
    return pd.DataFrame(rows)


def _summary_df(history) -> pd.DataFrame:
    rows = []
    for s in history:
        rows.append({
            "Year": s.year,
            "Total Demand (MT)": s.demand.total_volume_mt(s.year),
            "Total Produced (MT)": s.market.total_saf_produced_mt,
            "Total Traded (MT)": s.market.total_saf_traded_mt,
            "Market Balanced": s.market.market_balanced,
            "Expansion Triggered": s.expansion.build_triggered,
        })
    return pd.DataFrame(rows)


def build_scenario_excel(name: str, history: Optional[list]) -> bytes:
    """
    Build a combined Excel workbook:
      - Metadata sheet
      - One sheet per input CSV (from the saved scenario folder)
      - Output sheets (if history provided): Prices, Capacity, Trade Flows, Summary
    """
    buf = io.BytesIO()
    meta = _read_meta(name)
    scen_dir = os.path.join(_SCENARIOS_DIR, name)

    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        # Metadata
        meta_rows = [{"Key": k, "Value": str(v)} for k, v in meta.items()]
        pd.DataFrame(meta_rows).to_excel(writer, sheet_name="Metadata", index=False)

        # Input sheets
        for f in INPUT_CSVS:
            path = os.path.join(scen_dir, f)
            if os.path.exists(path):
                sheet_name = f.replace(".csv", "")[:31]
                pd.read_csv(path).to_excel(writer, sheet_name=sheet_name, index=False)

        # Output sheets
        if history:
            _prices_df(history).to_excel(writer, sheet_name="Out_Prices", index=False)
            _capacity_df(history).to_excel(writer, sheet_name="Out_Capacity", index=False)
            _trade_df(history).to_excel(writer, sheet_name="Out_TradeFlows", index=False)
            _summary_df(history).to_excel(writer, sheet_name="Out_MarketSummary", index=False)

    return buf.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# Streamlit UI
# ─────────────────────────────────────────────────────────────────────────────

def render(history: Optional[list] = None) -> None:
    from ui import components

    components.page_header(
        "Scenarios",
        "Save, load, and export named snapshots of all model input tables.",
    )
    components.methodology(
        """
        A **scenario** is a named snapshot of all model input tables (CSV files). Saving a
        scenario captures the current state of every input — routes, capacity, CORSIA
        schedule, regulatory parameters, WTP parameters, and more — so you can switch between
        assumptions without losing earlier configurations. If a model run has been completed,
        the downloaded Excel also includes all output sheets (prices, capacity, trade flows,
        market summary).

        **Workflow:** Edit inputs → Run model → Save scenario → Download combined Excel
        """,
        title="How scenarios work",
    )

    os.makedirs(_SCENARIOS_DIR, exist_ok=True)

    # ── Save current inputs ──────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("**Save current inputs as a scenario**")
        col_name, col_btn = st.columns([3, 1])
        with col_name:
            new_name = st.text_input(
                "Scenario name", value="", placeholder="e.g. high_demand_2040",
                key="scen_name_input",
                help="Only letters, numbers, hyphens, and underscores. Max 64 characters.",
            )
        with col_btn:
            st.write("")  # vertical align
            save_clicked = st.button(
                "Save scenario", key="scen_save_btn",
                icon=":material/save:", type="primary", use_container_width=True,
            )

        if save_clicked:
            safe = _safe(new_name)
            if not safe:
                st.error("Please enter a valid scenario name.")
            else:
                meta = {
                    "scenario_name": safe,
                    "start_year": st.session_state.get("start_year", "—"),
                    "end_year":   st.session_state.get("end_year",   "—"),
                    "run_completed": history is not None,
                }
                save_scenario(safe, meta)
                st.toast(f"Scenario {safe} saved ({len(INPUT_CSVS)} input files)",
                         icon=":material/check_circle:")

    # ── Saved scenarios list ─────────────────────────────────────────────────
    st.subheader("Saved Scenarios")
    scenarios = list_scenarios()

    if not scenarios:
        components.empty_state(
            "No scenarios saved yet. Edit your inputs, then save them as a "
            "named scenario above."
        )
        return

    for name in scenarios:
        meta = _read_meta(name)
        saved_at = meta.get("saved_at", "unknown")[:19].replace("T", " ")
        run_ok   = meta.get("run_completed", False)
        horizon  = f"{meta.get('start_year','?')}–{meta.get('end_year','?')}"
        run_str  = "run attached" if run_ok else "inputs only"

        with st.container(border=True):
            cols = st.columns([3, 2, 1.2, 1.8])
            cols[0].markdown(f"**{name}**")
            cols[1].caption(f"Saved: {saved_at}  ·  Horizon: {horizon}  ·  {run_str}")

            if cols[2].button("Load", key=f"load_{name}",
                              icon=":material/upload:", use_container_width=True):
                load_scenario(name)
                st.success(
                    f"Scenario **{name}** loaded into the input tables. "
                    "Open the **Inputs** page to review, then re-run the model."
                )

            excel_bytes = build_scenario_excel(name, history)
            cols[3].download_button(
                "Download Excel",
                data=excel_bytes,
                file_name=f"{name}_scenario.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"dl_{name}",
                icon=":material/download:",
                use_container_width=True,
            )
            st.caption(
                f"Inputs: {len(INPUT_CSVS)} CSVs"
                + (f" + {len(history)} years of outputs" if history else " (no run output yet)")
            )

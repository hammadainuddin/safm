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

# Demand run-settings persisted in meta.json so a scenario fully reproduces
# its run (not just the input CSVs). start_year/end_year are stored too.
RUN_SETTING_KEYS = [
    "demand_mode", "include_domestic", "route_sample_fraction",
    "demand_scale_factor", "efficiency_improvement_rate",
    "start_year", "end_year",
]


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


def load_scenario_files(name: str) -> None:
    """Copy a scenario's input CSVs into data/mock/ (no session-state access —
    safe to call from the batch runner's background thread)."""
    src_dir = os.path.join(_SCENARIOS_DIR, name)
    for f in INPUT_CSVS:
        src = os.path.join(src_dir, f)
        if os.path.exists(src):
            shutil.copy(src, _MOCK_DIR)


def load_scenario(name: str) -> None:
    """Load a scenario into the working inputs AND restore its run settings
    into session state (UI-thread use)."""
    load_scenario_files(name)
    # Clear any uploaded-CSV overrides from session state
    for f in INPUT_CSVS:
        key = "ss_" + f.replace(".csv", "").replace("-", "_")
        st.session_state.pop(key, None)
    # Restore the demand run-settings so the loaded scenario reproduces its run.
    meta = _read_meta(name)
    for k in RUN_SETTING_KEYS:
        if k in meta:
            try:
                st.session_state[k] = meta[k]
            except Exception:
                pass


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
                from config.settings import (
                    MODEL_START_YEAR, MODEL_END_YEAR,
                    ROUTE_SAMPLE_FRACTION as _DEF_RSF,
                )
                meta = {
                    "scenario_name": safe,
                    "run_completed": history is not None,
                    # Demand run-settings — captured so the scenario fully
                    # reproduces its run (see RUN_SETTING_KEYS).
                    "start_year": st.session_state.get("start_year", MODEL_START_YEAR),
                    "end_year": st.session_state.get("end_year", MODEL_END_YEAR),
                    "demand_mode": st.session_state.get("demand_mode", "corsia_schedule"),
                    "include_domestic": bool(st.session_state.get("include_domestic", False)),
                    "route_sample_fraction": float(st.session_state.get("route_sample_fraction", _DEF_RSF)),
                    "demand_scale_factor": float(st.session_state.get("demand_scale_factor", 1.0)),
                    "efficiency_improvement_rate": float(st.session_state.get("efficiency_improvement_rate", 0.015)),
                }
                save_scenario(safe, meta)
                st.toast(f"Scenario {safe} saved ({len(INPUT_CSVS)} input files)",
                         icon=":material/check_circle:")

    scenarios = list_scenarios()

    # ── Batch run ─────────────────────────────────────────────────────────────
    if scenarios:
        with st.container(border=True):
            st.markdown("**Batch run scenarios**")
            st.caption(
                "Select saved scenarios and run them sequentially. Each loads its "
                "own inputs and run settings; results are stored and available on the "
                "Results page (Compare runs). Your current working inputs are preserved."
            )
            selected = st.multiselect(
                "Scenarios to run", scenarios, key="batch_scen_select",
                label_visibility="collapsed",
            )
            runner = st.session_state.get("runner")
            running = runner is not None and not runner.done
            if st.button(
                f"Run {len(selected)} scenario(s)" if selected else "Run selected scenarios",
                icon=":material/play_arrow:", type="primary",
                disabled=running or not selected,
            ):
                from ui.runner import BackgroundRunner
                specs = []
                for nm in selected:
                    m = _read_meta(nm)
                    specs.append({
                        "name": nm,
                        "load_inputs": True,
                        "start_year": int(m.get("start_year", 2025)),
                        "end_year": int(m.get("end_year", 2050)),
                        "demand_mode": m.get("demand_mode", "corsia_schedule"),
                        "include_domestic": bool(m.get("include_domestic", False)),
                        "route_sample_fraction": float(m.get("route_sample_fraction", 1.0)),
                        "demand_scale_factor": float(m.get("demand_scale_factor", 1.0)),
                        "efficiency_improvement_rate": float(m.get("efficiency_improvement_rate", 0.015)),
                    })
                new_runner = BackgroundRunner()
                st.session_state.runner = new_runner
                st.session_state.history = None
                st.session_state.histories = {}
                st.session_state.step_log = []
                st.session_state.step_table = {}
                st.session_state["_run_finalized"] = False
                new_runner.start_batch(specs)
                st.rerun()

        # Live batch progress (shared panel with the Run Model page).
        from ui import run_model
        if st.session_state.get("runner") is not None:
            run_model.render_progress(empty_msg="Select scenarios above and run them.")

    # ── Saved scenarios list ─────────────────────────────────────────────────
    st.subheader("Saved Scenarios")

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
        mode     = meta.get("demand_mode", "?")
        dom      = "dom+intl" if meta.get("include_domestic") else "intl-only"
        eff      = meta.get("efficiency_improvement_rate")
        eff_str  = f"  ·  eff {eff*100:.1f}%/yr" if isinstance(eff, (int, float)) else ""

        with st.container(border=True):
            cols = st.columns([3, 2, 1.2, 1.8])
            cols[0].markdown(f"**{name}**")
            cols[1].caption(
                f"Saved: {saved_at}  ·  Horizon: {horizon}  ·  {run_str}\n\n"
                f"{mode}  ·  {dom}{eff_str}"
            )

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

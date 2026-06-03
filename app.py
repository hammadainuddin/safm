"""
SAF Global Market Model — Streamlit UI
======================================
Launch with:  streamlit run app.py

Three tabs:
  📊 Inputs    — editable tables + charts for all model inputs
  ▶  Run Model — scenario configuration, live progress, logs
  📈 Outputs   — price, capacity, trade flow tables and charts
"""

from __future__ import annotations

import os
import sys
import time

import streamlit as st

# Ensure project root is on path when running from any directory
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from config.settings import MODEL_END_YEAR, MODEL_START_YEAR, HORIZON_YEARS, ROUTE_SAMPLE_FRACTION as _DEFAULT_RSF
from ui import input_editor, output_dashboard

st.set_page_config(
    page_title="SAF Market Model",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Session state initialisation ────────────────────────────────────────────
if "runner" not in st.session_state:
    st.session_state.runner = None
if "history" not in st.session_state:
    st.session_state.history = None
if "step_log" not in st.session_state:
    st.session_state.step_log = []  # list of log strings
if "step_table" not in st.session_state:
    st.session_state.step_table = {}  # {year: {step: status}}
if "active_tab" not in st.session_state:
    st.session_state.active_tab = 0

# ── Tab layout ───────────────────────────────────────────────────────────────
tab_inputs, tab_run, tab_outputs, tab_scenarios = st.tabs([
    "📊 Inputs", "▶ Run Model", "📈 Outputs", "🎭 Scenarios"
])


# ============================================================================
# TAB 1 — Inputs
# ============================================================================
with tab_inputs:
    input_editor.render()


# ============================================================================
# TAB 2 — Run Model
# ============================================================================
with tab_run:
    st.header("Run Model")

    runner = st.session_state.runner

    # ── Configuration ────────────────────────────────────────────────────────
    with st.expander("⚙️ Run Configuration", expanded=(runner is None or runner.done)):
        col1, col2, col3 = st.columns(3)
        with col1:
            scenario = st.text_input("Scenario name", value="baseline", key="scenario")
        with col2:
            start_year = st.selectbox(
                "Start year", HORIZON_YEARS, index=0, key="start_year"
            )
        with col3:
            end_year = st.selectbox(
                "End year", HORIZON_YEARS,
                index=len(HORIZON_YEARS) - 1, key="end_year"
            )

    # ── Run / Stop buttons ───────────────────────────────────────────────────
    col_run, col_status = st.columns([1, 3])
    with col_run:
        run_disabled = runner is not None and not runner.done
        if st.button("▶ Run Model", disabled=run_disabled, type="primary", use_container_width=True):
            from ui.runner import BackgroundRunner
            new_runner = BackgroundRunner()
            st.session_state.runner = new_runner
            st.session_state.step_log = []
            st.session_state.step_table = {}
            new_runner.start(
                start_year=int(start_year),
                end_year=int(end_year),
                scenario=scenario,
                verbose=False,
                demand_scale_factor=float(st.session_state.get("demand_scale_factor", 1.0)),
                route_sample_fraction=float(st.session_state.get("route_sample_fraction", _DEFAULT_RSF)),
            )
            st.rerun()

    runner = st.session_state.runner  # refresh after potential start

    # ── Live progress ────────────────────────────────────────────────────────
    if runner is not None:
        # Drain queued events
        events = runner.drain_events()
        step_icons = {"demand": "📥", "expansion": "🏗️", "equilibrium": "⚖️", "done": "✅"}
        step_descriptions = {
            "demand":      "computed bottom-up CORSIA + national-mandate demand from flight activity, fleet efficiency, and route mix",
            "expansion":   "solved least-cost LP, sized any new endogenous plants and brought them online (LCOSAF-ranked, feedstock + refinery-cap constrained)",
            "equilibrium": "cleared the market with WTP-priority dispatch (domestic-first, LCOSAF ≤ regional WTP); unserved demand routed to CORSIA offsets",
            "done":        "year complete — prices, trade flows, and capacity state written to history",
        }
        for ev in events:
            if ev.step == "complete" and ev.year is None:
                break
            if ev.year is not None and ev.step != "complete":
                icon = step_icons.get(ev.step, "•")
                desc = step_descriptions.get(ev.step, ev.step)
                log_line = f"{icon} {ev.year} · {ev.step} — {desc}"
                st.session_state.step_log.append(log_line)
                # Update step table
                if ev.year not in st.session_state.step_table:
                    st.session_state.step_table[ev.year] = {}
                st.session_state.step_table[ev.year][ev.step] = "done"

        # Store finished history
        if runner.done and runner.history is not None and st.session_state.history is None:
            st.session_state.history = runner.history

        # Progress bar
        frac = runner.progress_fraction()
        elapsed = runner.elapsed_seconds
        remaining = runner.estimated_remaining()

        if runner.done and runner.error is None:
            st.success(f"✅ Run complete in {elapsed:.1f}s")
        elif runner.done and runner.error is not None:
            st.error(f"❌ Run failed: {runner.error}")
        else:
            st.progress(frac)
            with col_status:
                rem_str = f" — ~{remaining:.0f}s remaining" if remaining else ""
                st.caption(f"⏱ {elapsed:.1f}s elapsed{rem_str}  |  {int(frac*100)}% complete")

        # Step table
        if st.session_state.step_table:
            st.subheader("Step Progress")
            years = sorted(st.session_state.step_table.keys())
            steps = ["demand", "expansion", "equilibrium", "done"]
            import pandas as pd
            rows = []
            for y in years:
                row = {"Year": y}
                for s in steps:
                    status = st.session_state.step_table[y].get(s)
                    row[s.capitalize()] = "✅" if status == "done" else "⏳"
                rows.append(row)
            st.dataframe(pd.DataFrame(rows).set_index("Year"), use_container_width=True)

        # Live log
        with st.expander("📋 Step Log", expanded=not runner.done):
            log_text = "\n".join(st.session_state.step_log[-100:])  # last 100 lines
            st.text_area("Log", value=log_text, height=300, key="log_area", disabled=True)

        # Auto-rerun while running
        if not runner.done:
            time.sleep(0.5)
            st.rerun()

    else:
        st.info("Configure the scenario above and click **▶ Run Model** to start.")


# ============================================================================
# TAB 3 — Outputs
# ============================================================================
with tab_outputs:
    output_dashboard.render(st.session_state.history)


# ============================================================================
# TAB 4 — Scenarios
# ============================================================================
with tab_scenarios:
    from ui import scenario_builder
    scenario_builder.render(st.session_state.history)

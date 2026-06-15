"""
SARUS — Sustainable Aviation (Demand) Rationalization and Utility System model
==============================================================================
Streamlit UI. Launch with:  streamlit run app.py

Sidebar navigation:
  Workspace — Inputs, Run Model, Results, Scenarios
  Analysis  — LCOSAF Explorer
"""

from __future__ import annotations

import os
import sys

import streamlit as st

# Ensure project root is on path when running from any directory
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

st.set_page_config(
    page_title="SARUS",
    page_icon=os.path.join(_HERE, "assets", "icon.svg"),
    layout="wide",
    initial_sidebar_state="expanded",
)

from ui import styles, theme

theme.register()
styles.inject()

# ── Session state initialisation ────────────────────────────────────────────
if "runner" not in st.session_state:
    st.session_state.runner = None
if "history" not in st.session_state:
    st.session_state.history = None
if "step_log" not in st.session_state:
    st.session_state.step_log = []  # list of log strings
if "step_table" not in st.session_state:
    st.session_state.step_table = {}  # {year: {step: status}}

# st.navigation only reruns the active page, so widget state on inactive
# pages would otherwise be garbage-collected. Re-assigning promotes these
# cross-page keys to persistent session state.
for _k in (
    "demand_mode", "include_domestic", "route_sample_fraction",
    "demand_scale_factor", "efficiency_improvement_rate",
    "scenario", "start_year", "end_year",
):
    if _k in st.session_state:
        st.session_state[_k] = st.session_state[_k]

# Capture run events / finished history on every rerun, whichever page is open.
from ui import run_model

run_model.sync_runner_state()

st.logo(
    os.path.join(_HERE, "assets", "wordmark.svg"),
    icon_image=os.path.join(_HERE, "assets", "icon.svg"),
)


# ── Pages ────────────────────────────────────────────────────────────────────
def _inputs() -> None:
    from ui import input_editor
    input_editor.render()


def _run() -> None:
    run_model.render()


def _results() -> None:
    from ui import output_dashboard
    output_dashboard.render(st.session_state.history)


def _scenarios() -> None:
    from ui import scenario_builder
    scenario_builder.render(st.session_state.history)


def _lcosaf() -> None:
    from ui import lcosaf_explorer
    lcosaf_explorer.render()


pg_inputs = st.Page(_inputs, title="Inputs", icon=":material/edit_note:",
                    url_path="inputs", default=True)
pg_run = st.Page(_run, title="Run Model", icon=":material/play_circle:",
                 url_path="run")
pg_results = st.Page(_results, title="Results", icon=":material/monitoring:",
                     url_path="results")
pg_scenarios = st.Page(_scenarios, title="Scenarios", icon=":material/folder_copy:",
                       url_path="scenarios")
pg_lcosaf = st.Page(_lcosaf, title="LCOSAF Explorer", icon=":material/calculate:",
                    url_path="lcosaf")

# Registry used by components.empty_state for cross-page links.
st.session_state["_pages"] = {
    "inputs": pg_inputs,
    "run": pg_run,
    "results": pg_results,
}

nav = st.navigation({
    "Workspace": [pg_inputs, pg_run, pg_results, pg_scenarios],
    "Analysis":  [pg_lcosaf],
})
nav.run()

with st.sidebar:
    st.caption(
        "SARUS · v1.0 · horizon 2025–2050  \n"
        "Sustainable Aviation Rationalization & Utility System"
    )

"""
Run Model page — scenario configuration, live progress, and the run log.

sync_runner_state() is the single consumer of the BackgroundRunner event
queue. It is called from the app entry on every rerun (any page) and from
the progress fragment, so step events and the finished history are captured
even when the user navigates away mid-run.
"""

from __future__ import annotations

import streamlit as st

from config.settings import HORIZON_YEARS, ROUTE_SAMPLE_FRACTION as _DEFAULT_RSF
from ui import components

_STEP_DESCRIPTIONS = {
    "demand":      "computed bottom-up CORSIA + national-mandate demand from flight activity, fleet efficiency, and route mix",
    "expansion":   "solved least-cost LP, sized any new endogenous plants and brought them online (LCOSAF-ranked, feedstock + refinery-cap constrained)",
    "equilibrium": "cleared the market with WTP-priority dispatch (domestic-first, LCOSAF ≤ regional WTP); unserved demand routed to CORSIA offsets",
    "done":        "year complete — prices, trade flows, and capacity state written to history",
}

_STEPS = ("demand", "expansion", "equilibrium", "done")


def sync_runner_state() -> None:
    """Drain runner events into session state; store history when done."""
    runner = st.session_state.get("runner")
    if runner is None:
        return
    for ev in runner.drain_events():
        if ev.step == "complete" and ev.year is None:
            break
        if ev.year is not None and ev.step != "complete":
            desc = _STEP_DESCRIPTIONS.get(ev.step, ev.step)
            st.session_state.step_log.append(f"{ev.year} · {ev.step} — {desc}")
            st.session_state.step_table.setdefault(ev.year, {})[ev.step] = "done"
    if runner.done and runner.history is not None and st.session_state.history is None:
        st.session_state.history = runner.history


def _render_step_table() -> None:
    if not st.session_state.step_table:
        return
    import pandas as pd
    st.subheader("Step Progress")
    years = sorted(st.session_state.step_table.keys())
    rows = []
    for y in years:
        row = {"Year": y}
        for s in _STEPS:
            status = st.session_state.step_table[y].get(s)
            row[s.capitalize()] = "Done" if status == "done" else "–"
        rows.append(row)
    st.dataframe(pd.DataFrame(rows).set_index("Year"), use_container_width=True)


def render() -> None:
    components.page_header(
        "Run Model",
        "Configure the scenario and horizon, then start a run. "
        "Progress updates live; results appear on the Results page.",
    )

    runner = st.session_state.runner

    # ── Configuration ────────────────────────────────────────────────────────
    if "scenario" not in st.session_state:
        st.session_state.scenario = "baseline"
    if "start_year" not in st.session_state:
        st.session_state.start_year = HORIZON_YEARS[0]
    if "end_year" not in st.session_state:
        st.session_state.end_year = HORIZON_YEARS[-1]

    with st.container(border=True):
        st.markdown("**Run configuration**")
        col1, col2, col3 = st.columns(3)
        with col1:
            scenario = st.text_input("Scenario name", key="scenario")
        with col2:
            start_year = st.selectbox("Start year", HORIZON_YEARS, key="start_year")
        with col3:
            end_year = st.selectbox("End year", HORIZON_YEARS, key="end_year")

    # ── Run button ───────────────────────────────────────────────────────────
    run_disabled = runner is not None and not runner.done
    if st.button(
        "Run Model",
        icon=":material/play_arrow:",
        disabled=run_disabled,
        type="primary",
    ):
        from ui.runner import BackgroundRunner
        new_runner = BackgroundRunner()
        st.session_state.runner = new_runner
        st.session_state.history = None
        st.session_state.step_log = []
        st.session_state.step_table = {}
        st.session_state["_run_finalized"] = False
        new_runner.start(
            start_year=int(start_year),
            end_year=int(end_year),
            scenario=scenario,
            verbose=False,
            demand_scale_factor=float(st.session_state.get("demand_scale_factor", 1.0)),
            route_sample_fraction=float(st.session_state.get("route_sample_fraction", _DEFAULT_RSF)),
            demand_mode=st.session_state.get("demand_mode", "corsia_schedule"),
            include_domestic=bool(st.session_state.get("include_domestic", False)),
        )
        st.rerun()

    runner = st.session_state.runner  # refresh after potential start
    running = runner is not None and not runner.done

    # ── Live progress (fragment polls only while a run is active) ───────────
    @st.fragment(run_every=0.7 if running else None)
    def _progress_panel() -> None:
        sync_runner_state()
        r = st.session_state.runner
        if r is None:
            components.empty_state(
                "Configure a scenario above and click **Run Model** to start."
            )
            return

        if r.done and r.error is None:
            st.success(
                f"Run complete in {r.elapsed_seconds:.1f}s",
                icon=":material/check_circle:",
            )
        elif r.done and r.error is not None:
            st.error(f"Run failed: {r.error}")
        else:
            remaining = r.estimated_remaining()
            rem_str = f" · ~{remaining:.0f}s remaining" if remaining else ""
            st.progress(
                r.progress_fraction(),
                text=f"{r.elapsed_seconds:.0f}s elapsed{rem_str} "
                     f"· {int(r.progress_fraction() * 100)}% complete",
            )

        _render_step_table()

        with st.expander("Run log", icon=":material/terminal:", expanded=not r.done):
            st.code("\n".join(st.session_state.step_log[-100:]) or "—", language=None)

        if r.done and not st.session_state.get("_run_finalized", True):
            st.session_state["_run_finalized"] = True
            st.rerun(scope="app")

    _progress_panel()

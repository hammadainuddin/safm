"""
Background model runner for the Streamlit UI.

Runs one or more scenarios via run_model() in a daemon thread and exposes:
- A queue of step events (scenario-tagged) for the live progress display
- Per-scenario finished histories and DuckDB run_ids once complete
- Timing information for duration estimation

A single ad-hoc run is just a batch of one spec.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from queue import Queue, Empty
from threading import Thread
from typing import Dict, List, Optional


class StepEvent:
    __slots__ = ("year", "step", "ts", "payload", "scenario")

    def __init__(self, year, step: str, ts: float, payload=None, scenario=None):
        self.year = year
        self.step = step
        self.ts = ts
        self.payload = payload
        self.scenario = scenario


_MOCK_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "mock")

# Spec keys that map directly to run_model() kwargs.
_RUN_KWARGS = (
    "start_year", "end_year", "demand_mode", "include_domestic",
    "route_sample_fraction", "demand_scale_factor", "efficiency_improvement_rate",
)


class BackgroundRunner:
    """
    Wraps run_model() in a daemon thread for Streamlit progress display.

    Single run:
        runner.start(start_year=2025, end_year=2050, scenario="baseline", ...)

    Batch run (N saved scenarios, sequential):
        runner.start_batch([spec1, spec2, ...])
        # each spec: {name, load_inputs, start_year, end_year, demand_mode,
        #             include_domestic, route_sample_fraction,
        #             demand_scale_factor, efficiency_improvement_rate}
    """

    STEPS = ("demand", "expansion", "equilibrium", "done")

    def __init__(self):
        self.queue: "Queue[StepEvent]" = Queue()
        self.histories: Dict[str, list] = {}   # scenario name → List[ModelState]
        self.run_ids: Dict[str, str] = {}       # scenario name → DuckDB run_id
        self.history: Optional[List] = None      # last scenario's history (compat)
        self.done: bool = False
        self.error: Optional[Exception] = None
        self.scenario_names: List[str] = []
        self._start_ts: Optional[float] = None
        self._first_year_done_ts: Optional[float] = None
        self._years_total: int = 0
        self._years_done: int = 0

    # ── Timing / progress ─────────────────────────────────────────────────────

    @property
    def elapsed_seconds(self) -> float:
        if self._start_ts is None:
            return 0.0
        return time.time() - self._start_ts

    def estimated_remaining(self) -> Optional[float]:
        if self._first_year_done_ts is None or self._years_done == 0 or self._years_total == 0:
            return None
        secs_per_year = (self._first_year_done_ts - self._start_ts)
        remaining_years = self._years_total - self._years_done
        return secs_per_year * remaining_years

    def progress_fraction(self) -> float:
        if self._years_total == 0:
            return 0.0
        return min(1.0, self._years_done / self._years_total)

    # ── Launch ────────────────────────────────────────────────────────────────

    def start(self, scenario: str = "baseline", **run_model_kwargs):
        """Single ad-hoc run using the current working inputs in data/mock/."""
        spec = {"name": scenario, "load_inputs": False}
        spec.update({k: v for k, v in run_model_kwargs.items() if k in _RUN_KWARGS})
        self.start_batch([spec])

    def start_batch(self, specs: List[dict]):
        """Run a list of scenario specs sequentially in a daemon thread."""
        self.done = False
        self.error = None
        self.histories = {}
        self.run_ids = {}
        self.history = None
        self.scenario_names = [s["name"] for s in specs]
        self._start_ts = time.time()
        self._years_total = sum(
            int(s.get("end_year", 2050)) - int(s.get("start_year", 2025)) + 1
            for s in specs
        )
        self._years_done = 0
        self._first_year_done_ts = None
        t = Thread(target=self._run_batch, kwargs={"specs": specs}, daemon=True)
        t.start()

    def drain_events(self) -> List[StepEvent]:
        events = []
        while True:
            try:
                events.append(self.queue.get_nowait())
            except Empty:
                break
        return events

    # Module prefixes safe to evict so the background thread imports a
    # self-consistent set of class objects regardless of Streamlit's watcher.
    _PROJECT_PREFIXES = (
        "schemas.", "modules.", "data.", "config.", "utils.", "main",
    )

    def _evict_modules(self) -> None:
        import sys
        for key in [k for k in list(sys.modules)
                    if any(k == p or k.startswith(p) for p in self._PROJECT_PREFIXES)]:
            sys.modules.pop(key, None)

    def _run_batch(self, specs: List[dict]):
        backup_dir = None
        try:
            self._evict_modules()
            from main import run_model
            from data import results_store
            from data import loaders
            from ui import scenario_builder

            results_store.init_schema()

            # Snapshot working inputs so scenario CSV-swapping can't clobber them.
            needs_swap = any(s.get("load_inputs") for s in specs)
            if needs_swap:
                backup_dir = tempfile.mkdtemp(prefix="saf_mock_backup_")
                for f in os.listdir(_MOCK_DIR):
                    if f.endswith(".csv"):
                        shutil.copy(os.path.join(_MOCK_DIR, f), backup_dir)

            for spec in specs:
                name = spec["name"]
                if spec.get("load_inputs"):
                    scenario_builder.load_scenario_files(name)
                    # The only cross-run cache that would go stale in one thread.
                    loaders._CORSIA_CACHE = None

                self.queue.put(StepEvent(None, "scenario_start", time.time(), scenario=name))

                params = {k: spec[k] for k in _RUN_KWARGS if k in spec}

                def _on_step(year, step, payload=None, _name=name):
                    # run_model fires its own end-of-run "complete"; the batch
                    # emits its own scenario_done + a single final complete, so
                    # swallow the per-run one (it would stop the UI drain early).
                    if step == "complete":
                        return
                    self._on_step(year, step, payload, _name)

                history = run_model(scenario=name, verbose=False, on_step=_on_step, **params)
                self.histories[name] = history
                self.history = history

                try:
                    settings = {k: spec.get(k) for k in _RUN_KWARGS}
                    self.run_ids[name] = results_store.persist_run(name, history, settings)
                except Exception as exc:  # persistence failure shouldn't lose the run
                    self.queue.put(StepEvent(None, "persist_error", time.time(),
                                             payload=str(exc), scenario=name))

                self.queue.put(StepEvent(None, "scenario_done", time.time(), scenario=name))

        except Exception as exc:
            self.error = exc
            self.queue.put(StepEvent(None, "error", time.time(), payload=str(exc)))
        finally:
            # Restore the working inputs.
            if backup_dir is not None:
                for f in os.listdir(backup_dir):
                    shutil.copy(os.path.join(backup_dir, f), _MOCK_DIR)
                shutil.rmtree(backup_dir, ignore_errors=True)
            self.done = True
            self.queue.put(StepEvent(None, "complete", time.time()))

    def _on_step(self, year, step: str, payload=None, scenario=None):
        ts = time.time()
        self.queue.put(StepEvent(year, step, ts, payload, scenario))
        if step == "done" and year is not None:
            self._years_done += 1
            if self._first_year_done_ts is None:
                self._first_year_done_ts = ts

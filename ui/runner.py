"""
Background model runner for the Streamlit UI.

Runs run_model() in a daemon thread and exposes:
- A queue of step events for the live progress display
- The finished history list once the run completes
- Timing information for duration estimation
"""

from __future__ import annotations

import time
from queue import Queue, Empty
from threading import Thread
from typing import Callable, List, Optional


class StepEvent:
    __slots__ = ("year", "step", "ts", "payload")

    def __init__(self, year, step: str, ts: float, payload=None):
        self.year = year
        self.step = step
        self.ts = ts
        self.payload = payload


class BackgroundRunner:
    """
    Wraps run_model() in a daemon thread for Streamlit progress display.

    Usage (in Streamlit):
        runner = BackgroundRunner()
        runner.start(start_year=2025, end_year=2045, scenario="baseline", verbose=False)
        while not runner.done:
            events = runner.drain_events()
            update_ui(events)
            time.sleep(0.5)
            st.rerun()
    """

    STEPS = ("demand", "expansion", "equilibrium", "done")

    def __init__(self):
        self.queue: Queue[StepEvent] = Queue()
        self.history: Optional[List] = None
        self.done: bool = False
        self.error: Optional[Exception] = None
        self._start_ts: Optional[float] = None
        self._first_year_done_ts: Optional[float] = None
        self._years_total: int = 0
        self._years_done: int = 0

    @property
    def elapsed_seconds(self) -> float:
        if self._start_ts is None:
            return 0.0
        return time.time() - self._start_ts

    def estimated_remaining(self) -> Optional[float]:
        """Return estimated remaining seconds, or None if not enough data yet."""
        if self._first_year_done_ts is None or self._years_done == 0 or self._years_total == 0:
            return None
        secs_per_year = (self._first_year_done_ts - self._start_ts)
        remaining_years = self._years_total - self._years_done
        return secs_per_year * remaining_years

    def progress_fraction(self) -> float:
        if self._years_total == 0:
            return 0.0
        return min(1.0, self._years_done / self._years_total)

    def start(self, **run_model_kwargs):
        """Spawn the background thread."""
        self.done = False
        self.history = None
        self.error = None
        self._start_ts = time.time()
        self._years_total = (
            run_model_kwargs.get("end_year", 2045) -
            run_model_kwargs.get("start_year", 2025) + 1
        )
        t = Thread(target=self._run, kwargs=run_model_kwargs, daemon=True)
        t.start()

    def drain_events(self) -> List[StepEvent]:
        """Return all queued events without blocking."""
        events = []
        while True:
            try:
                events.append(self.queue.get_nowait())
            except Empty:
                break
        return events

    def _run(self, **kwargs):
        try:
            from main import run_model
            self.history = run_model(
                on_step=self._on_step,
                **kwargs,
            )
        except Exception as exc:
            self.error = exc
            self.queue.put(StepEvent(None, "error", time.time(), str(exc)))
        finally:
            self.done = True
            self.queue.put(StepEvent(None, "complete", time.time()))

    def _on_step(self, year, step: str, payload=None):
        ts = time.time()
        self.queue.put(StepEvent(year, step, ts, payload))
        if step == "done" and year is not None:
            self._years_done += 1
            if self._years_done == 1:
                self._first_year_done_ts = ts

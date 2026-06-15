"""
DuckDB results warehouse.

Persists every model run (prices, capacity, trade flows, demand, market
summary) keyed by a run_id so runs survive restarts and can be compared
across scenarios. All access goes through short-lived connections; a module
lock guards writes because the batch runner writes from a daemon thread
while the Streamlit UI thread reads.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from typing import List, Optional

import pandas as pd

from modules.reporting import (
    capacity_df,
    market_summary_df,
    prices_df,
    trade_flows_df,
)

_DB_PATH = os.path.join(os.path.dirname(__file__), "results.duckdb")
_WRITE_LOCK = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    scenario    TEXT,
    ran_at      TIMESTAMP,
    start_year  INTEGER,
    end_year    INTEGER,
    demand_mode TEXT,
    include_domestic BOOLEAN,
    route_sample_fraction DOUBLE,
    demand_scale_factor   DOUBLE,
    efficiency_improvement_rate DOUBLE
);
CREATE TABLE IF NOT EXISTS prices (
    run_id TEXT, year INTEGER, region TEXT,
    clearing_price_usd_per_mt DOUBLE, pricing_regime TEXT,
    shadow_price_usd_per_mt DOUBLE, supply_cost_usd_per_mt DOUBLE,
    transport_premium_usd_per_mt DOUBLE, mandate_premium_usd_per_mt DOUBLE,
    carbon_offset_usd_per_mt DOUBLE, margin_usd_per_mt DOUBLE
);
CREATE TABLE IF NOT EXISTS capacity (
    run_id TEXT, year INTEGER, region TEXT, pathway TEXT,
    total_capacity_mt_yr DOUBLE, new_capacity_mt_yr DOUBLE,
    expansion_triggered BOOLEAN, solver_status TEXT, npv_cost_usd_m DOUBLE
);
CREATE TABLE IF NOT EXISTS trade_flows (
    run_id TEXT, year INTEGER, origin_region TEXT, destination_region TEXT,
    volume_mt DOUBLE, transport_cost_usd_per_mt DOUBLE, is_cross_region BOOLEAN
);
CREATE TABLE IF NOT EXISTS demand (
    run_id TEXT, year INTEGER, region TEXT, demand_mt DOUBLE
);
CREATE TABLE IF NOT EXISTS market_summary (
    run_id TEXT, year INTEGER, total_demand_mt DOUBLE, total_produced_mt DOUBLE,
    total_traded_mt DOUBLE, market_balanced BOOLEAN, expansion_triggered BOOLEAN,
    expansion_npv_usd_m DOUBLE
);
"""

_FACT_TABLES = ("prices", "capacity", "trade_flows", "demand", "market_summary")


def _connect(read_only: bool = False):
    import duckdb
    return duckdb.connect(_DB_PATH, read_only=read_only)


def init_schema() -> None:
    """Create the database and all tables if they do not yet exist."""
    with _WRITE_LOCK:
        con = _connect()
        try:
            con.execute(_SCHEMA)
        finally:
            con.close()


def _demand_df(history) -> pd.DataFrame:
    rows = []
    for state in history:
        for region, vol in state.demand.volume_by_region(state.year).items():
            rows.append({"year": state.year, "region": region,
                         "demand_mt": round(float(vol), 6)})
    return pd.DataFrame(rows)


def persist_run(scenario: str, history, settings: dict) -> str:
    """Insert one run plus its fact rows; return the new run_id."""
    init_schema()
    ts = datetime.now(timezone.utc)
    run_id = f"{ts.strftime('%Y%m%d_%H%M%S')}_{scenario}"

    runs_row = pd.DataFrame([{
        "run_id": run_id,
        "scenario": scenario,
        "ran_at": ts,
        "start_year": int(settings.get("start_year", 0)),
        "end_year": int(settings.get("end_year", 0)),
        "demand_mode": str(settings.get("demand_mode", "")),
        "include_domestic": bool(settings.get("include_domestic", False)),
        "route_sample_fraction": float(settings.get("route_sample_fraction", 1.0)),
        "demand_scale_factor": float(settings.get("demand_scale_factor", 1.0)),
        "efficiency_improvement_rate": float(settings.get("efficiency_improvement_rate", 0.015)),
    }])

    facts = {
        "prices": prices_df(history),
        "capacity": capacity_df(history),
        "trade_flows": trade_flows_df(history),
        "demand": _demand_df(history),
        "market_summary": market_summary_df(history),
    }

    with _WRITE_LOCK:
        con = _connect()
        try:
            con.execute(_SCHEMA)
            con.register("runs_row", runs_row)
            con.execute("INSERT INTO runs SELECT * FROM runs_row")
            for table, df in facts.items():
                if df is None or df.empty:
                    continue
                df = df.copy()
                df.insert(0, "run_id", run_id)
                con.register("fact_df", df)
                # Column-explicit insert so order/extra columns never matter.
                cols = ", ".join(df.columns)
                con.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM fact_df")
                con.unregister("fact_df")
        finally:
            con.close()
    return run_id


def list_runs() -> pd.DataFrame:
    """Return all runs (most recent first); empty frame if the DB is absent."""
    if not os.path.exists(_DB_PATH):
        return pd.DataFrame()
    con = _connect(read_only=True)
    try:
        return con.execute(
            "SELECT * FROM runs ORDER BY ran_at DESC"
        ).fetch_df()
    except Exception:
        return pd.DataFrame()
    finally:
        con.close()


def load_table(table: str, run_ids: List[str]) -> pd.DataFrame:
    """Return all rows of `table` for the given run_ids."""
    if table not in _FACT_TABLES or not run_ids or not os.path.exists(_DB_PATH):
        return pd.DataFrame()
    con = _connect(read_only=True)
    try:
        placeholders = ", ".join("?" for _ in run_ids)
        return con.execute(
            f"SELECT * FROM {table} WHERE run_id IN ({placeholders})", run_ids
        ).fetch_df()
    except Exception:
        return pd.DataFrame()
    finally:
        con.close()


def delete_run(run_id: str) -> None:
    """Remove a run and all its fact rows."""
    if not os.path.exists(_DB_PATH):
        return
    with _WRITE_LOCK:
        con = _connect()
        try:
            con.execute("DELETE FROM runs WHERE run_id = ?", [run_id])
            for table in _FACT_TABLES:
                con.execute(f"DELETE FROM {table} WHERE run_id = ?", [run_id])
        finally:
            con.close()

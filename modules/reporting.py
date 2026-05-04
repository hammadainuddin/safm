"""
Reporting module — converts List[ModelState] into CSV and Excel outputs.
All writers are pure functions (no side effects beyond writing files).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import List

import pandas as pd

from schemas.state_schema import ModelState
from utils.logging_config import get_logger

logger = get_logger("reporting")


# ---------------------------------------------------------------------------
# Individual CSV writers
# ---------------------------------------------------------------------------

def prices_to_csv(history: List[ModelState], output_dir: str) -> str:
    rows = []
    for state in history:
        for p in state.market.prices:
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
    path = os.path.join(output_dir, "prices.csv")
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def trade_flows_to_csv(history: List[ModelState], output_dir: str) -> str:
    rows = []
    for state in history:
        for f in state.market.trade_flows:
            rows.append({
                "year": f.year,
                "origin_region": f.origin_region,
                "destination_region": f.destination_region,
                "volume_mt": f.volume_mt,
                "transport_cost_usd_per_mt": f.transport_cost_usd_per_mt,
                "is_cross_region": f.origin_region != f.destination_region,
            })
    path = os.path.join(output_dir, "trade_flows.csv")
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def capacity_to_csv(history: List[ModelState], output_dir: str) -> str:
    rows = []
    for state in history:
        by_rp = state.capacity.capacity_by_region_pathway()
        new_by_rp: dict = {}
        for p in state.expansion.new_plants:
            new_by_rp.setdefault(p.region, {})
            new_by_rp[p.region][p.pathway] = (
                new_by_rp[p.region].get(p.pathway, 0.0) + p.capacity_mt_yr
            )
        for region, pathways in by_rp.items():
            for pathway, total_cap in pathways.items():
                rows.append({
                    "year": state.year,
                    "region": region,
                    "pathway": pathway,
                    "total_capacity_mt_yr": round(total_cap, 4),
                    "new_capacity_mt_yr": round(
                        new_by_rp.get(region, {}).get(pathway, 0.0), 4
                    ),
                    "expansion_triggered": state.expansion.build_triggered,
                    "solver_status": state.expansion.solver_status,
                    "npv_cost_usd_m": round(state.expansion.npv_cost_usd / 1e6, 3),
                })
    path = os.path.join(output_dir, "capacity.csv")
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def market_summary_to_csv(history: List[ModelState], output_dir: str) -> str:
    rows = []
    for state in history:
        rows.append({
            "year": state.year,
            "total_demand_mt": state.demand.total_volume_mt(state.year),
            "total_produced_mt": state.market.total_saf_produced_mt,
            "total_traded_mt": state.market.total_saf_traded_mt,
            "market_balanced": state.market.market_balanced,
            "expansion_triggered": state.expansion.build_triggered,
            "expansion_npv_usd_m": round(state.expansion.npv_cost_usd / 1e6, 3),
        })
    path = os.path.join(output_dir, "market_summary.csv")
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


# ---------------------------------------------------------------------------
# Excel dashboard
# ---------------------------------------------------------------------------

def write_excel_dashboard(history: List[ModelState], output_dir: str) -> str:
    """Write a three-sheet Excel dashboard: Prices, Trade Flows, Capacity."""
    path = os.path.join(output_dir, "summary_dashboard.xlsx")

    prices_rows, flows_rows, cap_rows = [], [], []

    for state in history:
        for p in state.market.prices:
            prices_rows.append({
                "Year": p.year, "Region": p.region,
                "Clearing Price (USD/MT)": round(p.clearing_price_usd_per_mt, 2),
                "Regime": p.pricing_regime,
                "Shadow Price (USD/MT)": round(p.shadow_price_usd_per_mt, 2),
                "Mandate Premium (USD/MT)": round(p.mandate_premium_usd_per_mt, 2),
                "Carbon Offset (USD/MT)": round(p.carbon_offset_usd_per_mt, 2),
                "Margin (USD/MT)": round(p.margin_usd_per_mt, 2),
            })
        for f in state.market.trade_flows:
            if f.volume_mt > 1e-5:
                flows_rows.append({
                    "Year": f.year, "Origin": f.origin_region,
                    "Destination": f.destination_region,
                    "Volume (MT)": round(f.volume_mt, 4),
                    "Transport Cost (USD/MT)": f.transport_cost_usd_per_mt,
                    "Cross-Region": f.origin_region != f.destination_region,
                })
        by_rp = state.capacity.capacity_by_region_pathway()
        for region, pathways in by_rp.items():
            for pathway, cap in pathways.items():
                cap_rows.append({
                    "Year": state.year, "Region": region, "Pathway": pathway,
                    "Total Capacity (MT/yr)": round(cap, 4),
                    "Expansion Triggered": state.expansion.build_triggered,
                })

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(prices_rows).to_excel(writer, sheet_name="Prices", index=False)
        pd.DataFrame(flows_rows).to_excel(writer, sheet_name="Trade Flows", index=False)
        pd.DataFrame(cap_rows).to_excel(writer, sheet_name="Capacity", index=False)

    return path


# ---------------------------------------------------------------------------
# Composite writer
# ---------------------------------------------------------------------------

def write_all(history: List[ModelState], output_dir: str) -> dict:
    """Write all outputs; return {name: path} dict."""
    os.makedirs(output_dir, exist_ok=True)
    outputs = {
        "prices":           prices_to_csv(history, output_dir),
        "trade_flows":      trade_flows_to_csv(history, output_dir),
        "capacity":         capacity_to_csv(history, output_dir),
        "market_summary":   market_summary_to_csv(history, output_dir),
        "excel_dashboard":  write_excel_dashboard(history, output_dir),
    }
    logger.info("All outputs written to %s", output_dir)
    for name, path in outputs.items():
        logger.info("  %-20s → %s", name, os.path.basename(path))
    return outputs


# ---------------------------------------------------------------------------
# Console summary (live monitoring during the loop)
# ---------------------------------------------------------------------------

def print_annual_summary(state: ModelState) -> None:
    """Print a compact one-line summary for year t to stdout."""
    demand    = state.demand.total_volume_mt(state.year)
    produced  = state.market.total_saf_produced_mt
    traded    = state.market.total_saf_traded_mt
    n_new     = len(state.expansion.new_plants)
    avg_price = (
        sum(p.clearing_price_usd_per_mt for p in state.market.prices) / len(state.market.prices)
        if state.market.prices else 0.0
    )
    print(
        f"  {state.year} | demand={demand:6.2f} MT | produced={produced:6.2f} MT "
        f"| traded={traded:5.2f} MT | new_plants={n_new:2d} "
        f"| avg_price={avg_price:7.1f} USD/MT | balanced={state.market.market_balanced}"
    )

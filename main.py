"""
SAF Global Market Model — 20-Year Dynamic Loop
===============================================
Usage:
    python main.py                        # full 2025-2050 run, baseline scenario
    python main.py --start 2025 --end 2030 --scenario baseline
    python main.py --help

Architecture
------------
Each year t executes four steps in order:

    1. Demand     : BottomUpDemandModule estimates SAF demand from CORSIA-eligible
                    international flights + domestic blending mandates.
                    Demand is attributed to the refuelling airport's region (60/40
                    origin/destination split per CORSIA uplift rule).

    2. Expansion  : CapacityExpansionModule assesses gap → least-cost Pyomo LP →
                    new plants → supply_meets_demand flag.

    3. WTP        : WTPModel computes regional willingness-to-pay as
                    max(case1: jet+CORSIA, case2: LCOSAF@IRR, case3: policy penalty).

    4. Clearing   : PriceQuantityClearing allocates supply (cheapest CIF first) to
                    highest-WTP regions; clearing price = WTP of each served region.
                    (Only runs when supply_meets_demand = True.)

State is carried forward: capacity_state accumulates all plants year-over-year.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from typing import Callable, List, Optional

from config.settings import HORIZON_YEARS, MODEL_END_YEAR, MODEL_START_YEAR
from data.loaders import load_committed_capacity
from modules.capacity_expansion import CapacityExpansionModule
from modules.demand_bottom_up import BottomUpDemandModule
from modules.price_quantity_clearing import PriceQuantityClearing
from modules.reporting import print_annual_summary, write_all
from modules.wtp_model import WTPModel
from schemas.equilibrium_schema import MarketClearingResult
from schemas.state_schema import ModelState
from utils.logging_config import get_logger

logger = get_logger("main")

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def _make_empty_market_result(year: int) -> MarketClearingResult:
    """Placeholder result used when supply does not meet demand."""
    return MarketClearingResult(
        year=year,
        trade_flows=[],
        prices=[],
        total_saf_traded_mt=0.0,
        total_saf_produced_mt=0.0,
        market_balanced=False,
        solver_status="skipped_supply_shortfall",
        objective_value=0.0,
    )


def _scale_demand_matrix(matrix, factor: float):
    """Return a new DemandMatrix with all volumes multiplied by factor."""
    from schemas.demand_schema import DemandMatrix, DemandRecord
    from config.settings import MT_TO_PJ_FACTOR
    scaled = [
        DemandRecord(
            year=r.year,
            region=r.region,
            volume_mt=round(r.volume_mt * factor, 8),
            energy_pj=round(r.volume_mt * factor * MT_TO_PJ_FACTOR, 8),
            pathway_mix=r.pathway_mix,
            source=r.source,
        )
        for r in matrix.records
    ]
    return DemandMatrix(records=scaled, scenario_name=matrix.scenario_name,
                        created_at=matrix.created_at)


def run_model(
    start_year:          int = MODEL_START_YEAR,
    end_year:            int = MODEL_END_YEAR,
    scenario:            str = "baseline",
    output_dir:          str = None,
    verbose:             bool = True,
    on_step:             Optional[Callable] = None,
    demand_scale_factor:    float = 1.0,
    route_sample_fraction:  float = None,
    demand_mode:            str = "corsia_schedule",
) -> List[ModelState]:
    """
    Execute the dynamic SAF market model.

    Parameters
    ----------
    start_year : first year of simulation (default 2025)
    end_year   : last year of simulation inclusive (default 2050)
    scenario   : scenario name tag for output labelling
    output_dir : directory for CSV/Excel outputs; auto-generated if None
    verbose    : print per-year console summary
    on_step    : optional callback(year, step_name, payload) for live UI progress

    Returns
    -------
    List[ModelState] — one entry per simulated year, in chronological order.
    """
    def _notify(year, step, payload=None):
        if on_step is not None:
            try:
                on_step(year, step, payload)
            except Exception:
                pass

    # ── Output directory ─────────────────────────────────────────────────────
    if output_dir is None:
        ts         = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output_dir = os.path.join(_PROJECT_ROOT, "outputs", f"results_{ts}_{scenario}")
    os.makedirs(output_dir, exist_ok=True)

    years = [y for y in HORIZON_YEARS if start_year <= y <= end_year]

    logger.info("=" * 60)
    logger.info("SAF Market Model — scenario='%s'  %d–%d", scenario, years[0], years[-1])
    logger.info("=" * 60)

    # ── Module initialisation ─────────────────────────────────────────────────
    demand_module    = BottomUpDemandModule(
        route_sample_fraction=route_sample_fraction,
        demand_mode=demand_mode,
    )
    cap_expansion    = CapacityExpansionModule()
    wtp_model        = WTPModel()
    pq_clearing      = PriceQuantityClearing()

    # ── Initial capacity state (deterministic plants online by start_year) ────
    capacity_state = load_committed_capacity(start_year)

    # ── Annual loop ───────────────────────────────────────────────────────────
    history: List[ModelState] = []

    if verbose:
        print(f"\n{'Year':>4} | {'Demand':>8} | {'Produced':>9} | "
              f"{'Traded':>7} | {'NewPlants':>9} | {'AvgPrice':>10} | Balanced")
        print("-" * 75)

    for year in years:
        logger.info("── Year %d ──────────────────────────────────────────────", year)

        # Step 1: Bottom-up demand
        _notify(year, "demand")
        demand_matrix = demand_module.estimate_demand(year, scenario)
        if demand_scale_factor != 1.0:
            demand_matrix = _scale_demand_matrix(demand_matrix, demand_scale_factor)

        # Step 2: Capacity expansion (standalone module, unchanged)
        _notify(year, "expansion")
        expansion_result, capacity_state = cap_expansion.run(
            demand_matrix=demand_matrix,
            capacity_state=capacity_state,
            year=year,
        )
        expansion = expansion_result.expansion_decision

        # Step 3: WTP + market clearing. PriceQuantityClearing handles partial
        # supply gracefully by routing unserved demand to CORSIA offsets, so we
        # always run the clearing step regardless of supply_meets_demand.
        _notify(year, "equilibrium")
        wtp_matrix = wtp_model.compute_wtp(year, capacity_state)
        market = pq_clearing.clear_market(demand_matrix, capacity_state, year, wtp_matrix)
        if not expansion_result.supply_meets_demand:
            logger.info(
                "Year %d: partial supply — %.3f MT routed to CORSIA offset.",
                year, sum(market.offset_demand_mt_by_region.values()),
            )

        # Step 4: Build ModelState
        cumulative_capacity = capacity_state.total_capacity_by_region()
        state = ModelState(
            year=year,
            demand=demand_matrix,
            capacity=capacity_state,
            expansion=expansion,
            market=market,
            cumulative_capacity_by_region=dict(cumulative_capacity),
            feedstock_remaining=[],
        )
        history.append(state)
        _notify(year, "done", state)

        if verbose:
            print_annual_summary(state)

    # ── Write outputs ─────────────────────────────────────────────────────────
    logger.info("Writing outputs to %s", output_dir)
    outputs = write_all(history, output_dir)

    logger.info("=" * 60)
    logger.info("Run complete: %d years simulated.", len(history))
    for name, path in outputs.items():
        logger.info("  %s", path)
    logger.info("=" * 60)

    _notify(None, "complete", history)
    return history


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="SAF Global Market Model — 20-year dynamic spatial equilibrium"
    )
    p.add_argument("--start",    type=int, default=MODEL_START_YEAR)
    p.add_argument("--end",      type=int, default=MODEL_END_YEAR)
    p.add_argument("--scenario", type=str, default="baseline")
    p.add_argument("--output",   type=str, default=None)
    p.add_argument("--quiet",    action="store_true")
    return p.parse_args(argv)


if __name__ == "__main__":
    args    = _parse_args()
    history = run_model(
        start_year = args.start,
        end_year   = args.end,
        scenario   = args.scenario,
        output_dir = args.output,
        verbose    = not args.quiet,
    )
    sys.exit(0)

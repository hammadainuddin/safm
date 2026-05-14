"""
Standalone Capacity Expansion Module
=====================================
Runs the least-cost capacity expansion LP for a single year and returns a
CapacityExpansionResult that includes a supply_meets_demand flag.

The main loop uses this flag to gate the equilibrium solver:
    expansion_result, capacity_state = CapacityExpansionModule().run(...)
    if expansion_result.supply_meets_demand:
        market = equilibrium_solver.clear_market(...)
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from config.settings import SUPPLY_DEMAND_BALANCE_TOLERANCE
from data.loaders import load_coprocessing_caps, load_feedstock_bundles
from modules.supply_model import SupplyModel
from schemas.demand_schema import DemandMatrix
from schemas.expansion_schema import CapacityExpansionResult
from schemas.feedstock_schema import RegionalFeedstockBundle
from schemas.supply_schema import CapacityState, ExpansionDecision
from utils.logging_config import get_logger

logger = get_logger("capacity_expansion")


class CapacityExpansionModule:
    """
    Wraps SupplyModel to present a single run() entry point.

    Responsibilities:
      1. Assess demand gap (demand − effective supply by region).
      2. If any gap > 0: solve least-cost expansion LP → new plants.
      3. Compute supply_meets_demand flag for the gating logic.
      4. Return (CapacityExpansionResult, updated CapacityState).
    """

    def __init__(self, supply_model: Optional[SupplyModel] = None):
        self._sm = supply_model or SupplyModel()

    def run(
        self,
        demand_matrix: DemandMatrix,
        capacity_state: CapacityState,
        year: int,
        feedstock_bundles: Optional[List[RegionalFeedstockBundle]] = None,
    ) -> Tuple[CapacityExpansionResult, CapacityState]:
        """
        Execute the expansion pipeline for one year.

        Parameters
        ----------
        demand_matrix    : full DemandMatrix (CORSIA-suppressed records already applied)
        capacity_state   : current CapacityState (plants online through this year)
        year             : model year being processed
        feedstock_bundles: pre-loaded bundles; loaded from CSV if None

        Returns
        -------
        (CapacityExpansionResult, updated CapacityState)
            The returned CapacityState includes any new endogenous plants.
        """
        if feedstock_bundles is None:
            feedstock_bundles = load_feedstock_bundles(year)

        gaps = self._sm.assess_gap(demand_matrix, capacity_state, year)

        if any(g > 0 for g in gaps.values()):
            coprocessing_caps = load_coprocessing_caps()
            expansion = self._sm.build_expansion_lp(
                gaps, feedstock_bundles, year,
                existing_capacity=capacity_state,
                coprocessing_caps=coprocessing_caps,
            )
            if expansion.solver_status != "infeasible":
                capacity_state = self._sm.apply_expansion(capacity_state, expansion)
            else:
                logger.warning(
                    "Year %d: expansion LP infeasible — proceeding with available capacity. "
                    "Market clearing may be skipped if supply < demand.", year
                )
        else:
            expansion = ExpansionDecision(
                year=year,
                new_plants=[],
                npv_cost_usd=0.0,
                solver_status="not_needed",
                shadow_prices={},
                build_triggered=False,
            )

        effective_supply = capacity_state.effective_supply_by_region(self._sm.utilization)
        demand_by_region = demand_matrix.volume_by_region(year)

        # Per-region shortfall is kept for reporting, but the gating decision
        # ("did the LP build enough?") is now GLOBAL — capacity is built where
        # it is cheapest worldwide and the market-clearing step routes it via
        # trade flows. A per-region shortfall is normal and does not block the
        # clearing step.
        shortfall_by_region: dict = {}
        for region, demand_vol in demand_by_region.items():
            supply_vol = effective_supply.get(region, 0.0)
            shortfall_by_region[region] = round(max(0.0, demand_vol - supply_vol), 8)

        global_demand = sum(demand_by_region.values())
        global_supply = sum(effective_supply.values())
        global_shortfall = max(0.0, global_demand - global_supply)
        supply_meets_demand = global_shortfall <= SUPPLY_DEMAND_BALANCE_TOLERANCE
        warning_message = (
            f"Year {year}: global supply shortfall = {global_shortfall:.4f} MT "
            f"(supply={global_supply:.4f}, demand={global_demand:.4f})"
            if not supply_meets_demand else ""
        )
        if warning_message:
            logger.warning(warning_message)

        result = CapacityExpansionResult(
            year=year,
            expansion_decision=expansion,
            supply_meets_demand=supply_meets_demand,
            supply_by_region={r: round(v, 8) for r, v in effective_supply.items()},
            demand_by_region={r: round(v, 8) for r, v in demand_by_region.items()},
            shortfall_by_region=shortfall_by_region,
            warning_message=warning_message,
        )

        logger.info(
            "Year %d — expansion complete: supply_meets_demand=%s, "
            "new_plants=%d, status=%s",
            year,
            supply_meets_demand,
            len(expansion.new_plants),
            expansion.solver_status,
        )
        return result, capacity_state

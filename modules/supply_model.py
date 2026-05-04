"""
Module 2 — Supply & Capacity Expansion
=======================================
Manages deterministic (committed) capacity and triggers a least-cost
Pyomo LP when demand exceeds available supply.

LP formulation
--------------
Sets   : R = regions with demand gap > 0
         P = SAF conversion pathways
         F = feedstock types

Vars   : x[r,p] ∈ ℝ≥0   new capacity built in region r via pathway p (MT/yr)

Obj    : min  Σ_{r,p}  cost_coeff[r,p] × x[r,p]
         where cost_coeff = annualised_capex + opex  (USD / MT/yr capacity)

C1  Demand satisfaction  :  Σ_p  x[r,p] × η  ≥  gap[r]        ∀ r ∈ R
                            (η = utilization factor; dual → shadow price)
C2  Feedstock availability:  Σ_p  fi[p,f] × x[r,p]  ≤  avail[r,f]  ∀ r,f
"""

from __future__ import annotations

import os
from copy import deepcopy
from typing import Dict, List, Optional

import pyomo.environ as pyo
from pyomo.opt import TerminationCondition

from config.settings import (
    DISCOUNT_RATE,
    FEED_INTENSITY,
    FEEDSTOCK_TYPES,
    PROJECT_LIFE_YR,
    REGIONAL_CAPEX,
    REGIONAL_OPEX,
    SAF_PATHWAYS,
    UTILIZATION_FACTOR,
)
from config.solver_config import get_solver
from data.loaders import load_committed_capacity, load_feedstock_bundles
from schemas.feedstock_schema import RegionalFeedstockBundle
from schemas.supply_schema import CapacityState, ExpansionDecision, PlantRecord
from schemas.demand_schema import DemandMatrix
from utils.economics import annualised_total_cost, crf
from utils.logging_config import get_logger

logger = get_logger("supply_model")

_NEW_PLANT_THRESHOLD = 1e-4   # MT/yr — ignore LP solutions below this


class SupplyModel:
    """Least-cost capacity expansion module."""

    def __init__(
        self,
        committed_capacity_path: str = None,
        feedstock_path: str = None,
        utilization: float = UTILIZATION_FACTOR,
        discount_rate: float = DISCOUNT_RATE,
        project_life: int = PROJECT_LIFE_YR,
    ):
        self.committed_path = committed_capacity_path
        self.feedstock_path = feedstock_path
        self.utilization = utilization
        self.discount_rate = discount_rate
        self.project_life = project_life

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def load_committed_capacity(self, year: int) -> CapacityState:
        """Return all deterministic plants online by `year`."""
        return load_committed_capacity(year, path=self.committed_path)

    def load_feedstock_bundles(self, year: int) -> List[RegionalFeedstockBundle]:
        return load_feedstock_bundles(year, path=self.feedstock_path)

    def assess_gap(
        self,
        demand: DemandMatrix,
        capacity: CapacityState,
        year: int,
    ) -> Dict[str, float]:
        """
        Return {region: gap_mt} where gap > 0 means demand exceeds effective supply.
        Negative values (surplus) are returned as-is for reporting; only positive
        gaps trigger the LP.
        """
        effective = capacity.effective_supply_by_region(self.utilization)
        demand_by_region = demand.volume_by_region(year)

        gaps: Dict[str, float] = {}
        all_regions = set(effective) | set(demand_by_region)
        for region in all_regions:
            d = demand_by_region.get(region, 0.0)
            s = effective.get(region, 0.0)
            gaps[region] = round(d - s, 8)

        logger.info(
            "Year %d — gap assessment: %s",
            year,
            {r: f"{g:+.3f} MT" for r, g in gaps.items()},
        )
        return gaps

    def build_expansion_lp(
        self,
        gaps: Dict[str, float],
        feedstock_bundles: List[RegionalFeedstockBundle],
        year: int,
        regional_capex: Dict[str, Dict[str, float]] = None,
        regional_opex: Dict[str, Dict[str, float]] = None,
    ) -> ExpansionDecision:
        """
        Solve a least-cost capacity expansion LP.
        Only called when at least one region has gap > 0.

        Returns ExpansionDecision with new_plants, NPV cost, and shadow prices.
        If the LP is infeasible (feedstock constraints too tight), returns
        a warning decision rather than raising.
        """
        regions_with_gap = [r for r, g in gaps.items() if g > 0]
        if not regions_with_gap:
            return ExpansionDecision(
                year=year, new_plants=[], npv_cost_usd=0.0,
                solver_status="not_needed", shadow_prices={}, build_triggered=False,
            )

        capex_table = regional_capex or REGIONAL_CAPEX
        opex_table  = regional_opex  or REGIONAL_OPEX
        avail = self._feedstock_avail_lookup(feedstock_bundles)

        logger.info("Year %d — building expansion LP for regions: %s", year, regions_with_gap)

        m = pyo.ConcreteModel(name=f"CapExpansion_{year}")

        m.R = pyo.Set(initialize=regions_with_gap)
        m.P = pyo.Set(initialize=SAF_PATHWAYS)
        m.F = pyo.Set(initialize=FEEDSTOCK_TYPES)

        m.x = pyo.Var(m.R, m.P, within=pyo.NonNegativeReals)

        # Cost coefficients: annualised CAPEX + OPEX per unit capacity
        cost_coeff: Dict[tuple, float] = {}
        for r in regions_with_gap:
            r_capex = capex_table.get(r, capex_table.get("ROW", {}))
            r_opex  = opex_table.get(r,  opex_table.get("ROW",  {}))
            for p in SAF_PATHWAYS:
                cost_coeff[(r, p)] = annualised_total_cost(
                    r_capex.get(p, 2000.0),
                    r_opex.get(p, 600.0),
                    self.discount_rate,
                    self.project_life,
                )

        def obj_rule(m):
            return sum(cost_coeff[(r, p)] * m.x[r, p] for r in m.R for p in m.P)

        m.obj = pyo.Objective(rule=obj_rule, sense=pyo.minimize)

        # C1: demand satisfaction (+1e-3 buffer ensures effective supply > demand
        # after utilization factor, preventing floating-point infeasibility in the
        # downstream equilibrium LP)
        def demand_rule(m, r):
            return (
                sum(m.x[r, p] * self.utilization for p in m.P)
                >= gaps[r] + 1e-3
            )
        m.demand_satisfaction = pyo.Constraint(m.R, rule=demand_rule)

        # C2: feedstock availability — only when intensity > 0
        def feedstock_rule(m, r, f):
            lhs = sum(
                FEED_INTENSITY.get(p, {}).get(f, 0.0) * m.x[r, p]
                for p in m.P
                if FEED_INTENSITY.get(p, {}).get(f, 0.0) > 0
            )
            rhs = avail.get(r, {}).get(f, 0.0)
            if isinstance(lhs, (int, float)) and lhs == 0:
                return pyo.Constraint.Skip   # no pathway uses this feedstock in this region
            return lhs <= rhs
        m.feedstock_availability = pyo.Constraint(m.R, m.F, rule=feedstock_rule)

        # Activate dual suffix so GLPK returns shadow prices
        m.dual = pyo.Suffix(direction=pyo.Suffix.IMPORT)

        solver, opts = get_solver()
        results = solver.solve(m, options=opts, tee=False)

        tc = results.solver.termination_condition
        status_str = str(tc)

        # GLPK can return `other` when it cannot find a feasible solution;
        # check whether the objective has a value to distinguish this from
        # genuinely unexpected statuses (e.g. time-limit with partial solution).
        _INFEASIBLE = {TerminationCondition.infeasible, TerminationCondition.infeasibleOrUnbounded}
        _OK         = {TerminationCondition.optimal, TerminationCondition.feasible}

        try:
            obj_val = pyo.value(m.obj)
        except Exception:
            obj_val = None

        no_solution = obj_val is None or tc in _INFEASIBLE

        if no_solution:
            msg = (
                f"Year {year}: LP infeasible for regions {regions_with_gap}. "
                "Feedstock constraints may be too tight to satisfy demand gap. "
                "Consider relaxing feedstock availability or importing from other regions."
            )
            logger.warning(msg)
            return ExpansionDecision(
                year=year, new_plants=[], npv_cost_usd=0.0,
                solver_status="infeasible", shadow_prices={},
                build_triggered=True, warning_message=msg,
            )

        if tc not in _OK:
            msg = (
                f"Year {year}: LP returned status '{tc}' but has a solution value "
                f"({obj_val:.2f}). Proceeding with caution."
            )
            logger.warning(msg)

        new_plants = self._extract_plants(m, year, capex_table, opex_table)
        shadow_prices = self._extract_shadow_prices(m, regions_with_gap)
        obj_val = pyo.value(m.obj)
        npv_cost = obj_val / crf(self.discount_rate, self.project_life)

        logger.info(
            "Year %d — LP solved: status=%s, new_plants=%d, NPV_cost=$%.1fM",
            year, status_str, len(new_plants), npv_cost / 1e6,
        )
        return ExpansionDecision(
            year=year, new_plants=new_plants, npv_cost_usd=npv_cost,
            solver_status=status_str, shadow_prices=shadow_prices, build_triggered=True,
        )

    def apply_expansion(
        self, state: CapacityState, decision: ExpansionDecision
    ) -> CapacityState:
        """Return a new CapacityState with endogenous plants appended."""
        if not decision.new_plants:
            return state
        updated = CapacityState(
            year=state.year,
            plants=state.plants + decision.new_plants,
        )
        logger.info(
            "Year %d — capacity updated: %d total plants (+%d new)",
            state.year, len(updated.plants), len(decision.new_plants),
        )
        return updated

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _feedstock_avail_lookup(
        bundles: List[RegionalFeedstockBundle],
    ) -> Dict[str, Dict[str, float]]:
        return {b.region: {f.feedstock_type: f.max_available_mt for f in b.feedstocks} for b in bundles}

    def _extract_plants(
        self,
        m: pyo.ConcreteModel,
        year: int,
        capex_table: Dict,
        opex_table: Dict,
    ) -> List[PlantRecord]:
        plants = []
        for r in m.R:
            for p in m.P:
                capacity = pyo.value(m.x[r, p])
                if capacity is None or capacity < _NEW_PLANT_THRESHOLD:
                    continue
                r_capex = capex_table.get(r, capex_table.get("ROW", {}))
                r_opex  = opex_table.get(r,  opex_table.get("ROW",  {}))
                plants.append(PlantRecord(
                    plant_id=f"ENDO_{year}_{r}_{p}_{len(plants):02d}",
                    region=r,
                    pathway=p,
                    capacity_mt_yr=round(capacity, 6),
                    online_year=year,
                    capex_usd_per_mt=r_capex.get(p, 2000.0),
                    opex_usd_per_mt=r_opex.get(p, 600.0),
                    feedstock_intensity={
                        f: FEED_INTENSITY.get(p, {}).get(f, 0.0)
                        for f in FEEDSTOCK_TYPES
                        if FEED_INTENSITY.get(p, {}).get(f, 0.0) > 0
                    },
                    is_deterministic=False,
                ))
        return plants

    @staticmethod
    def _extract_shadow_prices(
        m: pyo.ConcreteModel,
        regions_with_gap: List[str],
    ) -> Dict[str, float]:
        prices: Dict[str, float] = {}
        for r in regions_with_gap:
            try:
                val = m.dual.get(m.demand_satisfaction[r])
                prices[r] = float(val) if val is not None else 0.0
            except Exception:
                prices[r] = 0.0
        return prices

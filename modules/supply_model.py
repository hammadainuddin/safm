"""
Module 2 — Supply & Capacity Expansion
=======================================
Manages deterministic (committed) capacity and triggers a least-cost
Pyomo LP when demand exceeds available supply.

LP formulation
--------------
Sets   : R = ALL regions (region-agnostic siting — LP picks the cheapest)
         P = SAF conversion pathways
         F = feedstock types

Vars   : x[r,p] ∈ ℝ≥0   new capacity built in region r via pathway p (MT/yr)

Obj    : min  Σ_{r,p}  cost_coeff[r,p] × x[r,p]
         where cost_coeff = annualised_capex + opex  (USD / MT/yr capacity)

C1  Global demand        :  Σ_{r,p}  x[r,p] × η  ≥  Σ_r gap[r]
                            (single dual → global shadow price)
C2  Feedstock availability:  Σ_p  fi[p,f] × x[r,p]  ≤  avail[r,f]  ∀ r,f
C3  Refinery co-proc cap :  x[r, "Co-processing"]  ≤  cap[r] − existing[r]   ∀ r

Inter-regional trade flows are resolved downstream in the market-clearing
step (PriceQuantityClearing), so this LP does NOT pin capacity to the
region that has demand — it builds where it is cheapest globally.
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
    REGIONS,
    SAF_PATHWAYS,
    UTILIZATION_FACTOR,
)
from config.solver_config import get_solver
from data.loaders import load_committed_capacity, load_coprocessing_caps, load_feedstock_bundles
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
        existing_capacity: Optional[CapacityState] = None,
        coprocessing_caps: Optional[Dict[str, float]] = None,
        wtp_dict: Optional[Dict[str, float]] = None,
        demand_by_region: Optional[Dict[str, float]] = None,
        transport_costs: Optional[Dict[tuple, float]] = None,
    ) -> ExpansionDecision:
        """
        Solve a least-cost capacity expansion LP.
        Only called when at least one region has gap > 0.

        Returns ExpansionDecision with new_plants, NPV cost, and shadow prices.
        If the LP is infeasible (feedstock constraints too tight), returns
        a warning decision rather than raising.
        """
        # Net global gap (NOT the sum of positive per-region gaps). With
        # region-agnostic siting, supply in a surplus region can ship to a
        # deficit region via trade flows, so the LP only needs to cover the
        # aggregate net deficit. Summing positive gaps double-counts when
        # some regions are in surplus and others are short.
        total_gap = max(0.0, sum(gaps.values()))
        if total_gap <= 0:
            return ExpansionDecision(
                year=year, new_plants=[], npv_cost_usd=0.0,
                solver_status="not_needed", shadow_prices={}, build_triggered=False,
            )

        capex_table = regional_capex or REGIONAL_CAPEX
        opex_table  = regional_opex  or REGIONAL_OPEX
        avail = self._feedstock_avail_lookup(feedstock_bundles)

        # The LP is region-agnostic: it can place new capacity in ANY region,
        # not just the ones with a local gap. Inter-regional trade flows in the
        # market clearing step then route built capacity to demand. This way
        # the LP picks the genuinely cheapest (region, pathway) globally.
        all_regions = list(REGIONS)

        logger.info(
            "Year %d — building expansion LP: total gap = %.4f MT, candidate regions = %s",
            year, total_gap, all_regions,
        )

        m = pyo.ConcreteModel(name=f"CapExpansion_{year}")

        m.R = pyo.Set(initialize=all_regions)
        m.P = pyo.Set(initialize=SAF_PATHWAYS)
        m.F = pyo.Set(initialize=FEEDSTOCK_TYPES)

        m.x = pyo.Var(m.R, m.P, within=pyo.NonNegativeReals)

        # Cost coefficients: annualised CAPEX + OPEX per unit capacity, for every
        # (region, pathway).
        cost_coeff: Dict[tuple, float] = {}
        lcosaf_by_rp: Dict[tuple, float] = {}
        for r in all_regions:
            r_capex = capex_table.get(r, capex_table.get("ROW", {}))
            r_opex  = opex_table.get(r,  opex_table.get("ROW",  {}))
            for p in SAF_PATHWAYS:
                cost_coeff[(r, p)] = annualised_total_cost(
                    r_capex.get(p, 2000.0),
                    r_opex.get(p, 600.0),
                    self.discount_rate,
                    self.project_life,
                )
                # LCOSAF (USD/MT SAF) for the WTP filter on flows.
                lcosaf_by_rp[(r, p)] = cost_coeff[(r, p)] / self.utilization

        # ── Dispatch-aware integration (optional) ────────────────────────────
        # If the caller passes WTP, demand, and transport data, the LP is solved
        # jointly with flow variables f[r,p,d] and a WTP filter — so it only
        # builds capacity that will actually clear in the downstream market step.
        # Otherwise it falls back to the simpler "total effective capacity ≥
        # total gap" formulation (used by unit tests and any caller that does
        # not supply WTP info).
        use_integrated = (
            wtp_dict is not None
            and demand_by_region is not None
            and transport_costs is not None
        )

        if use_integrated:
            # Existing effective supply per (region, pathway) cohort.
            existing_eff_by_rp: Dict[tuple, float] = {}
            if existing_capacity is not None:
                for plant in existing_capacity.plants:
                    key = (plant.region, plant.pathway)
                    existing_eff_by_rp[key] = (
                        existing_eff_by_rp.get(key, 0.0)
                        + plant.capacity_mt_yr * self.utilization
                    )

            # WTP filter: a flow (r → d via pathway p) is only feasible when the
            # delivered cost is at or below the destination's WTP.
            feasible_flows = []
            for r in all_regions:
                for p in SAF_PATHWAYS:
                    lc = lcosaf_by_rp[(r, p)]
                    for d in all_regions:
                        t = transport_costs.get((r, d), 0.0)
                        if lc + t <= wtp_dict.get(d, 0.0) + 1e-6:
                            feasible_flows.append((r, p, d))

            m.flow_idx = pyo.Set(initialize=feasible_flows, dimen=3)
            m.f = pyo.Var(m.flow_idx, within=pyo.NonNegativeReals)
            # Unmet demand (falls to CORSIA offset): penalty = destination WTP,
            # so the LP only chooses offset when no plant can serve it cheaper.
            m.u = pyo.Var(m.R, within=pyo.NonNegativeReals)

            def obj_rule(m):
                build_cost = sum(cost_coeff[(r, p)] * m.x[r, p] for r in m.R for p in m.P)
                # Light tie-breaker so the LP routes flows along the cheapest
                # transport corridor (does not change the build decision).
                transport_tiebreak = 1e-3 * sum(
                    transport_costs.get((r, d), 0.0) * m.f[r, p, d]
                    for (r, p, d) in feasible_flows
                )
                offset_penalty = sum(wtp_dict.get(d, 0.0) * m.u[d] for d in m.R)
                return build_cost + transport_tiebreak + offset_penalty
            m.obj = pyo.Objective(rule=obj_rule, sense=pyo.minimize)

            # Supply per (region, pathway): cohort outflow ≤ existing eff + new eff.
            def supply_rule(m, r, p):
                outflow = sum(m.f[r, p, d] for d in m.R if (r, p, d) in m.flow_idx)
                inflow_supply = (
                    existing_eff_by_rp.get((r, p), 0.0)
                    + m.x[r, p] * self.utilization
                )
                # If no feasible flow exists from this cohort, the LP must not
                # build it (would be pure waste) — set x[r,p] = 0 implicitly.
                if not any((r, p, d) in m.flow_idx for d in m.R):
                    return m.x[r, p] == 0
                return outflow <= inflow_supply
            m.supply_cohort = pyo.Constraint(m.R, m.P, rule=supply_rule)

            # Demand balance per destination: inflow + offset = demand.
            def demand_rule(m, d):
                inflow = sum(
                    m.f[r, p, d] for r in m.R for p in m.P
                    if (r, p, d) in m.flow_idx
                )
                return inflow + m.u[d] >= demand_by_region.get(d, 0.0)
            m.demand_satisfaction = pyo.Constraint(m.R, rule=demand_rule)

        else:
            # Legacy formulation: single global demand constraint, no dispatch
            # coupling. Preserved so unit tests that pass only (gaps, bundles)
            # still work without changes.
            def obj_rule(m):
                return sum(cost_coeff[(r, p)] * m.x[r, p] for r in m.R for p in m.P)
            m.obj = pyo.Objective(rule=obj_rule, sense=pyo.minimize)

            def demand_rule(m):
                return (
                    sum(m.x[r, p] * self.utilization for r in m.R for p in m.P)
                    >= total_gap + 1e-3
                )
            m.demand_satisfaction = pyo.Constraint(rule=demand_rule)

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

        # C3: co-processing capacity cap (refinery-throughput limit).
        # Co-processing SAF is physically constrained by the host refinery's
        # middle-distillate throughput (typically 5–10%). Includes any existing
        # committed Co-processing capacity already deployed in the region.
        if coprocessing_caps:
            existing_coprocess: Dict[str, float] = {}
            if existing_capacity is not None:
                for plant in existing_capacity.plants:
                    if plant.pathway == "Co-processing":
                        existing_coprocess[plant.region] = (
                            existing_coprocess.get(plant.region, 0.0) + plant.capacity_mt_yr
                        )

            def coprocess_rule(m, r):
                cap_r = coprocessing_caps.get(r)
                if cap_r is None or "Co-processing" not in SAF_PATHWAYS:
                    return pyo.Constraint.Skip
                headroom = max(0.0, cap_r - existing_coprocess.get(r, 0.0))
                return m.x[r, "Co-processing"] <= headroom
            m.coprocessing_cap = pyo.Constraint(m.R, rule=coprocess_rule)

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
                f"Year {year}: global expansion LP infeasible (total gap {total_gap:.3f} MT). "
                "Feedstock or refinery-cap constraints may be too tight across all regions. "
                "Consider relaxing feedstock availability or refinery co-processing caps."
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
        shadow_prices = self._extract_shadow_prices(m)
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
    def _extract_shadow_prices(m: pyo.ConcreteModel) -> Dict[str, float]:
        """
        Return the dual values of the demand-satisfaction constraint.

        - Integrated LP: demand_satisfaction is indexed by destination region
          and we return one dual per region.
        - Legacy LP: demand_satisfaction is a single global constraint and we
          return {"global": dual}.
        """
        try:
            constraint = m.demand_satisfaction
            if constraint.is_indexed():
                prices: Dict[str, float] = {}
                for d in constraint:
                    val = m.dual.get(constraint[d])
                    prices[str(d)] = float(val) if val is not None else 0.0
                return prices
            val = m.dual.get(constraint)
            return {"global": float(val) if val is not None else 0.0}
        except Exception:
            return {}

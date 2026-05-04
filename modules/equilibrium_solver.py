"""
Module 3 — Global Trade & Market Pricing (Spatial Equilibrium Core)
====================================================================
Implements a Takayama-Judge spatial equilibrium model, linearised as a
minimum-cost flow LP.  Regional clearing prices emerge as LP dual variables
on the demand-satisfaction constraints.

LP formulation
--------------
Sets   : I = supply regions  (all regions with effective_supply > 0)
         J = demand regions   (all regions with demand > 0)
         A = all (i, j) arcs  (I × J, including domestic i = j)

Vars   : q[i,j] ∈ ℝ≥0   SAF traded from i to j in year t (MT)

Obj    : min  Σ_{i,j}  [sc[i] + tc[i,j]] × q[i,j]
         sc[i] = capacity-weighted average OPEX in region i (USD/MT)
         tc[i,j] = transport cost on arc (i,j), 0 when i = j

C1  Supply balance   :  Σ_j  q[i,j]  ≤  effective_supply[i]   ∀ i
                        dual → π_i  (opportunity cost of supply in i)
C2  Demand satisfied :  Σ_i  q[i,j]  ≥  demand[j]             ∀ j
                        dual → λ_j  (market-clearing price in j)

Spatial equilibrium conditions (complementary slackness at optimum)
    λ_j - λ_i ≤ tc[i,j]            (no profitable arbitrage on zero-flow arc)
    λ_j - λ_i = sc[i] + tc[i,j]    (price difference equals cost on active arc)

Pricing regime layer (applied post-clearing)
--------------------------------------------
Regulated (ReFuelEU):
    p[j] = λ_j + mandate_premium[j] + carbon_offset[j]
    mandate_premium = mandate_fraction × penalty_usd_per_mt_saf
    carbon_offset   = carbon_tax_usd_per_tco2 × lifecycle_ci_reduction_tco2_per_mt_saf

Voluntary / Cost-Plus:
    p[j] = jet_fuel_price[j] + saf_green_premium[j]
            + margin_fraction × (avg_supply_cost[j] + avg_transport_cost[j])
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pyomo.environ as pyo
from pyomo.opt import TerminationCondition

from config.solver_config import get_solver
from data.loaders import load_regulatory_params, load_transport_costs
from schemas.demand_schema import DemandMatrix
from schemas.equilibrium_schema import (
    MarketClearingResult,
    RegionalPrice,
    TradeFlow,
)
from schemas.supply_schema import CapacityState
from utils.logging_config import get_logger

logger = get_logger("equilibrium_solver")

_TRADE_THRESHOLD = 1e-5   # MT; flows below this are treated as zero
_HIGH_COST       = 1e6    # USD/MT; placeholder for regions with no supply plants


class EquilibriumSolver:
    """Spatial equilibrium market-clearing solver with pricing regime overlay."""

    def __init__(
        self,
        transport_cost_path: str = None,
        regulatory_params_path: str = None,
    ):
        self._tc_path      = transport_cost_path
        self._reg_path     = regulatory_params_path
        self._tc_cache: Optional[Dict[Tuple[str, str], float]] = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def clear_market(
        self,
        demand: DemandMatrix,
        capacity: CapacityState,
        year: int,
    ) -> MarketClearingResult:
        """
        Run the spatial equilibrium LP for `year` and return a
        fully-populated MarketClearingResult.
        """
        regions          = sorted(set(r.region for r in demand.get_year(year)))
        tc               = self._transport_costs()
        supply_costs     = self._compute_supply_costs(capacity, regions)
        effective_supply = capacity.effective_supply_by_region()
        demand_by_region = demand.volume_by_region(year)

        logger.info(
            "Year %d — clearing market: regions=%s, total_demand=%.3f MT, total_supply=%.3f MT",
            year, regions,
            sum(demand_by_region.values()),
            sum(effective_supply.get(r, 0.0) for r in regions),
        )

        m = self._build_lp(regions, tc, supply_costs, effective_supply, demand_by_region, year)

        solver, opts = get_solver()
        results = solver.solve(m, options=opts, tee=False)
        tc_cond = results.solver.termination_condition

        try:
            obj_val = pyo.value(m.obj)
        except Exception:
            obj_val = None

        if obj_val is None or tc_cond in (
            TerminationCondition.infeasible,
            TerminationCondition.infeasibleOrUnbounded,
        ):
            logger.error(
                "Year %d — equilibrium LP infeasible (status=%s). "
                "Check that expansion step covered demand adequately.",
                year, tc_cond,
            )
            return MarketClearingResult(
                year=year, trade_flows=[], prices=[],
                total_saf_traded_mt=0.0, total_saf_produced_mt=0.0,
                market_balanced=False, solver_status="infeasible",
                objective_value=0.0,
            )

        # -- Extract results -----------------------------------------------
        shadow_prices = self._extract_shadow_prices(m, regions)
        trade_flows   = self._extract_trade_flows(m, year, tc, regions)

        total_produced  = sum(effective_supply.get(r, 0.0) for r in regions)
        total_traded    = sum(
            f.volume_mt for f in trade_flows
            if f.origin_region != f.destination_region
        )

        # -- Apply pricing regime overlay ----------------------------------
        pricing_params = load_regulatory_params(year, path=self._reg_path)
        avg_transport  = self._avg_import_transport_cost(trade_flows, regions)
        prices = self._apply_pricing_regimes(
            shadow_prices, supply_costs, avg_transport, pricing_params, year, regions
        )

        balanced = all(
            abs(
                sum(f.volume_mt for f in trade_flows if f.destination_region == j)
                - demand_by_region.get(j, 0.0)
            ) < 1e-3
            for j in regions
        )

        logger.info(
            "Year %d — market cleared: status=%s, traded=%.3f MT, balanced=%s",
            year, str(tc_cond), total_traded, balanced,
        )
        return MarketClearingResult(
            year=year, trade_flows=trade_flows, prices=prices,
            total_saf_traded_mt=total_traded,
            total_saf_produced_mt=total_produced,
            market_balanced=balanced,
            solver_status=str(tc_cond),
            objective_value=float(obj_val),
        )

    # ------------------------------------------------------------------
    # LP construction
    # ------------------------------------------------------------------

    def _build_lp(
        self,
        regions: List[str],
        tc: Dict[Tuple[str, str], float],
        supply_costs: Dict[str, float],
        effective_supply: Dict[str, float],
        demand_by_region: Dict[str, float],
        year: int,
    ) -> pyo.ConcreteModel:

        arcs = [(i, j) for i in regions for j in regions]

        m = pyo.ConcreteModel(name=f"SpatialEquilibrium_{year}")
        m.I = pyo.Set(initialize=regions)
        m.J = pyo.Set(initialize=regions)
        m.A = pyo.Set(initialize=arcs)

        m.q = pyo.Var(m.A, within=pyo.NonNegativeReals)

        def obj_rule(m_):
            return sum(
                (supply_costs.get(i, 0.0) + tc.get((i, j), _HIGH_COST)) * m_.q[i, j]
                for i, j in arcs
            )
        m.obj = pyo.Objective(rule=obj_rule, sense=pyo.minimize)

        def supply_rule(m_, i):
            return sum(m_.q[i, j] for j in m_.J) <= effective_supply.get(i, 0.0)
        m.supply_balance = pyo.Constraint(m.I, rule=supply_rule)

        def demand_rule(m_, j):
            return sum(m_.q[i, j] for i in m_.I) >= demand_by_region.get(j, 0.0)
        m.demand_satisfaction = pyo.Constraint(m.J, rule=demand_rule)

        m.dual = pyo.Suffix(direction=pyo.Suffix.IMPORT)
        return m

    # ------------------------------------------------------------------
    # Shadow price extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_shadow_prices(
        m: pyo.ConcreteModel,
        regions: List[str],
    ) -> Dict[str, float]:
        """
        Extract λ_j (dual on demand_satisfaction[j]) as clearing price.
        For a min LP with ≥ constraint the dual should be ≥ 0;
        take abs() to guard against solver sign conventions.
        """
        prices: Dict[str, float] = {}
        for j in regions:
            try:
                val = m.dual.get(m.demand_satisfaction[j])
                prices[j] = abs(float(val)) if val is not None else 0.0
            except Exception:
                prices[j] = 0.0
        return prices

    # ------------------------------------------------------------------
    # Trade flow extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_trade_flows(
        m: pyo.ConcreteModel,
        year: int,
        tc: Dict[Tuple[str, str], float],
        regions: List[str],
    ) -> List[TradeFlow]:
        flows: List[TradeFlow] = []
        for i in regions:
            for j in regions:
                val = pyo.value(m.q[i, j])
                if val is None or val < _TRADE_THRESHOLD:
                    continue
                flows.append(TradeFlow(
                    year=year,
                    origin_region=i,
                    destination_region=j,
                    volume_mt=round(val, 8),
                    transport_cost_usd_per_mt=tc.get((i, j), 0.0),
                ))
        return flows

    # ------------------------------------------------------------------
    # Pricing regime overlay
    # ------------------------------------------------------------------

    def _apply_pricing_regimes(
        self,
        shadow_prices: Dict[str, float],
        supply_costs: Dict[str, float],
        avg_transport: Dict[str, float],
        pricing_params: Dict[str, dict],
        year: int,
        regions: List[str],
    ) -> List[RegionalPrice]:
        """Apply regulatory or cost-plus pricing over the LP shadow prices."""
        prices: List[RegionalPrice] = []
        for j in regions:
            params  = pricing_params.get(j, {})
            regime  = str(params.get("pricing_regime", "voluntary_cost_plus"))
            sp      = shadow_prices.get(j, 0.0)
            sc      = supply_costs.get(j, 0.0)
            tc_avg  = avg_transport.get(j, 0.0)

            if regime == "regulated_refueleu":
                mandate_frac    = float(params.get("mandate_fraction", 0.0))
                penalty         = float(params.get("penalty_usd_per_mt_saf", 0.0))
                carbon_tax      = float(params.get("carbon_tax_usd_per_tco2", 0.0))
                ci_reduction    = float(params.get("lifecycle_ci_reduction_tco2_per_mt_saf", 2.5))
                mandate_premium = mandate_frac * penalty
                carbon_offset   = carbon_tax * ci_reduction
                clearing        = sp + mandate_premium + carbon_offset
                prices.append(RegionalPrice(
                    year=year, region=j,
                    clearing_price_usd_per_mt=max(0.0, clearing),
                    pricing_regime=regime,
                    supply_cost_usd_per_mt=sc,
                    transport_premium_usd_per_mt=tc_avg,
                    mandate_premium_usd_per_mt=mandate_premium,
                    carbon_offset_usd_per_mt=carbon_offset,
                    margin_usd_per_mt=0.0,
                    shadow_price_usd_per_mt=sp,
                ))

            else:  # voluntary_cost_plus
                jet_price       = float(params.get("jet_fuel_usd_per_mt", 600.0))
                green_premium   = float(params.get("saf_green_premium_usd_per_mt", 150.0))
                margin_frac     = float(params.get("margin_fraction", 0.10))
                margin_usd      = margin_frac * (sc + tc_avg)
                clearing        = jet_price + green_premium + margin_usd
                prices.append(RegionalPrice(
                    year=year, region=j,
                    clearing_price_usd_per_mt=max(0.0, clearing),
                    pricing_regime=regime,
                    supply_cost_usd_per_mt=sc,
                    transport_premium_usd_per_mt=tc_avg,
                    mandate_premium_usd_per_mt=0.0,
                    carbon_offset_usd_per_mt=0.0,
                    margin_usd_per_mt=margin_usd,
                    shadow_price_usd_per_mt=sp,
                ))
        return prices

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _transport_costs(self) -> Dict[Tuple[str, str], float]:
        if self._tc_cache is None:
            self._tc_cache = load_transport_costs(self._tc_path)
        return self._tc_cache

    @staticmethod
    def _compute_supply_costs(
        capacity: CapacityState,
        regions: List[str],
    ) -> Dict[str, float]:
        """Capacity-weighted average OPEX per region (USD/MT produced)."""
        weighted_opex: Dict[str, float] = {}
        total_cap:     Dict[str, float] = {}
        for plant in capacity.plants:
            r = plant.region
            weighted_opex[r] = weighted_opex.get(r, 0.0) + plant.opex_usd_per_mt * plant.capacity_mt_yr
            total_cap[r]     = total_cap.get(r, 0.0) + plant.capacity_mt_yr
        return {
            r: weighted_opex[r] / total_cap[r] if total_cap.get(r, 0.0) > 0 else 0.0
            for r in regions
        }

    @staticmethod
    def _avg_import_transport_cost(
        trade_flows: List[TradeFlow],
        regions: List[str],
    ) -> Dict[str, float]:
        """Volume-weighted average import transport cost per destination region."""
        total_vol: Dict[str, float] = {}
        total_cost: Dict[str, float] = {}
        for f in trade_flows:
            if f.origin_region == f.destination_region:
                continue
            j = f.destination_region
            total_vol[j]  = total_vol.get(j, 0.0)  + f.volume_mt
            total_cost[j] = total_cost.get(j, 0.0) + f.volume_mt * f.transport_cost_usd_per_mt
        return {
            j: total_cost[j] / total_vol[j] if total_vol.get(j, 0.0) > 0 else 0.0
            for j in regions
        }

"""
Price-Quantity Clearing Module
================================
Replaces the Takayama-Judge LP equilibrium solver with a priority-allocation
supply-demand clearing algorithm:

  1. Sort demand regions by WTP (descending) — highest WTP gets priority.
  2. For each demand region: allocate the cheapest available supply on a
     CIF (cost-insurance-freight) basis, i.e. supply_cost + transport to region.
  3. Record trade flows; clearing price = WTP of each served region.
  4. As aggregate supply grows, the marginal buyer's WTP falls, compressing prices
     toward marginal CIF cost (competitive convergence).

Output: MarketClearingResult — identical schema to EquilibriumSolver.clear_market(),
so ModelState and all reporting/CSV writers are unchanged.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from config.settings import MARKET_BALANCE_TOL, UTILIZATION_FACTOR
from data.loaders import load_transport_costs
from schemas.demand_schema import DemandMatrix
from schemas.equilibrium_schema import MarketClearingResult, RegionalPrice, TradeFlow
from schemas.supply_schema import CapacityState
from schemas.wtp_schema import WTPMatrix
from utils.logging_config import get_logger

logger = get_logger("price_quantity_clearing")

_PLACEHOLDER_COST = 1e6   # USD/MT — used when no supply is available in a region


class PriceQuantityClearing:
    """
    Priority supply-allocation clearing.

    Replaces EquilibriumSolver while keeping the same clear_market() signature
    (minus the LP dependency) and returning the same MarketClearingResult.
    """

    def __init__(self, transport_costs_path: str = None):
        self._tc_path = transport_costs_path
        self._tc_cache: Optional[Dict[tuple, float]] = None

    # ── Public interface ─────────────────────────────────────────────────────

    def clear_market(
        self,
        demand: DemandMatrix,
        capacity: CapacityState,
        year: int,
        wtp_matrix: WTPMatrix,
    ) -> MarketClearingResult:
        """
        Clear the SAF market for a single year using priority allocation.

        Parameters
        ----------
        demand      : DemandMatrix (CORSIA-suppressed volumes where applicable)
        capacity    : CapacityState after expansion
        year        : model year
        wtp_matrix  : regional willingness-to-pay from WTPModel

        Returns
        -------
        MarketClearingResult — same schema as EquilibriumSolver output
        """
        tc = self._transport_costs()
        supply_costs  = self._capacity_weighted_opex(capacity)
        supply_avail  = dict(capacity.effective_supply_by_region(UTILIZATION_FACTOR))
        demand_by_region = demand.volume_by_region(year)
        wtp_dict      = wtp_matrix.to_dict()

        trade_flows, marginal_supplier = self._allocate(
            demand_by_region, wtp_dict, supply_avail, supply_costs, tc, year
        )

        prices = self._compute_prices(
            demand_by_region, wtp_dict, trade_flows,
            marginal_supplier, supply_costs, tc, year
        )

        total_traded   = sum(f.volume_mt for f in trade_flows if f.origin_region != f.destination_region)
        total_produced = sum(f.volume_mt for f in trade_flows)
        inflow_totals: Dict[str, float] = {}
        for f in trade_flows:
            inflow_totals[f.destination_region] = inflow_totals.get(f.destination_region, 0.0) + f.volume_mt

        # Regions where physical SAF cannot meet demand — shortfall covered by CORSIA offsets
        offset_demand_mt_by_region: Dict[str, float] = {}
        for r, d in demand_by_region.items():
            if d > MARKET_BALANCE_TOL:
                inflow = inflow_totals.get(r, 0.0)
                shortfall = d - inflow
                if shortfall > MARKET_BALANCE_TOL:
                    offset_demand_mt_by_region[r] = round(shortfall, 6)

        unserved = list(offset_demand_mt_by_region.keys())
        market_balanced = len(unserved) == 0

        logger.info(
            "Year %d — PQ clearing: balanced=%s, produced=%.4f MT, "
            "traded=%.4f MT, corsia_offset=%s",
            year, market_balanced, total_produced, total_traded,
            {r: f"{v:.4f}" for r, v in offset_demand_mt_by_region.items()} or "none",
        )

        return MarketClearingResult(
            year=year,
            trade_flows=trade_flows,
            prices=prices,
            total_saf_traded_mt=round(total_traded, 6),
            total_saf_produced_mt=round(total_produced, 6),
            market_balanced=market_balanced,
            solver_status="optimal" if market_balanced else "partial",
            objective_value=0.0,
            offset_demand_mt_by_region=offset_demand_mt_by_region,
        )

    # ── Allocation algorithm ─────────────────────────────────────────────────

    def _allocate(
        self,
        demand_by_region: Dict[str, float],
        wtp_dict: Dict[str, float],
        supply_avail: Dict[str, float],
        supply_costs: Dict[str, float],
        tc: Dict[tuple, float],
        year: int,
    ) -> Tuple[List[TradeFlow], Dict[str, str]]:
        """
        Priority dispatch:
        - Highest WTP region gets supply first.
        - Within each demand region, supply is dispatched from cheapest CIF source.

        Returns (trade_flows, marginal_supplier_by_demand_region).
        """
        supply_remaining = dict(supply_avail)
        trade_flows: List[TradeFlow] = []
        marginal_supplier: Dict[str, str] = {}   # {demand_region: last supply region used}

        # Sort demand regions by WTP descending
        priority_order = sorted(demand_by_region.keys(), key=lambda r: -wtp_dict.get(r, 0.0))

        for d_region in priority_order:
            demand_remaining = demand_by_region.get(d_region, 0.0)
            if demand_remaining <= MARKET_BALANCE_TOL:
                continue

            # Build list of supply options sorted by CIF cost (cheapest first)
            supply_options = sorted(
                [
                    (s_region, supply_costs.get(s_region, _PLACEHOLDER_COST) + tc.get((s_region, d_region), 0.0))
                    for s_region, vol in supply_remaining.items()
                    if vol > MARKET_BALANCE_TOL
                ],
                key=lambda x: x[1],
            )

            for s_region, cif_cost in supply_options:
                if demand_remaining <= MARKET_BALANCE_TOL:
                    break
                avail = supply_remaining.get(s_region, 0.0)
                if avail <= MARKET_BALANCE_TOL:
                    continue
                vol = min(avail, demand_remaining)
                transport = tc.get((s_region, d_region), 0.0)
                trade_flows.append(TradeFlow(
                    year=year,
                    origin_region=s_region,
                    destination_region=d_region,
                    volume_mt=round(vol, 8),
                    transport_cost_usd_per_mt=transport,
                ))
                supply_remaining[s_region] = avail - vol
                demand_remaining -= vol
                marginal_supplier[d_region] = s_region

        return trade_flows, marginal_supplier

    # ── Price computation ─────────────────────────────────────────────────────

    def _compute_prices(
        self,
        demand_by_region: Dict[str, float],
        wtp_dict: Dict[str, float],
        trade_flows: List[TradeFlow],
        marginal_supplier: Dict[str, str],
        supply_costs: Dict[str, float],
        tc: Dict[tuple, float],
        year: int,
    ) -> List[RegionalPrice]:
        prices: List[RegionalPrice] = []

        # Build inflow by dest_region for served check
        inflow: Dict[str, float] = {}
        for f in trade_flows:
            inflow[f.destination_region] = inflow.get(f.destination_region, 0.0) + f.volume_mt

        # Average transport cost per destination (across all flows to that dest)
        tc_numerator: Dict[str, float] = {}
        tc_denominator: Dict[str, float] = {}
        for f in trade_flows:
            tc_numerator[f.destination_region]   = tc_numerator.get(f.destination_region, 0.0)   + f.transport_cost_usd_per_mt * f.volume_mt
            tc_denominator[f.destination_region] = tc_denominator.get(f.destination_region, 0.0) + f.volume_mt

        for d_region, wtp in wtp_dict.items():
            demand_vol = demand_by_region.get(d_region, 0.0)
            served_vol = inflow.get(d_region, 0.0)
            is_served  = served_vol >= demand_vol - MARKET_BALANCE_TOL

            if not is_served:
                # Demand unmet by physical SAF — falls to CORSIA offset credits
                prices.append(RegionalPrice(
                    year=year, region=d_region,
                    clearing_price_usd_per_mt=0.0,
                    pricing_regime="corsia_offset",
                    shadow_price_usd_per_mt=wtp,
                    supply_cost_usd_per_mt=0.0,
                    transport_premium_usd_per_mt=0.0,
                    mandate_premium_usd_per_mt=0.0,
                    carbon_offset_usd_per_mt=0.0,
                    margin_usd_per_mt=0.0,
                ))
                continue

            # Clearing price = WTP (buyers pay their willingness-to-pay in a
            # capacity-constrained market; price converges to marginal CIF as
            # supply grows relative to demand)
            clearing_price = wtp
            ms = marginal_supplier.get(d_region)
            sc = supply_costs.get(ms, 0.0) if ms else 0.0
            tc_avg = (tc_numerator.get(d_region, 0.0) / tc_denominator[d_region]
                      if tc_denominator.get(d_region, 0.0) > 0 else 0.0)
            margin = max(0.0, clearing_price - sc - tc_avg)

            prices.append(RegionalPrice(
                year=year, region=d_region,
                clearing_price_usd_per_mt=round(clearing_price, 2),
                pricing_regime="wtp_priority_allocation",
                shadow_price_usd_per_mt=round(sc + tc_avg, 2),  # marginal CIF cost
                supply_cost_usd_per_mt=round(sc, 2),
                transport_premium_usd_per_mt=round(tc_avg, 2),
                mandate_premium_usd_per_mt=0.0,
                carbon_offset_usd_per_mt=0.0,
                margin_usd_per_mt=round(margin, 2),
            ))

        return prices

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _capacity_weighted_opex(capacity: CapacityState) -> Dict[str, float]:
        """Capacity-weighted average OPEX (USD/MT) per supply region."""
        num: Dict[str, float] = {}
        den: Dict[str, float] = {}
        for plant in capacity.plants:
            r = plant.region
            num[r] = num.get(r, 0.0) + plant.opex_usd_per_mt * plant.capacity_mt_yr
            den[r] = den.get(r, 0.0) + plant.capacity_mt_yr
        return {r: num[r] / den[r] for r in num if den[r] > 0}

    def _transport_costs(self) -> Dict[tuple, float]:
        if self._tc_cache is None:
            self._tc_cache = load_transport_costs(self._tc_path)
        return self._tc_cache

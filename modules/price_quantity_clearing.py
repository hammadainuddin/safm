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

from config.settings import (
    DISCOUNT_RATE, MARKET_BALANCE_TOL, PROJECT_LIFE_YR, UTILIZATION_FACTOR,
)
from data.loaders import load_domestic_priority_shares, load_transport_costs
from schemas.demand_schema import DemandMatrix
from schemas.equilibrium_schema import MarketClearingResult, RegionalPrice, TradeFlow
from schemas.supply_schema import CapacityState
from schemas.wtp_schema import WTPMatrix
from utils.economics import levelised_cost
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
        self._priority_cache: Optional[Dict[str, float]] = None

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
        domestic_shares = self._domestic_priority_shares()
        supply_costs  = self._capacity_weighted_opex(capacity)
        demand_by_region = demand.volume_by_region(year)
        wtp_dict      = wtp_matrix.to_dict()

        trade_flows, marginal_supplier = self._allocate(
            demand_by_region, wtp_dict, capacity, tc, year, domestic_shares
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

        # Per-region dispatch summary (domestic vs import vs offset).
        served_domestic: Dict[str, float] = {}
        served_import:   Dict[str, float] = {}
        for f in trade_flows:
            if f.origin_region == f.destination_region:
                served_domestic[f.destination_region] = (
                    served_domestic.get(f.destination_region, 0.0) + f.volume_mt
                )
            else:
                served_import[f.destination_region] = (
                    served_import.get(f.destination_region, 0.0) + f.volume_mt
                )

        logger.info(
            "Year %d — PQ clearing: balanced=%s, produced=%.4f MT, "
            "traded=%.4f MT, corsia_offset=%s",
            year, market_balanced, total_produced, total_traded,
            {r: f"{v:.4f}" for r, v in offset_demand_mt_by_region.items()} or "none",
        )
        for d_region in sorted(demand_by_region.keys()):
            d   = demand_by_region.get(d_region, 0.0)
            if d <= MARKET_BALANCE_TOL:
                continue
            dom = served_domestic.get(d_region, 0.0)
            imp = served_import.get(d_region, 0.0)
            off = offset_demand_mt_by_region.get(d_region, 0.0)
            logger.info(
                "  %s: demand=%.4f  domestic=%.4f  import=%.4f  offset=%.4f",
                d_region, d, dom, imp, off,
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
            corsia_offset_price_usd_per_mt=wtp_matrix.corsia_offset_price_usd_per_mt,
        )

    # ── Allocation algorithm ─────────────────────────────────────────────────

    def _allocate(
        self,
        demand_by_region: Dict[str, float],
        wtp_dict: Dict[str, float],
        capacity: CapacityState,
        tc: Dict[tuple, float],
        year: int,
        domestic_shares: Dict[str, float],
    ) -> Tuple[List[TradeFlow], Dict[str, str]]:
        """
        Share-aware two-pass clearing.

        For each plant in region r with effective volume V:
            domestic_pool = V × domestic_share[r]
            export_pool   = V × (1 − domestic_share[r])

        Phase 1 — Domestic clearing. Each region (WTP-desc for stable
                  ordering) consumes its OWN plants' domestic_pool subject
                  to LCOSAF ≤ regional WTP, cheapest LCOSAF first.

        Phase 2 — Imports. For each destination (WTP-desc), build the
                  cross-region candidate pool from each plant's export_pool
                  PLUS any unused domestic_pool remainder (so reserved
                  capacity is not wasted when local demand is already met).
                  Filter by LCOSAF + transport ≤ destination WTP, sort by
                  cheapest CIF, dispatch in that order.

        Returns (trade_flows, marginal_supplier_by_demand_region).
        """
        # ── Pre-compute LCOSAF and per-plant pools ──────────────────────────────
        # Each entry: [lcosaf, region, pathway, dom_remaining, exp_remaining]
        plants: List[List] = []
        for p in capacity.plants:
            lc = levelised_cost(
                p.capex_usd_per_mt, p.opex_usd_per_mt,
                UTILIZATION_FACTOR, DISCOUNT_RATE, PROJECT_LIFE_YR,
            )
            eff_vol = p.capacity_mt_yr * UTILIZATION_FACTOR
            if eff_vol <= MARKET_BALANCE_TOL:
                continue
            share = domestic_shares.get(p.region, 1.0)
            share = max(0.0, min(1.0, share))
            dom = eff_vol * share
            exp = eff_vol - dom
            plants.append([lc, p.region, p.pathway, dom, exp])

        trade_flows: List[TradeFlow] = []
        marginal_supplier: Dict[str, str] = {}
        demand_remaining: Dict[str, float] = {
            r: float(v) for r, v in demand_by_region.items()
        }

        priority_order = sorted(
            demand_by_region.keys(),
            key=lambda r: -wtp_dict.get(r, 0.0),
        )

        # ── PHASE 1: domestic clearing — each region draws on its own pool ──────
        for d_region in priority_order:
            if demand_remaining.get(d_region, 0.0) <= MARKET_BALANCE_TOL:
                continue
            wtp_d = wtp_dict.get(d_region, 0.0)
            domestic = sorted(
                [
                    pl for pl in plants
                    if pl[1] == d_region
                    and pl[0] <= wtp_d
                    and pl[3] > MARKET_BALANCE_TOL
                ],
                key=lambda x: x[0],
            )
            for pl in domestic:
                if demand_remaining[d_region] <= MARKET_BALANCE_TOL:
                    break
                take = min(pl[3], demand_remaining[d_region])
                trade_flows.append(TradeFlow(
                    year=year,
                    origin_region=d_region,
                    destination_region=d_region,
                    volume_mt=round(take, 8),
                    transport_cost_usd_per_mt=0.0,
                    pathway=pl[2],
                ))
                pl[3] -= take
                demand_remaining[d_region] -= take
                marginal_supplier[d_region] = d_region

        # ── PHASE 2: cheapest-CIF allocation across ALL destinations ────────────
        # Each plant's export_pool + unused domestic remainder is available to
        # any destination (including its own region — so a plant whose home
        # market still has unmet demand serves it FIRST at zero transport,
        # before its output ships to a higher-WTP foreign destination).
        # Allocation is greedy by global cheapest CIF, which under transport=0
        # for own-region keeps SAF close to where it was made until local
        # demand is saturated.
        pairs = []
        for pl in plants:
            if pl[3] + pl[4] <= MARKET_BALANCE_TOL:
                continue
            for d_region in demand_by_region:
                if pl[0] > wtp_dict.get(d_region, 0.0):
                    continue
                transport = 0.0 if pl[1] == d_region else tc.get((pl[1], d_region), 0.0)
                cif = pl[0] + transport
                pairs.append((cif, pl, d_region, transport))
        pairs.sort(key=lambda x: x[0])
        for _cif, pl, d_region, transport in pairs:
            if demand_remaining.get(d_region, 0.0) <= MARKET_BALANCE_TOL:
                continue
            avail_now = pl[3] + pl[4]
            if avail_now <= MARKET_BALANCE_TOL:
                continue
            take = min(avail_now, demand_remaining[d_region])
            # Draw from the export pool first; spill into unused domestic
            # remainder only if the export pool is exhausted.
            from_exp = min(take, pl[4])
            from_dom = take - from_exp
            pl[4] -= from_exp
            pl[3] -= from_dom
            trade_flows.append(TradeFlow(
                year=year,
                origin_region=pl[1],
                destination_region=d_region,
                volume_mt=round(take, 8),
                transport_cost_usd_per_mt=transport,
                pathway=pl[2],
            ))
            demand_remaining[d_region] -= take
            marginal_supplier[d_region] = pl[1]

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
                if served_vol > MARKET_BALANCE_TOL:
                    # Partially served — physical SAF did flow to this region.
                    # Clearing price = WTP (same as fully served), reflecting
                    # that buyers still pay their willingness-to-pay for the
                    # SAF that was physically delivered.
                    ms = marginal_supplier.get(d_region)
                    sc = supply_costs.get(ms, 0.0) if ms else 0.0
                    tc_avg = (tc_numerator.get(d_region, 0.0) / tc_denominator[d_region]
                              if tc_denominator.get(d_region, 0.0) > 0 else 0.0)
                    margin = max(0.0, wtp - sc - tc_avg)
                    prices.append(RegionalPrice(
                        year=year, region=d_region,
                        clearing_price_usd_per_mt=round(wtp, 2),
                        pricing_regime="partial_supply",
                        shadow_price_usd_per_mt=round(sc + tc_avg, 2),
                        supply_cost_usd_per_mt=round(sc, 2),
                        transport_premium_usd_per_mt=round(tc_avg, 2),
                        mandate_premium_usd_per_mt=0.0,
                        carbon_offset_usd_per_mt=0.0,
                        margin_usd_per_mt=round(margin, 2),
                    ))
                else:
                    # Completely unserved — no physical SAF at all; falls entirely
                    # to CORSIA offset credits.
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

    def _domestic_priority_shares(self) -> Dict[str, float]:
        """Cached {region: domestic_share}. Missing regions default to 1.0."""
        if self._priority_cache is None:
            self._priority_cache = load_domestic_priority_shares()
        return self._priority_cache

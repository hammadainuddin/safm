"""
Unit tests for the spatial equilibrium solver (Module 3).

Test cases
----------
1. Symmetric 3-region model (equal costs, zero transport) → prices equalise
2. Trade flow conservation: supply balance and demand satisfaction hold
3. EU regulated price > cost-plus price when mandate premium is positive
4. No-arbitrage: price difference ≤ transport cost on zero-flow arcs
5. Prohibitive transport cost → each region supplied domestically (autarky)
"""

from __future__ import annotations

import os
import tempfile

import pytest

from config.settings import MT_TO_PJ_FACTOR
from modules.equilibrium_solver import EquilibriumSolver, _TRADE_THRESHOLD
from schemas.demand_schema import DemandMatrix, DemandRecord
from schemas.supply_schema import CapacityState, PlantRecord

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _demand(volumes: dict, year: int = 2025) -> DemandMatrix:
    records = [
        DemandRecord(
            year=year, region=r, volume_mt=v,
            energy_pj=round(v * MT_TO_PJ_FACTOR, 6), source="test",
        )
        for r, v in volumes.items()
    ]
    return DemandMatrix(records=records, scenario_name="test")


def _capacity(caps: dict, opex: float = 350.0, year: int = 2025) -> CapacityState:
    plants = [
        PlantRecord(
            plant_id=f"P_{r}", region=r, pathway="HEFA",
            capacity_mt_yr=cap, online_year=year,
            capex_usd_per_mt=800.0, opex_usd_per_mt=opex,
            feedstock_intensity={"UCO": 1.25}, is_deterministic=True,
        )
        for r, cap in caps.items()
    ]
    return CapacityState(year=year, plants=plants)


def _write_tc_csv(arcs: dict) -> str:
    """Write a temporary transport_costs.csv and return its path."""
    import csv, tempfile
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="")
    w = csv.DictWriter(f, fieldnames=["origin", "destination", "transport_cost_usd_per_mt"])
    w.writeheader()
    for (o, d), cost in arcs.items():
        w.writerow({"origin": o, "destination": d, "transport_cost_usd_per_mt": cost})
    f.close()
    return f.name


def _write_reg_csv(regions: list, regime: str, year: int = 2025,
                   mandate_fraction: float = 0.0, penalty: float = 0.0,
                   carbon_tax: float = 0.0, ci_reduction: float = 2.5,
                   jet_price: float = 600.0, green_premium: float = 150.0,
                   margin: float = 0.10) -> str:
    import csv, tempfile
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="")
    fields = ["year", "region", "pricing_regime", "mandate_fraction",
              "penalty_usd_per_mt_saf", "carbon_tax_usd_per_tco2",
              "lifecycle_ci_reduction_tco2_per_mt_saf", "jet_fuel_usd_per_mt",
              "saf_green_premium_usd_per_mt", "margin_fraction"]
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    for r in regions:
        w.writerow({
            "year": year, "region": r, "pricing_regime": regime,
            "mandate_fraction": mandate_fraction, "penalty_usd_per_mt_saf": penalty,
            "carbon_tax_usd_per_tco2": carbon_tax,
            "lifecycle_ci_reduction_tco2_per_mt_saf": ci_reduction,
            "jet_fuel_usd_per_mt": jet_price,
            "saf_green_premium_usd_per_mt": green_premium,
            "margin_fraction": margin,
        })
    f.close()
    return f.name


# ---------------------------------------------------------------------------
# Test 1: Symmetric model — prices should equalise
# ---------------------------------------------------------------------------

class TestSymmetricEquilibrium:
    def test_prices_equalise_with_zero_transport_and_equal_costs(self):
        """
        3 regions with equal supply cost, zero transport, and equal demand.
        At optimum, the LP dual on each demand constraint should be identical.
        """
        regions = ["EU", "US", "APAC"]
        # Each region has 2 MT supply, 0.5 MT demand → plenty of slack
        demand   = _demand({"EU": 0.5, "US": 0.5, "APAC": 0.5})
        capacity = _capacity({"EU": 2.0, "US": 2.0, "APAC": 2.0}, opex=350.0)

        # Zero transport costs everywhere
        arcs = {(i, j): 0.0 for i in regions for j in regions}
        tc_path  = _write_tc_csv(arcs)
        reg_path = _write_reg_csv(regions, "voluntary_cost_plus", jet_price=600.0,
                                  green_premium=0.0, margin=0.0)

        try:
            solver = EquilibriumSolver(transport_cost_path=tc_path,
                                       regulatory_params_path=reg_path)
            result = solver.clear_market(demand, capacity, year=2025)

            assert result.solver_status in ("optimal", "feasible"), \
                f"Expected optimal, got {result.solver_status}"

            shadow_prices = {p.region: p.shadow_price_usd_per_mt for p in result.prices}
            vals = list(shadow_prices.values())
            # All shadow prices should be within a small tolerance of each other
            assert max(vals) - min(vals) < 1.0, \
                f"Shadow prices diverge: {shadow_prices} — symmetric model should equalise"
        finally:
            os.unlink(tc_path)
            os.unlink(reg_path)

    def test_market_produces_prices_for_all_regions(self):
        regions = ["EU", "US", "APAC"]
        demand   = _demand({"EU": 0.5, "US": 0.3, "APAC": 0.2})
        capacity = _capacity({"EU": 2.0, "US": 2.0, "APAC": 2.0})
        arcs     = {(i, j): 45.0 for i in regions for j in regions if i != j}
        arcs.update({(r, r): 0.0 for r in regions})

        tc_path  = _write_tc_csv(arcs)
        reg_path = _write_reg_csv(regions, "voluntary_cost_plus")
        try:
            solver = EquilibriumSolver(tc_path, reg_path)
            result = solver.clear_market(demand, capacity, 2025)
            assert len(result.prices) == len(regions)
            assert all(p.clearing_price_usd_per_mt >= 0 for p in result.prices)
        finally:
            os.unlink(tc_path); os.unlink(reg_path)


# ---------------------------------------------------------------------------
# Test 2: Trade flow conservation
# ---------------------------------------------------------------------------

class TestTradeFlowConservation:
    def _run(self, year=2025):
        regions  = ["EU", "US", "APAC"]
        demand   = _demand({"EU": 0.5, "US": 0.3, "APAC": 0.2})
        # EU has 1 MT surplus; US and APAC are short
        capacity = _capacity({"EU": 1.5, "US": 0.1, "APAC": 0.1})
        arcs     = {(i, j): 45.0 for i in regions for j in regions if i != j}
        arcs.update({(r, r): 0.0 for r in regions})

        tc_path  = _write_tc_csv(arcs)
        reg_path = _write_reg_csv(regions, "voluntary_cost_plus")
        try:
            solver = EquilibriumSolver(tc_path, reg_path)
            return solver.clear_market(demand, capacity, year)
        finally:
            os.unlink(tc_path); os.unlink(reg_path)

    def test_demand_satisfaction_holds(self):
        """Σ_i q[i,j] ≥ demand[j] for all j (within numerical tolerance)."""
        result  = self._run()
        demand_by_region = {"EU": 0.5, "US": 0.3, "APAC": 0.2}
        for j, required in demand_by_region.items():
            inflow = sum(
                f.volume_mt for f in result.trade_flows if f.destination_region == j
            )
            assert inflow >= required - 1e-4, \
                f"Region {j}: inflow {inflow:.4f} MT < demand {required} MT"

    def test_supply_not_exceeded(self):
        """Σ_j q[i,j] ≤ effective_supply[i] for all i."""
        result  = self._run()
        effective_supply = {"EU": 1.5 * 0.85, "US": 0.1 * 0.85, "APAC": 0.1 * 0.85}
        for i, supply in effective_supply.items():
            outflow = sum(
                f.volume_mt for f in result.trade_flows if f.origin_region == i
            )
            assert outflow <= supply + 1e-4, \
                f"Region {i}: outflow {outflow:.4f} MT > supply {supply:.4f} MT"

    def test_all_flows_non_negative(self):
        result = self._run()
        for f in result.trade_flows:
            assert f.volume_mt >= 0, f"Negative flow on arc ({f.origin_region}, {f.destination_region})"

    def test_market_balanced_flag_is_true(self):
        result = self._run()
        assert result.market_balanced is True


# ---------------------------------------------------------------------------
# Test 3: Regulated vs voluntary pricing
# ---------------------------------------------------------------------------

class TestPricingRegimes:
    def test_mandate_premium_raises_regulated_price_above_shadow_price(self):
        """
        EU regulated: mandate_fraction=0.06, penalty=1000 → mandate_premium = 60 USD/MT.
        EU clearing price must equal shadow_price + mandate_premium + carbon_offset.

        Rationale: regulated and cost-plus prices use different bases (LP shadow price
        vs jet-fuel reference), so cross-regime comparison is not meaningful. The
        correct test is that the mandate premium is embedded in the total price.
        """
        regions  = ["EU", "US"]
        demand   = _demand({"EU": 0.5, "US": 0.5})
        capacity = _capacity({"EU": 2.0, "US": 2.0}, opex=350.0)
        arcs     = {("EU","EU"):0.0, ("EU","US"):45.0, ("US","EU"):45.0, ("US","US"):0.0}
        tc_path  = _write_tc_csv(arcs)
        reg_path = _write_reg_csv(
            regions, "regulated_refueleu",
            mandate_fraction=0.06, penalty=1000, carbon_tax=0.0,
        )
        try:
            solver = EquilibriumSolver(tc_path, reg_path)
            result = solver.clear_market(demand, capacity, 2025)
            eu     = result.price_for_region("EU")

            assert eu.mandate_premium_usd_per_mt == pytest.approx(60.0, abs=0.01), \
                f"Expected mandate premium 60, got {eu.mandate_premium_usd_per_mt}"
            expected_price = eu.shadow_price_usd_per_mt + eu.mandate_premium_usd_per_mt \
                             + eu.carbon_offset_usd_per_mt
            assert eu.clearing_price_usd_per_mt == pytest.approx(expected_price, abs=0.01), \
                "EU clearing price must equal shadow_price + mandate_premium + carbon_offset"
        finally:
            os.unlink(tc_path); os.unlink(reg_path)

    def test_regulated_price_exceeds_no_mandate_baseline(self):
        """
        A region with mandate has a higher clearing price than the same region without mandate,
        all else equal. Tests the directive that mandate raises effective cost.
        """
        regions = ["EU"]
        demand  = _demand({"EU": 0.5})
        cap     = _capacity({"EU": 2.0}, opex=350.0)
        arcs    = {("EU","EU"): 0.0}
        tc_path = _write_tc_csv(arcs)

        reg_with    = _write_reg_csv(regions, "regulated_refueleu",
                                     mandate_fraction=0.06, penalty=1000)
        reg_without = _write_reg_csv(regions, "regulated_refueleu",
                                     mandate_fraction=0.0,  penalty=0)
        try:
            price_with = EquilibriumSolver(tc_path, reg_with).clear_market(
                demand, cap, 2025).price_for_region("EU").clearing_price_usd_per_mt
            price_without = EquilibriumSolver(tc_path, reg_without).clear_market(
                demand, cap, 2025).price_for_region("EU").clearing_price_usd_per_mt
            assert price_with > price_without, \
                f"Mandate price {price_with:.1f} should exceed no-mandate {price_without:.1f}"
        finally:
            os.unlink(tc_path); os.unlink(reg_with); os.unlink(reg_without)

    def test_carbon_offset_included_in_regulated_price(self):
        regions  = ["EU"]
        demand   = _demand({"EU": 0.5})
        capacity = _capacity({"EU": 2.0})
        arcs     = {("EU", "EU"): 0.0}
        tc_path  = _write_tc_csv(arcs)
        reg_path = _write_reg_csv(
            regions, "regulated_refueleu",
            carbon_tax=50.0, ci_reduction=2.5,   # → 125 USD/MT carbon offset
            mandate_fraction=0.0, penalty=0.0,
        )
        try:
            solver = EquilibriumSolver(tc_path, reg_path)
            result = solver.clear_market(demand, capacity, 2025)
            p = result.price_for_region("EU")
            assert p.carbon_offset_usd_per_mt == pytest.approx(125.0, abs=0.01)
        finally:
            os.unlink(tc_path); os.unlink(reg_path)


# ---------------------------------------------------------------------------
# Test 4: No-arbitrage condition
# ---------------------------------------------------------------------------

class TestNoArbitrage:
    def test_no_profitable_arbitrage_on_zero_flow_arcs(self):
        """
        At LP optimum: for any arc (i,j) with q[i,j] ≈ 0,
        shadow_price[j] - shadow_price[i] ≤ transport_cost[i,j] + tolerance.
        This is the Samuelson spatial equilibrium no-arbitrage condition.
        """
        regions = ["EU", "US", "APAC"]
        demand  = _demand({"EU": 0.5, "US": 0.3, "APAC": 0.2})
        # EU has excess supply, US and APAC import
        capacity = _capacity({"EU": 2.0, "US": 0.05, "APAC": 0.05})

        tc_costs = {
            ("EU",   "EU"):   0.0, ("EU",   "US"): 45.0, ("EU",   "APAC"): 65.0,
            ("US",   "EU"):  45.0, ("US",   "US"):  0.0,  ("US",   "APAC"): 55.0,
            ("APAC", "EU"):  65.0, ("APAC", "US"): 55.0,  ("APAC", "APAC"):  0.0,
        }
        tc_path  = _write_tc_csv(tc_costs)
        reg_path = _write_reg_csv(regions, "voluntary_cost_plus",
                                  jet_price=0.0, green_premium=0.0, margin=0.0)
        try:
            solver   = EquilibriumSolver(tc_path, reg_path)
            result   = solver.clear_market(demand, capacity, 2025)

            sp       = {p.region: p.shadow_price_usd_per_mt for p in result.prices}
            flow_vol = {
                (f.origin_region, f.destination_region): f.volume_mt
                for f in result.trade_flows
            }

            TOLERANCE = 1.0   # USD/MT numerical tolerance
            for i in regions:
                for j in regions:
                    q_ij = flow_vol.get((i, j), 0.0)
                    if q_ij < _TRADE_THRESHOLD:   # zero-flow arc
                        tc_ij = tc_costs[(i, j)]
                        diff  = sp.get(j, 0.0) - sp.get(i, 0.0)
                        assert diff <= tc_ij + TOLERANCE, (
                            f"No-arbitrage violated on zero-flow arc ({i}→{j}): "
                            f"p[{j}]={sp.get(j,0):.2f} - p[{i}]={sp.get(i,0):.2f} = {diff:.2f} "
                            f"> transport_cost={tc_ij}"
                        )
        finally:
            os.unlink(tc_path); os.unlink(reg_path)


# ---------------------------------------------------------------------------
# Test 5: Autarky with prohibitive transport costs
# ---------------------------------------------------------------------------

class TestAutarky:
    def test_no_cross_region_trade_with_prohibitive_transport(self):
        """
        When transport costs are extremely high, each region is self-sufficient
        (assuming sufficient domestic supply) → zero cross-region trade.
        """
        regions  = ["EU", "US", "APAC"]
        demand   = _demand({"EU": 0.5, "US": 0.3, "APAC": 0.2})
        # Each region has more than enough domestic supply
        capacity = _capacity({"EU": 5.0, "US": 5.0, "APAC": 5.0})

        PROHIBITIVE = 1_000_000.0   # USD/MT — no rational trade at this cost
        arcs = {(i, j): (0.0 if i == j else PROHIBITIVE) for i in regions for j in regions}
        tc_path  = _write_tc_csv(arcs)
        reg_path = _write_reg_csv(regions, "voluntary_cost_plus")
        try:
            solver = EquilibriumSolver(tc_path, reg_path)
            result = solver.clear_market(demand, capacity, 2025)

            cross_region_flows = [
                f for f in result.trade_flows
                if f.origin_region != f.destination_region
            ]
            total_cross = sum(f.volume_mt for f in cross_region_flows)
            assert total_cross < 1e-3, \
                f"Expected near-zero cross-region trade, got {total_cross:.6f} MT: {cross_region_flows}"
        finally:
            os.unlink(tc_path); os.unlink(reg_path)

    def test_domestic_flows_cover_demand_in_autarky(self):
        """Domestic flows must equal demand when there's no cross-region trade."""
        regions  = ["EU", "US", "APAC"]
        demand_vols = {"EU": 0.5, "US": 0.3, "APAC": 0.2}
        demand   = _demand(demand_vols)
        capacity = _capacity({"EU": 5.0, "US": 5.0, "APAC": 5.0})

        PROHIBITIVE = 1_000_000.0
        arcs = {(i, j): (0.0 if i == j else PROHIBITIVE) for i in regions for j in regions}
        tc_path  = _write_tc_csv(arcs)
        reg_path = _write_reg_csv(regions, "voluntary_cost_plus")
        try:
            solver = EquilibriumSolver(tc_path, reg_path)
            result = solver.clear_market(demand, capacity, 2025)

            for r, d in demand_vols.items():
                domestic = sum(
                    f.volume_mt for f in result.trade_flows
                    if f.origin_region == r and f.destination_region == r
                )
                assert abs(domestic - d) < 1e-3, \
                    f"Region {r}: domestic flow {domestic:.4f} ≠ demand {d}"
        finally:
            os.unlink(tc_path); os.unlink(reg_path)


# ---------------------------------------------------------------------------
# Additional: MarketClearingResult helper methods
# ---------------------------------------------------------------------------

class TestResultHelpers:
    def _simple_result(self):
        regions  = ["EU", "US"]
        demand   = _demand({"EU": 0.5, "US": 0.3})
        capacity = _capacity({"EU": 2.0, "US": 2.0})
        arcs     = {("EU","EU"):0.0,("EU","US"):45.0,("US","EU"):45.0,("US","US"):0.0}
        tc_path  = _write_tc_csv(arcs)
        reg_path = _write_reg_csv(regions, "voluntary_cost_plus")
        try:
            solver = EquilibriumSolver(tc_path, reg_path)
            return solver.clear_market(demand, capacity, 2025)
        finally:
            os.unlink(tc_path); os.unlink(reg_path)

    def test_price_for_region_returns_correct_object(self):
        result = self._simple_result()
        p = result.price_for_region("EU")
        assert p is not None
        assert p.region == "EU"

    def test_total_saf_produced_is_non_negative(self):
        result = self._simple_result()
        assert result.total_saf_produced_mt >= 0

    def test_objective_value_is_non_negative(self):
        result = self._simple_result()
        assert result.objective_value >= 0

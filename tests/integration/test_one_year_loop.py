"""
Integration test: single year (2025) end-to-end loop using the new modules.

Verifies that BottomUpDemandModule → CapacityExpansionModule → WTPModel
→ PriceQuantityClearing → ModelState works as a coherent pipeline,
and that all outputs pass Pydantic validation.
"""

from __future__ import annotations

import pytest

from config.settings import MODEL_START_YEAR, REGIONS
from data.loaders import load_committed_capacity
from modules.capacity_expansion import CapacityExpansionModule
from modules.demand_bottom_up import BottomUpDemandModule
from modules.price_quantity_clearing import PriceQuantityClearing
from modules.wtp_model import WTPModel
from schemas.state_schema import ModelState


@pytest.fixture(scope="module")
def year_2025_state() -> ModelState:
    """Run a complete single-year pipeline for 2025 and return the ModelState."""
    year = MODEL_START_YEAR

    demand_module = BottomUpDemandModule()
    cap_expansion = CapacityExpansionModule()
    wtp_model     = WTPModel()
    pq_clearing   = PriceQuantityClearing()

    demand_matrix  = demand_module.estimate_demand(year, "baseline")
    capacity_state = load_committed_capacity(year)

    expansion_result, capacity_state = cap_expansion.run(
        demand_matrix=demand_matrix,
        capacity_state=capacity_state,
        year=year,
    )
    expansion = expansion_result.expansion_decision

    if expansion_result.supply_meets_demand:
        wtp_matrix = wtp_model.compute_wtp(year, capacity_state)
        market = pq_clearing.clear_market(demand_matrix, capacity_state, year, wtp_matrix)
    else:
        from main import _make_empty_market_result
        market = _make_empty_market_result(year)

    return ModelState(
        year=year,
        demand=demand_matrix,
        capacity=capacity_state,
        expansion=expansion,
        market=market,
        cumulative_capacity_by_region=dict(capacity_state.total_capacity_by_region()),
        feedstock_remaining=[],
    )


# ---------------------------------------------------------------------------
# ModelState validation
# ---------------------------------------------------------------------------

class TestModelStateValid:
    def test_state_is_model_state_instance(self, year_2025_state):
        assert isinstance(year_2025_state, ModelState)

    def test_year_is_correct(self, year_2025_state):
        assert year_2025_state.year == MODEL_START_YEAR

    def test_demand_matrix_present(self, year_2025_state):
        from schemas.demand_schema import DemandMatrix
        assert isinstance(year_2025_state.demand, DemandMatrix)

    def test_capacity_state_has_plants(self, year_2025_state):
        assert len(year_2025_state.capacity.plants) > 0

    def test_expansion_decision_present(self, year_2025_state):
        from schemas.supply_schema import ExpansionDecision
        assert isinstance(year_2025_state.expansion, ExpansionDecision)

    def test_cumulative_capacity_by_region_populated(self, year_2025_state):
        cumcap = year_2025_state.cumulative_capacity_by_region
        assert isinstance(cumcap, dict)
        assert len(cumcap) > 0


# ---------------------------------------------------------------------------
# Market clearing
# ---------------------------------------------------------------------------

class TestMarketClearing:
    def test_all_clearing_prices_non_negative(self, year_2025_state):
        for p in year_2025_state.market.prices:
            assert p.clearing_price_usd_per_mt >= 0, \
                f"Negative price in region {p.region}: {p.clearing_price_usd_per_mt}"

    def test_all_trade_flows_non_negative(self, year_2025_state):
        for f in year_2025_state.market.trade_flows:
            assert f.volume_mt >= 0

    def test_solver_status_valid(self, year_2025_state):
        valid = {"optimal", "partial", "skipped_supply_shortfall"}
        assert year_2025_state.market.solver_status in valid, \
            f"Unexpected market solver status: {year_2025_state.market.solver_status}"

    def test_wtp_pricing_regime_when_cleared(self, year_2025_state):
        """Prices produced by WTP clearing use wtp_priority_allocation or corsia_offset."""
        if not year_2025_state.market.market_balanced:
            pytest.skip("Market not balanced — clearing was skipped")
        for p in year_2025_state.market.prices:
            assert p.pricing_regime in {"wtp_priority_allocation", "corsia_offset"}, \
                f"Unexpected pricing regime for {p.region}: {p.pricing_regime}"

    def test_clearing_price_equals_wtp_for_served_region(self, year_2025_state):
        """For any served region, clearing_price must equal the WTP in the wtp_matrix."""
        if not year_2025_state.market.market_balanced:
            pytest.skip("Market not balanced — clearing was skipped")

        wtp_model = WTPModel()
        wtp_matrix = wtp_model.compute_wtp(
            year_2025_state.year, year_2025_state.capacity
        )

        for price in year_2025_state.market.prices:
            if price.pricing_regime == "corsia_offset":
                continue
            wtp_entry = wtp_matrix.wtp_for_region(price.region)
            if wtp_entry:
                assert price.clearing_price_usd_per_mt == pytest.approx(
                    wtp_entry.wtp_usd_per_mt, abs=0.01
                ), f"Clearing price mismatch for {price.region}"

    def test_eu_price_exceeds_us_when_cleared(self, year_2025_state):
        """EU has ReFuelEU Case-3 penalty → its WTP (and clearing price) > US."""
        if not year_2025_state.market.market_balanced:
            pytest.skip("Market not balanced — clearing was skipped")
        eu = year_2025_state.market.price_for_region("EU")
        us = year_2025_state.market.price_for_region("US")
        if eu and us and eu.pricing_regime != "corsia_offset" and us.pricing_regime != "corsia_offset":
            assert eu.clearing_price_usd_per_mt > us.clearing_price_usd_per_mt


# ---------------------------------------------------------------------------
# Supply expansion
# ---------------------------------------------------------------------------

class TestSupplyExpansion:
    def test_expansion_decision_has_valid_status(self, year_2025_state):
        valid = {"optimal", "not_needed", "infeasible", "feasible"}
        assert year_2025_state.expansion.solver_status in valid, \
            f"Unknown expansion status: {year_2025_state.expansion.solver_status}"

    def test_new_plants_are_endogenous_if_built(self, year_2025_state):
        for plant in year_2025_state.expansion.new_plants:
            assert plant.is_deterministic is False

    def test_npv_cost_non_negative(self, year_2025_state):
        assert year_2025_state.expansion.npv_cost_usd >= 0


# ---------------------------------------------------------------------------
# Demand module
# ---------------------------------------------------------------------------

class TestDemandIntegration:
    def test_demand_covers_all_regions(self, year_2025_state):
        regions_in_demand = {r.region for r in year_2025_state.demand.get_year(MODEL_START_YEAR)}
        assert regions_in_demand == set(REGIONS)

    def test_global_demand_2025_positive(self, year_2025_state):
        total = year_2025_state.demand.total_volume_mt(MODEL_START_YEAR)
        assert total > 0, f"2025 global SAF demand should be positive, got {total:.4f}"

    def test_demand_source_is_bottom_up(self, year_2025_state):
        for rec in year_2025_state.demand.get_year(MODEL_START_YEAR):
            assert rec.source == "bottom_up_flight_data"

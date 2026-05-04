"""Unit tests for modules/price_quantity_clearing.py — PriceQuantityClearing."""

from __future__ import annotations

import pytest

from config.settings import UTILIZATION_FACTOR
from modules.price_quantity_clearing import PriceQuantityClearing
from schemas.equilibrium_schema import MarketClearingResult
from schemas.supply_schema import CapacityState, PlantRecord
from schemas.wtp_schema import RegionalWTP, WTPMatrix


def _eff(mt: float) -> float:
    """Nameplate capacity needed to yield `mt` effective MT at UTILIZATION_FACTOR."""
    return mt / UTILIZATION_FACTOR


# ── Helpers ──────────────────────────────────────────────────────────────────

def _wtp_matrix(year: int, wtp_dict: dict) -> WTPMatrix:
    """Build a minimal WTPMatrix from {region: wtp_usd_per_mt}."""
    wtps = [
        RegionalWTP(
            year=year, region=r,
            wtp_usd_per_mt=v,
            case1_value=v, case2_value=v * 0.8, case3_value=v * 0.5,
            binding_case="case1",
        )
        for r, v in wtp_dict.items()
    ]
    return WTPMatrix(year=year, regional_wtps=wtps)


def _capacity(plants: list) -> CapacityState:
    return CapacityState(year=2025, plants=plants)


def _plant(region: str, capacity_mt_yr: float, opex: float = 600.0) -> PlantRecord:
    return PlantRecord(
        plant_id=f"test_{region}_{capacity_mt_yr}",
        region=region,
        pathway="HEFA",
        capacity_mt_yr=capacity_mt_yr,
        capex_usd_per_mt=1500.0,
        opex_usd_per_mt=opex,
        feedstock_intensity={"used_cooking_oil": 1.2},
        online_year=2025,
        is_deterministic=True,
    )


def _demand_matrix(year: int, volumes: dict):
    """Build a minimal DemandMatrix."""
    from datetime import datetime, timezone
    from config.settings import MT_TO_PJ_FACTOR
    from schemas.demand_schema import DemandMatrix, DemandRecord
    records = [
        DemandRecord(
            year=year, region=r, volume_mt=v,
            energy_pj=round(v * MT_TO_PJ_FACTOR, 8),
            source="test",
        )
        for r, v in volumes.items()
    ]
    return DemandMatrix(
        records=records,
        scenario_name="test",
        created_at=datetime.now(timezone.utc).isoformat(),
    )


YEAR = 2025


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def clearing():
    # Zero transport costs for simplicity
    pqc = PriceQuantityClearing()
    pqc._tc_cache = {}  # no transport costs
    return pqc


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestAllocationPriority:
    def test_highest_wtp_region_served_first(self, clearing):
        """When supply is scarce, the highest-WTP region gets all available supply."""
        # nameplate capacity gives exactly 1.0 MT effective supply via UTILIZATION_FACTOR
        demand  = _demand_matrix(YEAR, {"EU": 1.0, "US": 1.0})
        cap     = _capacity([_plant("EU", _eff(1.0))])     # effective = 1.0 MT
        wtp     = _wtp_matrix(YEAR, {"EU": 2500.0, "US": 800.0})

        result = clearing.clear_market(demand, cap, YEAR, wtp)

        eu_inflow = sum(f.volume_mt for f in result.trade_flows if f.destination_region == "EU")
        us_inflow = sum(f.volume_mt for f in result.trade_flows if f.destination_region == "US")
        assert eu_inflow == pytest.approx(1.0, abs=1e-4), "EU (highest WTP) should get all supply"
        assert us_inflow == pytest.approx(0.0, abs=1e-4), "US should be unserved"

    def test_lower_wtp_region_served_when_surplus(self, clearing):
        """With ample supply all regions should be served."""
        demand = _demand_matrix(YEAR, {"EU": 0.5, "US": 0.5})
        cap    = _capacity([_plant("EU", _eff(1.1))])       # effective > 1.0 MT total demand
        wtp    = _wtp_matrix(YEAR, {"EU": 2500.0, "US": 800.0})

        result = clearing.clear_market(demand, cap, YEAR, wtp)

        assert result.market_balanced is True

    def test_allocation_order_matches_wtp_ranking(self, clearing):
        """Multiple regions: supply fills highest-WTP first, then next, etc."""
        demand = _demand_matrix(YEAR, {"EU": 1.0, "APAC": 1.0, "US": 1.0})
        # effective = 2.0 MT — enough for EU + APAC but not US
        cap    = _capacity([_plant("EU", _eff(2.0))])
        wtp    = _wtp_matrix(YEAR, {"EU": 2500.0, "APAC": 900.0, "US": 800.0})

        result = clearing.clear_market(demand, cap, YEAR, wtp)

        eu_inflow   = sum(f.volume_mt for f in result.trade_flows if f.destination_region == "EU")
        apac_inflow = sum(f.volume_mt for f in result.trade_flows if f.destination_region == "APAC")

        assert eu_inflow   == pytest.approx(1.0, abs=1e-4)
        assert apac_inflow == pytest.approx(1.0, abs=1e-4)


class TestCheapestCIFDispatch:
    def test_cheapest_supply_dispatched_first(self, clearing):
        """Within a demand region, the lowest-OPEX supply region is used first."""
        # effective: EU=1.0 MT (cheap), US=0.5 MT (expensive); demand=1.5 MT
        demand = _demand_matrix(YEAR, {"EU": 1.5})
        cap    = _capacity([
            _plant("EU",  _eff(1.0), opex=400.0),   # cheap — dispatched first
            _plant("US",  _eff(0.5), opex=800.0),   # expensive — fills remainder
        ])
        wtp = _wtp_matrix(YEAR, {"EU": 2500.0})

        result = clearing.clear_market(demand, cap, YEAR, wtp)

        eu_origin_vol = sum(f.volume_mt for f in result.trade_flows
                            if f.origin_region == "EU" and f.destination_region == "EU")
        us_origin_vol = sum(f.volume_mt for f in result.trade_flows
                            if f.origin_region == "US" and f.destination_region == "EU")

        assert eu_origin_vol == pytest.approx(1.0, abs=1e-4), "Cheapest EU supply used first"
        assert us_origin_vol == pytest.approx(0.5, abs=1e-4), "US supply fills remainder"

    def test_supply_conservation(self, clearing):
        """Total volume allocated ≤ effective supply available."""
        demand = _demand_matrix(YEAR, {"EU": 1.0, "US": 1.0, "APAC": 1.0})
        effective_supply = 2.0
        cap = _capacity([_plant("EU", _eff(effective_supply))])
        wtp = _wtp_matrix(YEAR, {"EU": 2500.0, "US": 800.0, "APAC": 850.0})

        result = clearing.clear_market(demand, cap, YEAR, wtp)

        total_allocated = sum(f.volume_mt for f in result.trade_flows)
        assert total_allocated <= effective_supply + 1e-6


class TestMarketBalance:
    def test_balanced_when_supply_exceeds_demand(self, clearing):
        demand = _demand_matrix(YEAR, {"EU": 0.5, "US": 0.3})
        cap    = _capacity([_plant("EU", 1.0)])
        wtp    = _wtp_matrix(YEAR, {"EU": 2500.0, "US": 800.0})

        result = clearing.clear_market(demand, cap, YEAR, wtp)

        assert result.market_balanced is True
        assert result.solver_status == "optimal"

    def test_not_balanced_when_supply_insufficient(self, clearing):
        demand = _demand_matrix(YEAR, {"EU": 2.0})
        cap    = _capacity([_plant("EU", 1.0)])    # 1 MT supply < 2 MT demand
        wtp    = _wtp_matrix(YEAR, {"EU": 2500.0})

        result = clearing.clear_market(demand, cap, YEAR, wtp)

        assert result.market_balanced is False
        assert result.solver_status == "partial"

    def test_zero_demand_is_balanced(self, clearing):
        demand = _demand_matrix(YEAR, {"EU": 0.0})
        cap    = _capacity([_plant("EU", 1.0)])
        wtp    = _wtp_matrix(YEAR, {"EU": 2500.0})

        result = clearing.clear_market(demand, cap, YEAR, wtp)

        assert result.market_balanced is True


class TestClearingPrices:
    def test_served_region_price_equals_wtp(self, clearing):
        """Served region's clearing price = its WTP (capacity-constrained market)."""
        eu_wtp = 2500.0
        demand = _demand_matrix(YEAR, {"EU": 0.5})
        cap    = _capacity([_plant("EU", 1.0)])
        wtp    = _wtp_matrix(YEAR, {"EU": eu_wtp})

        result = clearing.clear_market(demand, cap, YEAR, wtp)

        eu_price = next(p for p in result.prices if p.region == "EU")
        assert eu_price.clearing_price_usd_per_mt == pytest.approx(eu_wtp, abs=0.01)

    def test_unserved_region_price_is_zero(self, clearing):
        """Unserved region must have clearing_price = 0 and pricing_regime = 'unserved'."""
        demand = _demand_matrix(YEAR, {"EU": 0.5, "US": 1.0})
        cap    = _capacity([_plant("EU", _eff(0.5))])   # effective = 0.5 MT, only enough for EU
        wtp    = _wtp_matrix(YEAR, {"EU": 2500.0, "US": 800.0})

        result = clearing.clear_market(demand, cap, YEAR, wtp)

        us_price = next(p for p in result.prices if p.region == "US")
        assert us_price.clearing_price_usd_per_mt == pytest.approx(0.0)
        assert us_price.pricing_regime == "unserved"

    def test_margin_non_negative_for_served_region(self, clearing):
        """Producer margin (WTP - supply_cost - transport) must be ≥ 0 for served region."""
        demand = _demand_matrix(YEAR, {"EU": 0.5})
        cap    = _capacity([_plant("EU", 1.0, opex=400.0)])
        wtp    = _wtp_matrix(YEAR, {"EU": 2500.0})

        result = clearing.clear_market(demand, cap, YEAR, wtp)

        eu_price = next(p for p in result.prices if p.region == "EU")
        assert eu_price.margin_usd_per_mt >= 0.0


class TestReturnSchema:
    def test_returns_market_clearing_result(self, clearing):
        demand = _demand_matrix(YEAR, {"EU": 0.5})
        cap    = _capacity([_plant("EU", 1.0)])
        wtp    = _wtp_matrix(YEAR, {"EU": 2500.0})

        result = clearing.clear_market(demand, cap, YEAR, wtp)

        assert isinstance(result, MarketClearingResult)
        assert result.year == YEAR

    def test_result_serialises(self, clearing):
        demand = _demand_matrix(YEAR, {"EU": 0.5})
        cap    = _capacity([_plant("EU", 1.0)])
        wtp    = _wtp_matrix(YEAR, {"EU": 2500.0})

        result = clearing.clear_market(demand, cap, YEAR, wtp)
        d = result.model_dump()

        assert "trade_flows" in d
        assert "prices" in d
        assert d["market_balanced"] is True

    def test_prices_cover_all_demand_regions(self, clearing):
        demand = _demand_matrix(YEAR, {"EU": 0.5, "US": 0.3, "APAC": 0.2})
        cap    = _capacity([_plant("EU", 2.0)])
        wtp    = _wtp_matrix(YEAR, {"EU": 2500.0, "US": 800.0, "APAC": 850.0})

        result = clearing.clear_market(demand, cap, YEAR, wtp)

        price_regions = {p.region for p in result.prices}
        assert {"EU", "US", "APAC"} == price_regions

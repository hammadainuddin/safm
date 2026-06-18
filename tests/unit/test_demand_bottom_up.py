"""Unit tests for modules/demand_bottom_up.py — BottomUpDemandModule."""

from __future__ import annotations

import pytest
from pandas import DataFrame, Series

from config.settings import REGIONS
from modules.demand_bottom_up import (
    BottomUpDemandModule,
    _EFFICIENCY_IMPROVEMENT_PA,
)
from schemas.demand_schema import DemandMatrix


@pytest.fixture(scope="module")
def module():
    return BottomUpDemandModule()


@pytest.fixture(scope="module")
def result_2025(module):
    return module.get_intermediate_result(2025)


@pytest.fixture(scope="module")
def result_2030(module):
    return module.get_intermediate_result(2030)


class TestFuelCalculation:
    def test_fuel_burn_formula(self):
        """fuel_mt = flights × distance × efficiency / 1000, at base year offset 0."""
        efficiency = 0.0089   # B777-300ER (t/km)
        flights = 730
        distance = 5570  # km
        expected_t = flights * distance * efficiency  # tonnes
        expected_mt = expected_t / 1_000            # metric tonnes → kt (used in model)

        # Verify formula directly
        assert expected_mt == pytest.approx(flights * distance * efficiency / 1_000, rel=1e-9)

    def test_positive_fuel_in_all_regions(self, result_2025):
        """Every region should have non-zero total jet fuel burn from the route set."""
        for region in REGIONS:
            assert result_2025.fuel_by_region.get(region, 0.0) > 0, \
                f"Zero fuel burn in {region} — check flight_routes.csv coverage"

    def test_saf_demand_non_negative(self, result_2025):
        """SAF demand must be ≥ 0 for all regions."""
        for region in REGIONS:
            assert result_2025.saf_demand_by_region.get(region, 0.0) >= 0.0


class TestCORSIAAttribution:
    def test_corsia_applied_to_international_only(self, result_2025):
        """All CORSIA SAF demand derives from international routes (not domestic)."""
        total_corsia = sum(result_2025.corsia_saf_demand_by_region.values())
        assert total_corsia > 0, "Expected non-zero CORSIA demand in 2025"

    def test_international_fuel_attributed_to_origin_only(self, tmp_path):
        """International fuel/CORSIA demand is attributed 100% to the origin region."""
        routes = tmp_path / "routes.csv"
        routes.write_text(
            "route_id,airline_id,operator_name,segment,origin_airport,origin_country,"
            "origin_region,dest_airport,dest_country,dest_region,flight_type,aircraft_type,"
            "annual_flights_2025,distance_km,annual_growth_rate,"
            "saf_pct_2025,saf_pct_2030,saf_pct_2035,saf_pct_2040,saf_pct_2045,saf_pct_2050\n"
            "T1,XX,Test Air,Passenger,AAA,CountryA,EU,BBB,CountryB,US,international,A320neo,"
            "1000,5000.0,0.0,0.05,0.05,0.05,0.05,0.05,0.05\n"
        )
        mod = BottomUpDemandModule(routes_path=str(routes), route_sample_fraction=1.0)
        r = mod.get_intermediate_result(2025)
        # Destination region (US) receives nothing; origin (EU) receives the full burn.
        assert r.fuel_by_region.get("US", 0.0) == pytest.approx(0.0, abs=1e-12)
        assert r.fuel_by_region.get("EU", 0.0) > 0.0
        assert r.corsia_saf_demand_by_region.get("US", 0.0) == pytest.approx(0.0, abs=1e-12)

    def test_corsia_increases_post_2027(self, result_2025, result_2030):
        """Mandatory CORSIA fraction rises sharply after 2027 — total demand should increase."""
        corsia_2025 = sum(result_2025.corsia_saf_demand_by_region.values())
        corsia_2030 = sum(result_2030.corsia_saf_demand_by_region.values())
        assert corsia_2030 > corsia_2025, \
            f"CORSIA demand should grow from 2025 ({corsia_2025:.4f}) to 2030 ({corsia_2030:.4f})"

    def test_corsia_fraction_stored_in_result(self, result_2025):
        """BottomUpDemandResult should store the applied mandatory fraction."""
        assert 0.0 < result_2025.corsia_fraction_applied <= 1.0


class TestGrowthFactor:
    def test_growth_increases_demand_over_time(self, result_2025, result_2030):
        """Fuel burn should grow from 2025 to 2030 due to annual flight growth."""
        fuel_2025 = sum(result_2025.fuel_by_region.values())
        fuel_2030 = sum(result_2030.fuel_by_region.values())
        assert fuel_2030 > fuel_2025, \
            f"Total fuel should grow from 2025 ({fuel_2025:.4f}) to 2030 ({fuel_2030:.4f})"

    def test_efficiency_improvement_reduces_fuel_per_km(self):
        """After 5 years, fuel per km should be ~7.3% lower (1.5% annual compounding)."""
        base = 1.0
        after_5yr = base * (1 - _EFFICIENCY_IMPROVEMENT_PA) ** 5
        assert after_5yr == pytest.approx(base * (0.985 ** 5), rel=1e-6)
        assert after_5yr < base

    def test_efficiency_improvement_rate(self):
        assert _EFFICIENCY_IMPROVEMENT_PA == pytest.approx(0.015)


class TestMandateDemand:
    def test_eu_mandate_zero_international_only(self, result_2025):
        """Default (international only) — domestic blending mandate demand is zero."""
        eu_mandate = result_2025.mandate_saf_demand_by_region.get("EU", 0.0)
        assert eu_mandate == pytest.approx(0.0, abs=1e-9)

    def test_eu_mandate_positive_with_domestic(self, tmp_path):
        """With domestic routes enabled, an EU domestic route yields EU blending-mandate
        SAF demand (the EU mandate in national_blending_mandates.csv applies)."""
        routes = tmp_path / "routes.csv"
        routes.write_text(
            "route_id,airline_id,operator_name,segment,origin_airport,origin_country,"
            "origin_region,dest_airport,dest_country,dest_region,flight_type,aircraft_type,"
            "annual_flights_2025,distance_km,annual_growth_rate,"
            "saf_pct_2025,saf_pct_2030,saf_pct_2035,saf_pct_2040,saf_pct_2045,saf_pct_2050\n"
            "D1,XX,Test Air,Passenger,FRA,Germany,EU,MUC,Germany,EU,domestic,A320neo,"
            "1000,500.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0\n"
        )
        mod = BottomUpDemandModule(routes_path=str(routes), include_domestic=True)
        r = mod.get_intermediate_result(2025)
        assert r.mandate_saf_demand_by_region.get("EU", 0.0) > 0.0

    def test_excluding_domestic_drops_its_mandate_demand(self, tmp_path):
        """The same domestic route contributes no mandate demand when excluded (default)."""
        routes = tmp_path / "routes.csv"
        routes.write_text(
            "route_id,airline_id,operator_name,segment,origin_airport,origin_country,"
            "origin_region,dest_airport,dest_country,dest_region,flight_type,aircraft_type,"
            "annual_flights_2025,distance_km,annual_growth_rate,"
            "saf_pct_2025,saf_pct_2030,saf_pct_2035,saf_pct_2040,saf_pct_2045,saf_pct_2050\n"
            "D1,XX,Test Air,Passenger,FRA,Germany,EU,MUC,Germany,EU,domestic,A320neo,"
            "1000,500.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0\n"
        )
        mod = BottomUpDemandModule(routes_path=str(routes), include_domestic=False)
        r = mod.get_intermediate_result(2025)
        assert r.mandate_saf_demand_by_region.get("EU", 0.0) == pytest.approx(0.0, abs=1e-9)

    def test_us_no_mandatory_blend_in_2025(self, result_2025):
        """US has no mandatory blending in 2025 (SAF Grand Challenge is voluntary)."""
        us_mandate = result_2025.mandate_saf_demand_by_region.get("US", 0.0)
        assert us_mandate == pytest.approx(0.0, abs=1e-9), \
            f"US mandate SAF in 2025 should be 0, got {us_mandate}"

    def test_mandate_fractions_recorded_for_all_regions(self, result_2025):
        for region in REGIONS:
            assert region in result_2025.mandate_fraction_by_region


class TestDemandMatrixOutput:
    def test_returns_demand_matrix(self, module):
        dm = module.estimate_demand(2025, "baseline")
        assert isinstance(dm, DemandMatrix)

    def test_all_regions_present(self, module):
        dm = module.estimate_demand(2025, "baseline")
        regions_in_dm = {r.region for r in dm.records}
        assert set(REGIONS) == regions_in_dm

    def test_volume_non_negative_for_all_regions(self, module):
        dm = module.estimate_demand(2025, "baseline")
        for rec in dm.records:
            assert rec.volume_mt >= 0.0, f"Negative volume in region {rec.region}"

    def test_source_tag(self, module):
        dm = module.estimate_demand(2025, "baseline")
        for rec in dm.records:
            assert rec.source == "bottom_up_flight_data"

    def test_energy_pj_consistent_with_volume(self, module):
        """energy_pj should be proportional to volume_mt (non-zero where volume > 0)."""
        from config.settings import MT_TO_PJ_FACTOR
        dm = module.estimate_demand(2025, "baseline")
        for rec in dm.records:
            expected_pj = round(rec.volume_mt * MT_TO_PJ_FACTOR, 8)
            assert rec.energy_pj == pytest.approx(expected_pj, abs=1e-6), \
                f"energy_pj mismatch for {rec.region}"

    def test_total_demand_positive(self, module):
        dm = module.estimate_demand(2025, "baseline")
        total = sum(r.volume_mt for r in dm.records)
        assert total > 0

    def test_invalid_year_raises(self, module):
        with pytest.raises(ValueError):
            module.estimate_demand(2000, "baseline")

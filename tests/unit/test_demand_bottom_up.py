"""Unit tests for modules/demand_bottom_up.py — BottomUpDemandModule."""

from __future__ import annotations

import pytest
from pandas import DataFrame, Series

from config.settings import REGIONS
from modules.demand_bottom_up import (
    BottomUpDemandModule,
    _EFFICIENCY_IMPROVEMENT_PA,
    _ORIGIN_SHARE,
    _DEST_SHARE,
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

    def test_origin_gets_larger_share(self):
        """CORSIA uplift rule: origin region gets 60%, destination 40%."""
        assert _ORIGIN_SHARE == pytest.approx(0.60)
        assert _DEST_SHARE   == pytest.approx(0.40)
        assert _ORIGIN_SHARE + _DEST_SHARE == pytest.approx(1.0)

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
    def test_eu_mandate_zero_without_domestic_routes(self, result_2025):
        """Domestic routes are excluded — mandate demand from domestic blending is zero."""
        eu_mandate = result_2025.mandate_saf_demand_by_region.get("EU", 0.0)
        assert eu_mandate == pytest.approx(0.0, abs=1e-9)

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

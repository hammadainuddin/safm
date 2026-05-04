"""Unit tests for modules/wtp_model.py — WTPModel (3 WTP cases)."""

from __future__ import annotations

import pytest

from config.settings import DISCOUNT_RATE, PROJECT_LIFE_YR
from modules.wtp_model import WTPModel, _CI_REDUCTION_T_CO2_PER_MT_SAF
from schemas.supply_schema import CapacityState
from utils.economics import levelised_cost


@pytest.fixture()
def empty_capacity():
    return CapacityState(year=2025, plants=[])


@pytest.fixture()
def wtp_model():
    return WTPModel()


class TestCase1JetFuelPlusCorsia:
    def test_case1_formula(self):
        """Case 1 = jet_fuel_price + credit × CI_reduction."""
        model = WTPModel()
        # Manually compute: jet=750, credit=30, CI=2.5 → 750 + 75 = 825
        from pandas import Series
        row = Series({"jet_fuel_price_usd_per_mt": 750.0, "corsia_credit_usd_per_tco2": 30.0})
        result = model._case1(row)
        assert result == pytest.approx(750.0 + 30.0 * _CI_REDUCTION_T_CO2_PER_MT_SAF, abs=0.01)

    def test_case1_crisis_value(self):
        """Crisis jet price (1800) + higher carbon credit gives much higher WTP."""
        from pandas import Series
        row = Series({"jet_fuel_price_usd_per_mt": 1800.0, "corsia_credit_usd_per_tco2": 70.0})
        result = WTPModel._case1(row)
        assert result == pytest.approx(1800.0 + 70.0 * _CI_REDUCTION_T_CO2_PER_MT_SAF, abs=0.01)
        assert result > 1900.0


class TestCase2LCOSAF:
    def test_case2_higher_irr_gives_higher_price(self):
        """LCOSAF at 18% IRR > 12% IRR > 10% discount rate (expected return floor)."""
        from pandas import Series
        row_12 = Series({"target_irr_pct": 12.0})
        row_18 = Series({"target_irr_pct": 18.0})
        c2_12 = WTPModel._case2("EU", row_12)
        c2_18 = WTPModel._case2("EU", row_18)
        assert c2_18 > c2_12 > 0

    def test_case2_positive_for_all_regions(self):
        """Case 2 should return a positive LCOSAF for every region."""
        from pandas import Series
        for region in ["EU", "US", "APAC", "MENA", "LATAM", "ROW"]:
            row = Series({"target_irr_pct": 12.0})
            result = WTPModel._case2(region, row)
            assert result > 0, f"Case 2 should be positive for {region}"

    def test_case2_uses_cheapest_pathway(self):
        """HEFA (lowest CAPEX) should determine Case 2; result < PtL-based cost."""
        from pandas import Series
        from config.settings import REGIONAL_CAPEX, REGIONAL_OPEX, UTILIZATION_FACTOR
        row = Series({"target_irr_pct": 12.0})
        c2 = WTPModel._case2("EU", row)
        # PtL at 12% IRR for EU (most expensive pathway)
        ptl_lcosaf = levelised_cost(
            REGIONAL_CAPEX["EU"]["PtL"],
            REGIONAL_OPEX["EU"]["PtL"] * UTILIZATION_FACTOR,
            UTILIZATION_FACTOR, 0.12, PROJECT_LIFE_YR
        )
        assert c2 <= ptl_lcosaf


class TestCase3PolicyPenalty:
    def test_eu_case3_is_nonzero(self):
        """EU should have a non-zero policy penalty (ReFuelEU)."""
        from pandas import Series
        row = Series({"case3_penalty_usd_per_mt": 2500.0})
        assert WTPModel._case3(row) == 2500.0

    def test_voluntary_market_case3_is_zero(self):
        """Non-EU regions with no mandate should have case3 = 0."""
        from pandas import Series
        row = Series({"case3_penalty_usd_per_mt": 0.0})
        assert WTPModel._case3(row) == 0.0


class TestWTPMaxBinding:
    def test_wtp_is_max_of_three_cases(self):
        """Final WTP must equal the maximum of cases 1, 2, 3."""
        wtp, binding = WTPModel._apply_mode(900.0, 1200.0, 2500.0, "max")
        assert wtp == pytest.approx(2500.0)
        assert binding == "case3"

    def test_binding_case_identified_correctly(self):
        """When case1 dominates, binding_case = 'case1'."""
        wtp, binding = WTPModel._apply_mode(1800.0, 1200.0, 0.0, "max")
        assert binding == "case1"
        assert wtp == pytest.approx(1800.0)

    def test_explicit_mode_overrides_max(self):
        """wtp_mode='case2' should return case2 regardless of which is largest."""
        wtp, binding = WTPModel._apply_mode(1800.0, 500.0, 2500.0, "case2")
        assert wtp == pytest.approx(500.0)
        assert binding == "case2"


class TestWTPMatrix:
    def test_compute_wtp_returns_all_regions(self, wtp_model, empty_capacity):
        """WTPMatrix should include all 6 model regions."""
        from config.settings import REGIONS
        matrix = wtp_model.compute_wtp(2025, empty_capacity)
        regions_in_matrix = {w.region for w in matrix.regional_wtps}
        assert set(REGIONS) == regions_in_matrix

    def test_eu_wtp_exceeds_us_in_2025(self, wtp_model, empty_capacity):
        """EU has ReFuelEU penalty (Case 3) → WTP >> US in 2025."""
        matrix = wtp_model.compute_wtp(2025, empty_capacity)
        eu_wtp = matrix.wtp_for_region("EU").wtp_usd_per_mt
        us_wtp = matrix.wtp_for_region("US").wtp_usd_per_mt
        assert eu_wtp > us_wtp, f"EU WTP {eu_wtp:.0f} should exceed US WTP {us_wtp:.0f}"

    def test_eu_binding_case_is_case3(self, wtp_model, empty_capacity):
        """EU in 2025 should be dominated by Case 3 (ReFuelEU penalty = 2500)."""
        matrix = wtp_model.compute_wtp(2025, empty_capacity)
        eu = matrix.wtp_for_region("EU")
        assert eu.binding_case == "case3"

    def test_wtp_grows_over_time_for_eu(self, wtp_model, empty_capacity):
        """EU WTP should increase from 2025 to 2040 as penalty escalates."""
        m2025 = wtp_model.compute_wtp(2025, empty_capacity)
        m2040 = wtp_model.compute_wtp(2040, empty_capacity)
        eu_2025 = m2025.wtp_for_region("EU").wtp_usd_per_mt
        eu_2040 = m2040.wtp_for_region("EU").wtp_usd_per_mt
        assert eu_2040 > eu_2025

    def test_wtp_matrix_serialises(self, wtp_model, empty_capacity):
        """WTPMatrix.model_dump() should work without errors."""
        matrix = wtp_model.compute_wtp(2025, empty_capacity)
        d = matrix.model_dump()
        assert "regional_wtps" in d
        assert len(d["regional_wtps"]) == 6

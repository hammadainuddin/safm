"""Unit tests for financial math utilities in utils/economics.py."""

import math
import pytest

from utils.economics import (
    annualise_capex,
    annualised_total_cost,
    crf,
    levelised_cost,
    npv,
)


class TestCrf:
    def test_textbook_value(self):
        # CRF(10%, 20yr) = 0.1746 — standard textbook result
        result = crf(0.10, 20)
        assert abs(result - 0.11746) < 0.0001

    def test_zero_discount_rate(self):
        # At 0% discount, CRF = 1/n
        result = crf(0.0, 10)
        assert abs(result - 0.1) < 1e-10

    def test_single_year(self):
        # CRF for 1 year at any rate = 1 + r (repay principal + interest)
        result = crf(0.10, 1)
        assert abs(result - 1.10) < 1e-10

    def test_higher_rate_gives_higher_crf(self):
        crf_low  = crf(0.05, 20)
        crf_high = crf(0.15, 20)
        assert crf_low < crf_high

    def test_longer_life_gives_lower_crf(self):
        crf_short = crf(0.10, 10)
        crf_long  = crf(0.10, 30)
        assert crf_short > crf_long

    def test_rejects_zero_or_negative_n_years(self):
        with pytest.raises(ValueError):
            crf(0.10, 0)


class TestAnnualiseCapex:
    def test_roundtrip_with_crf(self):
        # annualise_capex(C) / C == CRF(r, n)
        capex = 1000.0
        result = annualise_capex(capex, 0.10, 20)
        expected = capex * crf(0.10, 20)
        assert abs(result - expected) < 1e-9

    def test_zero_capex(self):
        assert annualise_capex(0.0, 0.10, 20) == 0.0

    def test_positive_result_for_positive_inputs(self):
        assert annualise_capex(800.0, 0.10, 20) > 0


class TestNpv:
    def test_single_cash_flow(self):
        # NPV of 100 received in year 0 = 100
        assert abs(npv([100.0], 0.10) - 100.0) < 1e-9

    def test_two_period_example(self):
        # 100 now + 110 next year @ 10%: 100 + 110/1.1 = 200
        result = npv([100.0, 110.0], 0.10)
        assert abs(result - 200.0) < 1e-9

    def test_uniform_series_matches_annuity_formula(self):
        # Ordinary annuity: 10 payments at t=1..10 (year-0 cash flow = 0)
        # PV = 100 / CRF(10%, 10)
        flows = [0.0] + [100.0] * 10    # index 0 = now (no payment), 1-10 = annual payments
        expected = 100.0 / crf(0.10, 10)
        result = npv(flows, 0.10)
        assert abs(result - expected) < 1e-6

    def test_all_zeros_gives_zero(self):
        assert npv([0.0, 0.0, 0.0], 0.10) == 0.0

    def test_higher_discount_gives_lower_npv(self):
        flows = [100.0] * 5
        npv_low  = npv(flows, 0.05)
        npv_high = npv(flows, 0.20)
        assert npv_low > npv_high


class TestLevelisedCost:
    def test_basic_calculation(self):
        # LCOSAF = (ann_capex + opex) / output
        capex   = 1000.0   # USD per MT/yr capacity
        opex    = 350.0    # USD per MT produced
        output  = 1.0      # 1 MT/yr nameplate, utilisation baked in externally
        result  = levelised_cost(capex, opex, output, 0.10, 20)
        ann_cap = annualise_capex(capex, 0.10, 20)
        assert abs(result - (ann_cap + opex)) < 1e-9

    def test_zero_output_returns_inf(self):
        assert levelised_cost(1000.0, 350.0, 0.0, 0.10, 20) == float("inf")

    def test_higher_capex_gives_higher_lcosaf(self):
        lco_cheap = levelised_cost(500.0,  350.0, 1.0, 0.10, 20)
        lco_dear  = levelised_cost(2000.0, 350.0, 1.0, 0.10, 20)
        assert lco_cheap < lco_dear


class TestAnnualisedTotalCost:
    def test_sum_of_parts(self):
        result   = annualised_total_cost(800.0, 350.0, 0.10, 20)
        expected = annualise_capex(800.0, 0.10, 20) + 350.0
        assert abs(result - expected) < 1e-9

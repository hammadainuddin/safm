"""
Unit tests for the supply model (Module 2).

Test cases
----------
1. Feasible LP on 3-region gap → solver_status optimal, new plants built
2. No gap → build_triggered False, LP never called
3. Binding feedstock constraint → shadow price > 0
4. LP infeasible (feedstock cap < demand gap) → graceful failure with warning
5. assess_gap() returns ≤ 0 for regions with deterministic surplus
"""

import pytest

from config.settings import UTILIZATION_FACTOR, REGIONS
from modules.supply_model import SupplyModel
from schemas.feedstock_schema import FeedstockAvailability, RegionalFeedstockBundle
from schemas.supply_schema import CapacityState, ExpansionDecision, PlantRecord
from schemas.demand_schema import DemandMatrix, DemandRecord
from config.settings import MT_TO_PJ_FACTOR


# Helpers
# ---------------------------------------------------------------------------

def _make_demand(volumes: dict, year: int = 2025) -> DemandMatrix:
    """Build a DemandMatrix from {region: volume_mt}."""
    records = [
        DemandRecord(
            year=year, region=r, volume_mt=v,
            energy_pj=round(v * MT_TO_PJ_FACTOR, 6),
            source="test",
        )
        for r, v in volumes.items()
    ]
    return DemandMatrix(records=records, scenario_name="test")


def _make_capacity(capacities: dict, year: int = 2025) -> CapacityState:
    """Build a CapacityState from {region: capacity_mt_yr}."""
    plants = [
        PlantRecord(
            plant_id=f"P_{r}", region=r, pathway="HEFA",
            capacity_mt_yr=cap, online_year=2025,
            capex_usd_per_mt=800.0, opex_usd_per_mt=350.0,
            feedstock_intensity={"UCO": 1.25},
            is_deterministic=True,
        )
        for r, cap in capacities.items()
    ]
    return CapacityState(year=year, plants=plants)


def _feedstock_bundle(region: str, year: int, avail_per_type: float) -> RegionalFeedstockBundle:
    from config.settings import FEEDSTOCK_TYPES
    return RegionalFeedstockBundle(
        year=year, region=region,
        feedstocks=[
            FeedstockAvailability(
                year=year, region=region, feedstock_type=ft,
                max_available_mt=avail_per_type, cost_usd_per_mt=350.0,
            )
            for ft in FEEDSTOCK_TYPES
        ],
    )


@pytest.fixture
def supply_model() -> SupplyModel:
    return SupplyModel()


# ---------------------------------------------------------------------------
# Test 1: Feasible LP — 3-region demand gap, abundant feedstock
# ---------------------------------------------------------------------------

class TestFeasibleLP:
    def test_solver_status_is_optimal(self, supply_model):
        demand   = _make_demand({"EU": 0.5, "US": 0.3, "APAC": 0.2})
        capacity = _make_capacity({"EU": 0.1, "US": 0.1, "APAC": 0.1})  # all short
        gaps     = supply_model.assess_gap(demand, capacity, 2025)
        bundles  = [_feedstock_bundle(r, 2025, 100.0) for r in ["EU", "US", "APAC"]]

        decision = supply_model.build_expansion_lp(gaps, bundles, 2025)

        assert decision.solver_status == "optimal"
        assert decision.build_triggered is True

    def test_new_plants_cover_the_gap(self, supply_model):
        demand   = _make_demand({"EU": 0.5, "US": 0.3, "APAC": 0.2})
        capacity = _make_capacity({"EU": 0.1, "US": 0.1, "APAC": 0.1})
        gaps     = supply_model.assess_gap(demand, capacity, 2025)
        bundles  = [_feedstock_bundle(r, 2025, 100.0) for r in ["EU", "US", "APAC"]]

        decision = supply_model.build_expansion_lp(gaps, bundles, 2025)

        # After applying expansion, effective supply should meet demand
        updated = supply_model.apply_expansion(capacity, decision)
        effective = updated.effective_supply_by_region(UTILIZATION_FACTOR)
        for r, g in gaps.items():
            if g > 0:
                assert effective.get(r, 0.0) >= demand.volume_by_region(2025)[r] - 1e-4, \
                    f"Region {r} still short after expansion"

    def test_new_plants_have_correct_year_and_flag(self, supply_model):
        demand   = _make_demand({"EU": 0.5})
        capacity = _make_capacity({"EU": 0.1})
        gaps     = supply_model.assess_gap(demand, capacity, 2030)
        bundles  = [_feedstock_bundle("EU", 2030, 100.0)]

        decision = supply_model.build_expansion_lp(gaps, bundles, 2030)

        for plant in decision.new_plants:
            assert plant.online_year == 2030
            assert plant.is_deterministic is False

    def test_npv_cost_is_positive(self, supply_model):
        demand   = _make_demand({"EU": 0.5})
        capacity = _make_capacity({"EU": 0.1})
        gaps     = supply_model.assess_gap(demand, capacity, 2025)
        bundles  = [_feedstock_bundle("EU", 2025, 100.0)]

        decision = supply_model.build_expansion_lp(gaps, bundles, 2025)

        assert decision.npv_cost_usd > 0


# ---------------------------------------------------------------------------
# Test 2: No gap — LP must not be triggered
# ---------------------------------------------------------------------------

class TestNoGap:
    def test_build_not_triggered_when_supply_exceeds_demand(self, supply_model):
        demand   = _make_demand({"EU": 0.5, "US": 0.3, "APAC": 0.2})
        capacity = _make_capacity({"EU": 10.0, "US": 10.0, "APAC": 10.0})  # huge surplus

        gaps     = supply_model.assess_gap(demand, capacity, 2025)
        bundles  = [_feedstock_bundle(r, 2025, 100.0) for r in ["EU", "US", "APAC"]]

        assert all(g <= 0 for g in gaps.values())

        decision = supply_model.build_expansion_lp(gaps, bundles, 2025)

        assert decision.build_triggered is False
        assert decision.new_plants == []
        assert decision.solver_status == "not_needed"

    def test_assess_gap_returns_negative_for_surplus_region(self, supply_model):
        demand   = _make_demand({"EU": 0.5})
        capacity = _make_capacity({"EU": 5.0})   # 5 MT cap × 0.85 util = 4.25 MT > 0.5 demand

        gaps = supply_model.assess_gap(demand, capacity, 2025)

        assert gaps["EU"] < 0


# ---------------------------------------------------------------------------
# Test 3: Binding feedstock constraint — shadow price must be positive
# ---------------------------------------------------------------------------

class TestBindingFeedstock:
    def test_shadow_price_positive_when_feedstock_binding(self, supply_model):
        """
        Set up a scenario where only HEFA is cheap enough to be chosen,
        but UCO availability is exactly at the margin — the feedstock
        constraint binds, so the shadow price on demand satisfaction > 0.
        """
        demand   = _make_demand({"EU": 1.0})
        capacity = _make_capacity({"EU": 0.1})   # 0.1 MT cap → 0.085 effective → gap ~0.915 MT
        gaps     = supply_model.assess_gap(demand, capacity, 2025)

        # UCO tightly constrained: just barely enough for one unit of HEFA
        # HEFA needs 1.25 t UCO / MT SAF; gap ~0.915 / 0.85 ≈ 1.08 MT capacity needed
        # → UCO needed ≈ 1.08 × 1.25 ≈ 1.35 MT; set avail = 0.50 MT → HEFA blocked, must use others
        from config.settings import FEEDSTOCK_TYPES
        tight_feedstocks = [
            FeedstockAvailability(year=2025, region="EU", feedstock_type="UCO",
                                  max_available_mt=0.50, cost_usd_per_mt=350.0),
            FeedstockAvailability(year=2025, region="EU", feedstock_type="tallow",
                                  max_available_mt=0.50, cost_usd_per_mt=300.0),
        ] + [
            FeedstockAvailability(year=2025, region="EU", feedstock_type=ft,
                                  max_available_mt=50.0, cost_usd_per_mt=200.0)
            for ft in FEEDSTOCK_TYPES if ft not in ("UCO", "tallow")
        ]
        bundles = [RegionalFeedstockBundle(year=2025, region="EU", feedstocks=tight_feedstocks)]

        decision = supply_model.build_expansion_lp(gaps, bundles, 2025)

        assert decision.solver_status == "optimal"
        # Shadow price on demand constraint must be positive (cost of the last unit)
        shadow = decision.shadow_prices.get("EU", 0.0)
        assert shadow > 0, f"Expected positive shadow price, got {shadow}"


# ---------------------------------------------------------------------------
# Test 4: LP infeasible — all feedstocks near-zero → graceful failure
# ---------------------------------------------------------------------------

class TestInfeasibleLP:
    def test_returns_infeasible_status_without_raising(self, supply_model):
        demand   = _make_demand({"EU": 5.0})   # large demand
        capacity = _make_capacity({"EU": 0.01})
        gaps     = supply_model.assess_gap(demand, capacity, 2025)

        # Feedstock so scarce that no pathway can supply the gap
        bundles = [_feedstock_bundle("EU", 2025, avail_per_type=0.0001)]

        decision = supply_model.build_expansion_lp(gaps, bundles, 2025)

        assert decision.solver_status == "infeasible"
        assert decision.build_triggered is True
        assert decision.new_plants == []
        assert decision.warning_message is not None

    def test_warning_message_is_informative(self, supply_model):
        demand   = _make_demand({"EU": 5.0})
        capacity = _make_capacity({"EU": 0.01})
        gaps     = supply_model.assess_gap(demand, capacity, 2025)
        bundles  = [_feedstock_bundle("EU", 2025, avail_per_type=0.0001)]

        decision = supply_model.build_expansion_lp(gaps, bundles, 2025)

        assert "infeasible" in decision.warning_message.lower()


# ---------------------------------------------------------------------------
# Test 5: assess_gap correctness
# ---------------------------------------------------------------------------

class TestAssessGap:
    def test_zero_gap_for_fully_covered_region(self, supply_model):
        # Capacity exactly meets demand (with utilization factor)
        demand_mt = 0.5
        needed_cap = demand_mt / UTILIZATION_FACTOR   # capacity that exactly covers demand
        demand   = _make_demand({"EU": demand_mt})
        capacity = _make_capacity({"EU": needed_cap})

        gaps = supply_model.assess_gap(demand, capacity, 2025)

        assert abs(gaps["EU"]) < 1e-6

    def test_gap_equals_demand_when_no_capacity(self, supply_model):
        demand   = _make_demand({"EU": 0.5})
        capacity = CapacityState(year=2025, plants=[])   # no plants at all

        gaps = supply_model.assess_gap(demand, capacity, 2025)

        assert abs(gaps.get("EU", 0.5) - 0.5) < 1e-9

    def test_multiple_regions_assessed_independently(self, supply_model):
        demand   = _make_demand({"EU": 0.5, "US": 0.3})
        capacity = _make_capacity({"EU": 10.0, "US": 0.0})   # EU surplus, US short

        gaps = supply_model.assess_gap(demand, capacity, 2025)

        assert gaps["EU"] < 0      # surplus
        assert gaps["US"] > 0      # shortage


# ---------------------------------------------------------------------------
# apply_expansion
# ---------------------------------------------------------------------------

class TestApplyExpansion:
    def test_plant_count_increases_after_expansion(self, supply_model):
        capacity = _make_capacity({"EU": 0.1, "US": 0.1})
        demand   = _make_demand({"EU": 0.5, "US": 0.3})
        gaps     = supply_model.assess_gap(demand, capacity, 2025)
        bundles  = [_feedstock_bundle(r, 2025, 100.0) for r in ["EU", "US"]]

        decision = supply_model.build_expansion_lp(gaps, bundles, 2025)
        updated  = supply_model.apply_expansion(capacity, decision)

        assert len(updated.plants) > len(capacity.plants)

    def test_apply_with_no_new_plants_returns_same_count(self, supply_model):
        capacity = _make_capacity({"EU": 10.0})
        decision = ExpansionDecision(
            year=2025, new_plants=[], npv_cost_usd=0.0,
            solver_status="not_needed", shadow_prices={}, build_triggered=False,
        )
        updated = supply_model.apply_expansion(capacity, decision)
        assert len(updated.plants) == len(capacity.plants)

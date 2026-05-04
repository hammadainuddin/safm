"""Shared pytest fixtures for unit and integration tests."""

import pytest

from config.settings import MT_TO_PJ_FACTOR
from schemas.demand_schema import DemandMatrix, DemandRecord
from schemas.equilibrium_schema import MarketClearingResult, RegionalPrice, TradeFlow
from schemas.feedstock_schema import FeedstockAvailability, RegionalFeedstockBundle
from schemas.supply_schema import CapacityState, ExpansionDecision, PlantRecord


def make_demand_record(year=2025, region="EU", volume_mt=0.5, source="test") -> DemandRecord:
    return DemandRecord(
        year=year,
        region=region,
        volume_mt=volume_mt,
        energy_pj=round(volume_mt * MT_TO_PJ_FACTOR, 6),
        source=source,
    )


@pytest.fixture
def minimal_demand_matrix() -> DemandMatrix:
    """3-region, single-year demand matrix for 2025."""
    return DemandMatrix(
        records=[
            make_demand_record(region="EU",   volume_mt=0.5),
            make_demand_record(region="US",   volume_mt=0.3),
            make_demand_record(region="APAC", volume_mt=0.2),
        ],
        scenario_name="test",
    )


@pytest.fixture
def abundant_capacity_state() -> CapacityState:
    """One large plant per region — covers demand without triggering LP."""
    plants = [
        PlantRecord(
            plant_id=f"P_{r}", region=r, pathway="HEFA",
            capacity_mt_yr=5.0, online_year=2025,
            capex_usd_per_mt=800.0, opex_usd_per_mt=350.0,
            feedstock_intensity={"UCO": 1.25},
            is_deterministic=True,
        )
        for r in ["EU", "US", "APAC"]
    ]
    return CapacityState(year=2025, plants=plants)


@pytest.fixture
def tight_capacity_state() -> CapacityState:
    """One small plant per region — insufficient; LP will be triggered."""
    plants = [
        PlantRecord(
            plant_id=f"P_{r}", region=r, pathway="HEFA",
            capacity_mt_yr=0.1, online_year=2025,
            capex_usd_per_mt=800.0, opex_usd_per_mt=350.0,
            feedstock_intensity={"UCO": 1.25},
            is_deterministic=True,
        )
        for r in ["EU", "US", "APAC"]
    ]
    return CapacityState(year=2025, plants=plants)


@pytest.fixture
def feedstock_bundles_abundant() -> list:
    """Feedstock availability that comfortably covers any reasonable expansion."""
    return [
        RegionalFeedstockBundle(
            year=2025, region=r,
            feedstocks=[
                FeedstockAvailability(year=2025, region=r, feedstock_type="UCO",
                                      max_available_mt=100.0, cost_usd_per_mt=350.0),
                FeedstockAvailability(year=2025, region=r, feedstock_type="tallow",
                                      max_available_mt=50.0, cost_usd_per_mt=300.0),
                FeedstockAvailability(year=2025, region=r, feedstock_type="agricultural_residue",
                                      max_available_mt=80.0, cost_usd_per_mt=200.0),
                FeedstockAvailability(year=2025, region=r, feedstock_type="MSW",
                                      max_available_mt=60.0, cost_usd_per_mt=150.0),
                FeedstockAvailability(year=2025, region=r, feedstock_type="CO2_green_H2",
                                      max_available_mt=30.0, cost_usd_per_mt=800.0),
                FeedstockAvailability(year=2025, region=r, feedstock_type="other",
                                      max_available_mt=40.0, cost_usd_per_mt=250.0),
            ]
        )
        for r in ["EU", "US", "APAC"]
    ]


@pytest.fixture
def feedstock_bundles_tight() -> list:
    """Feedstock availability so small it cannot cover the demand gap — forces LP infeasibility."""
    return [
        RegionalFeedstockBundle(
            year=2025, region=r,
            feedstocks=[
                FeedstockAvailability(year=2025, region=r, feedstock_type=ft,
                                      max_available_mt=0.001, cost_usd_per_mt=350.0)
                for ft in ["UCO", "tallow", "agricultural_residue", "MSW", "CO2_green_H2", "other"]
            ]
        )
        for r in ["EU", "US", "APAC"]
    ]

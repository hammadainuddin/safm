"""Unit tests for all Pydantic schemas — validate rejection of malformed data."""

import pytest
from pydantic import ValidationError

from config.settings import MT_TO_PJ_FACTOR
from schemas.demand_schema import DemandMatrix, DemandRecord
from schemas.equilibrium_schema import (
    MarketClearingResult,
    RegionalPrice,
    TradeFlow,
)
from schemas.feedstock_schema import FeedstockAvailability
from schemas.supply_schema import CapacityState, ExpansionDecision, PlantRecord


# ---------------------------------------------------------------------------
# DemandRecord
# ---------------------------------------------------------------------------

class TestDemandRecord:
    def _valid(self, **kwargs):
        defaults = dict(year=2025, region="EU", volume_mt=1.0,
                        energy_pj=round(1.0 * MT_TO_PJ_FACTOR, 6), source="test")
        defaults.update(kwargs)
        return DemandRecord(**defaults)

    def test_valid_record(self):
        r = self._valid()
        assert r.year == 2025
        assert r.volume_mt == 1.0

    def test_rejects_year_before_horizon(self):
        with pytest.raises(ValidationError, match="outside model horizon"):
            self._valid(year=2020)

    def test_rejects_year_after_horizon(self):
        with pytest.raises(ValidationError, match="outside model horizon"):
            self._valid(year=2050)

    def test_rejects_negative_volume(self):
        with pytest.raises(ValidationError, match="non-negative"):
            self._valid(volume_mt=-0.1, energy_pj=0.0)

    def test_rejects_inconsistent_energy_pj(self):
        with pytest.raises(ValidationError, match="inconsistent"):
            self._valid(volume_mt=1.0, energy_pj=999.0)

    def test_boundary_year_2045(self):
        r = self._valid(year=2045)
        assert r.year == 2045

    def test_zero_volume_allowed(self):
        r = self._valid(volume_mt=0.0, energy_pj=0.0)
        assert r.volume_mt == 0.0

    def test_pathway_mix_must_sum_to_one(self):
        with pytest.raises(ValidationError, match="sum to 1.0"):
            self._valid(pathway_mix={"HEFA": 0.5, "ATJ": 0.3})

    def test_valid_pathway_mix(self):
        r = self._valid(pathway_mix={"HEFA": 0.6, "ATJ": 0.4})
        assert r.pathway_mix is not None


# ---------------------------------------------------------------------------
# DemandMatrix
# ---------------------------------------------------------------------------

class TestDemandMatrix:
    def _matrix(self):
        return DemandMatrix(
            records=[
                DemandRecord(year=2025, region=r, volume_mt=v,
                             energy_pj=round(v * MT_TO_PJ_FACTOR, 6), source="test")
                for r, v in [("EU", 0.5), ("US", 0.3), ("APAC", 0.2)]
            ],
            scenario_name="test",
        )

    def test_get_year_returns_correct_records(self):
        m = self._matrix()
        records_2025 = m.get_year(2025)
        assert len(records_2025) == 3

    def test_total_volume_mt(self):
        m = self._matrix()
        assert abs(m.total_volume_mt(2025) - 1.0) < 1e-9

    def test_volume_by_region(self):
        m = self._matrix()
        vbr = m.volume_by_region(2025)
        assert abs(vbr["EU"] - 0.5) < 1e-9

    def test_to_dataframe_shape(self):
        m = self._matrix()
        df = m.to_dataframe()
        assert len(df) == 3
        assert "volume_mt" in df.columns


# ---------------------------------------------------------------------------
# PlantRecord
# ---------------------------------------------------------------------------

class TestPlantRecord:
    def test_rejects_invalid_pathway(self):
        with pytest.raises(ValidationError, match="pathway"):
            PlantRecord(
                plant_id="P1", region="EU", pathway="INVALID",
                capacity_mt_yr=1.0, online_year=2025,
                capex_usd_per_mt=800.0, opex_usd_per_mt=350.0,
                feedstock_intensity={"UCO": 1.25},
            )

    def test_rejects_negative_capacity(self):
        with pytest.raises(ValidationError, match="non-negative"):
            PlantRecord(
                plant_id="P1", region="EU", pathway="HEFA",
                capacity_mt_yr=-1.0, online_year=2025,
                capex_usd_per_mt=800.0, opex_usd_per_mt=350.0,
                feedstock_intensity={"UCO": 1.25},
            )


# ---------------------------------------------------------------------------
# CapacityState helper methods
# ---------------------------------------------------------------------------

class TestCapacityState:
    def _state(self):
        plants = [
            PlantRecord(plant_id=f"P_{r}", region=r, pathway="HEFA",
                        capacity_mt_yr=cap, online_year=2025,
                        capex_usd_per_mt=800.0, opex_usd_per_mt=350.0,
                        feedstock_intensity={"UCO": 1.25})
            for r, cap in [("EU", 1.0), ("EU", 0.5), ("US", 0.8)]
        ]
        return CapacityState(year=2025, plants=plants)

    def test_total_capacity_aggregates_by_region(self):
        state = self._state()
        totals = state.total_capacity_by_region()
        assert abs(totals["EU"] - 1.5) < 1e-9
        assert abs(totals["US"] - 0.8) < 1e-9

    def test_effective_supply_applies_utilization(self):
        state = self._state()
        effective = state.effective_supply_by_region(utilization=0.85)
        assert abs(effective["EU"] - 1.5 * 0.85) < 1e-9


# ---------------------------------------------------------------------------
# TradeFlow and RegionalPrice
# ---------------------------------------------------------------------------

class TestEquilibriumSchemas:
    def test_valid_trade_flow(self):
        tf = TradeFlow(year=2025, origin_region="US", destination_region="EU",
                       volume_mt=0.1, transport_cost_usd_per_mt=45.0)
        assert tf.volume_mt == 0.1

    def test_trade_flow_rejects_negative_volume(self):
        with pytest.raises(ValidationError, match="non-negative"):
            TradeFlow(year=2025, origin_region="US", destination_region="EU",
                      volume_mt=-0.1, transport_cost_usd_per_mt=45.0)

    def test_regional_price_rejects_invalid_regime(self):
        with pytest.raises(ValidationError, match="pricing_regime"):
            RegionalPrice(year=2025, region="EU",
                          clearing_price_usd_per_mt=1200.0,
                          pricing_regime="unknown_regime")

    def test_market_clearing_result_helpers(self):
        flows = [
            TradeFlow(year=2025, origin_region="US", destination_region="EU",
                      volume_mt=0.1, transport_cost_usd_per_mt=45.0),
            TradeFlow(year=2025, origin_region="APAC", destination_region="EU",
                      volume_mt=0.05, transport_cost_usd_per_mt=65.0),
        ]
        prices = [
            RegionalPrice(year=2025, region=r,
                          clearing_price_usd_per_mt=1200.0,
                          pricing_regime="voluntary_cost_plus")
            for r in ["EU", "US", "APAC"]
        ]
        result = MarketClearingResult(
            year=2025, trade_flows=flows, prices=prices,
            total_saf_traded_mt=0.15, total_saf_produced_mt=1.0,
            market_balanced=True, solver_status="optimal", objective_value=500.0,
        )
        assert len(result.flows_to("EU")) == 2
        assert result.price_for_region("US") is not None


# ---------------------------------------------------------------------------
# FeedstockAvailability
# ---------------------------------------------------------------------------

class TestFeedstockSchema:
    def test_rejects_negative_availability(self):
        with pytest.raises(ValidationError, match="non-negative"):
            FeedstockAvailability(year=2025, region="EU", feedstock_type="UCO",
                                  max_available_mt=-1.0)

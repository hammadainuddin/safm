"""Unit tests for the demand module (Module 1)."""

import os

import pandas as pd
import pytest

from config.settings import MODEL_END_YEAR, MODEL_START_YEAR, MT_TO_PJ_FACTOR, REGIONS
from modules.demand_model import DemandModel
from schemas.demand_schema import DemandMatrix, DemandRecord

_MOCK_CSV = os.path.join(os.path.dirname(__file__), "..", "..", "data", "mock", "demand_mock.csv")


@pytest.fixture
def model() -> DemandModel:
    return DemandModel(data_path=_MOCK_CSV, scenario="test")


# ---------------------------------------------------------------------------
# CSV loading and schema validation
# ---------------------------------------------------------------------------

class TestDemandModelLoading:
    def test_loads_full_matrix(self, model):
        matrix = model.load_all()
        assert isinstance(matrix, DemandMatrix)

    def test_total_record_count(self, model):
        matrix = model.load_all()
        # 6 regions × 21 years = 126 records
        assert len(matrix.records) == len(REGIONS) * (MODEL_END_YEAR - MODEL_START_YEAR + 1)

    def test_all_years_present(self, model):
        matrix = model.load_all()
        years_present = {r.year for r in matrix.records}
        assert years_present == set(range(MODEL_START_YEAR, MODEL_END_YEAR + 1))

    def test_all_regions_present(self, model):
        matrix = model.load_all()
        regions_present = {r.region for r in matrix.records}
        assert regions_present == set(REGIONS)

    def test_all_volumes_non_negative(self, model):
        matrix = model.load_all()
        assert all(r.volume_mt >= 0 for r in matrix.records)

    def test_energy_pj_consistent_with_volume(self, model):
        matrix = model.load_all()
        for r in matrix.records:
            expected = round(r.volume_mt * MT_TO_PJ_FACTOR, 6)
            assert abs(r.energy_pj - expected) < 1e-4, (
                f"Energy inconsistency for {r.region} {r.year}: "
                f"{r.energy_pj} vs expected {expected}"
            )

    def test_caching_returns_same_object(self, model):
        m1 = model.load_all()
        m2 = model.load_all()
        assert m1 is m2   # same in-memory object, not reloaded


# ---------------------------------------------------------------------------
# get_demand_for_year
# ---------------------------------------------------------------------------

class TestGetDemandForYear:
    def test_returns_one_record_per_region(self, model):
        records = model.get_demand_for_year(2025)
        assert len(records) == len(REGIONS)

    def test_all_regions_covered_for_every_year(self, model):
        for year in [2025, 2030, 2035, 2040, 2045]:
            records = model.get_demand_for_year(year)
            regions_returned = {r.region for r in records}
            assert regions_returned == set(REGIONS), f"Missing regions in {year}"

    def test_rejects_year_outside_horizon(self, model):
        with pytest.raises(ValueError):
            model.get_demand_for_year(2020)

    def test_rejects_year_beyond_horizon(self, model):
        with pytest.raises(ValueError):
            model.get_demand_for_year(2050)


# ---------------------------------------------------------------------------
# Demand growth trajectory sanity checks
# ---------------------------------------------------------------------------

class TestDemandTrajectory:
    def test_global_demand_grows_over_time(self, model):
        d2025 = model.total_global_demand(2025)
        d2035 = model.total_global_demand(2035)
        d2045 = model.total_global_demand(2045)
        assert d2025 < d2035 < d2045

    def test_eu_demand_grows_monotonically(self, model):
        eu_volumes = [
            next(r.volume_mt for r in model.get_demand_for_year(y) if r.region == "EU")
            for y in range(2025, 2046)
        ]
        assert all(eu_volumes[i] <= eu_volumes[i+1] for i in range(len(eu_volumes)-1))

    def test_eu_demand_2045_exceeds_2025_by_large_factor(self, model):
        eu_2025 = next(r.volume_mt for r in model.get_demand_for_year(2025) if r.region == "EU")
        eu_2045 = next(r.volume_mt for r in model.get_demand_for_year(2045) if r.region == "EU")
        assert eu_2045 / eu_2025 >= 10.0   # >10× growth: ReFuelEU mandate ramp

    def test_global_demand_2045_reasonable_scale(self, model):
        d2045 = model.total_global_demand(2045)
        # Should be in the range 50–150 MT (consistent with IATA/IEA net zero scenarios)
        assert 30.0 <= d2045 <= 200.0


# ---------------------------------------------------------------------------
# volume_by_region helper
# ---------------------------------------------------------------------------

class TestVolumeByRegion:
    def test_returns_dict_for_all_regions(self, model):
        vbr = model.volume_by_region(2030)
        assert set(vbr.keys()) == set(REGIONS)

    def test_values_match_get_demand_for_year(self, model):
        vbr = model.volume_by_region(2030)
        records = model.get_demand_for_year(2030)
        for r in records:
            assert abs(vbr[r.region] - r.volume_mt) < 1e-9


# ---------------------------------------------------------------------------
# plug_in_external_model interface
# ---------------------------------------------------------------------------

class TestPlugInExternalModel:
    def _make_df(self, years=None, regions=None):
        years = years or [2025, 2030]
        regions = regions or ["EU", "US", "APAC"]
        rows = []
        for y in years:
            for reg in regions:
                rows.append({"year": y, "region": reg, "volume_mt": 1.0})
        return pd.DataFrame(rows)

    def test_accepts_valid_dataframe(self, model):
        df = self._make_df()
        matrix = model.plug_in_external_model(df)
        assert isinstance(matrix, DemandMatrix)
        assert len(matrix.records) == 6   # 2 years × 3 regions

    def test_source_field_is_bottom_up_model(self, model):
        df = self._make_df()
        matrix = model.plug_in_external_model(df)
        assert all(r.source == "bottom_up_model" for r in matrix.records)

    def test_rejects_df_missing_required_columns(self, model):
        df = pd.DataFrame([{"year": 2025, "region": "EU"}])   # missing volume_mt
        with pytest.raises(ValueError, match="missing columns"):
            model.plug_in_external_model(df)

    def test_energy_pj_auto_derived(self, model):
        df = self._make_df([2025], ["EU"])
        matrix = model.plug_in_external_model(df)
        r = matrix.records[0]
        expected_pj = round(1.0 * MT_TO_PJ_FACTOR, 6)
        assert abs(r.energy_pj - expected_pj) < 1e-6


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_raises_on_missing_csv(self):
        model = DemandModel(data_path="/nonexistent/path.csv")
        with pytest.raises(FileNotFoundError):
            model.load_all()

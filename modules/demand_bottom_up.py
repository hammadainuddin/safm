"""
Bottom-Up Flight Demand Module
================================
Derives SAF demand from CORSIA-eligible international flights and national
blending mandates. Demand is attributed to the refuelling airport's region
(CORSIA uplift-based accounting): 60% origin, 40% destination.

Output: DemandMatrix — same schema as the existing mock CSV demand, making
this a drop-in replacement for DemandModel.load_all().
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from functools import lru_cache
from typing import Dict, List, Optional

import pandas as pd

from config.settings import (
    MODEL_END_YEAR,
    MODEL_START_YEAR,
    MT_TO_PJ_FACTOR,
    REGIONS,
    ROUTE_SAMPLE_FRACTION,
)
from schemas.demand_schema import DemandMatrix, DemandRecord
from schemas.flight_schema import AircraftType, AirlineRecord, BottomUpDemandResult, FlightRoute
from utils.logging_config import get_logger

logger = get_logger("demand_bottom_up")

_MOCK = os.path.join(os.path.dirname(__file__), "..", "data", "mock")

# Fraction of fuel attributed to origin (departure) airport region.
# Reflects CORSIA uplift rule: airlines report SAF uplift at departure airport.
_ORIGIN_SHARE = 0.60
_DEST_SHARE   = 1.0 - _ORIGIN_SHARE

# Fuel efficiency improves 1.5% per year from 2025 base (fleet renewal).
_EFFICIENCY_IMPROVEMENT_PA = 0.015


class BottomUpDemandModule:
    """
    Estimates annual SAF demand from:
      1. International flights under CORSIA mandatory offsetting
      2. Domestic/regional flights under national blending mandates

    All demand is attributed to the refuelling airport's region (60/40 split
    between origin and destination for international flights).
    """

    def __init__(
        self,
        routes_path: str = None,
        aircraft_path: str = None,
        corsia_path: str = None,
        mandates_path: str = None,
    ):
        self._routes_path   = routes_path   or os.path.join(_MOCK, "flight_routes.csv")
        self._aircraft_path = aircraft_path or os.path.join(_MOCK, "aircraft_types.csv")
        self._corsia_path   = corsia_path   or os.path.join(_MOCK, "corsia_schedule.csv")
        self._mandates_path = mandates_path or os.path.join(_MOCK, "national_blending_mandates.csv")
        self._routes_cache: Optional[pd.DataFrame]   = None
        self._aircraft_cache: Optional[Dict[str, float]] = None  # {type: efficiency}
        self._corsia_cache:   Optional[pd.DataFrame] = None
        self._mandates_cache: Optional[pd.DataFrame] = None

    # ── Public interface ─────────────────────────────────────────────────────

    def estimate_demand(
        self, year: int, scenario: str = "baseline"
    ) -> DemandMatrix:
        """
        Compute SAF demand for a given year and return a validated DemandMatrix.

        Parameters
        ----------
        year     : model year (2025–2045)
        scenario : scenario tag embedded in the returned DemandMatrix

        Returns
        -------
        DemandMatrix — same schema as mock CSV demand, ready for the model loop
        """
        if not (MODEL_START_YEAR <= year <= MODEL_END_YEAR):
            raise ValueError(f"year {year} outside model horizon {MODEL_START_YEAR}–{MODEL_END_YEAR}")

        result = self._compute_demand(year)
        records = self._build_demand_records(result, year)

        matrix = DemandMatrix(
            records=records,
            scenario_name=scenario,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        logger.info(
            "Year %d — bottom-up demand: total SAF = %.4f MT (CORSIA=%.4f, mandate=%.4f)",
            year,
            sum(result.saf_demand_by_region.values()),
            sum(result.corsia_saf_demand_by_region.values()),
            sum(result.mandate_saf_demand_by_region.values()),
        )
        return matrix

    def get_intermediate_result(self, year: int) -> BottomUpDemandResult:
        """Return the BottomUpDemandResult (useful for diagnostics and UI)."""
        return self._compute_demand(year)

    # ── Internal computation ─────────────────────────────────────────────────

    def _compute_demand(self, year: int) -> BottomUpDemandResult:
        routes     = self._load_routes()
        efficiency = self._load_aircraft_efficiency()
        corsia_row = self._load_corsia_schedule().query("year == @year").iloc[0]
        mandates_df = self._load_mandates()

        corsia_frac = float(corsia_row["mandatory_fraction"])
        mandate_by_region: Dict[str, float] = {}
        for region in REGIONS:
            rows = mandates_df[(mandates_df["year"] == year) & (mandates_df["region"] == region)]
            mandate_by_region[region] = float(rows["mandate_fraction"].iloc[0]) if not rows.empty else 0.0

        # Annual growth and efficiency improvement for this year
        yr_offset = year - MODEL_START_YEAR
        eff_factor = (1 - _EFFICIENCY_IMPROVEMENT_PA) ** yr_offset

        fuel_by_region: Dict[str, float] = {r: 0.0 for r in REGIONS}
        corsia_by_region: Dict[str, float] = {r: 0.0 for r in REGIONS}
        mandate_by_region_saf: Dict[str, float] = {r: 0.0 for r in REGIONS}

        for _, row in routes.iterrows():
            actype = row["aircraft_type"]
            base_eff = efficiency.get(actype)
            if base_eff is None:
                logger.warning("Unknown aircraft type %s for route %s — skipping", actype, row["route_id"])
                continue

            # Flights in this year: apply route-specific growth rate
            growth_rate = float(row.get("annual_growth_rate", 0.04))
            annual_flights = float(row["annual_flights_2025"]) * (1 + growth_rate) ** yr_offset

            # Fuel burn (tonnes) = flights × distance × efficiency × improvement
            fuel_t = annual_flights * float(row["distance_km"]) * base_eff * eff_factor
            fuel_mt = fuel_t / 1_000  # convert to MT (millions of tonnes)

            o_region = str(row["origin_region"])
            d_region = str(row["dest_region"])
            ftype    = str(row["flight_type"])

            if ftype == "international":
                # CORSIA: attribute 60% to origin region, 40% to destination
                if o_region in fuel_by_region:
                    fuel_by_region[o_region] += fuel_mt * _ORIGIN_SHARE
                if d_region in fuel_by_region:
                    fuel_by_region[d_region] += fuel_mt * _DEST_SHARE

                # CORSIA SAF demand
                corsia_saf = fuel_mt * corsia_frac
                if o_region in corsia_by_region:
                    corsia_by_region[o_region] += corsia_saf * _ORIGIN_SHARE
                if d_region in corsia_by_region:
                    corsia_by_region[d_region] += corsia_saf * _DEST_SHARE

            elif ftype == "domestic":
                # Domestic: 100% attributed to origin region
                if o_region in fuel_by_region:
                    fuel_by_region[o_region] += fuel_mt

                # Blending mandate (domestic only)
                m_frac = mandate_by_region.get(o_region, 0.0)
                if m_frac > 0 and o_region in mandate_by_region_saf:
                    mandate_by_region_saf[o_region] += fuel_mt * m_frac

        # Scale CORSIA demand: 64 routes ≈ ROUTE_SAMPLE_FRACTION of global traffic.
        # Mandate demand is a policy target (not sampled) so it is NOT scaled.
        scaled_corsia = {r: corsia_by_region[r] * ROUTE_SAMPLE_FRACTION for r in REGIONS}

        total_by_region = {
            r: round(scaled_corsia[r] + mandate_by_region_saf[r], 8)
            for r in REGIONS
        }

        return BottomUpDemandResult(
            year=year,
            fuel_by_region={r: round(v, 8) for r, v in fuel_by_region.items()},
            corsia_saf_demand_by_region={r: round(v, 8) for r, v in scaled_corsia.items()},
            mandate_saf_demand_by_region={r: round(v, 8) for r, v in mandate_by_region_saf.items()},
            saf_demand_by_region=total_by_region,
            corsia_fraction_applied=corsia_frac,
            mandate_fraction_by_region={r: mandate_by_region.get(r, 0.0) for r in REGIONS},
        )

    @staticmethod
    def _build_demand_records(
        result: BottomUpDemandResult, year: int
    ) -> List[DemandRecord]:
        records = []
        for region in REGIONS:
            vol = result.saf_demand_by_region.get(region, 0.0)
            vol = max(0.0, vol)   # guard against floating-point negatives
            records.append(DemandRecord(
                year=year,
                region=region,
                volume_mt=round(vol, 8),
                energy_pj=round(vol * MT_TO_PJ_FACTOR, 8),
                source="bottom_up_flight_data",
            ))
        return records

    # ── Data loaders (cached) ────────────────────────────────────────────────

    def _load_routes(self) -> pd.DataFrame:
        if self._routes_cache is None:
            self._routes_cache = pd.read_csv(self._routes_path)
        return self._routes_cache

    def _load_aircraft_efficiency(self) -> Dict[str, float]:
        if self._aircraft_cache is None:
            df = pd.read_csv(self._aircraft_path)
            self._aircraft_cache = dict(zip(df["aircraft_type"], df["fuel_efficiency_t_per_km"]))
        return self._aircraft_cache

    def _load_corsia_schedule(self) -> pd.DataFrame:
        if self._corsia_cache is None:
            self._corsia_cache = pd.read_csv(self._corsia_path)
        return self._corsia_cache

    def _load_mandates(self) -> pd.DataFrame:
        if self._mandates_cache is None:
            self._mandates_cache = pd.read_csv(self._mandates_path)
        return self._mandates_cache

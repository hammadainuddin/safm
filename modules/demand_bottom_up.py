"""
Bottom-Up Flight Demand Module
================================
Two demand modes:

  Mode 1 — "corsia_schedule" (default / legacy):
      A single global CORSIA mandatory_fraction is read from corsia_schedule.csv
      and applied uniformly to all international routes.  National blending
      mandates from national_blending_mandates.csv are applied to domestic routes.
      A route_sample_fraction scales up from the sample to the full global fleet.

  Mode 2 — "route_targets":
      Per-route SAF% target columns (saf_pct_2025/2030/2035/2040/2045/2050) in
      flight_routes.csv are used directly.  Values are linearly interpolated
      between the key years for every model year.  Because the route dataset is
      comprehensive (full global coverage) route_sample_fraction defaults to 1.0
      and is ignored.

In both modes only international routes are included. Domestic routes are excluded.

Output: DemandMatrix — same schema as the mock CSV demand.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from config.settings import (
    MODEL_END_YEAR,
    MODEL_START_YEAR,
    MT_TO_PJ_FACTOR,
    REGIONS,
    ROUTE_SAMPLE_FRACTION as _DEFAULT_ROUTE_SAMPLE_FRACTION,
)
from schemas.demand_schema import DemandMatrix, DemandRecord
from schemas.flight_schema import AircraftType, AirlineRecord, BottomUpDemandResult, FlightRoute
from utils.logging_config import get_logger

logger = get_logger("demand_bottom_up")

_MOCK = os.path.join(os.path.dirname(__file__), "..", "data", "mock")

# SAF% key years present in the routes CSV
_SAF_KEY_YEARS = [2025, 2030, 2035, 2040, 2045, 2050]

# Fraction of fuel attributed to origin (departure) airport region.
_ORIGIN_SHARE = 0.60
_DEST_SHARE   = 1.0 - _ORIGIN_SHARE

# Fuel efficiency improves 1.5% per year from 2025 base (fleet renewal).
_EFFICIENCY_IMPROVEMENT_PA = 0.015


def _interpolate_saf_pct(row: pd.Series, year: int) -> float:
    """Linearly interpolate per-route SAF target for an arbitrary model year."""
    key_years = _SAF_KEY_YEARS
    col_vals  = [float(row.get(f"saf_pct_{y}", 0.0) or 0.0) for y in key_years]
    if year <= key_years[0]:
        return col_vals[0]
    if year >= key_years[-1]:
        return col_vals[-1]
    for i in range(len(key_years) - 1):
        if key_years[i] <= year <= key_years[i + 1]:
            t = (year - key_years[i]) / (key_years[i + 1] - key_years[i])
            return col_vals[i] + t * (col_vals[i + 1] - col_vals[i])
    return 0.0


class BottomUpDemandModule:
    """
    Estimates annual SAF demand from:
      Mode 1 — single global CORSIA schedule + national blending mandates
      Mode 2 — per-route country-specific SAF% targets (comprehensive route set)
    """

    def __init__(
        self,
        routes_path: str = None,
        aircraft_path: str = None,
        corsia_path: str = None,
        mandates_path: str = None,
        route_sample_fraction: float = None,
        demand_mode: str = "corsia_schedule",
        include_domestic: bool = False,
        efficiency_improvement_rate: float = None,
    ):
        """
        Parameters
        ----------
        demand_mode      : "corsia_schedule"  → Mode 1 (default, legacy behaviour)
                           "route_targets"    → Mode 2 (per-route SAF% interpolation)
        include_domestic : when True, domestic routes contribute fuel burn and
                           blending-mandate SAF demand; CORSIA is international-only
                           regardless. Default False (international routes only).
        efficiency_improvement_rate : annual fleet fuel-efficiency improvement
                           (fraction/yr). Defaults to _EFFICIENCY_IMPROVEMENT_PA
                           (1.5%/yr) when None.
        """
        self._routes_path   = routes_path   or os.path.join(_MOCK, "flight_routes.csv")
        self._aircraft_path = aircraft_path or os.path.join(_MOCK, "aircraft_types.csv")
        self._corsia_path   = corsia_path   or os.path.join(_MOCK, "corsia_schedule.csv")
        self._mandates_path = mandates_path or os.path.join(_MOCK, "national_blending_mandates.csv")
        self._demand_mode     = demand_mode
        self._include_domestic = include_domestic
        self._eff_rate = (
            efficiency_improvement_rate if efficiency_improvement_rate is not None
            else _EFFICIENCY_IMPROVEMENT_PA
        )

        # Mode 2 is a comprehensive dataset — no extrapolation needed.
        if demand_mode == "route_targets":
            self._route_sample_fraction = 1.0
        else:
            self._route_sample_fraction = (
                route_sample_fraction if route_sample_fraction is not None
                else _DEFAULT_ROUTE_SAMPLE_FRACTION
            )

        self._routes_cache:   Optional[pd.DataFrame]      = None
        self._aircraft_cache: Optional[Dict[str, float]]  = None
        self._corsia_cache:   Optional[pd.DataFrame]      = None
        self._mandates_cache: Optional[pd.DataFrame]      = None

    # ── Public interface ─────────────────────────────────────────────────────

    def estimate_demand(self, year: int, scenario: str = "baseline") -> DemandMatrix:
        if not (MODEL_START_YEAR <= year <= MODEL_END_YEAR):
            raise ValueError(f"year {year} outside model horizon {MODEL_START_YEAR}–{MODEL_END_YEAR}")

        result  = self._compute_demand(year)
        records = self._build_demand_records(result, year)

        matrix = DemandMatrix(
            records=records,
            scenario_name=scenario,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        logger.info(
            "Year %d [%s] — total SAF = %.4f MT (CORSIA/route=%.4f, mandate=%.4f)",
            year,
            self._demand_mode,
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
        if self._demand_mode == "route_targets":
            return self._compute_demand_route_targets(year)
        return self._compute_demand_corsia_schedule(year)

    # ── Mode 1: single global CORSIA schedule ────────────────────────────────

    def _compute_demand_corsia_schedule(self, year: int) -> BottomUpDemandResult:
        routes      = self._load_routes()
        efficiency  = self._load_aircraft_efficiency()
        corsia_row  = self._load_corsia_schedule().query("year == @year").iloc[0]
        mandates_df = self._load_mandates()

        corsia_frac = float(corsia_row["mandatory_fraction"])

        yr_mandates = mandates_df[mandates_df["year"] == year]
        mandate_by_region:  Dict[str, float] = {}
        mandate_by_country: Dict[str, float] = {}
        if "country" in yr_mandates.columns:
            for _, mrow in yr_mandates.iterrows():
                c    = str(mrow.get("country", "")).strip()
                r    = str(mrow["region"])
                frac = float(mrow["mandate_fraction"])
                if c and c != r:
                    mandate_by_country[c] = frac
                else:
                    mandate_by_region[r] = frac
        else:
            for region in REGIONS:
                rows = yr_mandates[yr_mandates["region"] == region]
                mandate_by_region[region] = float(rows["mandate_fraction"].iloc[0]) if not rows.empty else 0.0

        yr_offset  = year - MODEL_START_YEAR
        eff_factor = (1 - self._eff_rate) ** yr_offset

        fuel_by_region:        Dict[str, float] = {r: 0.0 for r in REGIONS}
        corsia_by_region:      Dict[str, float] = {r: 0.0 for r in REGIONS}
        mandate_by_region_saf: Dict[str, float] = {r: 0.0 for r in REGIONS}

        for _, row in routes.iterrows():
            actype   = row["aircraft_type"]
            base_eff = efficiency.get(actype)
            if base_eff is None:
                logger.warning("Unknown aircraft type %s for route %s — skipping", actype, row["route_id"])
                continue

            growth_rate    = float(row.get("annual_growth_rate", 0.04))
            annual_flights = float(row["annual_flights_2025"]) * (1 + growth_rate) ** yr_offset
            fuel_t         = annual_flights * float(row["distance_km"]) * base_eff * eff_factor
            fuel_mt        = fuel_t / 1_000_000

            o_region = str(row["origin_region"])
            d_region = str(row["dest_region"])
            ftype    = str(row["flight_type"])

            if ftype == "domestic" and not self._include_domestic:
                continue

            if ftype in ("international", "international-fleet"):
                if d_region == "MULTI" or ftype == "international-fleet":
                    # Fleet aggregate: attribute 100% to origin
                    if o_region in fuel_by_region:
                        fuel_by_region[o_region] += fuel_mt
                    corsia_saf = fuel_mt * corsia_frac
                    if o_region in corsia_by_region:
                        corsia_by_region[o_region] += corsia_saf
                else:
                    if o_region in fuel_by_region:
                        fuel_by_region[o_region] += fuel_mt * _ORIGIN_SHARE
                    if d_region in fuel_by_region:
                        fuel_by_region[d_region] += fuel_mt * _DEST_SHARE
                    corsia_saf = fuel_mt * corsia_frac
                    if o_region in corsia_by_region:
                        corsia_by_region[o_region] += corsia_saf * _ORIGIN_SHARE
                    if d_region in corsia_by_region:
                        corsia_by_region[d_region] += corsia_saf * _DEST_SHARE

            elif ftype == "domestic":
                if o_region in fuel_by_region:
                    fuel_by_region[o_region] += fuel_mt
                o_country = str(row.get("origin_country", "")).strip()
                m_frac    = mandate_by_country.get(o_country,
                            mandate_by_region.get(o_region, 0.0))
                if m_frac > 0 and o_region in mandate_by_region_saf:
                    mandate_by_region_saf[o_region] += fuel_mt * m_frac

        rsf = self._route_sample_fraction
        fuel_by_region        = {r: v / rsf for r, v in fuel_by_region.items()}
        scaled_corsia         = {r: corsia_by_region[r] / rsf for r in REGIONS}
        mandate_by_region_saf = {r: v / rsf for r, v in mandate_by_region_saf.items()}

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

    # ── Mode 2: per-route country-specific SAF% targets ──────────────────────

    def _compute_demand_route_targets(self, year: int) -> BottomUpDemandResult:
        routes     = self._load_routes()
        efficiency = self._load_aircraft_efficiency()

        yr_offset  = year - MODEL_START_YEAR
        eff_factor = (1 - self._eff_rate) ** yr_offset

        fuel_by_region:        Dict[str, float] = {r: 0.0 for r in REGIONS}
        corsia_by_region:      Dict[str, float] = {r: 0.0 for r in REGIONS}
        mandate_by_region_saf: Dict[str, float] = {r: 0.0 for r in REGIONS}

        for _, row in routes.iterrows():
            actype   = row["aircraft_type"]
            base_eff = efficiency.get(actype)
            if base_eff is None:
                logger.warning("Unknown aircraft type %s for route %s — skipping", actype, row["route_id"])
                continue

            growth_rate    = float(row.get("annual_growth_rate", 0.04))
            annual_flights = float(row["annual_flights_2025"]) * (1 + growth_rate) ** yr_offset
            fuel_t         = annual_flights * float(row["distance_km"]) * base_eff * eff_factor
            fuel_mt        = fuel_t / 1_000_000

            saf_frac = _interpolate_saf_pct(row, year)

            o_region = str(row["origin_region"])
            d_region = str(row["dest_region"])
            ftype    = str(row["flight_type"])

            if ftype == "domestic" and not self._include_domestic:
                continue

            if ftype in ("international", "international-fleet"):
                if d_region == "MULTI" or ftype == "international-fleet":
                    # Fleet aggregate or indeterminate destination: 100% to origin
                    if o_region in fuel_by_region:
                        fuel_by_region[o_region] += fuel_mt
                    saf_demand = fuel_mt * saf_frac
                    if o_region in corsia_by_region:
                        corsia_by_region[o_region] += saf_demand
                else:
                    if o_region in fuel_by_region:
                        fuel_by_region[o_region] += fuel_mt * _ORIGIN_SHARE
                    if d_region in fuel_by_region:
                        fuel_by_region[d_region] += fuel_mt * _DEST_SHARE
                    saf_demand = fuel_mt * saf_frac
                    if o_region in corsia_by_region:
                        corsia_by_region[o_region] += saf_demand * _ORIGIN_SHARE
                    if d_region in corsia_by_region:
                        corsia_by_region[d_region] += saf_demand * _DEST_SHARE

            elif ftype == "domestic":
                if o_region in fuel_by_region:
                    fuel_by_region[o_region] += fuel_mt
                saf_demand = fuel_mt * saf_frac
                if o_region in mandate_by_region_saf:
                    mandate_by_region_saf[o_region] += saf_demand

        total_by_region = {
            r: round(corsia_by_region[r] + mandate_by_region_saf[r], 8)
            for r in REGIONS
        }

        return BottomUpDemandResult(
            year=year,
            fuel_by_region={r: round(v, 8) for r, v in fuel_by_region.items()},
            corsia_saf_demand_by_region={r: round(v, 8) for r, v in corsia_by_region.items()},
            mandate_saf_demand_by_region={r: round(v, 8) for r, v in mandate_by_region_saf.items()},
            saf_demand_by_region=total_by_region,
            corsia_fraction_applied=0.0,   # not applicable in route_targets mode
            mandate_fraction_by_region={r: 0.0 for r in REGIONS},
        )

    # ── Shared helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _build_demand_records(result: BottomUpDemandResult, year: int) -> List[DemandRecord]:
        records = []
        for region in REGIONS:
            vol = max(0.0, result.saf_demand_by_region.get(region, 0.0))
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

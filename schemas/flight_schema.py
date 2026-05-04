"""
Flight and bottom-up demand schemas.
Used by BottomUpDemandModule to represent flight routes, aircraft fuel efficiency,
and the intermediate demand estimation results.
"""

from __future__ import annotations

from typing import Dict, List, Literal

from pydantic import BaseModel, field_validator


class AircraftType(BaseModel):
    aircraft_type: str
    fuel_efficiency_t_per_km: float  # tonnes of jet fuel per km (whole aircraft)
    notes: str = ""

    @field_validator("fuel_efficiency_t_per_km")
    @classmethod
    def _positive_efficiency(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("fuel_efficiency_t_per_km must be > 0")
        return v


class AirlineRecord(BaseModel):
    airline_id: str
    airline_name: str
    home_country: str
    home_region: str
    hub_airport: str
    hub_country: str
    hub_region: str


class FlightRoute(BaseModel):
    route_id: str
    airline_id: str
    origin_airport: str
    origin_country: str
    origin_region: str
    dest_airport: str
    dest_country: str
    dest_region: str
    annual_flights_base: int      # 2025 base year count
    distance_km: float
    aircraft_type: str
    flight_type: Literal["international", "domestic"]
    annual_growth_rate: float = 0.04  # default 4% pa flight growth

    @field_validator("distance_km")
    @classmethod
    def _positive_distance(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("distance_km must be > 0")
        return v

    @field_validator("annual_flights_base")
    @classmethod
    def _positive_flights(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("annual_flights_base must be > 0")
        return v


class BottomUpDemandResult(BaseModel):
    """Intermediate result before conversion to DemandMatrix."""
    year: int
    fuel_by_region: Dict[str, float]              # total jet fuel burn (MT) by region
    corsia_saf_demand_by_region: Dict[str, float] # CORSIA-driven SAF demand (MT)
    mandate_saf_demand_by_region: Dict[str, float]# domestic mandate SAF demand (MT)
    saf_demand_by_region: Dict[str, float]        # total = CORSIA + mandate
    corsia_fraction_applied: float
    mandate_fraction_by_region: Dict[str, float]

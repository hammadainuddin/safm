"""Demand module data contracts — output of Module 1, input to Modules 2 and 3."""

from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd
from pydantic import BaseModel, field_validator, model_validator

from config.settings import MT_TO_PJ_FACTOR, MODEL_START_YEAR, MODEL_END_YEAR


class DemandRecord(BaseModel):
    """One region-year SAF demand observation."""

    year: int
    region: str
    volume_mt: float
    energy_pj: float
    pathway_mix: Optional[Dict[str, float]] = None   # {pathway: fraction}, sums to 1.0
    source: str = "mock"

    @field_validator("year")
    @classmethod
    def year_in_horizon(cls, v: int) -> int:
        if not (MODEL_START_YEAR <= v <= MODEL_END_YEAR):
            raise ValueError(f"year {v} is outside model horizon {MODEL_START_YEAR}–{MODEL_END_YEAR}")
        return v

    @field_validator("volume_mt")
    @classmethod
    def non_negative_volume(cls, v: float) -> float:
        if v < 0:
            raise ValueError("volume_mt must be non-negative")
        return v

    @field_validator("energy_pj")
    @classmethod
    def non_negative_energy(cls, v: float) -> float:
        if v < 0:
            raise ValueError("energy_pj must be non-negative")
        return v

    @model_validator(mode="after")
    def energy_consistent_with_volume(self) -> "DemandRecord":
        expected = round(self.volume_mt * MT_TO_PJ_FACTOR, 6)
        tol = max(0.001 * expected, 1e-9)
        if abs(self.energy_pj - expected) > tol:
            raise ValueError(
                f"energy_pj {self.energy_pj:.6f} is inconsistent with "
                f"volume_mt {self.volume_mt:.6f} (expected {expected:.6f} PJ)"
            )
        return self

    @model_validator(mode="after")
    def pathway_mix_sums_to_one(self) -> "DemandRecord":
        if self.pathway_mix is not None:
            total = sum(self.pathway_mix.values())
            if abs(total - 1.0) > 1e-6:
                raise ValueError(f"pathway_mix fractions must sum to 1.0 (got {total:.6f})")
        return self


class DemandMatrix(BaseModel):
    """Full demand dataset: one DemandRecord per region-year combination."""

    records: List[DemandRecord]
    scenario_name: str = "baseline"
    created_at: Optional[str] = None   # ISO-8601 timestamp, set by loader

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame([r.model_dump() for r in self.records])

    def get_year(self, year: int) -> List[DemandRecord]:
        return [r for r in self.records if r.year == year]

    def total_volume_mt(self, year: int) -> float:
        return sum(r.volume_mt for r in self.get_year(year))

    def volume_by_region(self, year: int) -> Dict[str, float]:
        return {r.region: r.volume_mt for r in self.get_year(year)}

"""Supply module data contracts — capacity state, deterministic plants, expansion decisions."""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, field_validator

from config.settings import UTILIZATION_FACTOR, SAF_PATHWAYS


class PlantRecord(BaseModel):
    """A single SAF production plant (deterministic or endogenously built)."""

    plant_id: str
    region: str
    pathway: str
    capacity_mt_yr: float            # nameplate capacity, million tonnes / year
    online_year: int
    capex_usd_per_mt: float          # overnight CAPEX, USD per MT/yr of nameplate capacity
    opex_usd_per_mt: float           # annual OPEX (fixed + variable), USD / MT produced
    feedstock_intensity: Dict[str, float]   # {feedstock_type: tonnes feedstock per MT SAF}
    is_deterministic: bool = True    # False = built by the LP expansion solver

    @field_validator("pathway")
    @classmethod
    def valid_pathway(cls, v: str) -> str:
        if v not in SAF_PATHWAYS:
            raise ValueError(f"pathway '{v}' not in {SAF_PATHWAYS}")
        return v

    @field_validator("capacity_mt_yr", "capex_usd_per_mt", "opex_usd_per_mt")
    @classmethod
    def non_negative_numeric(cls, v: float) -> float:
        if v < 0:
            raise ValueError("capacity, capex, and opex must be non-negative")
        return v


class CapacityState(BaseModel):
    """Snapshot of all operating plants in a given model year."""

    year: int
    plants: List[PlantRecord]

    def total_capacity_by_region(self) -> Dict[str, float]:
        result: Dict[str, float] = {}
        for p in self.plants:
            result[p.region] = result.get(p.region, 0.0) + p.capacity_mt_yr
        return result

    def capacity_by_region_pathway(self) -> Dict[str, Dict[str, float]]:
        result: Dict[str, Dict[str, float]] = {}
        for p in self.plants:
            result.setdefault(p.region, {})
            result[p.region][p.pathway] = result[p.region].get(p.pathway, 0.0) + p.capacity_mt_yr
        return result

    def effective_supply_by_region(self, utilization: float = UTILIZATION_FACTOR) -> Dict[str, float]:
        return {r: cap * utilization for r, cap in self.total_capacity_by_region().items()}

    def plants_online_in(self, year: int) -> List[PlantRecord]:
        return [p for p in self.plants if p.online_year <= year]


class ExpansionDecision(BaseModel):
    """Output of the least-cost capacity expansion LP solver."""

    year: int
    new_plants: List[PlantRecord]
    npv_cost_usd: float
    solver_status: str               # "optimal" | "infeasible" | "not_needed" | "warning"
    shadow_prices: Dict[str, float]  # {region: dual value on demand-satisfaction constraint}
    build_triggered: bool
    warning_message: Optional[str] = None

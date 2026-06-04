"""Annual model state bundle — passed from year t to year t+1 in the dynamic loop."""

from __future__ import annotations

from typing import Dict, List

from pydantic import BaseModel, field_validator

from schemas.demand_schema import DemandMatrix
from schemas.equilibrium_schema import MarketClearingResult
from schemas.feedstock_schema import FeedstockAvailability
from schemas.supply_schema import CapacityState, ExpansionDecision


class ModelState(BaseModel):
    """Complete state snapshot at the end of model year t."""

    year: int
    demand: DemandMatrix
    capacity: CapacityState
    expansion: ExpansionDecision
    market: MarketClearingResult
    cumulative_capacity_by_region: Dict[str, float]
    feedstock_remaining: List[FeedstockAvailability]

    class Config:
        arbitrary_types_allowed = True

    @field_validator("demand", mode="before")
    @classmethod
    def _coerce_demand(cls, v):
        # Streamlit's file watcher can reload schema modules mid-run, creating a
        # new DemandMatrix class object. Pydantic v2's isinstance check then fails
        # even though the data is structurally identical. Coerce via model_dump()
        # so validation always succeeds regardless of class identity.
        from schemas.demand_schema import DemandMatrix as _DM
        if isinstance(v, dict):
            return v
        if isinstance(v, _DM):
            return v
        if hasattr(v, "model_dump"):
            return v.model_dump()
        return v

    @field_validator("capacity", mode="before")
    @classmethod
    def _coerce_capacity(cls, v):
        from schemas.supply_schema import CapacityState as _CS
        if isinstance(v, dict) or isinstance(v, _CS):
            return v
        if hasattr(v, "model_dump"):
            return v.model_dump()
        return v

    @field_validator("expansion", mode="before")
    @classmethod
    def _coerce_expansion(cls, v):
        from schemas.supply_schema import ExpansionDecision as _ED
        if isinstance(v, dict) or isinstance(v, _ED):
            return v
        if hasattr(v, "model_dump"):
            return v.model_dump()
        return v

    @field_validator("market", mode="before")
    @classmethod
    def _coerce_market(cls, v):
        from schemas.equilibrium_schema import MarketClearingResult as _MCR
        if isinstance(v, dict) or isinstance(v, _MCR):
            return v
        if hasattr(v, "model_dump"):
            return v.model_dump()
        return v

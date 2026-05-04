"""Annual model state bundle — passed from year t to year t+1 in the dynamic loop."""

from __future__ import annotations

from typing import Dict, List

from pydantic import BaseModel

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

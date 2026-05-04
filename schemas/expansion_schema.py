"""
CapacityExpansionResult — output of the standalone CapacityExpansionModule.

Wraps an ExpansionDecision with supply/demand balance information so that
the main loop can gate the equilibrium solver on supply_meets_demand.
"""

from __future__ import annotations

from typing import Dict

from pydantic import BaseModel, Field

from schemas.supply_schema import ExpansionDecision


class CapacityExpansionResult(BaseModel):
    year: int
    expansion_decision: ExpansionDecision
    supply_meets_demand: bool = Field(
        description="True iff effective supply ≥ demand in every region (within tolerance)"
    )
    supply_by_region: Dict[str, float] = Field(
        description="Effective supply (MT/yr) after expansion, keyed by region"
    )
    demand_by_region: Dict[str, float] = Field(
        description="Effective demand (MT/yr, CORSIA-suppressed) keyed by region"
    )
    shortfall_by_region: Dict[str, float] = Field(
        description="max(0, demand - supply) per region; 0 means balanced or surplus"
    )
    warning_message: str = ""

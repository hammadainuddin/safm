"""Feedstock availability data contracts — inputs to the supply LP."""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, field_validator


class FeedstockAvailability(BaseModel):
    """Maximum feedstock available in one region-year for one feedstock type."""

    year: int
    region: str
    feedstock_type: str
    max_available_mt: float    # million tonnes
    notes: str = ""

    @field_validator("max_available_mt")
    @classmethod
    def non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("feedstock availability must be non-negative")
        return v


class RegionalFeedstockBundle(BaseModel):
    """All feedstock availability records for one region-year."""

    year: int
    region: str
    feedstocks: List[FeedstockAvailability]

    def get(self, feedstock_type: str) -> float:
        """Return max_available_mt for a feedstock type; 0.0 if not present."""
        for f in self.feedstocks:
            if f.feedstock_type == feedstock_type:
                return f.max_available_mt
        return 0.0

"""
Willingness-to-pay schemas.
Used by WTPModel and PriceQuantityClearing to represent per-region WTP estimates.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, field_validator


class RegionalWTP(BaseModel):
    year: int
    region: str
    wtp_usd_per_mt: float       # final WTP = max(case1, case2, case3)
    case1_value: float          # jet fuel price + CORSIA carbon credit value
    case2_value: float          # LCOSAF at target IRR
    case3_value: float          # policy compliance penalty (e.g. ReFuelEU)
    binding_case: str           # "case1" | "case2" | "case3"

    @field_validator("binding_case")
    @classmethod
    def _valid_case(cls, v: str) -> str:
        if v not in ("case1", "case2", "case3"):
            raise ValueError(f"binding_case must be case1/case2/case3, got {v!r}")
        return v


class WTPMatrix(BaseModel):
    year: int
    regional_wtps: List[RegionalWTP]
    corsia_offset_price_usd_per_mt: float = 0.0  # corsia_credit × 3.1 tCO2/MT SAF

    def wtp_for_region(self, region: str) -> Optional[RegionalWTP]:
        for wtp in self.regional_wtps:
            if wtp.region == region:
                return wtp
        return None

    def to_dict(self) -> Dict[str, float]:
        """Return {region: wtp_usd_per_mt}."""
        return {w.region: w.wtp_usd_per_mt for w in self.regional_wtps}

    def to_case_dict(self, case: str) -> Dict[str, float]:
        """Return {region: case_value} for case='case1', 'case2', or 'case3'."""
        attr = f"{case}_value"
        return {w.region: getattr(w, attr) for w in self.regional_wtps}

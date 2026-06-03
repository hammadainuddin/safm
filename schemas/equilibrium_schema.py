"""Market clearing data contracts — outputs of the spatial equilibrium solver (Module 3)."""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, field_validator


class TradeFlow(BaseModel):
    """SAF volume traded on one origin-destination arc in a given year."""

    year: int
    origin_region: str
    destination_region: str
    volume_mt: float               # million tonnes; 0 if no trade on this arc
    transport_cost_usd_per_mt: float
    pathway: str = ""              # production pathway (HEFA, FT, etc.); "" for legacy flows

    @field_validator("volume_mt", "transport_cost_usd_per_mt")
    @classmethod
    def non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("volume and transport cost must be non-negative")
        return v


class RegionalPrice(BaseModel):
    """Market-clearing price and decomposition for one region-year."""

    year: int
    region: str
    clearing_price_usd_per_mt: float
    pricing_regime: str            # "regulated_refueleu" | "voluntary_cost_plus"

    # Price decomposition (all additive)
    supply_cost_usd_per_mt: float = 0.0
    transport_premium_usd_per_mt: float = 0.0
    mandate_premium_usd_per_mt: float = 0.0   # 0 for voluntary markets
    carbon_offset_usd_per_mt: float = 0.0
    margin_usd_per_mt: float = 0.0
    shadow_price_usd_per_mt: float = 0.0      # LP dual on demand constraint

    @field_validator("pricing_regime")
    @classmethod
    def valid_regime(cls, v: str) -> str:
        valid = {"regulated_refueleu", "voluntary_cost_plus", "wtp_priority_allocation",
                 "unserved", "corsia_offset"}
        if v not in valid:
            raise ValueError(f"pricing_regime must be one of {valid}")
        return v


class MarketClearingResult(BaseModel):
    """Complete market clearing output for one year."""

    year: int
    trade_flows: List[TradeFlow]
    prices: List[RegionalPrice]
    total_saf_traded_mt: float    # cross-region trade only (excludes domestic)
    total_saf_produced_mt: float
    market_balanced: bool
    solver_status: str
    objective_value: float        # LP objective (minimised total supply + transport cost)
    offset_demand_mt_by_region: Dict[str, float] = {}  # unserved demand covered by CORSIA offsets
    corsia_offset_price_usd_per_mt: float = 0.0        # credit_price × 3.1 tCO2/MT SAF (for compliance cost chart)

    def price_for_region(self, region: str) -> Optional[RegionalPrice]:
        for p in self.prices:
            if p.region == region:
                return p
        return None

    def flows_from(self, origin: str) -> List[TradeFlow]:
        return [f for f in self.trade_flows if f.origin_region == origin]

    def flows_to(self, destination: str) -> List[TradeFlow]:
        return [f for f in self.trade_flows if f.destination_region == destination]

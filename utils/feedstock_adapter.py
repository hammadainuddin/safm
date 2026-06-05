"""
SAF_Saudi → market model feedstock bridge.

Imports availability dicts from SAF_Saudi/components/feedstock_profiles.py
and converts them to FeedstockAvailability Pydantic objects for the MENA
region.  This is the single sys.path seam; swap when SAF_Saudi is packaged.

All other regions are handled by the mock CSV in data/loaders.py.
"""

from __future__ import annotations

import os
import sys
from typing import List

from schemas.feedstock_schema import FeedstockAvailability

_SAF_SAUDI_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "SAF_Saudi", "components")
)
_GROWTH_RATE = 0.03   # annual 3% growth on base availability


def _saudi_base_availabilities() -> dict:
    """
    Import SAF_Saudi feedstock availability dicts.
    Falls back gracefully if the module is not found (e.g. in CI environments).
    """
    if _SAF_SAUDI_PATH not in sys.path:
        sys.path.insert(0, _SAF_SAUDI_PATH)
    try:
        import feedstock_profiles as fp
        return {
            "tallow":   fp.TALLOW_AVAILABILITY.get("available_for_saf_tonnes_yr", 20_000),
            "UCO":      20_000,    # Saudi restaurant/food-service UCO estimate (no direct var)
            "poultry":  fp.POULTRY_FAT_AVAILABILITY.get("available_for_saf_tonnes_yr", 42_000),
            "jatropha": fp.JATROPHA_AVAILABILITY.get("realistic_near_term_tonnes_yr", 10_000),
        }
    except ImportError:
        # Fallback values used when SAF_Saudi is not on the path
        return {"tallow": 20_000, "UCO": 20_000, "poultry": 42_000, "jatropha": 10_000}


def saudi_feedstocks_for_year(year: int) -> List[FeedstockAvailability]:
    """
    Return MENA region feedstock availability for a given model year.
    Units converted from tonnes → million tonnes (MT).
    Growth of 3% per year from 2025 baseline.
    """
    base  = _saudi_base_availabilities()
    growth = _GROWTH_RATE ** (year - 2025) if year > 2025 else 1.0
    # Compound growth: 1.03^(year-2025)
    growth = (1 + _GROWTH_RATE) ** (year - 2025)

    return [
        FeedstockAvailability(
            year=year, region="MENA", feedstock_type="tallow",
            max_available_mt=round(base["tallow"] * growth / 1_000_000, 6),
            notes="Hajj slaughterhouse tallow — SAF_Saudi TALLOW_AVAILABILITY",
        ),
        FeedstockAvailability(
            year=year, region="MENA", feedstock_type="UCO",
            max_available_mt=round(base["UCO"] * growth / 1_000_000, 6),
            notes="Saudi restaurant UCO collection estimate",
        ),
        FeedstockAvailability(
            year=year, region="MENA", feedstock_type="other",
            max_available_mt=round((base["poultry"] + base["jatropha"]) * growth / 1_000_000, 6),
            notes="Poultry fat + Jatropha oil — SAF_Saudi profiles",
        ),
    ]

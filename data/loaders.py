"""CSV → validated Pydantic objects. All I/O is isolated here."""

from __future__ import annotations

import os
from typing import Dict, List

import pandas as pd

from config.settings import MT_TO_PJ_FACTOR, FEEDSTOCK_TYPES
from schemas.feedstock_schema import FeedstockAvailability, RegionalFeedstockBundle
from schemas.supply_schema import CapacityState, PlantRecord

_HERE = os.path.dirname(__file__)
MOCK_DIR = os.path.join(_HERE, "mock")


def _mock_path(filename: str) -> str:
    return os.path.join(MOCK_DIR, filename)


# ---------------------------------------------------------------------------
# Transport cost matrix
# ---------------------------------------------------------------------------

def load_transport_costs(path: str = None) -> Dict[tuple, float]:
    """Return {(origin, destination): cost_usd_per_mt}."""
    path = path or _mock_path("transport_costs.csv")
    df = pd.read_csv(path)
    return {
        (row["origin"], row["destination"]): float(row["transport_cost_usd_per_mt"])
        for _, row in df.iterrows()
    }


def transport_cost_matrix(path: str = None) -> pd.DataFrame:
    """Return a region×region DataFrame of transport costs (USD/MT)."""
    path = path or _mock_path("transport_costs.csv")
    df = pd.read_csv(path)
    return df.pivot(index="origin", columns="destination", values="transport_cost_usd_per_mt").fillna(0.0)


# ---------------------------------------------------------------------------
# Committed capacity
# ---------------------------------------------------------------------------

def load_committed_capacity(year: int, path: str = None) -> CapacityState:
    """Return all deterministic plants with online_year ≤ year."""
    path = path or _mock_path("committed_capacity.csv")
    df = pd.read_csv(path)
    df = df[df["online_year"] <= year]

    plants = []
    for _, row in df.iterrows():
        # Parse "feedstock_type:intensity,feedstock_type:intensity" string
        fi: Dict[str, float] = {}
        for pair in str(row["feedstock_intensity_str"]).split(","):
            pair = pair.strip()
            if ":" in pair:
                ft, val = pair.split(":", 1)
                fi[ft.strip()] = float(val.strip())

        plants.append(PlantRecord(
            plant_id=str(row["plant_id"]),
            region=str(row["region"]),
            pathway=str(row["pathway"]),
            capacity_mt_yr=float(row["capacity_mt_yr"]),
            online_year=int(row["online_year"]),
            capex_usd_per_mt=float(row["capex_usd_per_mt"]),
            opex_usd_per_mt=float(row["opex_usd_per_mt"]),
            feedstock_intensity=fi,
            is_deterministic=True,
        ))

    return CapacityState(year=year, plants=plants)


# ---------------------------------------------------------------------------
# Refinery co-processing capacity caps
# ---------------------------------------------------------------------------

def load_domestic_priority_shares(path: str = None) -> Dict[str, float]:
    """
    Return {region: domestic_share} where each share is a fraction in [0, 1].

    `domestic_share` is the portion of a region's effective SAF supply that
    is reserved for local consumption (Phase 1 of market clearing) before
    any of that region's output can be exported. The remaining
    (1 - domestic_share) enters the cross-region import pool in Phase 2.

    Missing file or missing rows default to 1.0 (full domestic-first).
    """
    path = path or _mock_path("domestic_supply_priority.csv")
    if not os.path.exists(path):
        return {}
    df = pd.read_csv(path)
    shares: Dict[str, float] = {}
    for _, row in df.iterrows():
        pct = float(row.get("domestic_share_pct", 100.0))
        # Clamp to [0, 100] then convert to 0..1 fraction.
        pct = max(0.0, min(100.0, pct))
        shares[str(row["region"])] = pct / 100.0
    return shares


def load_coprocessing_caps(path: str = None) -> Dict[str, float]:
    """
    Return {region: max_coprocessing_mt_yr}.

    Co-processing SAF capacity is physically limited to a small share (typically
    5–10%) of the host refinery's middle-distillate throughput. The CSV captures
    that share per region:

        max_coprocessing = refinery_throughput × (coprocessing_share_max_pct / 100)

    Returns an empty dict if the file is missing, which disables the constraint
    (backwards-compatible behaviour).
    """
    path = path or _mock_path("refinery_capacity.csv")
    if not os.path.exists(path):
        return {}
    df = pd.read_csv(path)
    caps: Dict[str, float] = {}
    for _, row in df.iterrows():
        throughput = float(row.get("refinery_throughput_mt_yr", 0.0))
        share_pct  = float(row.get("coprocessing_share_max_pct", 0.0))
        caps[str(row["region"])] = throughput * share_pct / 100.0
    return caps


# ---------------------------------------------------------------------------
# Feedstock availability
# ---------------------------------------------------------------------------

def load_feedstock_bundles(year: int, path: str = None) -> List[RegionalFeedstockBundle]:
    """Return one RegionalFeedstockBundle per region for the given year."""
    path = path or _mock_path("feedstock_availability.csv")
    df = pd.read_csv(path)
    df = df[df["year"] == year]

    bundles: List[RegionalFeedstockBundle] = []
    for region, grp in df.groupby("region"):
        feedstocks = [
            FeedstockAvailability(
                year=year,
                region=str(region),
                feedstock_type=str(row["feedstock_type"]),
                max_available_mt=float(row["max_available_mt"]),
                cost_usd_per_mt=float(row["cost_usd_per_mt"]),
                notes=str(row.get("notes", "")),
            )
            for _, row in grp.iterrows()
        ]
        bundles.append(RegionalFeedstockBundle(year=year, region=str(region), feedstocks=feedstocks))
    return bundles


def feedstock_avail_dict(bundles: List[RegionalFeedstockBundle]) -> Dict[str, Dict[str, float]]:
    """Return {region: {feedstock_type: max_available_mt}} for quick lookup."""
    return {b.region: {f.feedstock_type: f.max_available_mt for f in b.feedstocks} for b in bundles}


# ---------------------------------------------------------------------------
# Regulatory parameters
# ---------------------------------------------------------------------------

def load_regulatory_params(year: int, path: str = None) -> Dict[str, dict]:
    """Return {region: param_dict} for the given year."""
    path = path or _mock_path("regulatory_params.csv")
    df = pd.read_csv(path)
    df = df[df["year"] == year]
    return {str(row["region"]): row.to_dict() for _, row in df.iterrows()}


# ---------------------------------------------------------------------------
# CORSIA demand suppression
# ---------------------------------------------------------------------------

_CORSIA_CACHE: Dict[tuple, float] | None = None


def load_corsia_suppression(path: str = None) -> Dict[tuple, float]:
    """
    Return {(year, region): suppression_factor} from corsia_suppression.csv.

    suppression_factor ∈ (0, 1] — fraction of full demand to use in voluntary
    markets during CORSIA-driven suppression years (2025–2034 by default).
    EU (REGULATED_REGIONS) is not present in the CSV and defaults to 1.0.
    """
    global _CORSIA_CACHE
    if _CORSIA_CACHE is not None and path is None:
        return _CORSIA_CACHE
    path = path or _mock_path("corsia_suppression.csv")
    df = pd.read_csv(path)
    result = {
        (int(row["year"]), str(row["region"])): float(row["suppression_factor"])
        for _, row in df.iterrows()
    }
    if path is None:
        _CORSIA_CACHE = result
    return result

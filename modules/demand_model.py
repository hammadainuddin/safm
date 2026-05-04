"""
Module 1 — Demand Model
=======================
Placeholder for the external bottom-up demand model.

Current implementation reads from the calibrated mock CSV.  When the
external bottom-up model is ready, plug it in via `plug_in_external_model()`
without touching any downstream schema or module.

Output schema: DemandMatrix  (strictly defined in schemas/demand_schema.py)
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

import pandas as pd

from config.settings import MODEL_END_YEAR, MODEL_START_YEAR, MT_TO_PJ_FACTOR, REGULATED_REGIONS
from data.loaders import load_corsia_suppression
from schemas.demand_schema import DemandMatrix, DemandRecord
from utils.logging_config import get_logger

logger = get_logger("demand_model")

_MOCK_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "mock", "demand_mock.csv")


class DemandModel:
    """
    Demand module interface.

    Replace ``_load_records_from_csv()`` with a call to the external
    bottom-up model when it is ready.  Everything downstream consumes
    only the ``DemandMatrix`` Pydantic object — the data contract is
    enforced at the boundary.
    """

    def __init__(self, data_path: str = None, scenario: str = "baseline"):
        self.data_path = os.path.abspath(data_path or _MOCK_PATH)
        self.scenario = scenario
        self._cache: Optional[DemandMatrix] = None

    # ------------------------------------------------------------------
    # Primary interface
    # ------------------------------------------------------------------

    def load_all(self, force_reload: bool = False) -> DemandMatrix:
        """Load and validate the full 21-year demand matrix (cached after first call)."""
        if self._cache is None or force_reload:
            records = self._load_records_from_csv(self.data_path)
            self._cache = DemandMatrix(
                records=records,
                scenario_name=self.scenario,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            logger.info(
                "Demand matrix loaded: %d records, scenario='%s'",
                len(records), self.scenario,
            )
        return self._cache

    def get_demand_for_year(self, year: int) -> List[DemandRecord]:
        """Return demand records for a single model year."""
        if not (MODEL_START_YEAR <= year <= MODEL_END_YEAR):
            raise ValueError(f"year {year} outside model horizon {MODEL_START_YEAR}–{MODEL_END_YEAR}")
        return self.load_all().get_year(year)

    def get_effective_demand_for_year(self, year: int) -> List[DemandRecord]:
        """
        Return demand records for `year` with CORSIA suppression applied.

        Voluntary-market regions (not in REGULATED_REGIONS) have their demand
        scaled by the suppression_factor from corsia_suppression.csv.
        EU (and any other REGULATED_REGIONS) always receive their full demand.
        """
        records = self.get_demand_for_year(year)
        suppression = load_corsia_suppression()
        result = []
        for r in records:
            if r.region in REGULATED_REGIONS:
                result.append(r)
            else:
                factor = suppression.get((year, r.region), 1.0)
                if factor >= 1.0:
                    result.append(r)
                else:
                    new_vol = round(r.volume_mt * factor, 8)
                    result.append(r.model_copy(update={
                        "volume_mt": new_vol,
                        "energy_pj": round(new_vol * MT_TO_PJ_FACTOR, 6),
                    }))
        return result

    def volume_by_region(self, year: int) -> Dict[str, float]:
        """Convenience method: {region: volume_mt} for a given year."""
        return self.load_all().volume_by_region(year)

    def total_global_demand(self, year: int) -> float:
        """Total global SAF demand in MT for a given year."""
        return self.load_all().total_volume_mt(year)

    # ------------------------------------------------------------------
    # External model plug-in interface (data contract boundary)
    # ------------------------------------------------------------------

    def plug_in_external_model(self, df: pd.DataFrame) -> DemandMatrix:
        """
        Validate and import demand data from an external bottom-up model.

        Parameters
        ----------
        df : pd.DataFrame
            Must have columns: year (int), region (str), volume_mt (float).
            energy_pj is derived automatically.

        Returns
        -------
        DemandMatrix
            Fully validated Pydantic object.  Replace ``self._cache`` with
            this object to use external demand for the current run.
        """
        required_cols = {"year", "region", "volume_mt"}
        missing = required_cols - set(df.columns)
        if missing:
            raise ValueError(f"External model DataFrame is missing columns: {missing}")

        records = []
        for _, row in df.iterrows():
            records.append(DemandRecord(
                year=int(row["year"]),
                region=str(row["region"]),
                volume_mt=float(row["volume_mt"]),
                energy_pj=round(float(row["volume_mt"]) * MT_TO_PJ_FACTOR, 6),
                source="bottom_up_model",
            ))

        matrix = DemandMatrix(
            records=records,
            scenario_name=self.scenario,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        logger.info(
            "External model demand loaded: %d records via plug_in_external_model()",
            len(records),
        )
        return matrix

    # ------------------------------------------------------------------
    # Internal loaders
    # ------------------------------------------------------------------

    @staticmethod
    def _load_records_from_csv(path: str) -> List[DemandRecord]:
        """Read and validate demand_mock.csv row-by-row."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"Demand CSV not found: {path}")

        df = pd.read_csv(path)
        required = {"year", "region", "volume_mt", "energy_pj"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"demand CSV missing columns: {missing}")

        records = []
        for idx, row in df.iterrows():
            try:
                records.append(DemandRecord(
                    year=int(row["year"]),
                    region=str(row["region"]),
                    volume_mt=float(row["volume_mt"]),
                    energy_pj=float(row["energy_pj"]),
                    source=str(row.get("source", "mock")),
                ))
            except Exception as exc:
                raise ValueError(f"Row {idx} failed validation: {exc}") from exc

        return records

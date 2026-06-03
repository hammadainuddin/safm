"""
Willingness-to-Pay (WTP) Model
================================
Computes the maximum price each region is willing to pay for SAF, drawing on
three complementary cases:

  Case 1 — Opportunity cost:
      jet_fuel_price + CORSIA_carbon_credit × lifecycle_CI_reduction_per_MT_SAF
      Represents the economic signal when SAF competes with jet fuel + carbon offsets.

  Case 2 — Minimum investor price:
      LCOSAF at target IRR (computed from CAPEX/OPEX tables using levelised_cost())
      This is the floor price that incentivises new capacity investment.

  Case 3 — Total market WTP ceiling (regional reality):
      The full market-clearing price airlines in a region will pay, combining
      the jet-fuel baseline + CORSIA/ETS/LCFS compliance value + a regional
      regulatory or voluntary premium (ReFuelEU non-compliance penalty for
      EU; LCFS + corporate sustainability buyers for US; pilot mandates for
      APAC; small flagship-carrier premium for MENA; near-zero premium for
      LATAM/ROW). Loaded from wtp_params.csv `case3_penalty_usd_per_mt` —
      now spans EU $2.6k–3.6k, US $1.5k–2.2k, APAC $1.3k–1.8k, MENA
      $1.0k–1.3k, LATAM/ROW $0.8k–1.0k over 2025–2045.

Final WTP = max(case1, case2, case3).  The binding case tells you which price
driver dominates — useful for scenario analysis.
"""

from __future__ import annotations

import os
from typing import Dict, Optional

import pandas as pd

from config.settings import (
    DISCOUNT_RATE,
    PROJECT_LIFE_YR,
    REGIONAL_CAPEX,
    REGIONAL_OPEX,
    SAF_PATHWAYS,
    UTILIZATION_FACTOR,
)
from schemas.supply_schema import CapacityState
from schemas.wtp_schema import RegionalWTP, WTPMatrix
from utils.economics import levelised_cost
from utils.logging_config import get_logger

logger = get_logger("wtp_model")

_MOCK = os.path.join(os.path.dirname(__file__), "..", "data", "mock")

# CO2 emitted by one MT of conventional jet fuel at combustion.
# Under the CORSIA convention SAF combustion is treated as zero-emission,
# so each MT of SAF that displaces jet fuel avoids this much CO2 — which
# is the basis for the SAF-vs-offset credit substitution in Case 1 WTP.
_CI_REDUCTION_T_CO2_PER_MT_SAF = 3.1


class WTPModel:
    """Computes per-region willingness-to-pay for SAF for a given model year."""

    def __init__(self, wtp_params_path: str = None):
        self._params_path = wtp_params_path or os.path.join(_MOCK, "wtp_params.csv")
        self._params_cache: Optional[pd.DataFrame] = None

    # ── Public interface ─────────────────────────────────────────────────────

    def compute_wtp(
        self, year: int, capacity_state: CapacityState
    ) -> WTPMatrix:
        """
        Return a WTPMatrix for all regions in the given year.

        Parameters
        ----------
        year           : model year
        capacity_state : current CapacityState, used to infer regional supply costs
                         for Case 2 (LCOSAF at target IRR)
        """
        params_df = self._load_params()
        year_params = params_df[params_df["year"] == year]

        regional_wtps = []
        for _, row in year_params.iterrows():
            region = str(row["region"])
            c1 = self._case1(row)
            c2 = self._case2(region, row)
            c3 = self._case3(row)
            wtp, binding = self._apply_mode(c1, c2, c3, str(row.get("wtp_mode", "max")))
            regional_wtps.append(RegionalWTP(
                year=year, region=region,
                wtp_usd_per_mt=round(wtp, 2),
                case1_value=round(c1, 2),
                case2_value=round(c2, 2),
                case3_value=round(c3, 2),
                binding_case=binding,
            ))

        credit_price = (float(year_params["corsia_credit_usd_per_tco2"].max())
                        if not year_params.empty else 30.0)
        matrix = WTPMatrix(
            year=year,
            regional_wtps=regional_wtps,
            corsia_offset_price_usd_per_mt=round(credit_price * _CI_REDUCTION_T_CO2_PER_MT_SAF, 2),
        )
        self._log_summary(matrix, year)
        return matrix

    def build_sd_curve_data(
        self,
        year: int,
        capacity_state: CapacityState,
        demand_by_region: Dict[str, float],
        wtp_matrix: Optional[WTPMatrix] = None,
        market_result=None,
    ) -> dict:
        """
        Return data for the pathway-level supply-demand curve.

        Returns
        -------
        dict with keys:
          demand_steps      : [(wtp, volume, region), ...]  sorted by wtp desc
          supply_steps      : [(lcosaf, volume, region, pathway, dispatched), ...]
                              sorted by lcosaf asc; dispatched=True when the plant's
                              cumulative volume falls within total_saf_produced_mt.
          offset_mt         : demand volume unserved by physical SAF (→ CORSIA offsets)
          offset_price_usd_per_mt : CORSIA carbon-offset cost per MT SAF for that year
                                    = corsia_credit_usd_per_tco2 × 3.1 tCO2/MT SAF.
                                    Used as the y-axis (height) of the offset demand bar.
          max_wtp           : highest regional WTP (kept for backwards compatibility).
        """
        from utils.economics import levelised_cost as _lc

        if wtp_matrix is None:
            wtp_matrix = self.compute_wtp(year, capacity_state)

        wtp_dict = wtp_matrix.to_dict()

        # ── Demand steps (unchanged structure) ───────────────────────────────
        demand_steps = sorted(
            [(wtp_dict.get(r, 0.0), demand_by_region.get(r, 0.0), r)
             for r in wtp_dict],
            key=lambda x: -x[0],
        )

        # ── Supply steps: one entry per plant (pathway-level granularity) ────
        raw_supply = []
        for plant in capacity_state.plants:
            lc = _lc(
                plant.capex_usd_per_mt, plant.opex_usd_per_mt,
                UTILIZATION_FACTOR, DISCOUNT_RATE, PROJECT_LIFE_YR,
            )
            vol = plant.capacity_mt_yr * UTILIZATION_FACTOR
            raw_supply.append((lc, vol, plant.region, plant.pathway))
        raw_supply.sort(key=lambda x: x[0])  # cheapest first

        # Mark dispatch status: cheapest plants fill dispatched_vol first
        dispatched_vol = (
            market_result.total_saf_produced_mt
            if market_result is not None
            else float("inf")
        )
        supply_steps = []
        cum = 0.0
        for lc, vol, region, pathway in raw_supply:
            dispatched = (cum + vol) <= dispatched_vol + 1e-6
            supply_steps.append((lc, vol, region, pathway, dispatched))
            cum += vol

        # ── Offset demand ────────────────────────────────────────────────────
        total_demand = sum(demand_by_region.values())
        actual_dispatched = min(dispatched_vol, cum)
        offset_mt = max(0.0, total_demand - actual_dispatched)
        max_wtp = max(wtp_dict.values(), default=0.0)

        # CORSIA offset price = carbon-credit price × 3.1 tCO2/MT SAF.
        # Pull the credit price from wtp_params for this year (regions share a
        # global CORSIA credit market; take the max across regions in case one
        # entry is missing a value).
        params_df = self._load_params()
        year_row = params_df[params_df["year"] == year]
        if not year_row.empty and "corsia_credit_usd_per_tco2" in year_row.columns:
            credit_price = float(year_row["corsia_credit_usd_per_tco2"].max())
        else:
            credit_price = 30.0
        offset_price_usd_per_mt = credit_price * _CI_REDUCTION_T_CO2_PER_MT_SAF

        return {
            "demand_steps": demand_steps,
            "supply_steps": supply_steps,
            "offset_mt":    offset_mt,
            "offset_price_usd_per_mt": offset_price_usd_per_mt,
            "max_wtp":      max_wtp,
        }

    # ── Case calculations ────────────────────────────────────────────────────

    @staticmethod
    def _case1(row: pd.Series) -> float:
        """
        Jet fuel price + CORSIA carbon credit value (USD/MT SAF).

        Case 1 reflects the airline's opportunity cost: each MT of SAF
        displaces 1 MT of conventional jet fuel and avoids 3.1 tCO₂ of
        combustion emissions, which would otherwise require buying CORSIA
        offsets at the credit price.
        """
        jet = float(row.get("jet_fuel_price_usd_per_mt", 700.0))
        credit = float(row.get("corsia_credit_usd_per_tco2", 30.0))
        return jet + credit * _CI_REDUCTION_T_CO2_PER_MT_SAF

    @staticmethod
    def _case2(region: str, row: pd.Series) -> float:
        """
        LCOSAF at the region's target IRR — minimum price for investment viability.
        Uses HEFA (cheapest) CAPEX/OPEX as the reference pathway.
        levelised_cost(capex, opex×utilization, utilization, irr, life)
        """
        irr = float(row.get("target_irr_pct", 12.0)) / 100.0
        r_capex = REGIONAL_CAPEX.get(region, REGIONAL_CAPEX.get("ROW", {}))
        r_opex  = REGIONAL_OPEX.get(region,  REGIONAL_OPEX.get("ROW",  {}))

        best_lcosaf = float("inf")
        for pathway in SAF_PATHWAYS:
            capex = r_capex.get(pathway, 2000.0)   # USD / MT/yr capacity
            opex  = r_opex.get(pathway, 600.0)     # USD / MT produced
            # OPEX is USD/MT-capacity/yr (includes feedstock as a fixed annual cost).
            # Formula: LCOSAF = (CRF × CAPEX + OPEX) / UTIL
            lc = levelised_cost(
                capex_usd_per_unit=capex,
                annual_opex_usd=opex,
                annual_output_mt=UTILIZATION_FACTOR,
                discount_rate=irr,
                n_years=PROJECT_LIFE_YR,
            )
            if lc < best_lcosaf:
                best_lcosaf = lc
        return best_lcosaf

    @staticmethod
    def _case3(row: pd.Series) -> float:
        """
        Total market WTP ceiling (USD/MT SAF) for the region in this year.

        Captures the combined effect of jet-fuel baseline, CORSIA/ETS/LCFS
        compliance value, and any regulatory or voluntary premium specific
        to the region (ReFuelEU penalty in EU, LCFS + corporate premium in
        US, pilot mandates in APAC, small flagship-carrier premium in
        MENA, ~0 premium in LATAM/ROW). Sourced from wtp_params.csv
        `case3_penalty_usd_per_mt`.
        """
        """Policy compliance penalty (e.g. ReFuelEU surcharge, USD/MT SAF)."""
        return float(row.get("case3_penalty_usd_per_mt", 0.0))

    @staticmethod
    def _apply_mode(c1: float, c2: float, c3: float, mode: str):
        """Return (wtp, binding_case) for the given mode."""
        if mode == "case1":
            return c1, "case1"
        if mode == "case2":
            return c2, "case2"
        if mode == "case3":
            return c3, "case3"
        # default: "max" — highest binding price
        values = {"case1": c1, "case2": c2, "case3": c3}
        binding = max(values, key=values.__getitem__)
        return values[binding], binding

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _capacity_weighted_lcosaf(self, capacity: CapacityState) -> Dict[str, float]:
        """Return {region: capacity-weighted average LCOSAF} (USD/MT).

        Uses each plant's own CAPEX and OPEX so the supply curve reflects
        the full levelised cost, consistent with Case-2 WTP.
        """
        from utils.economics import levelised_cost as _lc
        numerator: Dict[str, float] = {}
        denominator: Dict[str, float] = {}
        for plant in capacity.plants:
            r = plant.region
            lc = _lc(plant.capex_usd_per_mt, plant.opex_usd_per_mt,
                     UTILIZATION_FACTOR, DISCOUNT_RATE, PROJECT_LIFE_YR)
            numerator[r]   = numerator.get(r, 0.0)   + lc * plant.capacity_mt_yr
            denominator[r] = denominator.get(r, 0.0) + plant.capacity_mt_yr
        return {r: numerator[r] / denominator[r] for r in numerator if denominator[r] > 0}

    def _load_params(self) -> pd.DataFrame:
        if self._params_cache is None:
            self._params_cache = pd.read_csv(self._params_path)
        return self._params_cache

    @staticmethod
    def _log_summary(matrix: WTPMatrix, year: int) -> None:
        summary = {w.region: f"${w.wtp_usd_per_mt:.0f}({w.binding_case})"
                   for w in matrix.regional_wtps}
        logger.info("Year %d — WTP: %s", year, summary)

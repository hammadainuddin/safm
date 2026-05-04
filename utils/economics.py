"""
Financial math utilities — pure functions, no side effects.
Adapted from SAF_Saudi/tea/capex_opex_model.py patterns.
"""

from __future__ import annotations

from typing import List


def crf(discount_rate: float, n_years: int) -> float:
    """Capital Recovery Factor: converts overnight CAPEX to annual equivalent."""
    if n_years <= 0:
        raise ValueError("n_years must be positive")
    if discount_rate == 0.0:
        return 1.0 / n_years
    i, n = discount_rate, n_years
    return i * (1 + i) ** n / ((1 + i) ** n - 1)


def annualise_capex(capex_usd_per_unit: float, discount_rate: float, n_years: int) -> float:
    """Convert overnight CAPEX (USD / MT/yr capacity) to annual equivalent cost (USD / MT/yr)."""
    return capex_usd_per_unit * crf(discount_rate, n_years)


def npv(cash_flows: List[float], discount_rate: float) -> float:
    """Net Present Value of a sequence of annual cash flows (year-0 first)."""
    return sum(cf / (1 + discount_rate) ** t for t, cf in enumerate(cash_flows))


def levelised_cost(
    capex_usd_per_unit: float,
    annual_opex_usd: float,
    annual_output_mt: float,
    discount_rate: float,
    n_years: int,
) -> float:
    """
    Levelised Cost of SAF (USD / MT).
    = (annualised CAPEX + annual OPEX) / annual output
    """
    if annual_output_mt <= 0:
        return float("inf")
    ann = annualise_capex(capex_usd_per_unit, discount_rate, n_years)
    return (ann + annual_opex_usd) / annual_output_mt


def annualised_total_cost(
    capex_usd_per_mt_capacity: float,
    opex_usd_per_mt_produced: float,
    discount_rate: float,
    n_years: int,
) -> float:
    """
    Combined annual cost rate (USD / MT/yr capacity).
    Used directly as the LP objective coefficient.
    """
    return annualise_capex(capex_usd_per_mt_capacity, discount_rate, n_years) + opex_usd_per_mt_produced

"""Global constants — single source of truth. No magic numbers elsewhere."""

MODEL_START_YEAR = 2025
MODEL_END_YEAR   = 2045
HORIZON_YEARS    = list(range(MODEL_START_YEAR, MODEL_END_YEAR + 1))

REGIONS = ["EU", "US", "APAC", "MENA", "LATAM", "ROW"]

SAF_PATHWAYS = ["HEFA", "ATJ", "FT-MSW", "PtL", "Co-processing"]

FEEDSTOCK_TYPES = ["UCO", "tallow", "agricultural_residue", "MSW", "CO2_green_H2", "other"]

# Per-pathway feedstock intensities: tonnes feedstock per MT SAF
FEED_INTENSITY: dict = {
    "HEFA":          {"UCO": 1.25, "tallow": 1.30, "agricultural_residue": 0.0, "MSW": 0.0,  "CO2_green_H2": 0.0, "other": 0.0},
    "ATJ":           {"UCO": 0.0,  "tallow": 0.0,  "agricultural_residue": 2.50, "MSW": 0.0,  "CO2_green_H2": 0.0, "other": 0.0},
    "FT-MSW":        {"UCO": 0.0,  "tallow": 0.0,  "agricultural_residue": 0.0, "MSW": 4.00, "CO2_green_H2": 0.0, "other": 0.0},
    "PtL":           {"UCO": 0.0,  "tallow": 0.0,  "agricultural_residue": 0.0, "MSW": 0.0,  "CO2_green_H2": 2.80, "other": 0.0},
    "Co-processing": {"UCO": 0.60, "tallow": 0.65, "agricultural_residue": 0.0, "MSW": 0.0,  "CO2_green_H2": 0.0, "other": 0.80},
}

# Regional CAPEX and OPEX by pathway (USD per MT/year nameplate capacity)
# These are representative values; override via committed_capacity.csv for deterministic plants
# Full-cost OPEX (processing + feedstock + logistics).
#
# Cost stack reflects real-world competitive positioning:
#   - APAC (China, Malaysia, Singapore, India) — lowest cost: integrated feedstock supply
#     chains (UCO, palm-residue, agricultural residues), large-scale EPC at lower
#     labour/equipment cost, established refining base for co-processing.
#   - MENA — cheap solar electricity / green-H2 gives a clear PtL advantage; HEFA and
#     bio pathways slightly above APAC due to limited oilseed feedstock.
#   - LATAM, ROW — mid-stack; abundant ag-residue but less integrated capital base.
#   - US — IRA tax-credit support partially offsets higher construction labour and steel
#     costs, but raw plant economics remain above APAC/MENA.
#   - EU — highest CAPEX/OPEX: stringent environmental permitting, expensive labour,
#     small-scale European EPC market, high feedstock pricing.
#
# CRF(10%, 20yr) ≈ 0.1175. LCOSAF = (CRF × CAPEX + OPEX) / UTILIZATION_FACTOR.
# Resulting HEFA LCOSAF at 10% IRR / 85% utilisation:
#   APAC ≈ $1,170/MT  · MENA ≈ $1,245  · LATAM ≈ $1,290  · ROW ≈ $1,340
#   US   ≈ $1,415/MT  · EU   ≈ $1,540
REGIONAL_CAPEX: dict = {
    "APAC": {"HEFA": 2500, "ATJ": 3800, "FT-MSW": 5200, "PtL": 7000, "Co-processing": 1200},
    "MENA": {"HEFA": 2625, "ATJ": 4000, "FT-MSW": 5450, "PtL": 6300, "Co-processing": 1250},
    "LATAM":{"HEFA": 2750, "ATJ": 4200, "FT-MSW": 5700, "PtL": 7700, "Co-processing": 1325},
    "ROW":  {"HEFA": 2900, "ATJ": 4400, "FT-MSW": 6000, "PtL": 8050, "Co-processing": 1375},
    "US":   {"HEFA": 3000, "ATJ": 4550, "FT-MSW": 6250, "PtL": 8400, "Co-processing": 1450},
    "EU":   {"HEFA": 3250, "ATJ": 4900, "FT-MSW": 6750, "PtL": 9100, "Co-processing": 1550},
}

REGIONAL_OPEX: dict = {
    "APAC": {"HEFA": 700,  "ATJ": 950,  "FT-MSW": 1200, "PtL": 1700, "Co-processing": 550},
    "MENA": {"HEFA": 750,  "ATJ": 1000, "FT-MSW": 1250, "PtL": 1450, "Co-processing": 575},
    "LATAM":{"HEFA": 775,  "ATJ": 1050, "FT-MSW": 1325, "PtL": 1875, "Co-processing": 625},
    "ROW":  {"HEFA": 800,  "ATJ": 1100, "FT-MSW": 1375, "PtL": 1950, "Co-processing": 650},
    "US":   {"HEFA": 850,  "ATJ": 1150, "FT-MSW": 1450, "PtL": 2050, "Co-processing": 675},
    "EU":   {"HEFA": 925,  "ATJ": 1250, "FT-MSW": 1550, "PtL": 2200, "Co-processing": 725},
}

UTILIZATION_FACTOR  = 0.85
DISCOUNT_RATE       = 0.10
PROJECT_LIFE_YR     = 20

SAF_LHV_MJ_KG       = 43.2
SAF_DENSITY_KG_M3   = 800.0
MT_TO_PJ_FACTOR     = SAF_LHV_MJ_KG / 1_000     # 1 MT SAF → PJ (1 MT = 1e6 kg; MJ/kg × 1e6 kg / 1e9 = PJ × 1e-3 → use /1000)

DEFAULT_SOLVER      = "glpk"
MARKET_BALANCE_TOL  = 1e-4   # MT; absolute tolerance for market clearing check

# 64 representative routes ≈ 5% of global scheduled traffic.
# Applied to CORSIA SAF demand only (mandate targets are policy absolutes, not sampled).
ROUTE_SAMPLE_FRACTION = 0.05

# CORSIA demand suppression — voluntary regions have reduced effective demand
# in early years due to cheap jet fuel + CORSIA-eligible carbon offsets.
# Suppression factors are loaded from data/mock/corsia_suppression.csv and
# are analyst-adjustable via the Streamlit UI.
REGULATED_REGIONS             = {"EU"}  # always receive 100% (unsuppressed) demand
SUPPLY_DEMAND_BALANCE_TOLERANCE = 1e-3  # MT; gate threshold for equilibrium solver

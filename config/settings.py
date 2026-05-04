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
# Full-cost OPEX (processing + feedstock + logistics). Targets HEFA LCOSAF ≈ $1,531/MT
# at 12% IRR, 20yr project life, 85% utilisation. Other regions scaled proportionally.
# CRF(12%, 20yr) ≈ 0.1339. LCOSAF = (CRF × CAPEX + OPEX) / UTILIZATION.
REGIONAL_CAPEX: dict = {
    "EU":   {"HEFA": 3000, "ATJ": 4500, "FT-MSW": 6000, "PtL": 8000, "Co-processing": 1500},
    "US":   {"HEFA": 2750, "ATJ": 4150, "FT-MSW": 5650, "PtL": 7350, "Co-processing": 1375},
    "APAC": {"HEFA": 3250, "ATJ": 4850, "FT-MSW": 6350, "PtL": 8300, "Co-processing": 1625},
    "MENA": {"HEFA": 2800, "ATJ": 4650, "FT-MSW": 6650, "PtL": 7050, "Co-processing": 1450},
    "LATAM":{"HEFA": 3050, "ATJ": 4350, "FT-MSW": 6150, "PtL": 8650, "Co-processing": 1550},
    "ROW":  {"HEFA": 3200, "ATJ": 4850, "FT-MSW": 6500, "PtL": 9000, "Co-processing": 1675},
}

REGIONAL_OPEX: dict = {
    "EU":   {"HEFA": 900,  "ATJ": 1200, "FT-MSW": 1400, "PtL": 2000, "Co-processing": 700},
    "US":   {"HEFA": 825,  "ATJ": 1125, "FT-MSW": 1300, "PtL": 1850, "Co-processing": 650},
    "APAC": {"HEFA": 975,  "ATJ": 1275, "FT-MSW": 1475, "PtL": 2050, "Co-processing": 750},
    "MENA": {"HEFA": 850,  "ATJ": 1150, "FT-MSW": 1425, "PtL": 1800, "Co-processing": 675},
    "LATAM":{"HEFA": 925,  "ATJ": 1175, "FT-MSW": 1400, "PtL": 2100, "Co-processing": 725},
    "ROW":  {"HEFA": 950,  "ATJ": 1250, "FT-MSW": 1450, "PtL": 2175, "Co-processing": 775},
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

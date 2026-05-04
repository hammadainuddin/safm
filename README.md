# SAF Global Market Model

A 20-year (2025–2045) dynamic simulation of the global Sustainable Aviation Fuel (SAF) market. The model combines bottom-up flight-demand estimation, least-cost capacity expansion, willingness-to-pay (WTP) pricing, and regional trade clearing — all presented through an interactive Streamlit dashboard.

---

## Overview

Each model year runs four sequential steps:

| Step | Module | Description |
|------|--------|-------------|
| 1. Demand | `BottomUpDemandModule` | Derives SAF demand from CORSIA-eligible international flights and domestic blending mandates. Demand attributed 60/40 origin/destination per CORSIA uplift rules. |
| 2. Expansion | `CapacityExpansionModule` | Assesses supply gap → solves a least-cost Pyomo LP → adds new plants to the capacity state. |
| 3. WTP | `WTPModel` | Computes regional willingness-to-pay as `max(Case 1: jet+CORSIA, Case 2: LCOSAF@IRR, Case 3: policy penalty)`. |
| 4. Clearing | `PriceQuantityClearing` | Allocates cheapest-CIF supply to highest-WTP regions. Clearing price = WTP of the served region. |

Capacity accumulates year-over-year. Clearing only runs when supply meets demand.

---

## Project Structure

```
saf_market_model/
├── app.py                    # Streamlit UI entry point
├── main.py                   # CLI entry point (python main.py)
├── requirements.txt
│
├── config/
│   └── settings.py           # All global constants (CAPEX, OPEX, REGIONS, etc.)
│
├── modules/
│   ├── demand_bottom_up.py   # Bottom-up flight demand estimation
│   ├── wtp_model.py          # WTP calculation (3 cases) + supply-demand curve data
│   ├── price_quantity_clearing.py  # Market clearing (WTP-priority allocation)
│   ├── capacity_expansion.py # LP-based capacity expansion
│   └── reporting.py          # CSV + Excel output writer
│
├── schemas/                  # Pydantic v2 data schemas
│   ├── demand_schema.py
│   ├── supply_schema.py
│   ├── equilibrium_schema.py
│   ├── wtp_schema.py
│   ├── flight_schema.py
│   └── state_schema.py
│
├── data/
│   ├── loaders.py
│   └── mock/                 # Editable CSV inputs
│       ├── flight_routes.csv
│       ├── aircraft_types.csv
│       ├── airlines.csv
│       ├── committed_capacity.csv
│       ├── corsia_schedule.csv
│       ├── feedstock_availability.csv
│       ├── transport_costs.csv
│       ├── regulatory_params.csv
│       └── wtp_params.csv
│
├── ui/
│   ├── input_editor.py       # Tab 1: editable input tables + charts
│   ├── runner.py             # Tab 2: model execution + live logs
│   ├── output_dashboard.py   # Tab 3: results dashboard
│   └── charts.py             # All Plotly chart builders
│
├── utils/
│   ├── economics.py          # levelised_cost(), crf(), npv()
│   └── logging_config.py
│
├── tests/
│   ├── unit/                 # Unit tests for each module
│   └── integration/          # Single-year and full 20-year loop tests
│
└── outputs/                  # Model run results (CSV + Excel, timestamped)
```

---

## Key Modelling Concepts

### WTP — Willingness to Pay
Each region's WTP is the maximum of three cases:

- **Case 1 (Market floor):** Jet fuel price + CORSIA carbon credit value (2.5 tCO₂/MT SAF)
- **Case 2 (Investment floor):** Levelised Cost of SAF (LCOSAF) at the region's target IRR using the cheapest available pathway
- **Case 3 (Policy ceiling):** Regulatory penalty (e.g. EU ReFuelEU mandate non-compliance penalty = $2,500/MT)

### LCOSAF Formula
```
LCOSAF = (CRF(IRR, 20yr) × CAPEX + OPEX) / Utilisation
```
Where OPEX includes full feedstock + processing + logistics costs.  
EU HEFA benchmark: **~$1,531/MT** at 12% IRR, 85% utilisation.

### Demand Scaling
The 64 representative flight routes ≈ 5% of global scheduled traffic.  
CORSIA SAF demand is scaled by `ROUTE_SAMPLE_FRACTION = 0.05`.  
Blending mandate demand is a policy target and is **not** scaled.

### Market Clearing
Supply is dispatched cheapest-CIF first to the highest-WTP region. Regions are served in descending WTP order until supply is exhausted. The clearing price for each served region equals its WTP.

---

## Installation

```bash
git clone https://github.com/hammadainuddin/safm.git
cd safm
pip install -r requirements.txt
```

Requires Python 3.8+ and a compatible LP solver. The model defaults to GLPK:

```bash
# macOS (Homebrew)
brew install glpk

# Linux
sudo apt-get install glpk-utils
```

---

## Usage

### Streamlit Dashboard (recommended)

```bash
streamlit run app.py
```

Opens three tabs:
- **📊 Model Inputs** — edit demand, capacity, costs, regulatory parameters, and view LCOSAF charts
- **▶ Run Model** — configure scenario and horizon, run the model, view live logs
- **📈 Model Outputs** — global price chart, WTP trends, MAC supply-demand curve, capacity split, trade flow Sankey

### CLI

```bash
# Full 2025–2045 baseline run
python main.py

# Custom horizon and scenario
python main.py --start 2025 --end 2030 --scenario high_demand

# Output to a specific directory
python main.py --output-dir ./my_results
```

---

## Outputs

Each run writes to `outputs/results_<timestamp>_<scenario>/`:

| File | Contents |
|------|----------|
| `prices.csv` | Clearing price by region and year, with price decomposition |
| `trade_flows.csv` | Inter-regional SAF trade volumes and transport costs |
| `capacity.csv` | Capacity by region, pathway, and type (Planned / Modelled) |
| `market_summary.csv` | Annual demand, production, trade totals, balance status |
| `summary_dashboard.xlsx` | Excel workbook with Prices, Trade Flows, and Capacity sheets |

---

## Regions and Pathways

**Regions:** EU, US, APAC, MENA, LATAM, ROW

**SAF Pathways:** HEFA, ATJ, FT-MSW, PtL, Co-processing

---

## Tests

```bash
pytest tests/ -q
```

180 tests covering unit and integration scenarios including:
- Demand attribution and CORSIA scaling
- WTP case calculation
- Market clearing and supply conservation
- Full 20-year loop (capacity monotonicity, price validity, output files)

---

## Configuration

Key parameters in `config/settings.py`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `ROUTE_SAMPLE_FRACTION` | `0.05` | Fraction of global traffic represented by the 64 sample routes |
| `UTILIZATION_FACTOR` | `0.85` | Nameplate capacity → effective annual output |
| `PROJECT_LIFE_YR` | `20` | Plant economic life for LCOSAF calculation |
| `DISCOUNT_RATE` | `0.10` | Default discount rate for NPV/expansion LP |
| `MARKET_BALANCE_TOL` | `1e-4 MT` | Tolerance for supply-demand balance check |

Regional CAPEX and OPEX tables are also in `settings.py` and can be overridden per-plant in `data/mock/committed_capacity.csv`.

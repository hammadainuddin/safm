# SAF Global Market Model

A 20-year (2025–2050) dynamic simulation of the global Sustainable Aviation Fuel (SAF) market. The model combines bottom-up flight-demand estimation from a comprehensive 1,274-route dataset, least-cost capacity expansion, willingness-to-pay (WTP) pricing, and regional price–quantity clearing — all presented through an interactive four-tab Streamlit dashboard.

---

## Dashboard

### Tab 1 — Model Inputs

All model inputs are editable directly in the browser across seven sub-tabs. Changes auto-save to the underlying CSV layer and immediately refresh the inline preview charts.

**Demand Module** presents a radio selector to choose between the two demand modes. In *Single CORSIA Schedule* mode, the CORSIA mandatory blending fraction and carbon credit price are shown as an editable year-by-year table alongside a demand suppression table for voluntary-only regions. In *Country-Specific SAF Targets* mode, the full 1,274-route dataset is displayed with per-route SAF% target columns for key years 2025–2050. Both modes conclude with a stacked bar chart showing projected SAF demand by region across the full horizon.

**Airlines, Aircraft & Routes** exposes the three flight-activity datasets — the 163-operator airline register, 14-aircraft-type efficiency table, and the complete route network — as inline editable grids with download-template and CSV-upload controls.

**Committed Capacity** shows all 149 announced and operating SAF plants as an editable table, with a stacked bar chart summarising capacity by region and a pathway breakdown chart. A refinery co-processing capacity cap section lets users adjust regional refinery throughput and the share available for co-processing, with an implied capacity ceiling chart updated in real time.

**Feedstock & Costs** contains editable tables for regional feedstock availability (by type, year, and cost), inter-regional SAF transport costs, and domestic supply priority shares (the fraction of each region's output reserved for local consumption before export).

**Regulatory Parameters** displays the per-region, per-year regulatory input table covering pricing regime, mandate fraction, non-compliance penalty, carbon tax, jet fuel price, and green premium — all editable inline.

**WTP Parameters** provides the per-region, per-year willingness-to-pay input table (jet fuel price, CORSIA credit price, Case 3 penalty, target IRR) and a live LCOSAF Explorer. The explorer lets users adjust CAPEX, processing OPEX, feedstock price, and yield for any region–pathway combination and immediately see the updated levelised cost bar chart, cost-stack waterfall, and implied break-even SAF price.

**National Blending Mandates** shows the country-level mandate schedule as an editable table and a grouped bar chart of mandate fractions by country and year.

### Tab 2 — Run Model

Users configure a scenario name and start/end year, then click **▶ Run Model**. The model executes in a background thread and streams progress back to the UI in real time. A per-year step table tracks each of the four annual steps (Demand, Expansion, Equilibrium, Done) with tick marks as they complete. A scrollable log shows a plain-English description of each step's outcome. Elapsed time and estimated time remaining are displayed throughout the run.

### Tab 3 — Model Outputs

All output charts are interactive (zoomable, hoverable, with exportable data).

**Prices & WTP** shows three exhibits: (1) a volume-weighted global SAF market price chart with a steelblue average line and a light-blue shaded band representing the min–max spread across served regions for each year; (2) a regional WTP trend chart with one line per region showing how each region's willingness-to-pay evolves over the horizon; and (3) a Compliance Cost Curve (MAC supply-demand chart) that blends physical SAF clearing prices with CORSIA offset costs weighted by each region's served/unserved volume, giving a market-wide average abatement cost per year.

**Capacity** contains two area charts: cumulative SAF capacity stacked by region, and cumulative capacity stacked by pathway. New-build additions by year are overlaid as bar marks. A summary table lists each plant with its region, pathway, nameplate capacity, and online year.

**Trade Flows** presents a Sankey diagram of inter-regional SAF trade (exporter regions on the left, importer regions on the right, flow width proportional to traded volume). Below the Sankey, ranked bar charts show the top exporting and importing regions for a user-selected year, and a detailed trade flow table lists every origin–destination–pathway flow with volume, transport cost, and CIF price.

**Price Decomposition** displays a stacked bar chart breaking each region's clearing price into its cost components (feedstock, processing OPEX, CAPEX annuity, transport) alongside a narrative paragraph explaining the dominant pricing regime and how the global average price composition shifts over the horizon.

### Tab 4 — Scenarios

Stores and compares completed model runs side-by-side. Each saved scenario appears as a named entry; selecting two or more renders overlay charts for global price, regional WTP, capacity, and trade volume, allowing direct visual comparison of how different input assumptions drive divergent market outcomes.

---

## Model Architecture

Each simulation year runs four sequential steps:

| Step | Module | What it does |
|------|--------|-------------|
| 1. Demand | `BottomUpDemandModule` | Derives SAF demand from 1,274 international routes and domestic blending mandates. Two modes: **Single CORSIA schedule** (global mandatory fraction × route-sample scaling) or **Country-specific SAF targets** (per-route SAF% interpolated across 2025/2030/2035/2040/2045 key years, no sampling). Demand attributed 60/40 origin/destination per CORSIA uplift rules. |
| 2. Expansion | `CapacityExpansionModule` | Assesses supply gap → solves a least-cost Pyomo LP → ranks candidate plants by LCOSAF → brings new plants online subject to feedstock availability and regional refinery co-processing caps. |
| 3. WTP | `WTPModel` | Computes regional WTP as `max(Case 1: jet+CORSIA, Case 2: LCOSAF@IRR, Case 3: policy penalty)`. |
| 4. Clearing | `PriceQuantityClearing` | Dispatches cheapest-CIF supply to highest-WTP regions. Domestic supply is reserved first (configurable share per region). Unserved demand routes to CORSIA carbon offsets. Clearing price = WTP of each served region. |

Capacity state accumulates year-over-year. Endogenous plants built in year *t* are available from year *t+1*.

---

## Project Structure

```
saf_market_model/
├── app.py                        # Streamlit UI entry point (4 tabs)
├── main.py                       # CLI entry point (python main.py)
├── requirements.txt
│
├── config/
│   └── settings.py               # Global constants: CAPEX/OPEX tables, FEED_INTENSITY,
│                                 #   REGION list, HORIZON_YEARS, ROUTE_SAMPLE_FRACTION, etc.
│
├── modules/
│   ├── demand_bottom_up.py       # Bottom-up demand (corsia_schedule + route_targets modes)
│   ├── capacity_expansion.py     # Pyomo LP capacity expansion
│   ├── wtp_model.py              # WTP (3-case max) + supply–demand curve
│   ├── price_quantity_clearing.py# WTP-priority market clearing
│   └── reporting.py              # CSV + Excel output writer
│
├── schemas/                      # Pydantic v2 data contracts
│   ├── demand_schema.py          #   DemandMatrix, DemandRecord
│   ├── supply_schema.py          #   CapacityState, PlantRecord, ExpansionDecision
│   ├── equilibrium_schema.py     #   MarketClearingResult, TradeFlow, RegionalPrice
│   ├── wtp_schema.py             #   WTPMatrix, WTPRecord
│   ├── flight_schema.py          #   FlightRecord, FlightDataset
│   └── state_schema.py           #   ModelState (annual snapshot passed to next year)
│
├── data/
│   ├── loaders.py                # CSV → Pydantic loaders (all I/O isolated here)
│   ├── keyinputs_SAFM_v1.xlsx    # Source workbook (aircraft, operators, routes)
│   ├── mock/                     # Live editable CSVs (edited via UI or directly)
│   │   ├── flight_routes.csv         # 1,274 routes with per-route SAF% targets
│   │   ├── aircraft_types.csv        # 14 aircraft types with fuel efficiency
│   │   ├── airlines.csv              # 163 operators with region and CORSIA status
│   │   ├── committed_capacity.csv    # 149 announced/operating plants (deterministic)
│   │   ├── corsia_schedule.csv       # Mandatory blending fraction by year
│   │   ├── corsia_suppression.csv    # Voluntary-only region demand suppression factors
│   │   ├── national_blending_mandates.csv  # Country-level mandates (SAF%, year)
│   │   ├── domestic_supply_priority.csv    # Domestic-first dispatch share by region
│   │   ├── feedstock_availability.csv      # Regional feedstock caps and costs
│   │   ├── refinery_capacity.csv           # Regional refinery throughput for co-processing cap
│   │   ├── regulatory_params.csv           # Penalty rates, IRR targets, jet fuel prices
│   │   ├── transport_costs.csv             # Inter-regional SAF CIF transport costs
│   │   └── wtp_params.csv                  # WTP override parameters
│   └── templates/                # Download-template copies of each mock CSV
│
├── ui/
│   ├── input_editor.py           # Tab 1: editable tables + demand/LCOSAF preview charts
│   ├── runner.py                 # Tab 2: BackgroundRunner (daemon thread + event queue)
│   ├── output_dashboard.py       # Tab 3: results charts and narrative text
│   ├── scenario_builder.py       # Tab 4: multi-scenario comparison
│   └── charts.py                 # All Plotly figure builders
│
├── utils/
│   ├── economics.py              # levelised_cost(), crf(), npv()
│   └── logging_config.py
│
├── tests/
│   ├── unit/                     # Per-module unit tests
│   └── integration/              # Single-year and full 20-year loop tests
│
└── outputs/                      # Timestamped run results (auto-created)
```

---

## Key Modelling Concepts

### Demand — Two Modes

**Mode 1: Single CORSIA Schedule** (`corsia_schedule`)
A global `mandatory_fraction` from `corsia_schedule.csv` is applied uniformly to all CORSIA-eligible international routes. A `route_sample_fraction` scales the sample-route volumes up to represent full global traffic. Domestic demand is added from `national_blending_mandates.csv`.

**Mode 2: Country-Specific SAF Targets** (`route_targets`)
Each of the 1,274 routes carries its own SAF% columns for key years 2025, 2030, 2035, 2040, and 2045. The model linearly interpolates between key years for every simulated year. `route_sample_fraction` is fixed at 1.0 (the full dataset requires no scaling). Domestic mandates are still applied.

Demand is attributed 60% to the origin region and 40% to the destination region (CORSIA uplift-point rule). MULTI-destination aggregate routes are attributed 100% to the origin.

### WTP — Willingness to Pay

Each region's WTP is the maximum of three cases:

| Case | Formula | Interpretation |
|------|---------|----------------|
| 1 — Market floor | Jet fuel price + CORSIA carbon credit × 2.5 tCO₂/MT SAF | Minimum a buyer pays to avoid purchasing CORSIA offsets |
| 2 — Investment floor | LCOSAF at region's target IRR (cheapest available pathway) | Minimum needed to make new capacity financially viable |
| 3 — Policy ceiling | Regulatory non-compliance penalty (e.g. EU ReFuelEU = $2,500/MT) | Maximum a buyer pays before preferring the penalty |

### LCOSAF

```
LCOSAF = (CRF(IRR, project_life) × CAPEX + OPEX_processing + OPEX_feedstock) / Utilisation
```

Feedstock OPEX = `feedstock_price_usd_per_t × feedstock_intensity_t_per_MT_SAF`

Default SAF yields by pathway (MT SAF / MT raw feedstock):

| Pathway | Primary feedstock | Yield |
|---------|------------------|-------|
| HEFA | UCO | 0.80 |
| ATJ | Agricultural residue | 0.22 |
| FT-MSW | MSW | 0.15 |
| PtL | CO₂ + green H₂ | 0.28 |
| Co-processing | UCO | 0.45 |

### Capacity Expansion

The LP minimises total discounted LCOSAF across candidate plants subject to:
- Regional feedstock availability caps
- Refinery co-processing headroom cap (regional throughput × configurable share)
- Minimum supply-gap fill requirement

New plants are ranked by LCOSAF and brought online at the start of the following year.

### Market Clearing

1. **Domestic-first phase**: each region's supply is reserved for local consumption up to its `domestic_share` fraction.
2. **Export pool phase**: surplus supply enters the cross-regional pool; it is dispatched cheapest-CIF first to regions in descending WTP order.
3. **Offset phase**: any unserved demand is routed to CORSIA carbon offsets at the prevailing offset price.

Clearing price for each served region = that region's WTP. The volume-weighted global average price (shown in the Outputs tab) covers only regions served by physical SAF, with a min–max band showing the spread across served regions.

### Committed Capacity

149 announced and operating SAF plants are loaded from `data/mock/committed_capacity.csv`. Plants with `online_year ≤ simulation_year` are included in the initial capacity state for that year. This dataset covers all six regions and all five pathways.

---

## Installation

```bash
git clone https://github.com/hammadainuddin/safm.git
cd safm
pip install -r requirements.txt
```

Requires Python 3.8+ and a compatible LP solver. Defaults to GLPK:

```bash
# macOS
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

Opens four tabs:

| Tab | Purpose |
|-----|---------|
| **📊 Inputs** | Edit all CSVs inline: routes, airlines, aircraft, capacity, costs, regulatory params. Preview demand projections and LCOSAF charts live. |
| **▶ Run Model** | Set scenario name and year range. Click Run. Watch a per-year step table and live log. |
| **📈 Outputs** | Global SAF price trend (line + range band), regional WTP, Compliance Cost Curve, capacity mix, Sankey trade flows, and price decomposition. |
| **🎭 Scenarios** | Load and compare multiple completed runs side-by-side. |

### CLI

```bash
# Full 2025–2050 baseline run
python main.py

# Custom horizon and scenario tag
python main.py --start 2025 --end 2030 --scenario high_demand

# Quiet (no per-year console output)
python main.py --quiet
```

---

## Outputs

Each run writes to `outputs/results_<timestamp>_<scenario>/`:

| File | Contents |
|------|----------|
| `prices.csv` | Clearing price by region and year, pricing regime, price decomposition |
| `trade_flows.csv` | Inter-regional SAF trade volumes, CIF transport costs, pathway label |
| `capacity.csv` | Capacity by region, pathway, and source (Committed / Modelled) |
| `market_summary.csv` | Annual demand, production, trade totals, offset volume, balance status |
| `summary_dashboard.xlsx` | Excel workbook: Prices, Trade Flows, Capacity sheets |

---

## Regions and Pathways

**Regions:** EU · US · APAC · MENA · LATAM · ROW

**SAF Pathways:** HEFA · ATJ · FT-MSW · PtL · Co-processing

---

## Configuration

Key parameters in `config/settings.py`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `ROUTE_SAMPLE_FRACTION` | `1.0` | Fraction of global traffic covered by the route dataset (1.0 = full 1,274-route dataset) |
| `UTILIZATION_FACTOR` | `0.85` | Nameplate capacity → effective annual output |
| `PROJECT_LIFE_YR` | `20` | Plant economic life for LCOSAF and capacity expansion LP |
| `DISCOUNT_RATE` | `0.10` | Default discount rate for NPV / expansion LP |
| `MT_TO_PJ_FACTOR` | `44.0` | Energy content conversion (MJ/kg × 10⁻³) |
| `MARKET_BALANCE_TOL` | `1e-4` | Supply–demand balance tolerance (MT) |

Regional CAPEX and OPEX tables, feedstock intensities, and WTP parameters are all in `settings.py` and can be overridden per-plant in `data/mock/committed_capacity.csv` or via the Inputs tab in the dashboard.

---

## Tests

```bash
pytest tests/ -q
```

Covers unit and integration scenarios including demand attribution, CORSIA scaling, WTP case calculation, market clearing, supply conservation, and the full 20-year dynamic loop (capacity monotonicity, price validity, output file integrity).

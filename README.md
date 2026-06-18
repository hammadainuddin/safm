# SARUS

**Sustainable Aviation (Demand) Rationalization and Utility System model**

A 26-year (2025–2050) dynamic simulation of the global Sustainable Aviation Fuel (SAF) market. SARUS combines bottom-up flight-demand estimation from a comprehensive 1,258-route dataset, least-cost capacity expansion, willingness-to-pay (WTP) pricing, and regional price–quantity clearing — all presented through a professional Streamlit application with sidebar navigation. The mark is a Sarus crane in flight carrying a sustainable-fuel leaf.

---

## Application

The app is organised as five pages in a branded sidebar:

| Page | Purpose |
|------|---------|
| **Inputs** | Edit all model input tables inline; preview demand projections live |
| **Run Model** | Configure a scenario and watch the run progress in real time |
| **Results** | KPI strip, prices, capacity build-out, and trade flows from the latest run |
| **Scenarios** | Save, load, and export named snapshots of all input tables |
| **LCOSAF Explorer** | Standalone levelised-cost calculator for scenario analysis |

### Inputs

All model inputs are editable directly in the browser across seven sub-tabs. Each section follows the same pattern: a collapsed **Methodology** expander, import controls (download template / upload CSV), live preview charts, and an editable table with a Save button. Saves are confirmed with a toast and immediately refresh the inline charts.

- **Demand** — choose the demand mode (*Single CORSIA schedule* or *Country-specific SAF targets*), toggle whether domestic routes are included (international-only by default), and set the route sample fraction and demand scaling factor. Live projection charts show jet-fuel burn and total SAF demand by region over the full horizon, with a CORSIA-vs-mandate breakdown. Six nested sub-tabs expose the underlying datasets: Routes (1,258 routes), Airlines, Aircraft, CORSIA Schedule, Suppression, and Mandates.
- **Committed Capacity** — all announced and operating SAF plants, plus the refinery co-processing capacity cap and the domestic-vs-export supply share.
- **Feedstock** — regional feedstock availability by type and year.
- **Costs** — annual (year × region × pathway) CAPEX, processing OPEX, and feedstock cost from `lcosaf_costs.csv`. These values drive both the capacity-expansion LP and the Case 2 WTP floor.
- **Transport** — inter-regional SAF CIF transport cost matrix.
- **Regulatory** — per-region, per-year pricing regime, mandate fraction, carbon tax, lifecycle CI reduction, green premium, and margin fraction.
- **WTP** — jet fuel price trajectory, CORSIA credit price, Case 3 market-WTP ceiling, and target IRR. Case 2 cost inputs live in the Costs tab.

### Run Model

Configure a scenario name and start/end year, then start the run. The model executes in a background thread and streams progress to the UI: a progress bar with elapsed/remaining time, a per-year step table (Demand, Expansion, Equilibrium, Done), and a scrollable plain-English run log. Runs continue even if you navigate to another page mid-run.

### Results

A KPI strip summarises the final modelled year (total demand, average clearing price, capacity online, traded volume) above four sub-tabs:

- **Market Summary** — annual demand, production, offset demand, and trade totals with a market-balance bar chart.
- **Prices & WTP** — volume-weighted global SAF price with a min–max range band across served regions; the Compliance Cost Curve (blended physical SAF + CORSIA offset cost); regional WTP trends with Case 1/2/3 breakdowns; an interactive supply–demand curve; and a price decomposition explorer with three view modes (all regions × all years facet grid, single region, single year). Each bar decomposes into Supply Cost, Transport, Mandate Premium, Carbon Offset, and Margin.
- **Capacity** — cumulative capacity stacked by region and by pathway (dispatched vs total built), with an optional idle-capacity view.
- **Trade Flows** — origin × destination heatmap, a Sankey diagram of inter-regional flows (node heights proportional to traded volume), pathway-level Sankey and stacked views, and the raw flow table.

All charts share a single design system (registered Plotly template) and every table is downloadable as CSV.

### Scenarios

A scenario is a named snapshot of all 13 input CSVs. Save the current inputs under a name, load a saved scenario back into the input tables, or download a combined Excel workbook containing every input sheet plus output sheets (Prices, Capacity, Trade Flows, Market Summary) when a completed run is attached.

### LCOSAF Explorer

A standalone calculator for exploring levelised SAF cost. Adjust CAPEX, processing OPEX, and feedstock cost per region–pathway (SAF yield is read-only — a physical property from `FEED_INTENSITY`), sweep the target IRR, and see the LCOSAF heatmap and bar chart update live. Values entered here are for scenario analysis only and do **not** affect model runs — model cost assumptions are edited in the Inputs → Costs tab.

---

## Model Architecture

Each simulation year runs four sequential steps:

| Step | Module | What it does |
|------|--------|-------------|
| 1. Demand | `BottomUpDemandModule` | Derives SAF demand from 1,258 routes. Two modes: **Single CORSIA schedule** (global mandatory fraction × route-sample scaling) or **Country-specific SAF targets** (per-route SAF% interpolated across 2025/2030/2035/2040/2045/2050 key years, no sampling). International demand is attributed 100% to the origin (departure) region per the CORSIA uplift-at-departure convention. Domestic routes are excluded by default; an Inputs-page toggle includes them (fuel burn + blending-mandate demand — CORSIA stays international-only). |
| 2. Expansion | `CapacityExpansionModule` | Assesses supply gap → solves a least-cost Pyomo LP → ranks candidate plants by LCOSAF → brings new plants online subject to feedstock availability and regional refinery co-processing caps. Per-year CAPEX/OPEX from `lcosaf_costs.csv`. |
| 3. WTP | `WTPModel` | Computes regional WTP as `max(Case 1: jet+CORSIA, Case 2: LCOSAF@IRR, Case 3: market WTP ceiling)`. |
| 4. Clearing | `PriceQuantityClearing` | Dispatches cheapest-CIF supply to highest-WTP regions. Domestic supply is reserved first (configurable share per region). Produces three pricing regimes per region: `wtp_priority_allocation` (fully served, price = WTP), `partial_supply` (partially served, price = WTP), `corsia_offset` (unserved, price = CORSIA credit cost). |

Capacity state accumulates year-over-year. Endogenous plants built in year *t* are available from year *t+1*.

---

## Project Structure

```
saf_market_model/
├── app.py                        # Streamlit entry point (st.navigation, 5 pages)
├── main.py                       # CLI entry point (python main.py)
├── requirements.txt
│
├── assets/
│   ├── icon.svg                  # App icon / favicon
│   └── wordmark.svg              # Sidebar wordmark
│
├── config/
│   └── settings.py               # Global constants: fallback CAPEX/OPEX tables,
│                                 #   FEED_INTENSITY, REGIONS, HORIZON_YEARS, etc.
│
├── modules/
│   ├── demand_bottom_up.py       # Bottom-up demand (corsia_schedule + route_targets modes)
│   ├── capacity_expansion.py     # Pyomo LP capacity expansion
│   ├── wtp_model.py              # WTP (3-case max) + supply–demand curve data
│   ├── price_quantity_clearing.py# WTP-priority market clearing
│   └── reporting.py              # CSV + Excel output writer
│
├── schemas/                      # Pydantic v2 data contracts
│   ├── demand_schema.py          #   DemandMatrix, DemandRecord
│   ├── supply_schema.py          #   CapacityState, PlantRecord, ExpansionDecision
│   ├── equilibrium_schema.py     #   MarketClearingResult, TradeFlow, RegionalPrice
│   ├── wtp_schema.py             #   WTPMatrix, RegionalWTP
│   ├── flight_schema.py          #   FlightRoute, BottomUpDemandResult
│   └── state_schema.py           #   ModelState (annual snapshot passed to next year)
│
├── data/
│   ├── loaders.py                # CSV → Pydantic loaders (all I/O isolated here)
│   ├── mock/                     # Live editable CSVs (edited via UI or directly)
│   │   ├── flight_routes.csv         # 1,258 routes with per-route SAF% targets
│   │   ├── aircraft_types.csv        # Aircraft types with fuel efficiency
│   │   ├── airlines.csv              # Operators with region and CORSIA status
│   │   ├── committed_capacity.csv    # Announced/operating plants (deterministic)
│   │   ├── corsia_schedule.csv       # Mandatory blending fraction by year
│   │   ├── corsia_suppression.csv    # Voluntary-only region demand suppression factors
│   │   ├── national_blending_mandates.csv  # Country-level mandates (SAF%, year)
│   │   ├── domestic_supply_priority.csv    # Domestic-first dispatch share by region
│   │   ├── feedstock_availability.csv      # Regional feedstock caps by type and year
│   │   ├── lcosaf_costs.csv                # Annual CAPEX, processing OPEX, feedstock cost
│   │   │                                   #   per (year, region, pathway)
│   │   ├── refinery_capacity.csv           # Regional refinery throughput for co-processing cap
│   │   ├── regulatory_params.csv           # Mandates, carbon tax, CI reduction, premiums
│   │   ├── transport_costs.csv             # Inter-regional SAF CIF transport costs
│   │   └── wtp_params.csv                  # Jet fuel price, credit price, Case 3, target IRR
│   └── templates/                # Download-template copies of each mock CSV
│
├── ui/
│   ├── theme.py                  # Design system: colors + registered Plotly template
│   ├── styles.py                 # Global CSS (fonts, sidebar, cards, tabs)
│   ├── components.py             # Shared building blocks (headers, editors, metrics)
│   ├── input_editor.py           # Inputs page: editable tables + preview charts
│   ├── run_model.py              # Run Model page: config + live progress fragment
│   ├── runner.py                 # BackgroundRunner (daemon thread + event queue)
│   ├── output_dashboard.py       # Results page: KPI strip + charts + narrative
│   ├── scenario_builder.py       # Scenarios page: save/load/export snapshots
│   ├── lcosaf_explorer.py        # LCOSAF Explorer page (standalone calculator)
│   └── charts.py                 # All Plotly figure builders
│
├── utils/
│   ├── economics.py              # levelised_cost(), crf(), npv()
│   └── logging_config.py
│
├── tests/
│   ├── unit/                     # Per-module unit tests
│   └── integration/              # Single-year and full multi-year loop tests
│
└── outputs/                      # Timestamped run results (auto-created)
```

---

## Key Modelling Concepts

### Demand — Two Modes

**Mode 1: Single CORSIA Schedule** (`corsia_schedule`)
A global `mandatory_fraction` from `corsia_schedule.csv` is applied uniformly to all CORSIA-eligible international routes. A `route_sample_fraction` scales the sample-route volumes up to represent full global traffic.

**Mode 2: Country-Specific SAF Targets** (`route_targets`)
Each route carries its own SAF% columns for key years 2025, 2030, 2035, 2040, 2045, and 2050. The model linearly interpolates between key years for every simulated year. `route_sample_fraction` is fixed at 1.0 (the full dataset requires no scaling).

International demand is attributed 100% to the origin (departure) region, following the CORSIA uplift-at-departure convention. **Domestic routes are excluded by default**; the *Include domestic routes* toggle on the Inputs page adds their fuel burn and blending-mandate SAF demand (CORSIA obligations remain international-only in both modes).

### WTP — Willingness to Pay

Each region's WTP is the maximum of three cases:

| Case | Formula | Interpretation |
|------|---------|----------------|
| 1 — Market floor | Jet fuel price + CORSIA credit × 3.1 tCO₂/MT SAF | Opportunity cost of SAF vs jet fuel + offsets |
| 2 — Investment floor | LCOSAF at region's target IRR (cheapest pathway), costs from `lcosaf_costs.csv` for that year | Minimum price that makes new capacity financially viable |
| 3 — Market WTP ceiling | Per-region trajectory in `wtp_params.csv` (`case3_penalty_usd_per_mt`) | Full price airlines will actually pay: jet baseline + ETS/LCFS/mandate compliance value + regional voluntary premium |

### LCOSAF

```
LCOSAF = (CRF(IRR, project_life) × CAPEX + OPEX_processing + OPEX_feedstock) / Utilisation
```

Feedstock OPEX = `feedstock_cost_usd_per_t × feedstock_intensity_t_per_MT_SAF`

CAPEX, processing OPEX, and feedstock cost are annual inputs per (year, region, pathway) in `data/mock/lcosaf_costs.csv`, editable in the Inputs → Costs tab. Default SAF yields by pathway (MT SAF / MT raw feedstock — physical properties from `FEED_INTENSITY`):

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
3. **Offset phase**: any remaining unserved demand is routed to CORSIA carbon offsets at the prevailing credit price.

Each region ends the year in one of three states:

| Regime | Condition | Clearing price |
|--------|-----------|----------------|
| `wtp_priority_allocation` | Fully served by physical SAF | Regional WTP |
| `partial_supply` | Physical SAF reached region but demand not fully covered | Regional WTP (same basis as fully served) |
| `corsia_offset` | No physical SAF at all | CORSIA credit price × lifecycle CI factor |

The volume-weighted global average price includes both fully-served and partially-served regions (both received real physical SAF at a real price), with a min–max shaded band showing the spread across those regions.

### Committed Capacity

Announced and operating SAF plants are loaded from `data/mock/committed_capacity.csv`. Plants with `online_year ≤ simulation_year` are included in the initial capacity state for that year. The dataset covers all six regions and all five pathways.

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

Opens the sidebar-navigation app described above. Pages have direct URLs: `/inputs`, `/run`, `/results`, `/scenarios`, `/lcosaf`.

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
| `ROUTE_SAMPLE_FRACTION` | `1.0` | Fraction of global traffic covered by the route dataset (1.0 = full dataset) |
| `UTILIZATION_FACTOR` | `0.85` | Nameplate capacity → effective annual output |
| `PROJECT_LIFE_YR` | `20` | Plant economic life for LCOSAF and capacity expansion LP |
| `DISCOUNT_RATE` | `0.10` | Default discount rate for NPV / expansion LP |
| `MT_TO_PJ_FACTOR` | `44.0` | Energy content conversion (MJ/kg × 10⁻³) |
| `MARKET_BALANCE_TOL` | `1e-4` | Supply–demand balance tolerance (MT) |

Cost assumptions (annual CAPEX, processing OPEX, feedstock cost per region and pathway) live in `data/mock/lcosaf_costs.csv` and are edited via the Inputs → Costs tab; the `REGIONAL_CAPEX`/`REGIONAL_OPEX` tables in `settings.py` serve as fallbacks when that file is absent. Feedstock intensities (`FEED_INTENSITY`) and other physical constants remain in `settings.py`.

---

## Tests

```bash
pytest tests/ -q
```

Covers unit and integration scenarios including demand attribution, CORSIA scaling, WTP case calculation, market clearing, supply conservation, and the full multi-year dynamic loop (capacity monotonicity, price validity, output file integrity).

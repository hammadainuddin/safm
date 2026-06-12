"""
Design system — single source of truth for colors, sizing, and the
registered Plotly template used by every chart in the app.

Import order matters only in that `register()` must run before any
figure is created; both `app.py` (entry) and `ui/charts.py` (module
import) call it, and the call is idempotent.
"""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

# ── Brand ────────────────────────────────────────────────────────────────────
PRIMARY       = "#0077B6"
PRIMARY_DARK  = "#023E8A"
PRIMARY_LIGHT = "#90E0EF"

# ── Neutrals ─────────────────────────────────────────────────────────────────
INK       = "#1A2B3C"   # headings / body text
INK_MUTED = "#5C677D"   # captions, secondary labels
GRAY_100  = "#EEF2F6"   # chart gridlines
GRAY_200  = "#E3E8EF"   # borders
SURFACE   = "#F6F9FC"   # secondary background

# ── Semantic ─────────────────────────────────────────────────────────────────
SUCCESS = "#2E7D32"
WARNING = "#ED6C02"
DANGER  = "#C62828"

FONT_STACK = "Inter, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"

# ── Categorical palettes ─────────────────────────────────────────────────────
REGION_COLORS = {
    "EU":    "#0077B6",
    "US":    "#D1495B",
    "APAC":  "#2E933C",
    "MENA":  "#EDAE49",
    "LATAM": "#7768AE",
    "ROW":   "#5C677D",
}

PATHWAY_COLORS = {
    "HEFA":          "#0077B6",
    "FT":            "#EDAE49",
    "ATJ":           "#2E933C",
    "FT-MSW":        "#B07D2B",
    "Co-processing": "#D1495B",
    "PtL":           "#7768AE",
    "Other":         "#8D99AE",
}

# Price decomposition components — keys match dataframe column names.
COMPONENT_COLORS = {
    "supply_cost_usd_per_mt":       "#0077B6",
    "transport_premium_usd_per_mt": "#EDAE49",
    "mandate_premium_usd_per_mt":   "#7768AE",
    "carbon_offset_usd_per_mt":     "#2E933C",
    "margin_usd_per_mt":            "#8D99AE",
}

COLORWAY   = list(REGION_COLORS.values()) + ["#B07D2B", "#3E8989"]
SEQUENTIAL = ["#EAF4FA", "#90E0EF", "#48B5D8", "#0077B6", "#023E8A"]

# ── Standard chart heights ───────────────────────────────────────────────────
HEIGHT_SM = 320
HEIGHT_MD = 420
HEIGHT_LG = 560


def register() -> None:
    """Register pio.templates['saf'] and set it as the default. Idempotent."""
    if pio.templates.default == "saf" and "saf" in pio.templates:
        return
    saf = go.layout.Template(pio.templates["plotly_white"])
    saf.layout.update(
        font=dict(family=FONT_STACK, size=13, color=INK),
        # Title pinned to the very top of the figure so it never collides
        # with the horizontal legend sitting just above the plot area.
        title=dict(font=dict(size=16, color=INK), x=0, xanchor="left",
                   y=0.985, yanchor="top", yref="container"),
        colorway=COLORWAY,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hoverlabel=dict(
            bgcolor="white",
            bordercolor=GRAY_200,
            font=dict(family=FONT_STACK, size=12, color=INK),
        ),
        margin=dict(l=10, r=10, t=84, b=10),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.0,
            xanchor="right", x=1.0, title_text="",
        ),
        xaxis=dict(
            gridcolor=GRAY_100, zerolinecolor=GRAY_200,
            ticks="outside", tickcolor=GRAY_200, linecolor=GRAY_200,
        ),
        yaxis=dict(gridcolor=GRAY_100, zerolinecolor=GRAY_200),
        coloraxis=dict(colorscale=[
            [i / (len(SEQUENTIAL) - 1), c] for i, c in enumerate(SEQUENTIAL)
        ]),
    )
    pio.templates["saf"] = saf
    pio.templates.default = "saf"

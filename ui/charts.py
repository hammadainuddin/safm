"""Plotly chart builders for the Streamlit output dashboard."""

from __future__ import annotations

from typing import List, Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


def price_line_chart(df: pd.DataFrame) -> go.Figure:
    """Clearing price by region over time."""
    fig = px.line(
        df, x="year", y="clearing_price_usd_per_mt", color="region",
        title="SAF Clearing Price by Region (USD/MT)",
        labels={"clearing_price_usd_per_mt": "Price (USD/MT)", "year": "Year"},
        markers=True,
    )
    fig.update_layout(
        legend_title="Region",
        hovermode="x unified",
        xaxis=dict(tickformat="d"),
    )
    return fig


def price_decomposition_bar(df: pd.DataFrame, region: str) -> go.Figure:
    """Stacked bar of price components for a single region."""
    region_df = df[df["region"] == region].sort_values("year")
    components = [
        "supply_cost_usd_per_mt",
        "transport_premium_usd_per_mt",
        "mandate_premium_usd_per_mt",
        "carbon_offset_usd_per_mt",
        "margin_usd_per_mt",
    ]
    labels = {
        "supply_cost_usd_per_mt": "Supply Cost",
        "transport_premium_usd_per_mt": "Transport",
        "mandate_premium_usd_per_mt": "Mandate Premium",
        "carbon_offset_usd_per_mt": "Carbon Offset",
        "margin_usd_per_mt": "Margin",
    }
    fig = go.Figure()
    for col in components:
        if col in region_df.columns:
            fig.add_trace(go.Bar(
                x=region_df["year"], y=region_df[col], name=labels.get(col, col)
            ))
    fig.update_layout(
        barmode="stack",
        title=f"Price Decomposition — {region}",
        xaxis_title="Year", yaxis_title="USD/MT",
        legend_title="Component",
        xaxis=dict(tickformat="d"),
    )
    return fig


def capacity_stacked_area(df: pd.DataFrame) -> go.Figure:
    """
    Dispatched capacity stacked by region, with a dashed line overlay showing
    total built capacity. The visible gap above the filled area is capacity that
    stayed idle (demand was satisfied by CORSIA offsets instead).
    """
    disp_col = "dispatched_capacity_mt_yr" if "dispatched_capacity_mt_yr" in df.columns else "total_capacity_mt_yr"
    pivot = df.groupby(["year", "region"])[disp_col].sum().reset_index()
    fig = px.area(
        pivot, x="year", y=disp_col, color="region",
        title="Cumulative SAF Capacity by Region (MT/yr) — Dispatched (filled) vs Total Built (dashed)",
        labels={disp_col: "Capacity (MT/yr)", "year": "Year"},
    )
    if "total_capacity_mt_yr" in df.columns:
        total = df.groupby("year")["total_capacity_mt_yr"].sum().reset_index()
        fig.add_trace(go.Scatter(
            x=total["year"], y=total["total_capacity_mt_yr"],
            mode="lines+markers", name="Total Built Capacity",
            line=dict(dash="dash", color="black", width=2),
            marker=dict(size=6, color="black"),
            hovertemplate="Total built: %{y:.3f} MT/yr<extra></extra>",
        ))
    fig.update_layout(
        legend_title="Region",
        hovermode="x unified",
        xaxis=dict(tickformat="d"),
    )
    return fig


def capacity_by_pathway(df: pd.DataFrame) -> go.Figure:
    """
    Dispatched capacity stacked by pathway, with a dashed line overlay showing
    total built capacity.
    """
    disp_col = "dispatched_capacity_mt_yr" if "dispatched_capacity_mt_yr" in df.columns else "total_capacity_mt_yr"
    pivot = df.groupby(["year", "pathway"])[disp_col].sum().reset_index()
    fig = px.area(
        pivot, x="year", y=disp_col, color="pathway",
        title="Cumulative SAF Capacity by Pathway (MT/yr) — Dispatched (filled) vs Total Built (dashed)",
        labels={disp_col: "Capacity (MT/yr)", "year": "Year"},
    )
    if "total_capacity_mt_yr" in df.columns:
        total = df.groupby("year")["total_capacity_mt_yr"].sum().reset_index()
        fig.add_trace(go.Scatter(
            x=total["year"], y=total["total_capacity_mt_yr"],
            mode="lines+markers", name="Total Built Capacity",
            line=dict(dash="dash", color="black", width=2),
            marker=dict(size=6, color="black"),
            hovertemplate="Total built: %{y:.3f} MT/yr<extra></extra>",
        ))
    fig.update_layout(
        legend_title="Pathway",
        hovermode="x unified",
        xaxis=dict(tickformat="d"),
    )
    return fig


def trade_heatmap(df: pd.DataFrame, year: int) -> go.Figure:
    """Origin × destination trade volume for a selected year."""
    year_df = df[df["year"] == year]
    if year_df.empty:
        return go.Figure().update_layout(title=f"No trade flows in {year}")
    pivot = year_df.pivot_table(
        index="origin_region", columns="destination_region",
        values="volume_mt", aggfunc="sum", fill_value=0
    )
    fig = px.imshow(
        pivot, text_auto=".2f",
        title=f"Trade Flows (MT) — {year}",
        labels={"x": "Destination", "y": "Origin", "color": "Volume (MT)"},
        color_continuous_scale="Blues",
    )
    return fig


def trade_sankey(df: pd.DataFrame, year: int) -> go.Figure:
    """Sankey diagram of trade flows for a selected year (loop-safe double node list)."""
    year_df = df[(df["year"] == year) & (df["volume_mt"] > 1e-4)]
    if year_df.empty:
        return go.Figure().update_layout(title=f"No trade flows in {year}")

    regions = sorted(set(year_df["origin_region"]) | set(year_df["destination_region"]))
    n = len(regions)
    exp_idx = {r: i for i, r in enumerate(regions)}
    imp_idx = {r: i + n for i, r in enumerate(regions)}

    labels = [f"{r} (export)" for r in regions] + [f"{r} (import)" for r in regions]
    colors = ["steelblue"] * n + ["seagreen"] * n
    x_pos = [0.01] * n + [0.99] * n
    y_pos = [i / max(n - 1, 1) for i in range(n)] + [i / max(n - 1, 1) for i in range(n)]

    source = [exp_idx[r] for r in year_df["origin_region"]]
    target = [imp_idx[r] for r in year_df["destination_region"]]
    value  = year_df["volume_mt"].tolist()

    _label_font = dict(
        color="white",
        size=13,
        weight="bold",
        shadow="1px 1px 3px #000, -1px -1px 3px #000, 1px -1px 3px #000, -1px 1px 3px #000",
    )

    fig = go.Figure(go.Sankey(
        arrangement="fixed",
        valueformat=".4f",
        valuesuffix=" Mt",
        textfont=_label_font,
        node=dict(label=labels, x=x_pos, y=y_pos, pad=15, thickness=20, color=colors),
        link=dict(source=source, target=target, value=value),
    ))
    fig.update_layout(title=f"SAF Trade Flows (million tonnes) — {year}")
    return fig


_PATHWAY_COLORS = {
    "HEFA":          "#1f77b4",
    "FT":            "#ff7f0e",
    "ATJ":           "#2ca02c",
    "Co-processing": "#d62728",
    "PtL":           "#9467bd",
    "Other":         "#7f7f7f",
}


def trade_pathway_sankey(df: pd.DataFrame, year: int) -> go.Figure:
    """
    Sankey: (origin region × pathway) → destination region for one year.
    Each link is one supply lane so the user can trace which pathway from
    which origin clears each destination's demand.
    """
    year_df = df[(df["year"] == year) & (df["volume_mt"] > 1e-4)].copy()
    if year_df.empty or "pathway" not in year_df.columns:
        return go.Figure().update_layout(title=f"No pathway-level trade in {year}")

    year_df["pathway"] = year_df["pathway"].fillna("").replace("", "Unspecified")
    agg = (
        year_df.groupby(["origin_region", "pathway", "destination_region"], as_index=False)
               ["volume_mt"].sum()
    )

    source_labels = sorted({f"{o} · {p}" for o, p in zip(agg["origin_region"], agg["pathway"])})
    target_labels = sorted({f"→ {d}" for d in agg["destination_region"]})
    src_idx = {label: i for i, label in enumerate(source_labels)}
    tgt_idx = {label: i + len(source_labels) for i, label in enumerate(target_labels)}

    labels = source_labels + target_labels
    node_colors = (
        [_PATHWAY_COLORS.get(label.split(" · ", 1)[1], "#7f7f7f") for label in source_labels]
        + ["#444444"] * len(target_labels)
    )

    def _rgba(hex_color: str, alpha: float = 0.55) -> str:
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgba({r},{g},{b},{alpha})"

    sources, targets, values, link_colors = [], [], [], []
    for _, row in agg.iterrows():
        s = src_idx[f"{row['origin_region']} · {row['pathway']}"]
        t = tgt_idx[f"→ {row['destination_region']}"]
        sources.append(s)
        targets.append(t)
        values.append(row["volume_mt"])
        link_colors.append(_rgba(_PATHWAY_COLORS.get(row["pathway"], "#7f7f7f")))

    _label_font = dict(
        color="white",
        size=13,
        weight="bold",
        shadow="1px 1px 3px #000, -1px -1px 3px #000, 1px -1px 3px #000, -1px 1px 3px #000",
    )

    fig = go.Figure(go.Sankey(
        arrangement="snap",
        valueformat=".4f",
        valuesuffix=" Mt",
        textfont=_label_font,
        node=dict(label=labels, pad=18, thickness=18, color=node_colors),
        link=dict(source=sources, target=targets, value=values, color=link_colors,
                  hovertemplate="%{source.label} → %{target.label}<br>Volume: %{value:.4f} Mt<extra></extra>"),
    ))
    fig.update_layout(
        title=f"Pathway-Level Trade Flows (million tonnes) — {year}",
        margin=dict(t=60, l=10, r=10, b=10),
    )
    return fig


def trade_pathway_stacked(df: pd.DataFrame, year: int) -> go.Figure:
    """
    Stacked bar: destination region on x-axis, stacked by (origin region, pathway)
    so the pathway composition of each importer's supply is visible at a glance.
    """
    year_df = df[(df["year"] == year) & (df["volume_mt"] > 1e-4)].copy()
    if year_df.empty or "pathway" not in year_df.columns:
        return go.Figure().update_layout(title=f"No pathway-level trade in {year}")

    year_df["pathway"] = year_df["pathway"].fillna("").replace("", "Unspecified")
    year_df["source"] = year_df["origin_region"] + " · " + year_df["pathway"]
    agg = (
        year_df.groupby(["destination_region", "source", "pathway"], as_index=False)
               ["volume_mt"].sum()
    )

    fig = go.Figure()
    for src in sorted(agg["source"].unique()):
        sub = agg[agg["source"] == src]
        pathway = sub["pathway"].iloc[0]
        fig.add_trace(go.Bar(
            x=sub["destination_region"], y=sub["volume_mt"],
            name=src,
            marker_color=_PATHWAY_COLORS.get(pathway, "#7f7f7f"),
            hovertemplate=(
                f"<b>{src}</b><br>→ %{{x}}<br>Volume: %{{y:.3f}} MT<extra></extra>"
            ),
        ))

    fig.update_layout(
        barmode="stack",
        title=f"Pathway Mix per Destination — {year}",
        xaxis_title="Destination Region",
        yaxis_title="Volume (MT)",
        legend_title="Origin · Pathway",
        hovermode="closest",
    )
    return fig


def market_balance_bar(df: pd.DataFrame) -> go.Figure:
    """CORSIA demand vs produced vs CORSIA offset demand vs traded by year."""
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df["year"], y=df["total_demand_mt"], name="CORSIA Demand"))
    fig.add_trace(go.Bar(x=df["year"], y=df["total_produced_mt"], name="Physical SAF Produced"))
    fig.add_trace(go.Bar(x=df["year"], y=df["total_traded_mt"], name="Traded", opacity=0.7))
    if "corsia_offset_demand_mt" in df.columns:
        fig.add_trace(go.Bar(
            x=df["year"], y=df["corsia_offset_demand_mt"],
            name="CORSIA Offset Demand",
            marker_color="#aaaaaa",
            marker_pattern_shape="\\",
            opacity=0.8,
        ))
    fig.update_layout(
        barmode="group",
        title="Market Balance: CORSIA Demand vs Physical SAF vs Offset (MT)",
        xaxis_title="Year", yaxis_title="MT",
        legend_title="Metric",
        xaxis=dict(tickformat="d"),
    )
    return fig


def demand_trajectory(df: pd.DataFrame) -> go.Figure:
    """Demand volume by region over time (from demand_mock.csv input)."""
    fig = px.line(
        df, x="year", y="volume_mt", color="region",
        title="CORSIA Demand Trajectory by Region (MT)",
        labels={"volume_mt": "Volume (MT)", "year": "Year"},
        markers=True,
    )
    fig.update_layout(
        legend_title="Region",
        hovermode="x unified",
        xaxis=dict(tickformat="d"),
    )
    return fig


def corsia_suppression_chart(df: pd.DataFrame) -> go.Figure:
    """CORSIA suppression factors by region over time."""
    fig = px.line(
        df, x="year", y="suppression_factor", color="region",
        title="CORSIA Demand Suppression Factors by Region",
        labels={"suppression_factor": "Suppression Factor (0–1)", "year": "Year"},
        markers=True,
    )
    fig.add_hline(y=1.0, line_dash="dash", line_color="gray", annotation_text="Full demand")
    fig.update_layout(
        yaxis_range=[0, 1.1],
        legend_title="Region",
        xaxis=dict(tickformat="d"),
    )
    return fig


def supply_demand_curve(demand_steps, supply_steps, year,
                        offset_mt=0.0, max_wtp=0.0, offset_price_usd_per_mt=0.0):
    """
    Pathway-level supply-demand bar chart with dispatched/undispatched supply and
    CORSIA offset demand.

    supply_steps : [(lcosaf, vol, region, pathway, dispatched), ...] sorted asc by lcosaf
    demand_steps : [(wtp, vol, region), ...] sorted desc by WTP
    offset_mt    : unserved demand volume covered by CORSIA carbon offsets
    offset_price_usd_per_mt : CORSIA carbon-offset cost per MT SAF
                              (= credit price × 3.1 tCO2/MT SAF). Used as the
                              y-axis height of the offset demand bar.
    max_wtp      : highest regional WTP — fallback only, no longer used directly.
    """
    _REGION_COLORS = {
        "EU": "#e6194b", "US": "#3cb44b", "APAC": "#4363d8",
        "MENA": "#f58231", "LATAM": "#911eb4", "ROW": "#42d4f4",
    }
    _default_colors = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#42d4f4"]

    def _color(region, idx=0):
        return _REGION_COLORS.get(region, _default_colors[idx % len(_default_colors)])

    fig = go.Figure()
    # trace_meta: (type, region)  where type ∈ "supply"|"undispatched"|"demand"|"offset"
    trace_meta = []

    # ── Supply bars: dispatched (solid) ─────────────────────────────────────
    # Legend shows one entry per region; same-region plants share the legendgroup
    cum_s = 0.0
    seen_dispatched: set = set()
    for lc, vol, region, pathway, dispatched in supply_steps:
        if not dispatched:
            cum_s += vol
            continue
        mid = cum_s + vol / 2
        first_for_region = region not in seen_dispatched
        seen_dispatched.add(region)
        fig.add_trace(go.Bar(
            x=[mid], y=[lc], width=[vol],
            name=f"{region} Supply",
            legendgroup=f"supply_{region}",
            marker_color=_color(region),
            opacity=0.9,
            showlegend=first_for_region,
            hovertemplate=(
                f"<b>{region} — {pathway}</b><br>"
                f"LCOSAF: ${lc:.0f}/MT<br>Vol: {vol:.3f} MT"
                f"<extra>Dispatched Supply</extra>"
            ),
        ))
        trace_meta.append(("supply", region))
        cum_s += vol

    # ── Supply bars: undispatched (low opacity, default hidden) ─────────────
    cum_s2 = 0.0
    seen_undispatched: set = set()
    for lc, vol, region, pathway, dispatched in supply_steps:
        mid = cum_s2 + vol / 2
        if not dispatched:
            first_for_region = region not in seen_undispatched
            seen_undispatched.add(region)
            fig.add_trace(go.Bar(
                x=[mid], y=[lc], width=[vol],
                name=f"{region} Unbuilt Capacity",
                legendgroup=f"undispatched_{region}",
                marker_color=_color(region),
                marker_pattern_shape="x",
                opacity=0.22,
                visible=False,
                showlegend=first_for_region,
                hovertemplate=(
                    f"<b>{region} — {pathway}</b><br>"
                    f"LCOSAF: ${lc:.0f}/MT<br>Vol: {vol:.3f} MT"
                    f"<extra>Unbuilt / Undispatched</extra>"
                ),
            ))
            trace_meta.append(("undispatched", region))
        cum_s2 += vol

    # ── Demand bars: CORSIA demand per region (hatched) ──────────────────────
    cum_d = 0.0
    for i, (wtp, vol, region) in enumerate(demand_steps):
        mid = cum_d + vol / 2
        fig.add_trace(go.Bar(
            x=[mid], y=[wtp], width=[vol],
            name=f"CORSIA Demand: {region}",
            legendgroup=f"demand_{region}",
            marker_color=_color(region, i),
            marker_pattern_shape="/",
            opacity=0.55,
            showlegend=True,
            hovertemplate=(
                f"<b>{region} CORSIA Demand</b><br>"
                f"WTP: ${wtp:.0f}/MT<br>Vol: {vol:.3f} MT"
                f"<extra></extra>"
            ),
        ))
        trace_meta.append(("demand", region))
        cum_d += vol

    # ── CORSIA Offset annotation (text box above unserved demand region) ────
    # The unserved demand is already visible as the rightmost demand bars (where
    # the demand chart extends past the supply chart). A simple annotation in
    # that gap summarises the volume and the CORSIA carbon-offset unit price,
    # avoiding a redundant bar.
    dispatched_x_end = sum(vol for _, vol, _, _, disp in supply_steps if disp)
    sd_annotations = []
    if offset_mt > 1e-6 and cum_d > dispatched_x_end + 1e-6:
        if offset_price_usd_per_mt and offset_price_usd_per_mt > 0:
            off_price = offset_price_usd_per_mt
        else:
            off_price = max_wtp if max_wtp > 0 else (demand_steps[0][0] if demand_steps else 0.0)
        anno_x = (dispatched_x_end + cum_d) / 2
        # Place the box above the tallest demand bar so it sits in clear space.
        max_demand_height = max((w for w, _, _ in demand_steps), default=0.0)
        anno_y = max_demand_height * 1.04 if max_demand_height > 0 else off_price * 1.04
        sd_annotations.append(dict(
            x=anno_x, y=anno_y, xref="x", yref="y",
            text=(
                f"<b>CORSIA Offset Demand</b><br>"
                f"{offset_mt:.3f} MT unserved by physical SAF<br>"
                f"Offset price ≈ ${off_price:.0f}/MT SAF"
            ),
            showarrow=True, arrowhead=2, arrowcolor="#666666",
            ax=0, ay=-30,
            align="center",
            bgcolor="rgba(245,245,245,0.92)",
            bordercolor="#888888", borderwidth=1, borderpad=6,
            font=dict(size=11, color="#333333"),
        ))

    all_regions = sorted({r for _, r in trace_meta})

    def _vis(keep_type=None, keep_region=None, show_undispatched=False):
        vis = []
        for t_type, t_region in trace_meta:
            if t_type == "undispatched":
                show = show_undispatched and (keep_type in (None, "supply", "undispatched")) and \
                       (keep_region is None or t_region == keep_region)
            else:
                show = (keep_type is None or t_type == keep_type) and \
                       (keep_region is None or t_region == keep_region)
            vis.append(show)
        return vis

    type_buttons = [
        dict(label="All",              method="restyle", args=[{"visible": _vis()}]),
        dict(label="Supply only",      method="restyle", args=[{"visible": _vis(keep_type="supply")}]),
        dict(label="Demand only",      method="restyle", args=[{"visible": _vis(keep_type="demand")}]),
        dict(label="Show Unbuilt Cap", method="restyle", args=[{"visible": _vis(show_undispatched=True)}]),
    ]

    region_buttons = [
        dict(label="All regions", method="restyle", args=[{"visible": _vis()}]),
    ] + [
        dict(label=r, method="restyle", args=[{"visible": _vis(keep_region=r)}])
        for r in all_regions
    ]

    fig.update_layout(
        barmode="overlay",
        # Title placed in paper coords clearly above the toggle row.
        title=dict(
            text=f"SAF Supply-Demand Curve — {year}",
            x=0.5, xanchor="center",
            y=0.99, yanchor="top",
            yref="container",
        ),
        xaxis=dict(
            title=dict(text="Cumulative Volume (MT)", standoff=12),
            tickformat=".2f",
        ),
        yaxis_title="Price / Cost (USD/MT SAF)",
        # Legend pushed well clear of the x-axis title.
        legend=dict(
            orientation="h",
            yanchor="top", y=-0.45,
            xanchor="center", x=0.5,
        ),
        hovermode="closest",
        updatemenus=[
            dict(
                type="buttons", direction="right",
                x=0.0, xanchor="left", y=1.06, yanchor="bottom",
                pad=dict(t=2, b=2, l=2, r=2),
                showactive=True, buttons=type_buttons,
            ),
            dict(
                type="dropdown",
                x=0.78, xanchor="left", y=1.06, yanchor="bottom",
                pad=dict(t=2, b=2, l=2, r=2),
                showactive=True, buttons=region_buttons,
            ),
        ],
        margin=dict(t=150, b=210),
        annotations=sd_annotations,
        height=720,
    )
    return fig


def wtp_breakdown_chart(df: pd.DataFrame) -> go.Figure:
    """
    WTP case breakdown by region for a given year.
    df columns: region, case1_value, case2_value, case3_value, wtp_usd_per_mt, binding_case
    """
    fig = go.Figure()
    cases = [
        ("case1_value", "Case 1: Jet+CORSIA", "steelblue"),
        ("case2_value", "Case 2: LCOSAF@IRR", "seagreen"),
        ("case3_value", "Case 3: Policy Penalty", "tomato"),
    ]
    for col, label, color in cases:
        if col in df.columns:
            fig.add_trace(go.Bar(
                x=df["region"], y=df[col],
                name=label,
                marker_color=color,
                opacity=0.7,
            ))

    # Overlay final WTP as a scatter
    if "wtp_usd_per_mt" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["region"], y=df["wtp_usd_per_mt"],
            mode="markers",
            name="Final WTP",
            marker=dict(symbol="diamond", size=10, color="black"),
        ))

    fig.update_layout(
        barmode="group",
        title="WTP Case Breakdown by Region",
        xaxis_title="Region",
        yaxis_title="USD/MT SAF",
        legend_title="WTP Case",
    )
    return fig


def wtp_trend_chart(df: pd.DataFrame) -> go.Figure:
    """
    WTP by region over time.
    df columns: year, region, wtp_usd_per_mt (all years, all regions)
    """
    fig = px.line(
        df, x="year", y="wtp_usd_per_mt", color="region",
        title="WTP by Region Over Time (USD/MT SAF)",
        labels={"wtp_usd_per_mt": "WTP (USD/MT)", "year": "Year"},
        markers=True,
    )
    fig.update_layout(
        legend_title="Region",
        hovermode="x unified",
        xaxis=dict(tickformat="d"),
    )
    return fig


_REGION_COLORS = {
    "EU": "steelblue", "US": "tomato", "APAC": "seagreen",
    "MENA": "gold", "LATAM": "mediumpurple", "ROW": "darkorange",
}


def capacity_stacked_split(df: pd.DataFrame) -> go.Figure:
    """
    SAF dispatched capacity split by Planned vs Modelled, stacked by region.
    Only shows dispatched (active) capacity; idle capacity is omitted — use
    idle_capacity_chart() to render it separately.
    """
    fig = go.Figure()
    has_split = "dispatched_capacity_mt_yr" in df.columns

    for cap_type in ["Planned", "Modelled"]:
        base_opacity = 1.0 if cap_type == "Planned" else 0.55
        type_df = df[df["capacity_type"] == cap_type]
        if type_df.empty:
            continue
        for region in sorted(type_df["region"].unique()):
            rdf = type_df[type_df["region"] == region]
            if has_split:
                grouped = rdf.groupby("year")["dispatched_capacity_mt_yr"].sum().reset_index()
                y_col = "dispatched_capacity_mt_yr"
            else:
                grouped = rdf.groupby("year")["total_capacity_mt_yr"].sum().reset_index()
                y_col = "total_capacity_mt_yr"
            fig.add_trace(go.Bar(
                x=grouped["year"], y=grouped[y_col],
                name=f"{region} ({cap_type})",
                marker_color=_REGION_COLORS.get(region, "gray"),
                opacity=base_opacity,
                hovertemplate=f"<b>{region} {cap_type}</b><br>Dispatched: %{{y:.3f}} MT/yr<extra></extra>",
            ))

    fig.update_layout(
        barmode="stack",
        title="SAF Dispatched Capacity by Region / Type (MT/yr)",
        xaxis_title="Year", yaxis_title="Dispatched Capacity (MT/yr)",
        xaxis=dict(tickformat="d"),
        legend_title="Region / Type",
        hovermode="x unified",
    )
    return fig


def idle_capacity_chart(df: pd.DataFrame) -> go.Figure:
    """
    Idle (undispatched) SAF capacity by region and type — capacity that was
    built but stayed unused because its LCOSAF exceeded the destination WTP
    and the residual demand fell to CORSIA offsets.
    """
    fig = go.Figure()
    if "undispatched_capacity_mt_yr" not in df.columns:
        fig.update_layout(title="No idle capacity data available")
        return fig

    for cap_type in ["Planned", "Modelled"]:
        base_opacity = 1.0 if cap_type == "Planned" else 0.55
        type_df = df[df["capacity_type"] == cap_type]
        if type_df.empty:
            continue
        for region in sorted(type_df["region"].unique()):
            rdf = type_df[type_df["region"] == region]
            grouped = rdf.groupby("year")["undispatched_capacity_mt_yr"].sum().reset_index()
            if grouped["undispatched_capacity_mt_yr"].sum() == 0:
                continue
            fig.add_trace(go.Bar(
                x=grouped["year"], y=grouped["undispatched_capacity_mt_yr"],
                name=f"{region} ({cap_type})",
                marker_color=_REGION_COLORS.get(region, "gray"),
                marker_pattern_shape="/",
                opacity=base_opacity * 0.6,
                hovertemplate=(
                    f"<b>{region} {cap_type} — idle</b><br>"
                    "Undispatched: %{y:.3f} MT/yr<extra></extra>"
                ),
            ))

    fig.update_layout(
        barmode="stack",
        title="SAF Idle Capacity by Region / Type (MT/yr)",
        xaxis_title="Year", yaxis_title="Idle Capacity (MT/yr)",
        xaxis=dict(tickformat="d"),
        legend_title="Region / Type",
        hovermode="x unified",
    )
    return fig


def global_price_chart(df: pd.DataFrame) -> go.Figure:
    """
    Volume-weighted global SAF market price with min–max range band.

    Average line: volume-weighted clearing price across all wtp_priority_allocation
    regions per year.  Shaded area: spread between the lowest- and highest-priced
    served region that year, illustrating the regional composition effect.

    Years with no physical SAF clearing are represented as NaN; connectgaps=True
    interpolates a straight line across any such gaps so the chart is always
    continuous from 2025 to 2050.
    """
    from config.settings import HORIZON_YEARS

    gdf = (
        df[df["region"] == "Global (vol-wtd)"]
        .sort_values("year")
        .set_index("year")
        .reindex(HORIZON_YEARS)
    )
    if gdf["clearing_price_usd_per_mt"].isna().all():
        return go.Figure().update_layout(title="No global price data available")

    years = list(HORIZON_YEARS)
    avg = gdf["clearing_price_usd_per_mt"].tolist()
    mn  = gdf["min_price_usd_per_mt"].tolist() if "min_price_usd_per_mt" in gdf.columns else avg
    mx  = gdf["max_price_usd_per_mt"].tolist() if "max_price_usd_per_mt" in gdf.columns else avg

    fig = go.Figure()

    # Upper bound — invisible anchor for the fill-between
    fig.add_trace(go.Scatter(
        x=years, y=mx, mode="lines",
        line=dict(width=0), showlegend=False, hoverinfo="skip",
        connectgaps=True,
    ))

    # Lower bound — filled up to the max trace, forming the shaded band
    fig.add_trace(go.Scatter(
        x=years, y=mn, mode="lines",
        line=dict(width=0),
        fill="tonexty",
        fillcolor="rgba(135, 206, 250, 0.25)",
        name="Regional price range (min–max)",
        hovertemplate="Min: $%{y:,.0f}/MT<extra></extra>",
        connectgaps=True,
    ))

    # Volume-weighted average line on top
    fig.add_trace(go.Scatter(
        x=years, y=avg,
        mode="lines+markers",
        line=dict(color="steelblue", width=3),
        marker=dict(size=7, color="steelblue"),
        name="Vol-weighted average",
        hovertemplate="Avg: $%{y:,.0f}/MT<extra>Global average</extra>",
        connectgaps=True,
    ))

    fig.update_layout(
        title="Volume-Weighted Global SAF Market Price (USD/MT)",
        xaxis=dict(tickformat="d", tickvals=years, title="Year"),
        yaxis=dict(title="Price (USD/MT)"),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def saf_compliance_cost_chart(df: pd.DataFrame) -> go.Figure:
    """
    S-curve: volume-weighted blended SAF compliance cost over time.

    Unserved demand is priced at the CORSIA carbon-offset cost for the year;
    served demand is priced at the region's WTP clearing price.  As physical
    SAF replaces cheap CORSIA offsets the blended average traces an S-shaped
    curve from the offset floor toward WTP.
    df columns: year, compliance_cost_usd_per_mt
    """
    if df.empty:
        return go.Figure().update_layout(title="No compliance cost data available")
    fig = px.line(
        df.sort_values("year"),
        x="year", y="compliance_cost_usd_per_mt",
        title="SAF Compliance Cost Curve — Volume-Weighted (USD/MT)",
        labels={"compliance_cost_usd_per_mt": "Compliance Cost (USD/MT)", "year": "Year"},
        markers=True,
    )
    fig.update_traces(line=dict(color="mediumseagreen", width=3))
    fig.update_layout(
        xaxis=dict(tickformat="d"),
        hovermode="x unified",
        annotations=[dict(
            xref="paper", yref="paper", x=0.01, y=0.06, showarrow=False,
            text="Served regions: WTP clearing price · Unserved regions: CORSIA offset cost",
            font=dict(size=11, color="gray"), align="left",
        )],
    )
    return fig


def lcosaf_heatmap(regions, pathways, capex_dict, opex_dict, util, irr, life) -> go.Figure:
    """Heatmap of LCOSAF (USD/MT) for all region × pathway combinations."""
    from utils.economics import levelised_cost
    z = []
    for region in regions:
        row_caps = capex_dict.get(region, capex_dict.get("ROW", {}))
        row_opex = opex_dict.get(region, opex_dict.get("ROW", {}))
        z.append([
            round(levelised_cost(row_caps.get(p, 2000), row_opex.get(p, 600), util, irr, life), 0)
            for p in pathways
        ])
    fig = px.imshow(
        z, x=pathways, y=regions,
        text_auto=".0f",
        title=f"LCOSAF by Region & Pathway (USD/MT) @ {irr*100:.0f}% IRR",
        labels={"x": "Pathway", "y": "Region", "color": "USD/MT"},
        color_continuous_scale="RdYlGn_r",
    )
    fig.update_layout(xaxis=dict(tickformat=""))
    return fig


def lcosaf_bar(regions, pathways, capex_dict, opex_dict, util, irr, life) -> go.Figure:
    """Grouped bar chart of LCOSAF by region, coloured by pathway."""
    from utils.economics import levelised_cost
    rows = []
    for region in regions:
        row_caps = capex_dict.get(region, capex_dict.get("ROW", {}))
        row_opex = opex_dict.get(region, opex_dict.get("ROW", {}))
        for p in pathways:
            lc = levelised_cost(row_caps.get(p, 2000), row_opex.get(p, 600), util, irr, life)
            rows.append({"region": region, "pathway": p, "lcosaf": round(lc, 0)})
    import pandas as _pd
    df = _pd.DataFrame(rows)
    fig = px.bar(
        df, x="region", y="lcosaf", color="pathway", barmode="group",
        title=f"LCOSAF by Region and Pathway (USD/MT) @ {irr*100:.0f}% IRR",
        labels={"lcosaf": "LCOSAF (USD/MT)", "region": "Region", "pathway": "Pathway"},
    )
    fig.update_layout(xaxis=dict(tickformat=""), legend_title="Pathway")
    return fig

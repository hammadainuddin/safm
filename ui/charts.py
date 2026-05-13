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
    """Total capacity by region stacked over time."""
    pivot = df.groupby(["year", "region"])["total_capacity_mt_yr"].sum().reset_index()
    fig = px.area(
        pivot, x="year", y="total_capacity_mt_yr", color="region",
        title="Cumulative SAF Capacity by Region (MT/yr)",
        labels={"total_capacity_mt_yr": "Capacity (MT/yr)", "year": "Year"},
    )
    fig.update_layout(
        legend_title="Region",
        hovermode="x unified",
        xaxis=dict(tickformat="d"),
    )
    return fig


def capacity_by_pathway(df: pd.DataFrame) -> go.Figure:
    """Capacity by pathway stacked over time."""
    pivot = df.groupby(["year", "pathway"])["total_capacity_mt_yr"].sum().reset_index()
    fig = px.area(
        pivot, x="year", y="total_capacity_mt_yr", color="pathway",
        title="Cumulative SAF Capacity by Pathway (MT/yr)",
        labels={"total_capacity_mt_yr": "Capacity (MT/yr)", "year": "Year"},
    )
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

    fig = go.Figure(go.Sankey(
        arrangement="fixed",
        node=dict(label=labels, x=x_pos, y=y_pos, pad=15, thickness=20, color=colors),
        link=dict(source=source, target=target, value=value),
    ))
    fig.update_layout(title=f"SAF Trade Flows (MT) — {year}")
    return fig


def market_balance_bar(df: pd.DataFrame) -> go.Figure:
    """Demand vs produced vs traded by year."""
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df["year"], y=df["total_demand_mt"], name="Demand"))
    fig.add_trace(go.Bar(x=df["year"], y=df["total_produced_mt"], name="Produced"))
    fig.add_trace(go.Bar(x=df["year"], y=df["total_traded_mt"], name="Traded", opacity=0.7))
    fig.update_layout(
        barmode="group",
        title="Market Balance: Demand vs Produced vs Traded (MT)",
        xaxis_title="Year", yaxis_title="MT",
        legend_title="Metric",
        xaxis=dict(tickformat="d"),
    )
    return fig


def demand_trajectory(df: pd.DataFrame) -> go.Figure:
    """Demand volume by region over time (from demand_mock.csv input)."""
    fig = px.line(
        df, x="year", y="volume_mt", color="region",
        title="SAF Demand Trajectory by Region (MT)",
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


def supply_demand_curve(demand_steps, supply_steps, year, offset_mt=0.0, max_wtp=0.0):
    """
    Pathway-level MAC bar chart with dispatched/undispatched supply and CORSIA offset demand.

    supply_steps : [(lcosaf, vol, region, pathway, dispatched), ...] sorted asc by lcosaf
    demand_steps : [(wtp, vol, region), ...] sorted desc by WTP
    offset_mt    : unserved demand volume covered by CORSIA carbon offsets
    max_wtp      : highest regional WTP (height of the offset demand bar)
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
    cum_s = 0.0
    for lc, vol, region, pathway, dispatched in supply_steps:
        if not dispatched:
            cum_s += vol
            continue
        mid = cum_s + vol / 2
        fig.add_trace(go.Bar(
            x=[mid], y=[lc], width=[vol],
            name=f"{region} — {pathway}",
            legendgroup=f"supply_{region}",
            marker_color=_color(region),
            opacity=0.9,
            showlegend=True,
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
    for lc, vol, region, pathway, dispatched in supply_steps:
        mid = cum_s2 + vol / 2
        if not dispatched:
            fig.add_trace(go.Bar(
                x=[mid], y=[lc], width=[vol],
                name=f"{region} — {pathway} (unbuilt)",
                legendgroup=f"undispatched_{region}",
                marker_color=_color(region),
                marker_pattern_shape="x",
                opacity=0.22,
                visible=False,
                showlegend=True,
                hovertemplate=(
                    f"<b>{region} — {pathway}</b><br>"
                    f"LCOSAF: ${lc:.0f}/MT<br>Vol: {vol:.3f} MT"
                    f"<extra>Unbuilt / Undispatched</extra>"
                ),
            ))
            trace_meta.append(("undispatched", region))
        cum_s2 += vol

    # ── Demand bars: SAF demand per region (hatched) ─────────────────────────
    cum_d = 0.0
    for i, (wtp, vol, region) in enumerate(demand_steps):
        mid = cum_d + vol / 2
        fig.add_trace(go.Bar(
            x=[mid], y=[wtp], width=[vol],
            name=f"SAF Demand: {region}",
            legendgroup=f"demand_{region}",
            marker_color=_color(region, i),
            marker_pattern_shape="/",
            opacity=0.55,
            showlegend=True,
            hovertemplate=(
                f"<b>{region} SAF Demand (CORSIA/mandate)</b><br>"
                f"WTP: ${wtp:.0f}/MT<br>Vol: {vol:.3f} MT"
                f"<extra></extra>"
            ),
        ))
        trace_meta.append(("demand", region))
        cum_d += vol

    # ── CORSIA Offset demand bar (grey hatched, appended to demand axis) ─────
    if offset_mt > 1e-6:
        off_height = max_wtp if max_wtp > 0 else (demand_steps[0][0] if demand_steps else 1000)
        mid_off = cum_d + offset_mt / 2
        fig.add_trace(go.Bar(
            x=[mid_off], y=[off_height], width=[offset_mt],
            name="CORSIA Offset Demand (unserved)",
            legendgroup="offset",
            marker_color="#aaaaaa",
            marker_pattern_shape="\\",
            opacity=0.65,
            showlegend=True,
            hovertemplate=(
                f"<b>CORSIA Carbon Offset Demand</b><br>"
                f"Unserved by physical SAF<br>Vol: {offset_mt:.3f} MT"
                f"<extra></extra>"
            ),
        ))
        trace_meta.append(("offset", "offset"))

    all_regions = sorted({r for _, r in trace_meta if r != "offset"})

    def _vis(keep_type=None, keep_region=None, show_undispatched=False):
        vis = []
        for t_type, t_region in trace_meta:
            if t_type == "undispatched":
                show = show_undispatched and (keep_type in (None, "supply", "undispatched")) and \
                       (keep_region is None or t_region == keep_region)
            elif t_type == "offset":
                show = (keep_type is None or keep_type == "demand")
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
        title=f"SAF Supply-Demand (MAC) Curve — {year}",
        xaxis_title="Cumulative Volume (MT)",
        yaxis_title="Price / Cost (USD/MT SAF)",
        xaxis=dict(tickformat=".2f"),
        legend=dict(orientation="h", yanchor="bottom", y=1.18, xanchor="right", x=1),
        hovermode="closest",
        updatemenus=[
            dict(
                type="buttons", direction="right",
                x=0.0, xanchor="left", y=1.22, yanchor="top",
                showactive=True, buttons=type_buttons,
            ),
            dict(
                type="dropdown",
                x=0.72, xanchor="left", y=1.22, yanchor="top",
                showactive=True, buttons=region_buttons,
            ),
        ],
        margin=dict(t=140),
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


def capacity_stacked_split(df: pd.DataFrame) -> go.Figure:
    """
    SAF capacity split by Planned vs Modelled, stacked by region.
    df columns: year, region, total_capacity_mt_yr, capacity_type
    """
    fig = go.Figure()
    region_colors = {
        "EU": "steelblue", "US": "tomato", "APAC": "seagreen",
        "MENA": "gold", "LATAM": "mediumpurple", "ROW": "darkorange",
    }
    for cap_type in ["Planned", "Modelled"]:
        opacity = 1.0 if cap_type == "Planned" else 0.55
        type_df = df[df["capacity_type"] == cap_type]
        if type_df.empty:
            continue
        for region in sorted(type_df["region"].unique()):
            rdf = type_df[type_df["region"] == region].groupby("year")["total_capacity_mt_yr"].sum().reset_index()
            fig.add_trace(go.Bar(
                x=rdf["year"], y=rdf["total_capacity_mt_yr"],
                name=f"{region} ({cap_type})",
                marker_color=region_colors.get(region, "gray"),
                opacity=opacity,
                showlegend=True,
            ))
    fig.update_layout(
        barmode="stack",
        title="SAF Capacity: Planned vs Modelled (MT/yr)",
        xaxis_title="Year", yaxis_title="Capacity (MT/yr)",
        xaxis=dict(tickformat="d"),
        legend_title="Region / Type",
        hovermode="x unified",
    )
    return fig


def global_price_chart(df: pd.DataFrame) -> go.Figure:
    """
    Volume-weighted global SAF market price over time.
    df: prices DataFrame filtered to region == 'Global (vol-wtd)'
    """
    gdf = df[df["region"] == "Global (vol-wtd)"].sort_values("year")
    if gdf.empty:
        return go.Figure().update_layout(title="No global price data available")
    fig = px.line(
        gdf, x="year", y="clearing_price_usd_per_mt",
        title="Volume-Weighted Global SAF Market Price (USD/MT)",
        labels={"clearing_price_usd_per_mt": "Price (USD/MT)", "year": "Year"},
        markers=True,
    )
    fig.update_traces(line=dict(color="lightskyblue", width=3))
    fig.update_layout(xaxis=dict(tickformat="d"), hovermode="x unified")
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

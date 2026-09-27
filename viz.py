"""Map schematic and charts (Plotly). No Streamlit import."""
from __future__ import annotations

import math

import plotly.graph_objects as go

import model as M

PLANT = "#2563eb"
GRINDER = "#ea7a12"
MARKET = "#6b7280"
CLINKER = "#1d4ed8"
CEMENT = "#9ca3af"
COMPONENT_COLORS = {
    "Annualised capex": "#1e3a8a", "Fixed opex": "#3b82f6", "Limestone": "#a3a3a3",
    "Cement freight": "#f59e0b", "Clinker freight": "#b45309",
}


def _arrowhead(lat0, lon0, lat1, lon1, size=0.55, back=0.35):
    """Two short segments forming an arrowhead near (lat1, lon1), pointing from 0 → 1."""
    dx, dy = lon1 - lon0, lat1 - lat0
    L = math.hypot(dx, dy) or 1.0
    ux, uy = dx / L, dy / L
    # tip pulled back slightly so it is not hidden under the grinder marker
    tx, ty = lon1 - ux * back, lat1 - uy * back
    lons, lats = [], []
    for sgn in (1, -1):
        ang = math.radians(25) * sgn
        bx = -(ux * math.cos(ang) - uy * math.sin(ang)) * size
        by = -(ux * math.sin(ang) + uy * math.cos(ang)) * size
        lons += [tx + bx, tx, None]
        lats += [ty + by, ty, None]
    return lats, lons


def network_map(res: dict, inputs: dict, show_cement=True, height=640) -> go.Figure:
    fig = go.Figure()
    site_ll = {s: (M.SITE_INFO[s][2], M.SITE_INFO[s][3]) for s in M.SITES}
    mkt_ll = {m: (M.MARKET_INFO[m][2], M.MARKET_INFO[m][3]) for m in M.MARKETS}
    open_ = {s for s, k in (res.get("modules") or {}).items() if k}

    # cement lanes (source → market), light
    if show_cement and res.get("cement_flows"):
        mx = max(f["Mt"] for f in res["cement_flows"])
        for f in res["cement_flows"]:
            (a, b), (c, d) = site_ll[f["source"]], mkt_ll[f["market"]]
            fig.add_trace(go.Scattergeo(
                lat=[a, c], lon=[b, d], mode="lines", showlegend=False, hoverinfo="text",
                text=f"{f['source']}→{f['market']}: {f['Mt']:.2f} Mt, {f['distance']} km",
                line=dict(width=0.8 + 3 * f["Mt"] / mx, color=CEMENT), opacity=0.55))

    # clinker lanes: PLANT → GRINDER ONLY (enforced here, not just in the model)
    for f in res.get("clinker_flows") or []:
        if f["plant"] not in M.INTEGRATED or f["grinder"] not in M.GRINDERS:
            raise ValueError(f"Illegal clinker lane {f['plant']}→{f['grinder']}: "
                             "clinker moves integrated plant → grinding unit only.")
        (a, b), (c, d) = site_ll[f["plant"]], site_ll[f["grinder"]]
        w = 1.5 + 2.5 * f["Mt"]
        txt = f"Clinker {f['plant']}→{f['grinder']}: {f['Mt']:.3f} Mt, {f['distance']} km"
        fig.add_trace(go.Scattergeo(lat=[a, c], lon=[b, d], mode="lines", showlegend=False,
                                    hoverinfo="text", text=txt,
                                    line=dict(width=w, color=CLINKER)))
        hl, ho = _arrowhead(a, b, c, d)
        fig.add_trace(go.Scattergeo(lat=hl, lon=ho, mode="lines", showlegend=False,
                                    hoverinfo="skip", line=dict(width=w, color=CLINKER)))

    # markets
    fig.add_trace(go.Scattergeo(
        lat=[mkt_ll[m][0] for m in M.MARKETS], lon=[mkt_ll[m][1] for m in M.MARKETS],
        mode="markers+text", name="Market cluster",
        marker=dict(symbol="diamond", size=[6 + 2.2 * inputs["demand"][m] for m in M.MARKETS],
                    color=MARKET, opacity=0.8),
        text=[m for m in M.MARKETS], textposition="bottom center", textfont=dict(size=9, color=MARKET),
        hovertext=[f"{m} {M.MARKET_INFO[m][0]} — {inputs['demand'][m]:.3f} Mt" for m in M.MARKETS],
        hoverinfo="text"))

    def sites_trace(group, symbol, color, label):
        lat, lon, txt, hov, size, line = [], [], [], [], [], []
        mods = res.get("modules") or {}
        for s in group:
            lat.append(site_ll[s][0]); lon.append(site_ll[s][1])
            k = mods.get(s)
            txt.append(f"{s}-{k}" if k else s)
            hov.append(f"{s} {M.SITE_INFO[s][0]} — " + (f"module {k}" if k else "not opened"))
            size.append(18 if s in open_ else 10)
        return go.Scattergeo(
            lat=lat, lon=lon, mode="markers+text", name=label, text=txt,
            textposition="top center", textfont=dict(size=11, color=color),
            hovertext=hov, hoverinfo="text",
            marker=dict(symbol=symbol, size=size,
                        color=[color if s in open_ else "rgba(0,0,0,0)" for s in group],
                        line=dict(width=2, color=color)))

    fig.add_trace(sites_trace(M.INTEGRATED, "circle", PLANT, "Integrated plant (filled = open)"))
    fig.add_trace(sites_trace(M.GRINDERS, "square", GRINDER, "Split-grinding unit (filled = open)"))
    fig.add_trace(go.Scattergeo(lat=[None], lon=[None], mode="lines", name="Clinker lane (plant → grinder)",
                                line=dict(color=CLINKER, width=3)))
    if show_cement:
        fig.add_trace(go.Scattergeo(lat=[None], lon=[None], mode="lines", name="Cement lane",
                                    line=dict(color=CEMENT, width=2)))

    fig.update_geos(scope="asia", projection_type="mercator", lataxis_range=[7, 34],
                    lonaxis_range=[67, 92], showcountries=True, countrycolor="#cbd5e1",
                    showland=True, landcolor="#f8fafc", showocean=True, oceancolor="#e0f2fe",
                    showsubunits=True, subunitcolor="#e2e8f0")
    fig.update_layout(height=height, margin=dict(l=0, r=0, t=10, b=0),
                      legend=dict(orientation="h", yanchor="bottom", y=0.0, x=0.0,
                                  bgcolor="rgba(255,255,255,0.8)"))
    return fig


def cost_waterfall(costs: dict, total: float) -> go.Figure:
    names = list(costs) + ["Total"]
    vals = list(costs.values()) + [total]
    fig = go.Figure(go.Waterfall(
        x=names, y=vals, measure=["relative"] * len(costs) + ["total"],
        text=[f"{v:,.0f}" for v in vals], textposition="outside",
        connector=dict(line=dict(color="#94a3b8")),
        increasing=dict(marker=dict(color="#3b82f6")), totals=dict(marker=dict(color="#1e3a8a"))))
    fig.update_layout(height=360, margin=dict(l=10, r=10, t=30, b=10),
                      yaxis_title="₹ crore / yr", showlegend=False)
    return fig


def component_bars(rows: list[dict]) -> go.Figure:
    """rows: [{'name':..., 'costs': {...}}] — stacked bars by cost component."""
    fig = go.Figure()
    for comp, color in COMPONENT_COLORS.items():
        fig.add_trace(go.Bar(name=comp, x=[r["name"] for r in rows],
                             y=[r["costs"].get(comp, 0) if r.get("costs") else 0 for r in rows],
                             marker_color=color))
    fig.update_layout(barmode="stack", height=380, margin=dict(l=10, r=10, t=30, b=10),
                      yaxis_title="₹ crore / yr", legend=dict(orientation="h", y=1.1))
    return fig


def utilisation_bars(res: dict, beta: float) -> go.Figure:
    sites = res["sites"]
    fig = go.Figure()
    fig.add_trace(go.Bar(name="Grinding", x=[s["site"] for s in sites],
                         y=[s["util_grinding"] for s in sites], marker_color=GRINDER))
    fig.add_trace(go.Bar(name="Clinker", x=[s["site"] for s in sites],
                         y=[s["util_clinker"] or 0 for s in sites], marker_color=PLANT))
    fig.add_hline(y=beta * 100, line_dash="dash", line_color="#dc2626",
                  annotation_text=f"β = {beta:.0%}")
    fig.update_layout(barmode="group", height=320, margin=dict(l=10, r=10, t=30, b=10),
                      yaxis_title="% of nameplate", yaxis_range=[0, 105],
                      legend=dict(orientation="h", y=1.12))
    return fig


def band_chart(networks: list, optimum: float, opt_sites: tuple) -> go.Figure:
    same = [n for n in networks if n["sites"] == opt_sites and not n.get("is_optimum")]
    diff = [n for n in networks if n["sites"] != opt_sites]
    fig = go.Figure()
    fig.add_trace(go.Histogram(x=[n["premium"] * 100 for n in same], name="Same site set, re-sized",
                               marker_color=PLANT, xbins=dict(size=0.1)))
    fig.add_trace(go.Histogram(x=[n["premium"] * 100 for n in diff], name="Different site set",
                               marker_color=GRINDER, xbins=dict(size=0.1)))
    for b in (0.5, 1, 2, 5):
        fig.add_vline(x=b, line_dash="dot", line_color="#64748b", annotation_text=f"{b}%")
    fig.update_layout(barmode="stack", height=320, margin=dict(l=10, r=10, t=30, b=10),
                      xaxis_title="Premium over optimum (%)", yaxis_title="Networks",
                      legend=dict(orientation="h", y=1.12))
    return fig

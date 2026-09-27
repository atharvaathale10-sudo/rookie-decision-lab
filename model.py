"""The Rookie — cement network-design MILP.

Data + build_model() + solve(). No Streamlit import: this module is importable,
testable and runnable from the command line on its own.

    python model.py            # solves the base case and prints the result
"""
from __future__ import annotations

import copy
import itertools
import math
import time

import pulp

try:  # fast path for the LP re-solves used by enumeration
    import highspy
except ImportError:  # pragma: no cover
    highspy = None

# ---------------------------------------------------------------------------
# 1. Case data (spec section 2)
# ---------------------------------------------------------------------------

MARKETS = ["M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9", "M10", "M11", "M12"]
INTEGRATED = ["I1", "I2", "I3", "I4", "I5", "I6"]
GRINDERS = ["G1", "G2", "G3", "G4"]
SITES = INTEGRATED + GRINDERS
MODULES = ["S", "M", "L"]

MARKET_INFO = {
    "M1": ("Delhi NCR / Upper North", "Delhi NCR", 28.61, 77.21),
    "M2": ("Rajasthan", "Jaipur", 26.91, 75.79),
    "M3": ("Uttar Pradesh", "Lucknow", 26.85, 80.95),
    "M4": ("Madhya Pradesh", "Bhopal", 23.26, 77.41),
    "M5": ("Gujarat", "Ahmedabad", 23.02, 72.57),
    "M6": ("Maharashtra & Goa", "Pune", 18.52, 73.86),
    "M7": ("Bihar & Jharkhand", "Patna", 25.59, 85.14),
    "M8": ("West Bengal & NE", "Kolkata", 22.57, 88.36),
    "M9": ("Odisha & Chhattisgarh", "Bhubaneswar", 20.30, 85.82),
    "M10": ("Andhra & Telangana", "Hyderabad", 17.39, 78.49),
    "M11": ("Karnataka & Kerala", "Bengaluru", 12.97, 77.59),
    "M12": ("Tamil Nadu", "Chennai", 13.08, 80.27),
}

BASE_DEMAND = {
    "M1": 3.995, "M2": 1.900, "M3": 3.400, "M4": 1.745, "M5": 1.860, "M6": 3.900,
    "M7": 2.800, "M8": 3.050, "M9": 3.085, "M10": 3.100, "M11": 2.500, "M12": 2.445,
}
SCENARIO_A_DEMAND = {
    "M1": 3.993, "M2": 1.899, "M3": 3.731, "M4": 1.915, "M5": 1.640, "M6": 3.439,
    "M7": 3.155, "M8": 3.437, "M9": 3.476, "M10": 2.734, "M11": 2.205, "M12": 2.156,
}
BASE_SHARE = 5.0  # % — the client target is 5% of the FY2030 market

SITE_INFO = {
    "I1": ("Chittorgarh–Nimbahera", "Rajasthan", 24.9, 74.6),
    "I2": ("Kachchh / Bhuj", "Gujarat", 23.2, 69.7),
    "I3": ("Satna–Rewa", "Madhya Pradesh", 24.6, 80.8),
    "I4": ("Baloda Bazar–Raipur", "Chhattisgarh", 21.7, 82.2),
    "I5": ("Kurnool–Kadapa", "Andhra Pradesh", 15.8, 78.0),
    "I6": ("Kalaburagi–Wadi", "Karnataka", 17.3, 76.8),
    "G1": ("Dadri / Greater Noida", "NCR", 28.6, 77.5),
    "G2": ("Pune", "Maharashtra", 18.5, 73.9),
    "G3": ("Sankrail / Kolkata", "West Bengal", 22.6, 88.2),
    "G4": ("Chennai", "Tamil Nadu", 13.1, 80.3),
}

LIMESTONE = {"I1": 205, "I2": 225, "I3": 195, "I4": 200, "I5": 210, "I6": 215}

INT_MODULES = {  # clinker MTPA, grinding MTPA, capex ₹cr, fixed opex ₹cr/yr
    "S": {"clk": 3.0, "grd": 2.5, "capex": 2500, "opex": 90},
    "M": {"clk": 4.5, "grd": 3.5, "capex": 3300, "opex": 120},
    "L": {"clk": 6.0, "grd": 5.0, "capex": 4200, "opex": 155},
}
GRD_MODULES = {  # grinding MTPA, capex ₹cr, fixed opex ₹cr/yr
    "S": {"grd": 2.5, "capex": 700, "opex": 28},
    "M": {"grd": 4.0, "capex": 1000, "opex": 38},
    "L": {"grd": 6.0, "capex": 1500, "opex": 55},
}

BASE_PARAMS = {
    "r": 0.11,        # hurdle rate
    "n": 20,          # asset life, years
    "beta": 0.90,     # max planned utilisation
    "theta": 0.66,    # t clinker / t cement
    "lam": 1.5,       # t limestone / t clinker
    "fc": 3.03,       # ₹/t-km finished cement
    "fk": 1.60,       # ₹/t-km clinker
    "gamma": 0.1,     # ₹cr per (Mt × ₹/t)
    "Lcem": 800,      # km max cement lane
    "Lclk": 1300,     # km max clinker lane
    "mip_gap": 1e-4,  # relative MIP gap
}

_D_I = {
    "I1": [580, 300, 800, 400, 350, 860, 1270, 1700, 1510, 1110, 1630, 1730],
    "I2": [1150, 890, 1440, 950, 360, 820, 1900, 2300, 2040, 1350, 1700, 1910],
    "I3": [690, 680, 300, 450, 1030, 1180, 540, 960, 840, 1000, 1600, 1540],
    "I4": [1100, 1040, 710, 620, 1200, 1120, 640, 780, 490, 730, 1300, 1170],
    "I5": [1710, 1500, 1510, 1000, 1180, 640, 1570, 1580, 1150, 220, 390, 470],
    "I6": [1510, 1280, 1370, 800, 930, 410, 1510, 1600, 1200, 210, 590, 720],
}
_D_G = {
    "G1": [40, 300, 460, 710, 950, 1410, 980, 1520, 1490, 1490, 2080, 2090],
    "G2": [1410, 1140, 1410, 770, 620, 0, 1680, 1890, 1520, 610, 880, 1100],
    "G3": [1550, 1610, 1050, 1330, 1930, 1870, 550, 20, 430, 1400, 1860, 1620],
    "G4": [2110, 1930, 1840, 1410, 1650, 1100, 1780, 1630, 1200, 620, 350, 0],
}
_D_K = {
    "I1": [580, 820, 1620, 1660],
    "I2": [1130, 780, 2190, 1830],
    "I3": [630, 1130, 900, 1470],
    "I4": [1030, 1070, 730, 1120],
    "I5": [1630, 620, 1500, 450],
    "I6": [1440, 390, 1520, 690],
}
DIST_CEM = {s: dict(zip(MARKETS, row)) for s, row in {**_D_I, **_D_G}.items()}
DIST_CLK = {i: dict(zip(GRINDERS, row)) for i, row in _D_K.items()}

SCOPE_EXCLUSIONS = (
    "Inventory and working capital, implementation phasing, taxes and incentives, common "
    "variable conversion cost, and all other raw materials, power, packaging and labour are "
    "outside this comparison."
)
BIAS_NOTE = (
    "Omitting inventory and working capital favours MORE, SMALLER sites than a full-cost "
    "model would; the true optimum leans towards fewer, larger sites."
)


def crf(r: float, n: float) -> float:
    """Capital recovery factor r(1+r)^n / ((1+r)^n - 1)."""
    if r == 0:
        return 1.0 / n
    g = (1 + r) ** n
    return r * g / (g - 1)


def market_sizes() -> dict:
    """FY2030 total market by cluster, Mt (client target / 5%)."""
    return {m: BASE_DEMAND[m] / (BASE_SHARE / 100) for m in MARKETS}


def demand_at_share(share_pct: float, mix: dict | None = None) -> dict:
    """Rescale a demand mix (default: base) to a market share %."""
    mix = mix or BASE_DEMAND
    return {m: mix[m] * share_pct / BASE_SHARE for m in MARKETS}


def default_inputs() -> dict:
    """The full base-case input dict. Every number the solver uses lives here."""
    return {
        "demand": dict(BASE_DEMAND),
        "limestone": dict(LIMESTONE),
        "int_modules": copy.deepcopy(INT_MODULES),
        "grd_modules": copy.deepcopy(GRD_MODULES),
        "params": dict(BASE_PARAMS),
        "dist_cem": copy.deepcopy(DIST_CEM),
        "dist_clk": copy.deepcopy(DIST_CLK),
        # "available" | "forced" | "excluded"
        "site_status": {s: "available" for s in SITES},
        # optional module lock for a forced/available site: None or "S"/"M"/"L"
        "module_lock": {s: None for s in SITES},
        # "C" full redesign | "B" re-route only | "A" fixed plan
        "mode": "C",
        # for modes A/B: {site: module or None}
        "fixed_modules": None,
        # for mode A: {"cement": {(src, m): Mt}, "clinker": {(i, g): Mt}} (keys as "src|m")
        "fixed_flows": None,
    }


# ---------------------------------------------------------------------------
# 2. Model helpers
# ---------------------------------------------------------------------------

def _mods(inputs, site):
    return inputs["int_modules"] if site in INTEGRATED else inputs["grd_modules"]


def annual_fixed(inputs, site, k) -> float:
    p = inputs["params"]
    mod = _mods(inputs, site)[k]
    return mod["capex"] * crf(p["r"], p["n"]) + mod["opex"]


def lanes(inputs):
    """Feasible lanes under the current distance caps."""
    p = inputs["params"]
    dc, dk = inputs["dist_cem"], inputs["dist_clk"]
    cem = [(s, m) for s in SITES for m in MARKETS if dc[s][m] <= p["Lcem"]]
    clk = [(i, g) for i in INTEGRATED for g in GRINDERS if dk[i][g] <= p["Lclk"]]
    return cem, clk


def lane_summary(inputs) -> dict:
    cem, clk = lanes(inputs)
    n_ci = sum(1 for s, _ in cem if s in INTEGRATED)
    return {
        "cement_lanes": len(cem), "cement_from_plants": n_ci,
        "cement_from_grinders": len(cem) - n_ci, "clinker_lanes": len(clk),
        "flow_vars": len(cem) + len(clk), "binaries": 3 * len(SITES),
        "full_matrix": len(SITES) * len(MARKETS) + len(INTEGRATED) * len(GRINDERS),
    }


def allowed_modules(inputs, site) -> list:
    """Modules the site may take in the current mode (empty = must be closed)."""
    mode = inputs.get("mode", "C")
    if mode in ("A", "B"):
        fm = (inputs.get("fixed_modules") or {}).get(site)
        if inputs["site_status"].get(site) == "excluded":
            return []
        return [fm] if fm else []
    status = inputs["site_status"].get(site, "available")
    if status == "excluded":
        return []
    lock = inputs["module_lock"].get(site)
    return [lock] if lock else list(MODULES)


def _max_caps(inputs, modules_by_site):
    """Capacities (clk, grd) given {site: module or None}."""
    caps = {}
    for s in SITES:
        k = modules_by_site.get(s)
        if not k:
            caps[s] = (0.0, 0.0)
        elif s in INTEGRATED:
            mod = inputs["int_modules"][k]
            caps[s] = (mod["clk"], mod["grd"])
        else:
            caps[s] = (0.0, inputs["grd_modules"][k]["grd"])
    return caps


def _largest(inputs, site, allowed):
    if not allowed:
        return None
    return max(allowed, key=lambda k: (_mods(inputs, site)[k]["grd"],
                                       _mods(inputs, site)[k].get("clk", 0)))


# ---------------------------------------------------------------------------
# 3. The MILP
# ---------------------------------------------------------------------------

def build_model(inputs):
    """Build the PuLP MILP. Returns (prob, vars)."""
    p = inputs["params"]
    beta, theta, lam, gamma = p["beta"], p["theta"], p["lam"], p["gamma"]
    d = inputs["demand"]
    dc, dk = inputs["dist_cem"], inputs["dist_clk"]
    cem, clk = lanes(inputs)

    prob = pulp.LpProblem("Rookie", pulp.LpMinimize)
    y = {}  # (site, k) -> binary (both integrated and grinders)
    for s in SITES:
        allowed = allowed_modules(inputs, s)
        for k in allowed:
            y[s, k] = pulp.LpVariable(f"open_{s}_{k}", cat="Binary")
    x = {(s, m): pulp.LpVariable(f"cem_{s}_{m}", lowBound=0) for s, m in cem}
    v = {(i, g): pulp.LpVariable(f"clk_{i}_{g}", lowBound=0) for i, g in clk}

    fixed = pulp.lpSum(annual_fixed(inputs, s, k) * var for (s, k), var in y.items())
    lime = pulp.lpSum(
        gamma * lam * inputs["limestone"][i] * (
            theta * pulp.lpSum(x[s, m] for (s, m) in x if s == i)
            + pulp.lpSum(v[a, g] for (a, g) in v if a == i))
        for i in INTEGRATED)
    cfr = gamma * p["fc"] * pulp.lpSum(dc[s][m] * var for (s, m), var in x.items())
    kfr = gamma * p["fk"] * pulp.lpSum(dk[i][g] * var for (i, g), var in v.items())
    prob += fixed + lime + cfr + kfr

    mode = inputs.get("mode", "C")
    for s in SITES:
        ys = [y[s, k] for k in MODULES if (s, k) in y]
        if ys:
            if mode in ("A", "B") or inputs["site_status"].get(s) == "forced":
                prob += pulp.lpSum(ys) == 1, f"open_{s}"
            else:
                prob += pulp.lpSum(ys) <= 1, f"one_module_{s}"

    for m in MARKETS:
        prob += (pulp.lpSum(x[s, mm] for (s, mm) in x if mm == m) == d[m]), f"demand_{m}"

    for i in INTEGRATED:
        out = pulp.lpSum(x[s, m] for (s, m) in x if s == i)
        ship = pulp.lpSum(v[a, g] for (a, g) in v if a == i)
        grd_cap = pulp.lpSum(beta * inputs["int_modules"][k]["grd"] * y[i, k]
                             for k in MODULES if (i, k) in y)
        clk_cap = pulp.lpSum(beta * inputs["int_modules"][k]["clk"] * y[i, k]
                             for k in MODULES if (i, k) in y)
        prob += out <= grd_cap, f"int_grind_{i}"
        prob += theta * out + ship <= clk_cap, f"int_clinker_{i}"

    for g in GRINDERS:
        out = pulp.lpSum(x[s, m] for (s, m) in x if s == g)
        inflow = pulp.lpSum(v[i, gg] for (i, gg) in v if gg == g)
        cap = pulp.lpSum(beta * inputs["grd_modules"][k]["grd"] * y[g, k]
                         for k in MODULES if (g, k) in y)
        prob += inflow == theta * out, f"grinder_balance_{g}"
        prob += out <= cap, f"grinder_cap_{g}"

    if mode == "A" and inputs.get("fixed_flows"):
        ff = inputs["fixed_flows"]
        fc_flows = {tuple(k.split("|")): val for k, val in ff.get("cement", {}).items()}
        fk_flows = {tuple(k.split("|")): val for k, val in ff.get("clinker", {}).items()}
        for key, var in x.items():
            val = fc_flows.get(key, 0.0)
            var.lowBound = var.upBound = val
        for key, var in v.items():
            val = fk_flows.get(key, 0.0)
            var.lowBound = var.upBound = val

    return prob, {"y": y, "x": x, "v": v}


def _solver(p):
    try:
        s = pulp.HiGHS(msg=False, gapRel=p.get("mip_gap", 1e-4))
        if s.available():
            return s
    except Exception:  # pragma: no cover
        pass
    return pulp.PULP_CBC_CMD(msg=False, gapRel=p.get("mip_gap", 1e-4))  # pragma: no cover


def diagnose_infeasibility(inputs) -> dict:
    """Explain infeasibility in Mt: aggregate capacity check + elastic LP."""
    p = inputs["params"]
    beta, theta = p["beta"], p["theta"]
    D = sum(inputs["demand"].values())
    maxmods = {s: _largest(inputs, s, allowed_modules(inputs, s)) for s in SITES}
    caps = _max_caps(inputs, maxmods)
    grd_name = sum(c[1] for c in caps.values())
    clk_name = sum(c[0] for c in caps.values())
    out = {
        "demand": D,
        "grinding_nameplate": grd_name, "grinding_usable": beta * grd_name,
        "clinker_nameplate": clk_name, "clinker_usable": beta * clk_name,
        "clinker_needed": theta * D,
        "grinding_gap": max(0.0, D - beta * grd_name),
        "clinker_gap": max(0.0, theta * D - beta * clk_name),
        "max_modules": maxmods,
    }
    # Elastic LP at each site's largest allowed module: minimise unserved demand.
    cem, clk = lanes(inputs)
    prob = pulp.LpProblem("shortfall", pulp.LpMinimize)
    x = {(s, m): pulp.LpVariable(f"x_{s}_{m}", lowBound=0) for s, m in cem}
    v = {(i, g): pulp.LpVariable(f"v_{i}_{g}", lowBound=0) for i, g in clk}
    u = {m: pulp.LpVariable(f"u_{m}", lowBound=0) for m in MARKETS}
    prob += pulp.lpSum(u.values())
    for m in MARKETS:
        prob += pulp.lpSum(x[s, mm] for (s, mm) in x if mm == m) + u[m] == inputs["demand"][m]
    for i in INTEGRATED:
        o = pulp.lpSum(x[s, m] for (s, m) in x if s == i)
        prob += o <= beta * caps[i][1]
        prob += theta * o + pulp.lpSum(v[a, g] for (a, g) in v if a == i) <= beta * caps[i][0]
    for g in GRINDERS:
        o = pulp.lpSum(x[s, m] for (s, m) in x if s == g)
        prob += pulp.lpSum(v[i, gg] for (i, gg) in v if gg == g) == theta * o
        prob += o <= beta * caps[g][1]
    prob.solve(_solver(p))
    short = {m: (u[m].value() or 0.0) for m in MARKETS}
    out["min_shortfall"] = sum(short.values())
    out["short_markets"] = {m: q for m, q in short.items() if q > 1e-6}
    unreachable = [m for m in MARKETS
                   if not any(mm == m and caps[s][1] > 0 for (s, mm) in cem)]
    out["unreachable_markets"] = unreachable

    lines = []
    ff = inputs.get("fixed_flows") or {}
    if inputs.get("mode") == "A" and not ff.get("cement"):
        lines.append("The plan's network cannot be routed at all under these inputs, so there are "
                     "no plan flows to evaluate (mode B is infeasible too).")
    elif inputs.get("mode") == "A":
        o = {s: 0.0 for s in SITES}
        sh = {i: 0.0 for i in INTEGRATED}
        for k, q in ff.get("cement", {}).items():
            o[k.split("|")[0]] += q
        for k, q in ff.get("clinker", {}).items():
            sh[k.split("|")[0]] += q
        over = []
        for s in SITES:
            if o[s] > beta * caps[s][1] + 1e-6:
                over.append(f"{s} grinding {o[s]:.2f} Mt vs {beta * caps[s][1]:.2f} usable")
            if s in INTEGRATED and theta * o[s] + sh[s] > beta * caps[s][0] + 1e-6:
                over.append(f"{s} clinker {theta * o[s] + sh[s]:.2f} Mt vs {beta * caps[s][0]:.2f} usable")
        if over:
            lines.append("The fixed plan's flows overload its sites: " + "; ".join(over) + ".")
        got = {m: 0.0 for m in MARKETS}
        for k, q in ff.get("cement", {}).items():
            s, m = k.split("|")
            if (s, m) in cem and caps[s][1] > 0:
                got[m] += q
        miss = {m: inputs["demand"][m] - got[m] for m in MARKETS
                if abs(inputs["demand"][m] - got[m]) > 1e-4}
        if miss:
            lines.append("The fixed plan's flows do not match demand: "
                         + ", ".join(f"{m} {q:.2f} Mt short" if q > 0 else f"{m} {-q:.2f} Mt over"
                                     for m, q in miss.items())
                         + f" (net {sum(miss.values()):+.2f} Mt unserved).")
    if out["grinding_gap"] > 1e-6:
        lines.append(
            f"Usable grinding {beta * grd_name:.2f} Mt (β={beta:.2f} × {grd_name:.1f} MTPA nameplate) "
            f"against {D:.2f} Mt demand — a {out['grinding_gap']:.2f} Mt gap.")
    if out["clinker_gap"] > 1e-6:
        lines.append(
            f"Usable clinker {beta * clk_name:.2f} Mt against {theta * D:.2f} Mt needed "
            f"(θ={theta} × demand) — a {out['clinker_gap']:.2f} Mt gap.")
    if unreachable:
        lines.append("No open or openable source within the cement lane cap for: "
                     + ", ".join(unreachable) + ".")
    if out["min_shortfall"] > 1e-6:
        mk = ", ".join(f"{m} {q:.2f} Mt" for m, q in out["short_markets"].items())
        where = ("With the plan's modules" if inputs.get("mode") in ("A", "B")
                 else "Even with every permitted site at its largest module")
        lines.append(
            f"{where}, at least "
            f"{out['min_shortfall']:.2f} Mt cannot be delivered within the lane caps and capacity "
            f"limits. Short markets: {mk}.")
    if not lines:
        lines.append("Capacity is sufficient in aggregate; the infeasibility comes from fixed "
                     "flows or module locks that do not balance demand.")
    out["explanation"] = lines
    return out


def solve(inputs) -> dict:
    """Solve the model. Pure function: inputs dict in, results dict out."""
    t0 = time.perf_counter()
    p = inputs["params"]
    beta, theta, lam, gamma = p["beta"], p["theta"], p["lam"], p["gamma"]
    prob, var = build_model(inputs)
    prob.solve(_solver(p))
    wall = time.perf_counter() - t0
    status = pulp.LpStatus[prob.status]
    res = {"status": status, "wall_time": wall, "mode": inputs.get("mode", "C"),
           "lanes": lane_summary(inputs)}
    gap = None
    sm = getattr(prob, "solverModel", None)
    if sm is not None:
        try:
            gap = float(sm.getInfo().mip_gap)
            if not math.isfinite(gap) or gap > 1e10:
                gap = None
        except Exception:
            gap = None
    res["mip_gap"] = gap if gap is not None else 0.0

    if status != "Optimal":
        res["feasible"] = False
        res["objective"] = None
        res["diagnosis"] = diagnose_infeasibility(inputs)
        return res
    res["feasible"] = True

    val = lambda v_: max(0.0, v_.value() or 0.0)
    modules = {s: None for s in SITES}
    for (s, k), v_ in var["y"].items():
        if (v_.value() or 0) > 0.5:
            modules[s] = k
    x = {k: val(v_) for k, v_ in var["x"].items()}
    v = {k: val(v_) for k, v_ in var["v"].items()}
    res.update(evaluate(inputs, modules, x, v))
    res["objective_solver"] = pulp.value(prob.objective)
    res["wall_time"] = time.perf_counter() - t0
    return res


def evaluate(inputs, modules, x, v) -> dict:
    """Cost, sites, flows, KPIs and validation for a given network and flow set."""
    p = inputs["params"]
    beta, theta, lam, gamma = p["beta"], p["theta"], p["lam"], p["gamma"]
    c = crf(p["r"], p["n"])
    dc, dk = inputs["dist_cem"], inputs["dist_clk"]
    eps = 1e-6

    out_of = {s: sum(q for (a, _), q in x.items() if a == s) for s in SITES}
    ship_of = {i: sum(q for (a, _), q in v.items() if a == i) for i in INTEGRATED}
    clk_in = {g: sum(q for (_, b), q in v.items() if b == g) for g in GRINDERS}

    sites = []
    capex_ann = opex = capex_tot = 0.0
    for s in SITES:
        k = modules.get(s)
        if not k:
            continue
        mod = _mods(inputs, s)[k]
        capex_ann += mod["capex"] * c
        opex += mod["opex"]
        capex_tot += mod["capex"]
        if s in INTEGRATED:
            clk_made = theta * out_of[s] + ship_of[s]
            sites.append({
                "site": s, "name": SITE_INFO[s][0], "type": "Integrated", "module": k,
                "clinker_cap": mod["clk"], "grinding_cap": mod["grd"],
                "cement_out": out_of[s], "clinker_made": clk_made, "clinker_shipped": ship_of[s],
                "util_clinker": clk_made / mod["clk"] * 100,
                "util_grinding": out_of[s] / mod["grd"] * 100,
                "capex": mod["capex"], "capex_annual": mod["capex"] * c, "opex": mod["opex"],
            })
        else:
            sites.append({
                "site": s, "name": SITE_INFO[s][0], "type": "Grinding", "module": k,
                "clinker_cap": None, "grinding_cap": mod["grd"],
                "cement_out": out_of[s], "clinker_made": None, "clinker_in": clk_in[s],
                "util_clinker": None, "util_grinding": out_of[s] / mod["grd"] * 100,
                "capex": mod["capex"], "capex_annual": mod["capex"] * c, "opex": mod["opex"],
            })

    limestone = sum(gamma * lam * inputs["limestone"][i] * (theta * out_of[i] + ship_of[i])
                    for i in INTEGRATED)
    cem_rows = []
    for (s, m), q in sorted(x.items(), key=lambda kv: (SITES.index(kv[0][0]), MARKETS.index(kv[0][1]))):
        if q > eps:
            cem_rows.append({"source": s, "type": "Integrated" if s in INTEGRATED else "Grinding",
                             "market": m, "cluster": MARKET_INFO[m][0], "distance": dc[s][m],
                             "Mt": q, "cost": gamma * p["fc"] * dc[s][m] * q})
    clk_rows = []
    for (i, g), q in sorted(v.items()):
        if q > eps:
            clk_rows.append({"plant": i, "grinder": g, "distance": dk[i][g], "Mt": q,
                             "cost": gamma * p["fk"] * dk[i][g] * q})
    cem_fr = sum(r["cost"] for r in cem_rows)
    clk_fr = sum(r["cost"] for r in clk_rows)
    total = capex_ann + opex + limestone + cem_fr + clk_fr
    D = sum(inputs["demand"].values())
    cem_mt = sum(r["Mt"] for r in cem_rows)
    clk_mt = sum(r["Mt"] for r in clk_rows)

    costs = {"Annualised capex": capex_ann, "Fixed opex": opex, "Limestone": limestone,
             "Cement freight": cem_fr, "Clinker freight": clk_fr}
    kpis = {
        "clinker_nameplate": sum(s_["clinker_cap"] or 0 for s_ in sites),
        "grinding_nameplate": sum(s_["grinding_cap"] for s_ in sites),
        "cement_lead_km": sum(r["distance"] * r["Mt"] for r in cem_rows) / cem_mt if cem_mt else 0,
        "clinker_lead_km": sum(r["distance"] * r["Mt"] for r in clk_rows) / clk_mt if clk_mt else 0,
        "clinker_moved": clk_mt,
        "max_util": max([s_["util_grinding"] for s_ in sites]
                        + [s_["util_clinker"] for s_ in sites if s_["util_clinker"] is not None],
                        default=0),
        "unit_cost": total * 10 / D if D else 0,  # ₹cr / Mt × 10 = ₹/t
        "capex_total": capex_tot,
        "demand": D,
        "n_sites": len(sites),
    }

    # ----- validation panel -----
    checks = []
    served = {m: sum(q for (_, mm), q in x.items() if mm == m) for m in MARKETS}
    bad = [m for m in MARKETS if abs(served[m] - inputs["demand"][m]) > 1e-4]
    checks.append(("Every market served", not bad,
                   "All 12 markets exactly at target" if not bad else
                   "Mismatch: " + ", ".join(f"{m} {served[m]:.3f}/{inputs['demand'][m]:.3f}" for m in bad)))
    bad = [g for g in GRINDERS if abs(clk_in[g] - theta * out_of[g]) > 1e-4]
    checks.append((f"Grinder clinker in = {theta} × cement out", not bad,
                   "Balanced at every grinder" if not bad else "Unbalanced: " + ", ".join(bad)))
    over = []
    for s_ in sites:
        if s_["util_grinding"] > beta * 100 + 1e-3:
            over.append(f"{s_['site']} grinding {s_['util_grinding']:.1f}%")
        if s_["util_clinker"] is not None and s_["util_clinker"] > beta * 100 + 1e-3:
            over.append(f"{s_['site']} clinker {s_['util_clinker']:.1f}%")
    closed_flow = [s for s in SITES if not modules.get(s) and out_of.get(s, 0) + ship_of.get(s, 0) > eps]
    checks.append((f"No line above β = {beta:.0%} of nameplate", not over and not closed_flow,
                   "All lines within the cap" if not over and not closed_flow else
                   "; ".join(over + [f"{s} ships but is closed" for s in closed_flow])))
    long_c = [f"{r['source']}→{r['market']} {r['distance']} km" for r in cem_rows if r["distance"] > p["Lcem"]]
    long_k = [f"{r['plant']}→{r['grinder']} {r['distance']} km" for r in clk_rows if r["distance"] > p["Lclk"]]
    checks.append(("No lane over its cap", not long_c and not long_k,
                   f"Cement ≤ {p['Lcem']:.0f} km, clinker ≤ {p['Lclk']:.0f} km" if not long_c and not long_k
                   else "; ".join(long_c + long_k)))
    checks.append(("Clinker moves plant → grinder only", all(r["plant"] in INTEGRATED and r["grinder"] in GRINDERS for r in clk_rows),
                   "No plant→plant or grinder→grinder clinker"))

    return {
        "objective": total, "costs": costs, "modules": modules, "sites": sites,
        "cement_flows": cem_rows, "clinker_flows": clk_rows, "kpis": kpis,
        "validation": checks, "x": {f"{s}|{m}": q for (s, m), q in x.items() if q > eps},
        "v": {f"{i}|{g}": q for (i, g), q in v.items() if q > eps},
    }


def add_reconciliation_check(res):
    """Append the 'objective reconciles' check (components vs solver objective)."""
    if not res.get("feasible"):
        return res
    comp = sum(res["costs"].values())
    ok = abs(comp - res["objective_solver"]) < 0.01
    res["validation"].append(("Objective reconciles", ok,
                              f"Components sum {comp:,.2f} vs solver {res['objective_solver']:,.2f}"))
    return res


# ---------------------------------------------------------------------------
# 4. Scenario-level helpers (used by the app and the tests)
# ---------------------------------------------------------------------------

def with_mode(inputs, mode, fixed_modules=None, fixed_flows=None):
    out = copy.deepcopy(inputs)
    out["mode"] = mode
    out["fixed_modules"] = fixed_modules
    out["fixed_flows"] = fixed_flows
    return out


def run(inputs):
    """solve() + reconciliation check."""
    return add_reconciliation_check(solve(inputs))


def reroute(inputs, modules, drop=()):
    """Mode B: modules fixed (minus any dropped/excluded sites), flows re-optimised."""
    fm = {s: (None if s in drop else modules.get(s)) for s in SITES}
    return run(with_mode(inputs, "B", fixed_modules=fm))


def share_flows(inputs, reference):
    """Fixed-plan rule 1 — frozen sourcing shares. Each market keeps the source split of a
    reference solution, scaled to current demand; each grinder keeps its clinker-source
    split, scaled to its new output. `reference` is a solve() result."""
    theta = inputs["params"]["theta"]
    ref_d = {m: 0.0 for m in MARKETS}
    for k, q in reference["x"].items():
        ref_d[k.split("|")[1]] += q
    x = {}
    for k, q in reference["x"].items():
        s, m = k.split("|")
        if ref_d[m] > 0:
            x[s, m] = q / ref_d[m] * inputs["demand"][m]
    out = {g: sum(q for (s, _), q in x.items() if s == g) for g in GRINDERS}
    ref_in = {g: 0.0 for g in GRINDERS}
    for k, q in reference["v"].items():
        ref_in[k.split("|")[1]] += q
    v = {}
    for k, q in reference["v"].items():
        i, g = k.split("|")
        if ref_in[g] > 0:
            v[i, g] = q / ref_in[g] * theta * out[g]
    return {"cement": {f"{s}|{m}": q for (s, m), q in x.items()},
            "clinker": {f"{i}|{g}": q for (i, g), q in v.items()}}


def tkm_flows(inputs, modules):
    """Fixed-plan rule 2 — minimum tonne-km. Routes the plan's network to minimise total
    t-km moved (cement + clinker), blind to freight rates and limestone cost: the plan a
    distance-driven logistics desk would draw. Feasible whenever re-routing (mode B) is."""
    blind = copy.deepcopy(inputs)
    blind["params"].update(fc=1.0, fk=1.0, lam=0.0)
    r = solve(with_mode(blind, "B", fixed_modules=modules))
    if not r.get("feasible"):
        return {"cement": {}, "clinker": {}}
    return {"cement": dict(r["x"]), "clinker": dict(r["v"])}


PLAN_RULES = ("Frozen base-case sourcing shares", "Minimum tonne-km routing")


def plan_flows(inputs, modules, rule, reference=None):
    if rule == PLAN_RULES[0]:
        return share_flows(inputs, reference or solve(default_inputs()))
    return tkm_flows(inputs, modules)


def mode_gaps(inputs, plan_modules, rule=PLAN_RULES[0], reference=None):
    """Run A (fixed plan), B (re-route) and C (redesign) and report the gaps."""
    flows = plan_flows(inputs, plan_modules, rule, reference)
    a = run(with_mode(inputs, "A", fixed_modules=plan_modules, fixed_flows=flows))
    b = run(with_mode(inputs, "B", fixed_modules=plan_modules))
    c = run(with_mode(inputs, "C"))
    obj = lambda r: r["objective"] if r.get("feasible") else None  # noqa: E731
    A, B, C = obj(a), obj(b), obj(c)
    gaps = {
        "allocation_improvement": A - B if A is not None and B is not None else None,
        "footprint_regret": B - C if B is not None and C is not None else None,
        "status_quo_regret": A - C if A is not None and C is not None else None,
    }
    return {"A": a, "B": b, "C": c, "gaps": gaps}


# ---------------------------------------------------------------------------
# 5. Near-optimal enumeration
# ---------------------------------------------------------------------------

class _FastLP:
    """Flow-only LP with capacity rows whose bounds change per network (highspy)."""

    def __init__(self, inputs):
        p = inputs["params"]
        self.inputs = inputs
        beta, theta, lam, gamma = p["beta"], p["theta"], p["lam"], p["gamma"]
        self.beta, self.theta = beta, theta
        cem, clk = lanes(inputs)
        self.cem, self.clk = cem, clk
        dc, dk = inputs["dist_cem"], inputs["dist_clk"]
        cost = []
        for s, m in cem:
            c = gamma * p["fc"] * dc[s][m]
            if s in INTEGRATED:
                c += gamma * lam * inputs["limestone"][s] * theta
            cost.append(c)
        for i, g in clk:
            cost.append(gamma * p["fk"] * dk[i][g] + gamma * lam * inputs["limestone"][i])
        nx = len(cem)
        self.h = h = highspy.Highs()
        h.setOptionValue("output_flag", False)
        inf = highspy.kHighsInf
        for c in cost:
            h.addVar(0, inf)
        h.changeColsCost(len(cost), list(range(len(cost))), cost)
        self.rows = {}

        def add_row(key, lo, hi, idx, vals):
            h.addRow(lo, hi, len(idx), idx, vals)
            self.rows[key] = h.getNumRow() - 1

        for m in MARKETS:
            idx = [j for j, (s, mm) in enumerate(cem) if mm == m]
            d = inputs["demand"][m]
            add_row(("dem", m), d, d, idx, [1.0] * len(idx))
        for i in INTEGRATED:
            xi = [j for j, (s, _) in enumerate(cem) if s == i]
            vi = [nx + j for j, (a, _) in enumerate(clk) if a == i]
            add_row(("grd", i), -inf, 0, xi, [1.0] * len(xi))
            add_row(("clk", i), -inf, 0, xi + vi, [theta] * len(xi) + [1.0] * len(vi))
        for g in GRINDERS:
            xg = [j for j, (s, _) in enumerate(cem) if s == g]
            vg = [nx + j for j, (_, b) in enumerate(clk) if b == g]
            add_row(("bal", g), 0, 0, vg + xg, [1.0] * len(vg) + [-theta] * len(xg))
            add_row(("grd", g), -inf, 0, xg, [1.0] * len(xg))

    def solve(self, caps):
        """caps: {site: (clk, grd) nameplate}. Returns variable cost or None."""
        h, b = self.h, self.beta
        inf = highspy.kHighsInf
        for s in SITES:
            h.changeRowBounds(self.rows[("grd", s)], -inf, b * caps[s][1])
            if s in INTEGRATED:
                h.changeRowBounds(self.rows[("clk", s)], -inf, b * caps[s][0])
        h.run()
        if h.getModelStatus() != highspy.HighsModelStatus.kOptimal:
            return None
        return h.getInfo().objective_function_value


def enumerate_networks(inputs, optimum=None, band=0.05, progress=None) -> dict:
    """Enumerate every module combination whose optimal cost is within `band` of the
    optimum. Prunes on (a) capacity, (b) fixed cost + a site-set lower bound on variable
    cost, before solving each LP."""
    if highspy is None:
        raise RuntimeError("Near-optimal enumeration needs highspy (pip install highspy).")
    t0 = time.perf_counter()
    base = with_mode(inputs, "C")
    if optimum is None:
        optimum = run(base)
    if not optimum.get("feasible"):
        return {"feasible": False}
    opt = optimum["objective"]
    limit = opt * (1 + band) + 1e-6
    p = inputs["params"]
    beta, theta = p["beta"], p["theta"]
    D = sum(inputs["demand"].values())
    lp = _FastLP(base)

    opts = {s: allowed_modules(base, s) for s in SITES}
    forced = [s for s in SITES if base["site_status"].get(s) == "forced"]
    candidates = [s for s in SITES if opts[s]]
    fixed = {(s, k): annual_fixed(base, s, k) for s in SITES for k in opts[s]}

    networks = []
    n_lp = n_sets = n_pruned_cap = n_pruned_fixed = 0
    subsets = []
    for r_ in range(len(candidates) + 1):
        for comb in itertools.combinations(candidates, r_):
            if all(f in comb for f in forced):
                subsets.append(comb)
    for si, S in enumerate(subsets):
        if progress:
            progress(si / len(subsets))
        # Lower bound on variable cost for any sizing of this site set:
        # every site at its largest allowed module.
        big = {s: _largest(base, s, opts[s]) if s in S else None for s in SITES}
        caps_big = _max_caps(base, big)
        if beta * sum(c[1] for c in caps_big.values()) < D - 1e-9:
            continue
        min_fixed = sum(min(fixed[s, k] for k in opts[s]) for s in S)
        if min_fixed > limit:
            continue
        lb = lp.solve(caps_big)
        n_lp += 1
        n_sets += 1
        if lb is None:
            continue
        if min_fixed + lb > limit:
            continue
        for combo in itertools.product(*[opts[s] for s in S]):
            mods = dict(zip(S, combo))
            fx = sum(fixed[s, k] for s, k in mods.items())
            if fx + lb > limit:
                n_pruned_fixed += 1
                continue
            caps = _max_caps(base, mods)
            if (beta * sum(c[1] for c in caps.values()) < D - 1e-9
                    or beta * sum(c[0] for c in caps.values()) < theta * D - 1e-9):
                n_pruned_cap += 1
                continue
            var = lp.solve(caps)
            n_lp += 1
            if var is None:
                continue
            tot = fx + var
            if tot <= limit:
                networks.append({"modules": mods, "sites": tuple(S), "objective": tot,
                                 "premium": tot / opt - 1})
    networks.sort(key=lambda n_: n_["objective"])
    opt_set = tuple(s for s in SITES if optimum["modules"].get(s))
    opt_mods = {s: optimum["modules"][s] for s in opt_set}
    for n_ in networks:
        n_["is_optimum"] = n_["modules"] == opt_mods
    # Bands count ALTERNATIVE networks, i.e. excluding the optimum itself.
    bands = []
    for b_ in (0.005, 0.01, 0.02, 0.05):
        if b_ > band + 1e-12:
            break
        inb = [n_ for n_ in networks
               if n_["objective"] <= opt * (1 + b_) + 1e-6 and not n_["is_optimum"]]
        same = [n_ for n_ in inb if n_["sites"] == opt_set]
        alt = sorted({n_["sites"] for n_ in inb if n_["sites"] != opt_set})
        bands.append({"band": b_, "networks": len(inb), "same_sites": len(same),
                      "alt_footprints": len(alt)})
    footprints = {}
    for n_ in networks:
        if n_["sites"] != opt_set and n_["sites"] not in footprints:
            footprints[n_["sites"]] = n_
    alt_fp = []
    for S, n_ in sorted(footprints.items(), key=lambda kv: kv[1]["objective"]):
        alt_fp.append({"sites": S, "added": [s for s in S if s not in opt_set],
                       "removed": [s for s in opt_set if s not in S],
                       "objective": n_["objective"], "premium": n_["premium"],
                       "modules": n_["modules"]})
    return {"feasible": True, "optimum": opt, "optimum_sites": opt_set,
            "networks": networks, "bands": bands, "alt_footprints": alt_fp,
            "lps_solved": n_lp, "site_sets_checked": n_sets,
            "pruned_fixed": n_pruned_fixed, "pruned_capacity": n_pruned_cap,
            "wall_time": time.perf_counter() - t0}


def fmt_network(modules) -> str:
    return ", ".join(f"{s}-{modules[s]}" for s in SITES if modules.get(s))


if __name__ == "__main__":
    r = run(default_inputs())
    print(f"Status: {r['status']}  wall {r['wall_time']:.2f}s  gap {r['mip_gap']:.2e}")
    print(f"Objective: ₹{r['objective']:,.2f} crore/yr")
    print("Open sites:", fmt_network(r["modules"]))
    for k, v in r["costs"].items():
        print(f"  {k:<18}{v:>10,.2f}")
    for f in r["clinker_flows"]:
        print(f"  {f['plant']}→{f['grinder']} {f['Mt']:.4f} Mt")
    for s in r["sites"]:
        uc = f"{s['util_clinker']:.1f}" if s["util_clinker"] is not None else "  - "
        print(f"  {s['site']}-{s['module']}  clk {uc}  grd {s['util_grinding']:.1f}")
    print("KPIs:", {k: round(v, 2) for k, v in r["kpis"].items()})
    for name, ok, note in r["validation"]:
        print(("  PASS " if ok else "  FAIL ") + name + " — " + note)

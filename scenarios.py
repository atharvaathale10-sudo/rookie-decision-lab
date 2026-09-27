"""Scenario presets and JSON save/load. No Streamlit import."""
from __future__ import annotations

import copy
import io
import json

import pandas as pd

import model as M

PRESETS = {
    "Base": "Client target at 5% share, base freight, all ten candidates available.",
    "A — demand mix shift": "Same 33.78 Mt, redistributed towards the north and east.",
    "B — freight shock (3.75 / 1.85)": "Cement freight ₹3.75/t-km, clinker ₹1.85/t-km.",
    "C — Chittorgarh unavailable": "I1 excluded (land / limestone lease lost).",
    "600 km service standard": "Cement lane cap tightened from 800 to 600 km.",
}


def preset(name: str) -> dict:
    """Full input dict (steps 1-3) for a named preset."""
    if name not in PRESETS:
        raise KeyError(f"Unknown preset {name!r}")
    inp = M.default_inputs()
    if name == "A — demand mix shift":
        inp["demand"] = dict(M.SCENARIO_A_DEMAND)
    elif name == "B — freight shock (3.75 / 1.85)":
        inp["params"]["fc"] = 3.75
        inp["params"]["fk"] = 1.85
    elif name == "C — Chittorgarh unavailable":
        inp["site_status"]["I1"] = "excluded"
    elif name == "600 km service standard":
        inp["params"]["Lcem"] = 600
    return inp


def assumption_diff(inputs) -> list:
    """List of (label, base, current) for every input that differs from the base case."""
    base = M.default_inputs()
    diffs = []
    for k, v in inputs["params"].items():
        if abs(v - base["params"][k]) > 1e-12:
            diffs.append((k, base["params"][k], v))
    for m in M.MARKETS:
        if abs(inputs["demand"][m] - base["demand"][m]) > 1e-9:
            diffs.append((f"demand {m}", base["demand"][m], inputs["demand"][m]))
    for i in M.INTEGRATED:
        if inputs["limestone"][i] != base["limestone"][i]:
            diffs.append((f"limestone {i}", base["limestone"][i], inputs["limestone"][i]))
    for grp in ("int_modules", "grd_modules"):
        for k in M.MODULES:
            for f, v in inputs[grp][k].items():
                if v != base[grp][k][f]:
                    diffs.append((f"{grp} {k} {f}", base[grp][k][f], v))
    for s in M.SITES:
        if inputs["site_status"][s] != "available":
            diffs.append((f"site {s}", "available", inputs["site_status"][s]))
        if inputs["module_lock"].get(s):
            diffs.append((f"lock {s}", None, inputs["module_lock"][s]))
    return diffs


INPUT_KEYS = ("demand", "limestone", "int_modules", "grd_modules", "params",
              "site_status", "module_lock")


def to_json(name: str, inputs: dict) -> str:
    return json.dumps({"name": name, "rookie_scenario": 1,
                       "inputs": {k: inputs[k] for k in INPUT_KEYS}}, indent=2)


def from_json(text: str) -> tuple[str, dict]:
    data = json.loads(text)
    if "inputs" not in data:
        raise ValueError("Not a Rookie scenario file (no 'inputs' key).")
    inp = M.default_inputs()
    for k in INPUT_KEYS:
        if k in data["inputs"]:
            if isinstance(inp[k], dict) and isinstance(data["inputs"][k], dict):
                inp[k].update(copy.deepcopy(data["inputs"][k]))
            else:
                inp[k] = data["inputs"][k]
    return data.get("name", "Imported"), inp


def results_to_excel(res: dict, inputs: dict) -> bytes:
    """Open sites, flows, cost breakdown, KPIs, validation, assumptions → .xlsx bytes."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        if res.get("feasible"):
            pd.DataFrame(res["sites"]).to_excel(xw, sheet_name="Open sites", index=False)
            pd.DataFrame(res["cement_flows"]).to_excel(xw, sheet_name="Cement flows", index=False)
            pd.DataFrame(res["clinker_flows"]).to_excel(xw, sheet_name="Clinker flows", index=False)
            cb = [{"Component": k, "₹ crore/yr": v} for k, v in res["costs"].items()]
            cb.append({"Component": "Total", "₹ crore/yr": res["objective"]})
            pd.DataFrame(cb).to_excel(xw, sheet_name="Cost breakdown", index=False)
            pd.DataFrame([{"KPI": k, "Value": v} for k, v in res["kpis"].items()]).to_excel(xw, sheet_name="KPIs", index=False)
            pd.DataFrame([{"Check": n, "Pass": ok, "Detail": d} for n, ok, d in res["validation"]]
                         ).to_excel(xw, sheet_name="Validation", index=False)
        else:
            pd.DataFrame({"Diagnosis": res["diagnosis"]["explanation"]}).to_excel(xw, sheet_name="Infeasible", index=False)
        rows = [{"Parameter": k, "Value": v} for k, v in inputs["params"].items()]
        rows.append({"Parameter": "CRF", "Value": M.crf(inputs["params"]["r"], inputs["params"]["n"])})
        rows += [{"Parameter": f"demand {m}", "Value": inputs["demand"][m]} for m in M.MARKETS]
        rows += [{"Parameter": f"site {s}", "Value": inputs["site_status"][s]} for s in M.SITES]
        pd.DataFrame(rows).to_excel(xw, sheet_name="Assumptions", index=False)
    return buf.getvalue()

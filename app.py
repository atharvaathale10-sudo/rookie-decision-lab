"""The Rookie — Streamlit Decision Lab. Interface only; all model logic is in model.py."""
from __future__ import annotations

import copy
import hashlib
import json

import pandas as pd
import streamlit as st

import model as M
import scenarios as S
import viz as V

st.set_page_config(page_title="The Rookie — Decision Lab", page_icon="🏭", layout="wide")
# Metric values default to ~2.25rem and truncate with "…" in narrow columns; keep them
# readable and let them wrap instead of clipping.
st.markdown("""<style>
[data-testid="stMetricValue"] { font-size: clamp(1.05rem, 1.55vw, 1.6rem); line-height: 1.25; }
[data-testid="stMetricValue"] p, [data-testid="stMetricValue"] div {
  white-space: normal !important; overflow: visible !important; text-overflow: clip !important;
}
[data-testid="stMetricLabel"] p { white-space: normal !important; }
</style>""", unsafe_allow_html=True)

BENCHMARK = 7792.26
STEPS = {1: "Frame the demand", 2: "Choose candidate sites", 3: "Set rules and rates",
         4: "Solve", 5: "Read the network", 6: "Scenarios & recommendation"}
STATUS_LABEL = {"available": "Available", "forced": "Forced open", "excluded": "Excluded"}
LABEL_STATUS = {v: k for k, v in STATUS_LABEL.items()}

ss = st.session_state


# ---------------------------------------------------------------------------
# Cached solver wrappers (keyed on the full input dict)
# ---------------------------------------------------------------------------

def _key(inputs) -> str:
    return json.dumps(inputs, sort_keys=True)


@st.cache_data(show_spinner=False, max_entries=1000)
def _cached_run(key: str) -> dict:
    return M.run(json.loads(key))


def run(inputs) -> dict:
    return _cached_run(_key(inputs))


def run_mode(inputs, mode, modules=None, flows=None):
    return run(M.with_mode(inputs, mode, fixed_modules=modules, fixed_flows=flows))


def reroute(inputs, modules, drop=()):
    fm = {s: (None if s in drop else modules.get(s)) for s in M.SITES}
    return run_mode(inputs, "B", fm)


@st.cache_data(show_spinner=False, max_entries=20)
def _cached_enum(key: str, band: float) -> dict:
    inp = json.loads(key)
    return M.enumerate_networks(inp, optimum=M.run(M.with_mode(inp, "C")), band=band)


def enumerate_networks(inputs, band):
    return _cached_enum(_key(M.with_mode(inputs, "C")), band)



# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

def _init():
    if "inputs" in ss:
        return
    ss.inputs = M.default_inputs()
    ss.share = M.BASE_SHARE
    ss.mix = "Base"
    ss.ver = 0
    ss.step = 1
    ss.done = {1: False, 2: False, 3: False}
    ss.visited = set()
    ss.result = None
    ss.result_key = None
    ss.result_inputs = None
    ss.gaps = None
    ss.saved = {}
    ss.mode = "C"
    ss.plan_modules = dict(run(M.default_inputs())["modules"])
    ss.plan_flows_src = M.PLAN_RULES[0]
    ss.reco = None


_init()


def input_key() -> str:
    core = {k: ss.inputs[k] for k in S.INPUT_KEYS}
    plan = {"mode": ss.mode}
    if ss.mode in ("A", "B"):
        plan["modules"] = ss.plan_modules
    if ss.mode == "A":
        plan["flows"] = ss.plan_flows_src
    return hashlib.md5(json.dumps([core, plan], sort_keys=True).encode()).hexdigest()


def is_stale() -> bool:
    return ss.result is not None and ss.result_key != input_key()


def bump():
    ss.ver += 1


def _getp(path):
    d = ss.inputs
    for p in path:
        d = d[p]
    return d


def _setp(path, val):
    d = ss.inputs
    for p in path[:-1]:
        d = d[p]
    d[path[-1]] = val


def _cb_set(path, key, cast):
    _setp(path, cast(ss[key]))
    bump()


def num(label, path, where, integer=False, **kw):
    """Number input bound to ss.inputs[path]. Changing it re-keys every widget so the
    same value shown in two places (Step 3 and the Assumptions panel) never diverges."""
    key = f"{where}:{'/'.join(map(str, path))}:{ss.ver}"
    cur = _getp(path)
    val = int(cur) if integer else float(cur)
    return st.number_input(label, value=val, key=key, on_change=_cb_set,
                           args=(path, key, int if integer else float), **kw)


def apply_inputs(inp, share=M.BASE_SHARE, mix="Base"):
    ss.inputs = copy.deepcopy(inp)
    ss.share = share
    ss.mix = mix
    bump()


def fmt_cr(v):
    return "—" if v is None else f"₹{v:,.2f} cr"


def mods_str(mods):
    return M.fmt_network(mods) if mods else "—"


# ---------------------------------------------------------------------------
# Sidebar — step rail, benchmark, scenario save/load
# ---------------------------------------------------------------------------

def step_done(n):
    if n <= 3:
        return ss.done[n]
    if n == 4:
        return ss.result is not None and not is_stale()
    return n in ss.visited and ss.result is not None and not is_stale()


def step_unlocked(n):
    if n <= 1:
        return True
    if n <= 4:
        return all(ss.done[k] for k in range(1, n))
    return all(ss.done[k] for k in (1, 2, 3)) and ss.result is not None


def goto(n):
    ss.step = n


with st.sidebar:
    st.markdown("## 🏭 The Rookie")
    st.caption("FY2030 India cement network — decision lab")
    for n, name in STEPS.items():
        if not step_unlocked(n):
            icon = "🔒"
        elif n >= 4 and is_stale():
            icon = "⚠️"
        elif step_done(n):
            icon = "✅"
        else:
            icon = "⬜"
        st.button(f"{icon}  Step {n} — {name}", key=f"rail{n}", on_click=goto, args=(n,),
                  disabled=not step_unlocked(n), width="stretch",
                  type="primary" if ss.step == n else "secondary")
    if is_stale():
        st.warning("Inputs changed since the last solve — **re-solve needed** (Step 4).")

    st.divider()
    b = run(M.default_inputs())
    ok = abs(b["objective"] - BENCHMARK) < 0.01
    (st.success if ok else st.error)(
        f"{'✓' if ok else '✗'} Benchmark: base case solves to **₹{b['objective']:,.2f} cr** "
        f"(expected ₹{BENCHMARK:,.2f} cr)")

    st.divider()
    st.markdown("**Scenarios**")
    name = st.text_input("Name", value="My scenario", key="save_name")
    if st.button("💾 Save current inputs (steps 1–3)", width="stretch"):
        ss.saved[name] = copy.deepcopy({k: ss.inputs[k] for k in S.INPUT_KEYS})
        st.toast(f"Saved “{name}”")
    if ss.saved:
        pick = st.selectbox("Saved scenarios", list(ss.saved), key="load_pick")
        c1, c2 = st.columns(2)
        if c1.button("Load", width="stretch"):
            _, inp = S.from_json(S.to_json(pick, ss.saved[pick]))
            apply_inputs(inp, share=ss.share, mix="Custom")
            st.rerun()
        c2.download_button("Export JSON", S.to_json(pick, ss.saved[pick]),
                           file_name=f"{pick}.json", mime="application/json",
                           width="stretch")
    st.download_button("⬇️ Export current inputs as JSON", S.to_json("Current", ss.inputs),
                       file_name="rookie_scenario.json", mime="application/json",
                       width="stretch")
    up = st.file_uploader("Import scenario JSON", type="json", key=f"up{ss.ver}")
    if up is not None:
        try:
            nm, inp = S.from_json(up.getvalue().decode("utf-8"))
            ss.saved[nm] = {k: inp[k] for k in S.INPUT_KEYS}
            apply_inputs(inp, mix="Custom")
            st.toast(f"Imported and loaded “{nm}”")
            st.rerun()
        except Exception as ex:  # noqa: BLE001
            st.error(f"Could not import: {ex}")


# ---------------------------------------------------------------------------
# Assumptions panel (visible on every step)
# ---------------------------------------------------------------------------

def assumptions_panel():
    diffs = S.assumption_diff(ss.inputs)
    badge = f" · 🟠 {len(diffs)} differ from base" if diffs else " · 🟢 all at base"
    p = ss.inputs["params"]
    with st.expander(f"⚙️ Assumptions in force{badge}", expanded=False):
        top = st.columns([3, 1])
        top[0].caption("Every value the solver reads comes from here — nothing is hardcoded in "
                       "the solver. Edit inline to override.")
        if top[1].button("↺ Reset to base case", width="stretch"):
            apply_inputs(M.default_inputs())
            st.rerun()
        if diffs:
            top[0].markdown("**Differs from base:** " + " · ".join(
                f"`{k}` {b} → {v}" for k, b, v in diffs[:12]) + (" …" if len(diffs) > 12 else ""))

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown("**Financial** · *course case*")
            num("Hurdle rate r", ("params", "r"), "as", format="%.4f", step=0.005, min_value=0.0)
            num("Asset life n (yrs)", ("params", "n"), "as", integer=True, min_value=1, step=1)
            st.metric("CRF (derived)", f"{M.crf(p['r'], p['n']):.6f}")
        with c2:
            st.markdown("**Technical** · *case exhibit*")
            num("Clinker factor θ (t/t cement)", ("params", "theta"), "as", format="%.3f", step=0.01)
            num("Limestone factor λ (t/t clinker)", ("params", "lam"), "as", format="%.2f", step=0.05)
            num("Max utilisation β", ("params", "beta"), "as", format="%.2f", step=0.01,
                min_value=0.1, max_value=1.0)
        with c3:
            st.markdown("**Freight** · *case exhibit*")
            num("Cement freight fc (₹/t-km)", ("params", "fc"), "as", format="%.2f", step=0.05)
            num("Clinker freight fk (₹/t-km)", ("params", "fk"), "as", format="%.2f", step=0.05)
            num("Cost conversion γ (₹cr per Mt·₹/t)", ("params", "gamma"), "as", format="%.2f", step=0.1)
        with c4:
            st.markdown("**Policy** · *service standard*")
            num("Max cement lane (km)", ("params", "Lcem"), "as", integer=True, step=50, min_value=0)
            num("Max clinker lane (km)", ("params", "Lclk"), "as", integer=True, step=50, min_value=0)
            num("Relative MIP gap", ("params", "mip_gap"), "as", format="%.6f", step=0.00005,
                min_value=0.0, max_value=0.05)

        c5, c6, c7 = st.columns([1.2, 2, 2])
        with c5:
            st.markdown("**Limestone ₹/t** · *belt data*")
            for i in M.INTEGRATED:
                num(f"{i} {M.SITE_INFO[i][0]}", ("limestone", i), "as", format="%.0f", step=5.0)
        with c6:
            st.markdown("**Integrated modules** · *vendor quotes*")
            for k in M.MODULES:
                cc = st.columns(4)
                for col, f, lab in zip(cc, ("clk", "grd", "capex", "opex"),
                                       ("Clinker", "Grinding", "Capex", "Opex")):
                    with col:
                        num(f"{k} {lab}", ("int_modules", k, f), "as", format="%.1f", step=0.5)
        with c7:
            st.markdown("**Split-grinding modules** · *vendor quotes*")
            for k in M.MODULES:
                cc = st.columns(3)
                for col, f, lab in zip(cc, ("grd", "capex", "opex"), ("Grinding", "Capex", "Opex")):
                    with col:
                        num(f"{k} {lab}", ("grd_modules", k, f), "as", format="%.1f", step=0.5)

        st.markdown("**Scope exclusions** (text, not numbers)")
        st.info(M.SCOPE_EXCLUSIONS + "\n\n**Direction of bias:** " + M.BIAS_NOTE)


# ---------------------------------------------------------------------------
# Step 1 — demand
# ---------------------------------------------------------------------------

def _share_cb(key):
    new = float(ss[key])
    if ss.share > 0:
        ss.inputs["demand"] = {m: q * new / ss.share for m, q in ss.inputs["demand"].items()}
    ss.share = new
    bump()


def _demand_edit_cb(key):
    edits = ss[key].get("edited_rows", {})
    for idx, row in edits.items():
        if "Target (Mt)" in row and row["Target (Mt)"] is not None:
            ss.inputs["demand"][M.MARKETS[int(idx)]] = float(row["Target (Mt)"])
    ss.mix = "Custom"
    bump()


def step1():
    st.header("Step 1 — Frame the demand")
    st.caption("FY2030 client target by market cluster. The client target is a market share of the "
               "FY2030 cluster market; the slider rescales all 12 targets together.")
    c = st.columns([2, 1, 1, 1])
    key = f"share:{ss.ver}"
    c[0].slider("Market share %", 3.0, 8.0, float(ss.share), 0.1, key=key,
                on_change=_share_cb, args=(key,))
    if c[1].button("Base (5%)", width="stretch"):
        ss.inputs["demand"] = dict(M.BASE_DEMAND)
        ss.share, ss.mix = M.BASE_SHARE, "Base"
        bump()
        st.rerun()
    if c[2].button("Scenario A mix shift", width="stretch"):
        ss.inputs["demand"] = M.demand_at_share(ss.share, M.SCENARIO_A_DEMAND)
        ss.mix = "Scenario A"
        bump()
        st.rerun()
    if c[3].button("Custom", width="stretch"):
        ss.mix = "Custom"
        st.toast("Edit any target in the table below.")
    st.caption(f"Active mix: **{ss.mix}** at **{ss.share:.1f}%** share")

    sizes = M.market_sizes()
    d = ss.inputs["demand"]
    df = pd.DataFrame({
        "ID": M.MARKETS,
        "Cluster": [M.MARKET_INFO[m][0] for m in M.MARKETS],
        "Centre": [M.MARKET_INFO[m][1] for m in M.MARKETS],
        "FY2030 market (Mt)": [sizes[m] for m in M.MARKETS],
        "Target (Mt)": [d[m] for m in M.MARKETS],
    })
    ekey = f"demand_editor:{ss.ver}"
    st.data_editor(df, key=ekey, on_change=_demand_edit_cb, args=(ekey,), hide_index=True,
                   width="stretch", disabled=["ID", "Cluster", "Centre", "FY2030 market (Mt)"],
                   column_config={"FY2030 market (Mt)": st.column_config.NumberColumn(format="%.1f"),
                                  "Target (Mt)": st.column_config.NumberColumn(format="%.3f", min_value=0.0)})
    tot = sum(d.values())
    cc = st.columns(3)
    cc[0].metric("Total target", f"{tot:.3f} Mt", f"{tot - 33.78:+.3f} Mt vs 33.78" if abs(tot - 33.78) > 5e-4 else None)
    cc[1].metric("Clinker needed (θ × demand)", f"{ss.inputs['params']['theta'] * tot:.2f} Mt")
    cc[2].metric("Usable grinding needed (÷ β)", f"{tot / ss.inputs['params']['beta']:.2f} MTPA nameplate")
    if abs(tot - 33.78) > 5e-4:
        st.warning(f"Total demand is {tot:.3f} Mt — {tot - 33.78:+.3f} Mt away from the 33.78 Mt "
                   "client target. Results will not be comparable with the base case.")
    if st.button("Confirm demand → Step 2", type="primary"):
        ss.done[1] = True
        ss.step = 2
        st.rerun()


# ---------------------------------------------------------------------------
# Step 2 — candidate sites
# ---------------------------------------------------------------------------

def _status_cb(site, key):
    ss.inputs["site_status"][site] = LABEL_STATUS[ss[key]]
    if ss.inputs["site_status"][site] == "excluded":
        ss.inputs["module_lock"][site] = None
    bump()


def _lock_cb(site, key):
    v = ss[key]
    ss.inputs["module_lock"][site] = None if v == "Any" else v
    bump()


def site_row(s):
    info = M.SITE_INFO[s]
    status = ss.inputs["site_status"][s]
    cols = st.columns([2.6, 1.6, 1.1])
    extra = ""
    if s in M.INTEGRATED:
        ls = ss.inputs["limestone"][s]
        hi = ls == max(ss.inputs["limestone"].values())
        extra = f" · limestone ₹{ls:.0f}/t" + (" 🔺 **highest**" if hi else "")
    cols[0].markdown(f"**{s}** {info[0]}  \n<small>{info[1]}{extra}</small>", unsafe_allow_html=True)
    k1 = f"status:{s}:{ss.ver}"
    cols[1].selectbox("State", list(LABEL_STATUS), index=list(LABEL_STATUS).index(STATUS_LABEL[status]),
                      key=k1, on_change=_status_cb, args=(s, k1), label_visibility="collapsed")
    k2 = f"lock:{s}:{ss.ver}"
    lock = ss.inputs["module_lock"].get(s) or "Any"
    cols[2].selectbox("Module", ["Any", "S", "M", "L"], index=["Any", "S", "M", "L"].index(lock),
                      key=k2, on_change=_lock_cb, args=(s, k2), label_visibility="collapsed",
                      disabled=status == "excluded", help="Optional module lock")


def step2():
    st.header("Step 2 — Choose candidate sites")
    st.caption("**Available**: the optimiser may open it · **Forced open**: must open (optionally at a "
               "locked module) · **Excluded**: cannot open. Excluding I1 *is* Scenario C.")
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Integrated belts (kiln + grinding)")
        st.caption("State · module lock")
        for s in M.INTEGRATED:
            site_row(s)
    with c2:
        st.subheader("Split-grinding sites")
        st.caption("State · module lock")
        for s in M.GRINDERS:
            site_row(s)
        st.markdown("---")
        p = ss.inputs["params"]
        big = {s: max((M.allowed_modules(M.with_mode(ss.inputs, "C"), s)),
                      key=lambda k: M._mods(ss.inputs, s)[k]["grd"], default=None) for s in M.SITES}
        grd = sum(M._mods(ss.inputs, s)[k]["grd"] for s, k in big.items() if k)
        clk = sum(ss.inputs["int_modules"][k]["clk"] for s, k in big.items() if k and s in M.INTEGRATED)
        D = sum(ss.inputs["demand"].values())
        st.markdown("**Capacity ceiling** (every permitted site at its largest module)")
        cc = st.columns(2)
        cc[0].metric("Usable grinding", f"{p['beta'] * grd:.2f} Mt", f"{p['beta'] * grd - D:+.2f} vs demand")
        cc[1].metric("Usable clinker", f"{p['beta'] * clk:.2f} Mt",
                     f"{p['beta'] * clk - p['theta'] * D:+.2f} vs need")
        if p["beta"] * grd < D:
            st.error(f"Grinding ceiling is {D - p['beta'] * grd:.2f} Mt short of demand — "
                     "this selection cannot be feasible.")
    if st.button("Confirm sites → Step 3", type="primary"):
        ss.done[2] = True
        ss.step = 3
        st.rerun()


# ---------------------------------------------------------------------------
# Step 3 — rules and rates
# ---------------------------------------------------------------------------

def step3():
    st.header("Step 3 — Set rules and rates")
    st.markdown("**Scenario presets** — set Steps 1–3 together")
    pc = st.columns(len(S.PRESETS))
    for col, (nm, desc) in zip(pc, S.PRESETS.items()):
        if col.button(nm, help=desc, width="stretch"):
            apply_inputs(S.preset(nm), mix="Scenario A" if nm.startswith("A") else "Base")
            st.toast(f"Applied preset: {nm}")
            st.rerun()

    c1, c2, c3 = st.columns(3)
    with c1:
        st.subheader("Freight")
        num("Cement freight (₹/t-km)", ("params", "fc"), "s3", format="%.2f", step=0.05, min_value=0.0)
        num("Clinker freight (₹/t-km)", ("params", "fk"), "s3", format="%.2f", step=0.05, min_value=0.0)
        p = ss.inputs["params"]
        st.caption(f"Cement costs {p['fc'] / p['fk']:.2f}× clinker per t-km; per tonne of cement, "
                   f"clinker haul costs {p['theta'] * p['fk'] / p['fc']:.0%} of a cement haul.")
    with c2:
        st.subheader("Service rules")
        num("Cement lane cap (km)", ("params", "Lcem"), "s3", integer=True, step=50, min_value=0)
        num("Clinker lane cap (km)", ("params", "Lclk"), "s3", integer=True, step=50, min_value=0)
        num("Max utilisation β", ("params", "beta"), "s3", format="%.2f", step=0.01,
            min_value=0.1, max_value=1.0)
    with c3:
        st.subheader("Technical & financial")
        num("Clinker factor θ", ("params", "theta"), "s3", format="%.3f", step=0.01, min_value=0.1)
        num("Hurdle rate r", ("params", "r"), "s3", format="%.4f", step=0.005, min_value=0.0)
        num("Asset life n (years)", ("params", "n"), "s3", integer=True, step=1, min_value=1)
        st.metric("Capital recovery factor", f"{M.crf(p['r'], p['n']):.6f}")

    ls = M.lane_summary(ss.inputs)
    st.subheader("Model size under the current caps")
    mc = st.columns(5)
    mc[0].metric("Cement lanes", ls["cement_lanes"], f"{ls['cement_from_plants']} plant · {ls['cement_from_grinders']} grinder",
                 delta_color="off")
    mc[1].metric("Clinker lanes", ls["clinker_lanes"])
    mc[2].metric("Flow variables", ls["flow_vars"])
    mc[3].metric("Binary variables", ls["binaries"])
    mc[4].metric("Total variables", ls["flow_vars"] + ls["binaries"],
                 f"vs {ls['full_matrix'] + ls['binaries']} full matrix", delta_color="off")
    cem, _ = M.lanes(ss.inputs)
    orphan = [m for m in M.MARKETS if not any(mm == m and ss.inputs["site_status"][s] != "excluded"
                                              for s, mm in cem)]
    if orphan:
        st.error("No permitted source within the cement cap for: " + ", ".join(orphan))
    if st.button("Confirm rules → Step 4", type="primary"):
        ss.done[3] = True
        ss.step = 4
        st.rerun()


# ---------------------------------------------------------------------------
# Step 4 — solve
# ---------------------------------------------------------------------------

def plan_flows():
    return M.plan_flows(ss.inputs, ss.plan_modules, ss.plan_flows_src,
                        reference=run(M.default_inputs()))


def solve_now():
    mode = ss.mode
    if mode == "C":
        res = run_mode(ss.inputs, "C")
    elif mode == "B":
        res = run_mode(ss.inputs, "B", ss.plan_modules)
    else:
        res = run_mode(ss.inputs, "A", ss.plan_modules, plan_flows())
    ss.result = res
    ss.result_key = input_key()
    ss.result_inputs = copy.deepcopy(ss.inputs)
    ss.reco = None


def _plan_cb(site, key):
    v = ss[key]
    ss.plan_modules[site] = None if v == "closed" else v


def show_infeasible(res):
    d = res["diagnosis"]
    st.error(f"**INFEASIBLE** — no network in this mode can serve {d['demand']:.2f} Mt. Why:")
    for line in d["explanation"]:
        st.markdown(f"- {line}")
    cc = st.columns(4)
    cc[0].metric("Usable grinding", f"{d['grinding_usable']:.2f} Mt", f"{d['grinding_usable'] - d['demand']:+.2f} Mt")
    cc[1].metric("Usable clinker", f"{d['clinker_usable']:.2f} Mt", f"{d['clinker_usable'] - d['clinker_needed']:+.2f} Mt")
    cc[2].metric("Min. unserved (lanes + caps)", f"{d['min_shortfall']:.2f} Mt")
    cc[3].metric("Demand", f"{d['demand']:.2f} Mt")


def step4():
    st.header("Step 4 — Solve")
    labels = {"C": "C — Full redesign (modules + flows optimised)",
              "B": "B — Re-route only (modules held, flows optimised)",
              "A": "A — Fixed plan (modules and flows fixed; evaluate)"}
    mode = st.radio("Mode", list(labels), format_func=labels.get, index=list(labels).index(ss.mode),
                    horizontal=True, key=f"mode:{ss.ver}")
    ss.mode = mode

    if mode in ("A", "B"):
        with st.container(border=True):
            st.markdown("**The plan on the table** — module per site (default: base-case optimum)")
            cols = st.columns(10)
            for col, s in zip(cols, M.SITES):
                k = f"plan:{s}:{ss.ver}"
                cur = ss.plan_modules.get(s) or "closed"
                col.selectbox(s, ["closed", "S", "M", "L"], index=["closed", "S", "M", "L"].index(cur),
                              key=k, on_change=_plan_cb, args=(s, k))
            b1, b2 = st.columns(2)
            if b1.button("Reset plan to base-case optimum"):
                ss.plan_modules = dict(run(M.default_inputs())["modules"])
                bump()
                st.rerun()
            if ss.result and ss.result.get("feasible") and b2.button("Use last solved network as plan"):
                ss.plan_modules = dict(ss.result["modules"])
                bump()
                st.rerun()
            if mode == "A":
                ss.plan_flows_src = st.radio(
                    "Plan flows", list(M.PLAN_RULES), index=list(M.PLAN_RULES).index(ss.plan_flows_src),
                    horizontal=True,
                    help="Frozen shares: each market keeps the base-case optimum's source split (and each "
                         "grinder its clinker split), scaled to current demand. Minimum tonne-km: the plan's "
                         "network routed to minimise t-km moved, blind to freight rates and limestone cost.")

    c = st.columns([1, 1, 3])
    if c[0].button("▶ Solve", type="primary", width="stretch"):
        with st.spinner("Solving MILP…"):
            solve_now()
    if c[1].button("Compare A / B / C", width="stretch"):
        with st.spinner("Solving three modes…"):
            fl = plan_flows()
            a = run_mode(ss.inputs, "A", ss.plan_modules, fl)
            bb = run_mode(ss.inputs, "B", ss.plan_modules)
            cc_ = run_mode(ss.inputs, "C")
            ss.gaps = {"A": a, "B": bb, "C": cc_, "key": input_key(), "plan": dict(ss.plan_modules),
                       "flows": ss.plan_flows_src}
            if ss.result is None or is_stale():
                solve_now()

    res = ss.result
    if res is None:
        st.info("Press **Solve** to run the model.")
        return
    if is_stale():
        st.warning("⚠️ Inputs have changed since this solve — **re-solve needed**. Showing the previous result.")
    st.subheader(f"Result — mode {res['mode']}")
    mc = st.columns([1, 1.6, 0.9, 1, 1])
    mc[0].metric("Solver status", res["status"])
    mc[1].metric("Objective", fmt_cr(res.get("objective")) if res["feasible"] else "INFEASIBLE")
    mc[2].metric("Wall time", f"{res['wall_time']:.2f} s")
    mc[3].metric("MIP gap achieved", f"{res['mip_gap']:.4%}" if res["mode"] == "C" else "LP (n/a)")
    mc[4].metric("Model size", f"{res['lanes']['flow_vars'] + res['lanes']['binaries']} vars")
    if not res["feasible"]:
        show_infeasible(res)
    else:
        st.success(f"**Open network:** {mods_str(res['modules'])} · unit cost ₹{res['kpis']['unit_cost']:,.0f}/t · "
                   f"capex ₹{res['kpis']['capex_total']:,.0f} cr")
        if res["mode"] == "C" and not S.assumption_diff(ss.inputs):
            ok = abs(res["objective"] - BENCHMARK) < 0.01
            (st.success if ok else st.error)(
                f"{'✓ PASS' if ok else '✗ FAIL'} — base case reproduces ₹{BENCHMARK:,.2f} crore/yr "
                f"(solved: ₹{res['objective']:,.2f})")
        if st.button("Read the network → Step 5", type="primary"):
            ss.step = 5
            st.rerun()

    g = ss.gaps
    if g:
        st.subheader("Mode gaps")
        if g["key"] != input_key():
            st.caption("⚠️ computed for earlier inputs")
        ob = lambda r: r["objective"] if r.get("feasible") else None  # noqa: E731
        A, B, C = ob(g["A"]), ob(g["B"]), ob(g["C"])
        df = pd.DataFrame([
            {"Mode": "A — Fixed plan", "Objective ₹cr": A, "Network": mods_str(g["plan"]),
             "Note": f"flows: {g['flows']}"},
            {"Mode": "B — Re-route only", "Objective ₹cr": B, "Network": mods_str(g["plan"]), "Note": ""},
            {"Mode": "C — Full redesign", "Objective ₹cr": C,
             "Network": mods_str(g["C"].get("modules")), "Note": ""},
        ])
        st.dataframe(df, hide_index=True, width="stretch",
                     column_config={"Objective ₹cr": st.column_config.NumberColumn(format="%.2f")})
        gc = st.columns(3)
        dif = lambda x, y: None if x is None or y is None else x - y  # noqa: E731
        for col, lab, v, base_ in ((gc[0], "A − B · allocation improvement", dif(A, B), B),
                                   (gc[1], "B − C · footprint regret", dif(B, C), C),
                                   (gc[2], "A − C · status-quo regret", dif(A, C), C)):
            col.metric(lab, "n/a (infeasible)" if v is None else f"₹{v:,.1f} cr",
                       None if v is None else f"{v / base_:.2%}", delta_color="off")
        for lab, r in (("A", g["A"]), ("B", g["B"]), ("C", g["C"])):
            if not r["feasible"]:
                st.markdown(f"**Mode {lab} infeasible:** " + " ".join(r["diagnosis"]["explanation"]))


# ---------------------------------------------------------------------------
# Step 5 — read the network
# ---------------------------------------------------------------------------

def step5():
    st.header("Step 5 — Read the network")
    res = ss.result
    if is_stale():
        st.warning("⚠️ Inputs have changed — these outputs are from the previous solve. **Re-solve needed.**")
    if not res["feasible"]:
        show_infeasible(res)
        return
    ss.visited.add(5)
    inp = ss.result_inputs
    k = res["kpis"]
    st.caption(f"Mode {res['mode']} · {mods_str(res['modules'])}")
    kc = st.columns(4)
    kc[0].metric("Annual relevant cost", f"₹{res['objective']:,.2f} cr")
    kc[1].metric("Unit cost", f"₹{k['unit_cost']:,.0f}/t")
    kc[2].metric("Total capex", f"₹{k['capex_total']:,.0f} cr")
    kc[3].metric("Highest utilisation", f"{k['max_util']:.1f}%")
    kc = st.columns(4)
    kc[0].metric("Nameplate clinker", f"{k['clinker_nameplate']:.1f} MTPA")
    kc[1].metric("Nameplate grinding", f"{k['grinding_nameplate']:.1f} MTPA")
    kc[2].metric("Avg cement lead", f"{k['cement_lead_km']:.0f} km")
    kc[3].metric("Avg clinker lead", f"{k['clinker_lead_km']:.0f} km")

    t_map, t_sites, t_flows, t_cost, t_val = st.tabs(
        ["🗺️ Map", "🏭 Open sites", "🚚 Flows", "💰 Cost reconciliation", "✅ Validation"])
    with t_map:
        show_c = st.toggle("Show cement lanes", value=True)
        st.plotly_chart(V.network_map(res, inp, show_cement=show_c), width="stretch")
        st.caption("Blue circles: integrated plants · orange squares: split-grinding units · grey diamonds: "
                   "markets (size = demand). Arrows are clinker lanes, drawn plant → grinder only.")
    with t_sites:
        rows = [{"Site": s["site"], "Name": s["name"], "Type": s["type"], "Module": s["module"],
                 "Clinker cap MTPA": s["clinker_cap"], "Grinding cap MTPA": s["grinding_cap"],
                 "Cement out Mt": s["cement_out"],
                 "Clinker made / in Mt": s["clinker_made"] if s["clinker_made"] is not None else s.get("clinker_in"),
                 "Util clinker %": s["util_clinker"], "Util grinding %": s["util_grinding"],
                 "Annualised capex ₹cr": s["capex_annual"], "Fixed opex ₹cr": s["opex"]} for s in res["sites"]]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                     column_config={c_: st.column_config.NumberColumn(format="%.2f") for c_ in
                                    ("Cement out Mt", "Clinker made / in Mt", "Annualised capex ₹cr")} |
                                   {c_: st.column_config.NumberColumn(format="%.1f") for c_ in
                                    ("Util clinker %", "Util grinding %")})
        st.plotly_chart(V.utilisation_bars(res, inp["params"]["beta"]), width="stretch")
    with t_flows:
        f1, f2 = st.columns([3, 2])
        with f1:
            st.markdown("**Cement flows**")
            df = pd.DataFrame(res["cement_flows"]).rename(columns={
                "source": "Source", "type": "Type", "market": "Market", "cluster": "Cluster",
                "distance": "km", "Mt": "Mt", "cost": "₹cr"})
            st.dataframe(df, hide_index=True, width="stretch",
                         column_config={"Mt": st.column_config.NumberColumn(format="%.4f"),
                                        "₹cr": st.column_config.NumberColumn(format="%.2f")})
        with f2:
            st.markdown("**Clinker flows** (plant → grinder)")
            df = pd.DataFrame(res["clinker_flows"]).rename(columns={
                "plant": "Plant", "grinder": "Grinder", "distance": "km", "cost": "₹cr"})
            st.dataframe(df, hide_index=True, width="stretch",
                         column_config={"Mt": st.column_config.NumberColumn(format="%.4f"),
                                        "₹cr": st.column_config.NumberColumn(format="%.2f")})
            st.caption(f"Total clinker moved: {k['clinker_moved']:.4f} Mt")
    with t_cost:
        c1, c2 = st.columns([1, 2])
        rows = [{"Component": n, "₹ crore/yr": v, "Share": v / res["objective"]} for n, v in res["costs"].items()]
        rows.append({"Component": "Total", "₹ crore/yr": sum(res["costs"].values()), "Share": 1.0})
        c1.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                     column_config={"₹ crore/yr": st.column_config.NumberColumn(format="%.2f"),
                                    "Share": st.column_config.NumberColumn(format="percent")})
        diff = sum(res["costs"].values()) - res["objective_solver"]
        (c1.success if abs(diff) < 0.01 else c1.error)(
            f"Components sum to the solver objective (difference ₹{diff:.4f} cr)")
        c2.plotly_chart(V.cost_waterfall(res["costs"], res["objective"]), width="stretch")
    with t_val:
        allok = all(ok for _, ok, _ in res["validation"])
        (st.success if allok else st.error)("All checks green" if allok else "One or more checks failed")
        for name, ok, note in res["validation"]:
            st.markdown(f"{'🟢' if ok else '🔴'} **{name}** — {note}")

    st.download_button("⬇️ Export results to Excel", S.results_to_excel(res, inp),
                       file_name="rookie_results.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    if st.button("Scenarios & recommendation → Step 6", type="primary"):
        ss.step = 6
        st.rerun()


# ---------------------------------------------------------------------------
# Step 6 — scenarios and recommendation
# ---------------------------------------------------------------------------

def scenario_pool():
    pool = {"Current inputs": copy.deepcopy(ss.inputs)}
    for nm in S.PRESETS:
        pool[nm] = S.preset(nm)
    for nm, inp in ss.saved.items():
        full = M.default_inputs()
        full.update(copy.deepcopy(inp))
        pool[f"Saved: {nm}"] = full
    return pool


def reference_network():
    """The network under test in Step 6: the current solve if feasible, else the base optimum."""
    if ss.result and ss.result.get("feasible"):
        return dict(ss.result["modules"]), ss.result_inputs
    return dict(run(M.default_inputs())["modules"]), M.default_inputs()


def disruption(inputs, modules):
    rows = []
    opt = run_mode(inputs, "C")
    ref = reroute(inputs, modules)
    for s in [s for s in M.SITES if modules.get(s)]:
        fr = reroute(inputs, modules, drop=(s,))
        ex = copy.deepcopy(inputs)
        ex["site_status"][s] = "excluded"
        ex["module_lock"][s] = None
        rd = run_mode(ex, "C")
        rows.append({"site": s, "module": modules[s], "frozen": fr, "redesign": rd})
    return {"rows": rows, "ref": ref, "opt": opt}


def robustness(modules, pool):
    rows = []
    for nm, inp in pool.items():
        opt = run_mode(inp, "C")
        fx = reroute(inp, modules)
        relaxed = None
        if not fx["feasible"]:
            r2 = copy.deepcopy(inp)
            r2["params"]["Lcem"] = max(2500, r2["params"]["Lcem"])
            relaxed = reroute(r2, modules)
        rows.append({"name": nm, "opt": opt, "fixed": fx, "relaxed": relaxed})
    return rows


def _mod_diff(a, b):
    out = []
    for s in M.SITES:
        if a.get(s) != b.get(s):
            out.append(f"{s}-{a.get(s) or '×'} (not {s}-{b.get(s) or '×'})")
    return ", ".join(out)


def step6():
    st.header("Step 6 — Scenarios and recommendation")
    if is_stale():
        st.warning("⚠️ Inputs have changed since the last solve — the reference network is from the "
                   "previous solve. **Re-solve needed** for a consistent reading.")
    ss.visited.add(6)
    ref_mods, ref_inp = reference_network()
    st.caption(f"Reference network (from your last solve): **{mods_str(ref_mods)}**")
    tabs = st.tabs(["📊 Scenario comparison", "🛡️ Robustness", "⚡ Disruption grid",
                    "🔍 Near-optimal networks", "📈 Share sensitivity", "🧭 Recommendation"])
    pool = scenario_pool()

    with tabs[0]:
        pick = st.multiselect("Scenarios to compare (full re-optimisation each)", list(pool),
                              default=list(pool)[:6])
        rows, bars = [], []
        base_obj = run(M.default_inputs())["objective"]
        with st.spinner("Solving scenarios…"):
            for nm in pick:
                r = run_mode(pool[nm], "C")
                row = {"Scenario": nm}
                if r["feasible"]:
                    row.update({"Objective ₹cr": r["objective"], "vs base": r["objective"] / base_obj - 1,
                                "Open sites": mods_str(r["modules"])})
                    row.update({c_: v for c_, v in r["costs"].items()})
                    row.update({"Cement lead km": r["kpis"]["cement_lead_km"],
                                "Clinker lead km": r["kpis"]["clinker_lead_km"],
                                "Max util %": r["kpis"]["max_util"], "₹/t": r["kpis"]["unit_cost"]})
                    bars.append({"name": nm, "costs": r["costs"]})
                else:
                    row.update({"Open sites": "INFEASIBLE — " + r["diagnosis"]["explanation"][0]})
                rows.append(row)
        if rows:
            fmt = {c_: st.column_config.NumberColumn(format="%.1f") for c_ in
                   ["Objective ₹cr", *V.COMPONENT_COLORS, "Cement lead km", "Clinker lead km", "Max util %", "₹/t"]}
            fmt["vs base"] = st.column_config.NumberColumn(format="percent")
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config=fmt)
            if bars:
                st.plotly_chart(V.component_bars(bars), width="stretch")

    with tabs[1]:
        st.markdown(f"Hold **{mods_str(ref_mods)}** fixed and re-optimise flows only under each scenario.")
        with st.spinner("Re-routing under each scenario…"):
            rob = robustness(ref_mods, pool)
        rows = []
        for r in rob:
            o, f = r["opt"], r["fixed"]
            row = {"Scenario": r["name"],
                   "Scenario optimum ₹cr": o["objective"] if o["feasible"] else None,
                   "Fixed footprint ₹cr": f["objective"] if f["feasible"] else None}
            if f["feasible"] and o["feasible"]:
                row["Premium"] = f["objective"] / o["objective"] - 1
                row["Result"] = "Survives by re-routing"
            elif not f["feasible"]:
                d = f["diagnosis"]
                gap = d["grinding_gap"] or d["min_shortfall"]
                row["Result"] = f"INFEASIBLE — {gap:.2f} Mt short. " + d["explanation"][0]
                if r["relaxed"] is not None:
                    row["Result"] += (" Still infeasible with cement cap relaxed to 2,500 km."
                                      if not r["relaxed"]["feasible"] else
                                      f" Feasible at 2,500 km cap (₹{r['relaxed']['objective']:,.1f} cr).")
            else:
                row["Result"] = "Scenario itself infeasible"
            rows.append(row)
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                     column_config={"Scenario optimum ₹cr": st.column_config.NumberColumn(format="%.1f"),
                                    "Fixed footprint ₹cr": st.column_config.NumberColumn(format="%.1f"),
                                    "Premium": st.column_config.NumberColumn(format="percent"),
                                    "Result": st.column_config.TextColumn(width="large")})

    with tabs[2]:
        st.markdown("Close each open site in turn. **Frozen**: other modules unchanged, flows re-optimised. "
                    "**Redesign**: site excluded, everything else re-optimised.")
        with st.spinner("Running disruption grid…"):
            dg = disruption(ref_inp, ref_mods)
        rows = []
        refc = dg["ref"]["objective"] if dg["ref"]["feasible"] else None
        optc = dg["opt"]["objective"] if dg["opt"]["feasible"] else None
        for r in dg["rows"]:
            fr, rd = r["frozen"], r["redesign"]
            rows.append({
                "Close": f"{r['site']}-{r['module']} {M.SITE_INFO[r['site']][0]}",
                "Frozen modules ₹cr": fr["objective"] if fr["feasible"] else None,
                "Frozen": (f"+{fr['objective'] / refc - 1:.2%}" if fr["feasible"] and refc else
                           f"INFEASIBLE ({(fr['diagnosis']['grinding_gap'] or fr['diagnosis']['min_shortfall']):.2f} Mt short)"),
                "Redesign ₹cr": rd["objective"] if rd["feasible"] else None,
                "Redesign": (f"+{rd['objective'] / optc - 1:.2%}" if rd["feasible"] and optc else
                             f"INFEASIBLE ({(rd['diagnosis']['grinding_gap'] or rd['diagnosis']['min_shortfall']):.2f} Mt short)"),
                "Role": "Load-bearing" if not rd["feasible"] else "Economic",
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                     column_config={"Frozen modules ₹cr": st.column_config.NumberColumn(format="%.1f"),
                                    "Redesign ₹cr": st.column_config.NumberColumn(format="%.1f")})

    with tabs[3]:
        st.markdown("Every module combination within the band of the optimum. Pruned before each LP on "
                    "capacity (usable grinding / clinker below demand) and on fixed cost + a site-set "
                    "lower bound on variable cost.")
        band = st.select_slider("Band", [0.005, 0.01, 0.02, 0.05], value=0.05, format_func=lambda b: f"{b:.1%}")
        if st.button("Run enumeration", type="primary") or ss.get("enum_ran") == _key(ss.inputs) + str(band):
            with st.spinner("Enumerating module combinations…"):
                e = enumerate_networks(ss.inputs, band)
            ss.enum_ran = _key(ss.inputs) + str(band)
            if not e["feasible"]:
                st.error("Current inputs are infeasible — nothing to enumerate.")
            else:
                show_enum(e)

    with tabs[4]:
        shares = [4.0, 4.5, 5.0, 5.5, 6.0]
        mix = {m: ss.inputs["demand"][m] * M.BASE_SHARE / ss.share for m in M.MARKETS}
        st.markdown(f"Full re-optimisation at each share, current mix ({ss.mix}).")
        rows = []
        prev = None
        with st.spinner("Solving share band…"):
            for sh in shares:
                inp = copy.deepcopy(ss.inputs)
                inp["demand"] = M.demand_at_share(sh, mix)
                r = run_mode(inp, "C")
                row = {"Share %": sh, "Volume Mt": sum(inp["demand"].values())}
                if r["feasible"]:
                    sites = {s for s in M.SITES if r["modules"].get(s)}
                    row.update({"Objective ₹cr": r["objective"], "₹/t": r["kpis"]["unit_cost"],
                                "Network": mods_str(r["modules"])})
                    if prev is not None:
                        ch = [f"+{s}" for s in sorted(sites - prev)] + [f"−{s}" for s in sorted(prev - sites)]
                        row["Site changes vs previous"] = " ".join(ch) or "—"
                    prev = sites
                else:
                    row["Network"] = "INFEASIBLE — " + r["diagnosis"]["explanation"][0]
                rows.append(row)
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                     column_config={"Objective ₹cr": st.column_config.NumberColumn(format="%.1f"),
                                    "₹/t": st.column_config.NumberColumn(format="%.0f"),
                                    "Volume Mt": st.column_config.NumberColumn(format="%.2f")})

    with tabs[5]:
        recommendation(pool)


def show_enum(e):
    opt = e["optimum"]
    st.caption(f"{e['lps_solved']:,} LPs solved · {e['pruned_capacity']:,} pruned on capacity · "
               f"{e['pruned_fixed']:,} pruned on cost bound · {e['wall_time']:.1f}s")
    rows = [{"Within": f"{b['band']:.1%}", "Alternative networks": b["networks"],
             "Same site set (re-sized)": b["same_sites"],
             "Distinct alternative footprints": b["alt_footprints"]} for b in e["bands"]]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.plotly_chart(V.band_chart(e["networks"], opt, e["optimum_sites"]), width="stretch")
    optn = next(n for n in e["networks"] if n.get("is_optimum"))
    st.markdown("**Closest alternatives**")
    rows = []
    for n in [n for n in e["networks"] if not n.get("is_optimum")][:12]:
        rows.append({"Premium": n["premium"], "₹cr": n["objective"],
                     "Type": "Same sites, re-sized" if n["sites"] == e["optimum_sites"] else "Different site set",
                     "Differs from optimum": _mod_diff(n["modules"], optn["modules"])})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"Premium": st.column_config.NumberColumn(format="percent"),
                                "₹cr": st.column_config.NumberColumn(format="%.1f")})
    if e["alt_footprints"]:
        st.markdown("**Alternative footprints** (cheapest sizing of each different site set)")
        for a in e["alt_footprints"]:
            add = ", ".join(a["added"]) or "—"
            rem = ", ".join(a["removed"]) or "—"
            st.markdown(f"- **+{a['premium']:.2%}** · adds {add} · drops {rem} · {M.fmt_network(a['modules'])}")


def recommendation(pool):
    st.markdown("Generated from the model's own results for the current inputs — nothing is pre-written.")
    if not st.button("Generate recommendation", type="primary") and ss.reco is None:
        return
    inp = copy.deepcopy(ss.inputs)
    with st.spinner("Running redesign, disruption, robustness and enumeration…"):
        opt = run_mode(inp, "C")
        if not opt["feasible"]:
            st.error("The current inputs are infeasible, so there is no network to recommend.")
            for line in opt["diagnosis"]["explanation"]:
                st.markdown(f"- {line}")
            return
        mods = opt["modules"]
        dg = disruption(inp, mods)
        rob = robustness(mods, {k: v for k, v in pool.items() if k != "Current inputs"})
        e = enumerate_networks(inp, 0.05)
    ss.reco = True
    k = opt["kpis"]
    st.subheader("Recommended network")
    st.success(f"**{mods_str(mods)}** — ₹{opt['objective']:,.2f} crore/yr "
               f"(₹{k['unit_cost']:,.0f}/t; capex ₹{k['capex_total']:,.0f} cr; "
               f"{k['clinker_moved']:.2f} Mt clinker shipped to grinders)")

    lb = [r for r in dg["rows"] if not r["redesign"]["feasible"]]
    ec = sorted([r for r in dg["rows"] if r["redesign"]["feasible"]],
                key=lambda r: -r["redesign"]["objective"])
    st.subheader("Which sites carry the network")
    if lb:
        st.markdown("**Load-bearing** (removing any one is infeasible even with full redesign): " + ", ".join(
            f"**{r['site']}** {M.SITE_INFO[r['site']][0]} "
            f"({(r['redesign']['diagnosis']['grinding_gap'] or r['redesign']['diagnosis']['min_shortfall']):.2f} Mt unservable)"
            for r in lb))
    else:
        st.markdown("No single site is load-bearing: every site can be replaced by a redesign.")
    if ec:
        st.markdown("**Economic** (replaceable, at a premium): " + " · ".join(
            f"{r['site']} +{r['redesign']['objective'] / opt['objective'] - 1:.2%}" for r in ec))

    st.subheader("Does the footprint survive the scenarios?")
    for r in rob:
        o, f = r["opt"], r["fixed"]
        if f["feasible"] and o["feasible"]:
            prem = f["objective"] / o["objective"] - 1
            st.markdown(f"- **{r['name']}** — survives by re-routing at **{prem:+.2%}** over that scenario's "
                        f"optimum (₹{f['objective']:,.1f} vs ₹{o['objective']:,.1f} cr).")
        elif not f["feasible"]:
            d = f["diagnosis"]
            txt = (f"- **{r['name']}** — **does not survive**: {d['explanation'][0]}")
            if r["relaxed"] is not None and not r["relaxed"]["feasible"]:
                txt += " Relaxing the cement cap to 2,500 km does not help — it is a capacity gap, not a lane gap."
            if o["feasible"]:
                txt += f" The scenario needs a different network: {mods_str(o['modules'])} (₹{o['objective']:,.1f} cr)."
            st.markdown(txt)
        else:
            st.markdown(f"- **{r['name']}** — infeasible for any network.")

    st.subheader("Where the decision is tight, and where it is not")
    if e.get("feasible"):
        same = [n for n in e["networks"] if n["sites"] == e["optimum_sites"] and not n.get("is_optimum")]
        optn = next(n for n in e["networks"] if n.get("is_optimum"))
        b1 = next((b for b in e["bands"] if b["band"] == 0.01), None)
        if same:
            st.markdown(
                f"- **Module sizing is near-indifferent.** {b1['same_sites'] if b1 else len(same)} re-sizings of the "
                f"same site set lie within 1%; the closest is **+{same[0]['premium']:.2%}** "
                f"({_mod_diff(same[0]['modules'], optn['modules'])}). Size decisions can be phased "
                "and revisited as demand firms up.")
        if e["alt_footprints"]:
            a = e["alt_footprints"][0]
            st.markdown(
                f"- **Site choice is where the decision is tight.** The nearest different footprint "
                f"(adds {', '.join(a['added']) or '—'}, drops {', '.join(a['removed']) or '—'}) costs "
                f"**+{a['premium']:.2%}**; only {len(e['alt_footprints'])} different site set(s) come within 5%.")
        else:
            st.markdown("- **Site choice is decisive.** No different site set comes within 5% of the optimum.")

    st.subheader("Caveat")
    st.warning("The objective excludes inventory and working capital, implementation phasing, and taxes "
               "and incentives. All of these favour **fewer, larger sites**, so the true optimum leans "
               "towards consolidation relative to this answer. " + M.SCOPE_EXCLUSIONS)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

st.title("The Rookie — FY2030 Cement Network Decision Lab")
assumptions_panel()
if not step_unlocked(ss.step):
    ss.step = max(n for n in STEPS if step_unlocked(n))
{1: step1, 2: step2, 3: step3, 4: step4, 5: step5, 6: step6}[ss.step]()

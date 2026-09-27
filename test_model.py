"""Section 8 validation benchmarks. Run:  python -m pytest -q test_model.py
(or `python test_model.py` without pytest)."""
import copy

import model as M
import scenarios as S

BASE_SITES = "I1-L, I3-L, I4-L, I5-M, I6-S, G1-L, G2-M, G3-M, G4-M"
_cache = {}


def base():
    if "base" not in _cache:
        _cache["base"] = M.run(M.default_inputs())
    return _cache["base"]


def full(inp):
    return M.run(M.with_mode(inp, "C"))


def excl(*sites):
    inp = M.default_inputs()
    for s in sites:
        inp["site_status"][s] = "excluded"
    return full(inp)


def close(a, b, tol):
    return abs(a - b) <= tol


# ---------------- base case ----------------

def test_base_objective():
    r = base()
    assert r["feasible"]
    assert close(r["objective"], 7792.26, 0.01), r["objective"]


def test_base_sites():
    assert M.fmt_network(base()["modules"]) == BASE_SITES


def test_base_components():
    c = base()["costs"]
    for k, v in {"Annualised capex": 2875.68, "Fixed opex": 844.00, "Limestone": 681.31,
                 "Cement freight": 2444.69, "Clinker freight": 946.57}.items():
        assert close(c[k], v, 0.01), (k, c[k])


def test_base_kpis():
    k = base()["kpis"]
    assert round(k["unit_cost"]) == 2307
    assert close(k["capex_total"], 22900, 1e-6)


def test_base_clinker_flows():
    fl = {(f["plant"], f["grinder"]): f["Mt"] for f in base()["clinker_flows"]}
    exp = {("I1", "G1"): 1.2963, ("I1", "G2"): 1.1337, ("I3", "G1"): 2.0037,
           ("I4", "G3"): 2.2011, ("I5", "G2"): 0.0273, ("I5", "G4"): 1.9437,
           ("I6", "G2"): 1.2150}
    assert set(fl) == set(exp), fl
    for k, v in exp.items():
        assert close(fl[k], v, 1e-4), (k, fl[k])
    assert close(sum(fl.values()), 9.8208, 1e-3)


def test_base_utilisation():
    u = {s["site"]: (s["util_clinker"], s["util_grinding"]) for s in base()["sites"]}
    exp = {"I1": (90.0, 90.0), "I3": (82.9, 90.0), "I4": (86.2, 90.0), "I5": (90.0, 90.0),
           "I6": (90.0, 90.0), "G1": (None, 83.3), "G2": (None, 90.0), "G3": (None, 83.4),
           "G4": (None, 73.6)}
    for s, (c, g) in exp.items():
        assert close(u[s][1], g, 0.05), (s, u[s])
        if c is not None:
            assert close(u[s][0], c, 0.05), (s, u[s])


def test_base_validation_all_green():
    assert all(ok for _, ok, _ in base()["validation"]), base()["validation"]


def test_lane_counts():
    ls = M.lane_summary(M.default_inputs())
    assert (ls["cement_from_plants"], ls["cement_from_grinders"], ls["clinker_lanes"]) == (26, 14, 15)
    assert ls["flow_vars"] == 55 and ls["flow_vars"] + ls["binaries"] == 85


# ---------------- scenarios ----------------

def test_base_preset_is_base():
    assert S.preset("Base") == M.default_inputs()
    assert not S.assumption_diff(S.preset("Base"))


def test_scenarios():
    exp = {
        "A — demand mix shift": (7889.4, "I1-L, I3-L, I4-L, I5-S, I6-M, G1-L, G2-M, G3-L, G4-S"),
        "B — freight shock (3.75 / 1.85)": (8518.1, "I1-L, I3-L, I4-L, I5-M, I6-M, G1-L, G2-M, G3-M, G4-S"),
        "C — Chittorgarh unavailable": (8215.1, "I2-S, I3-L, I4-L, I5-M, I6-L, G1-L, G2-M, G3-L, G4-S"),
        "600 km service standard": (7831.1, None),
    }
    for name, (obj, sites) in exp.items():
        r = full(S.preset(name))
        assert r["feasible"], name
        assert close(r["objective"], obj, 0.05), (name, r["objective"])
        if sites:
            assert M.fmt_network(r["modules"]) == sites, (name, M.fmt_network(r["modules"]))


# ---------------- robustness ----------------

def test_robustness():
    mods = base()["modules"]
    for name, obj, opt in (("A — demand mix shift", 7974.9, 7889.4),
                           ("B — freight shock (3.75 / 1.85)", 8521.1, 8518.1)):
        r = M.reroute(S.preset(name), mods)
        assert r["feasible"] and close(r["objective"], obj, 0.05), (name, r.get("objective"))
    assert close(7974.9 / 7889.4 - 1, 0.011, 0.001)
    # C — infeasible, 30.6 Mt usable grinding, 3.18 Mt gap
    r = M.reroute(S.preset("C — Chittorgarh unavailable"), mods)
    assert not r["feasible"]
    d = r["diagnosis"]
    assert close(d["grinding_usable"], 30.6, 1e-6)
    assert close(d["grinding_gap"], 3.18, 1e-6)
    relaxed = S.preset("C — Chittorgarh unavailable")
    relaxed["params"]["Lcem"] = 2500
    assert not M.reroute(relaxed, mods)["feasible"]


# ---------------- structural checks ----------------

def test_no_grinders_infeasible():
    r = excl(*M.GRINDERS)
    assert not r["feasible"]
    d = r["diagnosis"]
    assert close(d["grinding_nameplate"], 30.0, 1e-9) and close(d["grinding_usable"], 27.0, 1e-9)
    assert close(d["clinker_usable"], 32.4, 1e-9) and close(d["clinker_needed"], 22.2948, 1e-4)
    assert d["clinker_gap"] == 0


def test_load_bearing():
    for s in ("I3", "I4", "G3"):
        assert not excl(s)["feasible"], s


def test_exclusions_and_forcing():
    inp = M.default_inputs()
    inp["site_status"]["I2"] = "forced"
    assert close(full(inp)["objective"], 7939.5, 0.05)
    assert close(7939.5 / 7792.26 - 1, 0.0189, 0.0001)
    for s, obj in (("I6", 7939.5), ("I5", 8088.7), ("G4", 8209.1), ("G2", 8272.9), ("G1", 8796.2)):
        r = excl(s)
        assert r["feasible"] and close(r["objective"], obj, 0.05), (s, r.get("objective"))


def test_force_i2_hold_base_modules():
    mods = base()["modules"]
    for k, obj in zip("SML", (8124.1, 8254.6, 8402.6)):
        m2 = dict(mods, I2=k)
        r = M.reroute(M.default_inputs(), m2)
        assert r["feasible"] and close(r["objective"], obj, 0.05), (k, r.get("objective"))
        assert not M.reroute(M.default_inputs(), m2, drop=("I1",))["feasible"], k


# ---------------- near-optimal enumeration ----------------

def test_enumeration():
    e = M.enumerate_networks(M.default_inputs(), optimum=base(), band=0.05)
    got = {b["band"]: (b["networks"], b["same_sites"], b["alt_footprints"]) for b in e["bands"]}
    assert got == {0.005: (4, 4, 0), 0.01: (18, 18, 0), 0.02: (104, 102, 1),
                   0.05: (1254, 709, 3)}, got
    second = e["networks"][1]
    assert close(second["premium"], 0.0009, 0.0001)
    assert second["modules"]["I6"] == "M" and second["modules"]["G4"] == "S"
    prem = [round(a["premium"] * 100, 2) for a in e["alt_footprints"]]
    assert prem == [1.89, 2.01, 3.80], prem


# ---------------- market-share band ----------------

def test_share_band():
    for share, obj, unit in ((4.0, 6289.2, 2327), (4.5, 7017.3, 2308), (5.0, 7792.3, 2307),
                             (5.5, 8599.3, 2314), (6.0, 9353.7, 2307)):
        inp = M.default_inputs()
        inp["demand"] = M.demand_at_share(share)
        r = full(inp)
        assert close(r["objective"], obj, 0.05), (share, r["objective"])
        assert round(r["kpis"]["unit_cost"]) == unit, (share, r["kpis"]["unit_cost"])
        if share == 4.5:
            assert not r["modules"]["I6"]
        if share == 6.0:
            assert r["modules"]["I2"]


if __name__ == "__main__":
    import sys
    import time
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            t = time.perf_counter()
            try:
                fn()
                print(f"PASS {name} ({time.perf_counter() - t:.1f}s)")
            except AssertionError as ex:
                fails += 1
                print(f"FAIL {name}: {ex}")
    sys.exit(1 if fails else 0)

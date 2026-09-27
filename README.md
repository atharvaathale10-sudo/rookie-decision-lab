# The Rookie — Streamlit Decision Lab

Interactive solve of the Rookie FY2030 India cement network-design case: frame demand, choose
candidate sites, set rules and rates, solve the MILP, read the network, then stress-test it and get a
recommendation generated from the results.

## Files

| File | Role |
|---|---|
| `model.py` | Case data, `build_model()`, `solve()`, `evaluate()`, re-route / fixed-plan helpers, infeasibility diagnosis, near-optimal enumeration. **No Streamlit import.** |
| `scenarios.py` | Presets (Base, A, B, C, 600 km), assumption diff, JSON save/load, Excel export. |
| `viz.py` | Plotly map (clinker arrows drawn plant → grinder only, enforced in code), waterfall, charts. |
| `app.py` | Streamlit interface only. |
| `test_model.py` | Every benchmark in spec §8. |

## Run locally

```bash
pip install -r requirements.txt
python model.py          # base case from the command line → ₹7,792.26 crore/yr
python test_model.py     # all §8 benchmarks (or: python -m pytest -q)
streamlit run app.py
```

## Solver notes

- The MILP is built in **PuLP 2.x** and solved with **HiGHS** (`pulp.HiGHS`, via `highspy`) at a relative
  MIP gap of 0.01%, falling back to PuLP's bundled CBC. PuLP 3/4 changed the modelling API, so
  `requirements.txt` pins `pulp<3`.
- Near-optimal enumeration re-solves a flow-only LP directly in `highspy`, changing only capacity-row
  bounds between networks. Before each LP it prunes on capacity (usable grinding or clinker below
  demand) and on fixed cost plus a site-set lower bound on variable cost. The full 5% band takes ~5 s.
- The near-optimal counts are **alternatives**, so they exclude the optimum itself (4 / 18 / 104 / 1,254).
- Mode A (fixed plan) evaluates a module plan with flows from one of two rules. *Frozen base-case
  sourcing shares* keeps each market's and grinder's source split, scaled to demand. *Minimum tonne-km
  routing* routes the plan to minimise t-km, blind to freight rates and limestone.

## Deploy (Streamlit Community Cloud)

1. Push this folder to a public GitHub repo.
2. At share.streamlit.io, connect the repo and choose `app.py`.
3. The build returns a `*.streamlit.app` link.

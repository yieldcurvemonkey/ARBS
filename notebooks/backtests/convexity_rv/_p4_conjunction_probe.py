r"""Why does the note's five-way conjunction never fire?  Measured, before the freeze.

The first preflight ran with the signal computed on the ROLL-SPLICED CA and got
**zero** days on which all five conditions hold, on any primary structure, over
1,409 dates.  A rule that never trades is a legitimate verdict, but only after
the obvious defect has been ruled out -- and there is an obvious one.

``roll_spliced`` removes each quarterly roll's jump from every later value.  The
jump IS the CA's own theta being paid back (measured here: +0.95 bp/roll on
BLUES against a quarter-theta of 0.92 bp, ratio 1.024), so a constant-rank CA is
STATIONARY precisely because of it and the spliced series is not -- it inherits
the whole undone decay as a downward drift of order 20 bp over the window.  A
252-day rolling z of a trending series mostly measures the trend.

Citi's screen z-scores the QUOTED pack CA, which is the constant-rank object a
desk looks at.  So the question this probe answers is: does the conjunction fire
on the raw quoted series, and if not, which pairs of conditions are actually
incompatible?

**No P&L is computed here.**

Output: notebooks/data/convexity_rv/p4_conjunction_probe.json
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.stdout.reconfigure(line_buffering=True)
pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 60)

from RVUtils.ConvexityRV import citi_rule as R  # noqa: E402
from RVUtils.ConvexityRV import citi_screen as SC  # noqa: E402

DATA = REPO / "notebooks" / "data" / "convexity_rv"
P = pd.read_parquet(DATA / "p4_citi.parquet")
P.index = pd.to_datetime(P.index)
S = SC.build_screen(P)
OUT: dict = {}


def sec(t: str) -> None:
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")


# ---------------------------------------------------------------------------
sec("0. What the splice does to the SIGNAL series")
# ---------------------------------------------------------------------------
from RVUtils.ConvexityRV.gv_sizing import roll_spliced  # noqa: E402

rolls = list(P.index[P["is_ca_roll"].astype(bool)])
rows = []
for lab in R.PRIMARY_UNIVERSE:
    raw = P[f"{lab.lower()}_ca_bp"].astype(float)
    spl = roll_spliced(raw, rolls)
    rows.append({
        "structure": lab,
        "raw_first": float(raw.iloc[0]), "raw_last": float(raw.iloc[-1]),
        "raw_drift_bp": float(raw.iloc[-1] - raw.iloc[0]),
        "spliced_drift_bp": float(spl.iloc[-1] - spl.iloc[0]),
        "undone_jumps_bp": float((raw.iloc[-1] - raw.iloc[0])
                                 - (spl.iloc[-1] - spl.iloc[0])),
        "raw_z_p50": float(SC.rolling_z(raw, 252).median()),
        "spliced_z_p50": float(SC.rolling_z(spl, 252).median()),
    })
D0 = pd.DataFrame(rows).set_index("structure")
print(D0.round(3).to_string())
print("\nThe spliced series carries the whole undone decay as a drift, so its "
      "rolling z sits below zero by construction.  That is right for P&L -- a "
      "DATED short earns exactly that decay -- and wrong for a screen, which "
      "asks whether a RANK of the curve is rich against its own history.")
OUT["splice_effect"] = json.loads(D0.reset_index().to_json(orient="records"))

# ---------------------------------------------------------------------------
sec("1. The conjunction on the RAW quoted CA (Citi's own screen object)")
# ---------------------------------------------------------------------------
for splice in (True, False):
    cfg = R.RuleConfig(splice_signal=splice)
    ctx = R.build_contexts(P, S, cfg)
    B = R.condition_binding(ctx, cfg)
    tag = "SPLICED" if splice else "RAW"
    print(f"\n--- signal on the {tag} series ---")
    print(B[[f"pass_{k}" for k in R.CONDITIONS] + ["pass_all"]].round(4).to_string())
    any_ok = pd.concat([c.all_ok.rename(l) for l, c in ctx.items()], axis=1)
    n = int(any_ok.any(axis=1).sum())
    print(f"days on which SOME primary structure satisfies all five: {n}")
    OUT[f"binding_{tag.lower()}"] = json.loads(B.reset_index().to_json(orient="records"))
    OUT[f"days_open_{tag.lower()}"] = n
    if not splice:
        CTX_RAW = ctx

# ---------------------------------------------------------------------------
sec("2. Which PAIRS of conditions are incompatible?  (raw signal, BLUES)")
# ---------------------------------------------------------------------------
c = CTX_RAW["BLUES"].conds
M = pd.DataFrame(index=list(R.CONDITIONS), columns=list(R.CONDITIONS),
                 dtype=float)
for a in R.CONDITIONS:
    for b in R.CONDITIONS:
        M.loc[a, b] = float((c[a] & c[b]).mean())
print("joint pass rate of each pair:")
print(M.round(4).to_string())
print("\nunder independence the pair rate would be the product; below/above "
      "that says whether the two conditions fight each other:")
ind = pd.DataFrame(np.outer(c.mean(), c.mean()), index=list(R.CONDITIONS),
                   columns=list(R.CONDITIONS))
print((M / ind.replace(0, np.nan)).round(3).to_string())
OUT["pair_joint_blues"] = json.loads(M.to_json())
OUT["pair_lift_blues"] = json.loads((M / ind.replace(0, np.nan)).to_json())

# ---------------------------------------------------------------------------
sec("3. The nested conjunction -- how many days survive each added condition?")
# ---------------------------------------------------------------------------
rows = []
for lab, cc in CTX_RAW.items():
    running = pd.Series(True, index=cc.conds.index)
    row = {"structure": lab}
    for k in R.CONDITIONS:
        running = running & cc.conds[k]
        row[f"after_{k}"] = int(running.sum())
    rows.append(row)
N = pd.DataFrame(rows).set_index("structure")
print(N.to_string())
OUT["nested"] = json.loads(N.reset_index().to_json(orient="records"))

# ---------------------------------------------------------------------------
sec("4. A relaxation ladder -- what threshold would the rule need to trade?")
# ---------------------------------------------------------------------------
print("Reported so the pre-registration can DECLARE a ladder rather than "
      "discover one after the fact.  Nothing here is scored.\n")
rows = []
for z in (2.0, 1.5, 1.0, 0.5, 0.0):
    for ir in (1.3, 1.0, 0.0):
        cfg = R.RuleConfig(splice_signal=False, z_model_min=z, z_fly_min=z,
                           impl_rlzd_min=ir)
        ctx = R.build_contexts(P, S, cfg)
        any_ok = pd.concat([x.all_ok.rename(l) for l, x in ctx.items()], axis=1)
        rows.append({"z_min": z, "impl_rlzd_min": ir,
                     "days_any_structure": int(any_ok.any(axis=1).sum()),
                     "days_blues": int(ctx["BLUES"].all_ok.sum())})
L = pd.DataFrame(rows)
print(L.pivot(index="z_min", columns="impl_rlzd_min",
              values="days_any_structure").to_string())
OUT["ladder"] = json.loads(L.to_json(orient="records"))

print("\nand with the positioning condition dropped as well:")
rows = []
rest = tuple(k for k in R.CONDITIONS if k != "positioning_stretched")
for z in (2.0, 1.5, 1.0):
    for ir in (1.3, 1.0, 0.0):
        cfg = R.RuleConfig(splice_signal=False, z_model_min=z, z_fly_min=z,
                           impl_rlzd_min=ir, conditions=rest)
        ctx = R.build_contexts(P, S, cfg)
        any_ok = pd.concat([x.all_ok.rename(l) for l, x in ctx.items()], axis=1)
        rows.append({"z_min": z, "impl_rlzd_min": ir,
                     "days_any_structure": int(any_ok.any(axis=1).sum())})
L2 = pd.DataFrame(rows)
print(L2.pivot(index="z_min", columns="impl_rlzd_min",
               values="days_any_structure").to_string())
OUT["ladder_no_positioning"] = json.loads(L2.to_json(orient="records"))

(DATA / "p4_conjunction_probe.json").write_text(json.dumps(OUT, indent=1))
print(f"\nwrote {DATA / 'p4_conjunction_probe.json'}")

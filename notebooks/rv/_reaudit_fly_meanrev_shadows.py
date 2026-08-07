"""Re-audit the fly mean-reversion lab's shadow tests at per-CONTRACT cost.

The shadow table charged every instrument ``2 * n_legs * 0.25bp``. A ``1/-2/1``
butterfly is three legs but **four contracts**, so it paid 1.5bp where it should
have paid 2.0bp, while every other shadow's leg count and contract count
coincide. Per-leg costing therefore handed the fly a 0.5bp-per-trade subsidy in
exactly the comparison the shadow test exists to make.

**No re-run is needed.** Cost enters the net P&L linearly and once per completed
trade, so for any instrument

    net_at(c) = gross - c * n_trades

and the stored table carries ``total_gross_bp`` and ``n_trades``. The corrected
fly figure is exactly ``gross - 2.0 * n``; every shadow is unchanged. That is an
identity, not an estimate, and it is asserted against the stored ``total_net_bp``
before anything is recomputed.

Run: conda run -n stir python notebooks/rv/_reaudit_fly_meanrev_shadows.py
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd

pd.set_option("display.width", 220, "display.max_columns", 30)

SRC = REPO / "notebooks" / "data" / "sfr_fly_meanrev" / "shadow_tests.csv"
OUT = REPO / "notebooks" / "data" / "sfr_fly_meanrev" / "shadow_tests_per_contract.csv"

#: contracts traded per instrument. Only the butterfly differs from its leg count.
CONTRACTS = {"fly": 4, "belly": 1, "belly_vs_front": 2, "belly_vs_back": 2,
             "wings_curve": 2}
HALF_SPREAD_BP = 0.25

df = pd.read_csv(SRC)
print(f"{len(df)} shadow rows over {df['framework'].nunique()} frameworks\n")

# ---------------------------------------------------------------- identity check
df["cost_per_leg_bp"] = 2.0 * df["n_legs"] * HALF_SPREAD_BP
recon = df["total_gross_bp"] - df["cost_per_leg_bp"] * df["n_trades"]
err = (recon - df["total_net_bp"]).abs()
# shadow_table stores gross and net each rounded to 1 decimal, so the identity
# can only be checked to +/-0.1bp. Anything larger would mean cost is NOT linear
# in the trade count and the frameworks would have to be re-run.
TOL = 0.1 + 1e-9
print("IDENTITY CHECK  net = gross - cost * n_trades")
print(f"  max |recomputed - stored| = {err.max():.6f}bp over {len(df)} rows")
print(f"  tolerance {TOL:.3f}bp: gross and net are each stored rounded to 1dp,")
print(f"  so 0.1bp is the largest discrepancy rounding alone can produce.")
if err.max() > TOL:
    bad = df[err > TOL]
    print("  ROWS THAT DO NOT RECONCILE -- the linear-cost assumption fails here:")
    print(bad.to_string(index=False))
    raise SystemExit("cannot re-cost by arithmetic; the frameworks must be re-run")
print(f"  {int((err > 1e-9).sum())} of {len(df)} rows differ at all, all by exactly one "
      f"rounding step.")
print("  -> cost is linear in n_trades, so re-costing needs no re-run.\n")

# ------------------------------------------------------------------ re-cost
df["n_contracts"] = df["instrument"].map(CONTRACTS)
df["cost_per_contract_bp"] = 2.0 * df["n_contracts"] * HALF_SPREAD_BP
df["net_per_contract_bp"] = (df["total_gross_bp"]
                             - df["cost_per_contract_bp"] * df["n_trades"])
df["delta_bp"] = df["net_per_contract_bp"] - df["total_net_bp"]

print("WHAT MOVES (mean change in net bp, by instrument):")
print(df.groupby("instrument")
      .agg(n_frameworks=("framework", "nunique"),
           cost_per_leg=("cost_per_leg_bp", "first"),
           cost_per_contract=("cost_per_contract_bp", "first"),
           mean_delta_bp=("delta_bp", "mean"))
      .round(3).to_string())
print("\n  Only the butterfly moves, and it moves DOWN. Every shadow is unchanged,")
print("  so the correction can only make the fly look worse relative to them.\n")

# ------------------------------------------------------- recount, both costings
rows = []
for fw, g in df.groupby("framework"):
    g = g.set_index("instrument")
    if "fly" not in g.index:
        continue
    shadows = [i for i in g.index if i != "fly"]
    old_fly, new_fly = g.loc["fly", "total_net_bp"], g.loc["fly", "net_per_contract_bp"]
    old_beat = [i for i in shadows if g.loc[i, "total_net_bp"] > old_fly]
    new_beat = [i for i in shadows if g.loc[i, "net_per_contract_bp"] > new_fly]
    belly_old = ("belly" in g.index and g.loc["belly", "total_net_bp"] > old_fly)
    belly_new = ("belly" in g.index and g.loc["belly", "net_per_contract_bp"] > new_fly)
    rows.append({
        "framework": fw, "n_trades": int(g.loc["fly", "n_trades"]),
        "fly_gross_bp": g.loc["fly", "total_gross_bp"],
        "fly_net_1.5bp": old_fly, "fly_net_2.0bp": new_fly,
        "any_shadow_beats_old": bool(old_beat), "any_shadow_beats_new": bool(new_beat),
        "belly_beats_old": bool(belly_old), "belly_beats_new": bool(belly_new),
        "any_flipped": bool(new_beat) and not bool(old_beat),
        "belly_flipped": bool(belly_new) and not bool(belly_old),
    })
res = pd.DataFrame(rows)
res.to_csv(OUT, index=False)

print("=" * 100)
print("RE-AUDIT: does a simpler instrument beat the fly, at per-CONTRACT cost?")
print("=" * 100)
print(res[["framework", "n_trades", "fly_net_1.5bp", "fly_net_2.0bp",
           "belly_beats_old", "belly_beats_new", "any_shadow_beats_old",
           "any_shadow_beats_new", "belly_flipped"]].round(1).to_string(index=False))

n = len(res)
print(f"""
SUMMARY over {n} frameworks

  outright belly beats the fly     per LEG (1.5bp)   {int(res['belly_beats_old'].sum())} / {n}
                                   per CONTRACT      {int(res['belly_beats_new'].sum())} / {n}
  ANY shadow beats the fly         per LEG           {int(res['any_shadow_beats_old'].sum())} / {n}
                                   per CONTRACT      {int(res['any_shadow_beats_new'].sum())} / {n}
  frameworks where the BELLY flipped to winning        {int(res['belly_flipped'].sum())}
    -> {', '.join(res.loc[res['belly_flipped'], 'framework']) or '(none)'}
  frameworks where ANY shadow flipped to winning      {int(res['any_flipped'].sum())}

  The prior lab published "the outright belly beats the fly in 16 of 24" and
  "the fly beats every linear shadow in 1 of 24" on the per-LEG figures. Those
  counts were computed with the butterfly under-charged by 0.5bp per trade, so
  they were CONSERVATIVE: the corrected counts are the ones above, and the
  conclusion the prior lab drew from them is strengthened, not weakened.

  Written to {OUT.name}""")

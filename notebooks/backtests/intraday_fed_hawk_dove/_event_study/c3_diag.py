import sys
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")

import pandas as pd
import numpy as np

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 100)
pd.set_option("display.max_rows", 200)

D = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study"
ev = pd.read_parquet(D + r"\event_paths.parquet")
pl = pd.read_parquet(D + r"\placebo_paths.parquet")

# ---- one row per event x rank at offset +240
def slab(df, off=240):
    return df[df["offset_min"] == off].copy()

s = slab(ev)
print("=== offset +240 slab ===")
print("rows", len(s), " events", s.event_id.nunique(), " ranks", sorted(s.contract_rank.unique()))
print()
print("coverage of d_rate_bp_from_baseline by rank (offset +240):")
for r in sorted(s.contract_rank.unique()):
    sr = s[s.contract_rank == r]
    sig = sr[sr.stance_score_exante.notna()]
    print(f"  rank {r}: n_ev={len(sr)}  y_ok={sr.d_rate_bp_from_baseline.notna().sum()}"
          f"  signed={len(sig)}  signed&y_ok={sig.d_rate_bp_from_baseline.notna().sum()}"
          f"  std(y)={sr.d_rate_bp_from_baseline.std():.3f}bp")
print()

# ---- is_voter PIT-varying?
ev1 = ev[(ev.offset_min == 240) & (ev.contract_rank == 1)]
print("=== is_voter variation within speaker ===")
vv = ev1.groupby("speaker")["is_voter"].agg(["mean", "nunique", "size"])
print(vv.sort_values("size", ascending=False).to_string())
print()

# ---- stance score distribution per speaker (signed events only)
sig = ev1[ev1.stance_score_exante.notna()]
print("=== speaker mean ex-ante stance (signed events, rank1 @+240) ===")
g = sig.groupby("speaker").agg(
    n=("event_id", "size"),
    mean_stance=("stance_score_exante", "mean"),
    min_stance=("stance_score_exante", "min"),
    max_stance=("stance_score_exante", "max"),
    n_voter=("is_voter", "sum"),
)
g["net_sign"] = np.sign(g["mean_stance"])
print(g.sort_values("n", ascending=False).to_string())
print()
print("speakers with NEGATIVE mean stance:", int((g.mean_stance < 0).sum()), "of", len(g))
print("speakers with n>=8:", int((g.n >= 8).sum()))
print("speakers with n>=8 AND negative mean stance:", int(((g.n >= 8) & (g.mean_stance < 0)).sum()))
print()

# ---- non-overlapping cut
clean = sig[~sig.is_overlapping]
print("=== non-overlapping AND signed ===")
gc = clean.groupby("speaker").agg(n=("event_id", "size"), mean_stance=("stance_score_exante", "mean"))
print("events", len(clean), " speakers", len(gc), " speakers n>=8:", int((gc.n >= 8).sum()),
      " neg-stance among those:", int(((gc.n >= 8) & (gc.mean_stance < 0)).sum()))
print(gc.sort_values("n", ascending=False).head(20).to_string())
print()

# ---- placebo: does it carry stance_score_exante?
pl1 = pl[(pl.offset_min == 240) & (pl.contract_rank == 1)]
print("=== placebo ===")
print("rows", len(pl1), "  stance_score notna", pl1.stance_score_exante.notna().sum())
print("speakers", pl1.speaker.nunique())
plsig = pl1[pl1.stance_score_exante.notna()]
gp = plsig.groupby("speaker").agg(n=("event_id", "size"), mean_stance=("stance_score_exante", "mean"))
print("placebo signed events", len(plsig), " speakers n>=8:", int((gp.n >= 8).sum()))
print()

# ---- how much does mean raw move vary across speakers? scale check
print("=== raw move at +240, rank1, signed events ===")
print(sig["d_rate_bp_from_baseline"].describe())
print()
print("per-speaker mean raw move (n>=8):")
gm = sig.groupby("speaker")["d_rate_bp_from_baseline"].agg(["size", "mean", "std", "count"])
gm["se"] = gm["std"] / np.sqrt(gm["count"])
print(gm[gm["size"] >= 8].sort_values("mean").to_string())

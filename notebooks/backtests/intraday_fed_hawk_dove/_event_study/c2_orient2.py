import sys
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")
import numpy as np
import pandas as pd

pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 100)

base = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study"
ev = pd.read_parquet(base + r"\event_paths.parquet")
pl = pd.read_parquet(base + r"\placebo_paths.parquet")

for nm, df in (("REAL", ev), ("PLACEBO", pl)):
    print("=" * 90)
    print(nm)
    s = df[df["offset_min"] == 240]
    print("rows at +240:", len(s), " unique events:", s["event_id"].nunique())
    print("\ncoverage of signed_d_bp at +240 by rank (needs price at +240 AND baseline AND signed):")
    g = s.groupby("contract_rank").agg(
        n_rows=("event_id", "size"),
        n_price=("price", lambda x: x.notna().sum()),
        n_dbp=("d_rate_bp_from_baseline", lambda x: x.notna().sum()),
        n_signed=("signed_d_bp", lambda x: x.notna().sum()),
        sd_signed=("signed_d_bp", "std"),
        mean_signed=("signed_d_bp", "mean"),
    )
    print(g.to_string())

print("=" * 90)
print("REAL signed-sample sizes at +240 (rank 3), various cuts")
s = ev[(ev["offset_min"] == 240) & (ev["contract_rank"] == 3)]
for label, mask in [
    ("all rows", pd.Series(True, index=s.index)),
    ("signed", s["stance_sign"] != 0),
    ("signed & priced", (s["stance_sign"] != 0) & s["signed_d_bp"].notna()),
    ("signed & priced & non-overlap", (s["stance_sign"] != 0) & s["signed_d_bp"].notna() & (~s["is_overlapping"])),
    ("signed & priced & |bucket|>=1", (s["stance_sign"] != 0) & s["signed_d_bp"].notna() & (s["bucket"].abs() >= 1)),
    ("signed & priced & nonovl & |bucket|>=1", (s["stance_sign"] != 0) & s["signed_d_bp"].notna() & (~s["is_overlapping"]) & (s["bucket"].abs() >= 1)),
]:
    sub = s[mask]
    print(f"  {label:42s} n={len(sub):5d}  hawk={int((sub['stance_sign']>0).sum()):4d} dove={int((sub['stance_sign']<0).sum()):4d} days={sub['date'].nunique():4d}")

print("\nPLACEBO signed-sample sizes at +240 rank 3")
sp = pl[(pl["offset_min"] == 240) & (pl["contract_rank"] == 3)]
for label, mask in [
    ("signed & priced", (sp["stance_sign"] != 0) & sp["signed_d_bp"].notna()),
    ("signed & priced & non-overlap-parent", (sp["stance_sign"] != 0) & sp["signed_d_bp"].notna() & (~sp["is_overlapping"])),
]:
    sub = sp[mask]
    print(f"  {label:42s} n={len(sub):5d}  hawk={int((sub['stance_sign']>0).sum()):4d} dove={int((sub['stance_sign']<0).sum()):4d} days={sub['date'].nunique():4d}")

print("\nis_overlapping on placebo: does it carry the parent's flag?")
print(sp["is_overlapping"].value_counts().to_string())

# symbol / rank mapping sanity: what is rank 1 vs rank 5 in months to expiry?
print("\nrank -> symbol counts (real, offset 240)")
print(pd.crosstab(ev.loc[ev.offset_min == 240, "contract_rank"], ev.loc[ev.offset_min == 240, "symbol"]).to_string())

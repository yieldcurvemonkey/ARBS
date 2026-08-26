"""Diagnostics for chart 2: the unsigned drift gap delta, and its candidate origins."""
import sys
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")
import numpy as np
import pandas as pd

pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 100)

base = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study"
ev = pd.read_parquet(base + r"\event_paths.parquet")
pl = pd.read_parquet(base + r"\placebo_paths.parquet")


def cut(df, off):
    return df[(df["offset_min"] == off) & df["signed_d_bp"].notna() & (df["stance_sign"] != 0)].copy()


print("=" * 118)
print("DIAGNOSTIC 1 -- delta = (speech-day unsigned drift) - (quiet-day unsigned drift), equal-arm weighted")
print("  d_rate_bp_from_baseline is the UNSIGNED rate change from the -60 baseline (bp).")
print("  equal-arm unsigned drift U = 0.5*mean(hawk-arm d_rate) + 0.5*mean(dove-arm d_rate)")
print("=" * 118)
for off in (30, 240):
    rows = []
    for r in range(1, 6):
        e = cut(ev, off)
        p = cut(pl, off)
        e = e[e.contract_rank == r]
        p = p[p.contract_rank == r]
        Uh_r = e.loc[e.stance_sign > 0, "d_rate_bp_from_baseline"].mean()
        Ud_r = e.loc[e.stance_sign < 0, "d_rate_bp_from_baseline"].mean()
        Uh_p = p.loc[p.stance_sign > 0, "d_rate_bp_from_baseline"].mean()
        Ud_p = p.loc[p.stance_sign < 0, "d_rate_bp_from_baseline"].mean()
        U_r = 0.5 * (Uh_r + Ud_r)
        U_p = 0.5 * (Uh_p + Ud_p)
        # arm excesses in SIGNED space
        hx = e.loc[e.stance_sign > 0, "signed_d_bp"].mean() - p.loc[p.stance_sign > 0, "signed_d_bp"].mean()
        dx = e.loc[e.stance_sign < 0, "signed_d_bp"].mean() - p.loc[p.stance_sign < 0, "signed_d_bp"].mean()
        rows.append(dict(rank=r, U_real=U_r, U_plac=U_p, delta=U_r - U_p,
                         hawk_excess=hx, dove_excess=dx,
                         half_arm_gap=0.5 * (hx - dx), DiD=0.5 * (hx + dx)))
    d = pd.DataFrame(rows).set_index("rank")
    print(f"\noffset +{off}")
    print(d.round(4).to_string())
    chk = np.abs(d["delta"] - d["half_arm_gap"]).max()
    print(f"  IDENTITY CHECK  max |delta - 0.5*(hawk_excess - dove_excess)| = {chk:.2e}  "
          f"({'PASS' if chk < 1e-9 else 'FAIL'})")

print()
print("=" * 118)
print("DIAGNOSTIC 2 -- days_to_fomc composition, real vs placebo (FOMC-cycle position)")
print("=" * 118)
e = cut(ev, 240).drop_duplicates("event_id")
p = cut(pl, 240).drop_duplicates("event_id")
print(f"real n={len(e)}  placebo n={len(p)}")
bins = [-99, -21, -14, -7, -1, 0, 7, 14, 21, 99]
print("\ndays_to_fomc distribution (share %):")
er = pd.cut(e["days_to_fomc"], bins).value_counts(normalize=True).sort_index() * 100
pr = pd.cut(p["days_to_fomc"], bins).value_counts(normalize=True).sort_index() * 100
print(pd.DataFrame({"real_%": er.round(1), "placebo_%": pr.round(1), "gap_pp": (er - pr).round(1)}).to_string())
print(f"\nmean days_to_fomc  real {e['days_to_fomc'].mean():.2f}  placebo {p['days_to_fomc'].mean():.2f}")
print(f"median |days_to_fomc| real {e['days_to_fomc'].abs().median():.1f}  placebo {p['days_to_fomc'].abs().median():.1f}")

print()
print("=" * 118)
print("DIAGNOSTIC 3 -- macro-calendar imbalance, and delta with CPI/NFP days dropped from BOTH books")
print("=" * 118)
print(f"is_cpi_day  real {e['is_cpi_day'].mean()*100:.1f}%  placebo {p['is_cpi_day'].mean()*100:.1f}%")
print(f"is_nfp_day  real {e['is_nfp_day'].mean()*100:.1f}%  placebo {p['is_nfp_day'].mean()*100:.1f}%")

for off in (30, 240):
    rows = []
    for r in range(1, 6):
        e2 = cut(ev, off)
        p2 = cut(pl, off)
        e2 = e2[(e2.contract_rank == r) & ~e2.is_cpi_day & ~e2.is_nfp_day]
        p2 = p2[(p2.contract_rank == r) & ~p2.is_cpi_day & ~p2.is_nfp_day]
        Uh_r = e2.loc[e2.stance_sign > 0, "d_rate_bp_from_baseline"].mean()
        Ud_r = e2.loc[e2.stance_sign < 0, "d_rate_bp_from_baseline"].mean()
        Uh_p = p2.loc[p2.stance_sign > 0, "d_rate_bp_from_baseline"].mean()
        Ud_p = p2.loc[p2.stance_sign < 0, "d_rate_bp_from_baseline"].mean()
        hx = e2.loc[e2.stance_sign > 0, "signed_d_bp"].mean() - p2.loc[p2.stance_sign > 0, "signed_d_bp"].mean()
        dx = e2.loc[e2.stance_sign < 0, "signed_d_bp"].mean() - p2.loc[p2.stance_sign < 0, "signed_d_bp"].mean()
        rows.append(dict(rank=r, n_real=len(e2), n_plac=len(p2),
                         delta=0.5 * (Uh_r + Ud_r) - 0.5 * (Uh_p + Ud_p),
                         pooled_excess=e2["signed_d_bp"].mean() - p2["signed_d_bp"].mean(),
                         DiD=0.5 * (hx + dx)))
    print(f"\noffset +{off}  (CPI and NFP days dropped from both books)")
    print(pd.DataFrame(rows).set_index("rank").round(4).to_string())

print()
print("=" * 118)
print("DIAGNOSTIC 4 -- does the rank ladder ever hold an ACCRUING contract? (roll convention)")
print("=" * 118)
s = ev[(ev.offset_min == 240) & (ev.contract_rank == 1)]
g = s.groupby("symbol")["date"].agg(["min", "max", "size"])
print(g.to_string())
print("\n(if each rank-1 symbol's window ENDS at its own IMM date, rank 1 is a fully-forward quarter)")

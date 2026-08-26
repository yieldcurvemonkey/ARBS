"""Why does the book print t=2.00 when the event study prints t=0.99 on the SAME edge?

_final_report.txt  FED: 492 trades, avg +0.3608 bp/trade, std 3.9981, t_stat 2.0015
event study        signed composite at +240: +0.3614 bp, day-clustered t 0.994, n=184

The point estimates agree to 4 decimal places. So the book and the event study are
measuring the same thing and disagreeing only about its uncertainty. Decompose the gap.
"""
import re

import numpy as np
import pandas as pd

BT = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove"


def load(fn):
    df = pd.read_csv(f"{BT}/{fn}")
    bpv = df["source_query"].str.extract(r"'bpv':\s*(-?\d+)")[0].astype(float).abs()
    df["pnl_bp"] = df["gross_realized_pnl"] / bpv
    df["day"] = pd.to_datetime(df["opened_at"], utc=True, format="mixed").dt.tz_convert(
        "America/New_York").dt.date
    return df


def clustered_t(x, groups):
    """CR1 day-clustered t on the mean. Reduces to the ordinary t when every
    cluster is a singleton -- verified below against a known answer."""
    x = np.asarray(x, float)
    n, mu = len(x), x.mean()
    g = pd.Series(x).groupby(np.asarray(groups))
    G = g.ngroups
    # var of the mean = sum_c (sum_i resid_i)^2 / n^2, with the CR1 finite-sample scale
    ssc = float(((g.sum() - g.size() * mu) ** 2).sum())
    scale = (G / max(G - 1, 1)) * ((n - 1) / max(n - 1, 1))
    var = scale * ssc / n ** 2
    return mu, np.sqrt(var), (mu / np.sqrt(var) if var > 0 else np.nan), G


# --- known-answer check: singleton clusters must reproduce the ordinary t ---
rng = np.random.default_rng(0)
z = rng.normal(size=200)
_, se_c, t_c, _ = clustered_t(z, np.arange(200))
t_plain = z.mean() / (z.std(ddof=1) / np.sqrt(200))
print(f"[check] singleton-cluster t {t_c:.6f} vs ordinary t {t_plain:.6f} "
      f"-> {'OK' if abs(t_c - t_plain) < 1e-6 else 'MISMATCH'}")

print()
for fn in ("sig_closed.csv", "nav_closed.csv"):
    d = load(fn)
    x = d["pnl_bp"].values
    n = len(x)
    mu = x.mean()
    t_naive = mu / (x.std(ddof=1) / np.sqrt(n))
    mu_c, se_c, t_c, G = clustered_t(x, d["day"].values)

    # how much of the sample is one-trade-per-day vs stacked?
    per_day = d.groupby("day").size()

    print(f"=== {fn} ===")
    print(f"  trades {n} on {G} distinct days  (max {per_day.max()}/day, "
          f"{(per_day > 1).sum()} days carry >1)")
    print(f"  mean edge            {mu:+.4f} bp/trade")
    print(f"  t, treating trades as independent : {t_naive:+.3f}")
    print(f"  t, day-clustered (CR1)            : {t_c:+.3f}")
    print(f"  SE inflation from clustering      : {se_c / (x.std(ddof=1)/np.sqrt(n)):.2f}x")

    # day-level: collapse to one observation per day, the honest unit
    daymean = d.groupby("day")["pnl_bp"].mean()
    t_day = daymean.mean() / (daymean.std(ddof=1) / np.sqrt(len(daymean)))
    print(f"  t on DAY MEANS (n={len(daymean)})            : {t_day:+.3f}")
    print()

# --- decompose the published FED book's t=2.00 ---
print("=== decomposing _final_report FED: 492 trades, avg 0.3608, std 3.9981 ===")
avg, sd, n_bt = 0.3608, 3.9981, 492
print(f"  published t (unclustered, n=492)        : {avg/(sd/np.sqrt(n_bt)):+.3f}")
for n_eff in (340, 184):
    print(f"  same edge/vol at n={n_eff:<3d} (non-overlap)     : "
          f"{avg/(sd/np.sqrt(n_eff)):+.3f}")
print(f"  event study measured (n=184, clustered) : +0.994")
print()
print("  => the edge is the SAME (+0.36bp). The book's t=2.00 buys its significance")
print("     from counting 492 overlapping trades as independent observations.")

"""Known-answer + mutation tests for MY OWN skeptic estimators, before I use them
to judge someone else's. A checking tool that is itself wrong reports success and
hides the thing it was built to find.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
import statsmodels.api as sm

HERE = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")
OK = True


def chk(c, m):
    global OK
    print(("  OK   " if c else "  FAIL ") + m)
    OK = OK and bool(c)


def t_cluster(v, day):
    v = np.asarray(v, float)
    r = sm.OLS(v, np.ones((v.size, 1))).fit(
        cov_type="cluster", cov_kwds={"groups": pd.factorize(np.asarray(day))[0]})
    return float(r.tvalues[0])


rng = np.random.default_rng(11)

# 1. singleton clusters must reproduce the ordinary one-sample t exactly
x = rng.normal(size=60) * 2 + 0.8
want = x.mean() / (x.std(ddof=1) / np.sqrt(60))
got = t_cluster(x, np.arange(60))
chk(abs(got - want) / abs(want) < 0.02, f"singleton clusters ~= iid t ({got:.4f} vs {want:.4f})")

# 2. clusters of IDENTICAL values: clustered t must be far smaller than the naive t
gm = rng.normal(size=15) * 1.5 + 0.6
xx = np.repeat(gm, 8)
cc = np.repeat(np.arange(15), 8)
t_naive = xx.mean() / (xx.std(ddof=1) / np.sqrt(120))
t_clu = t_cluster(xx, cc)
t_dm = gm.mean() / (gm.std(ddof=1) / np.sqrt(15))
chk(abs(t_clu - t_dm) / abs(t_dm) < 0.15, f"duplicated-within-cluster t ~= day-mean t ({t_clu:.4f} vs {t_dm:.4f})")
chk(abs(t_naive) > 2 * abs(t_clu), f"MUTATION: naive t {t_naive:.3f} is >2x clustered {t_clu:.3f} - clustering bites")

# 3. POWER: inject a real +0.5bp effect into the actual headline book and confirm detection
ev = pd.read_parquet(HERE / "event_paths.parquet")
ev["day"] = pd.to_datetime(ev["date"].astype(str))
h = ev[(ev["contract_rank"] == 3) & (ev["stance_sign"] != 0) & (~ev["is_overlapping"])
       & (ev["offset_min"] == 240)].dropna(subset=["signed_d_bp"])
t0 = t_cluster(h["signed_d_bp"], h["day"])
t1 = t_cluster(h["signed_d_bp"] + 0.5, h["day"])
t2 = t_cluster(h["signed_d_bp"] + 1.0, h["day"])
print(f"  observed t {t0:+.3f}; +0.5bp injected -> t {t1:+.3f}; +1.0bp injected -> t {t2:+.3f}")
chk(t1 > 2.0, f"injecting a real +0.5bp reaction into the headline book prints t={t1:.2f} > 2 - the test has power")

# 4. TRIM must not be able to manufacture a null from a genuine broad effect
hh = h.copy()
hh["signed_d_bp"] = hh["signed_d_bp"] + 1.0
dm = hh.groupby("day")["signed_d_bp"].mean()
k = max(1, int(np.ceil(0.01 * dm.size)))
w = dm.abs().sort_values(ascending=False).head(k)
kept = hh[~hh["day"].isin(w.index)]
t_tr = t_cluster(kept["signed_d_bp"], kept["day"])
print(f"  +1.0bp broad effect, then top-1%-of-days trim -> t {t_tr:+.3f} (mean {kept['signed_d_bp'].mean():+.3f}bp)")
chk(t_tr > 2.0, "MUTATION: a genuine BROAD effect SURVIVES my 1% day trim - so the trim "
                "collapsing the real headline is evidence about the data, not an artefact of the trim")

# 5. arithmetic of the tail claim
tot = h["signed_d_bp"].sum()
top3 = h["signed_d_bp"].nlargest(3).sum()
print(f"  headline sum of signed moves {tot:.2f}bp; largest 3 events {top3:.2f}bp = {100*top3/tot:.1f}% of the total")
chk(top3 / tot > 0.9, "the top 3 events carry >90% of the entire summed signed move")

print("SELFTEST:", "PASS" if OK else "FAIL")
sys.exit(0 if OK else 1)

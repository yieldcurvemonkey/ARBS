"""Shared estimators for the Fedspeak event-time fan (Chart 1).

Everything that produces a number for the chart or the report lives here, so the
figure and the statistics cannot drift apart.  Every estimator is day-clustered:
two speeches on one day are not two independent observations of the market, and
the placebo re-uses days heavily (2,931 pseudo-events on 376 days, up to 28 on a
single day), so a naive SE would shrink the null band by roughly sqrt(8).

Run this file directly to execute the known-answer tests.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")

OFFSETS = [-120, -90, -60, -45, -30, -20, -15, -10, -5, 0,
           5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 300]
PRE_OFFSETS = [o for o in OFFSETS if -120 <= o <= -5]
RANK = 3
BASELINE = -60

# hawk = warm/red, dove = cool/blue, placebo = recessive grey.
# The two categorical hues pass the dataviz validator on the all-pairs list
# (CVD dE 23.2 protan / 31.9 tritan, normal-vision dE 31.7, contrast >= 3:1 on
# a white surface).  Grey is a recessive reference series, not a peer slot, and
# carries a dashed stroke + a direct label so identity is never colour-alone.
C_HAWK = "#c62f2e"
C_DOVE = "#1f66c4"
C_PLACEBO = "#8a8f98"
C_INK = "#16181d"
C_INK2 = "#55595f"
C_GRID = "#dcdee2"


# --------------------------------------------------------------------------
# cluster-robust estimators
# --------------------------------------------------------------------------
def cluster_mean_se(values, clusters):
    """Mean of `values` with a cluster-robust SE (clusters = day labels).

    Var(xbar) = G/(G-1) * sum_g (sum_{i in g} (x_i - xbar))^2 / n^2
    which is the OLS-on-a-constant CR1 variance.  Two known answers pin it:
    singleton clusters reproduce the ordinary s/sqrt(n) exactly, and clusters of
    identical values reproduce the SE of the mean of the cluster means.
    """
    v = np.asarray(values, dtype=float)
    c = np.asarray(clusters)
    ok = np.isfinite(v)
    v, c = v[ok], c[ok]
    n = v.size
    if n == 0:
        return dict(mean=np.nan, se=np.nan, t=np.nan, n=0, n_clusters=0)
    xbar = float(v.mean())
    dev = v - xbar
    tg = pd.Series(dev).groupby(pd.Series(c).values).sum().to_numpy()
    g = tg.size
    if g < 2:
        return dict(mean=xbar, se=np.nan, t=np.nan, n=int(n), n_clusters=int(g))
    var = (g / (g - 1.0)) * float((tg ** 2).sum()) / (n ** 2)
    se = float(np.sqrt(var))
    return dict(mean=xbar, se=se, t=(xbar / se if se > 0 else np.nan),
                n=int(n), n_clusters=int(g))


def cluster_ols(y, X, clusters, names=None):
    """OLS with CR1 day-clustered covariance.  X must include its own intercept."""
    y = np.asarray(y, dtype=float)
    X = np.asarray(X, dtype=float)
    c = np.asarray(clusters)
    ok = np.isfinite(y) & np.isfinite(X).all(axis=1)
    y, X, c = y[ok], X[ok], c[ok]
    n, k = X.shape
    xtx_inv = np.linalg.pinv(X.T @ X)
    beta = xtx_inv @ (X.T @ y)
    resid = y - X @ beta
    uniq = pd.unique(c)
    g = len(uniq)
    meat = np.zeros((k, k))
    idx = pd.Series(np.arange(n)).groupby(pd.Series(c).values).apply(list)
    for rows in idx:
        rows = np.asarray(rows)
        s = X[rows].T @ resid[rows]
        meat += np.outer(s, s)
    scale = (g / (g - 1.0)) * ((n - 1.0) / (n - k))
    cov = xtx_inv @ (scale * meat) @ xtx_inv
    se = np.sqrt(np.diag(cov))
    names = names or [f"b{i}" for i in range(k)]
    return {nm: dict(coef=float(beta[i]), se=float(se[i]),
                     t=float(beta[i] / se[i]) if se[i] > 0 else np.nan)
            for i, nm in enumerate(names)} | dict(n=int(n), n_clusters=int(g))


def cluster_bootstrap_ratio(num_vals, den_vals, clusters, n_draw=2000, seed=20260825):
    """CI for mean(num)/mean(den) by resampling whole DAYS with replacement.

    num_vals/den_vals are paired per event (same event set), so the ratio's
    numerator and denominator always come from the same events.
    """
    num = np.asarray(num_vals, dtype=float)
    den = np.asarray(den_vals, dtype=float)
    c = np.asarray(clusters)
    ok = np.isfinite(num) & np.isfinite(den)
    num, den, c = num[ok], den[ok], c[ok]
    if num.size == 0:
        return dict(point=np.nan, lo=np.nan, hi=np.nan, n=0)
    point = float(num.mean() / den.mean()) if den.mean() != 0 else np.nan
    days = pd.unique(c)
    pos = {d: np.where(c == d)[0] for d in days}
    rng = np.random.default_rng(seed)
    out = np.empty(n_draw)
    for b in range(n_draw):
        pick = rng.choice(len(days), size=len(days), replace=True)
        rows = np.concatenate([pos[days[j]] for j in pick])
        dm = den[rows].mean()
        out[b] = num[rows].mean() / dm if dm != 0 else np.nan
    out = out[np.isfinite(out)]
    return dict(point=point, lo=float(np.percentile(out, 2.5)),
                hi=float(np.percentile(out, 97.5)), n=int(num.size),
                n_clusters=int(len(days)), n_ok_draws=int(out.size))


# --------------------------------------------------------------------------
# panel helpers
# --------------------------------------------------------------------------
def load_rank3():
    ev = pd.read_parquet(HERE / "event_paths.parquet")
    pl = pd.read_parquet(HERE / "placebo_paths.parquet")
    ev = ev[ev["contract_rank"] == RANK].copy()
    pl = pl[pl["contract_rank"] == RANK].copy()
    return ev, pl


def wide(d, value="d_rate_bp_from_baseline"):
    """One row per signed event, one column per offset, plus the event meta."""
    d = d[d["stance_sign"] != 0]
    piv = d.pivot_table(index="event_id", columns="offset_min", values=value, dropna=False)
    piv = piv.reindex(columns=OFFSETS)
    meta = d.drop_duplicates("event_id").set_index("event_id").loc[piv.index]
    return piv, meta


def arm_paths(piv, meta, sign):
    """Per-offset mean + day-clustered SE for one stance arm."""
    sel = meta["stance_sign"] == sign
    rows = []
    for o in OFFSETS:
        r = cluster_mean_se(piv.loc[sel, o].to_numpy(), meta.loc[sel, "date"].to_numpy())
        rows.append(dict(offset_min=o, **r))
    return pd.DataFrame(rows).set_index("offset_min")


def signed_path(piv, meta):
    """Per-offset mean signed move (hawk +d_rate, dove -d_rate) + clustered SE."""
    sgn = meta["stance_sign"].to_numpy()[:, None]
    s = piv.to_numpy() * sgn
    rows = []
    for j, o in enumerate(OFFSETS):
        r = cluster_mean_se(s[:, j], meta["date"].to_numpy())
        rows.append(dict(offset_min=o, **r))
    return pd.DataFrame(rows).set_index("offset_min")


# --------------------------------------------------------------------------
# known-answer tests -- a checking tool that is itself wrong hides the thing it
# was built to find, so both estimators are pinned against answers computed a
# different way, and each test is mutated to prove it is not vacuous.
# --------------------------------------------------------------------------
def _selftest():
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(("  OK   " if cond else "  FAIL ") + msg)
        ok = ok and bool(cond)

    rng = np.random.default_rng(7)

    # 1. singleton clusters -> ordinary SE of the mean, exactly
    x = rng.normal(size=40) * 3 + 1.5
    got = cluster_mean_se(x, np.arange(40))
    want = x.std(ddof=1) / np.sqrt(40)
    chk(np.isclose(got["se"], want), f"singleton clusters == s/sqrt(n)  ({got['se']:.9f} vs {want:.9f})")

    # 2. clusters of identical values -> SE of the mean of the cluster means
    gm = rng.normal(size=12) * 2
    xx = np.repeat(gm, 5)
    cc = np.repeat(np.arange(12), 5)
    got = cluster_mean_se(xx, cc)
    want = gm.std(ddof=1) / np.sqrt(12)
    chk(np.isclose(got["se"], want), f"duplicated-within-cluster == SE of cluster means  ({got['se']:.9f} vs {want:.9f})")

    # 2b. mutation: the naive (unclustered) SE must NOT match, or test 2 is vacuous
    naive = xx.std(ddof=1) / np.sqrt(60)
    chk(not np.isclose(naive, want, rtol=0.05),
        f"mutation: unclustered SE {naive:.6f} differs from clustered {want:.6f} "
        f"(ratio {want / naive:.2f}x) - the test bites")

    # 3. cluster_ols vs statsmodels cluster covariance
    try:
        import statsmodels.api as sm
        n = 300
        cl = rng.integers(0, 40, size=n)
        d = rng.integers(0, 2, size=n).astype(float)
        yy = 2.0 + 1.3 * d + rng.normal(size=n) + rng.normal(size=40)[cl]
        Xm = np.column_stack([np.ones(n), d])
        mine = cluster_ols(yy, Xm, cl, names=["const", "hawk"])
        ref = sm.OLS(yy, Xm).fit(cov_type="cluster", cov_kwds={"groups": cl})
        chk(np.isclose(mine["hawk"]["coef"], ref.params[1]) and
            np.isclose(mine["hawk"]["se"], ref.bse[1], rtol=1e-8),
            f"cluster_ols matches statsmodels  (coef {mine['hawk']['coef']:.9f} vs {ref.params[1]:.9f}; "
            f"se {mine['hawk']['se']:.9f} vs {ref.bse[1]:.9f})")
        chk(not np.isclose(mine["hawk"]["se"], sm.OLS(yy, Xm).fit().bse[1], rtol=0.02),
            "mutation: the homoskedastic SE differs, so the cluster path is really exercised")
    except ImportError:
        chk(False, "statsmodels available for the cross-check")

    # 4. bootstrap ratio recovers a known ratio
    n = 400
    cl = rng.integers(0, 50, size=n)
    den = rng.normal(10, 1, size=n)
    num = 0.4 * den + rng.normal(0, 0.05, size=n)
    bs = cluster_bootstrap_ratio(num, den, cl, n_draw=400, seed=1)
    chk(abs(bs["point"] - 0.4) < 0.02 and bs["lo"] < 0.4 < bs["hi"],
        f"bootstrap ratio brackets the true 0.40  (point {bs['point']:.4f}, "
        f"CI [{bs['lo']:.4f}, {bs['hi']:.4f}])")

    print("SELFTEST:", "PASS" if ok else "FAIL")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if _selftest() else 1)

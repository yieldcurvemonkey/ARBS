"""AUDIT probe 3 for F7:
  E1  non-overlap discard, done CORRECTLY (probe2's C1 never fired the lock)
  E2  pond estimator: gate's 20-sample median vs the 300+ samples available
  E3  independent mark: traded package leg rates from the Part 43 tape vs the Citi grid
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import importlib.util
import json
import pathlib

import numpy as np
import pandas as pd

_REPO = pathlib.Path(__file__).resolve().parents[1]
OUT = _REPO / "notebooks" / "data" / "citivelo_rv"
spec = importlib.util.spec_from_file_location("g", _REPO / "scripts" / "s3_f7_gate.py")
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
pd.set_option("display.width", 300)
pd.set_option("display.max_columns", 60)


def episodes_marked(x, z, ok, h, lag=1):
    """Every eligible entry, each tagged with whether the gate's lock WOULD have dropped it."""
    idx, n = x.index, len(x)
    xv, zv = x.to_numpy(), z.to_numpy()
    okv = ok.reindex(idx).fillna(False).to_numpy()
    rows, busy = [], -1
    for i in range(g.Z_WIN, n - lag - h):
        if not okv[i]:
            continue
        side = -np.sign(zv[i])
        if side == 0:
            continue
        blocked = i <= busy
        if not blocked:
            busy = i + lag + h
        e, xo = xv[i + lag], xv[i + lag + h]
        rows.append({"i": i, "date": idx[i], "z": zv[i], "blocked": blocked,
                     "gross_bp": float(side * (xo - e)),
                     "abs_move_bp": float(abs(xo - e))})
    return pd.DataFrame(rows)


par = pd.read_parquet(OUT / "par_grid_USD_SOFR.parquet")
par.index = pd.to_datetime(par.index)
pkg = pd.read_parquet(OUT / "f7_packages.parquet")
pkg["file_date"] = pd.to_datetime(pkg["file_date"])
uni = json.loads((OUT / "f7_universe.json").read_text())["universe"]
dg_all = pd.read_parquet(OUT / "f7_extract_diag.parquet")
common = par.index.intersection(pd.DatetimeIndex(pd.to_datetime(dg_all["file_date"])))

P = {}
for sig in uni:
    x = g.structure_series(par, sig).reindex(common).dropna()
    flow = (pkg[pkg["signature"] == sig].groupby("file_date").size()
            .reindex(x.index, fill_value=0).astype(float))
    z = g.zscore(x, g.Z_WIN)
    P[sig] = dict(x=x, z=z, shock=g.shock_flags(flow, g.FLOW_WIN, g.SHOCK_Q),
                  persistent=(z.abs() >= g.Z_ENTRY) & (np.sign(z) == np.sign(z.shift(1)))
                  & (z.shift(1).abs() >= g.Z_ENTRY),
                  rt=g.round_trips(sig))

print("=== E1 NON-OVERLAP DISCARD (lock actually applied) ===")
rows = []
for sig in uni:
    for h in g.HORIZONS:
        for bk, m in [("all", P[sig]["persistent"]),
                      ("shock", P[sig]["persistent"] & P[sig]["shock"])]:
            f = episodes_marked(P[sig]["x"], P[sig]["z"], m, h)
            k, dp = f[~f["blocked"]], f[f["blocked"]]
            rows.append({"sig": sig, "h": h, "book": bk, "elig": len(f), "kept": len(k),
                         "drop_pct": round(100 * len(dp) / max(1, len(f)), 1),
                         "absz_kept": round(k["z"].abs().median(), 3),
                         "absz_drop": round(dp["z"].abs().median(), 3) if len(dp) else np.nan,
                         "gross_kept": round(k["gross_bp"].median(), 3),
                         "gross_drop": round(dp["gross_bp"].median(), 3) if len(dp) else np.nan,
                         "amove_kept": round(k["abs_move_bp"].median(), 3),
                         "amove_drop": round(dp["abs_move_bp"].median(), 3) if len(dp) else np.nan})
e1 = pd.DataFrame(rows)
print(e1[e1["h"] == 21].to_string(index=False))
d = e1[(e1["h"] == 21) & (e1["book"] == "all")]
print(f"\nh=21 'all': median drop {d['drop_pct'].median():.1f}% of eligible entries.")
print(f"  |z| kept vs dropped   : {d['absz_kept'].median():.3f} vs {d['absz_drop'].median():.3f}")
print(f"  |move| kept vs dropped: {d['amove_kept'].median():.3f} vs {d['amove_drop'].median():.3f}")
print(f"  gross  kept vs dropped: {d['gross_kept'].median():.3f} vs {d['gross_drop'].median():.3f}")

print("\n=== E2 POND ESTIMATOR: gate (non-overlap, n~20) vs all eligible vs unconditional ===")
rows = []
gate = pd.read_parquet(OUT / "f7_gate.parquet")
for sig in uni:
    rt = P[sig]["rt"]["rt_cm2"]
    for h in g.HORIZONS:
        f = episodes_marked(P[sig]["x"], P[sig]["z"], P[sig]["persistent"], h)
        gv = gate[(gate.signature == sig) & (gate.h == h) & (gate.book == "all")].iloc[0]
        mv = (P[sig]["x"].shift(-h) - P[sig]["x"]).dropna().abs()
        # bootstrap the gate's own n-sample median to show its sampling error
        rng = np.random.default_rng(1)
        bs = [np.median(rng.choice(f["abs_move_bp"].to_numpy(), int(gv["n"]), replace=True))
              for _ in range(2000)]
        rows.append({"sig": sig, "h": h, "gate_n": int(gv["n"]),
                     "gate_pond": round(gv["abs_move_med"] / rt, 3),
                     "elig_n": len(f), "elig_pond": round(f["abs_move_bp"].median() / rt, 3),
                     "uncond_n": len(mv), "uncond_pond": round(mv.median() / rt, 3),
                     "boot_p05": round(np.percentile(bs, 5) / rt, 3),
                     "boot_p95": round(np.percentile(bs, 95) / rt, 3)})
e2 = pd.DataFrame(rows)
print(e2.to_string(index=False))
print("\nsignatures whose pond crosses the 1.0x line depending on the estimator:")
fl = e2[e2["sig"].str.count("-") == 2]
print(fl[(fl[["gate_pond", "elig_pond", "uncond_pond"]].min(axis=1) < 1.0)
         & (fl[["gate_pond", "elig_pond", "uncond_pond"]].max(axis=1) >= 1.0)].to_string(index=False))

print("\n=== E3 INDEPENDENT MARK: traded package rates vs the Citi grid ===")
for sig in ["5-10-30", "2-5-10", "5-7-10", "10-15-30", "10-30"]:
    sub = pkg[pkg["signature"] == sig].copy()
    t = [int(v) for v in sig.split("-")]
    w = g.weights(sig)
    R = sub["rates"].str.split(",", expand=True).astype(float)
    if R.shape[1] != len(t):
        print(f"  {sig}: unexpected rate columns {R.shape[1]}")
        continue
    traded = sum(w[t[j]] * R[j] for j in range(len(t))) * 100.0
    sub["traded_bp"] = traded.to_numpy()
    grid = g.structure_series(par, sig)
    sub["grid_bp"] = grid.reindex(sub["file_date"]).to_numpy()
    sub = sub.dropna(subset=["traded_bp", "grid_bp"])
    dev = sub["traded_bp"] - sub["grid_bp"]
    daily_grid_absd = grid.reindex(common).dropna().diff().abs().median()
    print(f"  {sig:<9} n={len(sub):6d}  traded-vs-grid dev: med {dev.median():+8.3f}bp  "
          f"|dev| med {dev.abs().median():7.3f}  p25/p75 {dev.quantile(.25):+.2f}/"
          f"{dev.quantile(.75):+.2f}   grid med|daily d| {daily_grid_absd:.3f}bp")
    # within-day dispersion of traded structure -- does the tape see moves the grid does not?
    wd = sub.groupby("file_date")["traded_bp"].agg(["median", "std", "count"])
    wd = wd[wd["count"] >= 5]
    print(f"            within-day sd of traded structure: median {wd['std'].median():.3f}bp "
          f"over {len(wd)} days; day-over-day change of the traded DAILY MEDIAN: "
          f"med|d| {wd['median'].diff().abs().median():.3f}bp")

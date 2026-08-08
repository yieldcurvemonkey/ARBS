"""AUDIT REFUTE: does re-admitting 2-5 to F7's universe change the VERDICT?

The claimed defect: s3_f7_universe.py:47 excludes 2-5 on the `z_vs_null >= 3.0` arm
even though 2-5 is enriched (1.09x, z=+2.1), not depleted. Claim reproduces; the
question is materiality. Rebuild the headline on the 11-signature universe
(registered 10 + 2-5) using the COMMITTED gate functions, unmodified.

Writes nothing to any committed artifact.
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
pd.set_option("display.width", 320)

par = pd.read_parquet(OUT / "par_grid_USD_SOFR.parquet")
par.index = pd.to_datetime(par.index)
pkg = pd.read_parquet(OUT / "f7_packages.parquet")
pkg["file_date"] = pd.to_datetime(pkg["file_date"])
dg = pd.read_parquet(OUT / "f7_extract_diag.parquet")
common = par.index.intersection(pd.DatetimeIndex(pd.to_datetime(dg["file_date"])))

UNI10 = json.loads((OUT / "f7_universe.json").read_text())["universe"]
UNI11 = UNI10 + ["2-5"]


def panel(sig):
    x = g.structure_series(par, sig).reindex(common).dropna()
    flow = (pkg[pkg["signature"] == sig].groupby("file_date").size()
            .reindex(x.index, fill_value=0).astype(float))
    z = g.zscore(x, g.Z_WIN)
    return dict(x=x, z=z, shock=g.shock_flags(flow, g.FLOW_WIN, g.SHOCK_Q),
                persistent=(z.abs() >= g.Z_ENTRY) & (np.sign(z) == np.sign(z.shift(1)))
                & (z.shift(1).abs() >= g.Z_ENTRY),
                rt=g.round_trips(sig))


P = {s: panel(s) for s in UNI11}

rows = []
for sig in UNI11:
    Q = P[sig]
    for h in g.HORIZONS:
        a = g.episodes(Q["x"], Q["z"], Q["persistent"] & Q["shock"], h)
        b = g.episodes(Q["x"], Q["z"], Q["persistent"] & ~Q["shock"], h)
        c = g.episodes(Q["x"], Q["z"], Q["persistent"], h)
        sa = g.stats(a, Q["rt"]["rt_cm2"])
        sb = g.stats(b, Q["rt"]["rt_cm2"])
        sc = g.stats(c, Q["rt"]["rt_cm2"])
        rows.append({
            "signature": sig, "h": h, "rt": Q["rt"]["rt_cm2"],
            "n_shock": sa.get("n", 0), "n_noshock": sb.get("n", 0),
            "gross_med_shock": sa.get("gross_med", np.nan),
            "gross_med_noshock": sb.get("gross_med", np.nan),
            "gross_med_all": sc.get("gross_med", np.nan),
            "gross_mean_shock": sa.get("gross_mean", np.nan),
            "net_mean_1x_shock": sa.get("net_mean_1x", np.nan),
            "net_med_1x_shock": sa.get("net_med_1x", np.nan),
            "sharpe_shock": sa.get("sharpe_per_trade", np.nan),
            "incr_vs_noshock": round(sa.get("gross_med", np.nan) - sb.get("gross_med", np.nan), 3),
            "incr_vs_all": round(sa.get("gross_med", np.nan) - sc.get("gross_med", np.nan), 3),
        })
R = pd.DataFrame(rows)
print("=== per-(signature,horizon) on the 11-signature universe (10 registered + 2-5) ===")
print(R.to_string(index=False))

print("\n=== HEADLINE: registered 10 vs 10+2-5, the median across signatures ===")
print(f"{'h':>3} {'median incr vs noshock':>26} {'median incr vs all':>22} "
      f"{'median shock net_mean@1x':>26} {'n_pos_incr':>12}")
summary = {}
for label, uni in (("REGISTERED(10)", UNI10), ("WITH 2-5 (11)", UNI11)):
    print(f"-- {label}")
    summary[label] = {}
    for h in g.HORIZONS:
        s = R[(R["h"] == h) & (R["signature"].isin(uni))]
        m_ns = float(s["incr_vs_noshock"].median())
        m_all = float(s["incr_vs_all"].median())
        m_net = float(s["net_mean_1x_shock"].median())
        npos = int((s["incr_vs_noshock"] > 0).sum())
        summary[label][h] = dict(incr_noshock=m_ns, incr_all=m_all, net=m_net,
                                 npos=npos, n=len(s))
        print(f"{h:>3} {m_ns:>+26.3f} {m_all:>+22.3f} {m_net:>+26.3f} "
              f"{npos:>7}/{len(s)}")

print("\n=== the cost bar the increment must clear to flip the verdict ===")
print("   spreads RT(cm2) = 1.8bp ; flies RT(cm2) = 3.6bp")
for h in g.HORIZONS:
    a = summary["REGISTERED(10)"][h]["incr_noshock"]
    b = summary["WITH 2-5 (11)"][h]["incr_noshock"]
    print(f"  h={h:>2}  median incr {a:+.3f} -> {b:+.3f}bp   "
          f"(needs >= +1.8bp to clear the cheapest round trip)   "
          f"shortfall {1.8 - b:+.3f}bp")

print("\n=== 2-5 alone at h=21: median vs mean, the statistic the gate reports ===")
Q = P["2-5"]
a = g.episodes(Q["x"], Q["z"], Q["persistent"] & Q["shock"], 21)
st = g.stats(a, Q["rt"]["rt_cm2"])
gv = a["gross_bp"].to_numpy()
t = gv.mean() / (gv.std(ddof=1) / np.sqrt(len(gv)))
print(json.dumps({k: (float(v) if isinstance(v, (int, float, np.floating)) else v)
                  for k, v in st.items()}, indent=2))
print(f"  t-stat on gross mean = {t:.3f}   (n={len(gv)})")
print(f"  net MEAN @1x = {gv.mean() - 1.8:+.3f}bp/trade   "
      f"net MEDIAN @1x = {np.median(gv) - 1.8:+.3f}bp/trade")
print(f"  net MEAN @2x = {gv.mean() - 3.6:+.3f}bp/trade")

print("\n=== how many of the 24 searched excluded cells are positive-net? "
      "(multiple-comparison context) ===")
EXCL = ["2-5", "5-7", "7-10", "7-30", "10-15-20", "15-20-30", "7-10-15", "2-5-30"]
hits = 0
tot = 0
for sig in EXCL:
    try:
        Q = panel(sig)
    except KeyError:
        continue
    line = [f"  {sig:<9} rt {Q['rt']['rt_cm2']:.1f}"]
    for h in g.HORIZONS:
        a = g.episodes(Q["x"], Q["z"], Q["persistent"] & Q["shock"], h)
        b = g.episodes(Q["x"], Q["z"], Q["persistent"] & ~Q["shock"], h)
        if not len(a):
            line.append(f" h{h}: n=0")
            continue
        tot += 1
        nm = a["gross_bp"].mean() - Q["rt"]["rt_cm2"]
        nmed = a["gross_bp"].median() - Q["rt"]["rt_cm2"]
        if nmed > 0:
            hits += 1
        inc = (a["gross_bp"].median() - b["gross_bp"].median()) if len(b) else np.nan
        line.append(f" h{h}: n{len(a):3d} netmed {nmed:+6.2f} netmean {nm:+6.2f} incr {inc:+6.2f}")
    print("".join(line))
print(f"  positive net-MEDIAN cells among excluded: {hits}/{tot}")

print("\n=== same statistic on the 10 REGISTERED signatures, for calibration ===")
hits2 = tot2 = 0
for sig in UNI10:
    Q = P[sig]
    for h in g.HORIZONS:
        a = g.episodes(Q["x"], Q["z"], Q["persistent"] & Q["shock"], h)
        if not len(a):
            continue
        tot2 += 1
        if a["gross_bp"].median() - Q["rt"]["rt_cm2"] > 0:
            hits2 += 1
print(f"  positive net-MEDIAN cells among registered: {hits2}/{tot2}")

"""AUDIT (verify claimed defect 'notional-arm'), robustness arm: the MAXIMALLY
INCLUSIVE flow.

The claim's 'loss' arm says genuine executions vanish because a leg fails a filter
(group falls below 2) or because the group stays above 3 legs. This builds the flow
that recovers all of them: for EVERY execution-timestamp group of ANY size, a
signature fires if its tenor set is a SUBSET of the group's surviving (bucketed +
spot) tenors. That is a strict superset of the as-built flow, so if the 2..3-leg
window were discarding the signal, this is where the signal would reappear.

Writes only to the scratchpad. Modifies nothing committed.
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import glob
import json
import pathlib
import sys
import time
from collections import Counter

import numpy as np
import pandas as pd

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import s3_f7_package_extract as e  # noqa: E402
import s3_f7_gate as G  # noqa: E402

SCRATCH = pathlib.Path(
    r"C:\Users\chris\AppData\Local\Temp\claude\C--Users-chris-clee-ARBS"
    r"\d0f44428-35f8-4f61-96a2-3a3318a94197\scratchpad")


def main() -> None:
    uni = json.loads((G.OUT / "f7_universe.json").read_text())["universe"]
    uni_sets = {s: frozenset(int(t) for t in s.split("-")) for s in uni}

    files = sorted(pathlib.Path(p) for p in
                   glob.glob(str(e.SDR_DIR / "*" / "*" / "*.parquet")))
    recs = []
    t0 = time.time()
    for i, fp in enumerate(files):
        raw = e.load_day(fp)
        cnt = Counter()
        if not raw.empty:
            passes = raw["_tenor"].notna() & raw["_spot"].fillna(False)
            d = raw.dropna(subset=["_ts"])
            for ts, g in d.groupby("_ts", sort=False):
                tens = set(int(t) for t in
                           g.loc[passes.reindex(g.index).fillna(False), "_tenor"])
                if len(tens) < 2:
                    continue
                for s, ss in uni_sets.items():
                    if ss <= tens:
                        cnt[s] += 1
        rec = {"file_date": pd.Timestamp(fp.stem)}
        rec.update({s: cnt.get(s, 0) for s in uni})
        recs.append(rec)
        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{len(files)} ({time.time()-t0:.0f}s)", flush=True)
    F = pd.DataFrame(recs).set_index("file_date")
    F.to_parquet(SCRATCH / "f7_flow_superset.parquet")

    ab = pd.read_parquet(G.OUT / "f7_packages.parquet")
    ab["file_date"] = pd.to_datetime(ab["file_date"])
    par = pd.read_parquet(G.OUT / "par_grid_USD_SOFR.parquet")
    par.index = pd.to_datetime(par.index)
    dg_all = pd.read_parquet(G.OUT / "f7_extract_diag.parquet")
    common = par.index.intersection(pd.DatetimeIndex(pd.to_datetime(dg_all["file_date"])))

    print("\n=== flow mass: as-built vs superset ===")
    rows = []
    for sig in uni:
        x = G.structure_series(par, sig).reindex(common).dropna()
        f_ab = (ab[ab["signature"] == sig].groupby("file_date").size()
                .reindex(x.index, fill_value=0).astype(float))
        f_su = F[sig].reindex(x.index, fill_value=0).astype(float)
        z = G.zscore(x, G.Z_WIN)
        persistent = (z.abs() >= G.Z_ENTRY) & (np.sign(z) == np.sign(z.shift(1))) \
            & (z.shift(1).abs() >= G.Z_ENTRY)
        rt = G.round_trips(sig)
        print(f"  {sig:<9} as-built total {f_ab.sum():>8.0f}  superset total "
              f"{f_su.sum():>8.0f}  ratio {f_su.sum()/max(1,f_ab.sum()):.2f}x")
        for name, f in (("asbuilt", f_ab), ("superset", f_su)):
            sh = G.shock_flags(f, G.FLOW_WIN, G.SHOCK_Q)
            for h in G.HORIZONS:
                a = G.episodes(x, z, persistent & sh, h)
                b = G.episodes(x, z, persistent & ~sh, h)
                sa, sb = G.stats(a, rt["rt_cm2"]), G.stats(b, rt["rt_cm2"])
                rows.append({"signature": sig, "h": h, "flow": name,
                             "n_shock": sa.get("n", 0),
                             "incr": sa.get("gross_med", np.nan) - sb.get("gross_med", np.nan),
                             "net_shock": sa.get("net_mean_1x", np.nan)})
    R = pd.DataFrame(rows)
    print("\n=== HEADLINE median increment across the 10 signatures ===")
    for h in G.HORIZONS:
        a = R[(R["h"] == h) & (R["flow"] == "asbuilt")]
        s = R[(R["h"] == h) & (R["flow"] == "superset")]
        print(f"  h={h:>2}bd   as-built {a['incr'].median():+.3f}bp "
              f"({int((a['incr']>0).sum())}/10 pos)   superset "
              f"{s['incr'].median():+.3f}bp ({int((s['incr']>0).sum())}/10 pos)   "
              f"best superset {s['incr'].max():+.3f}bp   "
              f"median superset shock net@1x {s['net_shock'].median():+.3f}bp")
    R.to_parquet(SCRATCH / "f7_superset_compare.parquet", index=False)


if __name__ == "__main__":
    main()

"""AUDIT (verify claimed defect 'notional-arm'), step 3: re-run F7's STEP (ii)
INCREMENT with the CORRECTED flow (intact-only packages) and compare against the
committed as-built numbers.

Everything except the flow series is held identical to s3_f7_gate: same par grid,
same 10-signature registered universe, same `common` index, same z-window, same
persistence rule, same episode constructor, same costs. Only shock_flags' input
changes, so any delta is attributable to the claimed defect alone.

Writes only to the scratchpad. Modifies nothing committed.
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import json
import pathlib
import sys

import numpy as np
import pandas as pd

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import s3_f7_gate as G  # noqa: E402  (main() is __main__-guarded)

SCRATCH = pathlib.Path(
    r"C:\Users\chris\AppData\Local\Temp\claude\C--Users-chris-clee-ARBS"
    r"\d0f44428-35f8-4f61-96a2-3a3318a94197\scratchpad")


def run(pkg: pd.DataFrame, par: pd.DataFrame, common: pd.DatetimeIndex,
        uni: list) -> tuple:
    rows, shockdays = [], {}
    for sig in uni:
        x = G.structure_series(par, sig).reindex(common).dropna()
        flow = (pkg[pkg["signature"] == sig].groupby("file_date").size()
                .reindex(x.index, fill_value=0).astype(float))
        z = G.zscore(x, G.Z_WIN)
        shock = G.shock_flags(flow, G.FLOW_WIN, G.SHOCK_Q)
        persistent = (z.abs() >= G.Z_ENTRY) & (np.sign(z) == np.sign(z.shift(1))) \
            & (z.shift(1).abs() >= G.Z_ENTRY)
        rt = G.round_trips(sig)
        shockdays[sig] = set(x.index[shock.reindex(x.index).fillna(False)])
        for h in G.HORIZONS:
            a = G.episodes(x, z, G.pd.Series(persistent) & shock, h)
            b = G.episodes(x, z, G.pd.Series(persistent) & ~shock, h)
            sa, sb = G.stats(a, rt["rt_cm2"]), G.stats(b, rt["rt_cm2"])
            rows.append({
                "signature": sig, "h": h,
                "flow_total": float(flow.sum()), "shock_days": int(shock.sum()),
                "n_shock": sa.get("n", 0), "n_noshock": sb.get("n", 0),
                "gross_med_shock": sa.get("gross_med", np.nan),
                "gross_med_noshock": sb.get("gross_med", np.nan),
                "net_mean_1x_shock": sa.get("net_mean_1x", np.nan),
                "rt_cm2": rt["rt_cm2"],
                "incr": (sa.get("gross_med", np.nan) - sb.get("gross_med", np.nan)),
            })
    return pd.DataFrame(rows), shockdays


def main() -> None:
    par = pd.read_parquet(G.OUT / "par_grid_USD_SOFR.parquet")
    par.index = pd.to_datetime(par.index)
    uni = json.loads((G.OUT / "f7_universe.json").read_text())["universe"]
    dg_all = pd.read_parquet(G.OUT / "f7_extract_diag.parquet")
    file_dates = pd.to_datetime(dg_all["file_date"])
    common = par.index.intersection(pd.DatetimeIndex(file_dates))

    ab = pd.read_parquet(G.OUT / "f7_packages.parquet")
    ab["file_date"] = pd.to_datetime(ab["file_date"])
    co = pd.read_parquet(SCRATCH / "f7_pkg_corrected.parquet")
    co["file_date"] = pd.to_datetime(co["file_date"])

    r_ab, sd_ab = run(ab, par, common, uni)
    r_co, sd_co = run(co, par, common, uni)

    print("=== shock-day overlap, as-built vs corrected ===")
    for sig in uni:
        A, B = sd_ab[sig], sd_co[sig]
        jac = len(A & B) / max(1, len(A | B))
        print(f"  {sig:<9} as-built {len(A):>4}  corrected {len(B):>4}  "
              f"shared {len(A & B):>4}  jaccard {jac:.3f}")

    m = r_ab.merge(r_co, on=["signature", "h"], suffixes=("_ab", "_co"))
    print("\n=== per-signature increment (gross_med shock - gross_med noshock), bp ===")
    print(m[["signature", "h", "n_shock_ab", "n_shock_co", "incr_ab", "incr_co",
             "rt_cm2_ab"]].round(3).to_string(index=False))

    print("\n=== HEADLINE: median increment across the 10 signatures ===")
    out = {}
    for h in G.HORIZONS:
        s = m[m["h"] == h]
        a = float(s["incr_ab"].median())
        c = float(s["incr_co"].median())
        na = int((s["incr_ab"] > 0).sum())
        nc = int((s["incr_co"] > 0).sum())
        rt = float(s["rt_cm2_ab"].median())
        print(f"  h={h:>2}bd   as-built {a:+.3f}bp ({na}/10 positive)   "
              f"corrected {c:+.3f}bp ({nc}/10 positive)   delta {c-a:+.3f}bp   "
              f"median round trip {rt:.2f}bp")
        out[h] = {"asbuilt": a, "corrected": c, "delta": c - a,
                  "n_pos_ab": na, "n_pos_co": nc, "median_rt": rt}

    print("\n=== spreads only (the 5 that cleared the pond at h=21) ===")
    spr = m[m["signature"].str.count("-") == 1]
    for h in G.HORIZONS:
        s = spr[spr["h"] == h]
        print(f"  h={h:>2}bd   as-built {s['incr_ab'].median():+.3f}bp   "
              f"corrected {s['incr_co'].median():+.3f}bp   "
              f"best corrected {s['incr_co'].max():+.3f}bp "
              f"({s.loc[s['incr_co'].idxmax(), 'signature']})")

    print("\n=== shock-book NET at 1x cost (corrected), median across signatures ===")
    for h in G.HORIZONS:
        s = m[m["h"] == h]
        print(f"  h={h:>2}bd   as-built {s['net_mean_1x_shock_ab'].median():+.3f}bp   "
              f"corrected {s['net_mean_1x_shock_co'].median():+.3f}bp")

    (SCRATCH / "f7_increment_compare.json").write_text(
        json.dumps(out, indent=2, default=str), encoding="utf-8")
    m.to_parquet(SCRATCH / "f7_increment_compare.parquet", index=False)


if __name__ == "__main__":
    main()

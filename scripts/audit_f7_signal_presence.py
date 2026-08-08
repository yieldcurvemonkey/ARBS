"""AUDIT probe (0 trials, no P&L): is the FLOW shock attached to the STATE at all?

If a flow shock never coincides with a dislocation, and never moves the structure on its
own day, then a zero increment is the honest answer rather than a bug that ate the signal.
Conversely, if shock days DO carry a contemporaneous move but the registered entry filter
never fires on them, the gate would have discarded the mechanism's own trades.

Measures, for the COUNT and the NOTIONAL shock, per signature:
  * entry & shock days vs the count expected if shock _|_ entry
  * |d structure| on shock days vs other days (contemporaneous impact)
  * mean |z| on shock days vs other days
  * P(entry fires | shock) vs P(entry fires) -- the discard question

Run: C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8 scripts/audit_f7_signal_presence.py
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
import s3_f7_gate as g  # noqa: E402

OUT = g.OUT


def main() -> None:
    par = pd.read_parquet(OUT / "par_grid_USD_SOFR.parquet")
    par.index = pd.to_datetime(par.index)
    pkg = pd.read_parquet(OUT / "f7_packages.parquet")
    pkg["file_date"] = pd.to_datetime(pkg["file_date"])
    uni = json.loads((OUT / "f7_universe.json").read_text())["universe"]
    dg = pd.read_parquet(OUT / "f7_extract_diag.parquet")
    common = par.index.intersection(pd.DatetimeIndex(pd.to_datetime(dg["file_date"])))

    for mode in ("count", "notional"):
        rows = []
        for sig in uni:
            x = g.structure_series(par, sig).reindex(common).dropna()
            sub = pkg[pkg["signature"] == sig]
            flow = (sub.groupby("file_date").size() if mode == "count"
                    else sub.groupby("file_date")["notional_sum"].sum())
            flow = flow.reindex(x.index, fill_value=0).astype(float)
            z = g.zscore(x, g.Z_WIN)
            sh = g.shock_flags(flow, g.FLOW_WIN, g.SHOCK_Q)
            ent = (z.abs() >= g.Z_ENTRY) & (np.sign(z) == np.sign(z.shift(1))) \
                & (z.shift(1).abs() >= g.Z_ENTRY)
            valid = z.notna() & z.shift(1).notna()          # days the rule could fire at all
            sh_v, ent_v = sh[valid], ent[valid]
            d = x.diff().abs()[valid]
            zz = z.abs()[valid]
            n = int(valid.sum())
            exp_joint = float(sh_v.sum()) * float(ent_v.sum()) / max(1, n)
            rows.append({
                "signature": sig, "n_days": n,
                "shock": int(sh_v.sum()), "entry": int(ent_v.sum()),
                "entry&shock": int((sh_v & ent_v).sum()),
                "exp_if_indep": round(exp_joint, 1),
                "lift": round(float((sh_v & ent_v).sum()) / exp_joint, 3) if exp_joint else np.nan,
                "P(entry|shock)": round(float(ent_v[sh_v].mean()), 3),
                "P(entry)": round(float(ent_v.mean()), 3),
                "|dx| shock": round(float(d[sh_v].median()), 3),
                "|dx| other": round(float(d[~sh_v].median()), 3),
                "|dx| ratio": round(float(d[sh_v].median() / d[~sh_v].median()), 3),
                "|z| shock": round(float(zz[sh_v].mean()), 3),
                "|z| other": round(float(zz[~sh_v].mean()), 3),
            })
        df = pd.DataFrame(rows)
        pd.set_option("display.width", 250)
        print(f"\n=== {mode.upper()} shock: is it attached to the state? ===")
        print(df.to_string(index=False))
        print(f"  median lift(entry&shock vs independence) = {df['lift'].median():.3f}   "
              f"median |dx| ratio (shock/other) = {df['|dx| ratio'].median():.3f}   "
              f"median |z| shock {df['|z| shock'].median():.3f} vs other "
              f"{df['|z| other'].median():.3f}")


if __name__ == "__main__":
    main()

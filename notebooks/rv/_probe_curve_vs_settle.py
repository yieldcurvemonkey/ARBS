"""Why does the Q16 curve's fly disagree with the settle fly by ~8bp?

Hypothesis: USD-SOFR-1D-Q16STIRT does not reprice the SR3 futures it is built
from. Its config in MDP/IRSwaps/BARCHART_STIRF/rl.py has no
``stirf_target_weight`` (Q12STIRT sets 1e6), and the strip showed bit-identical
rates across slots 8-14 on 2026-07-27 -- the signature of a solver that smoothed
instead of fitting.

Test: for several dates, print per slot the settle-implied rate (100 - settle)
against BOTH curves' IMM forward rates, and the resulting flies.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd
import pytz

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery

NYC = pytz.timezone("America/New_York")
DATA = REPO / "notebooks" / "data" / "sfr_fly_meanrev"
pd.set_option("display.width", 200)


def strip_rates(mdp, curve, d, n):
    ts = NYC.localize(datetime.datetime.combine(d, datetime.time(17, 0)))
    ch = mdp.get_pricer(request=dict(curve_name=curve, timestamp=ts))
    out = {}
    for i in range(1, n + 1):
        q = IRSwapQuery(curve=curve, tenor=f"IMM_{i}xIMM_{i+1}").resolve_query(
            ts, pricer_or_curve=ch)
        pkg, _ = q.resolve_package(pricer_or_curve=ch)
        kw = pkg[0].__dict__["kwargs"]
        out[i] = (kw["effective"].date(), kw["fixed_rate"])
    return out


def main():
    contracts = pd.read_parquet(DATA / "contracts.parquet")
    contracts["as_of"] = pd.to_datetime(contracts["as_of"])
    contracts["imm_start"] = pd.to_datetime(contracts["imm_start"])
    mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")

    for d in (datetime.date(2026, 7, 27), datetime.date(2025, 6, 12),
              datetime.date(2023, 6, 14)):
        day = contracts[contracts["as_of"] == pd.Timestamp(d)]
        day = day[day["imm_start"] > pd.Timestamp(d)].sort_values("imm_start")
        if day.empty:
            print(f"\n=== {d}: no settle rows ===")
            continue
        day = day.head(16).reset_index(drop=True)
        rows = []
        curves = {}
        for cname, n in (("USD-SOFR-1D-Q12STIRT", 12), ("USD-SOFR-1D-Q16STIRT", 16)):
            try:
                curves[cname] = strip_rates(mdp, cname, d, n)
            except Exception as exc:
                print(f"  {cname}: {type(exc).__name__}: {str(exc)[:90]}")
        for i, r in day.iterrows():
            slot = i + 1
            rec = {"slot": slot, "code": r["code"], "settle": r["settle"],
                   "settle_rate": 100.0 - r["settle"]}
            for cname, m in curves.items():
                tag = "q12" if "Q12" in cname else "q16"
                if slot in m:
                    rec[f"{tag}_eff"] = m[slot][0]
                    rec[f"{tag}_rate"] = m[slot][1]
                    rec[f"{tag}_diff_bp"] = (m[slot][1] - rec["settle_rate"]) * 100
            rows.append(rec)
        df = pd.DataFrame(rows)
        print(f"\n{'='*100}\n=== {d} ===\n{'='*100}")
        print(df.round(4).to_string(index=False))

        def flies(col):
            v = df[col].to_numpy(dtype=float)
            return np.array([(2 * v[i + 1] - v[i] - v[i + 2]) * 100
                             for i in range(len(v) - 2)])

        cmp = {"settle": flies("settle_rate")}
        for tag in ("q12", "q16"):
            if f"{tag}_rate" in df.columns:
                cmp[tag] = flies(f"{tag}_rate")
        n = min(len(v) for v in cmp.values())
        out = pd.DataFrame({k: v[:n] for k, v in cmp.items()})
        out.index = [f"SFR{i+1}{i+2}{i+3}" for i in range(n)]
        print("\n-- 3m fly (bp) --")
        print(out.round(3).to_string())
        for tag in ("q12", "q16"):
            if tag in out.columns:
                keep = out["settle"].abs() > 1e-9
                ratio = (out.loc[keep, tag] / out.loc[keep, "settle"]).median()
                print(f"  median {tag}/settle fly ratio: {ratio:.3f}   "
                      f"corr {out['settle'].corr(out[tag]):.3f}")


if __name__ == "__main__":
    main()

r"""ADVERSARIAL CHECK 1: as-of invariants, staleness arithmetic, freshness.

Written from scratch against the parquet. Does NOT import the builder's own helpers
for anything it is checking.
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

DATA = pathlib.Path(r"C:\Users\chris\clee\ARBS-etf\notebooks\backtests\etf_rebalance\_data")
OUT = []


def rec(check, value, verdict, note=""):
    OUT.append({"check": check, "value": value, "verdict": verdict, "note": note})
    print(f"  {verdict:9s} {check}: {value}   {note}", flush=True)


def target_ts(df):
    hh = df["mark_time"].str.slice(0, 2).astype(int)
    mm = df["mark_time"].str.slice(3, 5).astype(int)
    return df["date"] + pd.to_timedelta(hh, unit="h") + pd.to_timedelta(mm, unit="m")


def run_invariants(p, label):
    """Every invariant the builder claims. Returns dict of counts."""
    tgt = target_ts(p)
    res = {}
    for leg, tscol, stcol in (("ytm", "ts_ytm", "stale_min_ytm"),
                              ("px", "ts_px", "stale_min_px")):
        has = p[tscol].notna()
        ts = p.loc[has, tscol]
        tg = tgt[has]
        # 1. LOOKAHEAD: print stamp must be at or before the mark
        ahead = (ts > tg)
        rec(f"[{label}] {leg}: prints AFTER the mark (lookahead)", int(ahead.sum()),
            "PASS" if ahead.sum() == 0 else "FAIL",
            f"of {int(has.sum()):,}")
        # 2. same calendar day
        notsame = (ts.dt.normalize() != tg.dt.normalize())
        rec(f"[{label}] {leg}: prints on a DIFFERENT calendar day", int(notsame.sum()),
            "PASS" if notsame.sum() == 0 else "FAIL")
        # 3. staleness arithmetic exact
        st = (tg - ts).dt.total_seconds() / 60.0
        err = (st - p.loc[has, stcol]).abs()
        rec(f"[{label}] {leg}: max staleness arithmetic error (min)",
            float(err.max()), "PASS" if err.max() < 1e-6 else "FAIL")
        # 4. staleness within the declared cap
        over = p.loc[has, stcol] > 240
        rec(f"[{label}] {leg}: marks staler than the 240-min cap", int(over.sum()),
            "PASS" if over.sum() == 0 else "FAIL")
        res[leg] = int(has.sum())
    # 5. is_fresh consistency
    want = p["stale_min_ytm"].le(30) & p["stale_min_px"].le(30)
    want = want.fillna(False)
    bad = (want != p["is_fresh"])
    rec(f"[{label}] is_fresh matches (both legs <= 30 min)", int(bad.sum()),
        "PASS" if bad.sum() == 0 else "FAIL")
    return res


def main() -> int:
    pd.set_option("display.width", 240)
    p = pd.read_parquet(DATA / "ipanel_mi01.parquet")
    p["date"] = pd.to_datetime(p["date"])
    print(f"panel {len(p):,} rows, {p['date'].nunique()} dates, {p['cusip'].nunique()} cusips, "
          f"{p['mark_time'].nunique()} marks, {p['date'].min().date()}..{p['date'].max().date()}")

    print("\n--- INVARIANTS ON THE REAL PANEL")
    run_invariants(p, "real")

    # ------------------------------------------------ MUTATION TEST of this checker
    # House rule: run the checker against an input whose answer is known.
    print("\n--- MUTATION TEST: inject 1 lookahead row, 1 cross-day row, 1 bad stale")
    m = p.head(50000).copy()
    m.loc[m.index[0], "ts_ytm"] = m.loc[m.index[0], "ts_ytm"] + pd.Timedelta(minutes=3)
    m.loc[m.index[1], "ts_px"] = m.loc[m.index[1], "ts_px"] - pd.Timedelta(days=1)
    m.loc[m.index[2], "stale_min_ytm"] = 999.0
    n0 = len(OUT)
    run_invariants(m, "MUTATED")
    fired = sum(1 for r in OUT[n0:] if r["verdict"] == "FAIL")
    rec("mutation test: checks that fired on a seeded-bad panel", fired,
        "PASS" if fired >= 3 else "FAIL", "checker is live")

    # ------------------------------------------------------------- freshness profile
    print("\n--- FRESHNESS BY MARK (yield leg)")
    rows = []
    for mt, g in p[p["ytm"].notna()].groupby("mark_time"):
        rows.append({
            "mark_time": mt, "n": len(g),
            "med_stale_min": float(g["stale_min_ytm"].median()),
            "frac_at_mark": float(g["stale_min_ytm"].eq(0).mean()),
            "frac_le_1m": float(g["stale_min_ytm"].le(1).mean()),
            "frac_le_5m": float(g["stale_min_ytm"].le(5).mean()),
            "frac_le_30m": float(g["stale_min_ytm"].le(30).mean()),
            "frac_gt_30m": float(g["stale_min_ytm"].gt(30).mean()),
            "p95_stale_min": float(g["stale_min_ytm"].quantile(0.95)),
        })
    f = pd.DataFrame(rows).sort_values("mark_time")
    print(f.round(4).to_string(index=False))
    f.to_csv(DATA / "adv_ipanel_freshness.csv", index=False)

    # --------------------------------------------- does a mark ever precede the open?
    # a 09:30 mark resolved to an 09:00 print is legal here; flag how often marks come
    # from before the 09:30 cash open at all.
    tg = target_ts(p)
    early = p["ts_ytm"].notna() & (p["ts_ytm"].dt.hour < 9)
    rec("yield prints stamped before 09:00 NY", int(early.sum()), "INFO",
        f"{early.mean()*100:.2f}% of resolved rows")

    # -------------------------------------------------- weekend / non-business dates
    wd = p["date"].dt.dayofweek
    rec("rows on Sat/Sun", int((wd >= 5).sum()), "INFO",
        f"{(wd>=5).mean()*100:.2f}%; {p.loc[wd>=5,'date'].nunique()} distinct dates")
    rec("rows with a FedInvest join", int(p["ytm_fedinvest"].notna().sum()), "INFO",
        f"{p['ytm_fedinvest'].notna().mean()*100:.2f}%")

    pd.DataFrame(OUT).to_csv(DATA / "adv_ipanel_asof_checks.csv", index=False)
    print(f"\nwrote adv_ipanel_asof_checks.csv, adv_ipanel_freshness.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

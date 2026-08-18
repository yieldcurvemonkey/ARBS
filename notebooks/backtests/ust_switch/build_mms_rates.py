"""Matched-maturity SOFR par rates for every bond the switch study touches.

For each CUSIP that ever occupies ranks 0-3 of a tenor, fetch the daily par rate of a
USD-SOFR swap maturing on the bond's maturity date, over the bond's active window
(clipped to SOFR's own existence -- Citi serves USD-SOFR-1D curves from 2018-04, which is
the month SOFR was first published; there is no such thing as a matched-maturity SOFR
swap before that, so the MMS study window is 2018-04 .. 2026-08 by construction, and the
2010-2018 half of the bond study has no swap-hedged variant).

Source is CITIVELO_EXCEL: 6x faster than ERIS_EOD_LIVE-RL_BASIC per probe (1.9s vs 12.6s
per 10-day chunk) and 2 years deeper (2018-04 vs 2021-03); the two agree to ~0.1bp where
they overlap.

Conventions, stated: the swap RATE is Citi's USD SOFR par convention (annual/360); the
bond YTM is semi-annual bond-equivalent. The MMS *level* therefore mixes conventions, but
the box P&L only consumes DIFFERENCES of CHANGES of two nearby-maturity swap rates, where
the convention wedge is second-order (~2% of a hedge leg that is itself ~2bp).

The swap schedule is struck once per bond (effective = first active day) rather than
re-struck daily: the RATE value re-solves the fair fixed rate of the remaining schedule
each day, which differs from a spot-rolling par rate only through the stub start --
invisible in daily differences.

    <env>/python.exe notebooks/backtests/ust_switch/build_mms_rates.py
"""

from __future__ import annotations

import argparse
import datetime
import os
import pathlib
import sys
import time
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
warnings.filterwarnings("ignore")

import pandas as pd  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

HERE = pathlib.Path(__file__).resolve().parent
STORE = HERE / "_out" / "mms_rates"
SOFR_FLOOR = datetime.date(2018, 4, 2)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenors", default="")
    a = ap.parse_args(argv)
    STORE.mkdir(parents=True, exist_ok=True)

    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from TB.IRSwapsTB import IRSwapsTB

    panel = pd.read_parquet(HERE / "_data" / "prepared_panel.parquet")
    panel["date"] = pd.to_datetime(panel["date"])
    panel["maturity_date"] = pd.to_datetime(panel["maturity_date"])

    tenors = tuple(int(x) for x in a.tenors.split(",")) if a.tenors else (2, 3, 5, 7, 10, 20, 30)
    mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
    tb = IRSwapsTB(mdp, show_tqdm=False)

    for tenor in tenors:
        out_path = STORE / f"mms_rates_{tenor}.parquet"
        if out_path.exists():
            print(f"{tenor}Y: cached", flush=True)
            continue
        p = panel[panel["tenor"] == tenor]
        spans = (p.groupby("cusip")
                 .agg(start=("date", "min"), end=("date", "max"), mat=("maturity_date", "first"))
                 .reset_index())
        rows, n_ok, n_skip = [], 0, 0
        t0 = time.time()
        for _, r in spans.iterrows():
            start = max(r["start"].date(), SOFR_FLOOR)
            end = r["end"].date()
            if start >= end:
                n_skip += 1
                continue
            q = IRSwapQuery(
                curve="USD-SOFR-1D", value=IRSwapValue.RATE,
                effective_date=start, maturity_date=r["mat"].date(),
                structure_kwargs={"notional": 1_000_000},
            )
            try:
                df = tb.get_timeseries(start=start, end=end, queries=[q], n_jobs=1)
            except Exception as exc:
                print(f"  {r['cusip']}: FAILED {type(exc).__name__}: {str(exc)[:90]}", flush=True)
                continue
            if df is None or df.empty:
                continue
            s = df.iloc[:, 0].dropna()
            if s.empty:
                continue
            rows.append(pd.DataFrame({"date": pd.to_datetime(s.index), "cusip": r["cusip"],
                                      "par_rate_pct": s.values}))
            n_ok += 1
        if not rows:
            print(f"{tenor}Y: NOTHING (window predates SOFR?)", flush=True)
            continue
        out = pd.concat(rows, ignore_index=True)
        out.to_parquet(out_path, index=False)
        print(f"{tenor}Y: {n_ok} cusips ({n_skip} pre-SOFR), {len(out):,} rows "
              f"({(time.time() - t0) / 60:.1f} min) -> {out_path.name}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

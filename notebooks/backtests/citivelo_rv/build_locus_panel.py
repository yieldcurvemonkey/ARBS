"""Forward + annuity panel for the H16b straddle loci, off stored curves.

Per stored USD day (2020-01-24+, the full-smile cube era): for each locus
(expiry x tenor), the ATM forward (decimal) and the annuity ($/bp at $100mm)
of the underlying forward swap — the two curve inputs premium marks need.
Ghost days (reference-date mismatch) are dropped, same rule as the screens.

Rebuild: conda run -n stir python notebooks/backtests/citivelo_rv/build_locus_panel.py
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime
import pathlib
import sys
import time

_REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO))

import pandas as pd

LOCI = [("2Y", "10Y"), ("10Y", "10Y"), ("20Y", "10Y"), ("1Y", "10Y"), ("6M", "10Y"),
        ("1M", "10Y"), ("3M", "10Y"), ("3M", "2Y"), ("6M", "2Y")]
START = datetime.date(2020, 1, 24)
CHUNK = 250


def main() -> None:
    import logging

    logging.disable(logging.WARNING)
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from RVUtils.StrikelessVol.citivelo import stored_dates
    from RVUtils.StrikelessVol.premium_mark import forward_and_annuity

    days = stored_dates("USD", START, datetime.date(2026, 8, 7))
    mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
    rows = []
    t0 = time.time()
    for lo in range(0, len(days), CHUNK):
        chunk = days[lo:lo + CHUNK]
        cm = mdp.bulk_get_data({"curve_name": "USD-SOFR-1D", "timestamps": chunk,
                                "offline": True})
        for ts in sorted(cm, key=str):
            curve = cm[ts]
            if curve is None:
                continue
            ref = curve.reference_date()
            ref_d = ref.date() if hasattr(ref, "date") else ref
            ts_d = ts.date() if hasattr(ts, "date") else ts
            if ref_d != ts_d:
                continue
            rec = {"date": pd.Timestamp(ts_d)}
            try:
                for exp, ten in LOCI:
                    f, a = forward_and_annuity(curve, exp, ten)
                    rec[f"fwd_{exp.lower()}{ten.lower()}"] = f
                    rec[f"ann_{exp.lower()}{ten.lower()}"] = a
            except Exception:
                continue
            rows.append(rec)
        print(f"  {min(lo + CHUNK, len(days))}/{len(days)} ({time.time() - t0:.0f}s)",
              flush=True)

    df = pd.DataFrame(rows).set_index("date").sort_index()
    out = _REPO / "notebooks" / "data" / "citivelo_rv" / "locus_panel_USD.parquet"
    df.to_parquet(out)
    print(f"wrote {out.name}: {df.shape[0]} days x {df.shape[1]} cols in "
          f"{time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()

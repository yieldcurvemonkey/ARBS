"""Probe 2: do the two UnifiedQuery tenors actually serve?

``IMM_3xIMM_4`` is proven elsewhere in the repo; ``1d`` with IRS_RATE is not, so
this asks for a five-day window before anything commits to a seven-year fetch.
Also names the one Thursday in the FOMC registry.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")

import pandas as pd  # noqa: E402

sys.stdout.reconfigure(line_buffering=True)

CURVE = "USD-SOFR-1D"


def main() -> None:
    from fomc_extras import fomc_decision_dates
    ds = fomc_decision_dates()
    odd = [d for d in ds if d.weekday() != 2]
    print(f"registry dates not on a Wednesday: {odd}")

    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue
    from TB.IRSwapsTB import IRSwapsTB
    from TB.TimeseriesBuilder import TimeseriesBuilder

    tb = IRSwapsTB(IRSwapsMDP(source="citivelo_excel_rl"), show_tqdm=False)
    qs = [
        UnifiedQuery(curve=CURVE, tenor="IMM_3xIMM_4", value=UnifiedValue.IRS_RATE),
        UnifiedQuery(curve=CURVE, tenor="1d", value=UnifiedValue.IRS_RATE),
    ]
    for q in qs:
        print(f"query built: curve={q.curve} tenor={q.tenor} value={q.value}")

    for a, b in [(dt.date(2026, 8, 10), dt.date(2026, 8, 21)),
                 (dt.date(2019, 1, 2), dt.date(2019, 1, 15))]:
        print(f"\n=== window {a} .. {b} ===")
        try:
            df = TimeseriesBuilder().get_timeseries(
                start=a, end=b, queries=qs, n_jobs=4, routers={"IRS": tb})
            print(f"shape {df.shape}")
            print(f"columns: {list(df.columns)}")
            print(df.to_string())
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            print(f"FAILED: {type(exc).__name__}: {exc}")

    tb.close()


if __name__ == "__main__":
    main()

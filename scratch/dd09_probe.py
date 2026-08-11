"""Quick orientation probe for the repricing pass.

Three things the design turns on and none of them is documented anywhere:

  P1  does a BARCHART handle expose ``.meta()`` at all, and does it carry the
      snapshot lag keys? If it does not, requiring lag telemetry unconditionally
      would make the legacy branch unusable.
  P2  does the strict Citi path price a PAST-START leg (effective_date before
      the snap) without a fixings error?
  P3  what does ``IRSwapQuery`` return for RATE on a single leg - percent, as
      the reference note claims?
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import datetime

import pandas as pd


def main() -> None:
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy import SnapshotPolicy
    from SDRUtils.stir_flow.pricing import CurvePricer

    snap = pd.Timestamp("2026-04-01 14:30:00", tz="America/New_York").to_pydatetime()

    print("=== P1: Barchart handle metadata ===")
    bmdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    bp = CurvePricer(bmdp)
    try:
        h = bp.handle("USD-SOFR-1D-Q12xM12STIRT", snap)
        m = h.meta() if hasattr(h, "meta") else None
        print(f"  type={type(h).__name__} has meta()={hasattr(h, 'meta')}")
        print(f"  meta keys: {sorted(m)[:30] if isinstance(m, dict) else m!r}")
        if isinstance(m, dict):
            for k in ("snapshot_lag_signed_seconds", "snapshot_lag_seconds",
                      "snapshot_served_from_future", "snapshot_policy"):
                print(f"    {k} = {m.get(k)!r}")
    except Exception as exc:  # noqa: BLE001
        print(f"  FAILED {type(exc).__name__}: {exc}")

    print("\n=== P1b: does Barchart raise when handed a snapshot_policy? ===")
    try:
        CurvePricer(IRSwapsMDP(source="BARCHART_STIRF-RL"),
                    curve_kwargs={"snapshot_policy": SnapshotPolicy.strict(minutes=1)}
                    ).handle("USD-SOFR-1D-Q12xM12STIRT", snap)
        print("  NO RAISE -- the guard is not where the task said")
    except ValueError as exc:
        print(f"  ValueError (expected): {str(exc)[:140]}")

    print("\n=== P2: Citi strict, past-start leg ===")
    cp = CurvePricer(IRSwapsMDP(source="CITIVELO_EXCEL"),
                     curve_kwargs={"snapshot_policy": SnapshotPolicy.strict(minutes=1)})
    cases = {
        "spot 5Y": (datetime.date(2026, 4, 3), datetime.date(2031, 4, 3)),
        "fwd-start 1Yx5Y": (datetime.date(2027, 4, 5), datetime.date(2032, 4, 5)),
        "past-start (eff 2024-06-12)": (datetime.date(2024, 6, 12), datetime.date(2029, 6, 12)),
        "deep past-start (eff 2020-01-15)": (datetime.date(2020, 1, 15), datetime.date(2030, 1, 15)),
    }
    for label, (eff, mat) in cases.items():
        try:
            lp = cp.price_leg("USD-SOFR-1D", snap, eff, mat, 10_000_000.0, fixed_rate=0.04)
            print(f"  {label:34s} mid={lp.mid_pct:.6f}%  pv01={lp.pv01:,.2f}  "
                  f"npv={lp.npv_pay:,.2f}")
        except Exception as exc:  # noqa: BLE001
            print(f"  {label:34s} FAILED {type(exc).__name__}: {str(exc)[:110]}")

    print("\n=== P3: handle metadata on the Citi path ===")
    h = cp.handle("USD-SOFR-1D", snap)
    m = h.meta()
    print(f"  {sorted(m)}")
    print(f"  lag_signed={m.get('snapshot_lag_signed_seconds')!r} "
          f"future={m.get('snapshot_served_from_future')!r}")


if __name__ == "__main__":
    main()

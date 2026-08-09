"""Probe 11: can we reconstruct a JPY TONA 3M STIRFuture from the warmed
Citi Velocity minute curve?

Barchart has no JPY STIR future at all (probe 9 exhausted 14 roots), so the only
route to a BOJ leg is to build the instrument ourselves: read the minute curve at
the timestamp, take the forward rate over the IMM quarter, and hand 100 - rate to
rateslib as a STIRFuture price.

Two things must be checked, not assumed:
  1. does the minute store actually serve intraday, and how STALE is what it
     serves? The store does a nearest-snapshot search with NO lag tolerance, so a
     request can silently come back with a snapshot from a different day.
  2. does the reconstructed rate move intraday at all - i.e. is this a real
     intraday series or a daily curve repeated?
"""

from __future__ import annotations

import sys
import io
import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-gcb")

import pandas as pd
import pytz
import rateslib as rl

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

TYO = pytz.timezone("Asia/Tokyo")
CURVE = "JPY-TONAR-1D-LCH"


def _plain(ts):
    if hasattr(ts, "to_pydatetime"):
        ts = ts.to_pydatetime()
    return datetime.datetime(ts.year, ts.month, ts.day, ts.hour, ts.minute, ts.second,
                             tzinfo=ts.tzinfo)


def imm_pair(ref: datetime.date, n: int = 3):
    from rateslib.scheduling import next_imm
    imm = datetime.datetime(ref.year, ref.month, ref.day)
    for _ in range(n):
        imm = next_imm(imm)
    eff = imm
    mat = next_imm(imm)
    return eff.date(), mat.date()


def main():
    mdp = IRSwapsMDP(source="citivelo_excel")

    day = datetime.date(2025, 11, 20)
    times = [datetime.time(h, m) for h, m in
             [(9, 30), (10, 30), (11, 30), (13, 30), (14, 30), (15, 30)]]

    eff, mat = imm_pair(day, 3)
    print(f"curve   : {CURVE}")
    print(f"IMM_3   : {eff} -> {mat}")
    print()

    rows = []
    for t in times:
        ts = _plain(TYO.localize(datetime.datetime.combine(day, t)))
        try:
            pr = mdp.get_pricer({"curve_name": CURVE, "timestamp": ts})
        except Exception as e:  # noqa: BLE001
            print(f"  {t}  ERROR {type(e).__name__}: {str(e)[:110]}")
            continue
        if pr is None:
            print(f"  {t}  None")
            continue

        # what did the store actually serve?
        meta = getattr(pr, "meta", None)
        meta = meta() if callable(meta) else meta
        ref = getattr(pr, "reference_date", None)
        ref = ref() if callable(ref) else ref

        handle = getattr(pr, "handle", None)
        curve = handle() if callable(handle) else handle

        rate = None
        try:
            irs = rl.IRS(effective=rl.dt(eff.year, eff.month, eff.day),
                         termination=rl.dt(mat.year, mat.month, mat.day),
                         spec="jpy_irs", curves=curve)
            rate = float(irs.rate())
        except Exception as e:  # noqa: BLE001
            rate = f"ERR {type(e).__name__}: {str(e)[:60]}"

        served = None
        if isinstance(meta, dict):
            served = meta.get("actual_timestamp") or meta.get("timestamp") or meta.get("served")
        rows.append({"req": t, "served": served, "ref_date": ref, "rate": rate})
        print(f"  {t}  ref={ref}  served={served}  IMM3 rate={rate}")

    print()
    df = pd.DataFrame(rows)
    if "rate" in df and df["rate"].map(lambda x: isinstance(x, float)).all() and len(df) > 1:
        r = df["rate"].astype(float)
        print(f"  intraday range of the reconstructed IMM_3 rate: "
              f"{(r.max() - r.min()) * 100:.2f} bp over {len(r)} snapshots")
        if (r.max() - r.min()) < 1e-12:
            print("  ** the rate does NOT move intraday — this is a daily curve repeated **")
        else:
            print("  the reconstructed rate DOES move intraday")

        px = 100.0 - r
        print(f"  implied STIRFuture price range: {px.min():.4f} .. {px.max():.4f}")

        # And prove a real rl.STIRFuture can be built from it.
        f = rl.STIRFuture(
            effective=rl.dt(eff.year, eff.month, eff.day),
            termination=rl.dt(mat.year, mat.month, mat.day),
            spec="jpy_irs", price=float(px.iloc[0]), contracts=1, curves=CURVE,
        )
        print(f"  built rl.STIRFuture OK: {type(f).__name__}  price={float(px.iloc[0]):.4f}")

    print("\nDONE")


if __name__ == "__main__":
    main()

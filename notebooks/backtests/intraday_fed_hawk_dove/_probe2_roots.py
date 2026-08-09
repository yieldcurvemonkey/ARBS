"""Probe 2: distinguish 'wrong ticker' from 'no data' for the non-USD STIR roots.

(a) Daily bars per root over a long window -> does Barchart know the symbol at all?
(b) MDP.get_data() at an EOD date -> does the full pricer path work?
(c) Candidate alternative JPY roots.
"""

from __future__ import annotations

import sys
import datetime
import traceback

sys.path.insert(0, r"C:\Users\chris\clee\ARBS-gcb")

import pandas as pd
import pytz

from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP, _normalize_symbol, _to_barchart_symbol

NY = pytz.timezone("America/New_York")

# Explicit contracts that were definitely listed in their era.
CANDIDATES = [
    # (barchart symbol, note)
    ("SQZ25", "USD SOFR3M CME (control)"),
    ("RAZ25", "EUR ESTR3M ICE"),
    ("EBZ25", "EUR ESTR3M CME"),
    ("J8Z25", "GBP SONIA3M ICE"),
    ("JUZ25", "GBP SONIA1M ICE"),
    ("T0Z25", "JPY TONA3M JPX (mapped root)"),
    ("ITZ25", "JPY TONA3M TFX (mapped root)"),
    # alternative guesses for JPY
    ("TNZ25", "JPY guess TN"),
    ("JYZ25", "JPY guess JY"),
    ("TOZ25", "JPY guess TO"),
    ("BAZ25", "CAD BAX (sanity: known barchart root)"),
]


def daily_depth() -> pd.DataFrame:
    mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
    fetcher = mdp._get_barchart_fetcher(required_concurrency=4)
    start = NY.localize(datetime.datetime(2020, 1, 1))
    end = NY.localize(datetime.datetime(2026, 8, 7))

    rows = []
    for sym, note in CANDIDATES:
        n, lo, hi, last_px = 0, None, None, None
        err = ""
        try:
            per = fetcher.barchart_timeseries_api(
                barchart_symbols=[sym], start_date=start, end_date=end,
                interval=1440, one_df=False, show_tqdm=False,
            ) or {}
            frame = None
            for _k, v in per.items():
                if v is not None and len(v):
                    frame = v
                    break
            if frame is not None and len(frame):
                n = len(frame)
                lo = str(frame.index.min())[:10]
                hi = str(frame.index.max())[:10]
                if "Close" in frame.columns:
                    last_px = float(frame["Close"].iloc[-1])
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"[:100]
        rows.append(dict(symbol=sym, note=note, daily_bars=n, first=lo, last=hi,
                         last_px=last_px, err=err))
        print(f"  {sym:7s} {note:32s} days={n:5d} {lo}..{hi} last={last_px} {err}", flush=True)
    return pd.DataFrame(rows)


def mdp_pricer_path() -> None:
    """Does the full MDP -> RLSTIRFuturePricer path work per root?"""
    mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
    for sym in ["SR3Z25", "RAZ25", "EBZ25", "J8Z25", "T0Z25", "ITZ25"]:
        try:
            res = mdp.get_data({"symbols": [sym], "timestamp": datetime.date(2025, 11, 20)})
            flat = []
            for k, v in (res or {}).items():
                if isinstance(v, list):
                    flat.extend(v)
                else:
                    flat.append(v)
            if not flat:
                print(f"  {sym:7s} -> EMPTY")
                continue
            p = flat[0]
            print(f"  {sym:7s} -> id={p.id()} price={p.price():.4f} curve={p.curve_key()} "
                  f"eff={p.effective_date()} mat={p.maturity_date()}")
        except Exception as e:  # noqa: BLE001
            print(f"  {sym:7s} -> ERROR {type(e).__name__}: {str(e)[:140]}")


def main() -> None:
    print("=" * 100)
    print("PROBE 2a: DAILY bar depth 2020-2026 (does barchart know the symbol at all?)")
    print("=" * 100)
    try:
        df = daily_depth()
        df.to_csv(r"C:\Users\chris\clee\ARBS-gcb\notebooks\backtests\intraday_fed_hawk_dove\_probe_daily.csv", index=False)
    except Exception:
        traceback.print_exc()

    print()
    print("=" * 100)
    print("PROBE 2b: MDP.get_data -> RLSTIRFuturePricer at 2025-11-20")
    print("=" * 100)
    try:
        mdp_pricer_path()
    except Exception:
        traceback.print_exc()


if __name__ == "__main__":
    main()

"""Probe: does BARCHART_STIRF-RL serve intraday STIR futures for EUR/GBP/JPY?

Answers three questions that gate the global hawk/dove backtest:
  1. Which contract roots return minute bars, over what date span, in what session hours.
  2. Does STIRFutureQuery + QueryDrivenBacktest price them (rateslib STIRFuture path).
  3. Which direction encoding gives the CORRECT P&L sign for a short (hawk).

Run:  <env>/python.exe _probe_global_stirf.py
"""

from __future__ import annotations

import sys
import datetime
import traceback

sys.path.insert(0, r"C:\Users\chris\clee\ARBS-gcb")

import pandas as pd
import pytz

from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP, _normalize_symbol, _to_barchart_symbol

MONTH_CODES = {3: "H", 6: "M", 9: "U", 12: "Z"}


def nth_quarterly_contract(root: str, ref: datetime.date, n: int) -> str:
    """Nth quarterly contract whose accrual STARTS after `ref`.

    Mirrors Query.Base.imm_resolution.resolve_imm_token semantics: IMM_1 is the
    next quarterly IMM date strictly after ref, so IMM_n x IMM_{n+1} is the
    contract with month code = month of the nth IMM date.
    """
    from rateslib.scheduling import next_imm

    imm = datetime.datetime(ref.year, ref.month, ref.day) + datetime.timedelta(days=1)
    for _ in range(n):
        imm = next_imm(imm)
    return f"{root}{MONTH_CODES[imm.month]}{str(imm.year)[-2:]}"


# root -> (label, tz of its home session)
ROOTS = {
    "SR3": ("USD SOFR 3M (CME)", "America/New_York"),
    "RA": ("EUR ESTR 3M (ICE London)", "Europe/London"),
    "EB": ("EUR ESTR 3M (CME/NYC)", "Europe/London"),
    "J8": ("GBP SONIA 3M (ICE)", "Europe/London"),
    "JU": ("GBP SONIA 1M (ICE)", "Europe/London"),
    "T0": ("JPY TONA 3M (JPX)", "Asia/Tokyo"),
    "IT": ("JPY TONA 3M (TFX)", "Asia/Tokyo"),
}

PROBE_DATES = [
    datetime.date(2021, 6, 15),
    datetime.date(2022, 6, 15),
    datetime.date(2023, 6, 14),
    datetime.date(2024, 6, 12),
    datetime.date(2025, 6, 11),
    datetime.date(2026, 6, 10),
    datetime.date(2026, 8, 5),
]


def probe_minute_coverage() -> pd.DataFrame:
    """Per root x date: how many minute bars, and what session window they cover."""
    mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
    fetcher = mdp._get_barchart_fetcher(required_concurrency=4)

    rows = []
    for root, (label, tzname) in ROOTS.items():
        tz = pytz.timezone(tzname)
        for d in PROBE_DATES:
            sym = nth_quarterly_contract(root, d, 3)
            bc = _to_barchart_symbol(_normalize_symbol(sym) or sym)
            start = tz.localize(datetime.datetime(d.year, d.month, d.day, 0, 0))
            end = tz.localize(datetime.datetime(d.year, d.month, d.day, 23, 59))
            n, lo, hi, px_lo, px_hi = 0, None, None, None, None
            err = ""
            try:
                per_symbol = fetcher.barchart_timeseries_api(
                    barchart_symbols=[bc],
                    start_date=start,
                    end_date=end,
                    interval=1,
                    one_df=False,
                    show_tqdm=False,
                ) or {}
                frame = None
                for _k, v in per_symbol.items():
                    if v is not None and len(v):
                        frame = v
                        break
                if frame is not None and len(frame):
                    idx = frame.index
                    if getattr(idx, "tz", None) is not None:
                        idx = idx.tz_convert(tz)
                    n = len(frame)
                    lo = idx.min().strftime("%H:%M")
                    hi = idx.max().strftime("%H:%M")
                    if "Close" in frame.columns:
                        px_lo = float(frame["Close"].min())
                        px_hi = float(frame["Close"].max())
            except Exception as e:  # noqa: BLE001
                err = f"{type(e).__name__}: {e}"[:110]

            rows.append(
                dict(root=root, label=label, date=d, symbol=sym, barchart=bc,
                     bars=n, first=lo, last=hi, px_lo=px_lo, px_hi=px_hi, err=err)
            )
            print(f"  {root:4s} {d} {sym:8s} bars={n:5d} {lo or '-':>5s}..{hi or '-':<5s} "
                  f"px=[{px_lo}, {px_hi}] {err}", flush=True)
    return pd.DataFrame(rows)


def main() -> None:
    print("=" * 100)
    print("PROBE 1: minute-bar coverage per root (local session tz)")
    print("=" * 100)
    try:
        cov = probe_minute_coverage()
        out = r"C:\Users\chris\clee\ARBS-gcb\notebooks\backtests\intraday_fed_hawk_dove\_probe_coverage.csv"
        cov.to_csv(out, index=False)
        print(f"\nwrote {out}")
        print("\n--- bars by root (sum over probe dates) ---")
        print(cov.groupby(["root", "label"])["bars"].agg(["sum", "min", "max"]).to_string())
    except Exception:
        traceback.print_exc()


if __name__ == "__main__":
    main()

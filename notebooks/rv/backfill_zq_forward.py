"""Backfill the live forward ZQ strip into the serff EOD settle cache.

The serff cache holds the full expired-contract history (2018 → mid-2026) from
the SERFF project; what is missing is the strip a FedWatch tree needs *forward*
of the build date. Live contracts are cache-first with staleness refresh, so
re-running this is idempotent and cheap.
"""
import datetime
import sys

sys.path.insert(0, r"C:\Users\chris\clee\ARBS-xm")

from BT.serff.futures_data import backfill_settles

_MONTHS = "FGHJKMNQUVXZ"


def zq_symbols(start_ym, end_ym):
    (y, m), (y1, m1) = start_ym, end_ym
    out = []
    while (y, m) <= (y1, m1):
        out.append(f"ZQ{_MONTHS[m - 1]}{y % 100:02d}")
        m += 1
        if m == 13:
            m, y = 1, y + 1
    return out


if __name__ == "__main__":
    syms = zq_symbols((2026, 6), (2027, 12))
    print(f"fetching {len(syms)}: {syms}", flush=True)
    out = backfill_settles(
        datetime.date(2024, 1, 1), datetime.date(2026, 8, 1),
        symbols=syms, show_progress=True,
    )
    for s in syms:
        df = out.get(s)
        print(f"  {s}: {'MISSING' if df is None or df.empty else f'{len(df)} rows to {df.index.max().date()}'}",
              flush=True)

"""Pull SOFR + EFFR fixings around 2026-05-04 to anchor the screener."""
from __future__ import annotations

import datetime
import sys

from MDP.IRSwaps.CME_NY_EOD_LIVE.ql_basic.FixingsFetcher import FixingsFetcher


def main():
    sys.stdout.reconfigure(line_buffering=True)
    ff = FixingsFetcher()

    sofr = ff.get_fixings("USD-SOFR-1D")
    effr = ff.get_fixings("USD-OIS")

    cutoff = datetime.datetime(2026, 5, 4)

    sofr_recent = sorted([(d, r) for d, r in sofr.items() if d <= cutoff])[-10:]
    effr_recent = sorted([(d, r) for d, r in effr.items() if d <= cutoff])[-10:]

    print("Last 10 SOFR fixings on/before 2026-05-04:", flush=True)
    for d, r in sofr_recent:
        print(f"  {d.date()}: {r * 100:.4f}%", flush=True)

    print("\nLast 10 EFFR fixings on/before 2026-05-04:", flush=True)
    for d, r in effr_recent:
        print(f"  {d.date()}: {r * 100:.4f}%", flush=True)


if __name__ == "__main__":
    main()

"""Probe whether DTCC is serving historical reports again.

The v3 backfill recorded six days as `ok` with zero rows because DTCC returned
503 and the fetcher swallows it into an empty frame. Those days cannot be
repaired until DTCC serves again. Prints one line: SERVING <n> or DOWN.

Usage: python scripts/_dtcc_probe.py 2026-07-24
"""
from __future__ import annotations

import datetime
import sys
import warnings

warnings.filterwarnings("ignore")

from SDRUtils.data.builder import SDRDataBuilder
from utils.storage_paths import repo_store

CACHE = str(repo_store("sdr_cache", env_var="ARBS_SDR_CACHE_DIR"))


def main() -> int:
    d = datetime.date.fromisoformat(sys.argv[1] if len(sys.argv) > 1 else "2026-07-24")
    b = SDRDataBuilder(cache_path=CACHE, show_tqdm=False)
    try:
        df = b.grab_historical_sdr_trades(
            start_date=d, end_date=d, agency="CFTC", asset_class="RATES",
            one_df=True, ignore_cache=True,
        )
        n = 0 if df is None or getattr(df, "empty", True) else len(df)
    except Exception as exc:  # noqa: BLE001
        print(f"DOWN {d} raised {type(exc).__name__}: {str(exc)[:80]}")
        return 1
    if n > 0:
        print(f"SERVING {d} rows={n}")
        return 0
    print(f"DOWN {d} rows=0")
    return 1


if __name__ == "__main__":
    sys.exit(main())

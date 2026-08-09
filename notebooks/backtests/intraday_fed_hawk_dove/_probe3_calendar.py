"""Probe 3: ForexFactory speaker events for FED / ECB / BOE / BOJ.

What do the titles look like, what are the local-time distributions, and how many
events per bank? Needed to write the speaker-name extractor and the local
market-hours filter.
"""

from __future__ import annotations

import sys
import datetime

sys.path.insert(0, r"C:\Users\chris\clee\ARBS-gcb")

import pandas as pd
import pytz

from RVUtils.forex_factory_calendar import ForexFactoryCalendarFetcher, ForexFactoryTheme

BT_START = "2021-01-01"
BT_END = "2026-08-07"

THEMES = {
    "FED": (ForexFactoryTheme.FED_SPEAKERS, "America/New_York"),
    "ECB": (ForexFactoryTheme.ECB_SPEAKERS, "Europe/Berlin"),
    "BOE": (ForexFactoryTheme.BOE_SPEAKERS, "Europe/London"),
    "BOJ": (ForexFactoryTheme.BOJ_SPEAKERS, "Asia/Tokyo"),
}

OUT = r"C:\Users\chris\clee\ARBS-gcb\notebooks\backtests\intraday_fed_hawk_dove\_probe_calendar.csv"


def main() -> None:
    fetcher = ForexFactoryCalendarFetcher()
    frames = []
    for bank, (theme, tzname) in THEMES.items():
        print(f"\n{'='*90}\n{bank}  theme={theme}  local_tz={tzname}\n{'='*90}", flush=True)
        try:
            df = fetcher.fetch_range(
                BT_START, BT_END, themes=[theme], show_tqdm=False, bulk_chunk_weeks=52
            )
        except Exception as e:  # noqa: BLE001
            print(f"  FETCH FAILED: {type(e).__name__}: {e}")
            continue

        print(f"  rows={len(df)}  cols={list(df.columns)}")
        if not len(df):
            continue

        df = df.copy()
        df["bank"] = bank
        tz = pytz.timezone(tzname)
        ts = pd.to_datetime(df["TimestampNYC"], errors="coerce")
        if getattr(ts.dt, "tz", None) is None:
            ts = ts.dt.tz_localize("America/New_York", nonexistent="shift_forward", ambiguous="NaT")
        df["ts_nyc"] = ts
        df["ts_local"] = ts.dt.tz_convert(tz)
        df["local_hour"] = df["ts_local"].dt.hour

        print(f"  date range: {df['Date'].min()} -> {df['Date'].max()}")
        print(f"  missing timestamps: {df['ts_nyc'].isna().sum()}")
        print("\n  --- 25 sample titles ---")
        for t in df["Title"].dropna().drop_duplicates().head(25):
            print(f"    {t}")
        print("\n  --- local hour histogram ---")
        print(df["local_hour"].value_counts().sort_index().to_string())
        print("\n  --- top 25 title tokens (last word after stripping verbs) ---")
        import re
        last = (
            df["Title"].dropna()
            .map(lambda s: re.sub(r"\b(Speaks?|Testifies|Testimony)\b", "", s).strip().split()[-1]
                 if re.sub(r"\b(Speaks?|Testifies|Testimony)\b", "", s).strip() else "")
        )
        print(last.value_counts().head(25).to_string())
        frames.append(df)

    if frames:
        allf = pd.concat(frames, ignore_index=True)
        keep = [c for c in ["bank", "Date", "TimestampNYC", "ts_local", "local_hour",
                            "Title", "Impact", "Currency", "EventId"] if c in allf.columns]
        allf[keep].to_csv(OUT, index=False)
        print(f"\nwrote {OUT}  ({len(allf)} rows)")


if __name__ == "__main__":
    main()

"""Stage 1: the ForexFactory event calendar -- Fed speakers, US CPI, US NFP.

Deliberately does NOT set ARBS_SUPABASE_ENABLED=0: the ForexFactory core store is
the fetcher's own backing store and forcing it off here would silently narrow the
history this whole panel is built on.

Themes come back WITHOUT a theme column, so each theme is a separate call and the
label is attached on this side.

Target start is 2015-01-01; whatever the fetcher actually serves is what gets
recorded. Writes:
    fed_calendar_raw.parquet   -- every Fed-speaker event, press conferences kept
    cpi_nfp_raw.parquet        -- the two release themes
"""
from __future__ import annotations

import datetime as dt
import os
import pathlib
import re
import sys
import time

sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")

import pandas as pd  # noqa: E402

sys.stdout.reconfigure(line_buffering=True)

OUT = pathlib.Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests"
                   r"\intraday_fed_hawk_dove\_driver_analysis")
START = "2015-01-01"
END = "2026-08-25"

#: Verbatim from global_hawk_dove_common.extract_speaker -- copied rather than
#: imported because importing that module drags in QuantLib, the Barchart MDP and
#: a bar cache none of this stage needs.
_SPEAKER_STRIP = re.compile(r"\b(Speaks?|Testifies|Testimony)\b")


def extract_speaker(title: str) -> str:
    cleaned = _SPEAKER_STRIP.sub("", title or "").strip()
    parts = cleaned.split()
    return parts[-1] if parts else ""


def fetch(theme, label: str) -> pd.DataFrame:
    from RVUtils.forex_factory_calendar import ForexFactoryCalendarFetcher

    t0 = time.time()
    print(f"\n=== {label} : {START} .. {END} ===")
    df = ForexFactoryCalendarFetcher().fetch_range(
        START, END, themes=[theme], bulk_chunk_weeks=52, show_tqdm=False)
    print(f"  {len(df)} rows in {time.time() - t0:.0f}s")
    if df.empty:
        return df
    df = df.copy()
    df["Theme"] = label
    d = pd.to_datetime(df["Date"])
    print(f"  served span: {d.min().date()} .. {d.max().date()}")
    print(f"  rows per year:\n{d.dt.year.value_counts().sort_index().to_string()}")
    return df


def main() -> None:
    from RVUtils.forex_factory_calendar import ForexFactoryTheme

    fed = fetch(ForexFactoryTheme.FED_SPEAKERS, "FED_SPEAKERS")
    if fed.empty:
        raise SystemExit("FED_SPEAKERS returned nothing -- refusing to continue")

    fed["Speaker"] = [extract_speaker(t) for t in fed["Title"].astype(str)]
    fed["is_press_conf"] = (fed["Title"].astype(str)
                            .str.contains("press conference", case=False, na=False))
    fed["Date"] = pd.to_datetime(fed["Date"])
    fed["TimestampNYC"] = pd.to_datetime(fed["TimestampNYC"], utc=True, errors="coerce")

    print(f"\npress conferences flagged: {int(fed['is_press_conf'].sum())}")
    print(f"rows with no TimestampNYC: {int(fed['TimestampNYC'].isna().sum())}")
    print(f"\ntop 30 speakers:\n{fed['Speaker'].value_counts().head(30).to_string()}")
    print(f"\ndistinct titles, sample of 25:")
    for t in fed["Title"].astype(str).drop_duplicates().head(25):
        print(f"  {t}")

    fed.to_parquet(OUT / "fed_calendar_raw.parquet", index=False)
    print(f"\nwrote {OUT / 'fed_calendar_raw.parquet'}  {fed.shape}")

    rel = []
    for theme, label in ((ForexFactoryTheme.US_CPI, "US_CPI"),
                         (ForexFactoryTheme.US_NFP, "US_NFP")):
        r = fetch(theme, label)
        if not r.empty:
            r["Date"] = pd.to_datetime(r["Date"])
            rel.append(r)
    if rel:
        rl = pd.concat(rel, ignore_index=True)
        rl.to_parquet(OUT / "cpi_nfp_raw.parquet", index=False)
        print(f"\nwrote {OUT / 'cpi_nfp_raw.parquet'}  {rl.shape}")
        print(rl.groupby("Theme")["Date"].agg(["count", "min", "max"]).to_string())
    else:
        print("\nWARNING: neither CPI nor NFP returned rows")


if __name__ == "__main__":
    main()

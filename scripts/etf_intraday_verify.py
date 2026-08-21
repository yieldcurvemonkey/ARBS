r"""Measure what the backfill actually put on disk, and where in the day it sits.

Everything here reads the tag cache offline. Nothing touches Excel.

Three things are reported and they are not interchangeable
----------------------------------------------------------
**Minimum spacing proves RESOLUTION.** Bond ``MI01`` is sparse: the median gap is
two minutes even at full one-minute resolution, because that is how often the
bond prints, not how often the vendor samples. A median-spacing test therefore
reports illiquidity as downsampling and would condemn good data. The minimum gap
is the number that can only be one minute if minute data was served.

**Median spacing measures LIQUIDITY**, and is reported next to the minimum for
exactly that reason.

**A tag that returned nothing is not a tag with a gap.** The expected tag list
comes from the universe file, so a bond Citi never served is visible as an absent
row rather than inferred from a short series.

The timezone test is structural, not assumed
--------------------------------------------
Three independent readings, none of which needs an external calendar:

1. *The intraday volatility profile.* US Treasury yields have an unmistakable
   shape: flat overnight, a step at the London/New York handover, a spike into
   the 08:30 New York data release, then a long active session. Which STAMP hour
   the spike lands on says which clock the stamps are on - 08:30 New York is
   12:30 or 13:30 UTC, and the two are not close.
2. *The weekly gap.* The cash Treasury week runs from Sunday evening to Friday
   evening New York time. The stamp hours that bracket the weekly hole locate the
   same clock a second way.
3. *A named 13:00 event.* Treasury auctions close at 13:00 New York. The
   reference table carries every auction date, so the minute-of-day of peak
   one-minute activity on a 30-year auction day is a third, independent reading.

Self-test first
---------------
``--self-test`` runs the spacing measurement over the pre-existing four-day
``MI01`` bond cache, whose resolution is already known to be one minute. A
checker that is itself wrong reports success and hides what it was built to
find, so it is pointed at a known answer before it is pointed at new data.
"""

from __future__ import annotations

import argparse
import datetime
import logging
import pathlib
import sys
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("etf_verify")

REPO = pathlib.Path(__file__).resolve().parents[1]
DATA = REPO / "notebooks" / "backtests" / "etf_rebalance" / "_data"


def tag_of(isin: str, value: str) -> str:
    return f"RATES.BOND.{isin}.{value}"


def spacing_row(tag: str, s: pd.Series) -> dict:
    """Everything measurable about one cached series' shape."""
    if s is None or s.empty:
        return {"tag": tag, "rows": 0}
    d = pd.Series(s.index).diff().dropna()
    idx = pd.Series(s.index)
    # The weekend hole dominates a max-gap statistic and tells you nothing about
    # resolution, so the intraday gap is measured WITHIN a calendar day.
    same_day = d[idx.dt.date.values[1:] == idx.dt.date.values[:-1]]
    return {
        "tag": tag,
        "rows": int(s.size),
        "first": s.index.min(),
        "last": s.index.max(),
        "n_days": int(idx.dt.date.nunique()),
        "min_gap_s": float(d.min().total_seconds()),
        "med_gap_s": float(d.median().total_seconds()),
        "p90_gap_s": float(d.quantile(0.90).total_seconds()),
        "max_gap_h": float(d.max().total_seconds() / 3600.0),
        "intraday_min_gap_s": None if same_day.empty else float(same_day.min().total_seconds()),
        "intraday_med_gap_s": None if same_day.empty else float(same_day.median().total_seconds()),
        "hour_lo": int(idx.dt.hour.min()),
        "hour_hi": int(idx.dt.hour.max()),
        "has_1500": bool((idx.dt.hour == 15).any()),
        "has_1600": bool((idx.dt.hour == 16).any()),
        "vmin": float(np.nanmin(s.to_numpy())),
        "vmax": float(np.nanmax(s.to_numpy())),
    }


def load_cached(cache, tags: List[str], freq: str) -> Dict[str, pd.Series]:
    out = {}
    for t in tags:
        s = cache.read(t, freq, "CLOSE")
        if s is not None and not s.empty:
            out[t] = s.dropna()
    return out


# ------------------------------------------------------------------ #
#                            timezone tests                          #
# ------------------------------------------------------------------ #


def vol_profile(series: Dict[str, pd.Series], *, by: str = "hour") -> pd.DataFrame:
    """Mean absolute one-step yield change by stamp hour (or minute-of-day).

    Only YIELD tags, and only steps that stay inside one calendar day: an
    overnight step would fold the whole session's move into one bucket.
    """
    frames = []
    for tag, s in series.items():
        if not tag.endswith(".YIELD"):
            continue
        d = s.diff()
        idx = pd.Series(s.index)
        same_day = idx.dt.date.values
        keep = np.r_[False, same_day[1:] == same_day[:-1]]
        d = d[keep]
        if d.empty:
            continue
        key = (d.index.hour if by == "hour" else d.index.hour * 60 + d.index.minute)
        frames.append(pd.DataFrame({"key": key, "abs_bp": np.abs(d.to_numpy()) * 100.0}))
    if not frames:
        return pd.DataFrame()
    allf = pd.concat(frames, ignore_index=True)
    g = allf.groupby("key")["abs_bp"].agg(["mean", "median", "count"])
    g.index.name = by
    return g


def weekly_gap(series: Dict[str, pd.Series]) -> pd.DataFrame:
    """Where the weekly hole starts and ends, in STAMP hours."""
    rows = []
    for tag, s in list(series.items())[:12]:
        idx = pd.Series(s.index)
        d = idx.diff()
        big = d[d > pd.Timedelta(hours=24)]
        for pos in big.index:
            rows.append({
                "tag": tag,
                "gap_h": d.loc[pos].total_seconds() / 3600.0,
                "last_before": idx.loc[pos - 1],
                "first_after": idx.loc[pos],
                "last_before_dow": idx.loc[pos - 1].day_name(),
                "last_before_hour": idx.loc[pos - 1].hour,
                "first_after_dow": idx.loc[pos].day_name(),
                "first_after_hour": idx.loc[pos].hour,
            })
    return pd.DataFrame(rows)


def auction_profile(series: Dict[str, pd.Series], auction_dates: List[datetime.date],
                    ) -> pd.DataFrame:
    """Minute-of-day activity on 30-year auction days, which close at 13:00 New York."""
    want = set(auction_dates)
    frames = []
    for tag, s in series.items():
        if not tag.endswith(".YIELD"):
            continue
        idx = pd.Series(s.index)
        mask = idx.dt.date.isin(want).to_numpy()
        if not mask.any():
            continue
        sub = s[mask]
        d = sub.diff()
        same_day = pd.Series(sub.index).dt.date.to_numpy()
        keep = np.r_[False, same_day[1:] == same_day[:-1]]
        d = d[keep]
        if d.empty:
            continue
        frames.append(pd.DataFrame({
            "minute_of_day": d.index.hour * 60 + d.index.minute,
            "abs_bp": np.abs(d.to_numpy()) * 100.0,
        }))
    if not frames:
        return pd.DataFrame()
    allf = pd.concat(frames, ignore_index=True)
    g = allf.groupby("minute_of_day")["abs_bp"].agg(["mean", "count"])
    g["hhmm"] = [f"{m // 60:02d}:{m % 60:02d}" for m in g.index]
    return g


# ------------------------------------------------------------------ #
#                               sanity                               #
# ------------------------------------------------------------------ #


def seam_census(series: Dict[str, pd.Series], *, start_stamped: bool) -> pd.DataFrame:
    """Per bond-day, are BOTH the 15:00 and the 16:00 New York marks present?

    This is the layer's whole justification, so it is counted rather than
    asserted: the cash desk marks at 15:00 New York and the NAV is struck on the
    16:00 close, and a study of that seam needs both ends of it on the same day.

    ``start_stamped`` is not a nicety. Citi's HOURLY bars carry their close at
    the stamp that OPENS them - the value at stamp H equals the minute tape at
    H:59, exactly, on 100.0% of 3,804 bond-day-hours - so the 15:00 and 16:00
    marks live on stamps 14 and 15. Counting stamps 15 and 16 there would census
    the 16:00 and 17:00 marks instead, which is precisely the off-by-one this
    whole verification exists to stop. MI01 is a point tape and needs no shift.
    """
    lo, hi = (14, 15) if start_stamped else (15, 16)
    rows = []
    for tag, s in series.items():
        if not tag.endswith(".YIELD"):
            continue
        idx = pd.Series(s.index)
        day = idx.dt.date
        hour = idx.dt.hour
        have15 = set(day[hour == lo])
        have16 = set(day[hour == hi])
        days = set(day)
        # The denominator has to be BUSINESS days. Citi's bond tape runs from
        # Sunday evening to Saturday morning New York time, so a raw day count
        # includes Sunday-evening and Saturday-morning fragments that could not
        # carry a 15:00 mark and would report a complete layer as 75% complete.
        bdays = {d for d in days if d.weekday() < 5}
        rows.append({
            "tag": tag,
            "days": len(days),
            "bdays": len(bdays),
            "days_1500": len(have15),
            "days_1600": len(have16),
            "days_both": len(have15 & have16),
            "bdays_both": len({d for d in (have15 & have16) if d.weekday() < 5}),
            "frac_both_bdays": (len({d for d in (have15 & have16) if d.weekday() < 5})
                                / len(bdays)) if bdays else 0.0,
        })
    return pd.DataFrame(rows)


def sanity_scan(series: Dict[str, pd.Series]) -> pd.DataFrame:
    from MDP.CitiVelocityExcel.bonds import sanity

    rows = []
    for tag, s in series.items():
        parts = tag.split(".")
        isin, value = parts[2], parts[3]
        bands = sanity.bands_for(isin)
        band = bands.get(value.upper())
        if band is None:
            rows.append({"tag": tag, "value": value, "screened": False, "n": int(s.size),
                         "n_rejected": 0, "vmin": float(s.min()), "vmax": float(s.max())})
            continue
        bad = s[(s < band.lo) | (s > band.hi)]
        rows.append({
            "tag": tag, "value": value, "screened": True, "n": int(s.size),
            "n_rejected": int(bad.size),
            "band": f"{band.lo:g}..{band.hi:g}",
            "vmin": float(s.min()), "vmax": float(s.max()),
            "worst": None if bad.empty else float(bad.iloc[np.abs(bad.to_numpy()).argmax()]),
            "first_bad": None if bad.empty else bad.index.min(),
            "last_bad": None if bad.empty else bad.index.max(),
        })
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ #


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true",
                    help="measure the pre-existing 4-day MI01 bond cache, whose "
                         "resolution is already known, before trusting the measurement")
    ap.add_argument("--layers", nargs="+", default=["hourly", "asof", "mi01"])
    ap.add_argument("--universe", default=str(DATA / "intraday_universe.csv"))
    ap.add_argument("--prefix", default="intraday")
    args = ap.parse_args()

    from MDP.CitiVelocityExcel.cache import CitiVeloTagCache

    cache = CitiVeloTagCache()
    uni = pd.read_csv(args.universe)
    isins = list(dict.fromkeys(uni["isin"].astype(str)))
    pd.set_option("display.width", 220)

    if args.self_test:
        # 349 bonds x PRICE/YIELD over 2026-08-04..07, warmed at MI01 by an
        # earlier run. Known answer: minimum spacing MUST be 60 s.
        stems = sorted((cache.base_dir / "MI01" / "CLOSE").glob("RATES.BOND.*.parquet"))
        sample = [p.stem for p in stems[:60]]
        got = {t: cache.read(t, "MI01", "CLOSE") for t in sample}
        got = {k: v.dropna() for k, v in got.items() if v is not None and not v.empty}
        rows = pd.DataFrame([spacing_row(t, s) for t, s in got.items()])
        log.info("SELF-TEST over %d pre-existing MI01 bond tags", len(rows))
        log.info("min_gap_s  min=%s  median=%s  max=%s",
                 rows["min_gap_s"].min(), rows["min_gap_s"].median(), rows["min_gap_s"].max())
        log.info("med_gap_s  min=%s  median=%s  max=%s",
                 rows["med_gap_s"].min(), rows["med_gap_s"].median(), rows["med_gap_s"].max())
        log.info("date span %s .. %s over %s distinct days",
                 rows["first"].min(), rows["last"].max(), rows["n_days"].max())
        ok = float(rows["min_gap_s"].median()) == 60.0
        log.info("SELF-TEST %s: the checker reports 60 s minimum spacing on data "
                 "known to be one-minute.", "PASSED" if ok else "FAILED")
        # A deliberate mutation: resample one series to 10 minutes and confirm the
        # checker NOTICES. A test that only ever sees good data proves nothing.
        t0 = next(iter(got))
        coarse = got[t0].resample("10min").last().dropna()
        mutated = spacing_row(t0, coarse)
        log.info("MUTATION test: same tag resampled to 10 min -> min_gap_s=%s "
                 "(the checker %s)", mutated["min_gap_s"],
                 "CATCHES it" if mutated["min_gap_s"] >= 600 else "MISSED IT")
        rows.to_csv(DATA / f"{args.prefix}_selftest_mi01_spacing.csv", index=False)
        return 0

    summary = []
    for layer, freq, values in (("hourly", "HOURLY", ("YIELD", "PRICE")),
                                ("asof", "HOURLY", ("ASS_SOFR",)),
                                ("mi01", "MI01", ("YIELD", "PRICE"))):
        if layer not in args.layers:
            continue
        expected = [tag_of(i, v) for v in values for i in isins]
        got = load_cached(cache, expected, freq)
        rows = pd.DataFrame([spacing_row(t, s) for t, s in got.items()])
        missing = [t for t in expected if t not in got]
        if rows.empty:
            log.warning("LAYER %s: NOTHING cached (%d tags expected)", layer, len(expected))
            continue
        rows["layer"] = layer
        path = DATA / f"{args.prefix}_{layer}_coverage.csv"
        rows.sort_values("tag").to_csv(path, index=False)
        log.info("LAYER %s (%s): %d/%d tags served, %d absent -> %s",
                 layer, freq, len(got), len(expected), len(missing), path.name)
        log.info("  rows total %s | date floor %s | last %s",
                 f"{int(rows['rows'].sum()):,}", rows["first"].min(), rows["last"].max())
        log.info("  MIN gap  s: min=%.0f  median=%.0f  p90=%.0f  max=%.0f",
                 rows["min_gap_s"].min(), rows["min_gap_s"].median(),
                 rows["min_gap_s"].quantile(0.9), rows["min_gap_s"].max())
        log.info("  MEDIAN gap s: min=%.0f  median=%.0f  max=%.0f",
                 rows["med_gap_s"].min(), rows["med_gap_s"].median(), rows["med_gap_s"].max())
        log.info("  15:00 stamp present on %d/%d tags; 16:00 on %d/%d",
                 int(rows["has_1500"].sum()), len(rows),
                 int(rows["has_1600"].sum()), len(rows))
        if missing:
            pd.DataFrame({"tag": missing}).to_csv(
                DATA / f"{args.prefix}_{layer}_absent_tags.csv", index=False)
            log.warning("  absent tags (first 10): %s", missing[:10])
        summary.append({"layer": layer, "freq": freq, "tags_expected": len(expected),
                        "tags_served": len(got), "tags_absent": len(missing),
                        "rows": int(rows["rows"].sum()),
                        "floor": rows["first"].min(), "last": rows["last"].max(),
                        "min_gap_s_median": float(rows["min_gap_s"].median()),
                        "med_gap_s_median": float(rows["med_gap_s"].median())})

        # ---- the 15:00 / 16:00 seam, which is what the layer is FOR ----
        seam = seam_census(got, start_stamped=(freq == "HOURLY"))
        if not seam.empty:
            seam.to_csv(DATA / f"{args.prefix}_{layer}_seam_census.csv", index=False)
            log.info("  SEAM: %d yield tags; bond-BUSINESS-days with BOTH a 15:00 and a "
                     "16:00 stamp = %s of %s (%.1f%%)  [all bond-days incl. weekend "
                     "fragments: %s of %s]",
                     len(seam), f"{int(seam['bdays_both'].sum()):,}",
                     f"{int(seam['bdays'].sum()):,}",
                     100.0 * seam["bdays_both"].sum() / max(1, seam["bdays"].sum()),
                     f"{int(seam['days_both'].sum()):,}", f"{int(seam['days'].sum()):,}")

        # ---- sanity ----
        sc = sanity_scan(got)
        sc.to_csv(DATA / f"{args.prefix}_{layer}_sanity.csv", index=False)
        screened = sc[sc["screened"]]
        log.info("  SANITY: %d tags screened (%d unscreenable), %d cells rejected of %s",
                 len(screened), int((~sc["screened"]).sum()),
                 int(screened["n_rejected"].sum()) if len(screened) else 0,
                 f"{int(screened['n'].sum()):,}" if len(screened) else 0)
        if len(screened) and screened["n_rejected"].sum():
            log.warning("  SANITY rejects:\n%s",
                        screened[screened["n_rejected"] > 0].to_string(index=False))

        # ---- timezone ----
        if layer in ("hourly", "mi01"):
            prof = vol_profile(got, by="hour" if layer == "hourly" else "minute")
            if not prof.empty:
                prof.to_csv(DATA / f"{args.prefix}_{layer}_volprofile.csv")
                top = prof["mean"].sort_values(ascending=False).head(6)
                log.info("  VOL PROFILE (mean |1-step move|, bp) top stamp buckets:\n%s",
                         top.to_string())
            wg = weekly_gap(got)
            if not wg.empty:
                wg.to_csv(DATA / f"{args.prefix}_{layer}_weeklygap.csv", index=False)
                log.info("  WEEKLY GAP: %d holes >24h. last-before dow/hour mode=%s/%s, "
                         "first-after dow/hour mode=%s/%s",
                         len(wg), wg["last_before_dow"].mode().iat[0],
                         wg["last_before_hour"].mode().iat[0],
                         wg["first_after_dow"].mode().iat[0],
                         wg["first_after_hour"].mode().iat[0])

        if layer == "mi01":
            covered = {d for s in got.values() for d in pd.Series(s.index).dt.date}
            # ---- named 13:00 New York auctions -----------------------------
            # These are NOT expected to be covered by the month-turn blocks:
            # 30-year auctions land on the 8th-14th and 20-year auctions in the
            # third week, while the blocks run the 24th to the 3rd. Reporting
            # "no auction days found" without saying that would dress a coverage
            # gap up as a failed test.
            ad: list = []
            try:
                from RVUtils.ETFRebalance.bond_panel import reference_frame
                rf = reference_frame()
                rf = rf[rf["cusip"].astype(str).str.upper().isin(
                    pd.read_csv(args.universe)["cusip"].astype(str).str.upper())]
                ad = pd.to_datetime(rf["auction_date"], errors="coerce").dt.date.dropna().tolist()
            except Exception as exc:  # noqa: BLE001
                log.warning("could not load auction dates (%s)", exc)
            hit = sorted(set(ad) & covered)
            log.info("  AUCTION coverage: %d universe auction dates, %d of them inside "
                     "the warmed minute days", len(set(ad)), len(hit))
            aprof = auction_profile(got, hit)
            if not aprof.empty:
                aprof.to_csv(DATA / f"{args.prefix}_mi01_auction_profile.csv")
                log.info("  AUCTION-DAY minute profile (13:00 New York), top 8 by "
                         "mean |1-min move| (bp):\n%s",
                         aprof.sort_values("mean", ascending=False).head(8).to_string())
            else:
                log.info("  AUCTION test: NO auction day is inside the month-turn "
                         "blocks by construction - use the targeted window instead.")

            # ---- named 14:00 New York FOMC, which IS inside the blocks -------
            try:
                from RVUtils.SFRRVLab.panels import FOMC_DATES
                fh = sorted(set(FOMC_DATES) & covered)
                log.info("  FOMC coverage: %d decision dates inside the warmed minute days: %s",
                         len(fh), [str(d) for d in fh])
                fprof = auction_profile(got, fh)
                if not fprof.empty:
                    fprof.to_csv(DATA / f"{args.prefix}_mi01_fomc_profile.csv")
                    log.info("  FOMC-DAY minute profile (statement 14:00 New York), "
                             "top 8 by mean |1-min move| (bp):\n%s",
                             fprof.sort_values("mean", ascending=False).head(8).to_string())
            except Exception as exc:  # noqa: BLE001
                log.warning("FOMC profile skipped (%s)", exc)

            # ---- the 08:30 New York release, on the first Friday of a month --
            nfp = sorted(d for d in covered if d.weekday() == 4 and d.day <= 7)
            log.info("  first-Friday (payrolls, 08:30 New York) days covered: %d", len(nfp))
            nprof = auction_profile(got, nfp)
            if not nprof.empty:
                nprof.to_csv(DATA / f"{args.prefix}_mi01_nfp_profile.csv")
                log.info("  FIRST-FRIDAY minute profile, top 8 by mean |1-min move| (bp):\n%s",
                         nprof.sort_values("mean", ascending=False).head(8).to_string())

    if summary:
        sdf = pd.DataFrame(summary)
        sdf.to_csv(DATA / f"{args.prefix}_layer_summary.csv", index=False)
        print(sdf.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

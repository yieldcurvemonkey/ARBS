"""Per-session data-quality gate.

An adversarial audit of the dataset found three defects that are all SESSION-scoped: a
session whose feed died mid-day, a run of sessions where the tape stopped emitting large
packages, and scattered sessions where the classification mid is displaced by several basis
points. None of them is a property of the study's code -- they are properties of particular
days -- so the response is a session filter rather than a truncated window.

The filter is defined once, from the window's own distribution, and applied to EVERY session
in the window. It never reads the date, so it cannot be gerrymandered toward or away from the
lockout, and it is fixed before any price-test statistic is read.

  D1 TRUNCATED       the last print of the session lands before 14:00 ET.
                     A normal session runs to 16:00-19:00 ET; 2026-07-24's feed stopped at
                     06:55 ET and the whole US cash session is absent from the TAPE, not just
                     from classification, so it cannot be recovered by re-running a backfill.
                     Scheduled early closes are exempted by EARLY_CLOSE below -- a short Good
                     Friday is the market, not a defect.

  D2 PKG_BROKEN      the tape reports ZERO packages with more than four legs.
                     The window norm is 36-64 such packages a day and a maximum package of
                     ~50-200 legs; from 2026-07-21 the maximum is 3 and the count is 0. Large
                     multi-leg structures are arriving torn into standalone trades, each then
                     classified from its own spread-to-mid -- exactly what package handling
                     exists to prevent. Visible downstream as the OUTRIGHT share jumping from
                     ~87% to ~95% and the PKG share falling to precisely zero.

  D3 MID_DISPLACED   |median SIGNED spread-to-mid| on on-market OUTRIGHTs exceeds 2.0 bp.
                     The signed median is the diagnostic: a genuine widening of dealer spreads
                     moves the ABSOLUTE spread and leaves the signed median near zero, so a
                     one-sided several-bp median means the reference mid itself has moved. On
                     a displaced session `dealer_direction` is derived from a wrong mid.

The D3 threshold is not a round number chosen for looking reasonable. Measured over the
2026-01-12..07-29 window the sessions are cleanly bimodal -- 126 clean (median 0.349 bp,
maximum 1.913) against 12 displaced (median 5.283, minimum 2.092) -- and 2.0 sits in the empty
gap between the clusters, so no session is near the boundary and the cut is insensitive to
where in that gap it is placed.
"""
from __future__ import annotations

import dataclasses
import datetime

import pandas as pd

# Sessions the market itself shortens. A short day here is correct behaviour, so D1 must not
# fire on it. 2026-04-03 is Good Friday: the tape ends 11:49 ET with 4 of 9 cash hours, which
# is what an early close looks like and not what a dead feed looks like.
EARLY_CLOSE = frozenset({
    datetime.date(2026, 4, 3),      # Good Friday
    datetime.date(2026, 5, 22),     # Friday before Memorial Day
    datetime.date(2026, 7, 2),      # day before Independence Day observed
    datetime.date(2026, 11, 27),    # day after Thanksgiving
    datetime.date(2026, 12, 24),    # Christmas Eve
})


@dataclasses.dataclass(frozen=True)
class SessionQualityConfig:
    """Thresholds for the three defect detectors. See the module docstring for provenance."""

    enabled: bool = True
    # D1: a normal session's last print is 16:00-19:00 ET. 14:00 is well below every clean
    # session and well above the truncated one, so like D3 it sits in empty space.
    min_last_hour_et: int = 14
    # D2: the window norm is 36-64 packages/day with >4 legs. Requiring at least one is the
    # weakest possible form of the test, which is deliberate -- it fires only on total loss.
    min_large_packages: int = 1
    # D3: see the bimodality note above.
    max_abs_median_spread_bp: float = 2.0
    # A session with almost no on-market outrights cannot support the D3 median. Rather than
    # trust a median of 12 trades, treat the session as unmeasurable and let D1/D2 judge it.
    min_outrights_for_mid_test: int = 50


_SESSION_METRICS_SQL = """
WITH dir AS (
  SELECT as_of_date::date AS session_date,
         count(DISTINCT unit_key) AS units,
         max(execution_timestamp AT TIME ZONE 'America/New_York') AS last_et
  FROM arbs_stir_direction_v1
  WHERE as_of_date BETWEEN %(start)s AND %(end)s
  GROUP BY 1
),
mid AS (
  SELECT as_of_date::date AS session_date,
         count(*) AS n_outrights,
         percentile_cont(0.5) WITHIN GROUP (ORDER BY spread_to_mid_bps) AS median_spread_bp,
         100.0 * avg(CASE WHEN curve_suspect_trade THEN 1 ELSE 0 END) AS pct_suspect
  FROM arbs_stir_direction_v1
  WHERE as_of_date BETWEEN %(start)s AND %(end)s
    AND trade_type = 'OUTRIGHT' AND is_off_market = false
    AND spread_to_mid_bps IS NOT NULL
  GROUP BY 1
),
pk AS (
  SELECT session_date,
         sum(CASE WHEN legs > 4 THEN 1 ELSE 0 END) AS large_packages,
         max(legs) AS max_legs
  FROM (SELECT as_of_date::date AS session_date, package_id, count(*) AS legs
        FROM arbs_usd_swap_tape_legs_v2
        WHERE as_of_date BETWEEN %(start)s AND %(end)s AND package_id IS NOT NULL
        GROUP BY 1, 2) per_package
  GROUP BY 1
)
SELECT dir.session_date, dir.units, dir.last_et,
       mid.n_outrights, mid.median_spread_bp, mid.pct_suspect,
       pk.large_packages, pk.max_legs
FROM dir
LEFT JOIN mid USING (session_date)
LEFT JOIN pk  USING (session_date)
ORDER BY dir.session_date
"""


def assess_sessions(conn, window, config: SessionQualityConfig | None = None) -> pd.DataFrame:
    """Measure every session in `window` and flag the three defects.

    Returns one row per session with the raw metrics beside the flags, so a reader can see
    what each verdict was based on rather than having to trust the boolean.
    """
    config = config or SessionQualityConfig()
    start, end = window
    df = pd.read_sql(_SESSION_METRICS_SQL, conn,
                     params={"start": str(start), "end": str(end)})
    if df.empty:
        return df.assign(d1_truncated=False, d2_pkg_broken=False,
                         d3_mid_displaced=False, excluded=False, reason="")

    df["session_date"] = pd.to_datetime(df["session_date"]).dt.date
    last_hour = pd.to_datetime(df["last_et"]).dt.hour

    is_early_close = df["session_date"].isin(EARLY_CLOSE)
    df["d1_truncated"] = (last_hour < config.min_last_hour_et) & ~is_early_close

    # A session absent from the package table has no evidence either way. Treating missing as
    # broken would fail every session the tape has not yet been ingested for, so require the
    # count to be present AND zero.
    df["d2_pkg_broken"] = df["large_packages"].notna() & \
        (df["large_packages"] < config.min_large_packages)

    testable = df["n_outrights"].fillna(0) >= config.min_outrights_for_mid_test
    df["d3_mid_displaced"] = testable & (
        df["median_spread_bp"].abs() > config.max_abs_median_spread_bp)

    df["excluded"] = df["d1_truncated"] | df["d2_pkg_broken"] | df["d3_mid_displaced"]
    df["reason"] = [
        ",".join(n for n, flag in (("TRUNCATED", r.d1_truncated),
                                   ("PKG_BROKEN", r.d2_pkg_broken),
                                   ("MID_DISPLACED", r.d3_mid_displaced)) if flag)
        for r in df.itertuples()
    ]
    return df


def excluded_sessions(conn, window, config: SessionQualityConfig | None = None) -> set:
    """The set of session dates the gate removes. Empty when the gate is disabled."""
    config = config or SessionQualityConfig()
    if not config.enabled:
        return set()
    table = assess_sessions(conn, window, config)
    if table.empty:
        return set()
    return set(table.loc[table["excluded"], "session_date"])


def summarize(table: pd.DataFrame, lockout_start=None) -> pd.DataFrame:
    """Cost of the gate, split by segment, so its price is reported and not just paid.

    The split matters more than the total: a filter that removes evenly is a loss of power,
    while one that removes mostly from the holdout changes what the holdout can certify.
    """
    if table.empty:
        return pd.DataFrame()
    seg = ["lockout" if (lockout_start and d >= lockout_start) else "in-sample"
           for d in table["session_date"]]
    out = table.assign(segment=seg).groupby("segment").agg(
        sessions=("session_date", "size"),
        kept=("excluded", lambda s: int((~s).sum())),
        units=("units", "sum"),
        units_kept=("units", "sum"),
    )
    kept_units = table[~table["excluded"]].assign(segment=[
        s for s, e in zip(seg, table["excluded"]) if not e]).groupby("segment")["units"].sum()
    out["units_kept"] = kept_units.reindex(out.index).fillna(0).astype(int)
    out["pct_sessions_kept"] = (100.0 * out["kept"] / out["sessions"]).round(1)
    out["pct_units_kept"] = (100.0 * out["units_kept"] / out["units"]).round(1)
    for flag in ("d1_truncated", "d2_pkg_broken", "d3_mid_displaced"):
        out[flag] = table.assign(segment=seg).groupby("segment")[flag].sum()
    return out.reset_index()

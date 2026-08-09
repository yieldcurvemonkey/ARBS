"""Acceptance criteria for the v3 tape backfill (spec section 8).

Five checks:
  1. Day-set parity against v2, pinned to CUTOFF -- v2 is NOT frozen
     during the backfill (sky keeps writing it), so an unrestricted
     comparison fails as soon as sky publishes a day after the backfill
     started. One literal date (2026-07-03) is exempted -- DTCC publishes
     no daily file for the July-4-observed holiday and three production
     fetch attempts through the real window each returned 0 rows -- see
     EXEMPT_MISSING_DAYS for the full justification.
  2. Enrichment markers are populated corpus-wide and per-day.
  3. The 2026-07-24 hole sky left ~80% short is actually filled.
  4. v2 activity since backfill_start, informational only (does NOT fail
     the run -- see below for why).
  4b. v2 non-interference, the actual hard gate: a positive tripwire on
      content, not timestamps.

Criterion 4's predicate is `updated_at > :t0`, not `created_at > :t0`:
ARBS writes via `INSERT ... ON CONFLICT (trade_id) DO UPDATE`, and
neither `created_at` nor `producer` is in that statement's SET list
(confirmed in `ingest_usdswaps_tape.py:_upsert` -- `updated_at = NOW()`
is unconditionally appended to every conflict resolution, while
`created_at`/`producer` are simply absent from `cols` and therefore
never touched), so an ARBS overwrite of an existing sky row leaves both
untouched and invisible to a `created_at`-based check. That was the
dominant clobber mode the original criterion could not detect.

But `updated_at` is bumped by *any* UPSERT, ARBS's or sky's -- and sky's
own INSERTs set `created_at` and `updated_at` to the same instant (both
default to `NOW()`), so a live check against prod on 2026-08-09 found
`updated_at > t0` returning exactly as many rows as `created_at > t0`
(3717 legs, 3022 packages), with zero rows where `updated_at` moved
without `created_at` also moving. Every one of those was sky publishing
new trades, not a clobber -- yet a straightforward `updated_at > t0`
hard-fail would report ACCEPTANCE FAILED on that basis alone, every
single time it is run while sky is live. Restoring the original
`AND producer IS DISTINCT FROM 'swappulse_port'` filter does not fix
this: a clobbered row keeps its original sky-written `producer`, so the
filter would just reintroduce the exact blind spot criterion 4 exists
to close. There is no timestamp-only predicate that is both sensitive
to clobbers and immune to sky's ordinary churn.

4b is that predicate, on content instead of timestamps: the foreign
writer's rows are measurably 0%-enriched with ARBS-only fields
(event_timestamp, special_tenor_type, matched_ust_maturity), verified
live returning 0 today, so ANY nonzero count there is direct,
unambiguous proof ARBS wrote into v2 -- immune to sky's insert/update
volume and to whichever path (fresh INSERT or ON CONFLICT clobber)
ARBS's write took. 4b is therefore the actual hard gate for
v2 non-interference; criterion 4 is printed for human context (trend of
sky's write volume during the run) but does not fail the build.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date

from sqlalchemy import create_engine, text

from SDRUtils._swappulse_scripts import _tape_tables as tt
from SDRUtils._swappulse_scripts.ingest_usdswaps import get_db_connection_string

CUTOFF = "2026-08-07"

V2_LEGS = "arbs_usd_swap_tape_legs_v2"
V2_PACKAGES = "arbs_usd_swap_tape_packages_v2"

# --- Criterion 1 exemption: one date DTCC never published a file for ----
#
# Exempt ONLY this one literal date. Do NOT generalise this to "holidays"
# or "days with few rows" or anything computed -- a rule that generalises
# could silently absorb a real future failure.
#
# 2026-07-03 (Friday -- Independence Day observed, since 2026-07-04 falls
# on a Saturday):
#   DTCC published no daily file. The production per-day fetch window
#   (ingest_usdswaps_tape.py: `end = end_day + timedelta(days=1)`) resolves,
#   via CustomBusinessDay(USFederalHolidayCalendar), to an EMPTY business-day
#   range for 07-03..07-04 (Fri holiday, Sat, Sun all skipped) -- nothing is
#   ever fetched. Confirmed by 3 independent live pipeline attempts
#   (2026-08-08/09), each exit 0 with 0 rows written.
#   v2 holds 2 legs for this date, executed 21:40-21:47 ET on the PRIOR
#   business day (2026-07-02) and bucketed into 07-03 only by UTC calendar
#   date; they reached v2 through a different, untraced ingest path that the
#   current historical-bulk-file fetcher structurally cannot replicate (it
#   never reads a prior day's file).
#
# Combined impact: 2 legs out of ~2.3 million.
#
# --- A warning about the evidence that used to justify a second date ----
#
# 2024-10-14 (Columbus Day) was exempted here too, on the strength of a
# `SDRDataBuilder.grab_historical_sdr_trades(start=2024-10-14, end=2024-10-14)`
# probe returning 0 rows. That probe does NOT reproduce the production
# fetch window: `ingest_usdswaps_tape.py` requests D through D+1 forward,
# and `usd_swaps.py` extends the unfiltered raw pass by another day beyond
# that. The backfill has since processed 2024-10-14 successfully -- v3
# now ties out 3 legs to v2's 3 legs exactly -- because its 3 trades were
# reported in the 2024-10-15 file and bucketed back to 10-14 by execution
# date, a file the `start=D end=D` probe never looked at.
#
# The lesson: a `start=D end=D` probe against a holiday will show a false
# gap whenever the day's trades were actually reported in the following
# business day's file. It proves nothing about what production, which
# fetches D..D+1(+), will find. Do not re-add a date to this set on the
# strength of that probe alone -- confirm against the actual D+1-forward
# window, or better, against a completed production backfill attempt.
EXEMPT_MISSING_DAYS: frozenset[date] = frozenset({
    date(2026, 7, 3),
})


def evaluate_day_parity(
    v3_days: set[date],
    v2_days: set[date],
    exempt: frozenset[date] = EXEMPT_MISSING_DAYS,
) -> tuple[list[str], list[str]]:
    """Pure criterion-1 day-set-parity check. No I/O, easy to unit test.

    Returns ``(report_lines, failures)``:
      * ``report_lines`` is always printed -- an exempted day never passes
        unmentioned, whether it is (as expected) missing from v3 or (which
        would mean the exemption's premise no longer holds) unexpectedly
        present.
      * ``failures`` is non-empty exactly when the criterion should fail:
        any missing day NOT in ``exempt``, or any exempted day that is now
        present in v3 (a signal to remove it from the exemption, not proof
        the exemption was wrong to begin with).
    """
    def _iso(days: list[date]) -> list[str]:
        return [d.isoformat() for d in days]

    missing = v2_days - v3_days
    exempted_missing = sorted(missing & exempt)
    real_missing = sorted(missing - exempt)
    exempt_present = sorted(exempt & v3_days)

    report_lines = [
        f"criterion 1: {len(real_missing)} day(s) missing, "
        f"{len(exempted_missing)} exempted (holiday, no DTCC file): {_iso(exempted_missing)}"
    ]
    failures: list[str] = []
    if exempt_present:
        failures.append(
            "exempted day(s) now present in v3 -- the exemption's premise no "
            f"longer holds, remove from EXEMPT_MISSING_DAYS: {_iso(exempt_present)}"
        )
    if real_missing:
        failures.append(f"missing from v3: {_iso(real_missing)[:20]}")
    return report_lines, failures


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill-start", required=True,
                    help="UTC ISO timestamp recorded before the backfill began.")
    args = ap.parse_args()

    engine = create_engine(get_db_connection_string())
    failures: list[str] = []
    concerns: list[str] = []

    with engine.connect() as c:
        # 1. Day-set parity, pinned to the cutoff. v2 is NOT frozen -- sky
        #    keeps writing it, so an unrestricted comparison fails as soon
        #    as sky publishes a day after the backfill started.
        v3_days = {r[0] for r in c.execute(text(
            f"SELECT DISTINCT as_of_date FROM {tt.LEGS_TABLE} WHERE as_of_date <= :cut"
        ), {"cut": CUTOFF})}
        v2_days = {r[0] for r in c.execute(text(
            f"SELECT DISTINCT as_of_date FROM {V2_LEGS} WHERE as_of_date <= :cut"
        ), {"cut": CUTOFF})}
        print(f"1. days: v3={len(v3_days)} v2={len(v2_days)}")
        day_parity_lines, day_parity_failures = evaluate_day_parity(v3_days, v2_days)
        for line in day_parity_lines:
            print(f"   {line}")
        failures.extend(day_parity_failures)

        # 2. Enrichment markers.
        overall = c.execute(text(
            f"SELECT round(100.0*count(ptp_group_id)/nullif(count(*),0),2) "
            f"FROM {tt.LEGS_TABLE} WHERE as_of_date <= :cut"
        ), {"cut": CUTOFF}).scalar_one()
        print(f"2a. corpus ptp_group_id fill: {overall}%")
        if overall is None or float(overall) < 50.0:
            failures.append(f"corpus ptp fill {overall}% < 50%")

        bad = c.execute(text(f"""
            SELECT as_of_date::text, count(*) n,
                   round(100.0*count(ptp_group_id)/nullif(count(*),0),1)         ptp,
                   round(100.0*count(special_tenor_type)/nullif(count(*),0),1)   spec,
                   round(100.0*count(event_timestamp)/nullif(count(*),0),1)      evt,
                   round(100.0*count(matched_ust_maturity)/nullif(count(*),0),1) ust
            FROM {tt.LEGS_TABLE} WHERE as_of_date <= :cut
            GROUP BY 1
            HAVING round(100.0*count(ptp_group_id)/nullif(count(*),0),1) = 0
                OR round(100.0*count(special_tenor_type)/nullif(count(*),0),1) < 99
                OR round(100.0*count(event_timestamp)/nullif(count(*),0),1) < 99
                OR round(100.0*count(matched_ust_maturity)/nullif(count(*),0),1) < 99
            ORDER BY 1
        """), {"cut": CUTOFF}).fetchall()
        print(f"2b. days below threshold: {len(bad)}")
        if bad:
            failures.append(f"{len(bad)} day(s) below marker thresholds, e.g. {bad[:5]}")

        # 3. The 2026-07-24 hole sky left ~80% short.
        n0724 = c.execute(text(
            f"SELECT count(*) FROM {tt.LEGS_TABLE} WHERE as_of_date = DATE '2026-07-24'"
        )).scalar_one()
        print(f"3. as_of 2026-07-24 legs: {n0724}")
        if n0724 < 2000:
            failures.append(f"2026-07-24 still short: {n0724} legs")

        # 4. v2 activity since backfill_start -- informational, does NOT
        #    fail the run. `updated_at` is bumped by any UPSERT, ARBS's
        #    clobber path included, but it is bumped identically by
        #    sky's own routine INSERTs (created_at and updated_at share
        #    the same NOW() default), so this count is expected to be
        #    nonzero throughout a live run purely from sky publishing
        #    new trades -- confirmed live: 3717/3022 rows on 2026-08-09,
        #    all attributable to fresh sky inserts (updated_at > t0
        #    exactly equalled created_at > t0, zero true updates).
        #    Printed for human trend-watching only; see module docstring
        #    for why no timestamp-only predicate can safely hard-fail
        #    here. 4b below is the actual hard gate.
        for tbl in (V2_LEGS, V2_PACKAGES):
            n = c.execute(text(
                f"SELECT count(*) FROM {tbl} WHERE updated_at > :t0"
            ), {"t0": args.backfill_start}).scalar_one()
            print(f"4. {tbl}: {n} row(s) touched since backfill_start (informational)")
            if n:
                concerns.append(f"{tbl}: {n} row(s) touched since backfill_start (expected: sky's own traffic)")

        # 4b. The actual hard gate: a positive tripwire on content, not
        #     timestamps. The foreign (sky) writer never populates these
        #     ARBS-only columns, so ANY row in v2 carrying one of them is
        #     direct proof ARBS wrote into v2 -- immune to sky's write
        #     volume and to whether ARBS's write was an insert or a
        #     conflict-path clobber. Verified live returning 0 today.
        enriched = c.execute(text("""
            SELECT count(*) FROM arbs_usd_swap_tape_legs_v2
            WHERE as_of_date >= DATE '2026-07-23'
              AND (event_timestamp IS NOT NULL OR special_tenor_type IS NOT NULL
                   OR matched_ust_maturity IS NOT NULL)
        """)).scalar_one()
        print(f"4b. v2 legs carrying ARBS-only enrichment fields: {enriched}")
        if enriched:
            failures.append(
                f"v2 has {enriched} row(s) with ARBS-only enrichment fields populated "
                "-- ARBS wrote to v2"
            )

    if failures:
        print("\nACCEPTANCE FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    if concerns:
        print("\nACCEPTANCE OK WITH CONCERNS (informational, not blocking):")
        for c_ in concerns:
            print(f"  - {c_}")
        return 0
    print("\nACCEPTANCE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

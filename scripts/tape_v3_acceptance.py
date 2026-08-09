"""Acceptance criteria for the v3 tape backfill (spec section 8).

Five checks:
  1. Day-set parity against v2, pinned to CUTOFF -- v2 is NOT frozen
     during the backfill (sky keeps writing it), so an unrestricted
     comparison fails as soon as sky publishes a day after the backfill
     started.
  2. Enrichment markers are populated corpus-wide and per-day.
  3. The 2026-07-24 hole sky left ~80% short is actually filled.
  4. v2 non-interference: no row in v2 has been touched since
     backfill_start. ARBS writes via `INSERT ... ON CONFLICT (trade_id)
     DO UPDATE`, and neither `created_at` nor `producer` is in the
     updated column list -- so an ARBS overwrite of an existing sky row
     leaves both untouched, and a `created_at`-based check stays at 0
     while the dominant clobber mode (overwriting an existing row, not
     inserting a new one) goes completely undetected. `updated_at` IS
     bumped by any UPSERT, ARBS's or sky's, so it is the predicate that
     actually observes write activity against v2.
  4b. A positive tripwire on content, not timestamps: the foreign
      writer's rows are measurably 0%-enriched with ARBS-only fields
      (event_timestamp, special_tenor_type, matched_ust_maturity), so
      ANY nonzero count of those fields being populated in v2 is direct
      proof ARBS wrote into v2 -- immune to whatever ambiguity criterion
      4's timestamp predicate carries.
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import create_engine, text

from SDRUtils._swappulse_scripts import _tape_tables as tt
from SDRUtils._swappulse_scripts.ingest_usdswaps import get_db_connection_string

CUTOFF = "2026-08-07"

V2_LEGS = "arbs_usd_swap_tape_legs_v2"
V2_PACKAGES = "arbs_usd_swap_tape_packages_v2"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill-start", required=True,
                    help="UTC ISO timestamp recorded before the backfill began.")
    args = ap.parse_args()

    engine = create_engine(get_db_connection_string())
    failures: list[str] = []

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
        if v2_days - v3_days:
            failures.append(f"missing from v3: {sorted(v2_days - v3_days)[:20]}")

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

        # 4. v2 non-interference. v2 changes legitimately during the run
        #    (sky keeps writing it); what must hold is that ARBS never
        #    touched it. `updated_at`, not `created_at`, is the correct
        #    predicate: ARBS's `INSERT ... ON CONFLICT (trade_id) DO
        #    UPDATE` does not update `created_at` or `producer`, so an
        #    ARBS overwrite of a pre-existing sky row leaves both
        #    untouched and invisible to a `created_at`-based check --
        #    that was the dominant clobber mode this criterion needed to
        #    catch and could not.
        for tbl in (V2_LEGS, V2_PACKAGES):
            n = c.execute(text(
                f"SELECT count(*) FROM {tbl} WHERE updated_at > :t0"
            ), {"t0": args.backfill_start}).scalar_one()
            print(f"4. {tbl}: {n} row(s) touched since backfill_start")
            if n:
                failures.append(f"{tbl}: {n} row(s) touched since backfill_start")

        # 4b. Positive tripwire, on content rather than timestamps. The
        #     foreign (sky) writer never populates these ARBS-only
        #     columns, so ANY row in v2 carrying one of them is direct
        #     proof ARBS wrote into v2 -- independent of criterion 4's
        #     timestamp reasoning, so it cannot share the same blind
        #     spot.
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
    print("\nACCEPTANCE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

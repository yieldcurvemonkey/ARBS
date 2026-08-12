"""Does the retry wrapper retry the right things and nothing else?

A full publish died 274 days in with

    psycopg2.errors.ReadOnlySqlTransaction:
        cannot execute INSERT in a read-only transaction

and fifty minutes of work went with it, to a condition that cleared by itself
within minutes. The wrapper exists for that. But a retry loop that swallows a
GENUINE error is worse than no retry loop at all -- it turns a clear failure
into the same failure five times, delayed, with the real message buried.

So the classifier is pinned both ways.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2  # noqa: E402

from SDRUtils._swappulse_scripts.backfill_dealer_direction import (  # noqa: E402
    _is_transient,
)

# (exception, must_retry)
CASES = [
    # the one that actually happened
    (psycopg2.errors.ReadOnlySqlTransaction(
        "cannot execute INSERT in a read-only transaction"), True),
    (Exception("cannot execute DELETE in a read-only transaction"), True),
    (Exception("cannot execute TRUNCATE in a read-only transaction"), True),
    (Exception("the database system is in recovery mode"), True),
    (Exception("the database system is starting up"), True),
    (Exception("server closed the connection unexpectedly"), True),
    (Exception("terminating connection due to administrator command"), True),
    (Exception("SSL connection has been closed unexpectedly"), True),
    (Exception("too many connections for role"), True),
    (Exception("deadlock detected"), True),

    # things that will NEVER fix themselves -- retrying is pure delay
    (Exception('column "special_tenor_type" does not exist'), False),
    (Exception("duplicate key value violates unique constraint"), False),
    (Exception('relation "arbs_dd_unit_v1" does not exist'), False),
    (Exception("operator does not exist: date = text"), False),
    (Exception("null value in column violates not-null constraint"), False),
    (Exception("invalid input syntax for type numeric"), False),
    (Exception("permission denied for table"), False),
    (Exception("canceling statement due to statement timeout"), False),
    (ValueError("signed_weight is not 2p-1"), False),
    (AssertionError("the borrowed p landed on the opposite side"), False),
]


def main() -> int:
    bad = []
    for exc, want in CASES:
        got = _is_transient(exc)
        mark = "ok " if got == want else "BAD"
        if got != want:
            bad.append((exc, want, got))
        print(f"  [{mark}] retry={got!s:<5} want={want!s:<5} "
              f"{type(exc).__name__}: {str(exc)[:60]}")
    print()
    if bad:
        print(f"{len(bad)} MISCLASSIFIED:")
        for exc, want, got in bad:
            print(f"  {exc} -> retry={got}, wanted {want}")
        return 1
    print(f"all {len(CASES)} classified correctly "
          f"({sum(1 for _, w in CASES if w)} transient, "
          f"{sum(1 for _, w in CASES if not w)} permanent)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

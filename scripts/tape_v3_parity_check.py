"""Verify the v3 tape schema matches what the pipeline writes.

Three column sets must agree:
  1. v3's actual columns (information_schema)
  2. live v2's columns, minus `producer` (added by the sky writer)
  3. the column list the ingest's INSERT statements build

A column in (3) missing from (1) is silent data loss -- a column never
inserted looks exactly like a column always NULL. That is the only
column-based failure this script raises.

`_v2` has drifted under a foreign writer (the `sky` cron job) beyond the
one known case (`producer`). A column present in v2 but absent from v3
is NOT automatically a defect: if ARBS never wrote it (it is not in the
INSERT column list), it is almost certainly sky-only drift that v3 was
never meant to carry, and failing the build on it would be crying wolf.
So v2-vs-v3 column gaps are split into two groups and reported
separately:
  (a) in v2 AND in the ARBS insert list but missing from v3 -> real
      defect, FAILS the check.
  (b) in v2 but NOT in the ARBS insert list -> sky-only drift candidate,
      reported for human adjudication, does NOT fail the check.

Index parity is checked alongside, because a v3 with zero indexes passes
every column check while being unusable.

The check validates itself against a known answer: `producer` MUST
appear in v2 and in neither v3 nor the insert list. A run that does not
report that is broken, and its "pass" means nothing -- so a successful
self-check prints an explicit PASS line, not just silence.
"""
from __future__ import annotations

import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from SDRUtils._swappulse_scripts import _tape_tables as tt
from SDRUtils._swappulse_scripts.ingest_usdswaps import get_db_connection_string
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import LEG_COLUMNS, PACKAGE_COLUMNS

V2_LEGS = "arbs_usd_swap_tape_legs_v2"
V2_PACKAGES = "arbs_usd_swap_tape_packages_v2"


def _columns(conn: Connection, table: str) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=:t"
            ),
            {"t": table},
        )
    }


def _index_count(conn: Connection, table: str) -> int:
    return conn.execute(
        text("SELECT count(*) FROM pg_indexes WHERE schemaname='public' AND tablename=:t"),
        {"t": table},
    ).scalar_one()


def _index_names(conn: Connection, table: str) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            text("SELECT indexname FROM pg_indexes WHERE schemaname='public' AND tablename=:t"),
            {"t": table},
        )
    }


def _strip_generation(name: str, generation: str) -> str:
    """Normalise an index name by removing its generation infix.

    ``idx_tape_v3_legs_exec`` and ``idx_tape_v2_legs_exec`` both collapse
    to ``idx_tape_legs_exec`` so a v2-vs-v3 index-name diff is meaningful
    even though every name legitimately carries a different generation
    token.
    """
    return name.replace(f"_{generation}_", "_").replace(f"_{generation}", "")


def main() -> int:
    engine = create_engine(get_db_connection_string())
    failures: list[str] = []
    concerns: list[str] = []

    with engine.connect() as conn:
        pairs = [
            ("legs", tt.LEGS_TABLE, V2_LEGS, set(LEG_COLUMNS)),
            ("packages", tt.PACKAGES_TABLE, V2_PACKAGES, set(PACKAGE_COLUMNS)),
        ]
        for label, v3_table, v2_table, insert_cols in pairs:
            v3_cols = _columns(conn, v3_table)
            v2_cols = _columns(conn, v2_table)

            if not v3_cols:
                failures.append(f"{label}: {v3_table} does not exist")
                continue

            # --- self-validation against a known answer -------------------
            # `producer` must be present in v2, and absent from BOTH v3 and
            # the ARBS insert list. Any of those three not holding means the
            # check itself cannot be trusted -- report loudly either way.
            self_check_ok = True
            if "producer" not in v2_cols:
                failures.append(
                    f"{label}: SELF-CHECK FAILED -- `producer` absent from live "
                    f"{v2_table}. The check cannot be trusted; investigate before "
                    "reading any result below."
                )
                self_check_ok = False
            if "producer" in v3_cols:
                failures.append(f"{label}: SELF-CHECK FAILED -- v3 unexpectedly carries `producer`")
                self_check_ok = False
            if "producer" in insert_cols:
                failures.append(
                    f"{label}: SELF-CHECK FAILED -- `producer` unexpectedly appears in "
                    "the ARBS insert column list"
                )
                self_check_ok = False
            if self_check_ok:
                print(
                    f"  [self-check PASS] {label}: `producer` is in live {v2_table}, "
                    "and absent from both v3 and the ARBS insert list, as expected."
                )

            # --- group (a): real defect ------------------------------------
            # Anything ARBS's INSERT statements write that v3 lacks is silent
            # data loss, regardless of whether v2 also has it.
            missing_real = sorted(insert_cols - v3_cols)
            if missing_real:
                failures.append(f"{label}: v3 missing {len(missing_real)} columns ARBS writes: {missing_real}")

            # --- group (b): sky-only drift candidate, report don't fail ---
            v2_minus_v3 = v2_cols - v3_cols
            group_b = sorted(c for c in v2_minus_v3 if c not in insert_cols and c != "producer")
            if group_b:
                concerns.append(
                    f"{label}: {len(group_b)} column(s) in v2 but NOT in the ARBS insert "
                    f"list (excluding the known `producer` drift) -- sky-only drift "
                    f"candidate, needs human adjudication, NOT failing on this: {group_b}"
                )
                print(f"  [group-b ADJUDICATE] {label}: {group_b}")

            not_written = sorted(v3_cols - insert_cols - {"created_at", "updated_at"})
            if not_written:
                print(f"  [note] {label}: in v3 but not in INSERT list: {not_written}")

            v3_idx, v2_idx = _index_count(conn, v3_table), _index_count(conn, v2_table)
            print(f"  {label}: v3 cols={len(v3_cols)} v2 cols={len(v2_cols)} "
                  f"v3 idx={v3_idx} v2 idx={v2_idx}")

            if v3_idx == 0:
                failures.append(
                    f"{label}: v3 has ZERO indexes. Task 2's index parameterisation did "
                    "not take -- do not proceed."
                )
            elif v3_idx < v2_idx:
                v3_names = {_strip_generation(n, tt.TAPE_GENERATION) for n in _index_names(conn, v3_table)}
                v2_names = {_strip_generation(n, "v2") for n in _index_names(conn, v2_table)}
                only_in_v2 = sorted(v2_names - v3_names)
                failures.append(
                    f"{label}: v3 has {v3_idx} indexes vs v2's {v2_idx}. Index names "
                    "are schema-global -- CREATE INDEX IF NOT EXISTS silently skipped. "
                    f"Present on v2 but not (post-infix-strip) on v3: {only_in_v2}"
                )

    if failures:
        print("\nPARITY FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    if concerns:
        print("\nPARITY OK WITH CONCERNS (adjudication needed, not blocking):")
        for c in concerns:
            print(f"  - {c}")
        return 0
    print("\nPARITY OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

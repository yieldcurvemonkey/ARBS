"""USD swap tape v2 — maintenance tool.

One-shot cleanup + permanent health checks for the Postgres tables that
back the ``usd-swaps-tape-v2`` dashboard:

* ``arbs_usd_swap_tape_packages_v1``  (one row per package)
* ``arbs_usd_swap_tape_legs_v1``      (one row per leg / trade_id)
* ``arbs_usd_swap_tape_display_v1``   (view = packages LEFT JOIN legs)

Two legacy-state issues the pre-fix pipeline left behind:

1. **Orphan packages** — a package row whose ``package_id`` has no legs
   pointing at it. Caused by the daily ``CURVE_N`` counter collision
   bug: a later ingest re-classified the same leg under a fresh
   package_id (legs upsert on ``trade_id``), leaving the old package
   row behind. The dashboard shows the orphan but the expander chevron
   is hidden because ``legs_json`` is empty.

2. **Signature duplicates** — two (or more) package rows with different
   ``package_id`` values but identical execution window + tenors + risk
   + rate + spread. Same economic fill reported twice in the tape.

This script:

  - Inventories both issues.
  - Applies the cleanup (transactional DELETE).
  - Re-verifies counts.

Usage:
    conda run -n stir python scripts/usd_swap_tape_maintenance.py --inventory
    conda run -n stir python scripts/usd_swap_tape_maintenance.py --cleanup
    conda run -n stir python scripts/usd_swap_tape_maintenance.py --cleanup --apply   # actually DELETE
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import text
from sqlalchemy.engine import Engine

from SDRUtils._swappulse_scripts.ingest_usdswaps import create_db_engine
from SDRUtils._swappulse_scripts._tape_schema import (
    PACKAGES_TABLE,
    LEGS_TABLE,
    DISPLAY_VIEW,
)


# --- queries ---------------------------------------------------------------

_COUNT_PKGS_SQL = f"SELECT COUNT(*) FROM {PACKAGES_TABLE}"
_COUNT_LEGS_SQL = f"SELECT COUNT(*) FROM {LEGS_TABLE}"

_ORPHAN_IDS_SQL = f"""
SELECT p.package_id
FROM {PACKAGES_TABLE} p
WHERE NOT EXISTS (
    SELECT 1
    FROM {LEGS_TABLE} l
    WHERE l.package_id = p.package_id
)
"""

_DELETE_ORPHANS_SQL = f"""
DELETE FROM {PACKAGES_TABLE} p
WHERE NOT EXISTS (
    SELECT 1
    FROM {LEGS_TABLE} l
    WHERE l.package_id = p.package_id
)
"""

# Signature-duplicate groups: same logical trade, different package_ids.
# We only collapse non-OUTRIGHT rows — OUTRIGHT package_ids are already
# unique-per-trade (``OUTRIGHT-<trade_id>``).
_SIG_DUP_GROUPS_SQL = f"""
SELECT
    execution_start, execution_end, package_type, package_tenors,
    total_risk, weighted_fixed_rate, package_transaction_spread,
    COUNT(*) AS n_pkgs,
    array_agg(package_id ORDER BY package_id) AS package_ids
FROM {PACKAGES_TABLE}
WHERE UPPER(COALESCE(package_type, '')) NOT IN ('', 'OUTRIGHT', 'NONE')
GROUP BY
    execution_start, execution_end, package_type, package_tenors,
    total_risk, weighted_fixed_rate, package_transaction_spread
HAVING COUNT(*) > 1
"""

# For each signature-dup group, keep the variant with the most legs; tie
# break on package_id (deterministic). The others are deleted.
_DELETE_SIG_DUPS_SQL = f"""
WITH groups AS (
    SELECT
        execution_start, execution_end, package_type, package_tenors,
        total_risk, weighted_fixed_rate, package_transaction_spread,
        array_agg(package_id) AS package_ids
    FROM {PACKAGES_TABLE}
    WHERE UPPER(COALESCE(package_type, '')) NOT IN ('', 'OUTRIGHT', 'NONE')
    GROUP BY
        execution_start, execution_end, package_type, package_tenors,
        total_risk, weighted_fixed_rate, package_transaction_spread
    HAVING COUNT(*) > 1
),
ranked AS (
    SELECT
        p.package_id,
        ROW_NUMBER() OVER (
            PARTITION BY p.execution_start, p.execution_end, p.package_type,
                         p.package_tenors, p.total_risk, p.weighted_fixed_rate,
                         p.package_transaction_spread
            ORDER BY (
                SELECT COUNT(*) FROM {LEGS_TABLE} l WHERE l.package_id = p.package_id
            ) DESC, p.package_id ASC
        ) AS rnk
    FROM {PACKAGES_TABLE} p
    JOIN groups g
      ON g.execution_start IS NOT DISTINCT FROM p.execution_start
     AND g.execution_end   IS NOT DISTINCT FROM p.execution_end
     AND g.package_type    IS NOT DISTINCT FROM p.package_type
     AND g.package_tenors  IS NOT DISTINCT FROM p.package_tenors
     AND g.total_risk      IS NOT DISTINCT FROM p.total_risk
     AND g.weighted_fixed_rate IS NOT DISTINCT FROM p.weighted_fixed_rate
     AND g.package_transaction_spread IS NOT DISTINCT FROM p.package_transaction_spread
)
DELETE FROM {PACKAGES_TABLE} WHERE package_id IN (
    SELECT package_id FROM ranked WHERE rnk > 1
)
"""


# --- operations ------------------------------------------------------------

def inventory(engine: Engine) -> dict:
    with engine.connect() as conn:
        n_pkgs = conn.execute(text(_COUNT_PKGS_SQL)).scalar_one()
        n_legs = conn.execute(text(_COUNT_LEGS_SQL)).scalar_one()
        orphan_ids = [row[0] for row in conn.execute(text(_ORPHAN_IDS_SQL)).fetchall()]
        dup_rows = conn.execute(text(_SIG_DUP_GROUPS_SQL)).fetchall()
    return {
        "n_packages": int(n_pkgs),
        "n_legs": int(n_legs),
        "n_orphans": len(orphan_ids),
        "orphan_ids_sample": orphan_ids[:10],
        "n_sig_dup_groups": len(dup_rows),
        "sig_dup_sample": [
            dict(
                execution_start=r[0],
                execution_end=r[1],
                package_type=r[2],
                package_tenors=r[3],
                total_risk=r[4],
                weighted_fixed_rate=r[5],
                package_transaction_spread=r[6],
                n_pkgs=int(r[7]),
                package_ids=list(r[8]),
            )
            for r in dup_rows[:5]
        ],
    }


def print_inventory(inv: dict, *, label: str) -> None:
    print(f"\n=== {label} ===")
    print(f"total packages: {inv['n_packages']:>7,}")
    print(f"total legs:     {inv['n_legs']:>7,}")
    print(f"orphan packages (no legs):  {inv['n_orphans']:>6,}")
    if inv["orphan_ids_sample"]:
        print(f"  sample: {inv['orphan_ids_sample']}")
    print(f"signature-duplicate groups: {inv['n_sig_dup_groups']:>6,}")
    if inv["sig_dup_sample"]:
        for grp in inv["sig_dup_sample"]:
            print(
                f"  {grp['package_type']:<12} {grp['package_tenors']:<10} "
                f"risk={grp['total_risk']} "
                f"rate={grp['weighted_fixed_rate']} "
                f"n_pkgs={grp['n_pkgs']} "
                f"ids={grp['package_ids']}"
            )


def cleanup(engine: Engine, *, apply: bool) -> dict:
    """DB-safe cleanup.

    Only removes orphan package rows — rows with no legs pointing at them.
    Those are pure garbage from the pre-fix ``CURVE_N`` collision bug: a
    later ingest re-assigned the legs to a fresh package_id and the old
    package row was never cleaned up.

    Signature-duplicate packages are NOT deleted here. Their legs are
    live (FK-constrained) and either represent counterparty twin-reports
    (same trade, two reporting sides) or two genuinely different fills
    that happen to tie on all aggregate fields. The UI-side dedup in
    ``useTradeTapeData.dedupeDuplicatePackages`` collapses them for
    display; removing them from the DB would orphan their legs and lose
    information.
    """
    if not apply:
        print("\n-- DRY RUN (use --apply to commit the DELETE statements) --")
        return {"dry_run": True}

    stats: dict = {}
    with engine.begin() as conn:
        result = conn.execute(text(_DELETE_ORPHANS_SQL))
        stats["orphans_deleted"] = result.rowcount
    print(f"orphans deleted:  {stats['orphans_deleted']:>6,}")
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", action="store_true", help="show current state")
    parser.add_argument("--cleanup", action="store_true", help="DELETE orphans + sig-dups")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="commit the DELETE (required with --cleanup for it to actually run)",
    )
    args = parser.parse_args()

    if not (args.inventory or args.cleanup):
        parser.print_help()
        return 2

    engine = create_db_engine()
    try:
        before = inventory(engine)
        print_inventory(before, label="STATE BEFORE")

        if args.cleanup:
            cleanup_stats = cleanup(engine, apply=args.apply)
            if args.apply:
                after = inventory(engine)
                print_inventory(after, label="STATE AFTER")
                delta_orphans = before["n_orphans"] - after["n_orphans"]
                delta_sig_dups = before["n_sig_dup_groups"] - after["n_sig_dup_groups"]
                print(f"\nΔ orphans:          -{delta_orphans:,}")
                print(f"Δ sig-dup groups:   -{delta_sig_dups:,}")
                print(f"Δ packages removed: -{before['n_packages'] - after['n_packages']:,}")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

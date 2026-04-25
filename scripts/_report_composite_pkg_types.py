"""Post-ingest check: count SPREADOVER_* and MATCHED_MATURITY_* composite
package types by day."""
from sqlalchemy import text
from SDRUtils._swappulse_scripts.ingest_usdswaps import create_db_engine
from SDRUtils._swappulse_scripts._tape_schema import PACKAGES_TABLE, LEGS_TABLE


def main() -> None:
    engine = create_db_engine()
    with engine.connect() as conn:
        print("=== Composite package types per day ===")
        rows = conn.execute(
            text(
                f"""
                SELECT as_of_date::text, package_type, COUNT(*) AS n
                FROM {PACKAGES_TABLE}
                WHERE as_of_date BETWEEN '2026-04-06' AND '2026-04-23'
                  AND (package_type LIKE '%\\_CURVE' ESCAPE '\\'
                       OR package_type LIKE '%\\_FLY' ESCAPE '\\')
                GROUP BY as_of_date, package_type
                ORDER BY as_of_date, package_type
                """
            )
        ).fetchall()
        if not rows:
            print("  (no composite PKG types found)")
        current_day = None
        for d, pt, n in rows:
            if d != current_day:
                print(f"\n-- {d} --")
                current_day = d
            print(f"  {pt:<28} {n:>4}")

        print("\n=== Overall package_type distribution (4/6–4/23) ===")
        rows = conn.execute(
            text(
                f"""
                SELECT package_type, COUNT(*) AS n
                FROM {PACKAGES_TABLE}
                WHERE as_of_date BETWEEN '2026-04-06' AND '2026-04-23'
                GROUP BY package_type
                ORDER BY n DESC
                """
            )
        ).fetchall()
        for pt, n in rows:
            print(f"  {pt:<28} {n:>6}")

        n_orphans = conn.execute(
            text(
                f"""
                SELECT COUNT(*) FROM {PACKAGES_TABLE} p
                WHERE NOT EXISTS (
                    SELECT 1 FROM {LEGS_TABLE} l WHERE l.package_id = p.package_id
                )
                """
            )
        ).scalar_one()
        print(f"\nOrphan packages: {n_orphans}")
    engine.dispose()


if __name__ == "__main__":
    main()

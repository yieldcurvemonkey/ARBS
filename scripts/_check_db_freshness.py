"""Check which days in the tape DB have been re-ingested with the current
codebase and which are still stale (pre-fix data)."""
from sqlalchemy import text

from SDRUtils._swappulse_scripts.ingest_usdswaps import create_db_engine
from SDRUtils._swappulse_scripts._tape_schema import PACKAGES_TABLE, LEGS_TABLE


def main() -> None:
    engine = create_db_engine()
    with engine.connect() as conn:
        print("=== Day-by-day package counts ===")
        rows = conn.execute(
            text(
                f"""
                SELECT as_of_date::text AS day,
                       COUNT(*) AS n_pkg,
                       MIN(updated_at) AS first_write,
                       MAX(updated_at) AS last_write
                FROM {PACKAGES_TABLE}
                GROUP BY as_of_date
                ORDER BY as_of_date DESC
                """
            )
        ).fetchall()
        for d, n, first, last in rows:
            print(f"  {d}  n_pkg={n:>5}  last_write={last}")

        print("\n=== Orphan packages ===")
        n_orphans = conn.execute(
            text(
                f"""
                SELECT COUNT(*)
                FROM {PACKAGES_TABLE} p
                WHERE NOT EXISTS (
                    SELECT 1 FROM {LEGS_TABLE} l WHERE l.package_id = p.package_id
                )
                """
            )
        ).scalar_one()
        print(f"  total orphan packages: {n_orphans}")

        print("\n=== Stale-fix signatures (should be ZERO per day after backfill) ===")
        print("Each row = a day still carrying a pre-fix mis-tag")
        rows = conn.execute(
            text(
                f"""
                SELECT
                    l.as_of_date::text AS day,
                    SUM(CASE
                        WHEN p.package_type = 'MATCHED_MATURITY'
                             AND l.forward_label ILIKE 'IMM_%'
                        THEN 1 ELSE 0 END) AS stale_imm_fwd_mms,
                    SUM(CASE
                        WHEN l.is_mac = TRUE
                             AND ABS(ROUND(CAST(l.fixed_rate AS numeric) * 10000)
                                     - CAST(l.fixed_rate AS numeric) * 10000) > 1e-6
                        THEN 1 ELSE 0 END) AS stale_offpar_mac
                FROM {LEGS_TABLE} l
                JOIN {PACKAGES_TABLE} p ON p.package_id = l.package_id
                GROUP BY l.as_of_date
                ORDER BY l.as_of_date DESC
                """
            )
        ).fetchall()
        print(f"  {'day':<12} stale_IMM_fwd_MMS  stale_offpar_MAC")
        for d, imm, mac in rows:
            flag = "" if (int(imm or 0) == 0 and int(mac or 0) == 0) else "  <-- STALE"
            print(f"  {d:<12} {int(imm or 0):>17}  {int(mac or 0):>16}{flag}")

    engine.dispose()


if __name__ == "__main__":
    main()

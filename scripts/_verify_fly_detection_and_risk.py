"""Spot-check: verify the new fly detector + street-convention risk on
the 2026-04-10 IMM_M2026 3Y/5Y/7Y UFRO fly and the 2Y/10Y CURVE headline.
"""
from sqlalchemy import text

from SDRUtils._swappulse_scripts.ingest_usdswaps import create_db_engine
from SDRUtils._swappulse_scripts._tape_schema import PACKAGES_TABLE, LEGS_TABLE


def main() -> None:
    engine = create_db_engine()

    print("=== 2026-04-10 package_type distribution ===")
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT package_type, COUNT(*) AS n
                FROM {PACKAGES_TABLE}
                WHERE as_of_date = '2026-04-10'
                GROUP BY package_type
                ORDER BY n DESC
                """
            )
        ).fetchall()
    for pt, n in rows:
        print(f"  {pt:<20} {n:>5}")

    print("\n=== FLY packages on 2026-04-10 (sample) ===")
    with engine.connect() as conn:
        flys = conn.execute(
            text(
                f"""
                SELECT package_id, package_tenors, total_risk, weighted_fixed_rate,
                       execution_start
                FROM {PACKAGES_TABLE}
                WHERE as_of_date = '2026-04-10'
                  AND package_type = 'FLY'
                ORDER BY execution_start DESC
                LIMIT 10
                """
            )
        ).fetchall()
    for p in flys:
        print(
            f"  {str(p[0]):<42} tenors={p[1]:<12} risk={p[2]:>8.0f} "
            f"rate={p[3]:.4%} at={p[4]}"
        )

    print("\n=== 2Y/10Y CURVE on 2026-04-10 16:49:35 (user's screenshot) ===")
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT p.package_id, p.package_tenors, p.total_risk, p.gross_risk,
                       p.weighted_fixed_rate,
                       (SELECT COUNT(*) FROM {LEGS_TABLE} l WHERE l.package_id = p.package_id) AS n_legs
                FROM {PACKAGES_TABLE} p
                WHERE p.as_of_date = '2026-04-10'
                  AND p.package_type = 'CURVE'
                  AND p.package_tenors = '2Y/10Y'
                  AND p.execution_start::text LIKE '2026-04-10 16:4%'
                """
            )
        ).fetchall()
    for r in rows:
        print(
            f"  {str(r[0]):<42} tenors={r[1]} total_risk={r[2]:>8.0f} "
            f"gross_risk={r[3]:>8.0f} rate={r[4]:.4%} legs={r[5]}"
        )

    print("\n=== IMM_M2026 3Y/5Y/7Y FLY on 2026-04-10 16:48:13 ===")
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT p.package_id, p.package_tenors, p.total_risk,
                       p.weighted_fixed_rate, p.fomc_meeting_label,
                       (SELECT COUNT(*) FROM {LEGS_TABLE} l WHERE l.package_id = p.package_id) AS n_legs,
                       p.execution_start
                FROM {PACKAGES_TABLE} p
                WHERE p.as_of_date = '2026-04-10'
                  AND p.package_type = 'FLY'
                  AND p.package_tenors LIKE '%3Y%'
                  AND p.package_tenors LIKE '%5Y%'
                  AND p.package_tenors LIKE '%7Y%'
                ORDER BY p.execution_start
                """
            )
        ).fetchall()
    if not rows:
        print("  (no 3Y/5Y/7Y fly rows found)")
    for r in rows:
        print(
            f"  {str(r[0]):<42} tenors={r[1]:<12} total_risk={r[2]:>8.0f} "
            f"rate={r[3]:.4%} fomc={r[4]} legs={r[5]} at={r[6]}"
        )

    engine.dispose()


if __name__ == "__main__":
    main()

"""Check the exact trade from the user screenshot: 2026-04-10 15:39:43
IMM_M2026 5Y/30Y CURVE UFRO with a 3.999% 30Y leg. After the fix the 30Y
leg should NOT have is_mac = true and the tape_label should not say MAC.
"""
from sqlalchemy import text

from SDRUtils._swappulse_scripts.ingest_usdswaps import create_db_engine
from SDRUtils._swappulse_scripts._tape_schema import PACKAGES_TABLE, LEGS_TABLE


def main() -> None:
    engine = create_db_engine()
    with engine.connect() as conn:
        print("=== CURVEs executed 2026-04-10 15:39:43 IMM_M2026 5Y/30Y ===")
        rows = conn.execute(
            text(
                f"""
                SELECT package_id, package_tenors, total_risk,
                       weighted_fixed_rate, tape_label, execution_start
                FROM {PACKAGES_TABLE}
                WHERE as_of_date = '2026-04-10'
                  AND package_type = 'CURVE'
                  AND package_tenors LIKE '%5Y%'
                  AND package_tenors LIKE '%30Y%'
                  AND execution_start::text LIKE '2026-04-10 19:39%'
                """
            )
        ).fetchall()
        if not rows:
            print("  (no matching CURVE found)")
        for r in rows:
            print(f"  {r[0]}")
            print(f"    tenors={r[1]}  risk={r[2]:.0f}  rate={r[3]:.4%}")
            print(f"    tape_label: {r[4]}")

            leg_rows = conn.execute(
                text(
                    f"""
                    SELECT trade_id, tenor_label, fixed_rate, is_mac, tape_label
                    FROM {LEGS_TABLE}
                    WHERE package_id = :pid
                    ORDER BY tenor_years
                    """
                ),
                {"pid": r[0]},
            ).fetchall()
            for leg in leg_rows:
                print(
                    f"      leg {leg[0]} {leg[1]:<6} rate={leg[2]:.5%} "
                    f"is_mac={leg[3]} label='{leg[4]}'"
                )
    engine.dispose()


if __name__ == "__main__":
    main()

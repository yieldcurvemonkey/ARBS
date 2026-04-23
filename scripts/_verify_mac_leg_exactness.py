"""Verify leg-level is_mac only fires on exact MAC coupons (whole-bp)."""
from sqlalchemy import text

from SDRUtils._swappulse_scripts.ingest_usdswaps import create_db_engine
from SDRUtils._swappulse_scripts._tape_schema import LEGS_TABLE


def main() -> None:
    engine = create_db_engine()
    with engine.connect() as conn:
        total_mac = conn.execute(
            text(
                f"""
                SELECT COUNT(*) FROM {LEGS_TABLE}
                WHERE as_of_date BETWEEN '2026-04-06' AND '2026-04-10'
                  AND is_mac = TRUE
                """
            )
        ).scalar_one()
        print(f"Total is_mac=True legs (04-06..04-10): {total_mac:,}")

        # A MAC coupon must be a whole-0.1bp value. Any is_mac=True leg
        # whose fixed_rate is not whole-bp is a false positive.
        off_par_mac = conn.execute(
            text(
                f"""
                SELECT trade_id, tenor_label, fixed_rate, tape_label
                FROM {LEGS_TABLE}
                WHERE as_of_date BETWEEN '2026-04-06' AND '2026-04-10'
                  AND is_mac = TRUE
                  AND ABS(ROUND(CAST(fixed_rate AS numeric) * 10000)
                          - CAST(fixed_rate AS numeric) * 10000) > 1e-6
                LIMIT 20
                """
            )
        ).fetchall()

        if off_par_mac:
            print(f"\nFAILED: {len(off_par_mac)} off-par is_mac=True legs")
            for r in off_par_mac:
                print(f"  {r[0]} {r[1]:<6} rate={r[2]:.6%}")
        else:
            print("PASS — all is_mac=True legs have whole-bp coupons")

        # Sample legs per MAC coupon to confirm common MAC rates are still caught.
        print("\n=== MAC leg rate distribution ===")
        sample = conn.execute(
            text(
                f"""
                SELECT ROUND(CAST(fixed_rate AS numeric) * 10000)::int AS rate_bp,
                       COUNT(*) AS n
                FROM {LEGS_TABLE}
                WHERE as_of_date BETWEEN '2026-04-06' AND '2026-04-10'
                  AND is_mac = TRUE
                GROUP BY rate_bp
                ORDER BY n DESC
                LIMIT 15
                """
            )
        ).fetchall()
        for rate_bp, n in sample:
            print(f"  {rate_bp / 100:.2f}%  ({n} legs)")

    engine.dispose()


if __name__ == "__main__":
    main()

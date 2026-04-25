"""Verify IMM-to-IMM forward-starting swaps are no longer flagged MMS."""
from sqlalchemy import text

from SDRUtils._swappulse_scripts.ingest_usdswaps import create_db_engine
from SDRUtils._swappulse_scripts._tape_schema import PACKAGES_TABLE, LEGS_TABLE


def main() -> None:
    engine = create_db_engine()
    with engine.connect() as conn:
        print("=== MMS counts per day (2026-04-06 .. 2026-04-10) ===")
        rows = conn.execute(
            text(
                f"""
                SELECT as_of_date::text, COUNT(*)
                FROM {PACKAGES_TABLE}
                WHERE as_of_date BETWEEN '2026-04-06' AND '2026-04-10'
                  AND package_type = 'MATCHED_MATURITY'
                GROUP BY as_of_date
                ORDER BY as_of_date
                """
            )
        ).fetchall()
        for d, n in rows:
            print(f"  {d}  MMS count: {n}")

        print("\n=== Scan legs for IMM-to-IMM tape labels still flagged MMS ===")
        # Look for legs whose tape_label contains an IMM forward pattern
        # (IMM_H/M/U/Z YYYY) AND are package_type=MATCHED_MATURITY.
        suspicious = conn.execute(
            text(
                f"""
                SELECT l.trade_id, l.tape_label, l.effective_date, l.expiration_date,
                       l.tenor_years
                FROM {LEGS_TABLE} l
                JOIN {PACKAGES_TABLE} p ON p.package_id = l.package_id
                WHERE l.as_of_date BETWEEN '2026-04-06' AND '2026-04-10'
                  AND p.package_type = 'MATCHED_MATURITY'
                  AND l.tape_label ~ '\\mIMM_[HMUZ][0-9]{{4}}\\M'
                LIMIT 20
                """
            )
        ).fetchall()
        if not suspicious:
            print("  CLEAN — no IMM-forward-label MATCHED_MATURITY trades remain")
        else:
            print(f"  {len(suspicious)} IMM-forward-label MMS survivors:")
            for r in suspicious:
                print(f"    {r[0]}  eff={r[2]}  mat={r[3]}  tenor={r[4]}y")
                print(f"      {r[1]}")

        # Also spot-check the user's exact trades from the screenshot.
        print("\n=== User's screenshot trades (4/10 16:00:19 IMM_H2028 1Y) ===")
        cases = conn.execute(
            text(
                f"""
                SELECT l.trade_id, p.package_type, l.effective_date,
                       l.expiration_date, l.tape_label
                FROM {LEGS_TABLE} l
                JOIN {PACKAGES_TABLE} p ON p.package_id = l.package_id
                WHERE l.as_of_date = '2026-04-10'
                  AND l.trade_id IN (
                    '2690349489000000501', '2690349490000000601',
                    '2690349492000000801', '2690349493000000901'
                  )
                ORDER BY l.trade_id
                """
            )
        ).fetchall()
        for r in cases:
            print(f"  {r[0]}  pkg={r[1]}  eff={r[2]}  mat={r[3]}")
            print(f"    {r[4]}")

    engine.dispose()


if __name__ == "__main__":
    main()

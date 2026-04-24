"""Precise check: no IMM-forward-label trades remain tagged MMS."""
from sqlalchemy import text

from SDRUtils._swappulse_scripts.ingest_usdswaps import create_db_engine
from SDRUtils._swappulse_scripts._tape_schema import PACKAGES_TABLE, LEGS_TABLE


def main() -> None:
    engine = create_db_engine()
    with engine.connect() as conn:
        print("=== IMM-forward-label MMS survivors (must be zero) ===")
        survivors = conn.execute(
            text(
                f"""
                SELECT l.trade_id, l.effective_date, l.expiration_date,
                       l.forward_label, l.tape_label
                FROM {LEGS_TABLE} l
                JOIN {PACKAGES_TABLE} p ON p.package_id = l.package_id
                WHERE l.as_of_date BETWEEN '2026-04-06' AND '2026-04-10'
                  AND p.package_type = 'MATCHED_MATURITY'
                  AND l.forward_label ILIKE 'IMM_%'
                LIMIT 20
                """
            )
        ).fetchall()
        if not survivors:
            print("  PASS — no IMM-forward-label trades are MMS")
        else:
            print(f"  FAIL — {len(survivors)} survivors:")
            for r in survivors:
                print(f"    {r[0]}  eff={r[1]}  mat={r[2]}  fwd={r[3]}")

        print("\n=== User's screenshot batch (4/10 16:00:19 IMM_H2028 1Y) ===")
        rows = conn.execute(
            text(
                f"""
                SELECT l.trade_id, p.package_type, l.effective_date,
                       l.expiration_date, l.forward_label, l.tape_label
                FROM {LEGS_TABLE} l
                JOIN {PACKAGES_TABLE} p ON p.package_id = l.package_id
                WHERE l.as_of_date = '2026-04-10'
                  AND l.trade_id IN (
                    '2690349489000000501',
                    '2690349490000000601',
                    '2690349492000000801',
                    '2690349493000000901'
                  )
                ORDER BY l.trade_id
                """
            )
        ).fetchall()
        for r in rows:
            print(f"  {r[0]}  pkg={r[1]}  fwd={r[4]}")
            print(f"    eff={r[2]}  mat={r[3]}")
            print(f"    {r[5]}")

    engine.dispose()


if __name__ == "__main__":
    main()

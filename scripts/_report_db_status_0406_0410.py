"""Post-refresh DB status for 2026-04-06 .. 2026-04-10."""
from sqlalchemy import text

from SDRUtils._swappulse_scripts.ingest_usdswaps import create_db_engine
from SDRUtils._swappulse_scripts._tape_schema import PACKAGES_TABLE, LEGS_TABLE


def main() -> None:
    engine = create_db_engine()
    with engine.connect() as conn:
        print("=== Overall table health ===")
        n_pkgs = conn.execute(text(f"SELECT COUNT(*) FROM {PACKAGES_TABLE}")).scalar_one()
        n_legs = conn.execute(text(f"SELECT COUNT(*) FROM {LEGS_TABLE}")).scalar_one()
        orphans = conn.execute(
            text(
                f"""
                SELECT COUNT(*) FROM {PACKAGES_TABLE} p
                WHERE NOT EXISTS (
                    SELECT 1 FROM {LEGS_TABLE} l WHERE l.package_id = p.package_id
                )
                """
            )
        ).scalar_one()
        print(f"total packages: {n_pkgs:>7,}")
        print(f"total legs:     {n_legs:>7,}")
        print(f"orphan packages: {orphans:>6,}")

        print("\n=== Per-day breakdown (2026-04-06 .. 2026-04-10) ===")
        rows = conn.execute(
            text(
                f"""
                SELECT as_of_date::text, package_type, COUNT(*) AS n
                FROM {PACKAGES_TABLE}
                WHERE as_of_date BETWEEN '2026-04-06' AND '2026-04-10'
                GROUP BY as_of_date, package_type
                ORDER BY as_of_date, package_type
                """
            )
        ).fetchall()
        current_day = None
        for d, pt, n in rows:
            if d != current_day:
                print(f"\n-- {d} --")
                current_day = d
            print(f"  {pt:<20} {n:>5}")

        print("\n=== MAC cleanup: 3.999% no longer tagged MAC ===")
        mac_false_positives = conn.execute(
            text(
                f"""
                SELECT p.package_id, p.package_tenors, p.tape_label,
                       p.weighted_fixed_rate, p.package_type
                FROM {PACKAGES_TABLE} p
                WHERE p.as_of_date BETWEEN '2026-04-06' AND '2026-04-10'
                  AND p.tape_label ILIKE '%MAC%'
                  AND ABS(ROUND(CAST(p.weighted_fixed_rate AS numeric) * 10000)
                          - CAST(p.weighted_fixed_rate AS numeric) * 10000) > 0.01
                LIMIT 5
                """
            )
        ).fetchall()
        if mac_false_positives:
            print(f"  WARNING: {len(mac_false_positives)} off-par MAC tag still present")
            for r in mac_false_positives:
                print(f"    {r[0]}  rate={r[3]:.5%}")
        else:
            print("  OK — no off-par (non-whole-bp) MAC tags remain")

        print("\n=== FLY count (detector second-pass improvement) ===")
        fly_rows = conn.execute(
            text(
                f"""
                SELECT as_of_date::text, COUNT(*) AS n_fly
                FROM {PACKAGES_TABLE}
                WHERE as_of_date BETWEEN '2026-04-06' AND '2026-04-10'
                  AND package_type = 'FLY'
                GROUP BY as_of_date
                ORDER BY as_of_date
                """
            )
        ).fetchall()
        for d, n in fly_rows:
            print(f"  {d}  FLY count: {n}")

    engine.dispose()


if __name__ == "__main__":
    main()

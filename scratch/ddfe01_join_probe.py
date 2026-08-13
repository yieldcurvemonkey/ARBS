"""Does the dealer-direction `unit_key` join the tape display view 1:1?

The brief asserts it does: `arbs_usd_swap_tape_display_v3` is package-grained
with primary key `package_id`, and `universe.unit_frame` sets
``unit_key = trade_id`` for singletons and ``package_id`` for packages. If the
display view's `package_id` is a *synthetic* singleton key rather than the
trade id, or if the view drops rows the universe keeps (or vice versa), the
front end's "one direction per rendered row" premise is wrong and the whole
display design has to change.

Measured, not assumed. Run:

    set ARBS_SUPABASE_ENABLED=0
    C:/Users/chris/anaconda3/envs/stir/python.exe scratch/ddfe01_join_probe.py 2026-04-01
"""
from __future__ import annotations

import os
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd  # noqa: E402
import psycopg2  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url  # noqa: E402
from SDRUtils.dealer_direction import universe as U  # noqa: E402


def _read(conn, sql, **params) -> pd.DataFrame:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql(sql, conn, params=params or None)


def main(day: str) -> int:
    conn = psycopg2.connect(resolve_pg_url())

    # --- 0. what IS the display view? -----------------------------------
    cols = _read(conn, """
        SELECT table_name, table_type
        FROM information_schema.tables
        WHERE table_name LIKE 'arbs_usd_swap_tape%%'
        ORDER BY table_name
    """)
    print("tape objects:")
    print(cols.to_string(index=False))
    print()

    disp_cols = _read(conn, """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'arbs_usd_swap_tape_display_v3'
        ORDER BY ordinal_position
    """)
    print(f"display view: {len(disp_cols)} columns")
    print(", ".join(disp_cols["column_name"].tolist()))
    print()

    # --- 1. the view's own grain ----------------------------------------
    grain = _read(conn, """
        SELECT count(*) AS n_rows,
               count(DISTINCT package_id) AS n_pkg,
               count(*) FILTER (WHERE package_id IS NULL) AS n_null_pkg
        FROM arbs_usd_swap_tape_display_v3
        WHERE as_of_date = %(d)s
    """, d=day)
    print(f"display view on {day}:")
    print(grain.to_string(index=False))
    print()

    # --- 2. the universe's unit keys ------------------------------------
    legs = U.load_legs(conn, day, day)
    print(f"legs on {day}: {len(legs):,}")
    units = U.unit_frame(legs)
    print(f"units on {day}: {len(units):,}  "
          f"(kept {int(units['exclusion'].isna().sum()):,})")
    print()

    # --- 3. the join ----------------------------------------------------
    view_keys = _read(conn, """
        SELECT package_id, n_legs, structure_type, is_package
        FROM arbs_usd_swap_tape_display_v3
        WHERE as_of_date = %(d)s
    """, d=day) if "is_package" in set(disp_cols["column_name"]) else _read(conn, """
        SELECT package_id FROM arbs_usd_swap_tape_display_v3
        WHERE as_of_date = %(d)s
    """, d=day)

    vk = set(view_keys["package_id"].astype(str))
    uk = set(units["unit_key"].astype(str))

    print(f"view keys      : {len(vk):,}")
    print(f"unit keys      : {len(uk):,}")
    print(f"intersection   : {len(vk & uk):,}")
    print(f"view only      : {len(vk - uk):,}")
    print(f"units only     : {len(uk - vk):,}")
    print(f"MATCH RATE (units matched by the view): "
          f"{100.0 * len(vk & uk) / max(len(uk), 1):.4f}%")
    print()

    if vk - uk:
        sample = sorted(vk - uk)[:10]
        print("view-only sample:", sample)
        got = _read(conn, """
            SELECT * FROM arbs_usd_swap_tape_display_v3
            WHERE as_of_date = %(d)s AND package_id = ANY(%(k)s)
            LIMIT 5
        """, d=day, k=sample[:5])
        with pd.option_context("display.max_columns", 200, "display.width", 250):
            print(got.head().T.to_string())
        print()
    if uk - vk:
        sample = sorted(uk - vk)[:10]
        print("unit-only sample:", sample)
        print(units[units["unit_key"].astype(str).isin(sample)]
              [["unit_key", "package_id", "kind", "n_legs", "exclusion"]]
              .head(10).to_string(index=False))
        print()

    # --- 4. singleton keys: trade_id or synthetic? ----------------------
    singles = units[units["n_legs"] <= 1]
    print(f"singleton units: {len(singles):,}; "
          f"{100.0 * singles['unit_key'].astype(str).isin(vk).mean():.4f}% found in view")
    multis = units[units["n_legs"] > 1]
    print(f"package units  : {len(multis):,}; "
          f"{100.0 * multis['unit_key'].astype(str).isin(vk).mean():.4f}% found in view")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "2026-04-01"))

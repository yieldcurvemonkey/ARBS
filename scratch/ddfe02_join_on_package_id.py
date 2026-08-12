"""Probe 1 refuted the brief's join. This one measures the join that works.

`ddfe01` found: on 2026-04-01 the display view and `universe.unit_frame` agree
on the *grain* exactly (2,752 rows each) but agree on only 27.47% of the
*keys*, because a single-leg print that nonetheless carries a package id --
`MATCHED_MATURITY_2577667463000017801` and friends -- is keyed by that
package id in the view and by its raw `trade_id` in `unit_key`
(``universe.py:614``: ``np.where(n_legs <= 1, first_trade_id, index)``).

So the join key is `package_id`, which the unit frame also carries. Measure
that, on more than one day, and check the reverse direction too: does every
view row find a unit, and is the correspondence 1:1 rather than merely
same-sized?
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

DAYS = ["2024-07-01", "2025-01-15", "2025-10-17", "2026-04-01", "2026-08-07"]


def _read(conn, sql, **params) -> pd.DataFrame:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql(sql, conn, params=params or None)


def main(days: list[str]) -> int:
    conn = psycopg2.connect(resolve_pg_url())
    rows = []
    for day in days:
        view = _read(conn, """
            SELECT package_id, n_package_legs, legs_count, venue,
                   contributes_to_flow_any, economic_class_primary
            FROM arbs_usd_swap_tape_display_v3
            WHERE as_of_date = %(d)s
        """, d=day)
        legs = U.load_legs(conn, day, day)
        if len(legs) == 0:
            print(f"{day}: NO LEGS -- skipping (this is a data gap, not a pass)")
            continue
        units = U.unit_frame(legs)

        vk = view["package_id"].astype(str)
        pk = units["package_id"].astype(str)
        uk = units["unit_key"].astype(str)

        vset, pset = set(vk), set(pk)
        rows.append({
            "day": day,
            "view_rows": len(view),
            "view_uniq": vk.nunique(),
            "unit_rows": len(units),
            "unit_pkg_uniq": pk.nunique(),
            "match_on_package_id_pct": 100.0 * len(vset & pset) / max(len(pset), 1),
            "view_only": len(vset - pset),
            "unit_only": len(pset - vset),
            "match_on_unit_key_pct": 100.0 * len(vset & set(uk)) / max(uk.nunique(), 1),
            "kept_units": int(units["exclusion"].isna().sum()),
        })
        print(f"{day}: view {len(view):,} / units {len(units):,} -> "
              f"package_id match {rows[-1]['match_on_package_id_pct']:.4f}%  "
              f"(unit_key match {rows[-1]['match_on_unit_key_pct']:.4f}%)",
              flush=True)
        if vset - pset:
            print("   view-only:", sorted(vset - pset)[:5])
        if pset - vset:
            print("   unit-only:", sorted(pset - vset)[:5])

    conn.close()
    print()
    out = pd.DataFrame(rows)
    with pd.option_context("display.width", 220, "display.max_columns", 30):
        print(out.to_string(index=False))
    if out.empty:
        print("NO DAYS MEASURED -- failure, not a pass.")
        return 2
    worst = out["match_on_package_id_pct"].min()
    print(f"\nWORST package_id match rate: {worst:.4f}%")
    return 0 if worst >= 99.99 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or DAYS))

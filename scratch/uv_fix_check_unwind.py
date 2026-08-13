"""READ-ONLY: is ECONOMIC_UNWIND actually present in 2026-06-01..12, and does
annotate_legs see it?"""
import os
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd
import psycopg2

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils.dealer_direction import universe

pd.set_option("display.width", 240)
conn = psycopg2.connect(resolve_pg_url())


def q(sql):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql(sql, conn)


print("economic_class by month, whole tape")
print(q(f"""
    SELECT date_trunc('month', as_of_date)::date m, economic_class, count(*) n
    FROM {LEGS_TABLE} WHERE economic_class <> 'ECONOMIC_FLOW'
    GROUP BY 1,2 ORDER BY 1 DESC LIMIT 20
""").to_string(index=False))

print()
print("2026-06-01..12 slice")
print(q(f"""
    SELECT economic_class, count(*) n FROM {LEGS_TABLE}
    WHERE as_of_date BETWEEN '2026-06-01' AND '2026-06-12'
    GROUP BY 1 ORDER BY 2 DESC
""").to_string(index=False))

# pick a range that HAS unwinds and run it through the real code path
d = q(f"""
    SELECT min(as_of_date) lo, max(as_of_date) hi, count(*) n
    FROM {LEGS_TABLE} WHERE economic_class = 'ECONOMIC_UNWIND'
""")
print()
print("ECONOMIC_UNWIND date span:", d.to_dict("records"))
lo = pd.Timestamp(d["lo"].iloc[0]).date()

legs = universe.load_legs(conn, lo, lo)
print(f"\nloaded {len(legs)} legs for {lo}")
print(legs["economic_class"].value_counts(dropna=False).to_string())
ann = universe.annotate_legs(legs)
print("_is_unwind legs:", int(ann["_is_unwind"].sum()))
u = universe.unit_frame(legs)
print("is_unwind units:", int(u["is_unwind"].sum()),
      " kept:", int(u.loc[u["exclusion"].isna(), "is_unwind"].sum()))
rep = universe.aggregate_units(u)
print("rep unwind_units_kept:", rep["unwind_units_kept"],
      " lifecycle_units_kept:", rep["lifecycle_units_kept"],
      " kept:", rep["kept_units"])
conn.close()
print("DONE")

"""Checks the summary table cannot make: did the filters do what they claim?

Four things a headline count would hide:
  V1. every one of the 55 notional-sentinel legs lands in an EXCLUDED unit;
  V2. the vectorised report path and ``build_units`` agree on REAL data,
      not just on the synthetic frame the pytest suite uses;
  V3. what actually happens to the 15 UWIN legs;
  V4. the venue extension moves the populations it says it moves.
"""
from __future__ import annotations

import os
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils.dealer_direction import universe as un

pd.set_option("display.width", 220)
pd.set_option("display.max_rows", 120)
conn = psycopg2.connect(resolve_pg_url())


def q(sql):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql(sql, conn)


def head(t):
    print()
    print("=" * 88)
    print(t)
    print("=" * 88)


# --- V1 ---------------------------------------------------------------------
head("V1. the 55 notional-sentinel legs -- which unit exclusion did they get?")
days = q(f"SELECT DISTINCT as_of_date FROM {LEGS_TABLE} WHERE notional >= 1e11"
         ).sort_values("as_of_date")["as_of_date"].tolist()
sent_ids = set(q(f"SELECT trade_id FROM {LEGS_TABLE} WHERE notional >= 1e11"
                 )["trade_id"])
print(f"  sentinel legs {len(sent_ids)} across {len(days)} as_of_dates")

rows = []
for d in days:
    legs = un.load_legs(conn, d, d)
    ann = un.annotate_legs(legs)
    u = un.unit_frame(legs)
    hit = ann[ann["trade_id"].isin(sent_ids)]
    for _, leg in hit.iterrows():
        ur = u.loc[leg["_unit_group"]]
        rows.append({"as_of_date": d, "trade_id": leg["trade_id"],
                     "n_legs": int(ur["n_legs"]),
                     "exclusion": ur["exclusion"],
                     "detail": ur["exclusion_detail"]})
sent = pd.DataFrame(rows)
print(sent.groupby(["exclusion", "detail"], dropna=False).size().to_string())
kept_sent = sent["exclusion"].isna().sum()
print(f"  sentinel legs whose unit was KEPT: {kept_sent}  "
      f"{'<-- DEFECT' if kept_sent else '(none, as required)'}")

# --- V2 ---------------------------------------------------------------------
head("V2. report path vs build_units, on real days")
for d in ["2024-03-01", "2024-10-07", "2025-08-11", "2026-04-15", "2026-06-16"]:
    legs = un.load_legs(conn, d, d)
    u = un.unit_frame(legs)
    units, excl = un.build_universe(legs)
    kept_frame = int(u["exclusion"].isna().sum())
    ok = (kept_frame == len(units)) and (len(excl) == int(u["exclusion"].notna().sum()))
    # and the Unit objects themselves must be internally consistent
    leg_total = sum(x.n_legs for x in units) + int(
        u.loc[u["exclusion"].notna(), "n_legs"].sum())
    print(f"  {d}  legs {len(legs):>6,}  units {len(u):>6,}  "
          f"kept(frame) {kept_frame:>6,}  kept(objects) {len(units):>6,}  "
          f"legs re-summed {leg_total:>6,}  {'OK' if ok and leg_total == len(legs) else 'MISMATCH'}")
    if d == "2026-06-16" and units:
        s = units[0]
        print(f"    sample unit  key={s.unit_key}  kind={s.kind}  "
              f"venue={s.venue_class}  idx={s.rate_index}  "
              f"upfront={s.upfront} ({s.upfront_source})  lifecycle={s.is_lifecycle}")
        print(f"    clocks  pricing={s.clocks.pricing}  event={s.clocks.event}")
        print(f"            visibility={s.clocks.visibility} "
              f"[{s.clocks.visibility_source}]")

# --- V3 ---------------------------------------------------------------------
head("V3. the UWIN legs -- what the routing change actually buys")
uw = q(f"""
    SELECT as_of_date, trade_id, package_id, lifecycle_type, economic_class,
           other_payment_uwin, other_payment_ufro, package_transaction_price
    FROM {LEGS_TABLE} WHERE coalesce(other_payment_uwin,0) <> 0
    ORDER BY as_of_date
""")
print(f"  legs with a non-zero other_payment_uwin, whole tape: {len(uw)}")
print(uw.to_string(index=False))
got_uwin = 0
for d in sorted(set(uw["as_of_date"])):
    legs = un.load_legs(conn, d, d)
    u = un.unit_frame(legs)
    sub = u[u["upfront_source"] == un.UPFRONT_UWIN]
    got_uwin += len(sub)
print(f"  units whose upfront ends up sourced from UWIN: {got_uwin}")
pexh = q(f"SELECT count(*) n FROM {LEGS_TABLE} "
         "WHERE coalesce(other_payment_pexh,0) <> 0")["n"].iloc[0]
print(f"  legs with a non-zero other_payment_pexh (never aggregated): {pexh}")
term_ufro = q(f"""
    SELECT count(*) n_term,
           count(*) FILTER (WHERE coalesce(other_payment_ufro,0)<>0) n_with_ufro
    FROM {LEGS_TABLE}
    WHERE lifecycle_type='TERMINATION' AND contributes_to_flow
""")
print("  terminations already carrying a UFRO (the brief said there were none):")
print("   ", term_ufro.to_string(index=False).replace("\n", "\n    "))

# --- V4 ---------------------------------------------------------------------
head("V4. what the venue extension moves")
pf = q(f"""
    SELECT coalesce(platform_identifier,'(null)') pid, count(*) n
    FROM {LEGS_TABLE}
    WHERE economic_class='ECONOMIC_FLOW' AND contributes_to_flow
    GROUP BY 1
""")
old_d2c = {"TWSF", "BBSF", "BILT"}
old_d2d = {"BGCD", "DWSF", "IGDL", "ISWV", "TPSE", "TSEF"}
pf["old"] = [
    "D2C" if p in old_d2c else "D2D" if p in old_d2d else "VENUE_UNKNOWN"
    for p in pf["pid"]]
pf["new"] = [un.classify_venue(p) for p in pf["pid"]]
moved = pf[pf["old"] != pf["new"]]
print(pf.groupby(["old", "new"])["n"].sum().to_string())
print()
print("  platforms that changed class:")
print(moved.sort_values("n", ascending=False).to_string(index=False))
print()
print("  remaining VENUE_UNKNOWN, by evidence tier:")
unk = pf[pf["new"] == "VENUE_UNKNOWN"].copy()
unk["tier"] = [un.venue_evidence(p) for p in unk["pid"]]
print(unk.groupby("tier")["n"].agg(["sum", "size"]).to_string())
print()
print(unk.sort_values("n", ascending=False).head(12).to_string(index=False))

conn.close()
print("\ndone")

"""Measure dealer_spread_bps / opa_* distributions on the v3 tape (READ ONLY)."""
import os
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import psycopg2
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE, PACKAGES_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

conn = psycopg2.connect(resolve_pg_url())
cur = conn.cursor()

print("PACKAGES_TABLE =", PACKAGES_TABLE, "| LEGS_TABLE =", LEGS_TABLE)

# --- 0. which table actually carries which column (validation of premise) ---
cur.execute("""
    SELECT table_name, column_name
      FROM information_schema.columns
     WHERE table_name IN (%s, %s)
       AND (column_name LIKE 'opa%%' OR column_name LIKE 'dealer_spread%%'
            OR column_name LIKE 'other_payment%%' OR column_name = 'ptp_price_notation')
     ORDER BY table_name, column_name
""", (PACKAGES_TABLE, LEGS_TABLE))
print("\n--- 0. column placement ---")
for r in cur.fetchall():
    print(f"  {r[0]}.{r[1]}")

# --- 1. tier counts (validation anchor vs LEDGER F-5: EXACT 39,821 / TIGHT 37,365) ---
cur.execute(f"""
    SELECT COALESCE(opa_sign_confidence, '(null)') AS tier,
           count(*) AS n,
           count(dealer_spread_bps) AS n_bps,
           count(dealer_spread_est) AS n_est,
           avg(opa_ptp_residual)::float8 AS mean_resid,
           avg(dealer_spread_bps)::float8 AS mean_bps
      FROM {PACKAGES_TABLE}
     GROUP BY 1 ORDER BY 2 DESC
""")
print("\n--- 1. tier counts (anchor: LEDGER F-5 EXACT 39,821 / TIGHT 37,365) ---")
print(f"  {'tier':<12}{'n':>10}{'n_bps':>10}{'n_est':>10}{'mean_resid':>14}{'mean_bps':>12}")
for t, n, nb, ne, mr, mb in cur.fetchall():
    print(f"  {t:<12}{n:>10}{nb:>10}{ne:>10}"
          f"{(f'{mr:.4g}' if mr is not None else 'NULL'):>14}"
          f"{(f'{mb:.6g}' if mb is not None else 'NULL'):>12}")

# --- 2. dealer_spread_bps distribution per tier ---
cur.execute(f"""
    SELECT opa_sign_confidence AS tier,
           count(dealer_spread_bps) AS n,
           count(*) FILTER (WHERE dealer_spread_bps < 0)  AS n_neg,
           count(*) FILTER (WHERE dealer_spread_bps = 0)  AS n_zero,
           min(dealer_spread_bps)::float8,
           percentile_cont(0.01) WITHIN GROUP (ORDER BY dealer_spread_bps)::float8,
           percentile_cont(0.25) WITHIN GROUP (ORDER BY dealer_spread_bps)::float8,
           percentile_cont(0.50) WITHIN GROUP (ORDER BY dealer_spread_bps)::float8,
           percentile_cont(0.75) WITHIN GROUP (ORDER BY dealer_spread_bps)::float8,
           percentile_cont(0.90) WITHIN GROUP (ORDER BY dealer_spread_bps)::float8,
           percentile_cont(0.99) WITHIN GROUP (ORDER BY dealer_spread_bps)::float8,
           max(dealer_spread_bps)::float8
      FROM {PACKAGES_TABLE}
     WHERE dealer_spread_bps IS NOT NULL
     GROUP BY 1 ORDER BY 1
""")
print("\n--- 2. dealer_spread_bps distribution ---")
hdr = ["tier", "n", "n<0", "n=0", "min", "p1", "p25", "p50", "p75", "p90", "p99", "max"]
print("  " + "".join(f"{h:>13}" for h in hdr))
for row in cur.fetchall():
    cells = [str(row[0])] + [str(row[1]), str(row[2]), str(row[3])] + [
        (f"{v:.6g}" if v is not None else "NULL") for v in row[4:]]
    print("  " + "".join(f"{c:>13}" for c in cells))

# --- 3. same for dealer_spread_est ($) and residual: signedness check ---
cur.execute(f"""
    SELECT opa_sign_confidence,
           count(*) FILTER (WHERE dealer_spread_est < 0)   AS est_neg,
           count(*) FILTER (WHERE opa_ptp_residual < 0)    AS resid_neg,
           count(*) FILTER (WHERE opa_constrained_residual < 0) AS cresid_neg,
           count(*) FILTER (WHERE opa_signed_net < 0)      AS net_neg,
           count(*) FILTER (WHERE opa_signed_net > 0)      AS net_pos,
           min(dealer_spread_est)::float8, max(dealer_spread_est)::float8
      FROM {PACKAGES_TABLE}
     WHERE opa_sign_confidence IS NOT NULL
     GROUP BY 1 ORDER BY 1
""")
print("\n--- 3. signedness of $ quantities ---")
print(f"  {'tier':<12}{'est<0':>8}{'resid<0':>9}{'cresid<0':>10}{'net<0':>9}{'net>0':>9}{'min_est':>14}{'max_est':>14}")
for r in cur.fetchall():
    print(f"  {str(r[0]):<12}{r[1]:>8}{r[2]:>9}{r[3]:>10}{r[4]:>9}{r[5]:>9}"
          f"{(f'{r[6]:.6g}' if r[6] is not None else 'NULL'):>14}"
          f"{(f'{r[7]:.6g}' if r[7] is not None else 'NULL'):>14}")

# --- 4. per-leg opa_sign balance within EXACT/TIGHT packages ---
cur.execute(f"""
    SELECT p.opa_sign_confidence,
           count(*) FILTER (WHERE l.opa_sign = 1)  AS n_plus,
           count(*) FILTER (WHERE l.opa_sign = -1) AS n_minus,
           count(*) FILTER (WHERE l.opa_sign IS NULL) AS n_null
      FROM {LEGS_TABLE} l
      JOIN {PACKAGES_TABLE} p ON p.ptp_group_id = l.ptp_group_id
     WHERE p.opa_sign_confidence IN ('EXACT','TIGHT')
     GROUP BY 1 ORDER BY 1
""")
print("\n--- 4. leg opa_sign balance in EXACT/TIGHT packages ---")
for r in cur.fetchall():
    print(f"  {r[0]:<10} +1={r[1]:<9} -1={r[2]:<9} null={r[3]}")

# --- 5. does the solver ever see a repriced NPV? cross-check column presence ---
cur.execute(f"""
    SELECT count(*) AS n_exact_tight,
           count(*) FILTER (WHERE ptp_group_size = 2) AS sz2,
           count(*) FILTER (WHERE ptp_group_size >= 3) AS sz3p,
           min(ptp_group_size), max(ptp_group_size)
      FROM {PACKAGES_TABLE}
     WHERE opa_sign_confidence IN ('EXACT','TIGHT')
""")
print("\n--- 5. EXACT/TIGHT package sizes ---")
print("  n=%s  size2=%s  size>=3=%s  min=%s max=%s" % cur.fetchone())

conn.close()

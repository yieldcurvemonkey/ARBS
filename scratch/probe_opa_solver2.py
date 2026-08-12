"""Follow-ups: (a) UNRESOLVED zero-bps mass, (b) direction-blindness of the solver."""
import os
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import psycopg2
from SDRUtils._swappulse_scripts._tape_tables import PACKAGES_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils.packages.opa_sign_solver import solve_opa_signs

# ---------- (b) KNOWN-ANSWER TEST of the solver, run first ----------
# Case with a hand-known answer: OPAs 100k / 40k, PTP 60k.
# Only +100k -40k = +60k hits it exactly. Residual must be 0, tier EXACT.
r = solve_opa_signs([100_000.0, 40_000.0], 60_000.0)
print("--- (b0) known-answer: opa=[100k,40k] ptp=60k ---")
print("   signs=%s net=%.1f residual=%.6g conf=%s  (expect [+1,-1], 60000, 0, EXACT)"
      % (r["signs"], r["net"], r["residual"], r["confidence"]))

# Direction-blindness: flip the PTP sign. If the objective is
# min(|net-ptp|,|net+ptp|), the residual is IDENTICAL and the tier is identical,
# i.e. the solve cannot tell "customer paid" from "customer received".
r_neg = solve_opa_signs([100_000.0, 40_000.0], -60_000.0)
print("--- (b1) same OPAs, ptp = -60k (direction flipped) ---")
print("   signs=%s net=%.1f residual=%.6g conf=%s"
      % (r_neg["signs"], r_neg["net"], r_neg["residual"], r_neg["confidence"]))
print("   residual identical: %s | tier identical: %s"
      % (r["residual"] == r_neg["residual"], r["confidence"] == r_neg["confidence"]))

# Complement degeneracy: the globally-flipped sign vector scores the same.
opas = [100_000.0, 40_000.0]
net_a = sum(s * v for s, v in zip(r["signs"], opas))
net_b = sum(-s * v for s, v in zip(r["signs"], opas))
obj = lambda net, ptp: min(abs(net - ptp), abs(net + ptp))
print("--- (b2) complement degeneracy at ptp=+60k ---")
print("   chosen net=%.1f obj=%.6g | flipped net=%.1f obj=%.6g | equal=%s"
      % (net_a, obj(net_a, 60_000.0), net_b, obj(net_b, 60_000.0),
         obj(net_a, 60_000.0) == obj(net_b, 60_000.0)))

# ---------- (a) UNRESOLVED zero-bps mass ----------
conn = psycopg2.connect(resolve_pg_url())
cur = conn.cursor()
cur.execute(f"""
    SELECT count(*) AS n,
           count(*) FILTER (WHERE opa_signed_net = 0)            AS net_zero,
           count(*) FILTER (WHERE opa_ptp_residual = 0)          AS resid_zero,
           count(*) FILTER (WHERE package_transaction_price IS NULL) AS ptp_null,
           count(*) FILTER (WHERE package_transaction_price = 0) AS ptp_zero,
           count(*) FILTER (WHERE ptp_price_notation = 1)        AS notation1,
           count(*) FILTER (WHERE ptp_price_notation IS NULL)    AS notation_null
      FROM {PACKAGES_TABLE}
     WHERE opa_sign_confidence = 'UNRESOLVED' AND dealer_spread_bps = 0
""")
print("\n--- (a) UNRESOLVED rows with dealer_spread_bps = 0 ---")
print("   n=%s net=0:%s resid=0:%s ptp_null:%s ptp=0:%s notation1:%s notation_null:%s" % cur.fetchone())

# UNRESOLVED with NULL dealer_spread_est = the notation gate (early `continue`)
cur.execute(f"""
    SELECT count(*) AS n,
           count(*) FILTER (WHERE ptp_price_notation IS NOT NULL AND ptp_price_notation <> 1) AS notation_ne1,
           count(*) FILTER (WHERE ptp_price_notation IS NULL) AS notation_null
      FROM {PACKAGES_TABLE}
     WHERE opa_sign_confidence = 'UNRESOLVED' AND dealer_spread_est IS NULL
""")
print("   UNRESOLVED w/ NULL dealer_spread_est: n=%s notation<>1:%s notation NULL:%s" % cur.fetchone())

# Residual >= 50k share (the "true" UNRESOLVED-by-residual class)
cur.execute(f"""
    SELECT count(*) FILTER (WHERE opa_ptp_residual >= 50000),
           count(*) FILTER (WHERE opa_ptp_residual <  50000),
           count(*) FILTER (WHERE opa_ptp_residual IS NULL)
      FROM {PACKAGES_TABLE} WHERE opa_sign_confidence = 'UNRESOLVED'
""")
print("   UNRESOLVED split: resid>=50k:%s resid<50k:%s resid NULL:%s" % cur.fetchone())

# ---------- dealer_spread_bps vs a direction-relevant quantity? ----------
# If dealer_spread_bps carried direction it would correlate with the SIGN of
# opa_signed_net. Measure mean bps by sign of net on EXACT/TIGHT.
cur.execute(f"""
    SELECT opa_sign_confidence,
           sign(opa_signed_net) AS net_sign, count(*),
           avg(dealer_spread_bps)::float8
      FROM {PACKAGES_TABLE}
     WHERE opa_sign_confidence IN ('EXACT','TIGHT') AND opa_signed_net IS NOT NULL
     GROUP BY 1,2 ORDER BY 1,2
""")
print("\n--- dealer_spread_bps by sign(opa_signed_net), EXACT/TIGHT ---")
for t, s, n, m in cur.fetchall():
    print(f"   {t:<7} net_sign={str(s):>5}  n={n:<8} mean_bps={m:.6g}")

conn.close()

"""The residual is the JOIN RULE, not the pipeline. Prove it.

Every exact-date print with a non-zero error sits in ET hour 0 -- the
23:00-00:59 ET hole where Citi publishes nothing -- carries
`ASOF_2H_OUT_OF_SESSION`, and `validate`'s NEAREST_SQL matched it FORWARD to
the next session's 01:00 ET point. The direction pipeline priced it from the
PREVIOUS point, i.e. the prior ET day's 22:59.

So the documented consumer rule (carry the last grid point forward) should
reproduce those prints at ~1e-13, and if it does the 1.2 bp "error" is a
property of `nearest`, not of the mid.
"""
import os, sys, pathlib
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ.setdefault("ARBS_CITIVELO_QUOTES_OFFLINE", "1")
REPO = str(pathlib.Path(__file__).resolve().parents[1])
if REPO not in sys.path:
    sys.path.insert(0, REPO)
import pandas as pd
from SDRUtils._swappulse_scripts import _dealer_direction_schema_v1 as S
from SDRUtils._swappulse_scripts.backfill_dealer_direction import connect

FILES = ["D:/midgrid_cacheval_2026-04-01.parquet",
         "D:/midgrid_cacheval_2026-06-17.parquet",
         "D:/midgrid_cacheval_2025-04-07.parquet"]

df = pd.concat([pd.read_parquet(f) for f in FILES], ignore_index=True)
ex = df[df["exact_date"]]
nz = ex[ex["err_bp"].abs() > 1e-9].copy()
print(f"exact-date prints with |err| > 1e-9 under NEAREST: {len(nz)} "
      f"of {len(ex)}")

# LOCF: the latest grid point at or before the print's own curve_timestamp.
LOCF_SQL = f"""
SELECT ts, mid_pct, effective_date, maturity_date, snapshot_policy
FROM {S.CURVE_MID_TABLE}
WHERE rate_index = %s AND tenor_label = %s AND ts <= %s
ORDER BY ts DESC LIMIT 1
"""
conn = connect()
rows = []
with conn.cursor() as cur:
    for r in nz.to_dict("records"):
        cur.execute(LOCF_SQL, (r["rate_index"], r["tenor_label"],
                               r["curve_timestamp"]))
        g = cur.fetchone()
        if g is None:
            rows.append({**r, "locf_ts": None, "locf_err_bp": None})
            continue
        ts, mid, eff, mat, pol = g
        same = (pd.Timestamp(eff) == pd.Timestamp(r["effective_date"])
                and pd.Timestamp(mat) == pd.Timestamp(r["expiration_date"]))
        rows.append({
            "rate_index": r["rate_index"], "tenor_label": r["tenor_label"],
            "curve_timestamp": r["curve_timestamp"],
            "nearest_ts": r["ts"], "nearest_err_bp": r["err_bp"],
            "locf_ts": ts, "locf_lag_s":
                (pd.Timestamp(r["curve_timestamp"]).tz_convert("UTC")
                 - pd.Timestamp(ts).tz_convert("UTC")).total_seconds(),
            "locf_same_dates": same,
            "locf_err_bp": (float(mid) - float(r["implied_mid_pct"])) * 100.0,
            "locf_policy": pol,
        })
conn.close()

out = pd.DataFrame(rows)
pd.set_option("display.width", 220)
print("\nNEAREST (forward, next session) vs LOCF (carry last point forward):")
print(out[["rate_index", "tenor_label", "curve_timestamp", "nearest_ts",
           "nearest_err_bp", "locf_ts", "locf_lag_s", "locf_same_dates",
           "locf_err_bp"]].to_string(index=False))
if out["locf_err_bp"].notna().any():
    e = out["locf_err_bp"].dropna().abs()
    print(f"\nLOCF |err| bp: n={len(e)} med={e.median():.3e} max={e.max():.3e}")
    print(f"NEAREST |err| bp: max={out['nearest_err_bp'].abs().max():.3e}")
    print(f"\nLOCF reproduces the direction pipeline to <1e-9 bp on "
          f"{int((e < 1e-9).sum())} of {len(e)}")

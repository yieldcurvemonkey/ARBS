"""Series sanity, the FOMC day, the day ledger, and the sizes."""
import os, sys, pathlib
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ.setdefault("ARBS_CITIVELO_QUOTES_OFFLINE", "1")
REPO = str(pathlib.Path(__file__).resolve().parents[1])
if REPO not in sys.path:
    sys.path.insert(0, REPO)
import warnings
import pandas as pd
from SDRUtils._swappulse_scripts import _dealer_direction_schema_v1 as S
from SDRUtils._swappulse_scripts.backfill_dealer_direction import connect

pd.set_option("display.width", 240)
conn = connect()
NY = "America/New_York"
M = S.CURVE_MID_TABLE


def q(sql, **p):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql(sql, conn, params=p)


def sec(t):
    print("\n" + "=" * 92); print(t); print("=" * 92)


# ---------------------------------------------------------------- day ledger
sec("DAY LEDGER -- served fraction per grid date")
led = q(f"""SELECT grid_date, rate_index, status, partition_minutes,
                   session_expected_minutes, minutes_served, minutes_missed,
                   n_rows, n_tenors
            FROM {S.CURVE_MID_DAY_TABLE}
            WHERE grid_date >= '2025-04-06' ORDER BY grid_date, rate_index""")
led["served_of_partition"] = (led["minutes_served"] /
                              led["partition_minutes"].replace(0, pd.NA))
led["partition_of_session"] = (led["partition_minutes"] /
                               led["session_expected_minutes"].replace(0, pd.NA))
led["rows_ok"] = led["n_rows"] == led["n_tenors"] * led["minutes_served"]
print(led.to_string(index=False))

# ------------------------------------------------------- 10Y SOFR half-hourly
sec("10Y SOFR, 2026-04-01, every 30 minutes ET")
s = q(f"""SELECT ts, mid_pct, effective_date, maturity_date,
                 snapshot_lag_seconds, snapshot_policy
          FROM {M} WHERE grid_date='2026-04-01' AND rate_index='SOFR'
            AND tenor_label='10Y' ORDER BY ts""")
s["et"] = pd.to_datetime(s["ts"], utc=True).dt.tz_convert(NY)
half = s[(s["et"].dt.minute.isin([0, 30]))].copy()
half["chg_bp"] = half["mid_pct"].diff() * 100.0
print(half[["et", "mid_pct", "chg_bp", "snapshot_lag_seconds",
            "effective_date", "maturity_date"]].to_string(
    index=False, formatters={"et": lambda x: x.strftime("%H:%M")}))
print(f"\n  minutes on the day      : {len(s)}")
print(f"  distinct mid values     : {s['mid_pct'].nunique()}"
      f"  (a flat day would be 1)")
print(f"  range                   : {s['mid_pct'].min():.6f} .. "
      f"{s['mid_pct'].max():.6f} %  ({(s['mid_pct'].max()-s['mid_pct'].min())*100:.2f} bp)")
d1 = s["mid_pct"].diff().abs() * 100.0
print(f"  |1-min change| bp       : med={d1.median():.4f} p95={d1.quantile(.95):.4f} "
      f"max={d1.max():.4f}")
print(f"  |30-min change| bp      : max={half['chg_bp'].abs().max():.4f}")

# ------------------------------------------------------------------- the FOMC
sec("FOMC 2026-06-17 -- the short end around 14:00 ET, vs the 06-16 control")
tn = {"SOFR": ["1M", "3M", "6M", "1Y", "2Y", "10Y"],
      "FED_FUNDS": ["1M", "2M", "3M", "6M", "1Y"]}
for idx, ts_ in tn.items():
    f = q(f"""SELECT ts, tenor_label, mid_pct FROM {M}
              WHERE grid_date='2026-06-17' AND rate_index=%(i)s
                AND tenor_label = ANY(%(t)s) ORDER BY ts""",
          i=idx, t=ts_)
    if f.empty:
        print(f"  {idx}: NO ROWS"); continue
    f["et"] = pd.to_datetime(f["ts"], utc=True).dt.tz_convert(NY)
    p = f.pivot_table(index="et", columns="tenor_label", values="mid_pct")
    p = p[[c for c in ts_ if c in p.columns]]
    win = p[(p.index.hour == 13) & (p.index.minute >= 50) |
            (p.index.hour == 14) & (p.index.minute <= 20)]
    print(f"\n-- {idx} 13:50-14:20 ET (1-min) --")
    print((win * 100).round(3).to_string())
    step = win.loc[win.index.hour == 14].iloc[0] - win.loc[win.index.hour == 13].iloc[-1]
    print(f"  step across 13:59->14:00 ET, bp: "
          + "  ".join(f"{k} {v*100:+.2f}" for k, v in step.items()))
    # whole-day range on the FOMC day vs the control day
    ctl = q(f"""SELECT tenor_label, (max(mid_pct)-min(mid_pct))*100 rng
                FROM {M} WHERE grid_date='2026-06-16' AND rate_index=%(i)s
                  AND tenor_label = ANY(%(t)s) GROUP BY 1""", i=idx, t=ts_)
    fom = q(f"""SELECT tenor_label, (max(mid_pct)-min(mid_pct))*100 rng
                FROM {M} WHERE grid_date='2026-06-17' AND rate_index=%(i)s
                  AND tenor_label = ANY(%(t)s) GROUP BY 1""", i=idx, t=ts_)
    cmp_ = fom.merge(ctl, on="tenor_label", suffixes=("_0617", "_0616"))
    cmp_["ratio"] = cmp_["rng_0617"] / cmp_["rng_0616"]
    print("  intraday range bp, FOMC vs control 06-16:")
    print("   " + cmp_.round(3).to_string(index=False).replace("\n", "\n   "))

# ---------------------------------------------------------------------- sizes
sec("ROW COUNTS AND TABLE SIZE")
print(q(f"""SELECT grid_date, rate_index, count(*) n_rows,
                   count(DISTINCT ts) minutes, count(DISTINCT tenor_label) tenors
            FROM {M} GROUP BY 1,2 ORDER BY 1,2""").to_string(index=False))
print("\n" + q(f"""SELECT count(*) total_rows, min(grid_date) lo,
                          max(grid_date) hi, count(DISTINCT grid_date) days
                   FROM {M}""").to_string(index=False))
print("\n" + q("""SELECT relname,
       pg_size_pretty(pg_total_relation_size(c.oid)) total,
       pg_size_pretty(pg_relation_size(c.oid)) heap,
       pg_size_pretty(pg_indexes_size(c.oid)) idx
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE relname = ANY(%(t)s)""", t=[S.CURVE_MID_TABLE, S.CURVE_MID_DAY_TABLE]
              ).to_string(index=False))
print("\n" + q(f"""SELECT pg_total_relation_size(%(t)s)::numeric
                        / NULLIF(count(*),0) AS bytes_per_row
                   FROM {M}""", t=M).to_string(index=False))
conn.close()

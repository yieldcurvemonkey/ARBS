"""Three loose ends: the concurrent writer, honest sizing, and 2025-04-07."""
import os, sys, pathlib, time
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
conn.autocommit = True
M = S.CURVE_MID_TABLE
NY = "America/New_York"


def q(sql, **p):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        # params=None, not {}: psycopg2 rejects an empty dict, and with no
        # params it does no interpolation so a literal % in the SQL is safe.
        return pd.read_sql(sql, conn, params=(p or None))


def sec(t):
    print("\n" + "=" * 92); print(t); print("=" * 92)


MINE = ['2025-04-06', '2025-04-07', '2026-03-31', '2026-04-01',
        '2026-06-16', '2026-06-17']

sec("IS SOMETHING ELSE WRITING THIS TABLE RIGHT NOW?")
a = q(f"SELECT count(*) n, count(DISTINCT grid_date) d FROM {M}")
print("t0:", a.to_dict("records")[0])
print(q("""SELECT pid, state, application_name,
       left(regexp_replace(query, '\\s+', ' ', 'g'), 90) AS q,
       now()-query_start AS running
FROM pg_stat_activity
WHERE query ILIKE '%curve_mid%' AND pid <> pg_backend_pid()
ORDER BY query_start""").to_string(index=False))
time.sleep(20)
b = q(f"SELECT count(*) n, count(DISTINCT grid_date) d FROM {M}")
print("t0+20s:", b.to_dict("records")[0],
      "-> GREW" if b["n"][0] != a["n"][0] else "-> unchanged over 20 s")
print("\nmy 6 pilot grid dates contribute:")
print(q(f"SELECT count(*) FROM {M} WHERE grid_date = ANY(%(d)s::date[])",
        d=MINE).to_string(index=False))
print("everything else (another writer / the earlier Oct pilot):")
print(q(f"SELECT count(*) FROM {M} WHERE NOT (grid_date = ANY(%(d)s::date[]))",
        d=MINE).to_string(index=False))

sec("HONEST SIZING -- bloat from republish, and the projection")
print(q("""SELECT relname, n_live_tup, n_dead_tup, last_vacuum, last_autovacuum,
                  last_analyze, last_autoanalyze
           FROM pg_stat_user_tables WHERE relname = %(t)s""",
        t=M).to_string(index=False))
sz = q("""SELECT pg_total_relation_size(%(t)s) tot, pg_relation_size(%(t)s) heap,
                 pg_indexes_size(%(t)s) idx""", t=M).iloc[0]
n = int(q(f"SELECT count(*) c FROM {M}")["c"][0])
print(f"\nrows={n:,}  total={sz['tot']/2**20:.0f} MB  heap={sz['heap']/2**20:.0f} MB"
      f"  idx={sz['idx']/2**20:.0f} MB")
print(f"bytes/row: total={sz['tot']/n:.0f}  heap={sz['heap']/n:.0f}  "
      f"idx={sz['idx']/n:.0f}")
for label, rows in (("610 days @ 40,497 rows/day", 610 * 40497),
                    ("527 days @ 40,497 rows/day", 527 * 40497)):
    print(f"  projection {label}: {rows/1e6:.2f} M rows -> "
          f"{rows * sz['tot'] / n / 2**30:.2f} GB total "
          f"({rows * sz['heap'] / n / 2**30:.2f} heap + "
          f"{rows * sz['idx'] / n / 2**30:.2f} idx)")

sec("2025-04-07 -- where are SOFR's 180 missing session minutes?")
s = q(f"""SELECT ts, mid_pct FROM {M} WHERE grid_date='2025-04-07'
          AND rate_index='SOFR' AND tenor_label='10Y' ORDER BY ts""")
s["et"] = pd.to_datetime(s["ts"], utc=True).dt.tz_convert(NY)
gap = s["et"].diff()
big = s[gap > pd.Timedelta(minutes=1)]
print(f"rows={len(s)}  first={s['et'].iloc[0]:%H:%M}  last={s['et'].iloc[-1]:%H:%M}")
print("interior gaps > 1 min:")
for i in big.index:
    print(f"  {s['et'][i-1]:%H:%M} -> {s['et'][i]:%H:%M}  "
          f"({gap[i].total_seconds()/60:.0f} min)")
print("\nminutes present per ET hour:")
print(s.groupby(s["et"].dt.hour).size().to_string())

sec("2025-04-07 10Y SOFR every 30 min -- is the curve-shape break continuous?")
half = s[s["et"].dt.minute.isin([0, 30])].copy()
half["chg_bp"] = half["mid_pct"].diff() * 100.0
print(half[["et", "mid_pct", "chg_bp"]].to_string(
    index=False, formatters={"et": lambda x: x.strftime("%H:%M")}))
d1 = s["mid_pct"].diff().abs() * 100.0
print(f"\n  distinct mids={s['mid_pct'].nunique()} of {len(s)}   "
      f"range={s['mid_pct'].min():.6f}..{s['mid_pct'].max():.6f}% "
      f"({(s['mid_pct'].max()-s['mid_pct'].min())*100:.2f} bp)")
print(f"  |1-min change| bp: med={d1.median():.4f} p95={d1.quantile(.95):.4f} "
      f"max={d1.max():.4f}")
conn.close()

"""How often does ONE tenor move while its neighbours do not?

A market move moves neighbouring tenors together. A bad node in one region of
Citi's curve for one minute moves a tenor alone, and usually round-trips the
next minute. The grid reproduces the curve store bit-for-bit, so anything here
is Citi's data, not this pipeline -- but the chart will draw it, so it needs a
rate and a shape.
"""
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

pd.set_option("display.width", 260)
conn = connect()
NY = "America/New_York"
DAYS = ["2025-04-06", "2025-04-07", "2026-03-31", "2026-04-01",
        "2026-06-16", "2026-06-17"]
ORDER = ["1M", "2M", "3M", "6M", "9M", "1Y", "18M", "2Y", "3Y", "4Y", "5Y",
         "6Y", "7Y", "8Y", "9Y", "10Y", "12Y", "15Y", "20Y", "25Y", "30Y"]

tot_min = tot_lonely = 0
hits = []
for day in DAYS:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        d = pd.read_sql(
            f"""SELECT ts, tenor_label, mid_pct FROM {S.CURVE_MID_TABLE}
                WHERE grid_date=%(d)s AND rate_index='SOFR' ORDER BY ts""",
            conn, params={"d": day})
    p = d.pivot_table(index="ts", columns="tenor_label", values="mid_pct")
    p = p[[c for c in ORDER if c in p.columns]]
    p.index = pd.to_datetime(p.index, utc=True).tz_convert(NY)
    ch = (p.diff() * 100.0).iloc[1:]
    tot_min += len(ch)
    cols = list(ch.columns)
    for i, t in enumerate(cols):
        nb = [cols[j] for j in (i - 1, i + 1) if 0 <= j < len(cols)]
        lonely = (ch[t].abs() > 1.0) & (ch[nb].abs().max(axis=1) < 0.1)
        tot_lonely += int(lonely.sum())
        for ts in ch.index[lonely]:
            nxt = ch[t].shift(-1).loc[ts]
            hits.append({"day": day, "et": f"{ts:%H:%M}", "tenor": t,
                         "move_bp": ch[t].loc[ts],
                         "next_min_bp": nxt,
                         "round_trip": bool(pd.notna(nxt) and
                                            nxt * ch[t].loc[ts] < 0 and
                                            abs(nxt) > 0.5 * abs(ch[t].loc[ts])),
                         "nb_max_bp": ch[nb].abs().max(axis=1).loc[ts]})

print(f"SOFR, 6 pilot grid dates: {tot_min:,} tenor-minute transitions "
      f"({len(ORDER)} tenors)")
print(f"single-tenor moves > 1 bp with BOTH neighbours < 0.1 bp: {tot_lonely}"
      f"  ({100.0*tot_lonely/(tot_min*len(ORDER)):.4f}% of tenor-minutes)")
if hits:
    h = pd.DataFrame(hits)
    print("\n" + h.round(3).to_string(index=False))
    print(f"\nround-tripped within the next minute: "
          f"{int(h['round_trip'].sum())} of {len(h)}")
    print("ET hour histogram:", h["et"].str[:2].value_counts().to_dict())
conn.close()

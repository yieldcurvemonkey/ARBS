"""Are the biggest 1-minute moves the MARKET, or a snapshot splice?

A market move moves the whole curve together. A curve rebuild / bad snapshot
moves one tenor, or moves the curve into a shape it did not have a minute
earlier. So for the largest 1-min 10Y moves, show what every other tenor did in
the same minute -- and whether the curve stayed monotone in the same way.
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
T = ["1M", "3M", "6M", "1Y", "2Y", "5Y", "10Y", "30Y"]

for day in ("2026-04-01", "2025-04-07", "2026-06-17"):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        d = pd.read_sql(
            f"""SELECT ts, tenor_label, mid_pct FROM {S.CURVE_MID_TABLE}
                WHERE grid_date=%(d)s AND rate_index='SOFR'
                  AND tenor_label = ANY(%(t)s) ORDER BY ts""",
            conn, params={"d": day, "t": T})
    p = d.pivot_table(index="ts", columns="tenor_label", values="mid_pct")[T]
    p.index = pd.to_datetime(p.index, utc=True).tz_convert(NY)
    ch = p.diff() * 100.0
    print("\n" + "=" * 100)
    print(f"{day}: the 6 largest 1-minute 10Y moves, and what the rest of the "
          "curve did in the SAME minute (bp)")
    print("=" * 100)
    top = ch["10Y"].abs().nlargest(6).index
    out = ch.loc[top].copy()
    out["same_sign_as_10Y"] = (
        (ch.loc[top].apply(lambda r: (r[T] * (1 if r["10Y"] > 0 else -1) > 0).sum(),
                           axis=1)).astype(str) + "/8")
    out.index = [f"{i:%H:%M}" for i in out.index]
    print(out.round(3).to_string())
    # how often does the 10Y move alone?
    big = ch[ch["10Y"].abs() > 1.0]
    if len(big):
        corr = big.apply(lambda r: (r["5Y"] * r["10Y"] > 0) and
                                   (r["30Y"] * r["10Y"] > 0), axis=1)
        print(f"\n  minutes with |10Y move| > 1 bp: {len(big)}; of those, "
              f"5Y AND 30Y moved the same way in {int(corr.sum())} "
              f"({100*corr.mean():.0f}%)")
    print(f"  cross-tenor corr of 1-min changes, 10Y vs: "
          + "  ".join(f"{t} {ch['10Y'].corr(ch[t]):+.2f}" for t in T if t != "10Y"))
    # is the curve ever non-monotone in a way that appears for one minute only?
    print(f"  1M<3M<6M<1Y ordering holds on "
          f"{100*((p['1M']<p['3M'])&(p['3M']<p['6M'])&(p['6M']<p['1Y'])).mean():.1f}% "
          f"of minutes")
conn.close()

"""Pin down the UNITS and SIGN of a two-leg FixedRateBondQuery CURVE YTM value.

A spread whose sign is guessed is a backtest that trades the wrong way round, and the
guess survives every self-consistent test you can write against it. So: price the two
legs SEPARATELY as outrights and reconstruct the curve value from them.
"""

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime  # noqa: E402

import pandas as pd  # noqa: E402

from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP  # noqa: E402
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery  # noqa: E402
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue  # noqa: E402
from TB.FixedRateBondsTB import FixedRateBondsTB  # noqa: E402

pd.set_option("display.width", 250)

START, END = datetime.date(2024, 1, 2), datetime.date(2024, 1, 31)
mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")
tb = FixedRateBondsTB(mdp, show_tqdm=False)

# On 2024-01: CT10 = 91282CJJ1 (4.500 Nov 2033), O10 = 91282CJZ5? -- resolve to be sure.
from MDP.FixedRateBonds.FixedRateBondsMDP import _filter_and_rank_ref_df  # noqa: E402
from MDP.FixedRateBonds.reference_data_cache.ust_reference_data import (  # noqa: E402
    update_reference_data,
)

ref = _filter_and_rank_ref_df(update_reference_data(source="fiscaldata"), START)
ten = ref[ref["oi"] == "10-Year"].nsmallest(3, "rank")
print(ten[["rank", "cusip", "cpn", "issue_date", "maturity_date"]].to_string(index=False))
ct = ten[ten["rank"] == 0].iloc[0]
o1 = ten[ten["rank"] == 1].iloc[0]

qs = [
    FixedRateBondQuery(cusip=ct["cusip"], value=FixedRateBondValue.YTM),
    FixedRateBondQuery(cusip=o1["cusip"], value=FixedRateBondValue.YTM),
    FixedRateBondQuery(cusip=f"{o1['cusip']}/{ct['cusip']}", value=FixedRateBondValue.YTM),
    FixedRateBondQuery(cusip=f"{ct['cusip']}/{o1['cusip']}", value=FixedRateBondValue.YTM),
    FixedRateBondQuery(cusip=ct["cusip"], value=FixedRateBondValue.DV01),
    FixedRateBondQuery(cusip=o1["cusip"], value=FixedRateBondValue.DV01),
    FixedRateBondQuery(cusip=ct["cusip"], value=FixedRateBondValue.MOD_DURATION),
]
df = tb.get_timeseries(start=START, end=END, queries=qs, n_jobs=4)
df.columns = [str(c) for c in df.columns]
print("\ncolumns:", list(df.columns))

ct_y = df[[c for c in df.columns if ct["cusip"] in c and "YTM" in c and "/" not in c][0]]
o1_y = df[[c for c in df.columns if o1["cusip"] in c and "YTM" in c and "/" not in c][0]]
fwd = df[[c for c in df.columns if c.startswith(f"{o1['cusip']}/{ct['cusip']}") and "YTM" in c][0]]
rev = df[[c for c in df.columns if c.startswith(f"{ct['cusip']}/{o1['cusip']}") and "YTM" in c][0]]

out = pd.DataFrame(
    {
        "ct_ytm": ct_y,
        "o1_ytm": o1_y,
        "old_minus_cur_pct": o1_y - ct_y,
        "old_minus_cur_bp": (o1_y - ct_y) * 100.0,
        "curve_OLD/CUR": fwd,
        "curve_CUR/OLD": rev,
    }
)
print("\n=== units / sign reconstruction ===")
print(out.head(12).round(5).to_string())
print("\nOUTRIGHT YTM level range:", float(ct_y.min()), float(ct_y.max()), "-> percent" if ct_y.mean() > 1 else "-> decimal")
print("corr(curve_OLD/CUR, (old-cur) in pct):", round(float(fwd.corr(o1_y - ct_y)), 6))
print("ratio  curve_OLD/CUR / ((old-cur) pct)  median:",
      round(float((fwd / (o1_y - ct_y)).median()), 4))
print("ratio  curve_OLD/CUR / ((old-cur) bp )  median:",
      round(float((fwd / ((o1_y - ct_y) * 100)).median()), 4))
print("curve_CUR/OLD == -curve_OLD/CUR ? max abs diff:",
      float((rev + fwd).abs().max()))

for c in df.columns:
    if "DV01" in c or "MOD_DURATION" in c:
        print(f"{c}: mean {df[c].mean():.6f}")

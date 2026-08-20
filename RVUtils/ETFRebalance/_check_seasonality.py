"""Verify the seasonality helpers against inputs whose answers are known by hand.

A checking script that is itself wrong reports success and hides the thing it was built
to find, so each case below has an answer computed away from the code under test.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from RVUtils.ETFRebalance import _run_seasonality as S

fails = []


def ck(name, got, want):
    ok = np.allclose(np.asarray(got, float), np.asarray(want, float), equal_nan=True)
    print(f"{'PASS' if ok else 'FAIL'}  {name}\n      got  {got}\n      want {want}")
    if not ok:
        fails.append(name)


# ---- 1. calendar_keys: a month whose last trading day is NOT the last calendar day.
# Jan 2021 trading days here deliberately stop at the 28th (as if the 29th were a
# holiday), so a bdate_range anchor would be wrong and a panel-anchored one right.
jan = pd.bdate_range("2021-01-25", "2021-01-28")          # Mon..Thu, ends 28th
feb = pd.bdate_range("2021-02-01", "2021-02-05")          # Mon..Fri
cal = S.calendar_keys(pd.Series(list(jan) + list(feb)))
# anchors sit at positions 3 (2021-01-28) and 8 (2021-02-05).  Every date is assigned to
# the NEAREST anchor, so 02-03 (index 6) is +3 from January and -2 from February and
# belongs to February.  That is what makes -10..+10 partition the sample exactly once.
ck("bd_me around a short month end",
   cal["bd_me"].tolist(), [-3, -2, -1, 0, 1, 2, -2, -1, 0])
ck("dow (0=Mon) on 2021-01-25", int(cal.loc[0, "dow"]), 0)
ck("moy on 2021-02-01", int(cal.loc[4, "moy"]), 2)

# ---- 2. _spread: 20 names, forward returns = rank, signal = rank.  Decile = 2 names.
# top 2 fwd = 18,19 -> mean 18.5 ; bottom 2 = 0,1 -> mean 0.5 ; spread 18.0
sig = np.arange(20.0)
fwd = np.arange(20.0)
ck("decile spread on a perfectly ranked cross-section", S._spread(sig, fwd), 18.0)
ck("decile spread with the signal reversed", S._spread(-sig, fwd), -18.0)
ck("decile spread refuses too few names", S._spread(sig[:15], fwd[:15]), np.nan)

# ---- 3. _hac_t with zero autocorrelation must sit near the naive t.
rng = np.random.default_rng(0)
x = rng.normal(0.5, 1.0, 400)
naive = x.mean() / (x.std(ddof=1) / np.sqrt(x.size))
hac = S._hac_t(x, gap_bd=21.0, horizon=10)          # gap > horizon -> 1 lag
print(f"      iid series: naive t {naive:.2f} vs HAC t {hac:.2f}")
ck("HAC ~ naive on an iid series", abs(hac - naive) < 0.35, True)

# ---- 4. fund_intensity's densification must SEE an entry and an exit.
# A two-bond book: bond A held 1.0 throughout; bond B enters at 2.0 on day 2 and leaves
# after day 3.  Correct |d par/share| by day: d2 = 2.0 (B's entry), d3 = 0, d4 = 2.0
# (B's exit).  A naive inner-join diff would report 0, 0, 0.
orig = S.HP.load_holdings
pad_dates = pd.bdate_range("2021-01-04", periods=30)         # >= the 20-row guard
rows = []
for i, d in enumerate(pad_dates):
    rows.append({"ticker": "ZZZ", "date": d, "cusip": "A", "par": 1.0, "shares_out": 1.0})
    if i in (1, 2):
        rows.append({"ticker": "ZZZ", "date": d, "cusip": "B", "par": 2.0, "shares_out": 1.0})
h2 = pd.DataFrame(rows)
h2["par_per_share"] = h2["par"] / h2["shares_out"]
S.HP.load_holdings = lambda tickers: h2
try:
    fi = S.fund_intensity(["ZZZ"])
finally:
    S.HP.load_holdings = orig
got = fi["intensity"].head(5).tolist()
ck("entry and exit both register in |d par/share|", got, [np.nan, 2.0, 0.0, 2.0, 0.0])

print()
print("ALL PASS" if not fails else f"FAILURES: {fails}")
raise SystemExit(1 if fails else 0)

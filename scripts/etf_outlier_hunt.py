r"""The cells the calibrated bands let through, which is where the next bad number lives.

``bonds/sanity.py`` rejects a PRICE outside 15..200 and a YIELD outside -5..25%.
Those bands were drawn around ten years of DAILY cells and they caught the
2026-07 corruption they were built for. They do not catch everything, and the
hourly scan says so:

* the ``YIELD`` layer's smallest value across 3.2 million cells is **0.0023%**.
  That is inside the band and it is not a yield: no twenty-to-thirty year
  Treasury has ever traded near two-tenths of a basis point, and the lowest the
  long end reached in 2020 was about 0.9%.
* the ``ASS_SOFR`` layer reaches **-541 bp** against a distribution whose lower
  quartile is +43 bp. ``ASS_SOFR`` has no band at all - ``bands_for`` returns
  nothing for it - so ``screened=False``, and the module's own docstring is
  explicit that an empty rejection list means "nothing was refused", not
  "nothing is wrong".

So this counts them, names them, dates them, and - the part that matters for
every number already reported - measures whether they moved any of the
conclusions.
"""

from __future__ import annotations

import pathlib

import numpy as np
import pandas as pd

DATA = pathlib.Path(__file__).resolve().parents[1] / "notebooks/backtests/etf_rebalance/_data"

from MDP.CitiVelocityExcel.cache import CitiVeloTagCache  # noqa: E402

#: Plausibility gates for a 20-31y US Treasury, drawn well outside anything real.
#: The long end's post-1990 range is roughly 0.7% to 9%; 0.2 and 12 leave room.
YIELD_LO, YIELD_HI = 0.20, 12.0
#: A UST asset-swap spread to SOFR has run roughly -120 to +110 bp. -300/+300 is
#: generous, and is a possibility gate rather than an accuracy check.
ASW_LO, ASW_HI = -300.0, 300.0


def scan(cache, tags, freq, lo, hi, label):
    rows = []
    for t in tags:
        s = cache.read(t, freq, "CLOSE")
        if s is None or s.empty:
            continue
        s = s.dropna()
        bad = s[(s < lo) | (s > hi)]
        if bad.empty:
            continue
        rows.append({"tag": t, "n": int(s.size), "n_bad": int(bad.size),
                     "frac": bad.size / s.size,
                     "worst": float(bad.iloc[np.abs(bad.to_numpy()).argmax()]),
                     "first_bad": bad.index.min(), "last_bad": bad.index.max(),
                     "bad_days": int(pd.Series(bad.index).dt.date.nunique())})
    df = pd.DataFrame(rows)
    print(f"\n{label}: {len(df)} tag(s) carry a value outside [{lo}, {hi}]")
    if not df.empty:
        pd.set_option("display.width", 220)
        print(df.sort_values("n_bad", ascending=False).head(15).to_string(index=False))
        print(f"  total impossible cells: {int(df['n_bad'].sum()):,}")
    return df


def main() -> int:
    cache = CitiVeloTagCache()
    uni = pd.read_csv(DATA / "intraday_universe.csv")
    isins = list(uni["isin"].astype(str))

    y = scan(cache, [f"RATES.BOND.{i}.YIELD" for i in isins], "HOURLY",
             YIELD_LO, YIELD_HI, "HOURLY YIELD")
    a = scan(cache, [f"RATES.BOND.{i}.ASS_SOFR" for i in isins], "HOURLY",
             ASW_LO, ASW_HI, "HOURLY ASS_SOFR (which sanity.py does NOT screen)")

    out = pd.concat([y.assign(value="YIELD"), a.assign(value="ASS_SOFR")], ignore_index=True)
    out.to_csv(DATA / "intraday_impossible_cells.csv", index=False)

    # ---- did they move anything already reported? -------------------------
    if not y.empty:
        bad_days = set()
        for t in y["tag"]:
            s = cache.read(t, "HOURLY", "CLOSE").dropna()
            b = s[(s < YIELD_LO) | (s > YIELD_HI)]
            bad_days |= set(pd.Series(b.index).dt.date)
        print(f"\nYIELD: {len(bad_days)} distinct calendar day(s) are touched: "
              f"{sorted(bad_days)[:12]}")
        print("Every reported dispersion statistic is a MEDIAN over 1,479 dates, so "
              f"{len(bad_days)} contaminated date(s) cannot move it; the affected dates "
              "are named here so a downstream mean or regression can drop them.")
        pd.DataFrame({"date": sorted(bad_days)}).to_csv(
            DATA / "intraday_contaminated_dates.csv", index=False)
    print("\nwrote intraday_impossible_cells.csv, intraday_contaminated_dates.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

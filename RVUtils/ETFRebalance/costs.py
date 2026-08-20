"""What a cash-UST butterfly costs to trade, measured rather than assumed.

The three candidates, and why the default is the third
------------------------------------------------------
**1. ``BT/gss_fly/config.py``** keys a half-spread on time to maturity:
``{0: 0.20, 3: 0.25, 5: 0.30, 7: 0.40, 10: 0.50, 20: 0.80}`` yield bp. Every leg of a
three-month butterfly has essentially the same maturity, so this table charges all three
legs the same and prices the *differences* this study trades at zero. Wrong axis.

**2. NY Fed SR1170 Table 3** keys on off-the-run rank, which is the right axis, and is
the table the olds-vs-currents study used. Its problem here is the tail. For the
30-year sector it reports, in PRICE basis points:

    rank      0     1      2      3      4      5    "further off-the-run"
    spread  4.96  5.18  12.35  16.21  18.34  18.69         166.98

**Every bond TLT owns is in that last bucket.** A 167 price-bp spread on a 15-duration
bond is 11 yield bp per leg; a three-legged fly would cost 33bp round trip and no signal
of any kind survives. That number is dominated by odd lots in genuinely dead issues --
the paper says as much about deep off-the-runs in March 2020 -- and adopting it as the
base case would kill this study by construction rather than by evidence.

**3. FedInvest's own published bid and offer**, per CUSIP, per day. Measured over the
20-30y sector: a median full spread of **2.7-8.0 price bp** depending on the date, which
at a 14.5 modified duration is **0.19-0.55 yield bp** -- twenty to sixty times tighter
than SR1170's tail bucket, and dated, and specific to the bond actually being traded.
This is the default.

It is not the whole truth either, and the direction of its error is stated rather than
hoped: FedInvest quotes are the Federal Investments Program's, not an interdealer
market's, and they are *quotes* rather than executions. So they are used as a base case
with a multiplier that the notebook sweeps, and every result is reported alongside the
**break-even multiple** -- the number of times the measured spread the strategy could
pay before it stops making money. A strategy that breaks even at 3x a measured spread is
a different object from one that breaks even at 0.4x, and the multiple says which
without anyone having to agree on the level.

Charging the round trip
-----------------------
One completed round trip on one leg = in at the offer, out at the bid = exactly ONE full
spread. A butterfly holds three legs and their DV01 weights sum to twice the belly's, so
a fly costs the DV01-weighted sum of its three legs' full spreads, in yield bp of the
belly's DV01 -- roughly ``2 x`` the average leg spread.

And it is charged **once, at the unwind**, because that is the only place the engine
reads a fee: ``BT/query_engine.py`` takes ``order.meta["fee"]`` from the UnwindOrder and
entry actions carry none. Charging half a round trip at exit "because entry pays the
other half" charges half the true cost and never charges the other half at all -- that
error was worth $2.8m of $5.6m on a prior book, the difference between +$431k and
roughly -$2.4m.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Optional

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------------------
# SR1170 Table 3, verbatim, kept as the pessimistic bound. PRICE basis points, full
# (not half) proportional effective spread, July 2017 - June 2024. Key 6 is the paper's
# own "further off-the-run" bucket.
# --------------------------------------------------------------------------------------
SR1170_FULL_SAMPLE: Dict[int, Dict[int, float]] = {
    2: {0: 0.66, 1: 1.22, 2: 2.23, 3: 2.42, 4: 2.85, 5: 3.34, 6: 6.89},
    5: {0: 1.18, 1: 2.30, 2: 3.12, 3: 3.89, 4: 4.11, 5: 4.91, 6: 36.74},
    10: {0: 2.07, 1: 3.73, 2: 5.36, 3: 6.05, 4: 6.68, 5: 6.95, 6: 64.77},
    30: {0: 4.96, 1: 5.18, 2: 12.35, 3: 16.21, 4: 18.34, 5: 18.69, 6: 166.98},
}

SR1170_MARCH_2020: Dict[int, Dict[int, float]] = {
    2: {0: 1.38, 1: 4.23, 2: 7.45, 3: 8.58, 4: 10.31, 5: 9.44, 6: 10.52},
    5: {0: 2.68, 1: 10.45, 2: 12.17, 3: 16.46, 4: 9.33, 5: 15.47, 6: 65.91},
    10: {0: 5.13, 1: 16.86, 2: 23.67, 3: 26.33, 4: 27.99, 5: 31.49, 6: 53.38},
    30: {0: 12.59, 1: 26.77, 2: 73.39, 3: 66.62, 4: 99.66, 5: 129.00, 6: 159.27},
}

SECTOR_OF_TTM = ((3.0, 2), (5.5, 5), (12.0, 10), (1e9, 30))

#: Floor on the measured spread, in PRICE bp. FedInvest occasionally publishes a bid and
#: an offer that are equal, which is a quoting artefact and not a free trade: a zero cost
#: is exactly the kind of plausible number that must never be confused with a missing
#: one. The floor is the smallest spread actually observed at any tenor over the sample,
#: rounded down.
MIN_SPREAD_PRICE_BP = 0.5


def _sr1170_sector(ttm: float) -> int:
    for cut, sector in SECTOR_OF_TTM:
        if ttm < cut:
            return sector
    return 30


@dataclass(frozen=True)
class CostModel:
    """Round-trip execution cost of a package, in YIELD bp of its gross DV01.

    ``basis``:
      ``measured``  FedInvest's own dated bid/offer for that CUSIP on that day (default)
      ``sr1170``    NY Fed Staff Report 1170 Table 3, keyed on off-the-run rank
      ``flat``      one number for every leg, for sensitivity curves
    """

    basis: str = "measured"
    multiplier: float = 1.0
    flat_yield_bp: float = 0.30
    use_stress_table: bool = True
    min_spread_price_bp: float = MIN_SPREAD_PRICE_BP
    #: When the measured basis has no quote for a leg on a day, fall back to the sector
    #: median rather than to zero. Absence of a quote is not absence of a cost.
    fallback_to_sector_median: bool = True

    def leg_round_trip_yield_bp(self, panel: pd.DataFrame) -> pd.Series:
        """One leg, in and out again, in yield bp. Indexed like ``panel``."""
        if self.basis == "flat":
            return pd.Series(self.flat_yield_bp * self.multiplier, index=panel.index)

        if self.basis == "measured":
            px_bp = panel["spread_price_bp"].astype(float)
            px_bp = px_bp.where(px_bp >= self.min_spread_price_bp, np.nan)
            if self.fallback_to_sector_median:
                sector = panel["ttm"].map(_sr1170_sector)
                med = px_bp.groupby([panel["date"], sector]).transform("median")
                px_bp = px_bp.fillna(med)
                px_bp = px_bp.fillna(px_bp.median())
            px_bp = px_bp.clip(lower=self.min_spread_price_bp)
            return (px_bp / panel["mod_dur"].astype(float)) * self.multiplier

        if self.basis == "sr1170":
            stressed = self.use_stress_table & panel["date"].between("2020-03-01", "2020-04-15")
            rank = panel["rank"].fillna(6).clip(upper=6).astype(int)
            sector = panel["ttm"].map(_sr1170_sector)
            px_bp = pd.Series(
                [
                    (SR1170_MARCH_2020 if s else SR1170_FULL_SAMPLE)[sec][r]
                    for s, sec, r in zip(stressed, sector, rank)
                ],
                index=panel.index, dtype=float,
            )
            return (px_bp / panel["mod_dur"].astype(float)) * self.multiplier

        raise ValueError(f"Unknown cost basis {self.basis!r}")

    def package_round_trip_yield_bp(
        self, legs: pd.DataFrame, weights: Mapping[str, float] | pd.Series
    ) -> pd.Series:
        """DV01-weighted sum of the legs' round trips, per unit of BELLY DV01.

        ``weights`` are the package's DV01 weights with the belly at 1.0, so a
        slope-neutral fly contributes ``|1| + |a| + |1-a| = 2`` times the average leg
        spread -- the fly pays for all three legs even though only one carries the view.
        """
        w = pd.Series(weights, index=legs.index) if not isinstance(weights, pd.Series) else weights
        return (self.leg_round_trip_yield_bp(legs) * w.abs()).groupby(legs["trade_id"]).sum() \
            if "trade_id" in legs.columns else (self.leg_round_trip_yield_bp(legs) * w.abs()).sum()


def measured_spread_summary(panel: pd.DataFrame, *, bands=((1, 3), (3, 7), (7, 10), (10, 20), (20, 31))) -> pd.DataFrame:
    """What the measured spread actually is, by sector and year. Print before any P&L.

    House convention: the prior labs died on cost and cost was the last thing shown.
    """
    p = panel.dropna(subset=["spread_price_bp", "mod_dur"]).copy()
    p = p[p["spread_price_bp"] >= MIN_SPREAD_PRICE_BP]
    p["spread_yield_bp"] = p["spread_price_bp"] / p["mod_dur"]
    rows = []
    for lo, hi in bands:
        s = p[p["ttm"].between(lo, hi)]
        if s.empty:
            continue
        for year, g in s.groupby(s["date"].dt.year):
            rows.append({
                "band": f"{lo}-{hi}y", "year": int(year), "n": len(g),
                "price_bp_med": g["spread_price_bp"].median(),
                "yield_bp_med": g["spread_yield_bp"].median(),
                "yield_bp_p90": g["spread_yield_bp"].quantile(0.90),
                "fly_rt_bp_med": 2.0 * g["spread_yield_bp"].median(),
            })
    return pd.DataFrame(rows)

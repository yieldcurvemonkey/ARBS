"""Transaction costs for an olds-vs-currents switch, from NY Fed Staff Report 1170.

Why not the repo's existing table
---------------------------------
``BT/gss_fly/config.py:104`` carries ``CostConfig.half_spread_bp`` keyed by time to
maturity: ``{0: 0.20, 3: 0.25, 5: 0.30, 7: 0.40, 10: 0.50, 20: 0.80}``. That table is
indexed on the wrong axis for this study. A switch trade holds two bonds of nearly
identical maturity and differing only in *age*, so a TTM-keyed table charges both legs the
same and prices the entire strategy at zero cost differential -- while age is precisely
what drives the spread. SR1170 Table 3 measures the axis this trade lives on.

What SR1170 Table 3 actually reports
------------------------------------
"CUSIP/Day Proportional Effective Spreads (Basis Points)", July 2017 - June 2024, defined
as (mean customer BUY price - mean customer SELL price) / midpoint. Three consequences:

1. It is a **full** bid-ask, not a half-spread. One-way execution costs half of it.
2. It is in **price** bp (proportional to price), not yield bp. Converting needs the
   bond's modified duration: a 1bp yield move is ``ModDur x 100`` price bp, so
   ``yield_bp = price_bp / (100 * ModDur)``... in the units used here, where price bp are
   already 1e-4 of price, ``yield_bp = price_bp / ModDur``.
3. It is measured off **executed trades**, which biases it low for the securities that
   were hard to trade -- the paper says so itself about deep off-the-runs in March 2020.
   So these are, if anything, optimistic for the deep-old legs.

The rank axis is the point: in the 5-year sector the effective spread almost DOUBLES from
1.18bp on-the-run to 2.30bp at 1st off-the-run, and reaches 4.91bp by the 5th. A switch
pays the sum of its two legs' spreads on a round trip, so a CT-vs-OOO trade is structurally
more expensive than a CT-vs-O one, and any grid that ignores that will rank the deep-old
cells too highly.

March 2020 is carried as a separate regime because it is 3-10x wider and the trade is a
liquidity-premium trade -- the cell where the premium is most tempting is the cell where
the cost is worst.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Tuple

# --------------------------------------------------------------------------------------
# SR1170 Table 3, verbatim. Keys are (sector, rank) where rank 0 = on-the-run and
# 6 stands for "further off-the-run" (the paper's own bucket for everything past 5th).
# Values are FULL proportional effective spreads in PRICE basis points.
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

#: SR1170 measures four sectors. The study trades seven tenors, so three have to be
#: mapped. The mapping is by *sector*, which is how the paper buckets: its "5-year
#: sector" is everything with 3-5 years to maturity and its "10-year sector" is 7-10
#: years, so a 3y and a 7y issue genuinely fall inside those buckets rather than being
#: guessed into them.
#:
#: 20Y is the exception and is the one to be careful about. SR1170 has no 20-year sector;
#: its 30-year sector is ">20 years to maturity", which excludes a freshly issued 20y.
#: It is mapped to 30 anyway because that is the nearest measured liquidity regime, but
#: this is an ASSUMPTION, not a measurement -- and it matters more than the others,
#: because the 20y also carries by far the richest specialness in the JPM panel (16.9bp
#: mean when special vs 2.4-4.6bp elsewhere). That combination -- biggest premium, least
#: certain cost -- is exactly the shape of a cell that looks alive because its cost is
#: understated. Treated conservatively via COST_UNCERTAINTY_MULT below.
SECTOR_OF_TENOR: Dict[int, int] = {2: 2, 3: 5, 5: 5, 7: 10, 10: 10, 20: 30, 30: 30}

#: Multiplier applied on top of the mapped table, per tenor. 1.0 where SR1170 measures
#: the sector directly; >1 where it is inferred. This is a stated haircut, not a fudge:
#: it exists so the 20y cannot win the league on a cost number nobody measured.
COST_UNCERTAINTY_MULT: Dict[int, float] = {2: 1.0, 3: 1.0, 5: 1.0, 7: 1.0, 10: 1.0, 20: 1.25, 30: 1.0}

#: March 2020 window over which the stressed table is used.
STRESS_WINDOW: Tuple[str, str] = ("2020-03-01", "2020-04-15")


@dataclass(frozen=True)
class CostModel:
    """Round-trip execution cost of a two-leg switch, in YIELD bp of the traded spread.

    ``multiplier`` scales everything and is the knob the cost-curve / break-even section
    sweeps. ``use_stress_table`` switches March 2020 onto the stressed numbers.
    """

    multiplier: float = 1.0
    use_stress_table: bool = True
    uncertainty_mult: Mapping[int, float] = field(default_factory=lambda: dict(COST_UNCERTAINTY_MULT))
    #: Charge one-way (half the full spread) per leg per side. A round trip = enter both
    #: legs + exit both legs = ONE full spread per leg. See ``round_trip_yield_bp``.
    _: None = None

    def full_price_bp(self, tenor: int, rank: int, *, stressed: bool = False) -> float:
        """SR1170 full effective spread in PRICE bp for this (tenor, rank)."""
        table = SR1170_MARCH_2020 if (stressed and self.use_stress_table) else SR1170_FULL_SAMPLE
        sector = SECTOR_OF_TENOR[int(tenor)]
        row = table[sector]
        r = int(rank)
        if r > 5:
            r = 6
        return float(row[r])

    def leg_round_trip_yield_bp(
        self, tenor: int, rank: int, mod_duration: float, *, stressed: bool = False
    ) -> float:
        """One leg, in and out again, expressed in yield bp.

        In = half the full spread, out = half the full spread, so a completed round trip
        on one leg costs exactly ONE full spread. ``mod_duration`` converts price bp to
        yield bp (a 1bp yield move is ``ModDur`` price bp in these units).
        """
        if not mod_duration or mod_duration <= 0:
            return float("nan")
        price_bp = self.full_price_bp(tenor, rank, stressed=stressed)
        unc = float(self.uncertainty_mult.get(int(tenor), 1.0))
        return price_bp / float(mod_duration) * unc * float(self.multiplier)

    def round_trip_yield_bp(
        self,
        tenor: int,
        rank_long: int,
        rank_short: int,
        mod_dur_long: float,
        mod_dur_short: float,
        *,
        stressed: bool = False,
    ) -> float:
        """Both legs, in and out -- the total cost of one completed switch, in yield bp.

        This is the number the strategy has to beat. It is charged against a spread P&L
        that is itself in yield bp of a DV01-matched position, so the units line up
        directly with the equity curve.
        """
        return self.leg_round_trip_yield_bp(
            tenor, rank_long, mod_dur_long, stressed=stressed
        ) + self.leg_round_trip_yield_bp(tenor, rank_short, mod_dur_short, stressed=stressed)


def is_stressed(date) -> bool:
    import pandas as pd

    ts = pd.Timestamp(date)
    return pd.Timestamp(STRESS_WINDOW[0]) <= ts <= pd.Timestamp(STRESS_WINDOW[1])


def cost_table_summary(mod_duration_by_tenor: Optional[Mapping[int, float]] = None):
    """Round-trip cost in yield bp for every (tenor, pair) the study trades.

    Printed in the notebook so the cost line is visible before any P&L is, which is the
    house convention: the prior labs died on cost and the cost was the last thing shown.
    """
    import itertools

    import pandas as pd

    # Representative modified durations, only for display.
    md = dict(mod_duration_by_tenor or {2: 1.9, 3: 2.8, 5: 4.5, 7: 6.1, 10: 7.9, 20: 13.0, 30: 17.5})
    cm = CostModel()
    rows = []
    for tenor in (2, 3, 5, 7, 10, 20, 30):
        for rl, rs in itertools.combinations(range(4), 2):
            # long the OLDER (higher rank), short the YOUNGER -- the classic switch.
            rows.append(
                {
                    "tenor": tenor,
                    "pair": f"{_rank_label(rs)}/{_rank_label(rl)}",
                    "rank_short": rs,
                    "rank_long": rl,
                    "rt_cost_bp": round(
                        cm.round_trip_yield_bp(tenor, rl, rs, md[tenor], md[tenor]), 4
                    ),
                    "rt_cost_bp_mar2020": round(
                        cm.round_trip_yield_bp(tenor, rl, rs, md[tenor], md[tenor], stressed=True), 4
                    ),
                }
            )
    return pd.DataFrame(rows)


def _rank_label(rank: int) -> str:
    return {0: "CT", 1: "O", 2: "OO", 3: "OOO"}.get(int(rank), f"Ox{rank}")

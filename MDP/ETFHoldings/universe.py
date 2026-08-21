"""The ETF universe this study scrapes, and what each fund is mechanically forced to do.

Why a registry and not a list of tickers
----------------------------------------
Every signal here is a claim about a *rule* the fund follows -- "bonds that fall below
20 years get sold at the month-end rebalance" -- and the rule is a property of the
tracked index, not of the ticker. A ticker alone cannot tell you where the deletion
boundary is, so it cannot tell you which bond is about to be forced out. The band is
therefore carried explicitly, and a fund whose band this file does not know is a fund
whose calendar signals are refused rather than guessed.

``maturity_band`` is in years of REMAINING maturity and is the index's own inclusion
rule, read off the index methodology:

  ICE US Treasury 20+ Year          TLT    [20, inf)
  ICE US Treasury 10-20 Year        TLH    [10, 20)
  ICE US Treasury 7-10 Year         IEF    [7, 10)
  ICE US Treasury 3-7 Year          IEI    [3, 7)
  ICE US Treasury 1-3 Year          SHY    [1, 3)
  ICE US Treasury Core Bond         GOVT   [1, inf)
  ICE BofA Long US Treasury STRIPS  GOVZ   [25, inf)   -- principal STRIPS, NOT coupons

``rebalance`` names the calendar the index reconstitutes on. Every ICE US Treasury
index rebalances at the **last calendar day of the month**, using the universe as it
stands at the end of that month; the fund trades into the new composition around that
date. That is the clock the calendar-only placebo runs on.

STRIPS caveat
-------------
``GOVZ`` holds principal STRIPS. Those CUSIPs do not appear in the FedInvest coupon-bond
universe and will not join the pricing panel. The fund is kept in the dataset because
its *demand* lands on the same maturity sector as TLT's, and excluded from anything that
needs a bond price. ``prices_from_fedinvest=False`` is that switch, and it is honoured by
the panel builder rather than being a comment here.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class ETFSpec:
    ticker: str
    issuer: str
    fund_id: str                       # portfolioId for iShares
    name: str
    aum_usd: float                     # as at 2026-08-19, from the issuer's own screener
    maturity_band: Optional[Tuple[float, float]]   # remaining-maturity inclusion rule, years
    rebalance: str = "month_end"
    inception: datetime.date = datetime.date(2000, 1, 1)
    prices_from_fedinvest: bool = True
    instrument: str = "coupon"         # coupon | strips | bill | target_maturity

    @property
    def band_low(self) -> Optional[float]:
        return None if self.maturity_band is None else self.maturity_band[0]

    @property
    def band_high(self) -> Optional[float]:
        return None if self.maturity_band is None else self.maturity_band[1]


#: iShares funds, portfolioId + AUM read from the live product screener on 2026-08-19
#: (``product-screener-v3.1.jsn``). AUM is recorded so the ">$1bn" cut in the study is a
#: fact with a date on it rather than a recollection.
ISHARES: Dict[str, ETFSpec] = {
    s.ticker: s
    for s in [
        ETFSpec("TLT",  "ishares", "239454", "iShares 20+ Year Treasury Bond ETF",
                46.89e9, (20.0, 1e9), inception=datetime.date(2002, 7, 22)),
        ETFSpec("TLH",  "ishares", "239453", "iShares 10-20 Year Treasury Bond ETF",
                11.08e9, (10.0, 20.0), inception=datetime.date(2007, 1, 5)),
        ETFSpec("IEF",  "ishares", "239456", "iShares 7-10 Year Treasury Bond ETF",
                43.17e9, (7.0, 10.0), inception=datetime.date(2002, 7, 22)),
        ETFSpec("IEI",  "ishares", "239455", "iShares 3-7 Year Treasury Bond ETF",
                17.70e9, (3.0, 7.0), inception=datetime.date(2007, 1, 5)),
        ETFSpec("SHY",  "ishares", "239452", "iShares 1-3 Year Treasury Bond ETF",
                25.28e9, (1.0, 3.0), inception=datetime.date(2002, 7, 22)),
        ETFSpec("GOVT", "ishares", "239468", "iShares U.S. Treasury Bond ETF",
                44.14e9, (1.0, 1e9), inception=datetime.date(2012, 2, 14)),
        # STRIPS -- in the dataset for its demand, out of the pricing panel.
        ETFSpec("GOVZ", "ishares", "315911", "iShares 25+ Year Treasury STRIPS Bond ETF",
                0.31e9, (25.0, 1e9), inception=datetime.date(2020, 9, 22),
                prices_from_fedinvest=False, instrument="strips"),
        # iBonds term Treasury: each fund holds ONE maturity year and winds down into it.
        # No 20-30y band, but a uniquely sharp forced-buyer profile in its own year.
        ETFSpec("IBTG", "ishares", "312457", "iShares iBonds Dec 2026 Term Treasury ETF",
                2.08e9, None, inception=datetime.date(2020, 3, 3), instrument="target_maturity"),
        ETFSpec("IBTH", "ishares", "312460", "iShares iBonds Dec 2027 Term Treasury ETF",
                2.34e9, None, inception=datetime.date(2020, 3, 3), instrument="target_maturity"),
        ETFSpec("IBTI", "ishares", "312463", "iShares iBonds Dec 2028 Term Treasury ETF",
                2.00e9, None, inception=datetime.date(2020, 3, 3), instrument="target_maturity"),
        ETFSpec("IBTJ", "ishares", "312466", "iShares iBonds Dec 2029 Term Treasury ETF",
                1.38e9, None, inception=datetime.date(2020, 3, 3), instrument="target_maturity"),
        ETFSpec("IBTK", "ishares", "314830", "iShares iBonds Dec 2030 Term Treasury ETF",
                1.02e9, None, inception=datetime.date(2021, 6, 8), instrument="target_maturity"),
    ]
}

#: Non-iShares funds. Populated only for issuers whose endpoint was MEASURED to serve a
#: dated historical file -- see ``providers/`` for what each probe found. A fund that
#: publishes only its current holdings cannot contribute a panel and is not listed, so
#: the absence of an issuer here is a finding, not an omission.
OTHER: Dict[str, ETFSpec] = {}

REGISTRY: Dict[str, ETFSpec] = {**ISHARES, **OTHER}

#: The funds the long-end micro-RV study actually trades against. The 20+ band is where
#: one fund (TLT, $47bn) owns a double-digit share of the free float of every bond in a
#: 120-CUSIP sector, which is the only place in the Treasury curve where an ETF's
#: rebalance can plausibly move a yield.
LONG_END = ("TLT", "TLH", "GOVZ")

#: Everything with a coupon-bond band, i.e. everything that can join the price panel.
CURVE_LADDER = ("SHY", "IEI", "IEF", "TLH", "TLT", "GOVT")


def spec(ticker: str) -> ETFSpec:
    try:
        return REGISTRY[ticker.upper()]
    except KeyError as exc:
        raise KeyError(
            f"{ticker!r} is not in the ETF registry. Add an ETFSpec with its index "
            f"maturity band -- a fund whose deletion boundary is unknown cannot be "
            f"given a calendar signal."
        ) from exc


def tickers_above(aum_usd: float, *, coupon_only: bool = True) -> Tuple[str, ...]:
    """Registry tickers above an AUM cut, in descending size."""
    out = [
        s for s in REGISTRY.values()
        if s.aum_usd >= aum_usd and (not coupon_only or s.instrument in ("coupon", "target_maturity"))
    ]
    return tuple(s.ticker for s in sorted(out, key=lambda s: -s.aum_usd))

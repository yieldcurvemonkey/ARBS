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

  ICE US Treasury 20+ Year               TLT    [20, inf)
  ICE US Treasury 10-20 Year             TLH    [10, 20)
  ICE US Treasury 7-10 Year              IEF    [7, 10)
  ICE US Treasury 3-7 Year               IEI    [3, 7)
  ICE US Treasury 1-3 Year               SHY    [1, 3)
  ICE US Treasury Core Bond              GOVT   [1, inf)
  ICE BofA Long US Treasury STRIPS       GOVZ   [25, inf)  -- principal STRIPS, NOT coupons
  Bloomberg Long U.S. Treasury           SPTL   [10, inf)
  Bloomberg U.S. Long Treasury Bond      VGLT   [10, inf)
  Bloomberg U.S. Treasury STRIPS 20-30y  EDV    [20, 30]   -- STRIPS, coupon AND principal

**The 10+ band is the whole reason a second issuer is worth scraping.** SPTL and VGLT do
not track TLT's index. Their board starts at 10 years, not 20, so on any given day they
are choosing among roughly a hundred bonds where TLT is choosing among forty, and the
part of their book that overlaps TLT's is a *selection* out of a wider set rather than
the set itself. Measured on 2026-08-19/07-31: SPTL held 100 bonds spanning 10.49y-29.99y
(60 below 20y, 40 at or above); VGLT held 99 spanning 10.55y-29.79y (59 below, 40 at or
above). Treating either as a 20+ fund would put sixty positions outside its own
benchmark and make every active weight in the long bucket wrong.

``rebalance`` names the calendar the index reconstitutes on. Every ICE US Treasury
index rebalances at the **last calendar day of the month**, using the universe as it
stands at the end of that month; the Bloomberg indices reconstitute month-end too. That
is the clock the calendar-only placebo runs on.

``cadence`` and ``history`` are properties of the ENDPOINT, not of the index
-----------------------------------------------------------------------------
``history="dated"`` means the issuer serves a file for a date you name, so a decade can
be backfilled (iShares only). ``history="current_only"`` means the issuer serves exactly
one file -- whatever is current -- and a date parameter is either absent (SSGA) or
accepted and **silently ignored** (Vanguard, which answers 200 with a different date in
the body). Those funds accumulate a panel going forward, one snapshot per run, and any
runner that loops them over a historical grid is making thousands of requests for the
same document. ``backfill.py`` refuses to do that rather than trusting the operator.

``publishes_shares_outstanding`` is a refusal hook, not a nicety
----------------------------------------------------------------
iShares publishes ``Shares Outstanding`` in every holdings file. **SSGA and Vanguard
publish no share count at all** -- SSGA's workbook has no such line and Vanguard's
``sharesHeld`` is ``"0"`` on every bond row. So for SPTL/VGLT/EDV,
``holdings_panel.par_per_share`` is NaN, ``flag_flow_days`` produces no flow flags, and
the ``par_per_share`` signal in ``signals.py`` is **dead, not noisy**. The flag exists so
a caller can refuse those funds for a share-count-dependent signal instead of receiving
an all-NaN column and reading it as "no signal here". Weight-based signals are unaffected:
``Weight (%)`` is published by all three.

STRIPS caveat
-------------
``GOVZ`` and ``EDV`` hold STRIPS -- GOVZ principal only, EDV both coupon and principal
(measured: 80 EDV positions on 2026-07-31, ``United States Treasury Strip Principal`` and
``United States Treasury Strip Coupon``). Those CUSIPs do not appear in the FedInvest
coupon-bond universe and will not join the pricing panel. They are kept in the dataset
because their *demand* lands on the same maturity sector as TLT's, and excluded from
anything that needs a bond price. ``prices_from_fedinvest=False`` is that switch, and it
is honoured by the panel builder rather than being a comment here. STRIPS funds do NOT
belong in any coupon-bucket aggregation -- a principal STRIP and the coupon bond it was
stripped from are different instruments with different demand curves.

What is NOT here, and why
-------------------------
``ZROZ`` (PIMCO 25+ Year Zero Coupon U.S. Treasury Index ETF, $1.47bn) meets the size cut
and would fit the STRIPS bucket, but **no PIMCO holdings endpoint has been measured**.
The rule this file states above applies to it: a fund whose data source has not been
probed is absent, and the absence is a finding rather than an omission.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class ETFSpec:
    ticker: str
    issuer: str                        # also selects the provider module: see PROVIDER_MODULES
    fund_id: str                       # portfolioId for iShares; the URL ticker otherwise
    name: str
    aum_usd: float                     # dated by aum_asof, from the issuer or etfdb
    maturity_band: Optional[Tuple[float, float]]   # remaining-maturity inclusion rule, years
    rebalance: str = "month_end"
    inception: datetime.date = datetime.date(2000, 1, 1)
    prices_from_fedinvest: bool = True
    instrument: str = "coupon"         # coupon | strips | bill | target_maturity
    #: When the AUM above was read. Carried as data so ">$1bn" is a fact with a date on
    #: it rather than a recollection, and so a stale figure is visible without archaeology.
    aum_asof: datetime.date = datetime.date(2026, 8, 19)
    #: "dated" -> the endpoint serves a file for a date you name (backfillable).
    #: "current_only" -> it serves one file, whatever you ask for (snapshot forward).
    history: str = "dated"
    #: How often a NEW document appears: "daily" or "month_end".
    cadence: str = "daily"
    #: False when the issuer publishes no fund share count -- see the module docstring.
    #: par_per_share and every signal built on it are DEAD for such a fund, not noisy.
    publishes_shares_outstanding: bool = True
    #: Whose book the published document describes. "etf" -> the ETF share class.
    #: "fund" -> the whole multi-share-class fund, of which the ETF is one class; par and
    #: market value are then LARGER than the ETF's and weights are still book-relative.
    book_scope: str = "etf"

    @property
    def band_low(self) -> Optional[float]:
        return None if self.maturity_band is None else self.maturity_band[0]

    @property
    def band_high(self) -> Optional[float]:
        return None if self.maturity_band is None else self.maturity_band[1]

    @property
    def is_snapshot_only(self) -> bool:
        return self.history == "current_only"


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

#: Non-iShares funds. Listed only for issuers whose endpoint has been MEASURED -- see
#: ``providers/ssga.py`` and ``providers/vanguard.py`` for what each probe found, on what
#: date, and with what payload. An issuer that is absent here is absent because nobody has
#: probed it, which is a finding rather than an omission (``ZROZ``/PIMCO is the current
#: case). Both issuers below are ``current_only``: they contribute a snapshot per run and
#: accumulate a panel FORWARD; neither can be backfilled.
#:
#: AUM figures are etfdb's, read 2026-08-20, and are the ETF share class in every case.
#: For the two Vanguard funds that is deliberately NOT the same book the holdings
#: document describes -- ``book_scope="fund"``. Cross-checked on Vanguard's own VGLT fact
#: sheet (as of 2026-06-30): ETF total net assets $10,482mm, FUND total net assets
#: $15,152mm, and the holdings JSON's market values sum to $14.588bn on 2026-07-31.
OTHER: Dict[str, ETFSpec] = {
    s.ticker: s
    for s in [
        # SPDR Portfolio Long Term Treasury. Tracks the Bloomberg Long U.S. Treasury
        # Index: US Treasury obligations with 10+ years remaining. Launched 2007-05-23 as
        # TLO (SPDR Bloomberg Barclays Long Term Treasury); renamed SPTL in Oct 2017.
        # Measured 2026-08-19: 100 bonds, 10.49y-29.99y, market value $10.987bn against
        # $10.848bn of AUM -- a standalone ETF, so the document IS the ETF's book.
        ETFSpec("SPTL", "ssga", "SPTL", "SPDR Portfolio Long Term Treasury ETF",
                10.848e9, (10.0, 1e9), inception=datetime.date(2007, 5, 23),
                aum_asof=datetime.date(2026, 8, 20),
                history="current_only", cadence="daily",
                publishes_shares_outstanding=False, book_scope="etf"),
        # Vanguard Long-Term Treasury. Tracks the Bloomberg U.S. Long Treasury Bond Index
        # (10+ years). Benchmark spliced: Bloomberg U.S. Long Government Float Adjusted
        # through 2017-12-11, Long Treasury Bond thereafter -- so the band alone does not
        # describe what this fund held before 2018. Measured 2026-07-31: 99 bonds,
        # 10.55y-29.79y. Month-end cadence; the July file was still current on Aug 20.
        ETFSpec("VGLT", "vanguard", "VGLT", "Vanguard Long-Term Treasury ETF",
                10.368e9, (10.0, 1e9), inception=datetime.date(2009, 11, 19),
                aum_asof=datetime.date(2026, 8, 20),
                history="current_only", cadence="month_end",
                publishes_shares_outstanding=False, book_scope="fund"),
        # Vanguard Extended Duration Treasury. Tracks the Bloomberg U.S. Treasury STRIPS
        # 20-30 Year Equal Par Bond Index -- an EQUAL PAR index, so its weights are a
        # rule, not a market-value outcome, and it holds coupon STRIPS as well as
        # principal. Out of the coupon bucket and out of the pricing panel. Measured
        # 2026-07-31: 80 positions, $3.871bn of market value against $3.479bn ETF AUM
        # (whole-fund again, not separately confirmed on an EDV fact sheet).
        ETFSpec("EDV", "vanguard", "EDV", "Vanguard Extended Duration Treasury ETF",
                3.479e9, (20.0, 30.0), inception=datetime.date(2007, 12, 6),
                aum_asof=datetime.date(2026, 8, 20),
                history="current_only", cadence="month_end",
                publishes_shares_outstanding=False, book_scope="fund",
                prices_from_fedinvest=False, instrument="strips"),
    ]
}

REGISTRY: Dict[str, ETFSpec] = {**ISHARES, **OTHER}

#: issuer -> the dotted path of the module that knows how to fetch it. Resolved lazily
#: (``provider_module``) so importing the registry does not drag in ``requests`` or
#: ``openpyxl``, and so a broken provider fails where it is used rather than at import.
PROVIDER_MODULES: Dict[str, str] = {
    "ishares": "MDP.ETFHoldings.providers.ishares",
    "ssga": "MDP.ETFHoldings.providers.ssga",
    "vanguard": "MDP.ETFHoldings.providers.vanguard",
}

#: The funds the long-end micro-RV study actually trades against. The 20+ band is where
#: one fund (TLT, $47bn) owns a double-digit share of the free float of every bond in a
#: 120-CUSIP sector, which is the only place in the Treasury curve where an ETF's
#: rebalance can plausibly move a yield.
LONG_END = ("TLT", "TLH", "GOVZ")

#: Everything with a coupon-bond band, i.e. everything that can join the price panel.
CURVE_LADDER = ("SHY", "IEI", "IEF", "TLH", "TLT", "GOVT")

#: The multi-issuer long-end coupon set: the funds that hold the actual bonds the
#: micro-RV study trades, across the two index families that reach the 20+ sector.
#: Deliberately NOT merged into ``LONG_END`` -- that tuple is what the single-fund
#: results on the parent branch were produced with, and silently widening it would make
#: an old number and a new number look like the same experiment.
COUPON_LONG = ("TLT", "SPTL", "VGLT")

#: STRIPS funds whose demand lands on the same maturity sector. They are NOT part of any
#: coupon aggregation: a principal STRIP is a different instrument from the bond it came
#: out of, and adding its par to a coupon bucket double-counts nothing and explains less.
STRIPS_LONG = ("GOVZ", "EDV")


def provider_module(spec_or_ticker):
    """The module that fetches a given fund. Import is lazy and by issuer, not by guess."""
    import importlib

    sp = spec_or_ticker if isinstance(spec_or_ticker, ETFSpec) else spec(spec_or_ticker)
    try:
        path = PROVIDER_MODULES[sp.issuer]
    except KeyError as exc:
        raise KeyError(
            f"{sp.ticker}: no provider is registered for issuer {sp.issuer!r}. A fund "
            f"whose endpoint has not been probed cannot be fetched; add a module under "
            f"MDP/ETFHoldings/providers/ and register it in PROVIDER_MODULES."
        ) from exc
    return importlib.import_module(path)


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

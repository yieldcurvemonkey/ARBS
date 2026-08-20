"""Vanguard month-end holdings, from the investor-site profile API.

The endpoint
------------
``https://investor.vanguard.com/investment-products/etfs/profile/api/{ticker}/
portfolio-holding/bond``

Measured 2026-08-20: HTTP 200 ``application/json`` for VGLT (42,384 bytes, 99 positions)
and EDV (34,284 bytes, 80 positions). The ticker is case-insensitive. Shape::

    {"size": 99,
     "asOfDate": "2026-07-31T00:00:00-04:00",
     "self": {...},
     "fund": {"entity": [ {longName, shortName, sharesHeld, marketValue, couponRate,
                           maturityDate, faceAmount, ticker, isin, percentWeight,
                           notionalValue, cusip, sedol, ...}, ... ]}}

THE trap: ``asOfDate`` is accepted and silently ignored
-------------------------------------------------------
``?asOfDate=2026-06-30`` returns **HTTP 200 with ``asOfDate 2026-07-31`` in the body**
and no warning of any kind. A fetcher that trusted the request would write a year of
byte-identical month-end snapshots stamped with twelve different dates, and every
``diff()`` over that panel would report eleven months of zero rebalancing and one month
of a year's worth. So:

* the parameter is **never put on the wire** -- sending a knob that does nothing
  manufactures the appearance of a dated request;
* the row is keyed on the ``asOfDate`` the *document* reports; and
* a caller that names a date and gets a different one is told, by
  ``_base.check_requested_date`` (warning, or :class:`IgnoredDateRequest` under
  ``strict_date=True``).

Cadence is MONTH-END, not daily. The July file was still being served on 2026-08-20.

The document describes the FUND, not the ETF share class
--------------------------------------------------------
Measured and then confirmed against Vanguard's own VGLT fact sheet (as of 2026-06-30):

    ETF total net assets   $10,482 million
    Fund total net assets  $15,152 million

The holdings JSON's market values sum to **$14.588bn** for VGLT on 2026-07-31 -- the
whole multi-share-class fund (ETF + Admiral + institutional), 1.39x the ETF. EDV sums to
$3.871bn against $3.479bn of ETF AUM, the same phenomenon at a smaller ratio (not
separately confirmed against an EDV fact sheet).

What that does and does not affect:

* ``percentWeight`` and any active weight built from it are **unaffected** -- they are
  book-relative and the share classes hold one book.
* ``faceAmount`` (stored as ``Par Value``) is **whole-fund par**. Any footprint or
  free-float-ownership number computed from it measures the index fund's demand, not the
  ETF's, and overstates the ETF by roughly 1.4x for VGLT. Label it, do not net it out:
  the demand is real and lands on the same bonds; it is simply not all ETF demand.

``shares_outstanding`` is not published here either
---------------------------------------------------
``sharesHeld`` is ``"0"`` on every bond row (it is a share count for equity holdings),
and there is no fund-level share count in this payload. ``shares_outstanding`` is
therefore ``NaN``, which makes ``holdings_panel.par_per_share`` and the ``par_per_share``
signal in ``signals.py`` **dead for these funds** rather than noisy.
``ETFSpec.publishes_shares_outstanding`` is the flag to check before asking for them.

Benchmark history worth carrying
--------------------------------
VGLT's fact sheet splices its benchmark: *Bloomberg U.S. Long Government Float Adjusted
Index through December 11, 2017; Bloomberg U.S. Long Treasury Bond Index thereafter.*
The pre-2018 index was Government, not Treasury-only, so a maturity band alone does not
describe what VGLT held before 2018. This provider only serves the current month, so it
cannot reach that far -- but the registry records the band that applies today.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from typing import Optional

import numpy as np
import pandas as pd

from MDP.ETFHoldings.providers._base import (  # noqa: F401  (re-exported on purpose)
    BLOCKED_STATUSES,
    Blocked,
    FetchError,
    HoldingsFile,
    IgnoredDateRequest,
    LayoutChanged,
    check_requested_date,
    check_weight_units,
    get_with_retries,
    isin_to_cusip,
    validate_frame,
)

BASE_URL = (
    "https://investor.vanguard.com/investment-products/etfs/profile/api/{ticker}"
    "/portfolio-holding/bond"
)

HEADERS = {
    "Accept": "application/json",
    "Referer": "https://investor.vanguard.com/investment-products/etfs/profile/",
}

#: Wire field -> shared schema column. ``cusip``/``isin`` are handled separately because
#: they are cross-checked against each other rather than simply renamed.
FIELD_MAP = {
    "longName": "Name",
    "faceAmount": "Par Value",
    "marketValue": "Market Value",
    "percentWeight": "Weight (%)",
    "couponRate": "Coupon (%)",
    "maturityDate": "Maturity",
    "sedol": "SEDOL",
}


def _as_of(stamp: str) -> Optional[datetime.date]:
    """``"2026-07-31T00:00:00-04:00"`` -> ``date(2026, 7, 31)``.

    Sliced, not parsed with a timezone: the stamp's offset is New York's, so converting
    to UTC would move a month-end file stamped midnight ET onto the 1st of the next
    month and mis-key every row in it.
    """
    if not isinstance(stamp, str) or len(stamp) < 10:
        return None
    try:
        return datetime.date.fromisoformat(stamp[:10])
    except ValueError:
        return None


def parse(content, *, ticker: str, requested: datetime.date) -> Optional[HoldingsFile]:
    """Parse one Vanguard holdings payload (bytes or str).

    Returns ``None`` for a 200 that is not a holdings payload -- an HTML shell, an error
    object, a body with no ``fund.entity`` list. Raises :class:`LayoutChanged` when it
    *is* the payload but a field this parser depends on has moved.
    """
    raw = content if isinstance(content, bytes) else str(content).encode("utf-8")
    try:
        doc = json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return None
    if not isinstance(doc, dict):
        return None

    ents = doc.get("fund", {})
    ents = ents.get("entity") if isinstance(ents, dict) else None
    if not isinstance(ents, list) or not ents:
        return None
    if "asOfDate" not in doc:
        return None

    as_of = _as_of(doc["asOfDate"])
    if as_of is None:
        raise LayoutChanged(
            f"vanguard {ticker}: asOfDate {doc['asOfDate']!r} does not parse. Without the "
            f"document's own date the row would be keyed on the request -- and this "
            f"endpoint ignores the requested date silently."
        )

    e = pd.DataFrame(ents)
    missing = [k for k in ("longName", "faceAmount", "marketValue", "percentWeight",
                           "couponRate", "maturityDate") if k not in e.columns]
    if missing:
        raise LayoutChanged(
            f"vanguard {ticker}: entity objects are missing {missing}; got "
            f"{sorted(e.columns)[:20]}."
        )
    if "cusip" not in e.columns and "isin" not in e.columns:
        raise LayoutChanged(
            f"vanguard {ticker}: entities carry neither 'cusip' nor 'isin'. There is no "
            f"key to join these positions to a bond panel."
        )

    isin = e["isin"].astype(str).str.strip().str.upper() if "isin" in e.columns \
        else pd.Series("", index=e.index)
    wire_cusip = e["cusip"].astype(str).str.strip().str.upper() if "cusip" in e.columns \
        else pd.Series("", index=e.index)
    wire_cusip = wire_cusip.replace({"": np.nan, "NAN": np.nan, "NONE": np.nan})
    from_isin = isin.map(isin_to_cusip)

    # Cross-check, do not pick a favourite. Both fields were present and agreed on
    # 99/99 VGLT rows and 80/80 EDV rows on 2026-08-20; a disagreement means one of the
    # two columns has moved and the wrong one would join to a real but different bond.
    clash = from_isin.notna() & wire_cusip.notna() & (from_isin != wire_cusip)
    if bool(clash.any()):
        bad = e.loc[clash, ["isin", "cusip"]].head(3).to_dict("records")
        raise LayoutChanged(
            f"vanguard {ticker}: {int(clash.sum())} rows where cusip and isin[2:11] "
            f"disagree, e.g. {bad}. One of the two fields moved."
        )

    cusip = from_isin.where(from_isin.notna(), wire_cusip)
    is_security = cusip.notna()
    if not bool(is_security.any()):
        raise LayoutChanged(
            f"vanguard {ticker}: {len(e)} positions and not one resolves to a CUSIP."
        )

    name_u = e["longName"].astype(str).str.upper()
    out = pd.DataFrame(index=e.index)
    out["ticker"] = ticker.upper()
    out["date"] = pd.Timestamp(as_of)
    for src, dst in FIELD_MAP.items():
        out[dst] = e[src] if src in e.columns else np.nan
    out["ISIN"] = isin.where(is_security)
    # Unresolvable rows keep a real identifier rather than NaN: ``store.append_holdings``
    # dedupes on ["date", "CUSIP"], so two NaN keys on one date would collapse into one.
    fallback = isin.replace({"": np.nan}).where(lambda s: s.notna(), e.get("sedol"))
    out["CUSIP"] = cusip.where(is_security, fallback)
    out["Asset Class"] = np.where(is_security, "Fixed Income", "Cash and/or Derivatives")
    out["Sector"] = np.where(
        ~is_security, "Cash",
        np.where(name_u.str.contains("STRIP", na=False), "Treasury STRIPS",
                 np.where(name_u.str.contains("TREASURY", na=False), "Treasuries", "Other")),
    )

    for c in ("Weight (%)", "Coupon (%)", "Par Value", "Market Value"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out["Maturity"] = pd.to_datetime(out["Maturity"], format="%m/%d/%Y", errors="coerce")

    # Published by iShares, not by Vanguard. NaN so one schema serves all issuers.
    for c in ("Price", "Mod. Duration", "YTM (%)"):
        out[c] = np.nan

    # ``sharesHeld`` is "0" on every bond row and is a per-holding equity share count, not
    # a fund share count. NaN, never zero -- zero would make par_per_share infinite.
    out["shares_outstanding"] = np.nan
    # Whole-FUND market value, not the ETF share class. See the module docstring.
    out["fund_market_value"] = float(out["Market Value"].sum(skipna=True))
    out["requested_date"] = pd.Timestamp(requested)

    out = out.reset_index(drop=True)
    validate_frame(out, ticker=ticker, source="vanguard")
    check_weight_units(out, ticker=ticker, source="vanguard")

    return HoldingsFile(
        ticker=ticker.upper(),
        as_of=as_of,
        requested=requested,
        shares_outstanding=float("nan"),
        content_sha1=hashlib.sha1(raw).hexdigest(),
        frame=out,
    )


def fetch(
    fund_id: str,
    requested: Optional[datetime.date] = None,
    *,
    ticker: str,
    session=None,
    pool=None,
    max_attempts: int = 4,
    timeout: float = 45.0,
    strict_date: bool = False,
) -> Optional[HoldingsFile]:
    """The current month-end holdings for one Vanguard fund.

    ``requested`` is **bookkeeping only and is never sent**. The endpoint accepts an
    ``asOfDate`` parameter and ignores it, returning 200 with a different date in the
    body; putting it on the wire would dress a snapshot up as a dated request. Pass
    ``requested`` and a mismatch warns; pass ``strict_date=True`` and it raises
    :class:`IgnoredDateRequest`.

    Returns ``None`` only for a 200 that is not a holdings payload. A refusal raises
    :class:`Blocked`.
    """
    asked = requested is not None
    req = requested or datetime.date.today()
    url = BASE_URL.format(ticker=fund_id.lower())

    resp = get_with_retries(
        url, ticker=ticker, label="vanguard", headers=HEADERS, session=session, pool=pool,
        max_attempts=max_attempts, timeout=timeout,
    )
    hf = parse(resp.content, ticker=ticker, requested=req)
    if hf is None:
        return None
    return check_requested_date(hf, asked=asked, strict=strict_date, source="vanguard")

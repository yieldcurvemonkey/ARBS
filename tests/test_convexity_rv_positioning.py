r"""CFTC positioning as a *signal*: the release lag, and the dealer category.

Two things had to change before this panel could be read by a backtest.

**1. It was stamped by report date and never lagged.** The Traders in Financial
Futures report measures positions as of **Tuesday** and is published **Friday
15:30 ET**. ``build_positioning_panel`` indexed on
``Report_Date_as_YYYY-MM-DD`` and went straight to ``resample("B").ffill()``, so
a strategy reading Wednesday's value was reading a number that did not exist
until Friday — three business days of look-ahead, inside the signal, before any
backtest code ran.

Measured on the local cache: **329 of 332 report dates are Tuesdays**, the modal
gap is exactly 7 days (325/331), and **no column carries a release or
publication stamp** — so nothing in the data itself stops a reader from treating
Tuesday's position as known on Tuesday.

This is the same defect class as the ``bfill`` just removed from the SR3 price
panel, and as the JPM NLP score vintage already recorded in this repo (60 % of
score rows published *after* the speech they scored).

**2. There was no dealer metric**, although ``Dealer_Positions_Long_All`` and
``Dealer_Positions_Short_All`` are fully populated. The Dealer/Intermediary
category is precisely the one the convexity research is about:

    "Dealers, who are on the other side of the shorts established by hedge funds
    and asset managers, have ended up with significant long ED positions.
    Convexity adjustments have therefore widened to compensate dealers for this
    concentration risk."

so a positioning-enriched convexity signal that cannot read the dealer leg is
missing the variable the hypothesis names.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from BT.signals.cftc_positioning import (
    RELEASE_LAG_BUSINESS_DAYS,
    build_positioning_panel,
)


def _raw(dates, name="UST 10Y NOTE - CHICAGO BOARD OF TRADE", **cols):
    n = len(dates)
    base = {
        "Market_and_Exchange_Names": [name] * n,
        "Report_Date_as_YYYY-MM-DD": [d.strftime("%Y-%m-%d") for d in dates],
        "Lev_Money_Positions_Long_All": np.full(n, 100.0),
        "Lev_Money_Positions_Short_All": np.full(n, 40.0),
        "Asset_Mgr_Positions_Long_All": np.full(n, 200.0),
        "Asset_Mgr_Positions_Short_All": np.full(n, 50.0),
        "Dealer_Positions_Long_All": np.full(n, 300.0),
        "Dealer_Positions_Short_All": np.full(n, 90.0),
    }
    base.update(cols)
    return pd.DataFrame(base)


#: Three consecutive Tuesdays.
TUESDAYS = [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-09"),
            pd.Timestamp("2024-01-16")]


def test_the_report_date_itself_does_not_carry_the_number():
    """The Tuesday reading must not be visible on the Tuesday.

    This is the whole point. If it is, every downstream backtest is reading
    Friday's release on Tuesday.
    """
    raw = _raw(TUESDAYS)
    panel = build_positioning_panel(raw=raw, tenors=["10Y"], metric="dealer_net")

    first_report = TUESDAYS[0]
    visible = panel.loc[panel.index <= first_report, "10Y"].dropna()
    assert visible.empty, (
        f"the 2024-01-02 report is already readable on or before its own report "
        f"date: {visible.to_dict()}. It is not published until the Friday."
    )


def test_the_number_becomes_visible_only_after_the_release():
    """Visible on the release date, not before it."""
    raw = _raw(TUESDAYS)
    panel = build_positioning_panel(raw=raw, tenors=["10Y"], metric="dealer_net")

    release = TUESDAYS[0] + pd.tseries.offsets.BDay(RELEASE_LAG_BUSINESS_DAYS)
    assert release.dayofweek == 4, (
        f"Tuesday + {RELEASE_LAG_BUSINESS_DAYS} business days is "
        f"{release:%A}, not Friday — the lag no longer matches the CFTC "
        "publication convention"
    )

    prior = panel.loc[panel.index < release, "10Y"].dropna()
    assert prior.empty, f"readable before the release: {prior.to_dict()}"
    assert not np.isnan(panel.loc[release, "10Y"]), "not readable on the release date"
    assert panel.loc[release, "10Y"] == pytest.approx(300.0 - 90.0)


def test_every_metric_is_shifted_by_the_same_lag():
    """A lag applied to one category and not another is worse than none."""
    raw = _raw(TUESDAYS)
    firsts = {}
    for metric in ("lev_net", "am_net", "total_net", "dealer_net"):
        p = build_positioning_panel(raw=raw, tenors=["10Y"], metric=metric)
        firsts[metric] = p["10Y"].first_valid_index()
    assert len(set(firsts.values())) == 1, firsts


def test_dealer_net_is_long_minus_short():
    raw = _raw(TUESDAYS)
    panel = build_positioning_panel(raw=raw, tenors=["10Y"], metric="dealer_net")
    assert panel["10Y"].dropna().unique().tolist() == [pytest.approx(210.0)]


def test_dealer_and_the_others_sum_the_way_the_thesis_says():
    """Dealers sit on the other side of leveraged money and asset managers.

    Not an identity — the TFF categories also include Other Reportables and
    Non-Reportables — so this asserts only that the dealer leg is computed from
    the dealer columns and is not a copy of another category.
    """
    raw = _raw(TUESDAYS)
    got = {m: build_positioning_panel(raw=raw, tenors=["10Y"], metric=m)["10Y"].dropna().iloc[0]
           for m in ("lev_net", "am_net", "dealer_net")}
    assert got["lev_net"] == pytest.approx(60.0)
    assert got["am_net"] == pytest.approx(150.0)
    assert got["dealer_net"] == pytest.approx(210.0)
    assert got["dealer_net"] != got["am_net"]


def test_an_unknown_metric_raises_rather_than_returning_empty():
    """An empty frame is how a typo becomes 'the signal had no effect'."""
    with pytest.raises((KeyError, ValueError)):
        build_positioning_panel(raw=_raw(TUESDAYS), tenors=["10Y"], metric="dealer")


def test_stir_contracts_are_reachable():
    """SOFR-3M is the contract the pack-convexity work needs.

    The map covered only 2Y/5Y/10Y/30Y treasuries, so a STIR strategy could not
    read positioning at all.
    """
    raw = _raw(TUESDAYS, name="SOFR-3M - CHICAGO MERCANTILE EXCHANGE")
    panel = build_positioning_panel(raw=raw, tenors=["SOFR3M"], metric="dealer_net")
    assert not panel.empty, "SOFR-3M is not in the contract map"
    assert panel["SOFR3M"].dropna().iloc[0] == pytest.approx(210.0)


def test_the_pre_2022_rename_is_carried():
    """CFTC renamed the markets in Feb-2022; both vintages must map."""
    old = _raw([pd.Timestamp("2022-01-25")], name="3-MONTH SOFR - CHICAGO MERCANTILE EXCHANGE")
    new = _raw([pd.Timestamp("2022-02-08")], name="SOFR-3M - CHICAGO MERCANTILE EXCHANGE")
    panel = build_positioning_panel(raw=pd.concat([old, new], ignore_index=True),
                                    tenors=["SOFR3M"], metric="dealer_net")
    assert panel["SOFR3M"].notna().sum() > 0
    assert panel["SOFR3M"].first_valid_index() < pd.Timestamp("2022-02-08"), (
        "the pre-rename vintage is not mapped, so the series starts at the rename"
    )


def test_lag_is_configurable_and_zero_reproduces_the_old_behaviour():
    """The old behaviour stays reachable, but only by asking for it explicitly."""
    raw = _raw(TUESDAYS)
    unlagged = build_positioning_panel(raw=raw, tenors=["10Y"], metric="dealer_net",
                                       release_lag_bdays=0)
    assert unlagged["10Y"].first_valid_index() == TUESDAYS[0], (
        "release_lag_bdays=0 should put the value back on its report date"
    )

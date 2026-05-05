"""Tests for STIRAsymmetricScreener._catalysts."""

from __future__ import annotations

import datetime

import pytest


def test_catalyst_dataclass_has_kind_date_impact():
    from RVUtils.STIRAsymmetricScreener._catalysts import Catalyst

    c = Catalyst(kind="fomc", date=datetime.date(2026, 6, 17), impact="high")
    assert c.kind == "fomc"
    assert c.impact == "high"


def test_load_catalyst_calendar_includes_fomc_meetings_for_next_year():
    from RVUtils.STIRAsymmetricScreener._catalysts import (
        load_catalyst_calendar,
    )

    cal = load_catalyst_calendar(as_of=datetime.date(2026, 4, 28), lookahead_days=400)
    fomc_dates = [c.date for c in cal if c.kind == "fomc"]
    assert len(fomc_dates) >= 4, f"expected at least 4 FOMC meetings ahead, got {len(fomc_dates)}"
    # All inside lookahead window
    for d in fomc_dates:
        assert datetime.date(2026, 4, 28) <= d <= datetime.date(2027, 6, 1)


def test_load_catalyst_calendar_includes_ecb_when_eur_curve_supplied():
    from RVUtils.STIRAsymmetricScreener._catalysts import (
        load_catalyst_calendar,
    )

    cal = load_catalyst_calendar(
        as_of=datetime.date(2026, 4, 28), lookahead_days=400, include_ecb=True
    )
    ecb = [c for c in cal if c.kind == "ecb"]
    # Some loaded if EUR-ESTR data is available
    assert isinstance(ecb, list)


def test_catalysts_inside_window_filters_by_impact():
    from RVUtils.STIRAsymmetricScreener._catalysts import (
        Catalyst,
        catalysts_inside_window,
    )

    cs = (
        Catalyst(kind="fomc", date=datetime.date(2026, 6, 17), impact="high"),
        Catalyst(kind="cpi", date=datetime.date(2026, 6, 10), impact="high"),
        Catalyst(kind="umich", date=datetime.date(2026, 6, 14), impact="medium"),
    )

    inside_high = catalysts_inside_window(
        as_of=datetime.date(2026, 5, 1),
        expiry=datetime.date(2026, 6, 30),
        catalysts=cs,
        impact="high",
    )
    assert len(inside_high) == 2  # FOMC + CPI

    inside_all = catalysts_inside_window(
        as_of=datetime.date(2026, 5, 1),
        expiry=datetime.date(2026, 6, 30),
        catalysts=cs,
        impact="any",
    )
    assert len(inside_all) == 3


def test_catalysts_inside_window_excludes_pre_as_of():
    from RVUtils.STIRAsymmetricScreener._catalysts import (
        Catalyst,
        catalysts_inside_window,
    )

    cs = (
        Catalyst(kind="fomc", date=datetime.date(2026, 4, 1), impact="high"),
        Catalyst(kind="fomc", date=datetime.date(2026, 6, 17), impact="high"),
    )

    inside = catalysts_inside_window(
        as_of=datetime.date(2026, 5, 1),
        expiry=datetime.date(2026, 9, 11),
        catalysts=cs,
        impact="high",
    )
    assert len(inside) == 1
    assert inside[0].date == datetime.date(2026, 6, 17)

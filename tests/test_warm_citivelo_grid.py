"""The Citi Velocity warm grid, and the two intraday jobs added beside it.

What is pinned here:

* No banked series is orphaned. The computed-timeseries symbol is a sha1 of the
  tenor string AS TYPED, so renaming a tenor's spelling does not migrate its
  history - it abandons it and starts a new one alongside. Every tenor the grid
  used to carry must still be in it, spelled identically.
* Every package's legs are themselves warmed series, so a fly can be
  decomposed by whoever reads it.
* The intraday bond stride stays under the 50-reference-point line at which
  ``FixedRateBondsTB`` silently switches the computed-timeseries cache off in
  BOTH directions - past which the job would price a session and persist none
  of it while reporting a frame.

Hermetic: constants and grammar only. The measurements that justify the sizes
are in the module docstrings; the runs that produced them are in the commit.
"""

import datetime
import importlib.util
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def warmer():
    spec = importlib.util.spec_from_file_location(
        "daily_cache_warmer_grid_under_test",
        os.path.join(REPO_ROOT, "scripts", "daily_cache_warmer.py"),
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


#: Exactly what the grid carried before the enrichment. Not a sample - the whole
#: set, because the property being tested is that NONE of them moved.
_PREVIOUSLY_WARMED_OUTRIGHTS = ("1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y", "30Y")
_PREVIOUSLY_WARMED_FORWARDS = ("1y1y", "1y5y", "2y5y", "5y5y", "5y10y", "10y10y")
_PREVIOUSLY_WARMED_USD_FORWARDS = _PREVIOUSLY_WARMED_FORWARDS + (
    "1y2y", "1y3y", "1y7y", "1y10y", "1y15y", "1y20y", "1y30y",
)
_PREVIOUSLY_WARMED_PACKAGES = (
    "2y/5y", "2y/10y", "5y/10y", "10y/30y", "2y/5y/10y", "5y/10y/30y",
)
_PREVIOUSLY_WARMED_INTRADAY = ("2Y", "5Y", "10Y", "30Y", "2y/10y", "5y/10y/30y")


# ── continuity ───────────────────────────────────────────────────────

def test_no_usd_series_was_orphaned(warmer):
    grid = set(warmer._citivelo_eod_tenors("USD-SOFR-1D"))
    was = set(_PREVIOUSLY_WARMED_OUTRIGHTS) | set(_PREVIOUSLY_WARMED_USD_FORWARDS) | set(
        _PREVIOUSLY_WARMED_PACKAGES)
    assert was <= grid, f"dropped: {sorted(was - grid)}"


def test_no_non_usd_series_was_orphaned(warmer):
    grid = set(warmer._citivelo_eod_tenors("EUR-ESTR-1D"))
    was = set(_PREVIOUSLY_WARMED_OUTRIGHTS) | set(_PREVIOUSLY_WARMED_FORWARDS) | set(
        _PREVIOUSLY_WARMED_PACKAGES)
    assert was <= grid, f"dropped: {sorted(was - grid)}"


def test_no_intraday_series_was_orphaned(warmer):
    grid = set(warmer._CITIVELO_INTRADAY_TENORS)
    assert set(_PREVIOUSLY_WARMED_INTRADAY) <= grid


def test_the_grid_has_no_duplicates(warmer):
    for curve in ("USD-SOFR-1D", "EUR-ESTR-1D"):
        grid = warmer._citivelo_eod_tenors(curve)
        assert len(grid) == len(set(grid)), curve
    assert len(warmer._CITIVELO_INTRADAY_TENORS) == len(set(warmer._CITIVELO_INTRADAY_TENORS))


# ── what was added ───────────────────────────────────────────────────

def test_usd_carries_forward_curves_and_flies(warmer):
    grid = set(warmer._citivelo_eod_tenors("USD-SOFR-1D"))
    assert {"1y5y/1y10y", "5y5y/10y10y", "1y1y/2y1y"} <= grid, "forward curves"
    assert {"1y2y/1y5y/1y10y", "1y5y/1y10y/1y30y", "5y5y/10y10y/20y10y"} <= grid, "forward flies"


def test_the_non_usd_curves_do_not_get_forward_packages(warmer):
    """A forward fly on a thin long end is a number with no market behind it."""
    grid = set(warmer._citivelo_eod_tenors("EUR-ESTR-1D"))
    for package in warmer._CITIVELO_USD_SOFR_EOD_FWD_PACKAGES:
        assert package not in grid


def test_intraday_carries_forwards_and_forward_packages(warmer):
    grid = set(warmer._CITIVELO_INTRADAY_TENORS)
    assert {"1y1y", "5y5y", "10y10y"} <= grid
    assert {"1y1y/2y1y", "5y5y/10y10y"} <= grid


# ── closure ──────────────────────────────────────────────────────────

def test_every_package_leg_is_itself_warmed(warmer):
    """A fly is only interpretable next to its legs."""
    warmer._assert_packages_are_closed()  # raises with the offenders named


def test_the_closure_check_actually_catches_an_unwarmed_leg(warmer, monkeypatch):
    """A check that cannot fail is worse than no check."""
    monkeypatch.setattr(
        warmer, "_CITIVELO_EOD_SPREADS",
        warmer._CITIVELO_EOD_SPREADS + ("2y/99y",),
    )
    with pytest.raises(AssertionError, match="99y"):
        warmer._assert_packages_are_closed()


def test_closure_is_case_insensitive(warmer, monkeypatch):
    """Outrights are banked UPPERCASE and package legs written lowercase.

    Both spellings are history that must not be renamed, and the two name the
    same swap - so a check that compared them verbatim would reject the grid
    that actually ships.
    """
    monkeypatch.setattr(
        warmer, "_CITIVELO_EOD_SPREADS",
        warmer._CITIVELO_EOD_SPREADS + ("2Y/10Y",),
    )
    warmer._assert_packages_are_closed()


# ── the intraday jobs ────────────────────────────────────────────────

def test_the_bond_intraday_stride_stays_under_the_fifty_point_cliff(warmer):
    """Past 50 reference points FixedRateBondsTB turns the cache off, silently.

    ``_skip_ts_cache = is_intraday and len(ref_points) > 50`` gates the READ and
    the WRITE. A job over that line prices a whole session, returns a frame, and
    persists nothing.
    """
    import pandas as pd

    day = datetime.date(2026, 8, 21)
    points = pd.date_range(
        datetime.datetime.combine(day, warmer._CV_BOND_INTRADAY_OPEN),
        datetime.datetime.combine(day, warmer._CV_BOND_INTRADAY_CLOSE),
        freq=warmer._CV_BOND_INTRADAY_FREQ,
    )
    assert len(points) <= 50, f"{len(points)} points would disable the cache"


def test_the_swap_spread_intraday_window_is_in_session(warmer):
    """Outside Citi's session every point raises StaleCurveError with a traceback.

    The minute CurveStore holds the Sunday-evening open and the small hours, so
    a Monday 01:44 curve exists whose newest spread print is Friday 17:59 -
    roughly 4,000 logged tracebacks on a Monday, costing more than the pricing.
    """
    assert warmer._CV_SWAP_SPREAD_INTRADAY_OPEN >= datetime.time(8, 0)
    assert warmer._CV_SWAP_SPREAD_INTRADAY_CLOSE <= datetime.time(20, 0)


def test_the_mi01_bond_store_finally_has_a_reader(warmer):
    """It was provided by one job and required by none - a write-only store."""
    readers = [
        j.name for j in warmer.WARM_JOBS if warmer._CV_BOND_TAGS_MI01 in j.requires
    ]
    assert readers, "nothing reads CITIVELO-TAGS-RATES.BOND-MI01"


def test_the_mi01_swap_spread_asset_is_its_own_key(warmer):
    """Two jobs writing one asset means one silently deletes the other's day."""
    assert warmer._CV_SWAP_SPREAD_TAGS_MI01 != warmer._CV_SWAP_SPREAD_TAGS
    providers = [
        j.name for j in warmer.WARM_JOBS if warmer._CV_SWAP_SPREAD_TAGS_MI01 in j.provides
    ]
    assert len(providers) == 1, providers


def test_the_new_store_job_runs_before_its_consumer(warmer):
    """assert_ordered covers this, but name the pair so a reorder says why."""
    names = [j.name for j in warmer.WARM_JOBS]
    assert names.index("CITIVELO swap-spread tags MI01 (store)") < names.index(
        "CITIVELO swap spreads INTRADAY"
    )
    assert names.index("CITIVELO UST universe tags INTRADAY (store)") < names.index(
        "CITIVELO UST timeseries values INTRADAY"
    )


# ── the grammar ──────────────────────────────────────────────────────

def test_every_tenor_in_the_grid_builds_a_query(warmer):
    """A tenor that does not parse becomes an empty column, not an error."""
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue

    tenors = (
        set(warmer._citivelo_eod_tenors("USD-SOFR-1D"))
        | set(warmer._citivelo_eod_tenors("EUR-ESTR-1D"))
        | set(warmer._CITIVELO_INTRADAY_TENORS)
    )
    for tenor in sorted(tenors):
        query = UnifiedQuery(curve="USD-SOFR-1D", tenor=tenor,
                             value=UnifiedValue.IRS_RATE)
        assert query.to_legacy() is not None, tenor


def test_a_forward_fly_really_parses_as_three_forward_legs(warmer):
    """The property the whole forward half of the grid rests on."""
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue

    from TB.IRSwapsTB import _decompose_rate_into_outright_legs

    query = UnifiedQuery(curve="USD-SOFR-1D", tenor="1y2y/1y5y/1y10y",
                         value=UnifiedValue.IRS_RATE)
    assert "FLY" in query.col_name()

    # The leg tenors are normalised to '1Yx2Y' form inside resolve_query, which
    # needs a curve; what is checkable without one is that the string splits
    # into three legs with fly weights. A two-leg spelling would come back as a
    # CURVE and a four-leg one raises, so this is the discriminating check.
    legs = _decompose_rate_into_outright_legs(query.to_legacy())
    assert legs == [(-1.0, "1y2y"), (2.0, "1y5y"), (-1.0, "1y10y")]

    curve = UnifiedQuery(curve="USD-SOFR-1D", tenor="1y5y/1y10y",
                         value=UnifiedValue.IRS_RATE)
    assert "CURVE" in curve.col_name()
    assert _decompose_rate_into_outright_legs(curve.to_legacy()) == [
        (-1.0, "1y5y"), (1.0, "1y10y"),
    ]

r"""Hermetic tests for the Citi Velocity swaption cube, QuantLib and rateslib.

The headline pair is :func:`test_correct_volspreads_ordering_round_trips` and
:func:`test_transposed_volspreads_still_constructs_but_fails_the_check`.

``ql.InterpolatedSwaptionVolatilityCube`` takes ``volSpreads`` as a 2-D matrix
whose ROWS are ordered **optionTenors outer, swapTenors inner** - 1y2y, 1y10y,
1y30y, 10y2y, ... Confirmed against SWPM. Both layouts have
``n_expiry * n_tenor`` rows, so QuantLib **constructs either one without
complaint** and the wrong one silently misprices. A round-trip assertion is
therefore the only honest proof the ordering is right, and a mutation check is the
only honest proof the assertion has teeth.

Everything is synthetic: normal vols in basis points, declining in tail, humped in
expiry, with a payer-skewed smile whose curvature decays with expiry. Nothing here
validates Citi's actual numbers - see the units note in ``vol/cube_data.py``.
"""

from __future__ import annotations

import datetime
import math
import pathlib

import numpy as np
import pandas as pd
import pytest
import QuantLib as ql
import rateslib as rl

from MDP.CitiVelocityExcel import tags as T
from MDP.CitiVelocityExcel.cache import CitiVeloTagCache
from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient
from MDP.CitiVelocityExcel.errors import UnknownTagError
from MDP.CitiVelocityExcel.testing import FakeExcelApp, FakeVelocityData
from MDP.CitiVelocityExcel.vol.cube_data import (
    RaggedCubeError,
    SwaptionCubeData,
    VolUnitError,
    cube_from_quotes,
    cube_tags,
    fetch_cube,
    vol_coverage,
)
from MDP.CitiVelocityExcel.vol.ql_cube import (
    VolCubeOrderingError,
    assert_vol_spread_ordering,
    build_ql_atm_matrix,
    build_ql_swaption_cube,
    swap_indices_for,
    vol_spreads_matrix,
)
from MDP.CitiVelocityExcel.vol.rl_cube import build_rl_vol_cube

AS_OF = datetime.date(2026, 8, 5)
CURRENCY = "USD"
EXPIRIES = ("1M", "3M", "6M", "1Y", "2Y", "5Y", "10Y")
TENORS = ("1Y", "2Y", "5Y", "10Y", "30Y")
OFFSETS = (-100.0, -50.0, -25.0, 25.0, 50.0, 100.0)
#: The columns handed to QuantLib. The ZERO column is an ATM anchor, not a quote.
SPREAD_COLUMNS = (-100.0, -50.0, -25.0, 0.0, 25.0, 50.0, 100.0)

#: A smaller, DELIBERATELY ASYMMETRIC grid for the QuantLib round trips. Every
#: round-tripped node costs QuantLib an atmStrike solve through the swap index, so
#: the full 7x5x7 = 245-node surface takes ~37s per test - too slow for the fast
#: gate to pay twice. 4 expiries x 3 tenors still detects a transposition (both
#: layouts have n_exp*n_ten rows, so QuantLib accepts either), and the asymmetry
#: makes it a stricter case than a square grid. The full surface is swept in the
#: slow-marked test below.
SMALL_EXPIRIES = ("1M", "1Y", "5Y", "10Y")
SMALL_TENORS = ("2Y", "10Y", "30Y")
SMALL_OFFSETS = (-50.0, -25.0, 25.0, 50.0)
SMALL_COLUMNS = (-50.0, -25.0, 0.0, 25.0, 50.0)

_YEARS = {"D": 1 / 365.25, "W": 7 / 365.25, "M": 30.4375 / 365.25, "Y": 1.0}
_PILLARS = (0.0, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 15.0, 20.0, 30.0, 45.0)


# ------------------------------------------------------------------ #
#                        the synthetic surface                       #
# ------------------------------------------------------------------ #


def _yrs(token: str) -> float:
    return float(token[:-1]) * _YEARS[token[-1]]


def _atm_bp(expiry: str, tenor: str) -> float:
    te, ts = _yrs(expiry), _yrs(tenor)
    return 55.0 + 60.0 * math.exp(-ts / 8.0) + 20.0 * math.exp(-te / 2.0) - 3.0 * math.log1p(te)


def _spread_bp(expiry: str, tenor: str, offset: float) -> float:
    te, ts = _yrs(expiry), _yrs(tenor)
    curvature = 6.0 + 4.0 * math.exp(-te)
    slope = -(3.0 + 2.0 * math.exp(-ts / 10.0))
    u = offset / 100.0
    return curvature * u * u + slope * u


def _synthetic_quotes(
    currency: str = CURRENCY,
    expiries=EXPIRIES,
    tenors=TENORS,
    offsets=OFFSETS,
) -> dict[str, float]:
    tag_map = cube_tags(
        currency=currency,
        expiries=expiries,
        tenors=tenors,
        offsets_bp=offsets,
        measure="NORMAL",
        skew_measure="NORMALABSOLUTE",
    )
    out: dict[str, float] = {}
    for tag, (kind, expiry, tenor, offset) in tag_map.items():
        base = _atm_bp(expiry, tenor)
        out[tag] = base if kind == "ATM" else base + _spread_bp(expiry, tenor, offset)
    return out


@pytest.fixture(scope="module")
def cube() -> SwaptionCubeData:
    return cube_from_quotes(
        quotes=_synthetic_quotes(),
        currency=CURRENCY,
        as_of=AS_OF,
        expiries=EXPIRIES,
        tenors=TENORS,
        offsets_bp=OFFSETS,
        served_unit="bp",
        source="pytest/synthetic",
    )

@pytest.fixture(scope="module")
def small_cube() -> SwaptionCubeData:
    """The asymmetric grid the QuantLib round trips use. See SMALL_EXPIRIES."""
    return cube_from_quotes(
        quotes=_synthetic_quotes(
            expiries=SMALL_EXPIRIES, tenors=SMALL_TENORS, offsets=SMALL_OFFSETS
        ),
        currency=CURRENCY,
        as_of=AS_OF,
        expiries=SMALL_EXPIRIES,
        tenors=SMALL_TENORS,
        offsets_bp=SMALL_OFFSETS,
        served_unit="bp",
        source="pytest/synthetic-small",
    )


def _zero(t: float) -> float:
    return 0.030 + 0.012 * (1.0 - math.exp(-t / 4.0))


@pytest.fixture(scope="module")
def curves():
    """A QuantLib and a rateslib curve carrying the SAME discount factors.

    Identical DFs on identical dates, so any forward difference between the two
    backends is a convention difference and not a curve difference.
    """
    ql_today = ql.Date(AS_OF.day, AS_OF.month, AS_OF.year)
    ql.Settings.instance().evaluationDate = ql_today
    dates = [ql_today + int(round(t * 365)) for t in _PILLARS]
    dfs = [math.exp(-_zero(t) * t) for t in _PILLARS]
    dfs[0] = 1.0
    ql_curve = ql.DiscountCurve(dates, dfs, ql.Actual365Fixed())
    ql_curve.enableExtrapolation()

    nodes = {
        datetime.datetime(AS_OF.year, AS_OF.month, AS_OF.day)
        + datetime.timedelta(days=int(round(t * 365))): df
        for t, df in zip(_PILLARS, dfs)
    }
    rl_curve = rl.Curve(
        nodes, interpolation="log_linear", calendar="nyc", convention="act360", id="test_sofr"
    )
    return ql.YieldTermStructureHandle(ql_curve), rl_curve


# ------------------------------------------------------------------ #
#                          the cube data set                         #
# ------------------------------------------------------------------ #


def test_cube_is_already_expiry_by_tenor_by_offset(cube: SwaptionCubeData):
    """Citi publishes a ready-made cube; interpolation reads BETWEEN nodes only."""
    assert cube.expiries() == list(EXPIRIES)
    assert cube.tenors() == list(TENORS)
    assert set(cube.offsets()) >= set(OFFSETS)
    assert cube.atm_vol("1Y", "10Y") == pytest.approx(_atm_bp("1Y", "10Y"))
    assert cube.vol("1Y", "10Y", -25.0) == pytest.approx(
        _atm_bp("1Y", "10Y") + _spread_bp("1Y", "10Y", -25.0)
    )


def test_units_guard_raises_rather_than_rescaling():
    """A magnitude heuristic would leave no record of which unit a vintage used.

    The sibling ``NormalSabrVolCube._normalize_normal_vol`` does
    ``v / 10_000 if abs(v) > 1 else v``, which silently divides a legitimately
    large normal vol by ten thousand and stores nothing about the decision. Here
    the unit is DECLARED and a mismatch is an exception.
    """
    decimals = {tag: value / 10_000.0 for tag, value in _synthetic_quotes().items()}
    with pytest.raises(VolUnitError) as excinfo:
        cube_from_quotes(
            quotes=decimals,
            currency=CURRENCY,
            as_of=AS_OF,
            expiries=EXPIRIES,
            tenors=TENORS,
            offsets_bp=OFFSETS,
            served_unit="bp",
        )
    assert "served_unit" in str(excinfo.value)


def test_ragged_cube_is_refused_by_default_and_droppable_on_request():
    """A hole in the cube must be named, not interpolated over silently."""
    quotes = _synthetic_quotes()
    victim = T.vol_atm(CURRENCY, "10Y", "30Y")
    quotes.pop(victim)

    with pytest.raises(RaggedCubeError) as excinfo:
        cube_from_quotes(
            quotes=quotes,
            currency=CURRENCY,
            as_of=AS_OF,
            expiries=EXPIRIES,
            tenors=TENORS,
            offsets_bp=OFFSETS,
            served_unit="bp",
        )
    assert victim in str(excinfo.value)

    relaxed = cube_from_quotes(
        quotes=quotes,
        currency=CURRENCY,
        as_of=AS_OF,
        expiries=EXPIRIES,
        tenors=TENORS,
        offsets_bp=OFFSETS,
        served_unit="bp",
        strict=False,
    )
    assert not relaxed.atm.isna().any().any(), "strict=False must drop, never NaN-fill"
    assert "10Y" not in relaxed.expiries() or "30Y" not in relaxed.tenors()


# ------------------------------------------------------------------ #
#                THE ORDERING CONTRACT, AND ITS TEETH                #
# ------------------------------------------------------------------ #


def test_correct_volspreads_ordering_round_trips(small_cube: SwaptionCubeData, curves):
    """Every node must come back out of the built QuantLib object unchanged.

    Rows ordered optionTenors OUTER, swapTenors INNER. Measured on this 7x5x7
    surface: max abs error ~1.4e-14 bp.
    """
    ql_handle, _ = curves
    built = build_ql_swaption_cube(
        cube=small_cube, curve=ql_handle, offsets_bp=list(SMALL_COLUMNS)
    )
    worst = assert_vol_spread_ordering(built, small_cube, tol=1e-6)
    assert worst < 1e-6


def test_transposed_volspreads_still_constructs_but_fails_the_check(
    small_cube: SwaptionCubeData, curves
):
    """MUTATION CHECK for the ordering contract - the most important test here.

    Building the matrix with swapTenors OUTER produces a matrix of exactly the
    same shape, so ``ql.InterpolatedSwaptionVolatilityCube`` constructs it without
    error. The cube then misprices by up to ~4.85 bp (worst node 1Mx30Y at
    +100bp: 77.09 vs 81.94). If ``assert_vol_spread_ordering`` passed on this, it
    would be decoration rather than a check.
    """
    ql_handle, _ = curves
    long_index, short_index, conv = swap_indices_for(
        currency=small_cube.currency, curve=ql_handle
    )
    atm_handle = ql.SwaptionVolatilityStructureHandle(
        build_ql_atm_matrix(small_cube, calendar=conv.ql_calendar())
    )
    good = vol_spreads_matrix(small_cube, offsets_bp=list(SMALL_COLUMNS))
    n_exp, n_ten = len(small_cube.expiries()), len(small_cube.tenors())
    transposed = [good[i * n_ten + j] for j in range(n_ten) for i in range(n_exp)]
    assert len(transposed) == len(good), "the wrong layout has the SAME number of rows"

    wrong = ql.InterpolatedSwaptionVolatilityCube(
        atm_handle,
        ql.PeriodVector([ql.Period(e) for e in small_cube.expiries()]),
        ql.PeriodVector([ql.Period(t) for t in small_cube.tenors()]),
        ql.DoubleVector([o / 1e4 for o in SMALL_COLUMNS]),
        ql.QuoteHandleVectorVector([ql.QuoteHandleVector(r) for r in transposed]),
        long_index,
        short_index,
        False,
    )
    wrong.enableExtrapolation()  # it constructed: QuantLib does not catch this

    with pytest.raises(VolCubeOrderingError) as excinfo:
        assert_vol_spread_ordering(
            wrong, small_cube, tol=1e-6, offsets_bp=list(SMALL_COLUMNS)
        )
    assert "bp" in str(excinfo.value)

    worst = assert_vol_spread_ordering(
        wrong, small_cube, tol=float("inf"), offsets_bp=list(SMALL_COLUMNS)
    )
    assert worst > 1.0, f"the transposition should be worth bp, not noise; got {worst:.3e}"


@pytest.mark.slow
def test_full_surface_ordering_round_trips(cube: SwaptionCubeData, curves):
    """The same contract over the full 7x5x7 = 245-node surface.

    Measured max abs error 1.4e-14 bp. Marked slow because every node costs
    QuantLib an atmStrike solve: ~37s for this one test.
    """
    ql_handle, _ = curves
    built = build_ql_swaption_cube(cube=cube, curve=ql_handle, offsets_bp=list(SPREAD_COLUMNS))
    assert assert_vol_spread_ordering(built, cube, tol=1e-6) < 1e-6


def test_zero_strike_spread_column_is_forced_in(small_cube: SwaptionCubeData, curves):
    """Without a zero column the cube's own ATM node misreads.

    Each smile section interpolates over the strikeSpreads grid, and if 0.0 is not
    a knot the ATM quote is not on the curve: measured 0.605 bp of error at 1Mx1Y.
    The builder therefore inserts it whether or not the caller asked.
    """
    ql_handle, _ = curves
    built = build_ql_swaption_cube(
        cube=small_cube, curve=ql_handle, offsets_bp=list(SMALL_OFFSETS)
    )
    assert 0.0 in [float(s) for s in built.strike_spreads]
    atm_from_cube = built.vol("1M", "2Y", None, offset_bp=0.0)
    assert atm_from_cube == pytest.approx(small_cube.atm_vol("1M", "2Y"), abs=1e-6)


# ------------------------------------------------------------------ #
#                          the rateslib cube                         #
# ------------------------------------------------------------------ #


def test_rateslib_cube_round_trips_every_node(cube: SwaptionCubeData, curves):
    """rateslib 2.1.1 has no IR vol cube, so this one is built from primitives.

    ``IRSabrCube`` and ``IRSplineCube`` do not exist in this version - the only
    rateslib vol classes are FX. The cube here is a tensor-product spline over
    (expiry, tenor) plus a spline over the offset axis, with forwards and
    annuities from rateslib and Bachelier from ``Query/Base/bachelier.py``.
    """
    _, rl_curve = curves
    built = build_rl_vol_cube(cube=cube, rl_curve=rl_curve, interpolation="spline")
    worst = 0.0
    for expiry in cube.expiries():
        for tenor in cube.tenors():
            for offset in cube.offsets():
                got = built.normal_vol(expiry, tenor, offset_bp=offset)
                worst = max(worst, abs(got - cube.vol(expiry, tenor, offset)))
    assert worst < 1e-8, f"worst node error {worst:.3e} bp"


def test_rateslib_cube_reports_the_interpolation_it_actually_used(cube: SwaptionCubeData, curves):
    """A spline that quietly degraded to linear is a different model.

    With too few nodes on an axis a spline cannot be fitted; the cube falls back
    and SAYS which axis fell back rather than presenting itself as a spline.
    """
    _, rl_curve = curves
    built = build_rl_vol_cube(cube=cube, rl_curve=rl_curve, interpolation="spline")
    used = getattr(built, "interpolation_used", None) or getattr(built, "_interpolation_used", None)
    assert used is not None, "the cube must expose which interpolation it used"
    assert set(used) >= {"expiry", "tenor", "offset"}


# ------------------------------------------------------------------ #
#                       coverage and refusals                        #
# ------------------------------------------------------------------ #


def test_currencies_without_an_rfr_branch_fail_loudly():
    """AUD DKK KRW NOK SEK have only the DEAD legacy vol branches in the catalog.

    Every legacy non-RFR branch (``ATM``, ``OTM``, ``REALIZED``, ``VOL_RATIO``)
    accounts for the harvest's VOL failures and returns no data, so a cube built
    from them would be empty. Whether Citi genuinely lacks RFR vol for those five
    or the walk simply never reached it is NOT known - which is exactly why this
    raises rather than guessing.
    """
    for currency in ("AUD", "DKK", "SEK"):
        with pytest.raises(UnknownTagError):
            cube_tags(currency=currency, expiries=("1Y",), tenors=("10Y",))


def test_vol_coverage_is_computed_from_the_committed_catalog():
    """Coverage is MEASURED from the harvest, not asserted from the currency list.

    Only USD was ever walked past the measure level: it is the one currency with a
    recorded expiry and strike-offset axis (17 x 12). CAD CHF EUR GBP JPY have
    _RFR branches but no recorded axes, and AUD DKK KRW NOK SEK have no _RFR
    branch at all. A non-USD skew cube is therefore SHAPE-INFERRED, and the
    coverage table is how a caller finds that out before trusting one.
    """
    coverage = vol_coverage()
    assert set(coverage.columns) == {"rfr_branches", "n_expiries", "n_offsets"}
    assert bool(coverage.loc["USD", "rfr_branches"])
    assert int(coverage.loc["USD", "n_expiries"]) > 0
    assert int(coverage.loc["USD", "n_offsets"]) > 0
    # The five currencies with no _RFR branch at all.
    dead = set(coverage.index[~coverage["rfr_branches"].astype(bool)])
    assert dead == {"AUD", "DKK", "KRW", "NOK", "SEK"}
    # Every other currency has the branch but no recorded axis - shape-inferred.
    inferred = coverage[(coverage["rfr_branches"].astype(bool)) & (coverage["n_expiries"] == 0)]
    assert set(inferred.index) == {"CAD", "CHF", "EUR", "GBP", "JPY"}


def test_krw_has_no_ois_curve_and_says_so(curves):
    """KRW is in the VOL currency list but has no Citi OIS curve to build against."""
    ql_handle, _ = curves
    quotes = _synthetic_quotes("KRW") if "KRW" in str(cube_tags) else None
    _ = quotes, ql_handle  # the refusal happens at tag build time
    with pytest.raises(UnknownTagError):
        cube_tags(currency="KRW", expiries=("1Y",), tenors=("10Y",))


# ------------------------------------------------------------------ #
#                        the fetch path                              #
# ------------------------------------------------------------------ #


def test_fetch_cube_batches_and_then_serves_from_cache(tmp_path: pathlib.Path):
    """One ``CVTSHIST`` call for the whole cube; the cached re-read costs none."""
    quotes = _synthetic_quotes()
    index = pd.bdate_range("2026-07-01", "2026-08-05")
    series = {
        tag: pd.Series(np.full(len(index), value), index=index) for tag, value in quotes.items()
    }
    app = FakeExcelApp(FakeVelocityData(series=series), pending_reads=1)
    client = CitiVelocityExcelClient(app=app, drain_seconds=0.0)
    cache = CitiVeloTagCache(base_dir=tmp_path)
    try:
        first = fetch_cube(
            client=client,
            currency=CURRENCY,
            as_of=AS_OF,
            expiries=EXPIRIES,
            tenors=TENORS,
            offsets_bp=OFFSETS,
            cache=cache,
        )
        calls_after_first = len(app.formulas_for("CVTSHIST"))
        second = fetch_cube(
            client=client,
            currency=CURRENCY,
            as_of=AS_OF,
            expiries=EXPIRIES,
            tenors=TENORS,
            offsets_bp=OFFSETS,
            cache=cache,
        )
    finally:
        client.close()

    # 7 expiries x 5 tenors x (1 ATM + 6 offsets) = 245 tags, chunked at the
    # client's proven 44-per-call ceiling -> 6 calls, not 245.
    n_tags = len(EXPIRIES) * len(TENORS) * (1 + len(OFFSETS))
    expected_calls = -(-n_tags // 44)
    assert calls_after_first == expected_calls, (
        f"{n_tags} tags should batch into {expected_calls} CVTSHIST call(s), "
        f"got {calls_after_first}"
    )
    assert second.atm_vol("1Y", "10Y") == pytest.approx(first.atm_vol("1Y", "10Y"))

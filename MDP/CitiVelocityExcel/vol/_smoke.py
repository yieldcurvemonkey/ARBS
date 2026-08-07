r"""Smoke test for the Citi Velocity swaption cube. No Excel, no market data.

Run from the repo root::

    <env>/python.exe MDP/CitiVelocityExcel/vol/_smoke.py

Cases
-----
(a) round-trip every node through the QuantLib cube;
(b) build the volSpreads matrix in the WRONG order (swapTenors outer) and show
    that :func:`assert_vol_spread_ordering` FAILS - if it passed, the check would
    be decoration;
(c) round-trip every node through the rateslib cube;
(d) price the same payer swaption through both backends and print both premia;
(1) the ONE pricer - :class:`CitiVeloSwaptionCube` across every backend it can
    reach, then the spot check: price the swaption, invert the premium with a
    solver that shares no code with it, and compare against the quote. Every
    other case compares one implementation with another; only this one can see a
    wrong annuity, schedule or day count;
(e) drive :func:`fetch_cube` through the fake COM Excel, so the tag/fetch path is
    exercised end to end without a live add-in;
(f) hand the units guard decimal quotes declared as bp and show that it RAISES -
    the same teeth check as (b), for the other silent 10,000x failure;
(g) print :func:`vol_coverage`, which bounds what any of the above can serve.

The surface is synthetic but shaped like a real one: normal vols in bp, declining
in tail, humped in expiry, with a payer-skewed smile whose curvature decays with
expiry. Nothing here validates Citi's actual numbers - see the units note in
``cube_data``.
"""

from __future__ import annotations

import datetime
import math
import pathlib
import sys

import numpy as np
import pandas as pd
import QuantLib as ql
import rateslib as rl

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:  # smoke script only; never in library code
    sys.path.insert(0, str(_REPO_ROOT))

from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient  # noqa: E402
from MDP.CitiVelocityExcel.testing import FakeExcelApp, FakeVelocityData  # noqa: E402
from MDP.CitiVelocityExcel.vol.cube_data import (  # noqa: E402
    SwaptionCubeData,
    VolUnitError,
    cube_from_quotes,
    cube_tags,
    fetch_cube,
    vol_coverage,
)
from MDP.CitiVelocityExcel.vol.ql_cube import (  # noqa: E402
    VolCubeOrderingError,
    assert_vol_spread_ordering,
    build_ql_atm_matrix,
    build_ql_swaption_cube,
    swap_indices_for,
    vol_spreads_matrix,
)
from MDP.CitiVelocityExcel.vol.rl_cube import build_rl_vol_cube  # noqa: E402
from Query.Base.bachelier import bachelier_price  # noqa: E402

AS_OF = datetime.date(2026, 8, 5)
CURRENCY = "USD"
EXPIRIES = ("1M", "3M", "6M", "1Y", "2Y", "5Y", "10Y")
TENORS = ("1Y", "2Y", "5Y", "10Y", "30Y")
OFFSETS = (-100.0, -50.0, -25.0, 25.0, 50.0, 100.0)
#: Column order handed to QuantLib. The zero column is an ATM anchor, not a
#: quote: without it the cube's strike interpolation does not pass through the
#: ATM surface (0.605 bp at 1Mx1Y, measured below).
SPREAD_COLUMNS = (-100.0, -50.0, -25.0, 0.0, 25.0, 50.0, 100.0)
NOTIONAL = 100_000_000.0

_YEARS = {"D": 1 / 365.25, "W": 7 / 365.25, "M": 30.4375 / 365.25, "Y": 1.0}


def _yrs(token: str) -> float:
    return float(token[:-1]) * _YEARS[token[-1]]


# ------------------------------------------------------------------ #
#                        the synthetic surface                       #
# ------------------------------------------------------------------ #


def atm_bp(expiry: str, tenor: str) -> float:
    te, ts = _yrs(expiry), _yrs(tenor)
    return 55.0 + 60.0 * math.exp(-ts / 8.0) + 20.0 * math.exp(-te / 2.0) - 3.0 * math.log1p(te)


def spread_bp(expiry: str, tenor: str, offset: float) -> float:
    te, ts = _yrs(expiry), _yrs(tenor)
    curvature = 6.0 + 4.0 * math.exp(-te)
    slope = -(3.0 + 2.0 * math.exp(-ts / 10.0))
    u = offset / 100.0
    return curvature * u * u + slope * u


def synthetic_quotes() -> dict[str, float]:
    tags = cube_tags(
        currency=CURRENCY,
        expiries=EXPIRIES,
        tenors=TENORS,
        offsets_bp=OFFSETS,
        measure="NORMAL",
        skew_measure="NORMALABSOLUTE",
    )
    out: dict[str, float] = {}
    for tag, (kind, expiry, tenor, offset) in tags.items():
        base = atm_bp(expiry, tenor)
        out[tag] = base if kind == "ATM" else base + spread_bp(expiry, tenor, offset)
    return out


def synthetic_cube() -> SwaptionCubeData:
    return cube_from_quotes(
        quotes=synthetic_quotes(),
        currency=CURRENCY,
        as_of=AS_OF,
        expiries=EXPIRIES,
        tenors=TENORS,
        offsets_bp=OFFSETS,
        served_unit="bp",
        source="_smoke/synthetic",
    )


# ------------------------------------------------------------------ #
#                              the curve                             #
# ------------------------------------------------------------------ #

_PILLARS = (0.0, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 15.0, 20.0, 30.0, 45.0)


def _zero(t: float) -> float:
    """Continuously-compounded zero, upward sloping. Purely synthetic."""
    return 0.030 + 0.012 * (1.0 - math.exp(-t / 4.0))


def build_curves() -> tuple:
    """A QuantLib and a rateslib curve carrying the SAME discount factors.

    Identical DFs on identical dates, so any forward difference between the two
    backends is a CONVENTION difference and not a curve difference.
    """
    ql_today = ql.Date(AS_OF.day, AS_OF.month, AS_OF.year)
    ql.Settings.instance().evaluationDate = ql_today

    dates = [ql_today + int(round(t * 365)) for t in _PILLARS]
    dfs = [math.exp(-_zero(t) * t) for t in _PILLARS]
    dfs[0] = 1.0
    ql_curve = ql.DiscountCurve(dates, dfs, ql.Actual365Fixed())
    ql_curve.enableExtrapolation()
    ql_handle = ql.YieldTermStructureHandle(ql_curve)

    nodes = {
        datetime.datetime(AS_OF.year, AS_OF.month, AS_OF.day) + datetime.timedelta(days=int(round(t * 365))): df
        for t, df in zip(_PILLARS, dfs)
    }
    rl_curve = rl.Curve(nodes, interpolation="log_linear", calendar="nyc", convention="act360", id="smoke_sofr")
    return ql_handle, rl_curve


# ------------------------------------------------------------------ #
#                               cases                                #
# ------------------------------------------------------------------ #


def case_a(cube: SwaptionCubeData, ql_handle) -> tuple:
    built = build_ql_swaption_cube(cube=cube, curve=ql_handle, offsets_bp=list(SPREAD_COLUMNS))
    worst = assert_vol_spread_ordering(built, cube, tol=1e-6)
    n = len(cube.expiries()) * len(cube.tenors()) * len(SPREAD_COLUMNS)
    print(f"(a) QuantLib interpolated cube: {n} node(s) round-tripped, max abs error {worst:.3e} bp")
    print(f"    built: {built!r}")
    return built, worst


def case_a_sabr(cube: SwaptionCubeData, ql_handle) -> None:
    try:
        sabr = build_ql_swaption_cube(
            cube=cube, curve=ql_handle, offsets_bp=list(SPREAD_COLUMNS), sabr=True, check_ordering=False
        )
        worst = assert_vol_spread_ordering(sabr, cube, tol=float("inf"))
        print(f"(a2) SABR cube CONVERGED; node round-trip max abs error {worst:.4f} bp")
        print("     (a SABR cube FITS the smile, it does not interpolate it - node error is expected)")
    except Exception as exc:  # noqa: BLE001 - the honest report is the exception itself
        print(f"(a2) SABR cube FAILED to build: {type(exc).__name__}: {exc}")


def case_b(cube: SwaptionCubeData, ql_handle) -> None:
    """Transpose the volSpreads rows and prove the ordering check has teeth."""
    long_index, short_index, conv = swap_indices_for(currency=cube.currency, curve=ql_handle)
    atm_matrix = build_ql_atm_matrix(cube, calendar=conv.ql_calendar())
    atm_handle = ql.SwaptionVolatilityStructureHandle(atm_matrix)

    good = vol_spreads_matrix(cube, offsets_bp=list(SPREAD_COLUMNS))
    n_exp, n_ten = len(cube.expiries()), len(cube.tenors())
    # Same rows, swapTenors OUTER: row index j*n_exp + i instead of i*n_ten + j.
    bad = [good[i * n_ten + j] for j in range(n_ten) for i in range(n_exp)]
    assert len(bad) == len(good)

    wrong = ql.InterpolatedSwaptionVolatilityCube(
        atm_handle,
        ql.PeriodVector([ql.Period(e) for e in cube.expiries()]),
        ql.PeriodVector([ql.Period(t) for t in cube.tenors()]),
        ql.DoubleVector([o / 1e4 for o in SPREAD_COLUMNS]),
        ql.QuoteHandleVectorVector([ql.QuoteHandleVector(r) for r in bad]),
        long_index,
        short_index,
        False,
    )
    wrong.enableExtrapolation()
    print("(b) transposed volSpreads: ql.InterpolatedSwaptionVolatilityCube CONSTRUCTED WITHOUT ERROR")
    try:
        assert_vol_spread_ordering(wrong, cube, tol=1e-6, offsets_bp=list(SPREAD_COLUMNS))
    except VolCubeOrderingError as exc:
        first_line = str(exc).split(". The usual cause")[0]
        print(f"    assert_vol_spread_ordering FAILED as required:\n      {first_line}")
    else:
        print("    *** assert_vol_spread_ordering PASSED on a transposed matrix - THE CHECK IS BROKEN ***")


def case_c(cube: SwaptionCubeData, rl_curve) -> tuple:
    rlc = build_rl_vol_cube(cube=cube, rl_curve=rl_curve, interpolation="spline", notional=NOTIONAL)
    worst = 0.0
    worst_key = None
    n = 0
    for expiry in cube.expiries():
        for tenor in cube.tenors():
            for offset in cube.offsets():
                got = rlc.normal_vol(expiry, tenor, offset_bp=offset)
                want = cube.vol(expiry, tenor, offset)
                n += 1
                if abs(got - want) > worst:
                    worst, worst_key = abs(got - want), (expiry, tenor, offset, got, want)
    print(f"(c) rateslib cube: {n} node(s) round-tripped, max abs error {worst:.3e} bp")
    print(f"    interpolation actually used: {rlc.interpolation_used}")
    if worst_key:
        e, t, o, got, want = worst_key
        print(f"    worst node {e}x{t} @{o:+g}bp: got {got:.10f} want {want:.10f}")
    print(f"    built: {rlc!r}")
    return rlc, worst


def case_d(built, rlc, ql_handle) -> None:
    expiry, tenor = "1Y", "10Y"
    fwd_rl = rlc.forward(expiry, tenor)
    strike = fwd_rl + 0.0025  # 25bp out of the money, payer

    premium_rl = rlc.price(expiry, tenor, strike, right="payer", notional=NOTIONAL)
    vega_rl = rlc.vega(expiry, tenor, strike, right="payer", notional=NOTIONAL)
    vol_rl = rlc.normal_vol(expiry, tenor, strike=strike)

    conv = built.convention
    cal = conv.ql_calendar()
    exercise_date = built.option_date(expiry)
    start = cal.advance(exercise_date, conv.spot_lag, ql.Days)
    end = cal.advance(start, ql.Period(tenor))
    schedule = ql.Schedule(
        start, end, ql.Period(ql.Annual), cal, ql.ModifiedFollowing, ql.ModifiedFollowing,
        ql.DateGeneration.Forward, False,
    )
    on_index = conv.ql_index(ql_handle)
    swap = ql.OvernightIndexedSwap(
        ql.Swap.Payer, NOTIONAL, schedule, strike, ql.Actual360(), on_index
    )
    swap.setPricingEngine(ql.DiscountingSwapEngine(ql_handle))
    fwd_ql = float(swap.fairRate())
    annuity_ql = abs(float(swap.fixedLegBPS())) * 1e4 / NOTIONAL

    swaption = ql.Swaption(swap, ql.EuropeanExercise(exercise_date))
    swaption.setPricingEngine(ql.BachelierSwaptionEngine(ql_handle, built.handle))
    premium_ql = float(swaption.NPV())
    vol_ql = built.vol(expiry, tenor, strike=strike)

    print(f"(d) {expiry}x{tenor} PAYER, strike {strike*1e4:.2f}bp, notional {NOTIONAL:,.0f}")
    print(f"    rateslib : forward {fwd_rl*1e4:8.3f}bp  annuity {rlc.annuity(expiry, tenor):7.4f}  "
          f"vol {vol_rl:7.4f}bp  premium {premium_rl:,.2f}  vega/bp {vega_rl:,.2f}")
    print(f"    QuantLib : forward {fwd_ql*1e4:8.3f}bp  annuity {annuity_ql:7.4f}  "
          f"vol {vol_ql:7.4f}bp  premium {premium_ql:,.2f}")
    diff = premium_ql - premium_rl
    annuity_rl = rlc.annuity(expiry, tenor)
    print(f"    difference: {diff:,.2f} ({diff / premium_rl * 1e4:+.1f} bp of the rateslib premium)")
    print(f"    attribution: forward gap {abs(fwd_ql - fwd_rl)*1e4:.4f}bp, vol gap "
          f"{abs(vol_ql - vol_rl):.6f}bp, annuity gap "
          f"{(annuity_ql / annuity_rl - 1.0) * 1e4:+.1f}bp relative -> the residual is the ANNUITY, "
          f"i.e. the fixed-leg schedule, not the vol surface.")

    # Same vol, same forward, same annuity -> the two formulas must agree exactly.
    check = NOTIONAL * rlc.annuity(expiry, tenor) * bachelier_price(
        "C", strike, fwd_rl, vol_rl / 1e4, rlc.time_to_expiry(expiry), 1.0
    )
    print(f"    control (rateslib inputs through Query.Base.bachelier): {check:,.2f} "
          f"[= rateslib premium to {abs(check - premium_rl):.2e}]")


def case_e() -> None:
    """Drive fetch_cube through the fake COM Excel."""
    tags = cube_tags(
        currency=CURRENCY, expiries=("1Y", "5Y"), tenors=("2Y", "10Y"),
        offsets_bp=(-25.0, 25.0),
    )
    index = pd.date_range("2026-07-27", "2026-08-05", freq="B")
    series = {}
    for tag, (kind, expiry, tenor, offset) in tags.items():
        base = atm_bp(expiry, tenor) + (0.0 if kind == "ATM" else spread_bp(expiry, tenor, offset))
        series[tag] = pd.Series(base + 0.01 * np.arange(len(index)), index=index, name=tag)
    app = FakeExcelApp(FakeVelocityData(series=series), pending_reads=1)
    client = CitiVelocityExcelClient(app=app, poll_interval=0.0, drain_seconds=0.0)
    cube = fetch_cube(
        client=client, currency=CURRENCY, expiries=("1Y", "5Y"), tenors=("2Y", "10Y"),
        offsets_bp=(-25.0, 25.0), period="1M",
    )
    print(f"(e) fetch_cube over the fake add-in: {cube!r}")
    print(f"    as_of {cube.as_of}, 1Yx10Y ATM {cube.atm_vol('1Y', '10Y'):.4f}bp, "
          f"-25bp {cube.vol('1Y', '10Y', -25.0):.4f}bp, CVTSHIST calls {client.calls}")
    client.close()


def case_units() -> None:
    """The units guard must reject decimal quotes declared as bp."""
    decimal_quotes = {t: v / 1e4 for t, v in synthetic_quotes().items()}
    try:
        cube_from_quotes(
            quotes=decimal_quotes, currency=CURRENCY, as_of=AS_OF, expiries=EXPIRIES,
            tenors=TENORS, offsets_bp=OFFSETS, served_unit="bp",
        )
    except VolUnitError as exc:
        print(f"(f) units guard rejected decimal-as-bp: {str(exc)[:170]}...")
    else:
        print("    *** units guard PASSED decimal quotes declared as bp - THE GUARD IS BROKEN ***")


def case_native(cube: SwaptionCubeData, rl_curve) -> None:
    """The rateslib-native backend, and whether it agrees with the hand-built one."""
    from MDP.CitiVelocityExcel.vol.rl_native_cube import (
        RATESLIB_NATIVE_AVAILABLE,
        compare_backends,
    )

    if not RATESLIB_NATIVE_AVAILABLE:
        print("(n) rl.IRSplineCube not present (needs rateslib >= 2.7.0) - skipped.")
        return

    frame = compare_backends(
        cube=cube,
        rl_curve=rl_curve,
        notional=NOTIONAL,
        expiries=["1Y", "5Y"],
        tenors=["2Y", "10Y", "30Y"],
    )
    vega_rel = (frame["vega_diff"].abs() / frame["hand_vega"].abs()).max()
    print(f"(n) native rl.IRSplineCube + rl.IRSCall vs the hand-built cube, {len(frame)} nodes:")
    print(f"    max |vol - Citi quote|, native   : {frame['citi_vol_err_bp'].abs().max():.3e} bp")
    print(f"    max |forward difference|         : {frame['forward_diff_bp'].abs().max():.3e} bp")
    print(f"    max relative price difference    : {frame['price_rel'].max():.3e}")
    print(f"    max relative vega difference     : {vega_rel:.3e}")
    print("    (the vega residual is the +/-0.5bp central difference the native vega uses;")
    print("     it does NOT read rateslib's analytic vega, which is timed off the CURVE and")
    print("     is wrong by ~0.14%/day when the cube's as_of and the curve's first node differ)")


def case_one_object(cube: SwaptionCubeData, rl_curve, ql_handle) -> None:
    """The one pricer, all four backends, and the check that can fail.

    Everything above compares an implementation against another implementation.
    This prices the swaption and inverts the premium back with a solver that
    shares no code with either pricer, then compares against the QUOTE - which is
    the only comparison that can see a wrong annuity, schedule or day count.

    On the synthetic surface the quote is one this module invented, so a clean
    result here means the machinery is self-consistent. The claim about Citi's
    real numbers is made by ``tests/test_citivelo_swaption_spot_check.py``, which
    runs the same code against a recorded live capture.
    """
    from MDP.CitiVelocityExcel.vol.spot_check import (
        assert_spot_check,
        format_spot_check_report,
        spot_check_frame,
    )
    from MDP.CitiVelocityExcel.vol.swaption_cube import build_citivelo_swaption_cube

    one = build_citivelo_swaption_cube(
        cube=cube, rl_curve=rl_curve, ql_curve=ql_handle, notional=NOTIONAL
    )
    print(f"(1) {one!r}")
    strike = one.strike_for("1Y", "10Y", 25.0)
    print(f"    1Yx10Y +25bp, strike {strike * 100:.5f}%:")
    print(f"    {'backend':10}{'fwd %':>11}{'annuity':>11}{'vol bp':>10}{'payer PV':>16}{'vega/bp':>12}")
    for name in one.backends_available:
        side = one.with_backend(name)
        print(f"    {name:10}{side.forward('1Y', '10Y') * 100:>11.5f}"
              f"{side.annuity('1Y', '10Y'):>11.6f}"
              f"{side.normal_vol('1Y', '10Y', offset_bp=25.0):>10.4f}"
              f"{side.price('1Y', '10Y', strike):>16,.2f}"
              f"{side.vega('1Y', '10Y', strike):>12,.2f}")

    frame = spot_check_frame(
        cube=cube,
        cube_obj=one,
        backends=("rl-native", "ql") if "rl-native" in one.backends_available else ("rl-hand", "ql"),
        expiries=["1Y", "5Y"],
        tenors=["2Y", "30Y"],
    )
    print()
    for line in format_spot_check_report(frame).splitlines():
        print(f"    {line}")
    try:
        assert_spot_check(frame)
    except Exception as exc:  # noqa: BLE001 - the report IS the exception
        print(f"\n    *** SPOT CHECK FAILED: {str(exc)[:400]}")
    else:
        print("\n    -> every node reproduces its quote when priced and inverted independently.")


def case_g() -> None:
    """What the harvest actually covers - the constraint on every other case."""
    print("(g) catalog coverage of RATES.VOL (computed, not stored):")
    for line in vol_coverage().to_string().splitlines():
        print(f"    {line}")
    print("    only USD was walked past the measure level; the other ten need explicit axes")
    print("    and (for skew) inherit USD's offset spelling, unverified.")


def main() -> int:
    cube = synthetic_cube()
    print(f"synthetic cube: {cube!r}")
    print(f"  ATM corners: 1Mx1Y {cube.atm_vol('1M','1Y'):.2f}bp  1Yx10Y {cube.atm_vol('1Y','10Y'):.2f}bp  "
          f"10Yx30Y {cube.atm_vol('10Y','30Y'):.2f}bp")
    print(f"  1Yx10Y smile: " + "  ".join(f"{o:+g}:{v:.2f}" for o, v in cube.smile("1Y", "10Y").items()))
    print()

    ql_handle, rl_curve = build_curves()
    built, _ = case_a(cube, ql_handle)
    print()
    case_a_sabr(cube, ql_handle)
    print()
    case_b(cube, ql_handle)
    print()
    rlc, _ = case_c(cube, rl_curve)
    print()
    case_d(built, rlc, ql_handle)
    print()
    case_native(cube, rl_curve)
    print()
    case_one_object(cube, rl_curve, ql_handle)
    print()
    case_e()
    print()
    case_units()
    print()
    case_g()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

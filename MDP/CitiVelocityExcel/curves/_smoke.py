"""Self-contained smoke test for the Citi Velocity curve builders.

Run it::

    <env>/python.exe -m MDP.CitiVelocityExcel.curves._smoke

There is no live Excel and no market data here, so the test is built the only
honest way available: a **self-consistent synthetic par grid**. A smooth
analytic discount curve is chosen, the 44 Velocity par swaps are priced off it
with each currency's own conventions, and those par rates are fed back to the
builders. A correct builder must return a curve that reprices its own inputs.

What that does and does not prove
---------------------------------
It proves the two backends implement the *same* instrument and that each solves
it: it catches a wrong day count, a wrong payment lag, a wrong frequency, a
wrong end-of-month rule, a misplaced pillar, an unconverged solve. It does
**not** prove the conventions match the market - for the six ``market_standard``
currencies (DKK ILS MXN SGD THB ZAR) nothing here could, and MXN's 28-day Fondeo
roll is knowingly approximated by a monthly schedule.

Every check that could pass vacuously is paired with a mutation that must make
it fail; a checker that cannot fail is not a check.
"""

from __future__ import annotations

import datetime
import logging
import math
import pathlib
import sys
import tempfile
import time
from typing import Dict, List, Tuple

import pandas as pd
import QuantLib as ql
import rateslib as rl

from MDP.CitiVelocityExcel.cache import CitiVeloTagCache
from MDP.CitiVelocityExcel.catalog import CitiVeloCatalog
from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient
from MDP.CitiVelocityExcel.curves.conventions import conventions_for, supported_indices
from MDP.CitiVelocityExcel.curves.par_grid import (
    fetch_par_grid,
    par_grid_snapshot,
    tenor_columns_from_tags,
)
from MDP.CitiVelocityExcel.curves.ql_builder import (
    build_ql_ois_curve,
    ql_forward_rate,
    ql_par_reprice_errors_bp,
)
from MDP.CitiVelocityExcel.curves.rl_builder import (
    _as_ref_date,
    _make_irs,
    _prev_business_day,
    build_rl_ois_curve,
    build_rl_ois_curve_from_quotes,
    end_of_month_for,
    forward_rate,
    par_reprice_errors_bp,
    payment_lag_for,
)
from MDP.CitiVelocityExcel.testing import FakeExcelApp, FakeVelocityData

#: The Velocity OIS tenor axis, straight from the harvested catalog (44 tokens).
TENORS: List[str] = CitiVeloCatalog.default().tenors("RATES.OIS.USD_SOFR.PAR")

#: A Wednesday, so nothing is masked by an accidental weekend roll.
REF_DATE = datetime.date(2026, 8, 5)

#: The five the task names, in build order. ILS is the interesting one: a
#: Sunday-Thursday week and a calendar synthesised from QuantLib.
REQUIRED = ["USD_SOFR", "EUR_EUROSTR", "GBP_SONIA", "CAD_CORRA", "ILS_SHIR"]

#: Forward swaps used for the cross-backend comparison. Deliberately off the
#: calibration grid at the start date, so they exercise interpolation rather
#: than just re-reading a pillar.
FORWARDS = [("1Y", "1Y"), ("2Y", "3Y"), ("5Y", "5Y"), ("10Y", "10Y"), ("20Y", "10Y")]

#: Reprice tolerance the task sets. The default solver tolerances land ~5x
#: inside it; see the tightened-tolerance run in the report for why the residual
#: is solver noise and not a convention difference.
REPRICE_TOL_BP = 0.01

_failures: List[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' - ' + detail) if detail else ''}")
    if not ok:
        _failures.append(f"{name}: {detail}")
    return ok


# ------------------------------------------------------------------ #
#                        the synthetic par grid                      #
# ------------------------------------------------------------------ #


def _zero(t: float) -> float:
    """A smooth Nelson-Siegel-shaped continuously-compounded zero curve."""
    if t <= 0:
        return 0.042
    tau = 3.0
    a = (1.0 - math.exp(-t / tau)) / (t / tau)
    return 0.030 + 0.015 * a + 0.010 * (a - math.exp(-t / tau))


def synthetic_grid(citi_index: str) -> Tuple[Dict[str, float], rl.Curve, datetime.datetime]:
    """Price the 44 par swaps off a known discount curve, in this ccy's conventions.

    Returns the par grid (percent), the truth curve, and the rolled ref date.
    """
    conv = conventions_for(citi_index)
    cal = conv.rl_calendar_object()
    ref = _prev_business_day(_as_ref_date(REF_DATE), cal)
    spot = cal.add_bus_days(ref, int(conv.spot_lag), True)

    nodes = {ref: 1.0}
    for m in range(1, 12 * 55 + 1):
        d = rl.add_tenor(ref, f"{m}M", "f", cal)
        t = (d - ref).days / 365.0
        nodes[d] = math.exp(-_zero(t) * t)
    truth = rl.Curve(
        nodes=nodes,
        id="TRUTH",
        convention=conv.convention,
        calendar=cal,
        modifier="mf",
        interpolation="log_linear",
    )

    par = {
        tenor: float(
            _make_irs(
                conv=conv,
                calendar=cal,
                effective=spot,
                tenor=tenor,
                curve_id="TRUTH",
                fixed_rate=0.0,
            ).rate(curves=truth)
        )
        for tenor in TENORS
    }
    return par, truth, ref


# ------------------------------------------------------------------ #
#                              the checks                            #
# ------------------------------------------------------------------ #


def pillar_mismatches(rlc, qlc) -> List[Tuple[str, datetime.date, datetime.date]]:
    """Tenors whose rateslib maturity and QuantLib pillar fall on different days.

    They differ only when the two libraries' holiday calendars for that currency
    differ, which they do: rateslib ships its own 14 calendars and QuantLib its
    own national ones, and nothing reconciles them. This is data, not a bug in
    either builder, but it is the whole explanation for any cross-backend gap
    bigger than the solver residual, so it is measured rather than assumed.
    """
    # The helpers are RelativeDateRateHelpers: their pillar dates are recomputed
    # off the GLOBAL evaluation date, so they must be read with it pinned. Read
    # without pinning, this function reported 44 mismatches per curve for every
    # currency - which is how the first version of this smoke test discovered
    # the very hazard the ql_builder freezes its curve against.
    with qlc.pinned():
        ql_pillars = [h.pillarDate() for h in qlc.helpers]
    ql_days = {(d.year(), d.month(), d.dayOfMonth()) for d in ql_pillars}
    out = []
    for tenor, mat in rlc.meta["maturities"].items():
        key = (mat.year, mat.month, mat.day)
        if key not in ql_days:
            nearest = min(
                ql_pillars,
                key=lambda d: abs((datetime.date(d.year(), d.month(), d.dayOfMonth()) - mat.date()).days),
            )
            out.append(
                (tenor, mat.date(), datetime.date(nearest.year(), nearest.month(), nearest.dayOfMonth()))
            )
    return out


def check_calendar_divergence() -> None:
    """Diff every rateslib calendar against the QuantLib index calendar behind it.

    Reported, never asserted: these are two independent holiday datasets and
    neither is this package's to correct. It is here because it is the only
    explanation for any cross-backend gap larger than the solver residual, and
    an unexplained residual is how a convention bug hides.
    """
    print("\n== rateslib vs QuantLib holiday calendars, 2026-2076 ==")
    start, end = datetime.date(2026, 1, 1), datetime.date(2076, 12, 31)
    handle = ql.YieldTermStructureHandle()
    print(f"  {'index':16s} {'rl cal':7s} {'|rl|':>6s} {'|ql|':>6s} {'only_rl':>8s} {'only_ql':>8s}")
    for token in supported_indices():
        conv = conventions_for(token)
        if not conv.rl_calendar:
            continue  # the calendar IS QuantLib's; there is nothing to diff
        rl_cal = rl.get_calendar(conv.rl_calendar)
        rl_days = set()
        day = start
        while day <= end:
            if day.weekday() < 5 and not rl_cal.is_bus_day(
                datetime.datetime(day.year, day.month, day.day)
            ):
                rl_days.add(day)
            day += datetime.timedelta(days=1)
        ql_cal = conv.ql_index(handle).fixingCalendar()
        ql_days = {
            datetime.date(d.year(), d.month(), d.dayOfMonth())
            for d in ql.Calendar.holidayList(
                ql_cal, ql.Date(start.day, start.month, start.year),
                ql.Date(end.day, end.month, end.year), False
            )
        }
        print(
            f"  {token:16s} {conv.rl_calendar:7s} {len(rl_days):6d} {len(ql_days):6d} "
            f"{len(rl_days - ql_days):8d} {len(ql_days - rl_days):8d}"
        )


def check_convention_tables() -> None:
    print("\n== convention tables (payment lag / end-of-month vs rateslib specs) ==")
    bad = []
    for token in supported_indices():
        try:
            payment_lag_for(token)
            end_of_month_for(token)
        except Exception as exc:  # noqa: BLE001 - the point is to report which one
            bad.append(f"{token}: {exc}")
    check(
        f"all {len(supported_indices())} indices agree with rl.defaults.spec",
        not bad,
        "; ".join(bad),
    )


def check_evaluation_date_hygiene(par: Dict[str, float]) -> None:
    print("\n== QuantLib evaluation-date hygiene ==")
    original = ql.Settings.instance().evaluationDate
    sentinel = ql.Date(15, 3, 2001)
    ql.Settings.instance().evaluationDate = sentinel
    qlc = build_ql_ois_curve(par_rates=par, ref_date=REF_DATE, citi_index="USD_SOFR")
    restored = ql.Settings.instance().evaluationDate
    check("global evaluationDate restored by the builder", restored == sentinel, str(restored))

    probe = ql.Date(7, 8, 2036)
    before = qlc.curve.discount(probe)
    ql.Settings.instance().evaluationDate = ql.Date(5, 2, 2027)
    after = qlc.curve.discount(probe)
    ql.Settings.instance().evaluationDate = sentinel
    check(
        "returned curve is immune to an evaluation-date move",
        abs(after - before) < 1e-15,
        f"10Y DF moved {after - before:+.3e}",
    )
    # Teeth: a live Piecewise curve over the same helpers DOES move, so the
    # check above is measuring something real.
    with_ref = ql.Date(5, 8, 2026)
    ql.Settings.instance().evaluationDate = with_ref
    live = ql.PiecewiseLogLinearDiscount(with_ref, list(qlc.helpers), ql.Actual360())
    live.enableExtrapolation()
    live_before = live.discount(probe)
    ql.Settings.instance().evaluationDate = ql.Date(5, 2, 2027)
    live_after = live.discount(probe)
    ql.Settings.instance().evaluationDate = sentinel
    check(
        "mutation: an unfrozen Piecewise curve DOES move (so the test has teeth)",
        abs(live_after - live_before) > 1e-6,
        f"10Y DF moved {live_after - live_before:+.3e}",
    )
    ql.Settings.instance().evaluationDate = original


def check_currency(citi_index: str, verbose: bool = True) -> Dict[str, float]:
    par, truth, ref = synthetic_grid(citi_index)
    conv = conventions_for(citi_index)

    rlc = build_rl_ois_curve(par_rates=par, ref_date=REF_DATE, citi_index=citi_index)
    qlc = build_ql_ois_curve(par_rates=par, ref_date=REF_DATE, citi_index=citi_index)

    rl_err = float(par_reprice_errors_bp(rlc).abs().max())
    ql_err = float(ql_par_reprice_errors_bp(qlc, par).abs().max())

    # Same grid, tighter solve: if the residual below is solver tolerance the
    # cross-backend gap must collapse with it. If it does not, it is a
    # convention difference and this is where it shows up.
    rlc_tight = build_rl_ois_curve(
        par_rates=par, ref_date=REF_DATE, citi_index=citi_index, func_tol=1e-14, conv_tol=1e-16
    )
    fwd_gap = 0.0
    fwd_gap_tight = 0.0
    for fwd, ten in FORWARDS:
        q = ql_forward_rate(qlc, forward=fwd, tenor=ten)
        fwd_gap = max(fwd_gap, abs(forward_rate(rlc, forward=fwd, tenor=ten) - q) * 100.0)
        fwd_gap_tight = max(
            fwd_gap_tight, abs(forward_rate(rlc_tight, forward=fwd, tenor=ten) - q) * 100.0
        )

    # How far the 44-node rebuild sits from the 660-node curve it was priced off.
    # Reported, not asserted: it is an interpolation property of the grid, not a
    # property of the builder.
    node_gap = 0.0
    for tenor, mat in rlc.meta["maturities"].items():
        node_gap = max(node_gap, abs(float(rlc.rl_pricing_curve[mat]) - float(truth[mat])))

    mismatches = pillar_mismatches(rlc, qlc)

    if verbose:
        print(
            f"  {citi_index:15s} freq={conv.fixed_frequency} {conv.convention} "
            f"T+{conv.spot_lag} pay+{payment_lag_for(citi_index)} "
            f"eom={end_of_month_for(citi_index)} {'APPROX' if conv.approximate else 'spec  '}"
        )
        print(
            f"      rl reprice max {rl_err:.2e} bp | ql reprice max {ql_err:.2e} bp | "
            f"fwd gap {fwd_gap:.5f} bp (tight solve {fwd_gap_tight:.5f} bp) | "
            f"node vs truth {node_gap:.2e} DF | pillar mismatches {len(mismatches)}"
        )
    check(f"{citi_index} rateslib reprices < {REPRICE_TOL_BP} bp", rl_err < REPRICE_TOL_BP, f"{rl_err:.3e}")
    check(f"{citi_index} QuantLib reprices < {REPRICE_TOL_BP} bp", ql_err < REPRICE_TOL_BP, f"{ql_err:.3e}")
    check(
        f"{citi_index} rateslib and QuantLib calendars put the pillars on the same days",
        not mismatches,
        f"{len(mismatches)}: {mismatches[:3]}",
    )
    check(f"{citi_index} backends agree < {REPRICE_TOL_BP} bp on forwards", fwd_gap < REPRICE_TOL_BP, f"{fwd_gap:.5f}")
    check(f"{citi_index} agreement collapses with the solver tolerance", fwd_gap_tight < 1e-3, f"{fwd_gap_tight:.6f}")
    return par


def check_mutations(par: Dict[str, float]) -> None:
    print("\n== mutation checks (do the repricers actually measure anything?) ==")
    qlc = build_ql_ois_curve(par_rates=par, ref_date=REF_DATE, citi_index="USD_SOFR")
    bumped = {t: v + 0.01 for t, v in par.items()}  # +1 bp on every tenor
    err = ql_par_reprice_errors_bp(qlc, bumped).abs()
    check(
        "ql_par_reprice_errors_bp reports ~1 bp against a 1 bp-bumped grid",
        abs(float(err.min()) - 1.0) < 0.05 and abs(float(err.max()) - 1.0) < 0.05,
        f"min {float(err.min()):.4f} max {float(err.max()):.4f} bp",
    )

    shifted = dict(par)
    shifted["10Y"] = par["10Y"] + 0.05  # +5 bp on the 10Y only
    rlc = build_rl_ois_curve(par_rates=par, ref_date=REF_DATE, citi_index="USD_SOFR")
    rlc_shift = build_rl_ois_curve(par_rates=shifted, ref_date=REF_DATE, citi_index="USD_SOFR")
    moved = (
        forward_rate(rlc_shift, forward="0D", tenor="10Y")
        - forward_rate(rlc, forward="0D", tenor="10Y")
    ) * 100.0
    check(
        "a +5 bp 10Y quote moves the rebuilt 10Y par rate by +5 bp",
        abs(moved - 5.0) < 0.05,
        f"{moved:+.4f} bp",
    )


def check_guards(par: Dict[str, float]) -> None:
    print("\n== guards (the failure paths must raise, not degrade) ==")

    def raises(name: str, fn, needle: str = "") -> None:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - any raise is the pass condition
            ok = needle.lower() in str(exc).lower() if needle else True
            check(name, ok, "" if ok else f"raised but not about {needle!r}: {exc}")
            return
        check(name, False, "did not raise")

    raises(
        "rl: too few tenors",
        lambda: build_rl_ois_curve(par_rates={"5Y": 4.0}, ref_date=REF_DATE),
        "min_tenors",
    )
    raises(
        "ql: too few tenors",
        lambda: build_ql_ois_curve(par_rates={"5Y": 4.0}, ref_date=REF_DATE),
        "min_tenors",
    )
    raises(
        "rl: all-NaN grid",
        lambda: build_rl_ois_curve(par_rates={t: float("nan") for t in TENORS}, ref_date=REF_DATE),
        "no usable par rates",
    )
    raises(
        "rl: unknown index",
        lambda: build_rl_ois_curve(par_rates=par, ref_date=REF_DATE, citi_index="USD_LIBOR"),
        "no curve conventions",
    )
    raises(
        "ql: unknown interpolation",
        lambda: build_ql_ois_curve(par_rates=par, ref_date=REF_DATE, interpolation="cubic_spline"),
        "unknown interpolation",
    )
    raises(
        "rl: spline boundary not in the grid",
        lambda: build_rl_ois_curve(par_rates=par, ref_date=REF_DATE, spline_start_tenor="7M3D"),
        "not one of the supplied tenors",
    )
    raises(
        "from_quotes: index in the tags contradicts citi_index",
        lambda: build_rl_ois_curve_from_quotes(
            quotes={f"RATES.OIS.EUR_EUROSTR.PAR.{t}": v for t, v in par.items()},
            ref_date=REF_DATE,
            citi_index="USD_SOFR",
        ),
        "citi_index",
    )
    raises(
        "from_quotes: not a PAR tag",
        lambda: build_rl_ois_curve_from_quotes(
            quotes={"RATES.OIS.USD_SOFR.FWD.5Y.5Y": 4.0}, ref_date=REF_DATE
        ),
        "par",
    )
    # A duplicated tenor cannot be expressed in a dict, so a collision is forced
    # by handing two spellings of the same maturity to the builder.
    raises(
        "rl: two tenors on one maturity date",
        lambda: build_rl_ois_curve(
            par_rates={"1Y": 4.0, "12M": 4.0, "2Y": 3.9, "5Y": 3.8, "10Y": 3.9},
            ref_date=REF_DATE,
        ),
        "collide",
    )


def check_spline(par: Dict[str, float]) -> None:
    print("\n== spline knots ==")
    plain = build_rl_ois_curve(par_rates=par, ref_date=REF_DATE, citi_index="USD_SOFR")
    spline = build_rl_ois_curve(
        par_rates=par, ref_date=REF_DATE, citi_index="USD_SOFR", spline_start_tenor="2Y"
    )
    knots = spline.meta["spline_knots"]
    check("plain curve records no knots", plain.meta["spline_knots"] is None)
    check(
        "spline curve records its knot sequence",
        isinstance(knots, list) and len(knots) >= 8,
        f"{len(knots) if knots else 0} knots",
    )
    err = float(par_reprice_errors_bp(spline).abs().max())
    check(f"spline curve still reprices < {REPRICE_TOL_BP} bp", err < REPRICE_TOL_BP, f"{err:.3e}")

    # Teeth: rebuilding the same nodes WITHOUT the knots is a different curve.
    # The size of the error is a property of the node spacing, so both are
    # measured: on the dense 44-tenor grid it is small, on a sparse one it is
    # not, and the sparse case is what the knot-persistence warning is about.
    def _knotless_error(curve) -> float:
        naked = rl.Curve(
            nodes=dict(curve.rl_pricing_curve.nodes.nodes),
            id="NAKED",
            convention="act360",
            calendar="nyc",
            modifier="mf",
            interpolation="log_linear",
        )
        return max(
            abs(float(irs.rate(curves=naked)) - float(irs.kwargs["fixed_rate"])) * 100.0
            for irs in curve.rl_pricing_curve_instruments.values()
        )

    dense_err = _knotless_error(spline)
    sparse_tenors = ["3M", "6M", "1Y", "2Y", "5Y", "10Y", "30Y", "50Y"]
    sparse = build_rl_ois_curve(
        par_rates={t: par[t] for t in sparse_tenors},
        ref_date=REF_DATE,
        citi_index="USD_SOFR",
        spline_start_tenor="2Y",
    )
    sparse_err = _knotless_error(sparse)
    check(
        "mutation: dropping the knots misprices the calibration set",
        sparse_err > 0.1,
        f"dense 44-tenor grid {dense_err:.4f} bp, sparse 8-tenor grid {sparse_err:.4f} bp",
    )


def check_par_grid() -> None:
    print("\n== par grid fetch / snapshot (hermetic fake Excel) ==")
    stamps = pd.date_range("2026-07-27 09:00", periods=6, freq="h")
    tags = [f"RATES.OIS.USD_SOFR.PAR.{t}" for t in TENORS]
    data = FakeVelocityData(
        series={
            tag: pd.Series([4.0 + 0.001 * i + 0.01 * j for j in range(len(stamps))], index=stamps)
            for i, tag in enumerate(tags)
        }
    )
    data.bad_tags = {tags[3]}  # one tenor the add-in refuses
    client = CitiVelocityExcelClient(app=FakeExcelApp(data, pending_reads=0), poll_interval=0.0)
    try:
        frame = fetch_par_grid(client=client, citi_index="USD_SOFR", freq="HOURLY", period="1W")
    finally:
        client.close()

    check("grid is one CVTSHIST-shaped frame", isinstance(frame, pd.DataFrame) and not frame.empty)
    check(
        "a bad tenor costs its own column and nothing else",
        len(frame.columns) == len(TENORS) - 1,
        f"{len(frame.columns)} of {len(TENORS)}",
    )
    check(
        "columns are in maturity order, not lexical",
        list(frame.columns) == tenor_columns_from_tags(frame.columns),
        str(list(frame.columns)[:6]),
    )

    snap = par_grid_snapshot(frame, "2026-07-27 11:30")
    check(
        "asof does not look forward",
        snap.name == pd.Timestamp("2026-07-27 11:00"),
        str(snap.name),
    )
    # 11:40 is nearer to the 12:00 row than to the 11:00 one, so 'nearest'
    # answers with a row from the future while 'asof' does not. (11:30 would be
    # an exact tie and would prove nothing.)
    late = par_grid_snapshot(frame, "2026-07-27 11:40", method="asof")
    near = par_grid_snapshot(frame, "2026-07-27 11:40", method="nearest")
    check(
        "mutation: nearest DOES look forward (which is why it is not the default)",
        near.name > pd.Timestamp("2026-07-27 11:40") > late.name,
        f"nearest={near.name}, asof={late.name}",
    )
    exact = par_grid_snapshot(frame, "2026-07-27 11:00", method="exact")
    check("exact returns the exact row", exact.name == pd.Timestamp("2026-07-27 11:00"))
    try:
        par_grid_snapshot(frame, "2026-07-27 11:30", method="exact")
        check("exact raises on a missing timestamp", False, "did not raise")
    except ValueError:
        check("exact raises on a missing timestamp", True)
    try:
        par_grid_snapshot(frame, "2020-01-01")
        check("asof raises when the window starts too late", False, "did not raise")
    except ValueError:
        check("asof raises when the window starts too late", True)

    # A snapshot must be directly buildable.
    rlc = build_rl_ois_curve(par_rates=snap, ref_date=snap.name, citi_index="USD_SOFR")
    check(
        "a snapshot builds a curve straight off",
        float(par_reprice_errors_bp(rlc).abs().max()) < REPRICE_TOL_BP,
    )

    # Cache round trip: second call must not touch the client.
    with tempfile.TemporaryDirectory() as tmp:
        cache = CitiVeloTagCache(base_dir=pathlib.Path(tmp))
        app = FakeExcelApp(data, pending_reads=0)
        client = CitiVelocityExcelClient(app=app, poll_interval=0.0)
        try:
            fetch_par_grid(
                client=client,
                citi_index="USD_SOFR",
                freq="HOURLY",
                start="2026-07-27",
                end="2026-07-28",
                cache=cache,
            )
            first = len(app.formulas_for("CVTSHIST"))
            frame2 = fetch_par_grid(
                client=None,
                citi_index="USD_SOFR",
                freq="HOURLY",
                start="2026-07-27",
                end="2026-07-28",
                cache=cache,
            )
        finally:
            client.close()
        check("cache serves the second read with no client", not frame2.empty, f"{frame2.shape}")
        check("first read did hit the add-in", first > 0, f"{first} CVTSHIST call(s)")
    try:
        fetch_par_grid(client=None, citi_index="USD_SOFR", cache=cache, period="1Y")
        check("period + cache is refused", False, "did not raise")
    except ValueError:
        check("period + cache is refused", True)


def check_all_twenty() -> None:
    print("\n== all 20 curves build and reprice ==")
    rows = []
    for token in supported_indices():
        t0 = time.time()
        try:
            par, _truth, _ref = synthetic_grid(token)
            rlc = build_rl_ois_curve(par_rates=par, ref_date=REF_DATE, citi_index=token)
            qlc = build_ql_ois_curve(par_rates=par, ref_date=REF_DATE, citi_index=token)
            r = float(par_reprice_errors_bp(rlc).abs().max())
            q = float(ql_par_reprice_errors_bp(qlc, par).abs().max())
            gap = max(
                abs(forward_rate(rlc, forward=f, tenor=t) - ql_forward_rate(qlc, forward=f, tenor=t))
                * 100.0
                for f, t in FORWARDS
            )
            rows.append((token, r, q, gap, len(pillar_mismatches(rlc, qlc)), time.time() - t0, ""))
        except Exception as exc:  # noqa: BLE001 - report, do not abort the sweep
            rows.append(
                (token, float("nan"), float("nan"), float("nan"), -1, time.time() - t0, str(exc)[:90])
            )
    print(f"  {'index':16s} {'rl bp':>10s} {'ql bp':>10s} {'fwd gap bp':>11s} {'cal':>4s} {'sec':>6s}  note")
    for token, r, q, gap, mism, secs, note in rows:
        print(f"  {token:16s} {r:10.2e} {q:10.2e} {gap:11.5f} {mism:4d} {secs:6.2f}  {note}")

    bad_build = [r for r in rows if r[6] or not (r[1] < REPRICE_TOL_BP and r[2] < REPRICE_TOL_BP)]
    check(
        f"all {len(rows)} curves build and reprice their own inputs < {REPRICE_TOL_BP} bp",
        not bad_build,
        ", ".join(f"{b[0]}({b[6] or 'tolerance'})" for b in bad_build),
    )
    # The cross-backend bound is asserted only where the two libraries' holiday
    # calendars put the pillars on the same days. Where they do not (column
    # 'cal'), the gap is a calendar-data difference between rateslib and
    # QuantLib, and it is reported rather than asserted away.
    aligned = [r for r in rows if r[4] == 0]
    misaligned = [r for r in rows if r[4] > 0]
    check(
        f"{len(aligned)} calendar-aligned curves agree < {REPRICE_TOL_BP} bp",
        all(r[3] < REPRICE_TOL_BP for r in aligned),
        ", ".join(f"{r[0]}={r[3]:.5f}" for r in aligned if r[3] >= REPRICE_TOL_BP),
    )
    if misaligned:
        print(
            "  NOTE: "
            + ", ".join(f"{r[0]} ({r[4]} pillar(s), gap {r[3]:.5f} bp)" for r in misaligned)
            + " - rateslib and QuantLib disagree about that currency's holidays, so the"
            " swaps mature on different days. Neither builder is wrong; the calendars are."
        )
    check(
        "every misaligned curve's gap is explained by its pillar mismatches",
        all(r[3] < 0.5 for r in misaligned),
        ", ".join(f"{r[0]}={r[3]:.5f}" for r in misaligned if r[3] >= 0.5),
    )


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    # rateslib 2.1.1's Solver prints its own SUCCESS line and offers no quiet
    # switch, so expect one per solve interleaved with the output below.
    print("=" * 78)
    print(f"Citi Velocity curve builders - smoke test  (ref_date {REF_DATE}, {len(TENORS)} tenors)")
    print("=" * 78)

    check_convention_tables()
    check_calendar_divergence()

    print("\n== self-consistent synthetic grid, per currency ==")
    usd_par: Dict[str, float] = {}
    for token in REQUIRED:
        par = check_currency(token)
        if token == "USD_SOFR":
            usd_par = par

    check_evaluation_date_hygiene(usd_par)
    check_mutations(usd_par)
    check_spline(usd_par)
    check_guards(usd_par)
    check_par_grid()
    check_all_twenty()

    print("\n" + "=" * 78)
    if _failures:
        print(f"FAILED: {len(_failures)} check(s)")
        for f in _failures:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

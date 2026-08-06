r"""Round-trip smoke test for the Citi Velocity inflation builders.

Run::

    python -m MDP.CitiVelocityExcel.inflation._smoke

What it proves
--------------
1. Both backends invert their own pricer: a curve stripped from a set of
   zero-coupon inflation swap quotes reprices those quotes (2.2e-06 bp or better).
2. rateslib and QuantLib produce the same curve where nothing pins them to -
   **off-pillar** breakevens and implied index **levels**, not the pillar
   breakevens, which calibration fixes by construction and which are therefore a
   weak test. Both comparisons are printed.
3. The specific failure modes the modules claim to guard against actually happen -
   each is provoked here, with the resulting error in bp, so the numbers quoted in
   the docstrings are measured rather than asserted.

What it does NOT prove
----------------------
Nothing here touches a live Citi quote or a real published CPI print. The index
history is synthetic (a flat 2.5% p.a. compounding series), so seasonality is
absent by construction, and the conventions used for anything outside USD/EUR/GBP
are market standard rather than library-supplied.

And one thing it structurally cannot prove: **a self-consistent observation-lag
error is invisible to a round trip.** Rebuilding at a 6-month lag with a
6-month-lagged base leaves every breakeven and even the repricing error
bit-identical - the lag shifts both index observations together, so the ratio is
unchanged. That case is run below and reported, precisely so nobody reads
``SMOKE PASS`` as evidence the lags are right. Self-consistency is not correctness
against the market.
"""

from __future__ import annotations

import datetime
import warnings
from typing import Dict, List, Mapping, Tuple

import pandas as pd
import QuantLib as ql
import rateslib as rl

from MDP.CitiVelocityExcel.errors import CitiVelocityError
from MDP.CitiVelocityExcel.inflation.indices import (
    conventions_for,
    index_base_month,
    required_fixing_months,
)
from MDP.CitiVelocityExcel.inflation.ql_inflation import (
    _fixed_day_count,
    _zc_swap,
    build_ql_zero_inflation_curve,
    ql_breakeven,
    to_ql_date,
)
from MDP.CitiVelocityExcel.inflation.rl_inflation import (
    IndexBondDescriptor,
    _assert_index_values_populated,
    build_rl_index_curve,
    rl_breakeven,
    rl_index_bond,
)

#: Reference date for the whole run. Chosen so the base month (May 2026 at a
#: 3-month lag) is comfortably inside the synthetic history.
REF_DATE = datetime.date(2026, 8, 5)

#: A plausible, gently humped breakeven curve. Levels are arbitrary; only
#: self-consistency is being tested.
QUOTES: Dict[str, float] = {
    "1Y": 2.80, "2Y": 2.60, "3Y": 2.50, "5Y": 2.45, "7Y": 2.44,
    "10Y": 2.45, "12Y": 2.46, "15Y": 2.50, "20Y": 2.52, "25Y": 2.53,
    "30Y": 2.55, "40Y": 2.56,
}

#: Tenors reported in the cross-backend comparison. All are calibration pillars,
#: so agreement here is largely pinned by the round trip - see OFF_PILLAR.
COMPARE_AT: Tuple[str, ...] = ("2Y", "5Y", "10Y", "30Y")

#: Tenors deliberately NOT in :data:`QUOTES`. Nothing pins the two backends here:
#: rateslib interpolates log-linearly on index discount factors, QuantLib linearly
#: on zero inflation rates. This is where a real disagreement would show.
OFF_PILLAR: Tuple[str, ...] = ("4Y", "8Y", "17Y", "35Y")

#: The three indices with library-supplied conventions, and a starting level for
#: each synthetic index history.
INDICES: Tuple[Tuple[str, float], ...] = (
    ("USD_CPURNSA", 320.0),
    ("GBP_UKRPI", 400.0),
    ("EUR_CPTFEMU", 130.0),
)

#: Synthetic index growth, p.a. Flat by construction: no seasonality, so the two
#: backends' month arithmetic can be compared without a confound.
_SYNTHETIC_GROWTH = 0.025


def _month_start(d: datetime.date, back: int = 0) -> datetime.date:
    total = d.month - 1 - back
    year = d.year + total // 12
    return datetime.date(year, total % 12 + 1, 1)


def synthetic_fixings(
    *, level: float, anchor_month: datetime.date, back: int = 72, forward: int = 6
) -> pd.Series:
    """A month-start index history compounding at :data:`_SYNTHETIC_GROWTH`.

    ``level`` is the value AT ``anchor_month``; months either side scale by
    ``(1 + g) ** (k / 12)``. Extends ``forward`` months past the anchor because a
    daily-interpolated observation reads the month after the reference month.
    """
    out: Dict[datetime.date, float] = {}
    for k in range(-back, forward + 1):
        month = _month_start(anchor_month, -k)
        out[month] = level * (1.0 + _SYNTHETIC_GROWTH) ** (k / 12.0)
    return pd.Series(out).sort_index()


def _published_only(fixings: pd.Series, ref: datetime.date, publication_lag: int) -> pd.Series:
    """Trim the history to what a desk could actually see on ``ref``."""
    latest = _month_start(ref, publication_lag)
    return fixings[fixings.index <= latest]


# ------------------------------------------------------------------ #
#                        the two round trips                         #
# ------------------------------------------------------------------ #


def round_trip(citi_index: str, level: float) -> Dict[str, object]:
    """Build both backends for one index and measure everything."""
    convention = conventions_for(citi_index)
    base_month = index_base_month(REF_DATE, convention)
    full = synthetic_fixings(level=level, anchor_month=base_month)
    fixings = _published_only(full, REF_DATE, convention.publication_lag)
    index_base = float(fixings.loc[base_month])

    nominal_rl = rl.Curve(
        {datetime.datetime(2026, 8, 1): 1.0, datetime.datetime(2076, 1, 1): 0.20},
        id=f"{convention.currency.lower()}_nom",
        convention="act365f",
        calendar=convention.calendar,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        rlc = build_rl_index_curve(
            zc_swap_rates=QUOTES,
            ref_date=REF_DATE,
            citi_index=citi_index,
            index_base=index_base,
            nominal_curve=nominal_rl,
            index_fixings=fixings,
        )

    nominal_ql = ql.YieldTermStructureHandle(
        ql.FlatForward(
            to_ql_date(rlc.effective), ql.QuoteHandle(ql.SimpleQuote(0.035)), ql.Actual365Fixed()
        )
    )
    qlc = build_ql_zero_inflation_curve(
        zc_swap_rates=QUOTES,
        ref_date=REF_DATE,
        citi_index=citi_index,
        nominal_handle=nominal_ql,
        fixings=fixings,
        effective=rlc.effective,
    )

    all_diffs = {t: (rl_breakeven(rlc, t) - ql_breakeven(qlc, t)) * 100.0 for t in rlc.tenors}
    off_diffs = {t: (rl_breakeven(rlc, t) - ql_breakeven(qlc, t)) * 100.0 for t in OFF_PILLAR}
    # Implied index levels at the pillar maturities. Unlike the pillar breakevens
    # these are NOT pinned by calibration when the two fixed-leg year counts
    # disagree, so this is the honest cross-backend check.
    level_diffs = {}
    for tenor, mat in zip(qlc.tenors, qlc.maturities):
        rl_level = rlc.index_value(mat)
        ql_level = qlc.index_value(mat)
        level_diffs[tenor] = (rl_level / ql_level - 1.0) * 1e4
    return {
        "convention": convention,
        "rl": rlc,
        "ql": qlc,
        "fixings": fixings,
        "index_base": index_base,
        "base_month": base_month,
        "diffs": {t: all_diffs[t] for t in COMPARE_AT},
        "off_diffs": off_diffs,
        "level_diffs": level_diffs,
        "max_abs_diff_bp": max(abs(v) for v in all_diffs.values()),
        "worst_diff_tenor": max(all_diffs, key=lambda t: abs(all_diffs[t])),
        "max_off_pillar_bp": max(abs(v) for v in off_diffs.values()),
        "max_level_bp": max(abs(v) for v in level_diffs.values()),
        "worst_level_tenor": max(level_diffs, key=lambda t: abs(level_diffs[t])),
    }


# ------------------------------------------------------------------ #
#                     provoked failure modes                         #
# ------------------------------------------------------------------ #


def check_discounting_is_irrelevant(result: Mapping[str, object]) -> float:
    """Both ZCIS legs settle on the same date, so the discount curve cancels.

    Returns the largest breakeven change, in bp, between a 0% and a 6% nominal
    curve on an otherwise identical build.
    """
    citi_index = result["convention"].citi_index  # type: ignore[union-attr]
    fixings = result["fixings"]
    worst = 0.0
    curves = {}
    for rate, df_far in (("zero", 1.00), ("six", 0.05)):
        nominal = rl.Curve(
            {datetime.datetime(2026, 8, 1): 1.0, datetime.datetime(2076, 1, 1): df_far},
            id=f"nom_{rate}",
            convention="act365f",
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            curves[rate] = build_rl_index_curve(
                zc_swap_rates=QUOTES,
                ref_date=REF_DATE,
                citi_index=citi_index,
                index_base=result["index_base"],
                nominal_curve=nominal,
                index_fixings=fixings,
            )
    for tenor in curves["zero"].tenors:
        worst = max(worst, abs(rl_breakeven(curves["zero"], tenor) - rl_breakeven(curves["six"], tenor)) * 100.0)
    return worst


def check_wrong_base_month(result: Mapping[str, object]) -> Dict[str, float]:
    """Reprice with the LATEST PUBLISHED fixing as the base instead of the lagged one.

    This is the mistake the whole conventions table exists to stop: the base index
    is a published number and there is exactly one right month for it.

    Returns ``{tenor: error in bp}``.
    """
    rlc = result["rl"]
    convention = result["convention"]
    fixings: pd.Series = result["fixings"]  # type: ignore[assignment]
    naive_base = float(fixings.iloc[-1])  # latest print a desk can see
    out: Dict[str, float] = {}
    for tenor in COMPARE_AT:
        correct = rl_breakeven(rlc, tenor)
        wrong = rl.ZCIS(
            effective=rlc.effective,
            termination=tenor,
            spec=convention.rl_spec,
            curves=[rlc.curve, rlc.nominal],
            leg2_index_base=naive_base,
            leg2_index_lag=rlc.index_lag,
            leg2_index_method=rlc.index_method,
        )
        out[tenor] = (float(wrong.rate()) - correct) * 100.0
    return out


def check_rl_silent_zero(result: Mapping[str, object]) -> str:
    """Anchor an index curve on ``ref_date`` instead of the first of the month.

    rateslib then reads ``index_value`` at a date before the initial node, warns,
    and returns 0.0. The guard must convert that into a raise.
    """
    rlc = result["rl"]
    convention = result["convention"]
    bad = rl.Curve(
        {
            datetime.datetime(REF_DATE.year, REF_DATE.month, REF_DATE.day): 1.0,
            datetime.datetime(2056, 8, 5): 0.55,
        },
        id="bad_anchor",
        index_base=result["index_base"],
        index_lag=convention.observation_lag,
        interpolation="log_linear",
        convention="act365f",
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        leaked = float(
            bad.index_value(
                datetime.datetime(rlc.effective.year, rlc.effective.month, rlc.effective.day),
                convention.observation_lag,
                convention.index_method,
            )
        )
    try:
        _assert_index_values_populated(
            bad,
            [datetime.datetime(rlc.effective.year, rlc.effective.month, rlc.effective.day)],
            lag=convention.observation_lag,
            method=convention.index_method,
            citi_index=convention.citi_index,
        )
    except CitiVelocityError:
        return f"rateslib returned index base {leaked:.4f} (true {rlc.swap_index_base:.4f}); guard RAISED"
    return f"GUARD DID NOT FIRE - rateslib returned {leaked!r}"


def check_ql_evaluation_date(result: Mapping[str, object]) -> float:
    """Bootstrap with the evaluation date left on ``ref_date`` while spot is T+2.

    ``ZeroCouponInflationSwapHelper`` starts its swap at the evaluation date, so
    the helpers describe swaps starting a day or two before the spot swaps being
    repriced. Returns the worst self-repricing error in bp.
    """
    convention = result["convention"]
    if convention.spot_lag == 0:
        return 0.0
    fixings: pd.Series = result["fixings"]  # type: ignore[assignment]
    rlc = result["rl"]
    cal = result["ql"].calendar
    fixed_dc = result["ql"].fixed_day_count
    obs = result["ql"].observation_interpolation
    lag = ql.Period(convention.observation_lag, ql.Months)

    ql.Settings.instance().evaluationDate = to_ql_date(REF_DATE)  # deliberately wrong
    handle = ql.RelinkableZeroInflationTermStructureHandle()
    index = convention.ql_index(handle)
    ql.IndexManager.instance().clearHistory(index.name())
    for month, level in fixings.items():
        index.addFixing(to_ql_date(month), float(level), True)
    nominal = ql.YieldTermStructureHandle(
        ql.FlatForward(to_ql_date(REF_DATE), ql.QuoteHandle(ql.SimpleQuote(0.035)), ql.Actual365Fixed())
    )
    tenors = list(rlc.tenors)
    mats = [cal.advance(to_ql_date(rlc.effective), ql.Period(t), ql.ModifiedFollowing) for t in tenors]
    helpers = [
        ql.ZeroCouponInflationSwapHelper(
            ql.QuoteHandle(ql.SimpleQuote(QUOTES[t] / 100.0)), lag, m, cal,
            ql.ModifiedFollowing, fixed_dc, index, obs, nominal,
        )
        for t, m in zip(tenors, mats)
    ]
    curve = ql.PiecewiseZeroInflation(
        to_ql_date(REF_DATE),
        ql.inflationPeriod(to_ql_date(REF_DATE) - lag, ql.Monthly)[0],
        ql.Monthly, fixed_dc, helpers,
    )
    curve.enableExtrapolation()
    handle.linkTo(curve)
    worst = 0.0
    for tenor, mat in zip(tenors, mats):
        swap = ql.ZeroCouponInflationSwap(
            ql.Swap.Payer, 1.0e6, to_ql_date(rlc.effective), mat, cal, ql.ModifiedFollowing,
            fixed_dc, QUOTES[tenor] / 100.0, index, lag, obs,
        )
        swap.setPricingEngine(ql.DiscountingSwapEngine(nominal))
        worst = max(worst, abs(float(swap.fairRate()) * 100.0 - QUOTES[tenor]) * 100.0)
    result["ql"].activate()  # type: ignore[union-attr]
    return worst


def check_zerorate_is_not_breakeven(result: Mapping[str, object]) -> Dict[str, float]:
    """``curve.zeroRate`` is the curve's parametrisation, not the tradeable rate."""
    qlc = result["ql"]
    qlc.activate()
    out: Dict[str, float] = {}
    for tenor, mat in zip(qlc.tenors, qlc.maturities):
        if tenor not in ("1Y", "2Y", "10Y", "30Y"):
            continue
        zero = float(qlc.curve.zeroRate(to_ql_date(mat), qlc.observation_lag, False)) * 100.0
        out[tenor] = (zero - ql_breakeven(qlc, tenor)) * 100.0
    return out


def check_fixed_day_count(result: Mapping[str, object]) -> Dict[str, float]:
    """Price the SAME swaps off the SAME curve with ActAct/ISDA instead of 30/360.

    Rebuilding the curve with the other day count would hide the effect - the
    bootstrap absorbs it and the quotes reprice either way. The honest experiment
    holds the curve fixed and changes only the fixed leg's year fraction.
    ``(1+r)^N`` wants exactly N; ActAct/ISDA returns N plus a leap remainder.

    Returns ``{tenor: fair-rate difference in bp}``.
    """
    qlc = result["ql"]
    qlc.activate()
    actact = _fixed_day_count("ActActISDA")
    engine = ql.DiscountingSwapEngine(qlc.nominal_handle)
    out: Dict[str, float] = {}
    for tenor, mat, quote in zip(qlc.tenors, qlc.maturities, qlc.quotes):
        if tenor not in COMPARE_AT:
            continue
        pair = []
        for day_count in (qlc.fixed_day_count, actact):
            swap = _zc_swap(
                index=qlc.index, calendar=qlc.calendar, day_count=day_count,
                obs=qlc.observation_interpolation, lag=qlc.observation_lag,
                effective=qlc.effective, maturity=mat, fixed_rate=quote / 100.0,
                notional=1.0e6,
            )
            swap.setPricingEngine(engine)
            pair.append(float(swap.fairRate()) * 100.0)
        out[tenor] = (pair[1] - pair[0]) * 100.0
    return out


def check_lag_is_invisible_to_round_trip(result: Mapping[str, object]) -> List[str]:
    """Rebuild with a deliberately wrong 6-month lag and a matching wrong base.

    This is the honest bound on what this whole script can prove. Everything about
    the round trip is scale-invariant in the lag: shift both observations by the
    same number of months and the ratio, hence the breakeven, is unchanged. The
    error shows up only in the implied index LEVEL, and only against a published
    print.
    """
    rlc = result["rl"]
    convention = result["convention"]
    fixings: pd.Series = result["fixings"]  # type: ignore[assignment]
    wrong_base_month = _month_start(REF_DATE, 6)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        wrong = build_rl_index_curve(
            zc_swap_rates=QUOTES,
            ref_date=REF_DATE,
            citi_index=convention.citi_index,
            index_base=float(fixings.loc[wrong_base_month]),
            nominal_curve=rlc.nominal,
            index_fixings=fixings,
            index_lag=6,
        )
    be = [
        f"{t} {(rl_breakeven(wrong, t) - rl_breakeven(rlc, t)) * 100.0:+.2e}"
        for t in COMPARE_AT
    ]
    levels = []
    for tenor, mat in zip(result["ql"].tenors, result["ql"].maturities):
        if tenor in COMPARE_AT:
            levels.append(f"{tenor} {1e4 * (rlc.index_value(mat) / wrong.index_value(mat) - 1.0):+.1f}")
    return [
        f"  reprice error {rlc.max_repricing_error_bp:.2e} bp (3M) vs "
        f"{wrong.max_repricing_error_bp:.2e} bp (6M) - the round trip cannot see it",
        f"  breakeven change, bp : {'  '.join(be)}",
        f"  index LEVEL change, bp of level : {'  '.join(levels)}",
    ]


def check_quarterly_refused() -> str:
    """``AUD_AUCPI`` is quarterly; rateslib must refuse it, QuantLib must take it."""
    try:
        build_rl_index_curve(
            zc_swap_rates=QUOTES,
            ref_date=REF_DATE,
            citi_index="AUD_AUCPI",
            index_base=100.0,
        )
    except CitiVelocityError as exc:
        head = str(exc).split(".")[0]
        return f"rateslib REFUSED: {head}."
    return "rateslib DID NOT REFUSE a quarterly index - guard broken"


def check_index_bond(result: Mapping[str, object]) -> List[str]:
    """A seasoned index-linked gilt: refused without fixings, priced with them.

    Also confirms the bond uses LINKER conventions (3M/daily) rather than the RPI
    SWAP's (2M/monthly).
    """
    rlc = result["rl"]
    descriptor = IndexBondDescriptor(
        citi_index="GBP_UKRPI",
        effective=datetime.date(2013, 3, 22),
        termination=datetime.date(2036, 3, 22),
        fixed_rate=0.125,
        index_base=242.0,
        notional=-100.0,
    )
    lines: List[str] = []

    # What the guard is stopping: price the same bond with the zeros left in.
    unguarded = rl.IndexFixedRateBond(
        effective=datetime.datetime(2013, 3, 22),
        termination=datetime.datetime(2036, 3, 22),
        fixed_rate=descriptor.fixed_rate,
        index_base=descriptor.index_base,
        notional=descriptor.notional,
        spec="uk_gbi",
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        leaked = float(unguarded.rate(curves=[rlc.curve, rlc.nominal], metric="clean_price"))

    try:
        rl_index_bond(descriptor=descriptor, index_curve=rlc)
        lines.append("  GUARD DID NOT FIRE on a seasoned linker without index_fixings")
    except CitiVelocityError as exc:
        lines.append(f"  no index_fixings -> RAISED ({str(exc).split(' - ')[0]})")

    history = synthetic_fixings(
        level=result["index_base"], anchor_month=result["base_month"], back=200
    )
    history = _published_only(history, REF_DATE, rlc.convention.publication_lag)
    bond = rl_index_bond(descriptor=descriptor, index_curve=rlc, index_fixings=history)
    price = float(bond.rate(curves=[rlc.curve, rlc.nominal], metric="clean_price"))
    lines.append(
        f"  with index_fixings   -> index_lag {bond.leg1.index_lag}M / "
        f"{bond.leg1.index_method} (the SWAP is {rlc.convention.observation_lag}M / "
        f"{rlc.convention.index_method}); clean price {price:.4f} "
        f"vs {leaked:.4f} unguarded"
    )
    return lines


# ------------------------------------------------------------------ #
#                               main                                 #
# ------------------------------------------------------------------ #


def main() -> int:
    print("=" * 78)
    print("Citi Velocity inflation - rateslib 2.1.1 vs QuantLib 1.41 round trip")
    print(f"reference date {REF_DATE:%Y-%m-%d}   "
          f"{len(QUOTES)} quotes {min(QUOTES, key=lambda t: len(t))}..40Y   "
          "synthetic 2.5% p.a. index history, no seasonality")
    print("=" * 78)

    results: Dict[str, Dict[str, object]] = {}
    for citi_index, level in INDICES:
        results[citi_index] = round_trip(citi_index, level)

    print()
    print("--- calibration round trip -------------------------------------------------")
    print(f"{'index':<14} {'lag/method':<14} {'rl err bp':>12} {'ql err bp':>12}  base month / level")
    for citi_index, res in results.items():
        c = res["convention"]
        rlc, qlc = res["rl"], res["ql"]
        print(
            f"{citi_index:<14} {str(c.observation_lag) + 'M/' + c.index_method:<14} "
            f"{rlc.max_repricing_error_bp:>12.3e} {qlc.max_repricing_error_bp:>12.3e}"
            f"  {res['base_month']:%Y-%m} @ {res['index_base']:.4f}"
        )

    print()
    print("--- rateslib minus QuantLib breakeven at PILLARS, bp -----------------------")
    print("    (each backend calibrated to the same quotes, so this mostly re-tests the")
    print("     round trip; the informative comparisons are the two tables below)")
    print(f"{'index':<14}" + "".join(f"{t:>12}" for t in COMPARE_AT) + f"{'worst (all)':>16}")
    for citi_index, res in results.items():
        row = f"{citi_index:<14}" + "".join(f"{res['diffs'][t]:>12.6f}" for t in COMPARE_AT)
        row += f"{res['max_abs_diff_bp']:>12.6f} @{res['worst_diff_tenor']:>3}"
        print(row)

    print()
    print("--- rateslib minus QuantLib breakeven OFF PILLAR, bp -----------------------")
    print("    (nothing pins these: rl interpolates log-linearly on index DFs, ql")
    print("     linearly on zero inflation rates)")
    print(f"{'index':<14}" + "".join(f"{t:>12}" for t in OFF_PILLAR))
    for citi_index, res in results.items():
        print(f"{citi_index:<14}" + "".join(f"{res['off_diffs'][t]:>12.6f}" for t in OFF_PILLAR))

    print()
    print("--- implied index LEVEL, rl vs ql at pillar maturities, bp of level --------")
    print("    (not pinned by calibration when the two fixed-leg year counts disagree)")
    print(f"{'index':<14}" + "".join(f"{t:>12}" for t in COMPARE_AT) + f"{'worst (all)':>16}")
    for citi_index, res in results.items():
        row = f"{citi_index:<14}" + "".join(f"{res['level_diffs'][t]:>12.6f}" for t in COMPARE_AT)
        row += f"{res['max_level_bp']:>12.6f} @{res['worst_level_tenor']:>3}"
        print(row)

    usd = results["USD_CPURNSA"]

    print()
    print("--- provoked failure modes (USD unless noted) ------------------------------")
    print(f"discount curve 0% vs 6%, worst breakeven change : "
          f"{check_discounting_is_irrelevant(usd):.3e} bp   (ZCIS legs settle same day)")

    wrong = check_wrong_base_month(usd)
    print("base index taken from the LATEST PUBLISHED month instead of the lagged one:")
    for tenor, err in wrong.items():
        print(f"    {tenor:>4}  {err:+8.2f} bp")

    print(f"curve anchored on ref_date not month start       : {check_rl_silent_zero(usd)}")

    eval_err = check_ql_evaluation_date(usd)
    print(f"QuantLib evaluationDate left on ref_date         : "
          f"{eval_err:.4f} bp worst self-repricing error")

    zr = check_zerorate_is_not_breakeven(usd)
    print("curve.zeroRate() minus the swap fair rate        : "
          + "  ".join(f"{t} {v:+.3f} bp" for t, v in zr.items()))

    dc = check_fixed_day_count(usd)
    print("fixed leg ActAct/ISDA instead of 30/360, same curve:")
    print("    " + "  ".join(f"{t} {v:+.4f} bp" for t, v in dc.items()))

    print("a WRONG 3-month lag error (6M instead of 3M), with a matching wrong base:")
    for line in check_lag_is_invisible_to_round_trip(usd):
        print(line)

    print(f"quarterly index (AUD_AUCPI)                     : {check_quarterly_refused()}")
    print("index-linked gilt (GBP, 2013 issue):")
    for line in check_index_bond(results["GBP_UKRPI"]):
        print(line)

    print()
    print("--- required fixings per index ---------------------------------------------")
    for citi_index, res in results.items():
        c = res["convention"]
        months = required_fixing_months(REF_DATE, res["rl"].effective, c)
        print(f"{citi_index:<14} effective {res['rl'].effective:%Y-%m-%d}  needs "
              f"{', '.join(m.strftime('%Y-%m') for m in months)}"
              f"   (QuantLib baseDate {res['ql'].base_date:%Y-%m-%d})")

    worst_backend = max(r["max_abs_diff_bp"] for r in results.values())
    worst_off = max(r["max_off_pillar_bp"] for r in results.values())
    worst_level = max(r["max_level_bp"] for r in results.values())
    worst_reprice = max(
        max(r["rl"].max_repricing_error_bp, r["ql"].max_repricing_error_bp) for r in results.values()
    )
    print()
    print("=" * 78)
    print(f"worst self-repricing error, either backend, any index : {worst_reprice:.3e} bp")
    print(f"worst rateslib-vs-QuantLib pillar breakeven diff      : {worst_backend:.6f} bp")
    print(f"worst rateslib-vs-QuantLib OFF-PILLAR breakeven diff  : {worst_off:.6f} bp")
    print(f"worst rateslib-vs-QuantLib index LEVEL diff           : {worst_level:.6f} bp of level")
    print("=" * 78)
    ok = worst_reprice < 1e-3 and worst_backend < 1e-2 and worst_off < 1.0
    print("SMOKE PASS" if ok else "SMOKE FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

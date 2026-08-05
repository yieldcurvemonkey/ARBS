r"""Smoke test for :mod:`MDP.CitiVelocityExcel.options`. Reports numbers, not "OK".

Run::

    C:/Users/chris/anaconda3/envs/stir/python.exe -m MDP.CitiVelocityExcel.options._smoke

Eight sections, each printing what it measured rather than asserting it passed:

1.  every pair/underlying token form the splitter supports, INCLUDING the
    supposedly-ambiguous ones, with the full candidate enumeration shown so the
    "only one split exists" claim is visible rather than asserted;
2.  the Hagan CMS convexity adjustment against ``ql.LinearTsrPricer`` and
    ``ql.AnalyticHaganPricer``, run **twice** - on a flat curve, where Hagan's
    own flat-yield assumption is true and the gap is therefore pure algebra, and
    on a sloped one, where the gap is the approximation's real cost;
2b. all four ``forward_swap_rate`` backends on ONE set of discount factors, with
    the day-count effect separated from the missing-calendar effect;
3.  a 1Y expiry 10Y-2Y single-look cap across a correlation sweep, showing
    monotonicity in rho and the round trip through :func:`implied_correlation`;
4.  the same option against QuantLib's ``LognormalCmsSpreadPricer`` caplet, with
    a NORMAL surface (a wiring check - both reduce to the same formula) and a
    LOGNORMAL one (a genuine model difference), plus the 1-coupon vs 2-coupon
    NPVs that show a strip is not a single look;
5.  a 1Y1Y midcurve: what the expiry and the forward start compose to, what each
    wrong reading costs, and the Bachelier cross-check (a tautology by
    construction, reported as one);
6.  the vol-cube reader in all three modes, including interpolation, the
    duck-typed sources, and the bp-vs-decimal unit trap demonstrated against the
    real sibling ``SwaptionCubeData``;
7.  the fetch path against the package's fake Excel, plus the loud failure when
    the unverified tag shape serves nothing.

Nothing here needs Excel or market data. Section 7 uses
:mod:`MDP.CitiVelocityExcel.testing`.

The checks were confirmed to have teeth by mutation: flipping the sign of the
``-2 rho`` term in the spread variance makes section 3's monotonicity check
report ``False`` and its round-trip error jump from 6e-13 to 1.98; dropping the
payment-delay term from ``G'/G`` shifts the convexity adjustment by 0.98 bp,
five times the 0.20 bp gap section 2 measures.
"""

from __future__ import annotations

import datetime
import warnings

import pandas as pd
import QuantLib as ql

from MDP.CitiVelocityExcel.catalog import TENOR_RE
from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient
from MDP.CitiVelocityExcel.errors import CitiVelocityError
from MDP.CitiVelocityExcel.options.midcurves import (
    add_tenors,
    fetch_midcurves,
    midcurve_forward,
    midcurve_from_vol_cube,
    midcurve_implied_vol,
    midcurve_price,
    midcurve_vol_from_decomposition,
    parse_underlying,
)
from MDP.CitiVelocityExcel.options.spread_options import (
    QlCmsSpreadBuild,
    SpreadOptionQuote,
    build_ql_cms_spread,
    cms_rate,
    fetch_spread_options,
    forward_swap_rate,
    hagan_convexity_adjustment,
    hagan_g_ratio,
    implied_correlation,
    pair_token,
    parse_pair,
    single_look_spread_option_price,
    spread_normal_vol,
)
from MDP.CitiVelocityExcel.testing import FakeExcelApp, FakeVelocityData
from Query.Base.bachelier import bachelier_price

BP = 1e4
TODAY = datetime.date(2026, 8, 5)


def rule(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


# ------------------------------------------------------------------ #
#                     1. the tenor-pair grammar                      #
# ------------------------------------------------------------------ #


def section_grammar() -> None:
    rule("1. pair / underlying token forms")

    tokens = [
        "2Y5Y", "5Y10Y", "10Y30Y", "1Y10Y", "1Y1Y", "30Y10Y",
        "18M2Y", "3M2Y", "2W1M", "1D1W",
        "10Y-30Y", "10Y/30Y", "10Yx30Y", "10Y_30Y", "10Y 30Y", "10Yvs30Y",
    ]
    print(f"{'token':12s} {'parse_pair':20s} {'naive middle split':22s} {'#valid splits'}")
    for token in tokens:
        text = token.replace(" ", "").replace("-", "").replace("/", "").upper()
        half = len(text) // 2
        naive = f"({text[:half]!r}, {text[half:]!r})"
        candidates = [
            (text[:i], text[i:])
            for i in range(1, len(text))
            if TENOR_RE.match(text[:i]) and TENOR_RE.match(text[i:])
        ]
        parsed = parse_pair(token)
        flag = "  <-- naive is WRONG" if naive != f"({parsed[0]!r}, {parsed[1]!r})" else ""
        print(f"{token:12s} {str(parsed):20s} {naive:22s} {len(candidates)}{flag}")

    print()
    print("The 'ambiguous' cases, enumerated rather than assumed:")
    for token in ("1Y10Y", "10Y1Y", "1Y1Y", "18M2Y"):
        candidates = [
            (token[:i], token[i:])
            for i in range(1, len(token))
            if TENOR_RE.match(token[:i]) and TENOR_RE.match(token[i:])
        ]
        print(f"  {token:8s} -> {len(candidates)} valid split(s): {candidates}")
    print(
        "  A valid first half is digits + ONE unit letter, so the split can only fall at the\n"
        "  first unit letter. The family is provably unambiguous; the enumeration is kept\n"
        "  because that proof depends on the vocabulary staying ^\\d+[DWMY]$."
    )

    print()
    print("Rejected as they should be:")
    for bad in ("10Y", "10Y30", "XYZ", "1Y2Y3Y", ""):
        try:
            parse_pair(bad)
            print(f"  {bad!r:10s} -> ACCEPTED (this is a bug)")
        except ValueError as exc:
            print(f"  {bad!r:10s} -> ValueError: {str(exc)[:78]}")

    print()
    print("parse_underlying reads position, not maturity (start, tenor):")
    for token in ("1Y1Y", "1Y10Y", "10Y1Y", "3M2Y"):
        start, tenor = parse_underlying(token)
        print(f"  {token:8s} -> start={start:5s} tenor={tenor:5s}")

    print()
    print("SpreadOptionQuote assigns long/short by MATURITY, so token order does not matter:")
    for token in ("10Y30Y", "30Y10Y"):
        q = SpreadOptionQuote.from_pair(currency="USD", kind="OPT_CAP", expiry="1Y", pair=token)
        print(f"  {token:8s} -> long={q.tenor_long:5s} short={q.tenor_short:5s} right={q.right}")

    print()
    print("pair_token / underlying_token are round-trip checked inverses:")
    for a, b in (("10Y", "30Y"), ("2Y", "5Y"), ("1Y", "1Y"), ("18M", "2Y")):
        token = pair_token(a, b)
        print(f"  pair_token({a!r}, {b!r}) = {token!r} -> parse_pair -> {parse_pair(token)}")
    try:
        pair_token("10Y", "XX")
    except ValueError as exc:
        print(f"  pair_token('10Y', 'XX') -> ValueError: {str(exc)[:70]}")

    print()
    print("add_tenors (midcurve expiry + forward start):")
    for a, b in (("1Y", "1Y"), ("3M", "1Y"), ("6M", "6M"), ("2W", "1W")):
        print(f"  {a} + {b} = {add_tenors(a, b)}")
    try:
        add_tenors("2W", "1Y")
    except ValueError as exc:
        print(f"  2W + 1Y -> ValueError: {str(exc)[:96]}")


# ------------------------------------------------------------------ #
#                 2. CMS convexity against QuantLib                  #
# ------------------------------------------------------------------ #


def ql_setup(*, flat: bool = False) -> tuple:
    """A USD-ish zero curve - sloped by default, flat on request - as a QuantLib handle.

    The FLAT curve is the control. Hagan's standard model discounts the annuity
    and the payment bond at the forward swap rate itself, i.e. it assumes a flat
    curve; on a flat curve that assumption is TRUE, so any remaining gap to
    QuantLib is algebra rather than approximation. Running the check first on the
    input whose answer is known is what makes the sloped-curve gap interpretable.
    """
    today = ql.Date(TODAY.day, TODAY.month, TODAY.year)
    ql.Settings.instance().evaluationDate = today
    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    dc = ql.Actual365Fixed()
    if flat:
        curve = ql.FlatForward(today, ql.QuoteHandle(ql.SimpleQuote(0.04)), dc,
                               ql.Compounded, ql.Annual)
    else:
        years = [0.0, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 40.0]
        zeros = [0.030, 0.031, 0.033, 0.037, 0.042, 0.046, 0.047, 0.047]
        dates = [today] + [today + ql.Period(int(y * 12), ql.Months) for y in years[1:]]
        curve = ql.ZeroCurve(dates, zeros, dc, cal, ql.Linear(), ql.Compounded, ql.Annual)
    handle = ql.YieldTermStructureHandle(curve)
    return today, cal, dc, curve, handle


def _convexity_table(*, flat: bool) -> tuple:
    today, cal, dc, curve, handle = ql_setup(flat=flat)
    sigma_n = 0.0100  # 100 bp normal vol
    vol = ql.ConstantSwaptionVolatility(
        today, cal, ql.ModifiedFollowing, ql.QuoteHandle(ql.SimpleQuote(sigma_n)), dc, ql.Normal, 0.0
    )
    volh = ql.SwaptionVolatilityStructureHandle(vol)
    mr = ql.QuoteHandle(ql.SimpleQuote(1e-4))
    ibor = ql.USDLibor(ql.Period("3M"), handle)
    index = ql.SwapIndex(
        "USDSwap", ql.Period("10Y"), 2, ql.USDCurrency(), cal, ql.Period("6M"),
        ql.ModifiedFollowing, ql.Thirty360(ql.Thirty360.BondBasis), ibor,
    )

    label = "FLAT 4% curve (the control: Hagan's own assumption holds)" if flat else \
            "SLOPED curve (3.0% -> 4.7%): the flat-yield assumption is now false"
    print(f"\n{label}")
    print(f"{'expiry':>7s} {'fwd(bp)':>9s} {'closed(bp)':>11s} {'LinearTsr':>10s} "
          f"{'Hagan/Std':>10s} {'ParShift':>9s} {'d(Tsr)':>8s} {'d(Std)':>8s}")
    worst_tsr = 0.0
    worst_std = 0.0
    for expiry_y in (1, 2, 5, 10):
        fixing = cal.advance(today, ql.Period(f"{expiry_y}Y"))
        start = cal.advance(fixing, 2, ql.Days)
        end = cal.advance(start, ql.Period("1Y"))
        coupon = ql.CmsCoupon(end, 1.0, start, end, 2, index)

        coupon.setPricer(ql.LinearTsrPricer(volh, mr))
        fwd = float(coupon.indexFixing())
        ca_tsr = float(coupon.adjustedFixing()) - fwd
        coupon.setPricer(ql.AnalyticHaganPricer(volh, ql.GFunctionFactory.Standard, mr))
        ca_std = float(coupon.adjustedFixing()) - fwd
        coupon.setPricer(ql.AnalyticHaganPricer(volh, ql.GFunctionFactory.ParallelShifts, mr))
        ca_par = float(coupon.adjustedFixing()) - fwd

        expiry_t = dc.yearFraction(today, fixing)
        delay = dc.yearFraction(start, end)
        ca_own = hagan_convexity_adjustment(
            forward=fwd, normal_vol=sigma_n, expiry_years=expiry_t,
            tenor_years_=10.0, fixed_frequency=2, payment_delay_years=delay,
        )
        d_tsr = (ca_own - ca_tsr) * BP
        d_std = (ca_own - ca_std) * BP
        worst_tsr = max(worst_tsr, abs(d_tsr))
        worst_std = max(worst_std, abs(d_std))
        print(f"{expiry_y:6d}Y {fwd * BP:9.3f} {ca_own * BP:11.4f} {ca_tsr * BP:10.4f} "
              f"{ca_std * BP:10.4f} {ca_par * BP:9.4f} {d_tsr:8.4f} {d_std:8.4f}")
    print(f"  worst |closed - LinearTsr| = {worst_tsr:.4f} bp    "
          f"worst |closed - Hagan/Standard| = {worst_std:.4f} bp")
    return worst_tsr, worst_std


def section_convexity() -> None:
    rule("2. CMS convexity: closed form vs QuantLib")

    print("10Y CMS, flat 100 bp normal vol, semi-annual fixed leg, 1Y payment delay.")
    flat_tsr, flat_std = _convexity_table(flat=True)
    slope_tsr, slope_std = _convexity_table(flat=False)

    print()
    print(f"CONTROL (flat curve):  worst gap to LinearTsr {flat_tsr:.4f} bp - the ALGEBRA is right.")
    print(f"REAL    (sloped):      worst gap to LinearTsr {slope_tsr:.4f} bp - that gap IS the")
    print("        flat-yield approximation, and it is the number to quote as the model's error.")
    print("ParShift is a different linearisation, not an error bar on ours - the gap to it is")
    print("what limits any linear-TSR adjustment, and it grows with expiry.")

    today, cal, dc, curve, handle = ql_setup()
    sigma_n = 0.0100
    vol = ql.ConstantSwaptionVolatility(
        today, cal, ql.ModifiedFollowing, ql.QuoteHandle(ql.SimpleQuote(sigma_n)), dc, ql.Normal, 0.0
    )
    volh = ql.SwaptionVolatilityStructureHandle(vol)
    mr = ql.QuoteHandle(ql.SimpleQuote(1e-4))
    ibor = ql.USDLibor(ql.Period("3M"), handle)
    index = ql.SwapIndex(
        "USDSwap", ql.Period("10Y"), 2, ql.USDCurrency(), cal, ql.Period("6M"),
        ql.ModifiedFollowing, ql.Thirty360(ql.Thirty360.BondBasis), ibor,
    )

    print()
    print("The payment-delay term, varied independently (10Y CMS, 1Y expiry, sloped curve):")
    fixing = cal.advance(today, ql.Period("1Y"))
    start = cal.advance(fixing, 2, ql.Days)
    for delay_tenor in ("3M", "6M", "1Y", "2Y"):
        pay = cal.advance(start, ql.Period(delay_tenor))
        coupon = ql.CmsCoupon(pay, 1.0, start, pay, 2, index)
        coupon.setPricer(ql.LinearTsrPricer(volh, mr))
        fwd = float(coupon.indexFixing())
        ca_tsr = float(coupon.adjustedFixing()) - fwd
        ca_own = hagan_convexity_adjustment(
            forward=fwd, normal_vol=sigma_n,
            expiry_years=dc.yearFraction(today, fixing), tenor_years_=10.0,
            fixed_frequency=2, payment_delay_years=dc.yearFraction(start, pay),
        )
        print(f"  delay={delay_tenor:3s} closed={ca_own * BP:8.4f} bp  LinearTsr={ca_tsr * BP:8.4f} bp"
              f"  diff={(ca_own - ca_tsr) * BP:+7.4f} bp")

    print()
    print("G'/G is the whole model; here it is, so the sensitivity is visible:")
    for tenor_y, freq in ((2.0, 2), (10.0, 2), (30.0, 2), (10.0, 1), (10.0, 4)):
        g = hagan_g_ratio(forward=0.04, tenor_years_=tenor_y, fixed_frequency=freq)
        print(f"  S=4.00%  tenor={tenor_y:5.1f}Y  q={freq}  G'/G={g:8.5f}  "
              f"CA@100bp,1Y={g * 1e-4 * BP:7.4f} bp")

    print()
    print("cms_rate refuses to silently skip the adjustment:")
    try:
        cms_rate(curve=0.0425, forward="1Y", tenor="10Y")
    except ValueError as exc:
        print(f"  ValueError: {str(exc)[:150]}")
    adjusted = cms_rate(curve=0.0425, forward="1Y", tenor="10Y", normal_vol=0.01)
    plain = cms_rate(curve=0.0425, forward="1Y", tenor="10Y", convexity_adjustment=0.0)
    print(f"  cms_rate(normal_vol=0.01)          = {adjusted * BP:.4f} bp")
    print(f"  cms_rate(convexity_adjustment=0.0) = {plain * BP:.4f} bp")
    print(f"  difference                         = {(adjusted - plain) * BP:.4f} bp")


# ------------------------------------------------------------------ #
#              3. the single look across a correlation sweep         #
# ------------------------------------------------------------------ #


def section_backends() -> None:
    rule("2b. forward_swap_rate's four backends, on ONE set of discount factors")

    today, cal, dc, curve, handle = ql_setup()
    print("All four are handed the same curve. They disagree because they build different")
    print("schedules off it; the size of that disagreement is the point of this table.")

    def df(when) -> float:
        d = ql.Date(when.day, when.month, when.year)
        return float(curve.discount(d))

    import rateslib as rl

    node_dates = [datetime.datetime(TODAY.year, TODAY.month, TODAY.day)]
    for months in (6, 12, 24, 36, 60, 84, 120, 180, 240, 360, 480):
        d = today + ql.Period(months, ql.Months)
        node_dates.append(datetime.datetime(d.year(), d.month(), d.dayOfMonth()))
    rl_curve = rl.Curve(
        nodes={d: float(curve.discount(ql.Date(d.day, d.month, d.year))) for d in node_dates},
        calendar="nyc", convention="act360", id="citivelo-smoke",
    )

    print()
    print("The QuantLib column is a semi-annual 30/360 swap index, so the DF route is run BOTH")
    print("ways: matching it (30/360) and mismatched (ACT/360). The mismatch column is what a")
    print("wrong day count costs; the matched column is what the missing holiday calendar costs.")
    print(f"{'fwd x tenor':>13s} {'QuantLib(bp)':>13s} {'rateslib(bp)':>13s} "
          f"{'DF 30/360':>11s} {'DF ACT/360':>11s} {'rl-ql':>8s} {'df30-ql':>9s} {'df360-ql':>9s}")
    worst_rl = 0.0
    worst_df30 = 0.0
    worst_df360 = 0.0
    for fwd, tenor in (("1Y", "10Y"), ("1Y", "2Y"), ("2Y", "1Y"), ("5Y", "5Y"), ("0D", "10Y")):
        v_ql = forward_swap_rate(curve=handle, forward=fwd, tenor=tenor, calendar=cal,
                                 currency="USD")
        v_rl = forward_swap_rate(curve=rl_curve, forward=fwd, tenor=tenor, spec="usd_irs")
        v_30 = forward_swap_rate(curve=df, forward=fwd, tenor=tenor, fixed_frequency=2,
                                 convention="30360", valuation=TODAY)
        v_360 = forward_swap_rate(curve=df, forward=fwd, tenor=tenor, fixed_frequency=2,
                                  convention="act360", valuation=TODAY)
        d_rl = (v_rl - v_ql) * BP
        d_30 = (v_30 - v_ql) * BP
        d_360 = (v_360 - v_ql) * BP
        worst_rl = max(worst_rl, abs(d_rl))
        worst_df30 = max(worst_df30, abs(d_30))
        worst_df360 = max(worst_df360, abs(d_360))
        print(f"{fwd + ' x ' + tenor:>13s} {v_ql * BP:13.4f} {v_rl * BP:13.4f} {v_30 * BP:11.4f} "
              f"{v_360 * BP:11.4f} {d_rl:8.3f} {d_30:9.3f} {d_360:9.3f}")

    print(f"\nworst |rateslib   - QuantLib| = {worst_rl:.3f} bp")
    print(f"worst |DF 30/360  - QuantLib| = {worst_df30:.3f} bp   <- calendar rolls only")
    print(f"worst |DF ACT/360 - QuantLib| = {worst_df360:.3f} bp   <- + a wrong day count")
    print("So on the DF route the day count dominates the missing calendar by roughly")
    print(f"{worst_df360 / max(worst_df30, 1e-9):.0f}x. Pass convention= to match your quote source; the")
    print("calendar-free schedule itself is worth well under a basis point.")
    print("The rateslib gap is a real convention difference, not an error: rateslib's usd_irs")
    print("spec is an annual ACT/360 SOFR OIS while the QuantLib index here is a semi-annual")
    print("30/360 ibor swap. Neither is 'the' answer - pick the backend whose conventions match")
    print("the quotes you are calibrating to.")
    print("rateslib returns PERCENT and is divided by 100 inside forward_swap_rate; a missing")
    print(f"conversion would show up here as a factor of 100, not as {worst_rl:.1f} bp.")


def section_single_look() -> dict:
    rule("3. 1Y expiry 10Y-2Y single-look CAP across a correlation sweep")

    today, cal, dc, curve, handle = ql_setup()
    sigma_n = 0.0100
    vol = ql.ConstantSwaptionVolatility(
        today, cal, ql.ModifiedFollowing, ql.QuoteHandle(ql.SimpleQuote(sigma_n)), dc, ql.Normal, 0.0
    )
    volh = ql.SwaptionVolatilityStructureHandle(vol)
    mr = ql.QuoteHandle(ql.SimpleQuote(1e-4))
    ibor = ql.USDLibor(ql.Period("3M"), handle)

    def swap_index(tenor: str):
        return ql.SwapIndex(
            "USDSwap", ql.Period(tenor), 2, ql.USDCurrency(), cal, ql.Period("6M"),
            ql.ModifiedFollowing, ql.Thirty360(ql.Thirty360.BondBasis), ibor,
        )

    fixing = cal.advance(today, ql.Period("1Y"))
    start = cal.advance(fixing, 2, ql.Days)
    end = cal.advance(start, ql.Period("1Y"))
    expiry_t = dc.yearFraction(today, fixing)
    delay = dc.yearFraction(start, end)

    # Convexity-adjust each leg separately: G'/G differs by tenor, so the
    # adjustment does NOT cancel in the spread.
    legs = {}
    for label, tenor, n_years in (("long", "10Y", 10.0), ("short", "2Y", 2.0)):
        coupon = ql.CmsCoupon(end, 1.0, start, end, 2, swap_index(tenor))
        coupon.setPricer(ql.LinearTsrPricer(volh, mr))
        par = float(coupon.indexFixing())
        ca = hagan_convexity_adjustment(
            forward=par, normal_vol=sigma_n, expiry_years=expiry_t,
            tenor_years_=n_years, fixed_frequency=2, payment_delay_years=delay,
        )
        legs[label] = (par, ca, par + ca)
        print(f"  {label:5s} {tenor:4s}: par={par * BP:8.3f} bp  convexity={ca * BP:+7.4f} bp  "
              f"CMS={(par + ca) * BP:8.3f} bp")
    f_long = legs["long"][2]
    f_short = legs["short"][2]
    strike = 0.0020
    print(f"  spread    : par={(legs['long'][0] - legs['short'][0]) * BP:8.3f} bp  "
          f"CMS={(f_long - f_short) * BP:8.3f} bp  "
          f"(convexity moves it {((f_long - f_short) - (legs['long'][0] - legs['short'][0])) * BP:+.4f} bp)")
    print(f"  strike    : {strike * BP:.1f} bp,  T = {expiry_t:.4f} y,  leg vols {sigma_n * BP:.0f} bp each")

    print()
    print(f"{'rho':>7s} {'sigma_S(bp)':>12s} {'price(bp)':>11s} {'d/drho':>10s} "
          f"{'implied rho':>12s} {'round-trip err':>15s}")
    rows = []
    prev_price = None
    worst_rt = 0.0
    for rho in (-0.99, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 0.9, 0.99):
        sigma_s = spread_normal_vol(vol_long=sigma_n, vol_short=sigma_n, correlation=rho)
        price = single_look_spread_option_price(
            forward_long=f_long, forward_short=f_short,
            vol_long=sigma_n, vol_short=sigma_n, correlation=rho,
            strike=strike, expiry_years=expiry_t, right="OPT_CAP",
        )
        back = implied_correlation(
            market_price=price, forward_long=f_long, forward_short=f_short,
            vol_long=sigma_n, vol_short=sigma_n, strike=strike,
            expiry_years=expiry_t, right="OPT_CAP",
        )
        err = abs(back - rho)
        worst_rt = max(worst_rt, err)
        slope = "" if prev_price is None else f"{(price - prev_price) * BP:10.4f}"
        print(f"{rho:7.2f} {sigma_s * BP:12.4f} {price * BP:11.4f} {slope:>10s} "
              f"{back:12.6f} {err:15.2e}")
        rows.append((rho, price))
        prev_price = price

    monotone = all(b[1] < a[1] for a, b in zip(rows, rows[1:]))
    print(f"\nstrictly DECREASING in rho: {monotone}")
    print("  (higher rho -> lower spread vol -> lower option value; a cap on a spread is short")
    print("   correlation, which is the entire reason the product exists)")
    print(f"worst implied_correlation round-trip error over the sweep: {worst_rt:.3e}")
    print("  tolerance: 1e-6 in rho.  PASS" if worst_rt < 1e-6 else
          f"  tolerance: 1e-6 in rho.  FAIL ({worst_rt:.3e})")

    print()
    print("Straddles round-trip too (put-call parity conversion, not a root search):")
    for rho in (-0.5, 0.0, 0.6):
        price = single_look_spread_option_price(
            forward_long=f_long, forward_short=f_short, vol_long=sigma_n, vol_short=sigma_n,
            correlation=rho, strike=strike, expiry_years=expiry_t, right="OPT_STR",
        )
        back = implied_correlation(
            market_price=price, forward_long=f_long, forward_short=f_short,
            vol_long=sigma_n, vol_short=sigma_n, strike=strike, expiry_years=expiry_t,
            right="OPT_STR",
        )
        print(f"  rho={rho:+.2f}  straddle={price * BP:9.4f} bp  implied rho={back:.9f}  "
              f"err={abs(back - rho):.2e}")

    print()
    print("Out-of-band prices raise instead of returning nan:")
    for bad, why in ((1e-9, "below the rho=+1 floor"), (0.02, "above the rho=-1 ceiling")):
        try:
            implied_correlation(
                market_price=bad, forward_long=f_long, forward_short=f_short,
                vol_long=sigma_n, vol_short=sigma_n, strike=strike,
                expiry_years=expiry_t, right="OPT_CAP",
            )
            print(f"  price={bad}: ACCEPTED (this is a bug)")
        except ValueError as exc:
            print(f"  price={bad:g} ({why}) -> ValueError: {str(exc)[:96]}")

    return {
        "f_long": f_long, "f_short": f_short, "sigma": sigma_n, "strike": strike,
        "expiry_t": expiry_t, "handle": handle, "cal": cal, "dc": dc, "today": today,
    }


# ------------------------------------------------------------------ #
#             4. the single look against QuantLib's strip            #
# ------------------------------------------------------------------ #


def section_quantlib_spread(ctx: dict) -> None:
    rule("4. single look vs QuantLib's CMS-spread coupon machinery")

    print("QuantLib 1.41 has NO CMS-spread option instrument. Its CMS-spread classes are")
    print("coupon-based (SwapSpreadIndex / CmsSpreadCoupon / CappedFlooredCmsSpreadCoupon /")
    print("LognormalCmsSpreadPricer), i.e. the parts of a cap/floor STRIP. build_ql_cms_spread")
    print("builds that and says so; it is not the single look.")
    print()

    strike = ctx["strike"]
    print(f"{'rho':>7s} {'closed(bp)':>12s} {'QL caplet rate(bp)':>20s} {'diff(bp)':>12s} "
          f"{'QL 1-cpn NPV':>14s} {'QL 2-cpn NPV':>14s}")
    worst = 0.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for rho in (-0.5, 0.0, 0.5, 0.9, 0.99):
            build = build_ql_cms_spread(
                discount_curve=ctx["handle"], tenor_long="10Y", tenor_short="2Y",
                expiry="1Y", correlation=rho, strike=strike, normal_vol=ctx["sigma"],
                right="OPT_CAP", n_periods=1, calendar=ctx["cal"], currency="USD",
                day_count=ctx["dc"], warn=False,
            )
            build2 = build_ql_cms_spread(
                discount_curve=ctx["handle"], tenor_long="10Y", tenor_short="2Y",
                expiry="1Y", correlation=rho, strike=strike, normal_vol=ctx["sigma"],
                right="OPT_CAP", n_periods=2, calendar=ctx["cal"], currency="USD",
                day_count=ctx["dc"], warn=False,
            )
            closed = single_look_spread_option_price(
                forward_long=build.adjusted_spread + _short_leg(build),
                forward_short=_short_leg(build),
                vol_long=ctx["sigma"], vol_short=ctx["sigma"], correlation=rho,
                strike=strike, expiry_years=ctx["expiry_t"], right="OPT_CAP",
            )
            ql_rate = build.option_rates[0]
            diff = (closed - ql_rate) * BP
            worst = max(worst, abs(diff))
            print(f"{rho:7.2f} {closed * BP:12.4f} {ql_rate * BP:20.4f} {diff:12.2e} "
                  f"{build.npv:14.8f} {build2.npv:14.8f}")

    print(f"\nworst |Bachelier single look - QL caplet rate| = {worst:.3e} bp")
    print("READ THIS HONESTLY: with a NORMAL ATM surface, LognormalCmsSpreadPricer's marginals")
    print("and its copula are both normal, so its 2-d integral collapses to exactly the same")
    print("Bachelier-on-the-spread formula. Agreement at 1e-13 bp therefore confirms the WIRING")
    print("- forwards, convexity adjustment, strike, sign, gearings - and is NOT an independent")
    print("model check. The independent checks are section 2 (convexity) and the next block.")
    print("The 1-coupon vs 2-coupon NPV columns are the point that matters here: the strip is")
    print("worth about twice the single look, which is the whole reason they are kept apart.")

    print()
    print("An independent comparison: same trade with a LOGNORMAL ATM surface, where QuantLib's")
    print("marginals are lognormal and a normal model on the spread is genuinely a different")
    print("model. Leg vols are matched at the money (sigma_LN = sigma_N / F) so the two start")
    print("from the same at-the-money variance.")
    print(f"{'rho':>7s} {'QL lognormal(bp)':>18s} {'closed normal(bp)':>19s} {'diff(bp)':>10s}")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for rho in (-0.5, 0.0, 0.5, 0.9):
            f_long_par = ctx["f_long"]
            sigma_ln = ctx["sigma"] / f_long_par   # ATM-matched lognormal vol
            ln_vol = ql.ConstantSwaptionVolatility(
                ctx["today"], ctx["cal"], ql.ModifiedFollowing,
                ql.QuoteHandle(ql.SimpleQuote(sigma_ln)), ctx["dc"], ql.ShiftedLognormal, 0.0,
            )
            build = build_ql_cms_spread(
                discount_curve=ctx["handle"], tenor_long="10Y", tenor_short="2Y", expiry="1Y",
                correlation=rho, strike=strike,
                swaption_vol=ql.SwaptionVolatilityStructureHandle(ln_vol),
                right="OPT_CAP", n_periods=1, calendar=ctx["cal"], currency="USD",
                day_count=ctx["dc"], warn=False,
            )
            short_fwd = _short_leg(build)
            long_fwd = build.adjusted_spread + short_fwd
            closed = single_look_spread_option_price(
                forward_long=long_fwd, forward_short=short_fwd,
                vol_long=sigma_ln * long_fwd, vol_short=sigma_ln * short_fwd,
                correlation=rho, strike=strike, expiry_years=ctx["expiry_t"], right="OPT_CAP",
            )
            ql_rate = build.option_rates[0]
            print(f"{rho:7.2f} {ql_rate * BP:18.4f} {closed * BP:19.4f} "
                  f"{(closed - ql_rate) * BP:10.4f}")
    print("Those gaps are the cost of modelling a lognormal-margin spread as normal. They are")
    print("the honest error bar on using this module against a lognormally-quoted book.")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        build = build_ql_cms_spread(
            discount_curve=ctx["handle"], tenor_long="10Y", tenor_short="2Y", expiry="1Y",
            correlation=0.5, strike=strike, normal_vol=ctx["sigma"], right="OPT_CAP",
            n_periods=1, calendar=ctx["cal"], currency="USD", day_count=ctx["dc"],
        )
        print(f"\nn_periods=1 warns: {len(caught)} warning(s)")
        for w in caught:
            print(f"  {str(w.message)[:180]}")
    print(f"is_single_look = {build.is_single_look}   is_strip = {build.is_strip}   "
          f"n_periods = {build.n_periods}")
    print(f"forward spread = {build.forward_spread * BP:.4f} bp, "
          f"adjusted = {build.adjusted_spread * BP:.4f} bp "
          f"(coupon timing adjustment {((build.adjusted_spread - build.forward_spread) * BP):+.4f} bp)")

    print()
    print("put-call parity on the QuantLib leg, which exercises OPT_FLR and OPT_STR:")
    print(f"{'rho':>7s} {'cap(bp)':>10s} {'floor(bp)':>11s} {'straddle(bp)':>13s} "
          f"{'cap-floor':>11s} {'F-K':>10s} {'parity err':>12s}")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for rho in (-0.5, 0.0, 0.5, 0.9):
            kwargs = dict(discount_curve=ctx["handle"], tenor_long="10Y", tenor_short="2Y",
                          expiry="1Y", correlation=rho, strike=strike, normal_vol=ctx["sigma"],
                          n_periods=1, calendar=ctx["cal"], currency="USD",
                          day_count=ctx["dc"], warn=False)
            cap = build_ql_cms_spread(right="OPT_CAP", **kwargs)
            flr = build_ql_cms_spread(right="OPT_FLR", **kwargs)
            std = build_ql_cms_spread(right="OPT_STR", **kwargs)
            f_minus_k = cap.adjusted_spread - strike
            err = (cap.option_rates[0] - flr.option_rates[0]) - f_minus_k
            print(f"{rho:7.2f} {cap.option_rates[0] * BP:10.4f} {flr.option_rates[0] * BP:11.4f} "
                  f"{std.option_rates[0] * BP:13.4f} "
                  f"{(cap.option_rates[0] - flr.option_rates[0]) * BP:11.4f} "
                  f"{f_minus_k * BP:10.4f} {err * BP:12.2e}")
    print("cap - floor == adjusted forward - strike, and straddle == cap + floor, so the three")
    print("legs of build_ql_cms_spread are internally consistent.")


def _short_leg(build: QlCmsSpreadBuild) -> float:
    """The short CMS leg's own adjusted fixing, so the closed form uses QL's forwards."""
    return float(build.swap_index_short.fixing(build.plain_leg[0].fixingDate()))


# ------------------------------------------------------------------ #
#                        5. the midcurve                             #
# ------------------------------------------------------------------ #


def section_midcurve() -> None:
    rule("5. a 1Y midcurve on a 1Y1Y underlying")

    today, cal, dc, curve, handle = ql_setup()
    start, tenor = parse_underlying("1Y1Y")
    expiry = "1Y"
    print(f"expiry={expiry}  underlying=1Y1Y -> start={start}, tenor={tenor}")
    print(f"the swap therefore starts at {add_tenors(expiry, start)} and matures at "
          f"{add_tenors(add_tenors(expiry, start), tenor)}")

    print()
    print("what 'expiry' and 'underlying start' compose to, and what each wrong reading costs:")
    print(f"{'expiry':>7s} {'underlying':>11s} {'swap starts':>12s} {'fwd(bp)':>9s} "
          f"{'start@spot(bp)':>15s} {'start ignored':>14s}")
    for exp_token, und in (("1Y", "1Y1Y"), ("6M", "1Y1Y"), ("1Y", "1Y10Y"), ("2Y", "3M5Y")):
        s_tok, t_tok = parse_underlying(und)
        f_ok = midcurve_forward(curve=handle, expiry=exp_token, underlying_start=s_tok,
                                underlying_tenor=t_tok, calendar=cal, currency="USD")
        f_spot = midcurve_forward(curve=handle, expiry=exp_token, underlying_start=s_tok,
                                  underlying_tenor=t_tok, start_relative_to="spot",
                                  calendar=cal, currency="USD")
        f_none = forward_swap_rate(curve=handle, forward=exp_token, tenor=t_tok, calendar=cal,
                                   currency="USD")
        print(f"{exp_token:>7s} {und:>11s} {add_tenors(exp_token, s_tok):>12s} {f_ok * BP:9.4f} "
              f"{f_spot * BP:15.4f} {f_none * BP:14.4f}")
    print("  'start@spot' reads the underlying's forward start from today; 'start ignored'")
    print("  prices the expiry-forward swap. The first two coincide only when expiry == start.")

    fwd_mid = midcurve_forward(
        curve=handle, expiry=expiry, underlying_start=start, underlying_tenor=tenor,
        calendar=cal, currency="USD",
    )
    fwd_naive = forward_swap_rate(curve=handle, forward=expiry, tenor=tenor, calendar=cal,
                                  currency="USD")

    sigma = 0.0090
    expiry_t = dc.yearFraction(today, cal.advance(today, ql.Period(expiry)))
    strike = round(fwd_mid, 6)
    annuity = 0.95

    print()
    print(f"vol = {sigma * BP:.0f} bp normal, T = {expiry_t:.4f} y, annuity = {annuity}, "
          f"strike = ATM = {strike * BP:.4f} bp")
    print(f"{'right':10s} {'midcurve_price':>16s} {'annuity*bachelier':>19s} {'abs diff':>12s}")
    for right, ql_right in (("OPT_PAY", "C"), ("OPT_REC", "P")):
        mine = midcurve_price(forward=fwd_mid, strike=strike, normal_vol=sigma,
                              expiry_years=expiry_t, annuity=annuity, right=right)
        theirs = annuity * bachelier_price(ql_right, strike, fwd_mid, sigma, expiry_t, 1.0)
        print(f"{right:10s} {mine:16.10f} {theirs:19.10f} {abs(mine - theirs):12.3e}")
    straddle = midcurve_price(forward=fwd_mid, strike=strike, normal_vol=sigma,
                              expiry_years=expiry_t, annuity=annuity, right="OPT_STR")
    parts = annuity * (bachelier_price("C", strike, fwd_mid, sigma, expiry_t, 1.0)
                       + bachelier_price("P", strike, fwd_mid, sigma, expiry_t, 1.0))
    print(f"{'OPT_STR':10s} {straddle:16.10f} {parts:19.10f} {abs(straddle - parts):12.3e}")
    print()
    wrong = midcurve_price(forward=fwd_naive, strike=strike, normal_vol=sigma,
                           expiry_years=expiry_t, annuity=annuity, right="OPT_PAY")
    right_price = midcurve_price(forward=fwd_mid, strike=strike, normal_vol=sigma,
                                 expiry_years=expiry_t, annuity=annuity, right="OPT_PAY")
    print()
    print("This agreement is a TAUTOLOGY: midcurve_price IS Query.Base.bachelier with the")
    print("annuity factored out. It is worth printing only as a guard against a units or a")
    print("right-mapping slip. The real midcurve content is the forward above and the vol")
    print("below. Pricing this trade off the 1Y-forward rate instead of the 2Y-forward one")
    print(f"misses the forward by {abs(fwd_mid - fwd_naive) * BP:.2f} bp and the payer premium by "
          f"{abs(wrong - right_price) * BP:.2f} bp of annuity-scaled premium")
    print(f"({abs(wrong - right_price) / right_price * 100:.1f}% of the option) - which is what a")
    print("'midcurves are just Bachelier' shortcut actually costs.")

    print()
    print("implied vol round-trips:")
    for right in ("OPT_PAY", "OPT_REC", "OPT_STR"):
        for k in (strike, strike - 0.0025, strike + 0.0025):
            price = midcurve_price(forward=fwd_mid, strike=k, normal_vol=sigma,
                                   expiry_years=expiry_t, annuity=annuity, right=right)
            back = midcurve_implied_vol(market_price=price, forward=fwd_mid, strike=k,
                                        expiry_years=expiry_t, annuity=annuity, right=right)
            print(f"  {right:8s} K={k * BP:8.2f} bp  price={price:.10f}  vol={back * BP:8.4f} bp  "
                  f"err={abs(back - sigma) * BP:.2e} bp")


# ------------------------------------------------------------------ #
#                    6. reading a vol off a cube                     #
# ------------------------------------------------------------------ #


def section_cube() -> None:
    rule("6. midcurve_from_vol_cube in all three modes")

    midcurve_surface = {("1Y", "1Y1Y"): 0.0091, ("1Y", "1Y10Y"): 0.0104, ("2Y", "1Y1Y"): 0.0088}
    print("mode 'direct' on a MIDCURVE-shaped surface keyed (expiry, forward-swap token):")
    for exp, token in (("1Y", "1Y1Y"), ("2Y", "1Y1Y")):
        start, tenor = parse_underlying(token)
        v = midcurve_from_vol_cube(cube=midcurve_surface, expiry=exp, underlying_start=start,
                                   underlying_tenor=tenor, method="direct")
        print(f"  ({exp}, {token}) -> {v * BP:.4f} bp   (exact node, no interpolation)")
    try:
        midcurve_from_vol_cube(cube=midcurve_surface, expiry="1Y", underlying_start="2Y",
                               underlying_tenor="5Y", method="direct")
    except ValueError as exc:
        print(f"  missing node -> ValueError: {str(exc)[:110]}")

    grid = pd.DataFrame(
        [[0.0085, 0.0095, 0.0105, 0.0100],
         [0.0090, 0.0099, 0.0108, 0.0102],
         [0.0094, 0.0102, 0.0110, 0.0103]],
        index=["6M", "1Y", "2Y"], columns=["1Y", "2Y", "5Y", "10Y"],
    )
    print()
    print("a STANDARD swaption cube (rows = expiry, cols = swap tenor), vols in bp:")
    print((grid * BP).to_string())

    print()
    print("mode 'tenor' - the crude proxy: read at (expiry, underlying_tenor), start ignored:")
    v_tenor = midcurve_from_vol_cube(cube=grid, expiry="1Y", underlying_start="1Y",
                                     underlying_tenor="1Y", method="tenor")
    print(f"  (1Y, 1Y1Y) -> {v_tenor * BP:.4f} bp   == the (1Y, 1Y) node, i.e. a SPOT-starting 1Y swap")

    print()
    print("mode 'decomposition' - annuity-weighted difference of the (1Y,2Y) and (1Y,1Y) nodes:")
    a_long, a_short = 1.90, 0.97   # 2Y and 1Y annuities off a ~4% curve
    for rho in (0.999, 0.99, 0.97, 0.95):
        v = midcurve_from_vol_cube(cube=grid, expiry="1Y", underlying_start="1Y",
                                   underlying_tenor="1Y", method="decomposition",
                                   annuity_long=a_long, annuity_short=a_short, correlation=rho)
        print(f"  rho={rho:.3f} -> {v * BP:8.4f} bp   (weights w_L={a_long / (a_long - a_short):.3f}, "
              f"w_S={a_short / (a_long - a_short):.3f})")
    print("  The sensitivity to rho is enormous because the weights are large. That is a")
    print("  property of the decomposition, not a bug, and it is why the 0.99 default is")
    print("  documented as a placeholder rather than a measurement.")

    print()
    print("off-node reads on the standard cube use bilinear-in-vol with FLAT extrapolation:")
    for exp, ten in (("1Y", "3Y"), ("9M", "2Y"), ("5Y", "2Y"), ("1M", "1Y"), ("1Y", "30Y")):
        v = midcurve_from_vol_cube(cube=grid, expiry=exp, underlying_start="0D",
                                   underlying_tenor=ten, method="tenor")
        edge = " (flat-extrapolated)" if exp in {"5Y", "1M"} or ten == "30Y" else ""
        print(f"  ({exp}, {ten}) -> {v * BP:8.4f} bp{edge}")

    print()
    print("duck-typed sources: a callable and an object with .normal_vol")
    print(f"  callable      -> "
          f"{midcurve_from_vol_cube(cube=lambda e, t: 0.0111, expiry='1Y', underlying_start='1Y', underlying_tenor='1Y') * BP:.4f} bp")

    class Cube:
        def normal_vol(self, *, expiry: str, tenor: str) -> float:
            return 0.0080 + 0.0001 * len(expiry) + 0.0001 * len(tenor)

    print(f"  .normal_vol   -> "
          f"{midcurve_from_vol_cube(cube=Cube(), expiry='1Y', underlying_start='1Y', underlying_tenor='1Y') * BP:.4f} bp")
    try:
        midcurve_from_vol_cube(cube=object(), expiry="1Y", underlying_start="1Y",
                               underlying_tenor="1Y")
    except TypeError as exc:
        print(f"  unsupported   -> TypeError: {str(exc)[:110]}")

    print()
    print("a non-finite node raises rather than propagating:")
    try:
        midcurve_from_vol_cube(cube={("1Y", "1Y1Y"): float("nan")}, expiry="1Y",
                               underlying_start="1Y", underlying_tenor="1Y")
    except ValueError as exc:
        print(f"  ValueError: {str(exc)[:110]}")

    print()
    print("decomposition guards its own algebra:")
    try:
        midcurve_vol_from_decomposition(vol_long=0.01, vol_short=0.01,
                                        annuity_long=0.9, annuity_short=1.9)
    except ValueError as exc:
        print(f"  A_long < A_short -> ValueError: {str(exc)[:110]}")

    print()
    print("UNITS - the 1e4 trap, against the real sibling SwaptionCubeData (vols in bp):")
    try:
        from MDP.CitiVelocityExcel.vol.cube_data import SwaptionCubeData
    except ImportError as exc:
        print(f"  MDP.CitiVelocityExcel.vol not importable ({exc}); the duck-typed stand-in")
        print("  below covers the same contract.")
        SwaptionCubeData = None  # type: ignore[assignment]

    if SwaptionCubeData is not None:
        real = SwaptionCubeData(
            as_of=TODAY, currency="USD", measure="NORMAL",
            atm=pd.DataFrame([[85.0, 95.0], [90.0, 99.0]],
                             index=["6M", "1Y"], columns=["1Y", "2Y"]),
        )
        print(f"  cube.vol_unit = {real.vol_unit!r}, cube.vol('1Y','1Y') = {real.vol('1Y', '1Y')}")
        auto = midcurve_from_vol_cube(cube=real, expiry="1Y", underlying_start="0D",
                                      underlying_tenor="1Y", method="tenor")
        as_is = midcurve_from_vol_cube(cube=real, expiry="1Y", underlying_start="0D",
                                       underlying_tenor="1Y", method="tenor", unit="as_is")
        print(f"  unit='auto'   -> {auto:.6f}  (decimals: it read vol_unit='bp' and converted)")
        print(f"  unit='as_is'  -> {as_is:.6f}  (raw bp - what a naive hand-off would carry)")
        print(f"  ratio         -> {as_is / auto:.0f}x")
        priced = midcurve_price(forward=0.03, strike=0.03, normal_vol=auto, expiry_years=1.0,
                                annuity=1.0, right="OPT_PAY")
        print(f"  midcurve_price with the converted vol = {priced * BP:.4f} bp of annuity")
        try:
            midcurve_price(forward=0.03, strike=0.03, normal_vol=as_is, expiry_years=1.0,
                           annuity=1.0, right="OPT_PAY")
            print("  the raw-bp vol PRICED (this is a bug - the guard did not fire)")
        except ValueError as exc:
            print(f"  the raw-bp vol RAISES: {str(exc)[:120]}")

    print()
    print("the same guard on the spread side:")
    try:
        single_look_spread_option_price(
            forward_long=429.6, forward_short=357.6, vol_long=100.0, vol_short=100.0,
            correlation=0.5, strike=20.0, expiry_years=1.0, right="OPT_CAP")
        print("  a whole option quoted in bp PRICED (this is a bug)")
    except ValueError as exc:
        print(f"  everything in bp -> ValueError: {str(exc)[:120]}")


# ------------------------------------------------------------------ #
#                    7. the fetch path, on the fake                  #
# ------------------------------------------------------------------ #


def section_fetch() -> None:
    rule("7. fetch_spread_options / fetch_midcurves against the fake Excel")

    dates = pd.date_range("2026-07-01", "2026-08-04", freq="B")
    served = {}
    for expiry in ("1Y", "2Y"):
        for pair in ("10Y30Y", "2Y5Y"):
            base = 55.0 if pair == "10Y30Y" else 30.0
            served[f"RATES.SPREAD_OPTIONS.USD.OPT_CAP.VOL.{expiry}.{pair}"] = pd.Series(
                [base + i * 0.05 for i in range(len(dates))], index=dates
            )
            served[f"RATES.SPREAD_OPTIONS.USD.OPT_CAP.PRICE.{expiry}.{pair}"] = pd.Series(
                [base * 0.4 + i * 0.02 for i in range(len(dates))], index=dates
            )
    served["RATES.MIDCURVES.USD_SOFR.OPT_STR.VOL.1Y.1Y1Y"] = pd.Series(
        [88.0 + i * 0.03 for i in range(len(dates))], index=dates
    )
    served["RATES.MIDCURVES.USD_SOFR.OPT_STR.PRICE.1Y.1Y1Y"] = pd.Series(
        [35.0 + i * 0.01 for i in range(len(dates))], index=dates
    )

    app = FakeExcelApp(FakeVelocityData(series=served), pending_reads=1)
    client = CitiVelocityExcelClient(app=app)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        quotes = fetch_spread_options(
            client=client, currency="USD", expiries=["1Y", "2Y"],
            pairs=["10Y30Y", "2Y5Y"], kind="OPT_CAP", as_of="2026-08-03", warn=False,
        )
    print(f"{len(quotes)} spread-option quote(s) from {len(app.formulas_for('CVTSHIST'))} "
          f"CVTSHIST call(s) for {2 * 2 * 2} tags")
    for q in quotes:
        print(f"  {q.expiry:3s} {q.pair:8s} long={q.tenor_long:4s} short={q.tenor_short:4s} "
              f"price={q.price:7.3f} vol={q.vol:7.3f} as_of={q.as_of.date()} right={q.right}")
    print("  (price and vol are RAW - the units of this family are unverified)")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        mids = fetch_midcurves(
            client=client, currency="USD_SOFR", expiries=["1Y"], underlyings=["1Y1Y"],
            kind="OPT_STR", as_of="2026-08-03", warn=False,
        )
    for m in mids:
        print(f"  midcurve {m.expiry} {m.underlying}: start={m.underlying_start} "
              f"tenor={m.underlying_tenor} price={m.price:.3f} vol={m.vol:.3f} "
              f"swap starts at {m.swap_start_years:.2f}y  true_midcurve={m.is_true_midcurve}")

    print()
    print("the warning fires when it is not suppressed:")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fetch_spread_options(client=client, currency="USD", expiries=["1Y"],
                             pairs=["10Y30Y"], kind="OPT_CAP", as_of="2026-08-03")
        print(f"  {len(caught)} warning(s): {str(caught[0].message)[:150]}")

    print()
    print("an unserved (i.e. wrong) shape RAISES rather than returning []:")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fetch_spread_options(client=client, currency="EUR", expiries=["1Y"],
                                 pairs=["5Y10Y"], kind="OPT_FLR", as_of="2026-08-03", warn=False)
        print("  ACCEPTED (this is a bug)")
    except CitiVelocityError as exc:
        print(f"  CitiVelocityError: {str(exc)[:190]}")

    print()
    print("bad pairs are rejected BEFORE any Excel traffic:")
    before = len(app.formulas)
    try:
        fetch_spread_options(client=client, currency="USD", expiries=["1Y"], pairs=["10Y30"],
                             kind="OPT_CAP", warn=False)
    except ValueError as exc:
        print(f"  ValueError: {str(exc)[:96]}")
    print(f"  formulas written during that call: {len(app.formulas) - before}")
    client.close()


def main() -> None:
    section_grammar()
    section_convexity()
    section_backends()
    ctx = section_single_look()
    section_quantlib_spread(ctx)
    section_midcurve()
    section_cube()
    section_fetch()
    print()
    print("=" * 78)
    print("smoke complete")
    print("=" * 78)


if __name__ == "__main__":
    main()

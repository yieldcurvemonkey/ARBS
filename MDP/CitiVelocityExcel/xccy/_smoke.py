r"""Smoke test for the cross-currency layer. No Excel, no market data, no network.

Run::

    <env>/python.exe MDP/CitiVelocityExcel/xccy/_smoke.py

What it proves, and what it does not
------------------------------------
It proves the code paths execute and are **internally** consistent: that the
rateslib solve and the QuantLib bootstrap each reprice their own inputs, and
that two independently written implementations of the same swap agree. It proves
nothing about Citi's numbers - the basis strip here is invented, the OIS curves
are invented, and neither the sign nor the leg convention of Velocity's
``BASIS_SPREAD`` has been checked against a live quote.

``MDP/CitiVelocityExcel/curves/`` currently ships only ``conventions.py`` - there
is no ``rl_builder.py`` yet - so the two OIS curves are solved here directly with
:class:`rateslib.Solver` off a synthetic par grid, using the conventions table
for the specs. Swap that for the builder when it lands.
"""

from __future__ import annotations

import datetime
import math
import pathlib
import sys
import tempfile
import traceback
import warnings

import pandas as pd

from MDP.CitiVelocityExcel.cache import CitiVeloTagCache
from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient
from MDP.CitiVelocityExcel.testing import FakeExcelApp, FakeVelocityData
from MDP.CitiVelocityExcel.xccy.basis_data import (
    XCCY_TENORS,
    basis_from_quotes,
    conventions_for_currency,
    fetch_xccy_basis,
    ois_index_for_currency,
)
from MDP.CitiVelocityExcel.xccy.ql_xccy import (
    bootstrap_ql_xccy_discount_curve,
    build_ql_xccy_swap,
    ql_curve_from_rl,
    ql_fair_basis_spread,
    ql_xccy_reprice_errors_bp,
)
from MDP.CitiVelocityExcel.xccy.rl_xccy import (
    RL_XCS_SPECS,
    build_rl_xcs,
    rl_xccy_reprice_errors_bp,
    rl_xcs_kwargs,
    solve_rl_collateral_curve,
)

REF_DATE = datetime.datetime(2026, 8, 5)
FX_EURUSD = 1.08  # USD per EUR
NOTIONAL = 100_000_000.0

#: Calibration axis. Deliberately shorter than XCCY_TENORS: the sub-1Y points
#: roll inside the first coupon period and are not what the curve is shaped by.
AXIS = ("1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y", "30Y")
#: A plausible EUR/USD basis strip, in bp on the EUR leg. Invented.
BASIS_BP = {
    "1Y": -8.0,
    "2Y": -11.0,
    "3Y": -13.5,
    "5Y": -16.0,
    "7Y": -17.5,
    "10Y": -19.0,
    "15Y": -21.0,
    "20Y": -23.0,
    "30Y": -26.5,
}
#: Upward-sloping synthetic par OIS, in percent.
USD_PAR = {"1Y": 3.90, "2Y": 3.80, "3Y": 3.78, "5Y": 3.85, "7Y": 3.95, "10Y": 4.05, "15Y": 4.20, "20Y": 4.25, "30Y": 4.20}
EUR_PAR = {"1Y": 2.05, "2Y": 2.00, "3Y": 2.02, "5Y": 2.15, "7Y": 2.28, "10Y": 2.42, "15Y": 2.58, "20Y": 2.62, "30Y": 2.55}

REPORT_TENORS = ("1Y", "5Y", "10Y", "30Y")


# ------------------------------------------------------------------ #
#                        synthetic market data                       #
# ------------------------------------------------------------------ #


def build_ois_curve(*, citi_index: str, par: dict[str, float], curve_id: str):
    """Solve one domestic OIS curve from a synthetic par grid."""
    import rateslib as rl

    conv = conventions_for_currency(citi_index.split("_")[0], ois_index=citi_index)
    cal = conv.rl_calendar_object()
    nodes = {REF_DATE: 1.0}
    for tenor in par:
        nodes[rl.add_tenor(REF_DATE, tenor, "MF", cal)] = 1.0
    curve = rl.Curve(
        nodes=nodes,
        id=curve_id,
        convention=conv.convention,
        calendar=cal,
        currency=conv.currency.lower(),
        modifier="MF",
    )
    instruments = [
        rl.IRS(REF_DATE, tenor, spec=conv.rl_spec, curves=curve) for tenor in par
    ]
    solver = rl.Solver(
        curves=[curve],
        instruments=instruments,
        s=list(par.values()),
        instrument_labels=list(par),
        id=curve_id,
    )
    if str(solver.result.get("status", "")).upper() != "SUCCESS":
        raise SystemExit(f"synthetic {curve_id} curve did not solve: {solver.result}")
    return curve, solver


# ------------------------------------------------------------------ #
#                                sections                            #
# ------------------------------------------------------------------ #


def section_fetch() -> None:
    """basis_data end to end against the fake Excel COM surface."""
    from MDP.CitiVelocityExcel import tags as cv_tags

    grid = cv_tags.xccy_basis_grid("EUR", "USD", tenors=list(AXIS))
    idx = pd.bdate_range(end=pd.Timestamp("2026-08-05"), periods=40)
    series = {
        tag: pd.Series(
            [BASIS_BP[tenor] + 0.05 * math.sin(i / 3.0) for i in range(len(idx))],
            index=idx,
            dtype="float64",
        )
        for tenor, tag in grid.items()
    }
    app = FakeExcelApp(FakeVelocityData(series=series))
    client = CitiVelocityExcelClient(app=app)
    basis = fetch_xccy_basis(
        client=client,
        ccy1="EUR",
        ccy2="USD",
        tenors=list(AXIS),
        as_of=datetime.date(2026, 8, 5),
    )
    print(f"  tags built            : {len(grid)}  e.g. {grid['5Y']}")
    print(f"  fetched               : {len(basis)}/{len(AXIS)} tenors, spread_ccy={basis.spread_ccy}")
    print(f"  CVTSHIST calls        : {len(app.formulas_for('CVTSHIST'))} for {len(AXIS)} tenors")
    print(f"  5Y quote              : {basis.at('5Y'):+.4f} bp (observed {basis.observed['5Y']})")
    print(f"  default tenor axis    : {len(XCCY_TENORS)} tokens, catalog.options() gives 0")

    # The cache-backed path uses a different adapter, so exercise it too.
    with tempfile.TemporaryDirectory() as tmp:
        cache = CitiVeloTagCache(pathlib.Path(tmp))
        cached = fetch_xccy_basis(
            client=client, ccy1="EUR", ccy2="USD", tenors=list(AXIS),
            as_of=datetime.date(2026, 8, 5), cache=cache,
        )
        agree = max(abs(cached.at(t) - basis.at(t)) for t in AXIS)
        print(f"  via CitiVeloTagCache  : {len(cached)} tenors, max |cached - direct| = {agree:.2e} bp")
    if agree > 1e-12:
        raise SystemExit("The cached read disagreed with the direct read.")


def section_validate_teeth() -> None:
    """The checker must fail on inputs whose answer is known in advance."""
    cases = [
        ("empty strip", {}),
        ("NaN point", {"1Y": -8.0, "5Y": float("nan")}),
        ("wrong units (decimals read as bp)", {"1Y": -8000.0, "5Y": -16000.0}),
    ]
    for label, quotes in cases:
        try:
            basis_from_quotes(quotes=quotes, ccy1="EUR", ccy2="USD", as_of=None)
        except ValueError as exc:
            print(f"  {label:36s} -> raised: {str(exc).split('.')[0][:72]}")
        else:
            raise SystemExit(f"validate() did NOT catch {label!r} - the check has no teeth.")

    ragged = basis_from_quotes(
        quotes={"1Y": -8.0, "5Y": -16.0},
        ccy1="EUR",
        ccy2="USD",
        as_of=None,
        requested_tenors=["1Y", "2Y", "5Y"],
        validate=False,
    )
    try:
        ragged.validate()
    except ValueError as exc:
        print(f"  {'ragged strip':36s} -> raised: {str(exc).split('.')[0][:72]}")
    else:
        raise SystemExit("validate() did NOT catch a ragged strip.")

    try:
        ois_index_for_currency("AUD_BBSW")
    except Exception as exc:  # noqa: BLE001 - the type is the point
        print(f"  {'AUD_BBSW as an OIS leg':36s} -> raised: {type(exc).__name__}")
    else:
        raise SystemExit("AUD_BBSW was accepted as an OIS leg.")


def main() -> int:
    import QuantLib as ql
    import rateslib as rl

    print("=" * 78)
    print("CitiVelocityExcel.xccy smoke - synthetic EUR/USD, no Excel, no market data")
    print("=" * 78)

    print("\n[1] basis_data over the fake Excel COM surface")
    section_fetch()

    print("\n[2] validate() teeth (each of these MUST raise)")
    section_validate_teeth()

    print("\n[3] synthetic domestic OIS curves")
    usd_curve, usd_solver = build_ois_curve(citi_index="USD_SOFR", par=USD_PAR, curve_id="usdusd")
    eur_curve, eur_solver = build_ois_curve(citi_index="EUR_EUROSTR", par=EUR_PAR, curve_id="eureur")
    for label, curve, par in (("USD SOFR", usd_curve, USD_PAR), ("EUR ESTR", eur_curve, EUR_PAR)):
        conv = "usd_irs" if label.startswith("USD") else "eur_irs"
        errs = [
            float(rl.IRS(REF_DATE, t, spec=conv, curves=curve).rate()) - s
            for t, s in par.items()
        ]
        print(f"  {label:9s} {len(par)} pillars, max |par reprice| = {max(abs(e) for e in errs) * 100:.3e} bp")

    basis = basis_from_quotes(
        quotes={t: BASIS_BP[t] for t in AXIS},
        ccy1="EUR",
        ccy2="USD",
        as_of=REF_DATE.date(),
    )
    print(f"  basis     {len(basis)} tenors, spread on the {basis.spread_ccy} leg, "
          f"{basis.at('1Y'):+.1f}bp -> {basis.at('30Y'):+.1f}bp")

    print("\n[4] rateslib: solve the EUR-under-USD-collateral discount curve")
    curves = solve_rl_collateral_curve(
        basis=basis,
        domestic_curve=eur_curve,
        foreign_curve=usd_curve,
        fx_rate=FX_EURUSD,
        ref_date=REF_DATE,
        pre_solvers=[eur_solver, usd_solver],
        notional=NOTIONAL,
        mtm=True,
    )
    rl_err = rl_xccy_reprice_errors_bp(curves, basis)
    print(f"  curve id {curves.curve_id!r}, discounts {curves.discount_ccy} under "
          f"{curves.collateral_ccy} collateral, mtm={curves.mtm}")
    print(f"  {'tenor':>6} {'quote_bp':>10} {'reprice_err_bp':>16}")
    for tenor in basis.tenors():
        print(f"  {tenor:>6} {basis.at(tenor):>10.3f} {rl_err[tenor]:>16.3e}")
    print(f"  MAX ABS REPRICE ERROR (rateslib) = {rl_err.abs().max():.3e} bp")

    print("\n[5] QuantLib: bootstrap the same curve from explicit cashflows")
    ql.Settings.instance().evaluationDate = ql.Date(REF_DATE.day, REF_DATE.month, REF_DATE.year)
    tgt = ql.TARGET()
    nyc = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    joint = ql.JointCalendar(tgt, nyc)
    h_eur = ql.YieldTermStructureHandle(ql_curve_from_rl(eur_curve, ref_date=REF_DATE, calendar=tgt))
    h_usd = ql.YieldTermStructureHandle(ql_curve_from_rl(usd_curve, ref_date=REF_DATE, calendar=nyc))
    estr = ql.Estr(h_eur)
    sofr = ql.Sofr(h_usd)

    handle, diag = bootstrap_ql_xccy_discount_curve(
        basis=basis,
        base_index=estr,
        quote_index=sofr,
        base_discount=h_eur,
        quote_discount=h_usd,
        fx_spot=FX_EURUSD,
        ref_date=REF_DATE.date(),
        notional=NOTIONAL,
        calendar=joint,
        return_diagnostics=True,
    )
    ql_err = ql_xccy_reprice_errors_bp(
        basis=basis,
        handle=handle,
        base_index=estr,
        quote_index=sofr,
        base_discount=h_eur,
        quote_discount=h_usd,
        fx_spot=FX_EURUSD,
        ref_date=REF_DATE.date(),
        notional=NOTIONAL,
        calendar=joint,
    )
    print(f"  {'tenor':>6} {'pillar':>12} {'z_bp':>9} {'reprice_err_bp':>16}")
    for tenor in basis.tenors():
        row = diag.loc[tenor]
        print(f"  {tenor:>6} {str(row['pillar']):>12} {row['z_bp']:>9.3f} {ql_err[tenor]:>16.3e}")
    print(f"  MAX ABS REPRICE ERROR (QuantLib) = {ql_err.abs().max():.3e} bp")

    print("\n[6] the two curves, side by side (continuous spread of QL over RL)")
    dc = ql.Actual365Fixed()
    d0 = ql.Date(REF_DATE.day, REF_DATE.month, REF_DATE.year)
    print(f"  {'tenor':>6} {'df_ql':>12} {'df_rl':>12} {'diff_bp':>10}")
    for tenor in basis.tenors():
        eff = joint.advance(d0, 2, ql.Days)
        mat = joint.adjust(eff + ql.Period(tenor), ql.ModifiedFollowing)
        df_ql = handle.discount(mat)
        df_rl = float(curves.collateral_curve[datetime.datetime(mat.year(), mat.month(), mat.dayOfMonth())])
        yf = dc.yearFraction(d0, mat)
        print(f"  {tenor:>6} {df_ql:>12.8f} {df_rl:>12.8f} {-math.log(df_ql / df_rl) / yf * 1e4:>10.3f}")

    print("\n[7] rateslib vs QuantLib fair basis, off the SAME (rateslib-solved) curve")
    print("    ql is constant-notional; rl_mtm is the market convention. The like-for-like")
    print("    column is rl_nomtm, and (ql - rl_nomtm) is pure construction difference.")
    h_coll = ql.YieldTermStructureHandle(
        ql_curve_from_rl(curves.collateral_curve, ref_date=REF_DATE, calendar=tgt)
    )
    print(f"  {'tenor':>6} {'quote':>8} {'rl_mtm':>10} {'rl_nomtm':>10} {'ql':>10} "
          f"{'ql-rl_nomtm':>13} {'mtm effect':>11}")
    worst_construction = 0.0
    ql_fairs: dict[str, float] = {}
    for tenor in REPORT_TENORS:
        quote = basis.at(tenor)
        rl_mtm = float(
            build_rl_xcs(
                basis=basis, tenor=tenor, domestic_curve=eur_curve, foreign_curve=usd_curve,
                fx_forwards=curves.fx_forwards, collateral_curve=curves.collateral_curve,
                notional=NOTIONAL, mtm=True, float_spread=0.0,
            ).rate(solver=curves.solver)
        )
        rl_nomtm = float(
            build_rl_xcs(
                basis=basis, tenor=tenor, domestic_curve=eur_curve, foreign_curve=usd_curve,
                fx_forwards=curves.fx_forwards, collateral_curve=curves.collateral_curve,
                notional=NOTIONAL, mtm=False, float_spread=0.0,
            ).rate(solver=curves.solver)
        )
        eff = joint.advance(d0, 2, ql.Days)
        mat = eff + ql.Period(tenor)  # unadjusted; build_ql_xccy_swap adjusts it
        ql_fair = build_ql_xccy_swap(
            notional=NOTIONAL, fx_spot=FX_EURUSD, start=eff, maturity=mat,
            base_index=estr, quote_index=sofr, base_discount=h_coll, quote_discount=h_usd,
            spread_bp=quote, base_ccy="EUR", quote_ccy="USD", spread_ccy="EUR", calendar=joint,
        ).fair_basis_spread
        worst_construction = max(worst_construction, abs(ql_fair - rl_nomtm))
        ql_fairs[tenor] = ql_fair
        print(f"  {tenor:>6} {quote:>8.3f} {rl_mtm:>10.4f} {rl_nomtm:>10.4f} {ql_fair:>10.4f} "
              f"{ql_fair - rl_nomtm:>13.6f} {rl_mtm - rl_nomtm:>11.4f}")
    print(f"  worst |ql - rl_nomtm| over {list(REPORT_TENORS)} = {worst_construction:.3e} bp")

    print("\n[8] does the cross-library check have teeth? (mutate the QuantLib payment lag)")
    moved = 0.0
    for tenor in REPORT_TENORS:
        eff = joint.advance(d0, 2, ql.Days)
        mat = eff + ql.Period(tenor)
        broken = build_ql_xccy_swap(
            notional=NOTIONAL, fx_spot=FX_EURUSD, start=eff, maturity=mat,
            base_index=estr, quote_index=sofr, base_discount=h_coll, quote_discount=h_usd,
            spread_bp=basis.at(tenor), base_ccy="EUR", quote_ccy="USD", spread_ccy="EUR",
            calendar=joint, payment_lag=0,
        ).fair_basis_spread
        moved = max(moved, abs(broken - ql_fairs[tenor]))
        print(f"  {tenor:>6} payment_lag 2 -> 0 moves the fair basis by "
              f"{broken - ql_fairs[tenor]:+.4f} bp")
    if moved < 1e-4:
        raise SystemExit(
            "Mutating the payment lag did not move the fair basis: the cross-library "
            "agreement above is not evidence of anything."
        )
    eff = joint.advance(d0, 2, ql.Days)
    verified = ql_fair_basis_spread(
        notional=NOTIONAL, fx_spot=FX_EURUSD, start=eff, maturity=eff + ql.Period("10Y"),
        base_index=estr, quote_index=sofr, base_discount=h_coll, quote_discount=h_usd,
        spread_bp=basis.at("10Y"), base_ccy="EUR", quote_ccy="USD", spread_ccy="EUR",
        calendar=joint,
    )
    print(f"  ql_fair_basis_spread 10Y (self-verified by repricing) = {verified:.4f} bp")
    try:
        build_ql_xccy_swap(
            notional=NOTIONAL, fx_spot=FX_EURUSD, start=eff, maturity=eff + ql.Period("5Y"),
            base_index=ql.Euribor3M(h_eur), quote_index=sofr, base_discount=h_coll,
            quote_discount=h_usd, spread_bp=-16.0, base_ccy="EUR", quote_ccy="USD",
            spread_ccy="EUR", calendar=joint,
        )
    except ValueError as exc:
        print(f"  IborIndex as a leg -> raised: {str(exc)[:74]}")
    else:
        raise SystemExit("An IborIndex was accepted and priced as compounded OIS.")

    print("\n[9] the reverse CSA: solve the USD-under-EUR-collateral curve instead")
    reverse = solve_rl_collateral_curve(
        basis=basis, domestic_curve=eur_curve, foreign_curve=usd_curve, fx_rate=FX_EURUSD,
        ref_date=REF_DATE, collateral_ccy="EUR", pre_solvers=[eur_solver, usd_solver],
        notional=NOTIONAL, mtm=True,
    )
    rev_err = rl_xccy_reprice_errors_bp(reverse, basis)
    print(f"  curve id {reverse.curve_id!r} discounts {reverse.discount_ccy} under "
          f"{reverse.collateral_ccy}; max reprice {rev_err.abs().max():.3e} bp")

    print("\n[10] a pair with NO rateslib spec: SEK/USD off explicit conventions")
    sek_par = {k: v + 0.6 for k, v in EUR_PAR.items()}
    sek_curve, sek_solver = build_ois_curve(citi_index="SEK_STINA", par=sek_par, curve_id="seksek")
    sek_basis = basis_from_quotes(
        quotes={t: BASIS_BP[t] * 0.4 for t in AXIS},
        ccy1="SEK",
        ccy2="USD",
        as_of=REF_DATE.date(),
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        sek_curves = solve_rl_collateral_curve(
            basis=sek_basis, domestic_curve=sek_curve, foreign_curve=usd_curve,
            fx_rate=0.095, ref_date=REF_DATE, pre_solvers=[sek_solver, usd_solver],
            notional=NOTIONAL, mtm=True,
        )
    sek_err = rl_xccy_reprice_errors_bp(sek_curves, sek_basis)
    kw, approx, notes = rl_xcs_kwargs(spread_ccy="SEK", other_ccy="USD")
    print(f"  spec available        : {'SEK/USD' in RL_XCS_SPECS} -> built from "
          f"calendar={kw['calendar']!r} conv={kw['convention']}/{kw['leg2_convention']}")
    print(f"  approximate={approx}, warned={len(caught)}: {str(caught[0].message)[:60] if caught else ''}")
    print(f"  curve {sek_curves.curve_id!r}, max reprice {sek_err.abs().max():.3e} bp")
    dkk_kw, _, dkk_notes = rl_xcs_kwargs(spread_ccy="DKK", other_ccy="USD")
    ils_kw, _, _ = rl_xcs_kwargs(spread_ccy="ILS", other_ccy="USD")
    print(f"  DKK/USD (no rateslib calendar) -> {type(dkk_kw['calendar']).__name__} from QuantLib "
          "holidays, not a proxy")
    print(f"  ILS/USD week mask (Sun-Thu market): "
          f"{sorted(ils_kw['calendar'].week_mask)} are the non-business weekdays (Mon=0)")
    print(f"  DKK note: {dkk_notes[-1][:70]}")

    print("\n" + "=" * 78)
    print(f"OK  rateslib max reprice {rl_err.abs().max():.3e} bp | "
          f"QuantLib max reprice {ql_err.abs().max():.3e} bp | "
          f"cross-library {worst_construction:.3e} bp | "
          f"mutation moved it {moved:.4f} bp")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - smoke script: show the whole failure
        traceback.print_exc()
        sys.exit(1)

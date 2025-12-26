import datetime

import pytest
import rateslib as rl

from Query.FixedRateBonds.backends.rateslib.RLFixedRateBondPricer import RLFixedRateBondPricer
from Query.USTFutures.backends.rateslib.RLUSTFuturePricer import RLUSTFuturePricer


def _build_curve() -> rl.Curve:
    return rl.Curve(
        {
            rl.dt(2024, 1, 2): 1.0,
            rl.dt(2025, 1, 2): 0.99,
            rl.dt(2034, 1, 2): 0.80,
        },
        id="USD-SOFR-1D",
    )


def _build_bond_pricers(reference_date: datetime.date):
    bond_a = RLFixedRateBondPricer(
        rl_frb_id="USTS",
        reference_date=reference_date,
        issue_date=datetime.date(2020, 1, 2),
        maturity_date=datetime.date(2026, 1, 2),
        cpn=2.5,
        clean_price=101.25,
    )
    bond_b = RLFixedRateBondPricer(
        rl_frb_id="USTS",
        reference_date=reference_date,
        issue_date=datetime.date(2019, 1, 2),
        maturity_date=datetime.date(2027, 1, 2),
        cpn=3.0,
        clean_price=110.0,
    )
    return [bond_a, bond_b]


def test_ust_future_rateslib_ctd_and_delta():
    reference_date = datetime.date(2024, 6, 3)
    delivery = (datetime.date(2024, 9, 2), datetime.date(2024, 9, 30))
    basket_pricers = _build_bond_pricers(reference_date)
    curve = _build_curve()

    rl_basket = [pricer.build_pricable() for pricer in basket_pricers]
    rl_future = rl.BondFuture(
        delivery=(rl.dt(2024, 9, 2), rl.dt(2024, 9, 30)),
        coupon=6.0,
        basket=rl_basket,
        nominal=100_000.0,
        contracts=1,
        currency="USD",
        calc_mode="ytm",
    )

    conversion_factors = list(rl_future.cfs)

    pricer = RLUSTFuturePricer(
        symbol="TYU4",
        reference_date=reference_date,
        price=105.0,
        delivery=delivery,
        basket=basket_pricers,
        conversion_factors=conversion_factors,
        coupon=6.0,
        notional=100_000.0,
        currency="USD",
        curve_id=curve.id,
        calc_mode="ytm",
    )

    expected_ctd = rl_future.ctd_index(
        future_price=105.0,
        prices=[p.clean_price() for p in basket_pricers],
        settlement=basket_pricers[0].settlement_date(),
    )
    assert pricer.ctd_index() == expected_ctd

    analytic_delta = pricer.analytic_delta(curves=curve)
    bond_deltas = [float(bond.analytic_delta(curve=curve)) for bond in rl_basket]
    weighted_delta = sum(cf * delta for cf, delta in zip(conversion_factors, bond_deltas))
    assert analytic_delta == pytest.approx(weighted_delta)

    assert pricer.conversion_factors() == conversion_factors

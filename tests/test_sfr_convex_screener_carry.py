from RVUtils.SFRConvexScreener import Leg
from RVUtils.SFRConvexScreener._carry import structure_pnl_from_rates_bp


def test_fly_pnl_zero_when_curve_unchanged():
    legs = (Leg("A", 1, 96.5, 25), Leg("B", -2, 96.6, 25), Leg("C", 1, 96.7, 25))
    rates_now = {"A": 3.5, "B": 3.4, "C": 3.3}
    rates_then = dict(rates_now)
    assert abs(structure_pnl_from_rates_bp(legs, rates_now=rates_now, rates_then=rates_then)) < 1e-9


def test_fly_pnl_positive_when_belly_richens():
    """Fly = front + back - 2*belly. If belly drops 5 bp, fly P&L = +10 bp."""
    legs = (Leg("A", 1, 96.5, 25), Leg("B", -2, 96.6, 25), Leg("C", 1, 96.7, 25))
    rates_now = {"A": 3.5, "B": 3.4, "C": 3.3}
    rates_then = {"A": 3.5, "B": 3.35, "C": 3.3}
    pnl_bp = structure_pnl_from_rates_bp(legs, rates_now=rates_now, rates_then=rates_then)
    assert abs(pnl_bp - 10.0) < 1e-6

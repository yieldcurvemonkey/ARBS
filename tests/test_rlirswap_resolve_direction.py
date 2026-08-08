"""resolve_pricable must not double-apply direction (kink-fade v2 §6 seam).

rateslib notionals arrive ALREADY SIGNED (the bpv path gives a receiver a
negative notional), and resolve_pricable signs by risk_weight. Before the
2026-08-08 fix it multiplied the SIGNED notional by the direction sign, so a
receiver (-N, rw=-1) resolved to (+N) — bpv=+100k and bpv=-100k priced as the
identical all-payer package through QueryDrivenBacktest (verified live on the
2022-09 CPI week: both printed +$2,303,346 on a +23.4bp move; after the fix
they mirror).

Every assertion here is derived from the sign algebra, not from the
implementation's output.
"""
import rateslib as rl

from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

REF = rl.dt(2026, 1, 5)


def _flat_curve(ref=REF):
    nodes = {ref: 1.0}
    for y in range(1, 41):
        nodes[rl.dt(ref.year + y, ref.month, ref.day)] = 1.0 / (1.04 ** y)
    handle = rl.Curve(nodes=nodes, convention="act360", calendar="nyc", id="c")
    return RLIRSwapCurve(
        rl_curve_id="USD-OIS",
        rl_curve_handle=handle,
        fixings=rl.NoInput(0),
        meta_data={"reference_curve_name": "USD-OIS"},
    )


def _leg1_notional(swap) -> float:
    return float(swap.kwargs.leg1["notional"])


def test_receiver_stays_receiver_through_resolve():
    curve = _flat_curve()
    receiver = curve.build_irswap(fwd="0D", tenor="5Y", bpv=-100_000.0)
    n0 = _leg1_notional(receiver)
    assert n0 < 0, "bpv<0 must build a negative-notional (receiver) swap"
    resolved = curve.resolve_pricable(receiver, risk_weight=-1.0)
    assert _leg1_notional(resolved) < 0, (
        "resolve_pricable flipped a receiver into a payer — the direction-blind "
        "seam is back"
    )
    assert abs(_leg1_notional(resolved)) == abs(n0)


def test_payer_stays_payer_through_resolve():
    curve = _flat_curve()
    payer = curve.build_irswap(fwd="0D", tenor="5Y", bpv=+100_000.0)
    n0 = _leg1_notional(payer)
    assert n0 > 0
    resolved = curve.resolve_pricable(payer, risk_weight=+1.0)
    assert _leg1_notional(resolved) > 0
    assert abs(_leg1_notional(resolved)) == abs(n0)


def test_buy_and_sell_resolve_to_mirrors():
    curve = _flat_curve()
    plus = curve.resolve_pricable(
        curve.build_irswap(fwd="0D", tenor="5Y", bpv=+100_000.0), risk_weight=+1.0
    )
    minus = curve.resolve_pricable(
        curve.build_irswap(fwd="0D", tenor="5Y", bpv=-100_000.0), risk_weight=-1.0
    )
    assert _leg1_notional(plus) == -_leg1_notional(minus)


def test_unsigned_notional_with_negative_weight_becomes_receiver():
    """The QL-convention caller: positive notional, direction only in rw."""
    curve = _flat_curve()
    swap = curve.build_irswap(fwd="0D", tenor="5Y", notional=1_000_000.0)
    resolved = curve.resolve_pricable(swap, risk_weight=-1.0)
    assert _leg1_notional(resolved) < 0

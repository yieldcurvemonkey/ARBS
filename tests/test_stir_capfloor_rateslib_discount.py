"""D2: ``STIRCapFloorMDP._discount`` indexed a rateslib curve with a QuantLib Date.

``_discount`` dispatches on the curve handle: a ``-QL`` source hands back a
``ql.YieldTermStructureHandle`` (called), an ``-RL`` source hands back a
``rateslib.Curve`` (subscripted). The subscript key was the ``ql.Date`` itself,
and ``rateslib.curves.Curve.__getitem__`` compares its key against
``self.nodes.initial`` -- a ``datetime.datetime`` -- so the comparison raised::

    TypeError: '<' not supported between instances of 'Date' and 'datetime.datetime'

Measured on ``CITIVELO_EXCEL``/``USD-SOFR-1D``/2023-06-09, ``expiry="1Y"``,
``tail="1Y"``: both ``weight_method="duration"`` (via ``_resolve_weights``) and
``strike_convention="flat_swap_rate"`` (via ``_contract_forward_price``) died
with that TypeError before a single option quote was requested. The QuantLib
branch is why nobody saw it -- the class default source, ``ERIS_EOD_LIVE-QL_BASIC``,
never reaches the subscript.

A ``datetime.date`` is NOT a sufficient fix and the tests below pin that:
rateslib rejects it with the same comparison failure
(``'<' not supported between instances of 'datetime.date' and 'datetime.datetime'``).
Only ``datetime.datetime`` works.

Nothing in the fast-gate tests here touches the network or the shared disk cache.
The object that used to raise is a **genuine** ``rateslib.Curve``, wrapped the way
``Query.IRSwaps.backends.rateslib.RLIRSwapCurve`` wraps it (``handle()`` returns
the bare ``rl.Curve``), so this is the real failure and not an imitation of it.
The one test that goes through the actual ``CITIVELO_EXCEL`` provider is marked
``slow``/``network`` because a cold cache would fetch.

MUTATION-CHECKED. Each mutation, the test that catches it, and the reason are
recorded in the docstring of the catching test.
"""

from __future__ import annotations

import datetime
import math

import pytest
import pytz
import QuantLib as ql
import rateslib as rl

from MDP.STIRCapFloors.STIRCapFloorMDP import STIRCapFloorMDP, _discount
from MDP.STIRFutures._sofr_option_contracts import _strike_from_symbol
from Query.STIRFutureOptions.backends.quantlib.QLSTIRFutureOptionPricer import (
    QLSTIRFutureOptionPricer,
)


AS_OF = datetime.date(2026, 3, 6)

#: 1Yx1Y off 2026-03-06 resolves to these four contracts, whose reference
#: quarters are (2027-03-17, 2027-06-16), (2027-06-16, 2027-09-15),
#: (2027-09-15, 2027-12-15) and (2027-12-15, 2028-03-15).
STRIP = ("SFRH27", "SFRM27", "SFRU27", "SFRZ27")
REF_WINDOWS = (
    (datetime.date(2027, 3, 17), datetime.date(2027, 6, 16)),
    (datetime.date(2027, 6, 16), datetime.date(2027, 9, 15)),
    (datetime.date(2027, 9, 15), datetime.date(2027, 12, 15)),
    (datetime.date(2027, 12, 15), datetime.date(2028, 3, 15)),
)

#: Planted discount factors. Every date ``_discount`` is asked for in this module
#: is a NODE of the curve, so the expected answer is the node value verbatim and
#: is independent of rateslib's interpolation as well as of the code under test.
NODES: dict[datetime.date, float] = {
    datetime.date(2026, 3, 6): 1.00,
    datetime.date(2027, 3, 17): 0.95,
    datetime.date(2027, 6, 16): 0.94,
    datetime.date(2027, 9, 15): 0.93,
    datetime.date(2027, 12, 15): 0.92,
    datetime.date(2028, 3, 15): 0.91,
    datetime.date(2029, 3, 15): 0.88,
}


def _act360(start: datetime.date, end: datetime.date) -> float:
    return (end - start).days / 360.0


class _RateslibBackedCurve:
    """A genuine ``rateslib.Curve``, wrapped the way ``RLIRSwapCurve`` wraps one.

    ``RLIRSwapCurve.handle()`` returns the bare ``rl.Curve`` and the class has no
    ``discount`` method, which is exactly the shape that routed ``_discount``
    into the subscript branch on ``CITIVELO_EXCEL``. ``build_irswap``/
    ``fair_rate`` mirror the other two curve methods ``_build_context`` calls, and
    ``fair_rate`` returns a DECIMAL rate as ``RLIRSwapCurve.fair_rate`` does
    (``irswap.rate(...) / 100``), not a percentage.
    """

    def __init__(self) -> None:
        self._curve = rl.Curve(
            nodes={
                datetime.datetime(d.year, d.month, d.day): v for d, v in NODES.items()
            },
            id="d2_rl_curve",
        )

    def handle(self) -> rl.Curve:
        return self._curve

    def build_irswap(self, *, effective_date=None, maturity_date=None, **_):
        return (effective_date, maturity_date)

    def fair_rate(self, swap) -> float:
        start, end = swap
        tau = _act360(start, end)
        return (NODES[start] / NODES[end] - 1.0) / tau


class _QuantLibBackedCurve:
    """The shape that already worked: a handle exposing ``discount(ql.Date)``.

    Mirrors ``QLIRSwapCurve``. ``__getitem__`` raises so that any regression that
    routes a QuantLib curve into the rateslib branch is a loud failure rather
    than a silently different number.
    """

    def __init__(self, zero_rate: float = 0.04) -> None:
        self.zero_rate = float(zero_rate)

    def handle(self):
        return self

    def discount(self, ql_date: ql.Date) -> float:
        py_date = datetime.date(ql_date.year(), ql_date.month(), ql_date.dayOfMonth())
        return math.exp(-self.zero_rate * max((py_date - AS_OF).days, 0) / 365.0)

    def __getitem__(self, key):  # pragma: no cover - the assertion is that this never runs
        raise AssertionError(
            f"a QuantLib-backed curve was subscripted with {key!r} instead of "
            "having discount() called"
        )

    def build_irswap(self, *, effective_date=None, maturity_date=None, **_):
        return (effective_date, maturity_date)

    def fair_rate(self, swap) -> float:
        _ = swap
        return 0.043473010505977384


def _mk_pricer(*, symbol: str, expiry_date: datetime.date) -> QLSTIRFutureOptionPricer:
    return QLSTIRFutureOptionPricer(
        symbol=symbol,
        right=symbol[-1],
        underlying_symbol=symbol.split("|", 1)[0],
        strike=_strike_from_symbol(symbol),
        quote_timestamp=pytz.UTC.localize(datetime.datetime(2026, 3, 6, 17, 0)),
        expiry_date=expiry_date,
        market_price=1.0,
        model_price=1.0,
        iv_normal=0.9,
        delta=-0.4,
        gamma=0.2,
        vega=0.1,
        theta=-0.01,
        forward=95.75,
        discount=1.0,
        meta_data={},
    )


def _fake_option_snapshot(req):
    """Echo back whatever strike was asked for, as a listed quote.

    Faithful to the real MDP for this purpose: ``flat_swap_rate`` builds the
    symbol from the SNAPPED strike, so echoing it back means the leg identities
    the test asserts on are the strikes the curve produced.
    """
    symbol = req["symbols"][0]
    contract = symbol.split("|", 1)[0]
    right = symbol[-1]
    resolved = f"{contract}|9587{right}" if symbol.endswith("ATMP") or symbol.endswith("ATMC") else symbol
    return {symbol: [_mk_pricer(symbol=resolved, expiry_date=datetime.date(2027, 3, 17))]}


def _mdp(monkeypatch, curve) -> STIRCapFloorMDP:
    mdp = STIRCapFloorMDP()
    monkeypatch.setattr(mdp._curve_mdp, "get_pricer", lambda req: curve)
    monkeypatch.setattr(mdp._option_mdp, "get_data", _fake_option_snapshot)
    return mdp


BASE_REQUEST = {
    "endpoint": "synthetic_capfloor_snapshot",
    "structure": "CAP",
    "curve_name": "USD-SOFR-1D",
    "timestamp": AS_OF,
    "expiry": "1Y",
    "tail": "1Y",
}


# ===========================================================================
# The defect, at its narrowest
# ===========================================================================
def test_discount_on_a_rateslib_curve_returns_the_curves_own_discount_factor():
    """Planted known answer: every asked-for date is a node, so df == node value.

    BEFORE THE FIX this raises ``TypeError: '<' not supported between instances
    of 'Date' and 'datetime.datetime'``.

    MUTATIONS CAUGHT:
      * key reverted to the raw ``ql_date``          -> the original TypeError
      * key built as ``dt.date`` instead of ``dt.datetime`` -> date/datetime TypeError
      * subscript branch replaced by ``return 1.0``  -> 1.0 != 0.94
    """
    curve = _RateslibBackedCurve()
    assert _discount(curve, ql.Date(16, 6, 2027)) == pytest.approx(0.94, abs=1e-12)
    assert _discount(curve, ql.Date(17, 3, 2027)) == pytest.approx(0.95, abs=1e-12)
    assert _discount(curve, ql.Date(15, 3, 2028)) == pytest.approx(0.91, abs=1e-12)
    # ...and the bare rl.Curve, not just the wrapper (RLIRSwapCurve.handle()).
    assert _discount(curve.handle(), ql.Date(15, 9, 2027)) == pytest.approx(0.93, abs=1e-12)


def test_rateslib_rejects_a_plain_date_so_the_fix_must_hand_it_a_datetime():
    """Why ``ql_date_to_datetime`` and not ``ql_date_to_pydate``.

    This is a property of the dependency, asserted directly so that a future
    "simplification" to ``datetime.date`` is caught with its reason attached
    rather than as a bare failure inside ``_discount``.
    """
    curve = _RateslibBackedCurve().handle()
    assert curve[datetime.datetime(2027, 6, 16)] == pytest.approx(0.94, abs=1e-12)
    with pytest.raises(TypeError, match="datetime.date.*datetime.datetime"):
        curve[datetime.date(2027, 6, 16)]
    with pytest.raises(TypeError, match="Date.*datetime.datetime"):
        curve[ql.Date(16, 6, 2027)]


def test_quantlib_backed_curve_is_still_called_not_subscripted():
    """The backend that already worked must keep working, by the same route.

    ``_QuantLibBackedCurve.__getitem__`` raises ``AssertionError``, so a mutation
    that drops or inverts the ``hasattr(handle, "discount")`` dispatch fails here
    instead of quietly pricing off the wrong branch.

    MUTATION CAUGHT: deleting the ``discount`` branch, or reordering it after the
    subscript.
    """
    curve = _QuantLibBackedCurve(zero_rate=0.04)
    expected = math.exp(-0.04 * (datetime.date(2027, 6, 16) - AS_OF).days / 365.0)
    assert _discount(curve, ql.Date(16, 6, 2027)) == pytest.approx(expected, abs=1e-15)


# ===========================================================================
# The two settings the defect made unusable, through the real request path
# ===========================================================================
def test_duration_weights_resolve_on_a_rateslib_curve(monkeypatch):
    """``weight_method="duration"`` end to end, against planted node values.

    BEFORE THE FIX: ``TypeError: '<' not supported between instances of 'Date'
    and 'datetime.datetime'`` out of ``_resolve_weights``, before any option
    quote is requested.

    The expected weights are ``df(ref_end) * tau`` normalised, computed here from
    the ``NODES`` table rather than from the curve, so a ``_discount`` that
    returned a constant (weights all 0.25-ish but not these) is caught: the four
    expected values are 0.254054, 0.251351, 0.248649, 0.245946 and equal
    weighting would give 0.25 exactly.
    """
    raw = [NODES[end] * _act360(start, end) for start, end in REF_WINDOWS]
    total = sum(raw)
    expected = [r / total for r in raw]

    mdp = _mdp(monkeypatch, _RateslibBackedCurve())
    ctx = mdp.get_data({**BASE_REQUEST, "weight_method": "duration"})

    assert ctx.metadata["strip_contracts"] == list(STRIP)
    assert [leg.economic_weight for leg in ctx.legs] == pytest.approx(expected, abs=1e-12)
    assert sum(leg.economic_weight for leg in ctx.legs) == pytest.approx(1.0, abs=1e-12)
    # Not the equal-weight answer, so a constant-returning _discount cannot pass.
    assert [leg.economic_weight for leg in ctx.legs] != pytest.approx([0.25] * 4, abs=1e-6)


def test_contract_forward_price_on_a_rateslib_curve():
    """``_contract_forward_price`` is the only ``_discount`` caller on the
    ``flat_swap_rate`` path; pin its four planted answers.

    BEFORE THE FIX: the same TypeError.
    """
    mdp = STIRCapFloorMDP()
    curve = _RateslibBackedCurve()
    for contract, (start, end) in zip(STRIP, REF_WINDOWS):
        tau = _act360(start, end)
        fwd_rate = (NODES[start] / NODES[end] - 1.0) / tau
        assert mdp._contract_forward_price(curve=curve, contract=contract) == pytest.approx(
            100.0 - fwd_rate * 100.0, abs=1e-10
        )


def test_flat_swap_rate_strikes_resolve_on_a_rateslib_curve(monkeypatch):
    """``strike_convention="flat_swap_rate"`` end to end.

    BEFORE THE FIX: ``TypeError: '<' not supported between instances of 'Date'
    and 'datetime.datetime'`` out of ``_contract_forward_price``.

    The requested strike is the pack's matched forward swap rate as a price,
    ``100 - 100 * (df(2027-03-17)/df(2028-03-15) - 1) / tau`` = 95.652699 on the
    planted curve. The snapped strikes are asserted as leg IDENTITIES: the
    per-contract forward the curve produced decides which rung of the listed
    ladder each caplet lands on, and the four planted forwards (95.791443,
    95.746189, 95.699952, 95.652699) do NOT all land on the same rung -- SFRU27
    snaps up to 95.75 where the other three snap to 95.625. A ``_discount`` that
    returned a constant would give four identical forwards and therefore four
    identical strikes, which this list rejects.
    """
    tau = _act360(datetime.date(2027, 3, 17), datetime.date(2028, 3, 15))
    flat_rate = (NODES[datetime.date(2027, 3, 17)] / NODES[datetime.date(2028, 3, 15)] - 1.0) / tau

    mdp = _mdp(monkeypatch, _RateslibBackedCurve())
    ctx = mdp.get_data({**BASE_REQUEST, "strike_convention": "flat_swap_rate"})

    assert ctx.metadata["strip_contracts"] == list(STRIP)
    assert ctx.metadata["flat_swap_rate"] == pytest.approx(flat_rate, abs=1e-12)
    assert len(ctx.legs) == 4
    for leg in ctx.legs:
        assert leg.requested_strike_price == pytest.approx(100.0 - flat_rate * 100.0, abs=1e-10)
    assert [leg.option_symbol for leg in ctx.legs] == [
        "SFRH27|9562P",
        "SFRM27|9562P",
        "SFRU27|9575P",
        "SFRZ27|9562P",
    ]
    assert [leg.strike_price for leg in ctx.legs] == pytest.approx(
        [95.625, 95.625, 95.75, 95.625], abs=1e-12
    )


def test_quantlib_curve_unaffected_by_the_rateslib_fix(monkeypatch):
    """Non-regression for the backend that already worked, at request level.

    Both settings run against a ``discount()``-bearing curve whose
    ``__getitem__`` raises, so any leakage into the rateslib branch fails loudly.
    """
    mdp = _mdp(monkeypatch, _QuantLibBackedCurve(zero_rate=0.07))
    duration = mdp.get_data({**BASE_REQUEST, "weight_method": "duration"})
    flat = mdp.get_data({**BASE_REQUEST, "strike_convention": "flat_swap_rate"})

    weights = [leg.economic_weight for leg in duration.legs]
    assert sum(weights) == pytest.approx(1.0, abs=1e-12)
    assert weights != pytest.approx([0.25] * 4, abs=1e-6)
    assert len(flat.legs) == 4


# ===========================================================================
# The real provider
# ===========================================================================
@pytest.mark.slow
@pytest.mark.network
def test_real_citivelo_excel_curve_supports_both_settings():
    """The measured reproduction, against the actual ``CITIVELO_EXCEL`` provider.

    ``CITIVELO_EXCEL`` is an ``-RL`` token, so ``IRSwapsMDP`` returns an
    ``RLIRSwapCurve`` whose ``handle()`` is a ``rateslib.Curve`` -- the exact
    object that raised. Marked ``slow``/``network``: it reads the shared curve
    store, and a cold store would fetch.

    The curve fetch is retried once, serially, because a concurrent reader of the
    shared disk cache surfaces as a miss.
    """
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    as_of = datetime.date(2023, 6, 9)
    curve_mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
    curve = None
    for _ in range(2):
        try:
            curve = curve_mdp.get_pricer({"curve_name": "USD-SOFR-1D", "timestamp": as_of})
            break
        except Exception:
            curve = None
    if curve is None:
        pytest.skip("CITIVELO_EXCEL USD-SOFR-1D 2023-06-09 not available from the local store")

    # The precondition that makes this the D2 path and not the QuantLib one.
    handle = curve.handle()
    assert isinstance(handle, rl.Curve)
    assert not hasattr(handle, "discount")

    mdp = STIRCapFloorMDP(curve_source="CITIVELO_EXCEL")
    strip = ["SFRM24", "SFRU24", "SFRZ24", "SFRH25"]

    weights = mdp._resolve_weights(curve=curve, strip_contracts=strip, weight_method="duration")
    assert len(weights) == 4
    assert sum(weights) == pytest.approx(1.0, abs=1e-12)
    assert weights != pytest.approx([0.25] * 4, abs=1e-6)
    assert weights == sorted(weights, reverse=True)  # dfs fall, so weights fall

    for contract in strip:
        price = mdp._contract_forward_price(curve=curve, contract=contract)
        assert 80.0 < price < 100.0

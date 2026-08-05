r"""Hermetic tests for the Citi Velocity Query product and its timeseries builder.

The centrepiece is :func:`test_fast_path_matches_repricing_path`. ``CitiVelocityTB``
routes queries that resolve to a tag straight to a bulk ``CVTSHIST`` read instead of
stripping a curve at every timestep, and **an optimisation that has not been shown
to agree with the path it replaces is a silent-divergence risk, not an
optimisation.** The comparison is meaningful rather than circular because the curve
is calibrated to the very quotes the fast path reads: a 10y par rate repriced off a
curve stripped from a grid containing that 10y quote must reproduce it to solver
tolerance.

Everything runs against :class:`MDP.CitiVelocityExcel.testing.FakeExcelApp`; no
Excel, no network, no database.
"""

from __future__ import annotations

import datetime
import logging
import pathlib

import numpy as np
import pandas as pd
import pytest

from MDP.CitiVelocityExcel import tags as T
from MDP.CitiVelocityExcel.cache import CitiVeloTagCache
from MDP.CitiVelocityExcel.catalog import tenor_years
from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient
from MDP.CitiVelocityExcel.errors import CitiVelocityError
from MDP.CitiVelocityExcel.mdp import CitiVelocityMDP
from MDP.CitiVelocityExcel.pricer import classify_tag
from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes
from MDP.CitiVelocityExcel.testing import FakeExcelApp, FakeVelocityData
from Query.Base.product_adapter import get_adapter
from Query.CitiVelocity import (
    CitiVeloKind,
    CitiVeloQuery,
    CitiVeloStructure,
    CitiVeloUnit,
    CitiVeloValue,
)
from TB.CitiVelocityTB import CitiVelocityTB

CURVE = "USD_SOFR"
START = datetime.date(2026, 7, 20)
END = datetime.date(2026, 8, 4)
#: A shorter window for tests that drive the per-timestep repricing path -
#: each timestep there is a full curve solve, so 4 points is plenty to prove
#: agreement and 12 just makes the fast gate slower.
REPRICE_START = datetime.date(2026, 7, 30)


# ------------------------------------------------------------------ #
#                              fixtures                              #
# ------------------------------------------------------------------ #


def _par(tenor: str, step: int) -> float:
    """A smooth, monotone, solvable par curve that also moves through time."""
    years = tenor_years(tenor)
    return 3.60 + 0.90 * (1.0 - np.exp(-years / 3.0)) + 0.02 * np.sin(step / 9.0)


@pytest.fixture()
def fake_app() -> FakeExcelApp:
    index = pd.bdate_range("2026-06-01", "2026-08-04")
    grid = T.ois_par_grid(CURVE)
    series = {
        tag: pd.Series(
            [_par(tag.rsplit(".", 1)[-1], k) for k in range(len(index))],
            index=index,
        )
        for tag in grid
    }
    # A vol point, so the mixed-family routing has something to route.
    series[T.vol_atm("USD", "1Y", "10Y")] = pd.Series(
        95.0 + 0.05 * np.arange(len(index)), index=index
    )
    return FakeExcelApp(FakeVelocityData(series=series), pending_reads=1)


@pytest.fixture()
def tb(fake_app: FakeExcelApp, tmp_path: pathlib.Path) -> CitiVelocityTB:
    client = CitiVelocityExcelClient(app=fake_app, drain_seconds=0.0)
    quotes = CitiVeloQuotes(client=client, cache=CitiVeloTagCache(base_dir=tmp_path))
    return CitiVelocityTB(CitiVelocityMDP(quotes=quotes), show_tqdm=False)


def _outright() -> CitiVeloQuery:
    return CitiVeloQuery(citi_index=CURVE, tenor="10Y")


def _curve() -> CitiVeloQuery:
    return CitiVeloQuery(
        citi_index=CURVE,
        structure=CitiVeloStructure.CURVE,
        structure_kwargs={"front_tenor": "2Y", "back_tenor": "10Y"},
    )


def _fly() -> CitiVeloQuery:
    return CitiVeloQuery(
        citi_index=CURVE,
        structure=CitiVeloStructure.FLY,
        structure_kwargs={"front_tenor": "2Y", "belly_tenor": "5Y", "back_tenor": "10Y"},
    )


# ------------------------------------------------------------------ #
#                          the Query product                         #
# ------------------------------------------------------------------ #


def test_product_registers_on_import():
    """Importing the Query class is what registers the adapter, per repo convention."""
    assert get_adapter("CITIVELO") is not None
    assert _outright().product == "CITIVELO"


def test_column_names_and_eval_expressions_pair_up():
    q = _fly()
    assert q.col_name() == "USD_SOFR 2Y-5Y-10Y FLY QUOTE"
    assert q.eval_expression() == "`USD_SOFR 2Y-5Y-10Y FLY QUOTE`"
    # BaseQuery.__mul__ seeds an unweighted query's risk_weight from the int 1, so
    # the coefficient formats without a decimal point. The contract that matters is
    # that eval_expression() references col_name() in backticks.
    assert (q * 2).eval_expression() == "2 * `USD_SOFR 2Y-5Y-10Y FLY QUOTE`"
    assert (q * 2.5).eval_expression() == "2.5 * `USD_SOFR 2Y-5Y-10Y FLY QUOTE`"


def test_list_valued_value_fans_out_into_one_query_each():
    q = CitiVeloQuery(
        citi_index=CURVE, tenor="10Y", value=[CitiVeloValue.QUOTE, CitiVeloValue.RL_RATE]
    )
    expanded = q.return_query()
    assert [x.value for x in expanded] == [CitiVeloValue.QUOTE, CitiVeloValue.RL_RATE]
    assert len({x.col_name() for x in expanded}) == 2


def test_tag_classification_recovers_structure_from_a_passthrough_tag():
    """A tag passed straight through must be as well understood as a built one.

    Otherwise a caller who knows the tag loses the unit, the repricing route and a
    readable column label - and a tag newer than the committed catalog must never
    be blocked.
    """
    kind, fields = classify_tag("RATES.OIS.USD_SOFR.PAR.10Y")
    assert kind is CitiVeloKind.OIS_PAR
    assert fields["citi_index"] == "USD_SOFR" and fields["tenor"] == "10Y"

    kind, fields = classify_tag("RATES.VOL.USD.OTM_RFR.NORMALABSOLUTE.ANNUAL.OTM_M25.1Y.10Y")
    assert kind is CitiVeloKind.VOL_OTM
    assert fields["offset_bp"] == -25.0

    kind, fields = classify_tag(
        "RATES.XCCY_OIS_SWAP.USD.EUR.SPOT.10Y.SPREAD_LEG.BASIS_SPREAD"
    )
    assert kind is CitiVeloKind.XCCY_BASIS
    assert fields["currency"] == "USD" and fields["counter_currency"] == "EUR"

    assert classify_tag("RATES.SOMETHING.BRAND.NEW")[0] is CitiVeloKind.RAW


def test_units_are_declared_per_family():
    """Par rates are percent; spreads, bases and normal vols are basis points."""
    assert CitiVeloKind.OIS_PAR.unit is CitiVeloUnit.PERCENT
    assert CitiVeloKind.SWAP_SPREAD.unit is CitiVeloUnit.BASIS_POINTS
    assert CitiVeloKind.XCCY_BASIS.unit is CitiVeloUnit.BASIS_POINTS
    assert CitiVeloKind.VOL_ATM.unit is CitiVeloUnit.VOL_BP
    assert CitiVeloUnit.PERCENT.scale_to_bp == 100.0
    assert CitiVeloUnit.BASIS_POINTS.scale_to_bp == 1.0


def test_heterogeneous_curve_is_refused(tb: CitiVelocityTB):
    """A SOFR leg against a Fed Funds leg is a basis, not a curve.

    Netting them under a CURVE label would produce a number nobody asked for, so
    the structure layer refuses and points at SPREAD.
    """
    pricer = tb.mdp.get_pricer({"timestamp": "live"})
    q = CitiVeloQuery(
        structure=CitiVeloStructure.SPREAD,
        structure_kwargs={
            "legs": [
                {"citi_index": "USD_SOFR", "tenor": "10Y"},
                {"citi_index": "USD_FEDFUND", "tenor": "10Y"},
            ]
        },
    )
    package, weights = q.resolve_package(pricer_or_curve=pricer)
    assert [leg.citi_index for leg in package] == ["USD_SOFR", "USD_FEDFUND"]
    assert weights == [-1.0, 1.0]

    bad = CitiVeloQuery(
        structure=CitiVeloStructure.SPREAD,
        structure_kwargs={
            "legs": [
                {"citi_index": "USD_SOFR", "tenor": "10Y"},
                {"citi_index": "USD_SOFR", "tenor": "10Y", "family": "SWAP_SPREAD"},
            ]
        },
    )
    with pytest.raises(ValueError, match="different units"):
        bad.resolve_package(pricer_or_curve=pricer)


def test_risk_weight_defaults_are_not_mutated_between_queries():
    """MUTATION-PROOFING for a bug the sibling product actually has.

    ``Query/FixedRateBonds`` declares ``risk_weights: List[float] = [1.0, 2.0, 1.0]``
    as a mutable default and then sign-flips it IN PLACE, so an unweighted query
    permanently poisons the next one. The defaults here are tuples, copied on use.
    """
    from Query.CitiVelocity.CitiVeloStructure import DEFAULT_FLY_WEIGHTS

    before = tuple(DEFAULT_FLY_WEIGHTS)
    q = _fly()
    for _ in range(3):
        assert q.structure_kwargs.get("risk_weights") is None
    assert tuple(DEFAULT_FLY_WEIGHTS) == before
    assert isinstance(DEFAULT_FLY_WEIGHTS, tuple)


# ------------------------------------------------------------------ #
#                          the fast path                             #
# ------------------------------------------------------------------ #


def test_quote_only_queries_route_to_the_fast_path(tb: CitiVelocityTB):
    plan = tb.plan([_outright(), _curve(), _fly()])
    assert len(plan.fast) == 3
    assert not plan.slow
    assert set(plan.tags) == {
        T.ois_par(CURVE, "2Y"),
        T.ois_par(CURVE, "5Y"),
        T.ois_par(CURVE, "10Y"),
    }


def test_model_valued_queries_route_to_the_repricing_path(tb: CitiVelocityTB):
    q = CitiVeloQuery(citi_index=CURVE, tenor="10Y", value=CitiVeloValue.RL_RATE)
    plan = tb.plan([q, _outright()])
    assert [x.col_name() for x in plan.fast] == [_outright().col_name()]
    assert [x.col_name() for x in plan.slow] == [q.col_name()]
    assert "RL_RATE" in plan.reasons[id(plan.slow[0])]


def test_fast_path_costs_one_cvtshist_call_for_the_whole_window(
    tb: CitiVelocityTB, fake_app: FakeExcelApp
):
    """This is the point of the fast path.

    The repricing path would build one curve per timestep - a solver run each -
    to recover numbers the add-in already published.
    """
    frame = tb.get_timeseries(START, END, [_outright(), _curve(), _fly()])
    assert frame.shape == (12, 3)
    assert len(fake_app.formulas_for("CVTSHIST")) == 1


def test_fast_path_units_match_the_irswaps_convention(tb: CitiVelocityTB):
    """Outright in percent, curve and fly in basis points."""
    frame = tb.get_timeseries(START, END, [_outright(), _curve(), _fly()])
    outright = frame[_outright().col_name()].iloc[-1]
    curve = frame[_curve().col_name()].iloc[-1]
    fly = frame[_fly().col_name()].iloc[-1]
    assert 3.0 < outright < 5.0, "an outright par rate should be in percent"
    assert 10.0 < curve < 200.0, "a 2s10s curve should be in basis points"
    assert 0.0 < fly < 100.0, "a 2s5s10s fly should be in basis points"

    # ... and the arithmetic is the structure's own, not a coincidence.
    q2 = CitiVeloQuery(citi_index=CURVE, tenor="2Y")
    q5 = CitiVeloQuery(citi_index=CURVE, tenor="5Y")
    legs = tb.get_timeseries(START, END, [q2, q5, _outright()])
    expected_curve = (legs[_outright().col_name()] - legs[q2.col_name()]) * 100.0
    assert frame[_curve().col_name()].iloc[-1] == pytest.approx(expected_curve.iloc[-1])
    expected_fly = (
        2 * legs[q5.col_name()] - legs[q2.col_name()] - legs[_outright().col_name()]
    ) * 100.0
    assert frame[_fly().col_name()].iloc[-1] == pytest.approx(expected_fly.iloc[-1])


def test_risk_weight_scales_the_fast_path_result(tb: CitiVelocityTB):
    plain = tb.get_timeseries(START, END, [_outright()])
    doubled = tb.get_timeseries(START, END, [_outright() * 2])
    col = _outright().col_name()
    assert doubled[col].iloc[-1] == pytest.approx(2.0 * plain[col].iloc[-1])


# ------------------------------------------------------------------ #
#                        THE EQUIVALENCE PROOF                       #
# ------------------------------------------------------------------ #


@pytest.mark.parametrize(
    "model_value, tol",
    [(CitiVeloValue.RL_RATE, 1e-3), (CitiVeloValue.QL_RATE, 1e-3)],
)
def test_fast_path_matches_repricing_path(tb: CitiVelocityTB, model_value, tol):
    """The fast path and the repricing path must agree, or the shortcut is a bug.

    The fast path reads Citi's published par rate. The comparison path strips a
    curve from the whole 44-tenor grid - which contains that quote - and reprices
    the structure off it. Measured on this synthetic grid: rateslib agrees to
    ~7e-06 (its default ``func_tol=1e-9`` solver residual) and QuantLib to
    ~3e-09. The tolerance asserted here is 1e-3, two to six orders looser, so the
    test fails on a real divergence rather than on solver noise.
    """
    out = tb.assert_fast_path_matches(
        REPRICE_START,
        END,
        [_outright(), _curve()],
        model_value=model_value,
        tol=tol,
    )
    assert len(out) > 0
    assert float(out["diff"].abs().max()) < tol


def test_equivalence_helper_refuses_an_empty_comparison(tb: CitiVelocityTB):
    """An empty comparison must never read as a pass."""
    with pytest.raises(ValueError, match="no overlapping points"):
        tb.assert_fast_path_matches(
            datetime.date(2001, 1, 2),
            datetime.date(2001, 1, 5),
            [_outright()],
            model_value=CitiVeloValue.RL_RATE,
        )


def test_equivalence_helper_catches_a_real_divergence(tb: CitiVelocityTB, monkeypatch):
    """MUTATION CHECK: the equivalence assertion has teeth.

    Bias the repricing path by 1 bp and confirm the helper raises. Without this,
    "the two paths agree" could be true because both are reading the same number
    through the same code.
    """
    from MDP.CitiVelocityExcel import pricer as pricer_module

    original = pricer_module.CitiVeloPricer.rl_par_rate
    monkeypatch.setattr(
        pricer_module.CitiVeloPricer,
        "rl_par_rate",
        lambda self, leg: original(self, leg) + 0.01,  # +1 bp, in percent
    )
    with pytest.raises(AssertionError, match="disagree"):
        tb.assert_fast_path_matches(
            REPRICE_START, END, [_outright()], model_value=CitiVeloValue.RL_RATE, tol=1e-3
        )


# ------------------------------------------------------------------ #
#                       the repricing path                           #
# ------------------------------------------------------------------ #


def test_repricing_path_warms_the_whole_par_grid_in_one_call(
    tb: CitiVelocityTB, fake_app: FakeExcelApp
):
    """A par-rate reprice needs the grid, not just the tenor asked for.

    Warming it up front is what keeps the slow path to one ``CVTSHIST`` sweep as
    well - otherwise every timestep would fetch 44 tags of its own.
    """
    q = CitiVeloQuery(citi_index=CURVE, tenor="10Y", value=CitiVeloValue.RL_RATE)
    frame = tb.get_timeseries(REPRICE_START, END, [q])
    assert not frame.empty
    assert len(fake_app.formulas_for("CVTSHIST")) == 1


def test_repricing_failures_are_reported_not_silently_dropped(
    tb: CitiVelocityTB, caplog: pytest.LogCaptureFixture
):
    """The base class swallows every exception; this builder counts and reports.

    ``IRSwapsTB`` broke the same pattern after a missing-DV01 bug "returned an
    empty DataFrame with no message and no exception, so asking for DV01 looked
    like 'no data'".
    """
    q = CitiVeloQuery(
        citi_index=CURVE, tenor="10Y", value=CitiVeloValue.QL_BOND_YIELD
    )  # nonsense for a rate leg
    with caplog.at_level(logging.WARNING, logger="TB.CitiVelocityTB"):
        frame = tb.get_timeseries(REPRICE_START, END, [q])
    assert frame.empty
    assert any("repricing path" in r.getMessage() for r in caplog.records)


def test_missing_quote_raises_rather_than_pricing_a_partial_package(tb: CitiVelocityTB):
    """A fly priced with a missing wing is a plausible number that is wrong."""
    pricer = tb.mdp.get_pricer({"timestamp": datetime.date(2026, 8, 4)})
    with pytest.raises(CitiVelocityError, match="No Citi Velocity quote"):
        pricer.quote("RATES.OIS.USD_SOFR.PAR.999Y")


# ------------------------------------------------------------------ #
#                     mixed families and frequency                   #
# ------------------------------------------------------------------ #


def test_mixed_velocity_frequencies_are_refused(tb: CitiVelocityTB):
    """MI01 and DAILY are different data cached under different keys."""
    daily = _outright()
    intraday = CitiVeloQuery(citi_index=CURVE, tenor="10Y", freq="MI01", name="10Y MI01")
    with pytest.raises(ValueError, match="share a Velocity frequency"):
        tb.get_timeseries(START, END, [daily, intraday])


def test_vol_and_rates_queries_share_one_fetch(tb: CitiVelocityTB, fake_app: FakeExcelApp):
    """Tags are batched ACROSS queries, not per query."""
    vol = CitiVeloQuery(currency="USD", expiry="1Y", tenor="10Y", family="VOL")
    frame = tb.get_timeseries(START, END, [_outright(), vol])
    assert frame.shape[1] == 2
    assert len(fake_app.formulas_for("CVTSHIST")) == 1
    assert frame[vol.col_name()].iloc[-1] > 90.0  # normal vol, in bp


def test_plan_summary_explains_every_route(tb: CitiVelocityTB):
    """The router's decision is inspectable rather than implicit."""
    q_model = CitiVeloQuery(citi_index=CURVE, tenor="10Y", value=CitiVeloValue.QL_RATE)
    summary = tb.plan([_outright(), q_model]).summary()
    assert set(summary["route"]) == {"fast", "reprice"}
    assert summary.loc[summary["route"] == "reprice", "reason"].str.contains("QL_RATE").all()

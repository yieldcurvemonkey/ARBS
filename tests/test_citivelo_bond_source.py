r"""The Velocity bond SOURCE: the four quote-only FRB values and the MDP branch.

Hermetic - no Excel, no network, no disk cache. Reference data is a hand-built
frame and the vendor is the packaged COM fake, for the reason recorded in
``docs/citivelo_bonds_and_swapspreads_decisions.md`` (D0): the live add-in was at
7,639 MB against a 3,800 MB ceiling, and there were zero cached ``RATES.BOND``
tags to fall back on.

The claim under test
--------------------
``SPREAD_TSY``, ``OAS``, ``ASW_SPREAD`` and ``CAS`` are **quote-only**. Each needs
something this repo does not carry - an OAS needs a term-structure model and a
call schedule; a spread to Treasuries needs Citi's own benchmark choice - so
there is deliberately no local fallback. The failure mode being defended against
is not "the number is missing", it is "the number is 0.0 and looks like a
spread": a quote-only value that returns ``nan`` or ``0.0`` on a pricer from
another vendor is a silent wrong answer, and 0.0 is a perfectly plausible spread
to Treasuries.

So every one of these raises, and the message says which of the three causes it
was - wrong source, not served for this bond, or served-but-empty-in-this-window
- because the three have three different fixes.
"""

from __future__ import annotations

import dataclasses
import datetime

import pandas as pd
import pytest

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo  # type: ignore

from MDP.CitiVelocityExcel.bonds import values as V
from MDP.CitiVelocityExcel.bonds.fetcher import (
    DEFAULT_BOND_VALUES,
    CitiVeloBondFetcher,
    build_pricer_args,
)
from MDP.CitiVelocityExcel.bonds.resolution import resolve_bond
from MDP.CitiVelocityExcel.bonds.universe import BondUniverse
from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient
from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes
from MDP.CitiVelocityExcel.testing import FakeExcelApp, FakeVelocityData
from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
from Query.FixedRateBonds.FixedRateBondStructure import FixedRateBondPricableSpec
from Query.FixedRateBonds.FixedRateBondValue import (
    FixedRateBondValue,
    FixedRateBondValueFunctionMap,
)
from Query.Unified.registry import UnifiedValue

#: Real ISINs from the committed harvest, with real (and different) coverage.
ISIN_A = "US91282CNJ61"
CUSIP_A = "91282CNJ6"
ISIN_B = "US91282CCS89"
CUSIP_B = "91282CCS8"


def _unserved_value() -> str:
    """A value NO US Treasury serves, derived rather than named.

    These tests used to say "no US Treasury serves CAS" and "CUSIP_B does not
    serve ASW_4_USD". Both were artefacts of a ONE-WEEK probe window against a
    single bond: re-measured over five years, 304 of 349 USTs serve CAS and all
    349 serve ASW_4_USD. The property under test â€” a value the bond's own
    vocabulary lacks is reported as unavailable, never as an empty window â€” is
    unchanged, so it now asks the catalog which value has that shape.
    """
    from MDP.CitiVelocityExcel import tags as _T
    from MDP.CitiVelocityExcel.bonds.universe import BondUniverse

    uni = BondUniverse.from_catalog(country="USA", asset_type="GOVT")
    served = {v for d in uni for v in uni.available_values(d.isin)}
    missing = [v for v in _T.BOND_VALUES if v not in served]
    assert missing, "every value serves some UST; the unavailable case is unreachable"
    return missing[0]


UNSERVED_VALUE = _unserved_value()

AS_OF = datetime.date(2026, 8, 6)

_VALUES = {
    "PRICE": {CUSIP_A: 99.25, CUSIP_B: 88.50},
    "YIELD": {CUSIP_A: 4.11, CUSIP_B: 4.37},
    "DURATION": {CUSIP_A: 5.31, CUSIP_B: 4.62},
    "SPREAD_TSY": {CUSIP_A: -2.75, CUSIP_B: 6.25},
    "DV01": {CUSIP_A: 0.0527, CUSIP_B: 0.0409},
    "ASW_4_USD": {CUSIP_A: -23.6648},
}
_ISIN_OF = {CUSIP_A: ISIN_A, CUSIP_B: ISIN_B}


# ------------------------------------------------------------------ #
#                              plumbing                              #
# ------------------------------------------------------------------ #


def _fake_quotes(*, minutes: bool = False, bad_tags=()):
    """A real ``CitiVeloQuotes`` over the packaged COM fake.

    ``cache=False``: a default-constructed ``CitiVeloQuotes`` would write into the
    user's real cache directory and, on any miss, connect to a live Excel.

    ``minutes=True`` adds a fresh one-minute series ending now, which is what a
    LIVE request reads. Without it a live request resolves nothing and any
    assertion about live mode passes vacuously.

    ``bad_tags`` makes the add-in write ``Bad tag: <tag>`` into that column's first
    data cell while every other column answers normally - the per-column
    degradation ``CVTSHIST`` really has, and the shape of a transport failure that
    costs one value rather than the whole request.
    """
    # Runs to TODAY, not to a literal. The daily leg used to stop at the same
    # hardcoded 2026-08-06 as ``AS_OF``, which was "recent" on the day it was
    # written and decayed from there: once the calendar moved two days past it, a
    # LIVE request - whose window looks back five days from now - saw daily rows
    # up to 08-06, then a hole, then the minute block, measured the span at
    # one-day spacing and raised DownsampledWindowError. A fixture that only works
    # in the week it was written fails silently as a calendar bug rather than
    # loudly as a code one. Later rows cannot disturb the EOD tests: those ask for
    # AS_OF, which is an as-of search, not the end of the series.
    idx = pd.date_range("2026-07-01", max(pd.Timestamp(AS_OF), pd.Timestamp.now().normalize()), freq="D")
    series = {}
    for value, per_cusip in _VALUES.items():
        for cusip, number in per_cusip.items():
            series[f"RATES.BOND.{_ISIN_OF[cusip]}.{value}"] = pd.Series(number, index=idx)
    if minutes:
        now = pd.Timestamp.now().floor("min")
        m_idx = pd.date_range(now - pd.Timedelta(hours=2), now, freq="1min")
        for value, per_cusip in _VALUES.items():
            for cusip, number in per_cusip.items():
                series[f"RATES.BOND.{_ISIN_OF[cusip]}.{value}"] = pd.concat(
                    [series[f"RATES.BOND.{_ISIN_OF[cusip]}.{value}"],
                     pd.Series(number, index=m_idx)]
                )
    app = FakeExcelApp(
        data=FakeVelocityData(series=series, bad_tags=set(bad_tags)), pending_reads=0
    )
    workbook = app.Workbooks.Add()
    client = CitiVelocityExcelClient(app=app, workbook=workbook, drain_seconds=0.0)
    client._ws = workbook.Worksheets(1)
    return CitiVeloQuotes(client=client, cache=False), app


def _ref_df() -> pd.DataFrame:
    """The UST reference rows the alias resolver and the pricer builder need.

    Object-dtype dates on purpose: ``_filter_and_rank_ref_df`` compares the column
    against a ``datetime.date``, which raises on a datetime64 column.
    """
    return pd.DataFrame(
        [
            {
                "cusip": CUSIP_A, "oi": "7-Year",
                "issue_date": datetime.date(2025, 6, 30),
                "maturity_date": datetime.date(2032, 6, 30), "cpn": 4.0,
            },
            {
                "cusip": CUSIP_B, "oi": "10-Year",
                "issue_date": datetime.date(2021, 8, 15),
                "maturity_date": datetime.date(2031, 8, 15), "cpn": 1.25,
            },
        ]
    )


#: The default set plus ``OAS``. OAS is not fetched by default - it is
#: window-dependent, measured empty over one week and full over five years, and the
#: default 21-day EOD lookback cannot answer it - but it is the value these tests
#: use for the ``empty`` classification, so it is asked for explicitly here. Asking
#: for it and getting nothing IS the empty case; leaving it out of the request
#: would exercise the "you did not ask for it" message instead.
_REQUESTED_VALUES = tuple(DEFAULT_BOND_VALUES) + ("OAS",)


def _velocity_meta(cusip: str = CUSIP_A, backend: str = "QL") -> dict:
    """A pricer ``meta_data`` built by the real fetcher off the real catalog."""
    quotes, _ = _fake_quotes()
    resolution = resolve_bond(cusip, universe=BondUniverse.from_catalog(country="USA", asset_type="GOVT"))
    quote = CitiVeloBondFetcher(quotes=quotes).fetch(
        [resolution], AS_OF, values=_REQUESTED_VALUES
    )[_ISIN_OF[cusip]]
    row = _ref_df().set_index("cusip").loc[cusip].to_dict()
    row["cusip"] = cusip
    args = build_pricer_args(quote, backend=backend, ref_meta=row)
    args["meta_data"] = FixedRateBondsMDP._pyify_meta(args["meta_data"])
    return args["meta_data"]


def _pricer(meta: dict, cusip: str = CUSIP_A):
    from Query.FixedRateBonds.backends.quantlib.QLFixedRateBondPricer import QLFixedRateBondPricer

    row = _ref_df().set_index("cusip").loc[cusip]
    return QLFixedRateBondPricer(
        ql_frb_id="USTS",
        reference_date=AS_OF,
        issue_date=row["issue_date"],
        maturity_date=row["maturity_date"],
        cpn=float(row["cpn"]),
        clean_price=float(_VALUES["PRICE"][cusip]),
        meta_data=meta,
    )


def _spec(cusip: str = CUSIP_A) -> FixedRateBondPricableSpec:
    row = _ref_df().set_index("cusip").loc[cusip]
    return FixedRateBondPricableSpec(
        instrument=None,
        cusip=cusip,
        issue_date=row["issue_date"],
        maturity_date=row["maturity_date"],
        cpn=float(row["cpn"]),
        notional=100.0,
    )


def _value_map(*cusips, risk_weights=None):
    pricers = {c: _pricer(_velocity_meta(c), c) for c in cusips}
    package = [_spec(c) for c in cusips]
    weights = risk_weights if risk_weights is not None else [1.0] * len(cusips)
    return FixedRateBondValueFunctionMap(pricer=pricers, package=package, risk_weights=weights)


# ------------------------------------------------------------------ #
#                        the enum and the registry                   #
# ------------------------------------------------------------------ #


def test_the_four_new_members_exist_and_are_wired_into_the_map():
    for name in ("SPREAD_TSY", "OAS", "ASW_SPREAD", "CAS"):
        assert hasattr(FixedRateBondValue, name), name
    mapping = _value_map(CUSIP_A)._create_map()
    for member in (
        FixedRateBondValue.SPREAD_TSY,
        FixedRateBondValue.OAS,
        FixedRateBondValue.ASW_SPREAD,
        FixedRateBondValue.CAS,
    ):
        assert member in mapping, f"{member.name} is in the enum but not in _create_map"


def test_unified_value_picks_the_new_members_up_automatically():
    """``_build_unified_enum`` walks the product's value enum at import, so adding
    a member is supposed to be enough. Asserted rather than assumed - and it also
    kills a name typo, which would otherwise only surface at query time."""
    for name in ("FRB_SPREAD_TSY", "FRB_OAS", "FRB_ASW_SPREAD", "FRB_CAS"):
        assert hasattr(UnifiedValue, name), name
    assert UnifiedValue.FRB_SPREAD_TSY.name == "FRB_SPREAD_TSY"


def test_every_new_value_function_accepts_kwargs():
    """``BaseValueFunctionMap.apply`` calls ``func(**{**common, **extra})``, so a
    positional signature would blow up only when someone passed value_kwargs."""
    import inspect

    mapping = _value_map(CUSIP_A)._create_map()
    for member in (
        FixedRateBondValue.SPREAD_TSY,
        FixedRateBondValue.OAS,
        FixedRateBondValue.ASW_SPREAD,
        FixedRateBondValue.CAS,
    ):
        params = inspect.signature(mapping[member]).parameters.values()
        assert any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params), member.name


# ------------------------------------------------------------------ #
#                     quote-only: reading the number                 #
# ------------------------------------------------------------------ #


def test_spread_tsy_returns_citis_published_number():
    got = _value_map(CUSIP_A).apply(FixedRateBondValue.SPREAD_TSY)
    assert got == pytest.approx(_VALUES["SPREAD_TSY"][CUSIP_A])


def test_a_negative_spread_keeps_its_sign():
    """``calc_spread_rate`` takes abs() of every leg. A spread to Treasuries is
    signed - a rich bond trades through - and folding that away would turn -2.75
    into +2.75 with nothing to show for it."""
    assert _value_map(CUSIP_A).apply(FixedRateBondValue.SPREAD_TSY) < 0


def test_a_curve_of_spreads_is_not_multiplied_by_a_hundred():
    """``_ytm`` scales a 2-leg structure by 100 because a yield is in PERCENT and
    a spread of percents has to become basis points. These values are ALREADY
    basis points; reusing that factor would inflate every curve and fly 100x."""
    value_map = _value_map(CUSIP_A, CUSIP_B, risk_weights=[-1.0, 1.0])
    got = value_map.apply(FixedRateBondValue.SPREAD_TSY)
    expected = _VALUES["SPREAD_TSY"][CUSIP_B] - _VALUES["SPREAD_TSY"][CUSIP_A]
    assert got == pytest.approx(expected)
    assert abs(got) < 100, "a 100x scaling would put this at ~900"


def test_asw_spread_selects_the_leg_currency():
    got = _value_map(CUSIP_A).apply(FixedRateBondValue.ASW_SPREAD, asw_currency="USD")
    assert got == pytest.approx(_VALUES["ASW_4_USD"][CUSIP_A])


def test_asw_spread_defaults_to_usd():
    value_map = _value_map(CUSIP_A)
    assert value_map.apply(FixedRateBondValue.ASW_SPREAD) == pytest.approx(
        value_map.apply(FixedRateBondValue.ASW_SPREAD, asw_currency="USD")
    )


def test_an_unknown_asw_currency_names_the_legs_that_exist():
    """Otherwise ``asw_currency='usd '`` surfaces as "Citi does not serve this
    bond's asset swap", which sends the reader to look at coverage."""
    with pytest.raises(KeyError, match="No asset-swap leg for currency"):
        _value_map(CUSIP_A).apply(FixedRateBondValue.ASW_SPREAD, asw_currency="XYZ")


# ------------------------------------------------------------------ #
#                     quote-only: refusing to guess                  #
# ------------------------------------------------------------------ #


def test_a_non_velocity_pricer_raises_and_names_the_source():
    """The central guard. NaN or 0.0 here is a silent wrong answer."""
    pricer = _pricer({"cusip": CUSIP_A}, CUSIP_A)  # plain meta: any other source
    value_map = FixedRateBondValueFunctionMap(
        pricer={CUSIP_A: pricer}, package=[_spec(CUSIP_A)], risk_weights=[1.0]
    )
    with pytest.raises(V.QuoteNotServedError) as exc:
        value_map.apply(FixedRateBondValue.SPREAD_TSY)
    message = str(exc.value)
    assert "USTS_CITIVELO-QL" in message and "USTS_CITIVELO-RL" in message
    assert "QUOTE-ONLY" in message


def test_all_four_quote_only_values_refuse_a_non_velocity_pricer():
    pricer = _pricer({"cusip": CUSIP_A}, CUSIP_A)
    value_map = FixedRateBondValueFunctionMap(
        pricer={CUSIP_A: pricer}, package=[_spec(CUSIP_A)], risk_weights=[1.0]
    )
    for member in (
        FixedRateBondValue.SPREAD_TSY,
        FixedRateBondValue.OAS,
        FixedRateBondValue.ASW_SPREAD,
        FixedRateBondValue.CAS,
    ):
        with pytest.raises(V.QuoteNotServedError):
            value_map.apply(member)


def test_not_served_for_this_bond_says_so_rather_than_blaming_the_window():
    """A value no US Treasury serves at all. The message has to distinguish that
    from an empty window, because "widen the window" would be advice that cannot
    work.

    The value is DERIVED (see ``_unserved_value``) rather than named: this test
    used to name CAS on the belief that no UST served it, and 304 of 349 do.
    """
    from MDP.CitiVelocityExcel.bonds import values as _V

    meta = _velocity_meta()
    with pytest.raises(V.QuoteNotServedError, match=f"does not serve {UNSERVED_VALUE}"):
        _V.require_quoted(meta, UNSERVED_VALUE, subject=f"{UNSERVED_VALUE} for {CUSIP_A}")


def test_a_value_this_bond_serves_but_that_was_not_requested_says_that_instead():
    """The third message, and the only one whose fix IS to change the request."""
    quotes, _ = _fake_quotes()
    resolution = resolve_bond(CUSIP_A, universe=BondUniverse.from_catalog(country="USA", asset_type="GOVT"))
    quote = CitiVeloBondFetcher(quotes=quotes).fetch([resolution], AS_OF, values=["PRICE"])[ISIN_A]
    row = _ref_df().set_index("cusip").loc[CUSIP_A].to_dict()
    row["cusip"] = CUSIP_A
    meta = build_pricer_args(quote, backend="QL", ref_meta=row)["meta_data"]

    assert "SPREAD_TSY" in V.coverage_of(meta)["serves"]
    with pytest.raises(V.QuoteNotServedError, match="was not requested for this bond"):
        V.require_quoted(meta, "SPREAD_TSY")


def test_served_but_empty_says_widen_the_window():
    """OAS is in this bond's vocabulary and returned nothing in this window.
    Measured: empty over one week, full over five years. Telling the caller the
    bond has no OAS would be false for 1,401 of 2,162 ISINs."""
    with pytest.raises(V.QuoteNotServedError, match="no rows in the window"):
        _value_map(CUSIP_A).apply(FixedRateBondValue.OAS)


def test_a_value_outside_this_bonds_vocabulary_is_named_as_unavailable():
    """Re-measured, ALL six ASW_4_<CCY> legs serve all 349 US Treasuries, so the
    ASW matrix no longer provides an unavailable case on this universe. The
    property still holds and is exercised with the derived value instead."""
    from MDP.CitiVelocityExcel.bonds import values as _V

    meta = _velocity_meta()
    with pytest.raises(V.QuoteNotServedError, match="does not serve"):
        _V.require_quoted(meta, UNSERVED_VALUE, subject=UNSERVED_VALUE)


def test_one_bad_leg_fails_the_whole_structure():
    """A curve where only one leg has a quote must raise, not return the leg it
    happened to have. A half-priced spread is a number that means nothing."""
    value_map = _value_map(CUSIP_A, CUSIP_B, risk_weights=[-1.0, 1.0])
    with pytest.raises(V.QuoteNotServedError):
        value_map.apply(FixedRateBondValue.ASW_SPREAD, asw_currency="USD")


# ------------------------------------------------------------------ #
#                          the MDP branch                            #
# ------------------------------------------------------------------ #


@pytest.fixture()
def wired(monkeypatch):
    """A ``FixedRateBondsMDP`` with reference data stubbed and the pricer cache
    replaced by a dict.

    Neither is what is under test: the real ``update_reference_data`` fetches over
    the network, and the real pricer cache is a DiskCache in the user's home
    directory. The vendor seam is NOT stubbed - the fetcher runs for real against
    the packaged COM fake, which is where the interesting failures live.
    """
    ref = _ref_df()
    monkeypatch.setattr(
        "MDP.FixedRateBonds.reference_data_cache.ust_reference_data.update_reference_data",
        lambda source, source_kwargs=None, force_refresh=False: ref.copy(),
    )
    monkeypatch.setattr(FixedRateBondsMDP, "_ensure_pricer_cache", lambda self: None)

    def _make(source: str):
        mdp = FixedRateBondsMDP(source=source)
        setattr(mdp, FixedRateBondsMDP._FRB_PRICER_CACHE, {})
        return mdp

    return _make


def test_the_branch_builds_a_pricer_from_citis_price(wired):
    quotes, _ = _fake_quotes()
    mdp = wired("USTS_CITIVELO-QL")
    out = mdp._get_multi_pricers(
        cusips=[CUSIP_A], timestamp=AS_OF, kwargs={"citivelo_quotes": quotes}
    )
    assert list(out) == [CUSIP_A]
    pricer = out[CUSIP_A]
    assert pricer.clean_price() == pytest.approx(_VALUES["PRICE"][CUSIP_A])
    assert pricer.reference_date() == AS_OF


def test_the_ql_and_rl_suffixes_select_different_backends(wired):
    for source, expected in (
        ("USTS_CITIVELO-QL", "QLFixedRateBondPricer"),
        ("USTS_CITIVELO-RL", "RLFixedRateBondPricer"),
    ):
        quotes, _ = _fake_quotes()
        out = wired(source)._get_multi_pricers(
            cusips=[CUSIP_A], timestamp=AS_OF, kwargs={"citivelo_quotes": quotes}
        )
        assert type(out[CUSIP_A]).__name__ == expected


def test_the_alias_table_runs_before_the_velocity_resolver(wired):
    """``CT10`` reaches Citi as a CUSIP. This is what makes
    ``UnifiedQuery(cusip="CT10")`` work without a fourth alias implementation
    inside the Velocity package."""
    quotes, _ = _fake_quotes()
    out = wired("USTS_CITIVELO-QL")._get_multi_pricers(
        cusips=["CT10"], timestamp=AS_OF, kwargs={"citivelo_quotes": quotes}
    )
    assert list(out) == ["CT10"]
    assert out["CT10"].meta()["cusip"] == CUSIP_B, "CT10 is the on-the-run 10-year here"
    assert out["CT10"].meta()["isin"] == ISIN_B


def test_the_provenance_book_reaches_the_pricer(wired):
    quotes, _ = _fake_quotes()
    out = wired("USTS_CITIVELO-QL")._get_multi_pricers(
        cusips=[CUSIP_A], timestamp=AS_OF, kwargs={"citivelo_quotes": quotes}
    )
    meta = out[CUSIP_A].meta()
    assert V.is_velocity_meta(meta)
    assert V.provenance_of(meta, "SPREAD_TSY").origin == "quoted"
    assert V.provenance_of(meta, "YTM").origin == "computed"
    assert V.provenance_of(meta, "CLEAN_PRICE").verified is True


def test_a_pricer_from_the_branch_answers_the_quote_only_values(wired):
    """End to end: MDP branch -> pricer -> FRB value."""
    quotes, _ = _fake_quotes()
    out = wired("USTS_CITIVELO-QL")._get_multi_pricers(
        cusips=[CUSIP_A], timestamp=AS_OF, kwargs={"citivelo_quotes": quotes}
    )
    value_map = FixedRateBondValueFunctionMap(
        pricer={CUSIP_A: out[CUSIP_A]}, package=[_spec(CUSIP_A)], risk_weights=[1.0]
    )
    assert value_map.apply(FixedRateBondValue.SPREAD_TSY) == pytest.approx(
        _VALUES["SPREAD_TSY"][CUSIP_A]
    )


def test_a_single_cusip_request_is_answered_by_the_same_branch(wired):
    """Without the delegation in ``_get_single_pricer`` a one-CUSIP request falls
    through to the blocks below and is answered by a DIFFERENT vendor."""
    quotes, _ = _fake_quotes()
    pricer = wired("USTS_CITIVELO-QL")._get_single_pricer(
        cusip=CUSIP_A, timestamp=AS_OF, kwargs={"citivelo_quotes": quotes}
    )
    assert pricer is not None
    assert V.is_velocity_meta(pricer.meta())


def test_the_branch_asks_the_vendor_for_only_what_each_bond_serves(wired):
    quotes, app = _fake_quotes()
    wired("USTS_CITIVELO-QL")._get_multi_pricers(
        cusips=[CUSIP_A, CUSIP_B], timestamp=AS_OF, kwargs={"citivelo_quotes": quotes}
    )
    asked = set()
    for formula in app.formulas_for("CVTSHIST"):
        asked.update(t.strip() for t in formula.split('"')[1].split(","))
    # All 349 USTs serve ASW_4_USD (re-measured), so the discriminator is the
    # value NO bond serves: it must never be asked for, for either bond.
    assert f"RATES.BOND.{ISIN_A}.ASW_4_USD" in asked
    assert f"RATES.BOND.{ISIN_B}.ASW_4_USD" in asked
    assert not [t for t in asked if t.endswith(f".{UNSERVED_VALUE}")], (
        f"no US Treasury serves {UNSERVED_VALUE}; it must never be requested"
    )


def test_an_eod_request_is_cached_and_a_live_one_is_not(wired):
    """An EOD quote is a fixed historical fact. Caching "live" under today's date
    would serve the 09:31 print at 16:00 and still call it live.

    The live half asserts a pricer was actually BUILT before asserting nothing was
    cached. Without that, a live request that resolved nothing at all would leave
    an empty cache and the test would pass for the wrong reason - which is exactly
    what it did before the fake was given a minute series.
    """
    quotes, _ = _fake_quotes()
    mdp = wired("USTS_CITIVELO-QL")
    mdp._get_multi_pricers(cusips=[CUSIP_A], timestamp=AS_OF, kwargs={"citivelo_quotes": quotes})
    cache = getattr(mdp, FixedRateBondsMDP._FRB_PRICER_CACHE)
    assert list(cache) == [f"{AS_OF.isoformat()}-{CUSIP_A}-USTS_CITIVELO-QL"]

    quotes2, _ = _fake_quotes(minutes=True)
    live = wired("USTS_CITIVELO-QL")
    out = live._get_multi_pricers(
        cusips=[CUSIP_A], timestamp="live", kwargs={"citivelo_quotes": quotes2}
    )
    assert CUSIP_A in out, "live built no pricer, so the cache assertion below means nothing"
    assert out[CUSIP_A].meta()["citivelo_mode"] == "live"
    assert getattr(live, FixedRateBondsMDP._FRB_PRICER_CACHE) == {}


def test_a_second_eod_request_is_served_from_the_cache_without_the_vendor(wired):
    quotes, app = _fake_quotes()
    mdp = wired("USTS_CITIVELO-QL")
    mdp._get_multi_pricers(cusips=[CUSIP_A], timestamp=AS_OF, kwargs={"citivelo_quotes": quotes})
    calls = len(app.formulas_for("CVTSHIST"))

    out = mdp._get_multi_pricers(cusips=[CUSIP_A], timestamp=AS_OF, kwargs={"citivelo_quotes": quotes})
    assert len(app.formulas_for("CVTSHIST")) == calls, "the cached bond was refetched"
    assert V.is_velocity_meta(out[CUSIP_A].meta()), "the cached args lost the provenance book"


def test_the_cached_args_survive_a_real_pickle_round_trip(wired):
    """The pricer cache is a DiskCache, which PICKLES. The tests above use a dict,
    so this is the one that proves the provenance and quoted books are not merely
    "still in memory" - it round-trips them the way the real cache does and then
    reads a quote-only value back out.

    It also pins the nested books to plain Python scalars. ``_pyify_meta`` maps
    only TOP-LEVEL values - it does not descend - so the quoted, coverage and
    provenance books are outside its reach and have to keep themselves clean.

    The type check is deliberately ``type(v) is float`` rather than
    ``json.dumps``: ``numpy.float64`` **subclasses** ``float``, so it serialises
    to JSON without complaint and a ``json.dumps`` assertion here was measured to
    survive every mutation that removed the ``float()`` coercions. An identity
    check on the type is what actually catches it.
    """
    import pickle

    quotes, _ = _fake_quotes()
    mdp = wired("USTS_CITIVELO-QL")
    mdp._get_multi_pricers(cusips=[CUSIP_A], timestamp=AS_OF, kwargs={"citivelo_quotes": quotes})
    args = getattr(mdp, FixedRateBondsMDP._FRB_PRICER_CACHE)[
        f"{AS_OF.isoformat()}-{CUSIP_A}-USTS_CITIVELO-QL"
    ]

    quoted_book = args["meta_data"][V.QUOTED_KEY]
    assert quoted_book
    for value, number in quoted_book.items():
        assert type(number) is float, f"{value} is {type(number).__name__}, not a plain float"
    for key, book in args["meta_data"][V.PROVENANCE_KEY].items():
        for field, item in book.items():
            assert type(item) in (str, bool), f"{key}.{field} is {type(item).__name__}"

    revived = pickle.loads(pickle.dumps(args))
    assert revived == args
    pricer = FixedRateBondsMDP._build_pricer_from_args(
        revived, issue_date_key="issue_date", maturity_date_key="maturity_date", cpn_key="cpn"
    )
    meta = pricer.meta()
    assert V.require_quoted(meta, "SPREAD_TSY") == pytest.approx(_VALUES["SPREAD_TSY"][CUSIP_A])
    assert V.provenance_of(meta, "YTM").origin == "computed"


def test_citis_yield_and_the_computed_ytm_are_kept_apart(wired):
    """They are different numbers, and the provenance says which is which.

    Recording YTM as "quoted" because Citi published a yield in the same response
    would be a false audit trail - the pricer is built from PRICE and re-solves
    its own yield, so what FRB_YTM returns is the computed one.
    """
    quotes, _ = _fake_quotes()
    out = wired("USTS_CITIVELO-QL")._get_multi_pricers(
        cusips=[CUSIP_A], timestamp=AS_OF, kwargs={"citivelo_quotes": quotes}
    )
    meta = out[CUSIP_A].meta()
    assert V.quoted_value_of(meta, "YIELD") == pytest.approx(_VALUES["YIELD"][CUSIP_A])
    assert V.provenance_of(meta, "YIELD").origin == "quoted"
    assert V.provenance_of(meta, "YTM").origin == "computed"
    # The pricer's own yield is a separate number reached a separate way. Bounded
    # rather than merely "not equal to Citi's": `!= approx(4.11, abs=1e-9)` passes
    # for any two distinct floats, including 41.1, so it survives a pricer that has
    # gone wildly wrong. This bond is a 4% coupon at 99.25 with ~7y to run, so its
    # yield is a few bp the far side of the coupon and nowhere near Citi's 4.11.
    ytm = out[CUSIP_A].ytm()
    assert 4.0 < ytm < 4.3, f"the re-solved yield is implausible: {ytm}"
    assert abs(ytm - _VALUES["YIELD"][CUSIP_A]) > 1e-6, "and it is not Citi's number"


def test_a_bond_citi_does_not_quote_does_not_lose_the_rest_of_the_basket(wired, monkeypatch):
    """Citi carries a liquid 349-name UST subset, not the whole universe. One
    off-the-run in a 300-name warm must not take the other 299 with it."""
    ref = _ref_df()
    ref = pd.concat(
        [
            ref,
            pd.DataFrame([{
                "cusip": "912810FT0", "oi": "30-Year",
                "issue_date": datetime.date(2005, 2, 15),
                "maturity_date": datetime.date(2035, 2, 15), "cpn": 4.5,
            }]),
        ],
        ignore_index=True,
    )
    monkeypatch.setattr(
        "MDP.FixedRateBonds.reference_data_cache.ust_reference_data.update_reference_data",
        lambda source, source_kwargs=None, force_refresh=False: ref.copy(),
    )
    quotes, _ = _fake_quotes()
    out = wired("USTS_CITIVELO-QL")._get_multi_pricers(
        cusips=[CUSIP_A, "912810FT0"], timestamp=AS_OF, kwargs={"citivelo_quotes": quotes}
    )
    assert CUSIP_A in out
    assert "912810FT0" not in out


# ------------------------------------------------------------------ #
#           the pricer classifies as what it actually is             #
# ------------------------------------------------------------------ #


def test_a_velocity_eod_pricer_is_classified_eod_by_the_real_carry_roll_classifiers(wired):
    """``meta['timestamp']`` decides which VENDOR carry/roll expands against.

    ``carry_roll._infer_pricing_timestamp`` branches on ``ts.tzinfo is not None``
    BEFORE its midnight-means-date rule, and ``_infer_universe_source`` then keys
    off whether the result is a datetime. This branch was the only one in
    ``FixedRateBondsMDP`` writing an OFFSET-BEARING timestamp, so an EOD Velocity
    pricer classified as intraday and ``FRB_CARRY_BPS_RUNNING`` expanded its
    universe against ``USTS_WEBULL_WSJ_LIVE-RL`` - a live intraday broker feed,
    over the network - at a historical midnight.

    Both classifiers are the real ones and the pricer is the real one; only the
    timestamp spelling is varied, on the same object, so the assertion is about the
    field rather than about a constructed dict.
    """
    from Query.FixedRateBonds.carry_roll import (
        _infer_pricing_timestamp,
        _infer_universe_source,
    )

    quotes, _ = _fake_quotes()
    out = wired("USTS_CITIVELO-RL")._get_multi_pricers(
        cusips=[CUSIP_A], timestamp=AS_OF, kwargs={"citivelo_quotes": quotes}
    )
    pricers = {CUSIP_A: out[CUSIP_A]}

    stamp = _infer_pricing_timestamp(pricers, AS_OF)
    assert isinstance(stamp, datetime.date) and not isinstance(stamp, datetime.datetime)
    assert stamp == AS_OF
    assert _infer_universe_source(pricers, stamp) == "USTS_FEDINVEST_WSJ_LIVE-QL"

    # The spelling that used to be written here, on the same pricer.
    meta = out[CUSIP_A].meta()
    assert meta["citivelo_as_of"].endswith("-04:00"), "the wire offset is still recorded"
    meta["timestamp"] = meta["citivelo_as_of"]
    offset_stamp = _infer_pricing_timestamp(pricers, AS_OF)
    assert isinstance(offset_stamp, datetime.datetime)
    assert _infer_universe_source(pricers, offset_stamp) == "USTS_WEBULL_WSJ_LIVE-RL"


def test_the_live_reference_date_comes_from_the_wire_zone_not_the_machine(wired, monkeypatch):
    """Everything else in this package is anchored to the wire zone, including
    ``fetcher._window_bounds``; the live reference-data date was the MACHINE-local
    one. Run from London at 02:00 BST (21:00 the previous day in New York) it
    resolves ``CT10`` against a date on which the current on-the-run may not yet be
    eligible, so the alias resolves to a different CUSIP from the one the quotes
    were fetched for.

    Two zones 25 hours apart are used because their calendar dates ALWAYS differ,
    which makes the assertion independent of when the suite runs.
    """
    import MDP.FixedRateBonds.FixedRateBondsMDP as mdp_module

    seen = []
    real = mdp_module._filter_and_rank_ref_df

    def _record(df, as_of, *args, **kwargs):
        seen.append(as_of)
        return real(df, as_of, *args, **kwargs)

    monkeypatch.setattr(mdp_module, "_filter_and_rank_ref_df", _record)

    for zone in ("Pacific/Kiritimati", "Pacific/Midway"):
        monkeypatch.setenv("CITIVELO_EXCEL_WIRE_TZ", zone)
        quotes, _ = _fake_quotes(minutes=True)
        wired("USTS_CITIVELO-QL")._get_multi_pricers(
            cusips=[CUSIP_A], timestamp="live", kwargs={"citivelo_quotes": quotes}
        )
        expected = datetime.datetime.now(ZoneInfo(zone)).date()
        assert seen[-1] == expected, f"{zone}: reference date {seen[-1]} is not the wire date"

    assert seen[0] != seen[1], "UTC+14 and UTC-11 are never on the same calendar date"


def test_a_programming_error_in_the_builder_is_not_reported_as_missing_data(wired, monkeypatch):
    """The branch drops a bond on a bond-level failure and on nothing else.

    ``build_pricer_args`` raises plain ``ValueError`` for an unknown backend, and
    ``float()`` raises it for a non-numeric cell. Catching the base class turned
    "every bond in this basket hit a bug" into an empty dict plus a WARNING line
    reading like Citi had no data.
    """
    def _boom(*args, **kwargs):
        raise ValueError("backend='ql' is not a backend token")

    monkeypatch.setattr("MDP.CitiVelocityExcel.bonds.fetcher.build_pricer_args", _boom)
    quotes, _ = _fake_quotes()
    with pytest.raises(ValueError, match="not a backend token"):
        wired("USTS_CITIVELO-QL")._get_multi_pricers(
            cusips=[CUSIP_A], timestamp=AS_OF, kwargs={"citivelo_quotes": quotes}
        )


def test_a_bond_with_no_price_still_only_costs_itself(wired, monkeypatch):
    """The other half of the same rule: the narrowed except must still catch the
    case it was written for, or one illiquid bond takes the basket with it."""
    def _no_price(*args, **kwargs):
        raise V.NoQuotedPriceError("no PRICE row in this window")

    monkeypatch.setattr("MDP.CitiVelocityExcel.bonds.fetcher.build_pricer_args", _no_price)
    quotes, _ = _fake_quotes()
    out = wired("USTS_CITIVELO-QL")._get_multi_pricers(
        cusips=[CUSIP_A], timestamp=AS_OF, kwargs={"citivelo_quotes": quotes}
    )
    assert out == {}


# ------------------------------------------------------------------ #
#            what the refusal messages are allowed to claim          #
# ------------------------------------------------------------------ #


def test_a_failed_tag_is_not_answered_with_widen_the_window(wired):
    """A rejected tag and an empty window are different answers.

    ``CVTSHIST`` degrades per column, so one bad tag costs its own value; reporting
    that as ``empty`` sends the caller to widen a window, which cannot work. The
    fake writes ``Bad tag: <tag>`` into that column exactly as the add-in does.
    """
    bad = f"RATES.BOND.{ISIN_A}.SPREAD_TSY"
    quotes, _ = _fake_quotes(bad_tags={bad})
    out = wired("USTS_CITIVELO-QL")._get_multi_pricers(
        cusips=[CUSIP_A], timestamp=AS_OF, kwargs={"citivelo_quotes": quotes}
    )
    meta = out[CUSIP_A].meta()
    assert "SPREAD_TSY" in V.coverage_of(meta)["failed"]
    assert "SPREAD_TSY" not in V.coverage_of(meta)["empty"]
    assert "bad tag" in V.failures_of(meta)["SPREAD_TSY"]

    value_map = FixedRateBondValueFunctionMap(
        pricer={CUSIP_A: out[CUSIP_A]}, package=[_spec(CUSIP_A)], risk_weights=[1.0]
    )
    with pytest.raises(V.QuoteNotServedError) as exc:
        value_map.apply(FixedRateBondValue.SPREAD_TSY)
    message = str(exc.value)
    assert "FAILED" in message and "bad tag" in message
    assert "Widen" not in message, "a transport failure is not fixed by a wider window"


def test_a_bond_the_sweep_never_covered_is_an_open_question_not_a_coverage_fact():
    """``available_values == []`` for fifteen of the 2,162 ISINs because the sweep
    missed them, not because Citi serves nothing. The message has to say which."""
    unswept = "CND0000002K8"
    resolution = resolve_bond(unswept, universe=BondUniverse.from_catalog())
    assert resolution.available_values == ()

    quotes, _ = _fake_quotes()
    quote = CitiVeloBondFetcher(quotes=quotes).fetch(
        [resolution], AS_OF, values=["PRICE", "SPREAD_TSY"]
    )[unswept]
    meta = {
        V.QUOTED_KEY: quote.quoted_book(),
        V.COVERAGE_KEY: quote.coverage_book(),
        V.FAILURES_KEY: quote.failure_book(),
    }

    with pytest.raises(V.QuoteNotServedError) as exc:
        V.require_quoted(meta, "SPREAD_TSY", subject=f"SPREAD_TSY for {unswept}")
    message = str(exc.value)
    assert "NEVER VALIDATED" in message
    assert "does not serve" not in message, "the sweep never asked, so it cannot say that"
    assert unswept in message


def test_every_refusal_names_the_leg_it_is_about():
    """``subject`` used to reach only the first of the messages, so a three-leg fly
    failed with "this bond" and no CUSIP anywhere - leaving the caller to re-run
    each leg singly to find out which one it was."""
    with pytest.raises(V.QuoteNotServedError, match=CUSIP_A):
        _value_map(CUSIP_A).apply(FixedRateBondValue.CAS)              # not served
    with pytest.raises(V.QuoteNotServedError, match=CUSIP_A):
        _value_map(CUSIP_A).apply(FixedRateBondValue.OAS)              # served, empty
    with pytest.raises(V.QuoteNotServedError, match=CUSIP_B):
        _value_map(CUSIP_A, CUSIP_B, risk_weights=[-1.0, 1.0]).apply(
            FixedRateBondValue.ASW_SPREAD, asw_currency="USD"
        )


def test_a_pricer_whose_meta_raises_does_not_impersonate_the_wrong_source():
    """``_vendor_quote`` used to wrap ``pricer.meta()`` in a bare
    ``except Exception: meta = {}``, so ANY failure - a corrupted DiskCache entry,
    an AttributeError from a refactor - came back as the FIRST of require_quoted's
    causes: "this pricer did not come from the Velocity source. Build it with
    FixedRateBondsMDP(source='USTS_CITIVELO-QL')". That instructs the user to do
    what they already did, and destroys the traceback that would have said why."""
    class _CorruptedPricer:
        def meta(self):
            raise RuntimeError("unpickling the DiskCache entry failed")

    value_map = FixedRateBondValueFunctionMap(
        pricer={CUSIP_A: _CorruptedPricer()},
        package=[_spec(CUSIP_A)],
        risk_weights=[1.0],
    )
    with pytest.raises(RuntimeError, match="unpickling the DiskCache entry failed"):
        value_map.apply(FixedRateBondValue.SPREAD_TSY)


# ------------------------------------------------------------------ #
#                    provenance carries its standing                 #
# ------------------------------------------------------------------ #


def test_a_computed_number_tracks_the_standing_of_the_quote_it_came_from():
    """``verified`` exists so a consumer can filter on it. Hardcoding ``True`` for
    every computed value inverted it: CLEAN_PRICE declared its clean-vs-dirty
    uncertainty (worth 0.0163 to 3.1844 price points) and the seven numbers solved
    FROM that price all claimed to be verified, so a filter kept the derived ones
    and dropped the only one that told the truth."""
    meta = _velocity_meta()
    price = V.provenance_of(meta, "CLEAN_PRICE")

    # The invariant is PROPAGATION, not a particular value. PRICE's reading was
    # measured on 2026-08-07 and is now verified, so the seven numbers solved
    # from it are too - but they must still track it rather than hardcode
    # anything, which is what the original defect did in the other direction.
    for name in ("YTM", "MOD_DURATION", "PV01", "DV01", "NPV", "DIRTY_PRICE", "CONVEXITY"):
        prov = V.provenance_of(meta, name)
        assert prov.origin == "computed", name
        assert prov.verified is price.verified, (
            f"{name} reports verified={prov.verified} while the CLEAN_PRICE it was "
            f"solved from reports {price.verified}: a derived number cannot be better "
            "established than its input"
        )
        if not price.verified:
            # The caveat is attached only when there is something to caveat;
            # a verified input needs no disclaimer trailing every derived number.
            assert "Inherits the standing of its input" in prov.note, name


def test_a_number_solved_from_an_unverified_quote_inherits_that(monkeypatch):
    """The other direction, forced: make the input unverified and every number
    solved from it must follow. Without this the propagation test above would
    pass on a hardcoded ``True`` now that PRICE is measured."""
    spec = V.CITI_BOND_VALUES["PRICE"]
    monkeypatch.setitem(
        V.CITI_BOND_VALUES, "PRICE",
        dataclasses.replace(spec, verified=False, note="forced unverified for this test"),
    )
    meta = _velocity_meta()
    assert V.provenance_of(meta, "CLEAN_PRICE").verified is False
    for name in ("YTM", "MOD_DURATION", "DV01"):
        assert V.provenance_of(meta, name).verified is False, name

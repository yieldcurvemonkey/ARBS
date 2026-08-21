r"""Intraday convexity adjustment — the transport, pinned.

A preflight investigation reported that ``IRSwapQuery.build_mdp_request``
"silently date-truncates ``CVX_ADJ``", so an intraday request would return an EOD
number with no error, and concluded that reaching an instant needed a code
change. That is half right and the half that is wrong matters: the truncation is
real **on the default path**, but the Query layer already carries a mechanism for
asking for an instant, and ``CVX_ADJ`` can use it today.

``BaseQuery.build_mdp_request`` injects ``_request_date(now)`` when
``mdp_time_key`` is absent from ``market_request``, and ``_request_datetime(now)``
when it is present with the literal value ``"now"``. So::

    market_request={"timestamp": "now"}

is the supported way to reach an instant, and it is the same sentinel the STIR
futures query uses — where its absence is already recorded in this codebase as
the reason a request came back with EOD zeros.

``CVX_ADJ_EMPIRICAL`` overrides ``build_mdp_request`` to pass a datetime
*unconditionally*, which is why it looked like the only value that could go
intraday. It is not; it is the only one that goes intraday **without being
asked**.

Pinning this matters because the difference is invisible in the result. Both
paths return a number. Only the type of ``request["timestamp"]`` says which
instant it belongs to, and an EOD number silently standing in for a 15:00 one is
exactly the class of error the convexity work has already been bitten by twice.
"""

from __future__ import annotations

import datetime
import os
import zoneinfo

import pytest

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue

NOW = datetime.datetime(2026, 8, 19, 15, 0, 0)
EFF = datetime.date(2026, 9, 16)
MAT = datetime.date(2027, 9, 15)


def _q(value=IRSwapValue.CVX_ADJ, market_request=None) -> IRSwapQuery:
    return IRSwapQuery(
        curve="USD-SOFR-1D", structure=IRSwapStructure.OUTRIGHT, value=value,
        effective_date=EFF, maturity_date=MAT, structure_kwargs={"bpv": 1},
        market_request=market_request,
    )


def test_the_default_path_really_does_truncate_to_a_date():
    """The half of the report that is right, asserted so it stays visible."""
    ts = _q().build_mdp_request(NOW)["timestamp"]
    assert isinstance(ts, datetime.date) and not isinstance(ts, datetime.datetime)
    assert ts == NOW.date()


def test_the_now_sentinel_delivers_the_instant_to_cvx_adj():
    """The half that is wrong: no code change is needed to go intraday."""
    ts = _q(market_request={"timestamp": "now"}).build_mdp_request(NOW)["timestamp"]
    assert isinstance(ts, datetime.datetime), (
        "the 'now' sentinel no longer reaches CVX_ADJ; intraday convexity has "
        "lost its transport"
    )
    assert ts == NOW
    assert ts.hour == 15 and ts.minute == 0


def test_an_explicit_instant_is_passed_through_untouched():
    """A concrete timestamp must not be rewritten to either end of the day."""
    pinned = datetime.datetime(2026, 8, 19, 11, 32)
    ts = _q(market_request={"timestamp": pinned}).build_mdp_request(NOW)["timestamp"]
    assert ts == pinned


def test_empirical_is_the_one_that_goes_intraday_unasked():
    """Why the default looked like the only intraday-capable value."""
    ts = _q(value=IRSwapValue.CVX_ADJ_EMPIRICAL).build_mdp_request(NOW)["timestamp"]
    assert isinstance(ts, datetime.datetime) and ts == NOW


def test_live_survives_every_path():
    """``"live"`` is a literal, not a time, and must not be coerced."""
    for mr in ({"timestamp": "live"},):
        assert _q(market_request=mr).build_mdp_request(NOW)["timestamp"] == "live"
        assert _q(value=IRSwapValue.CVX_ADJ_EMPIRICAL,
                  market_request=mr).build_mdp_request(NOW)["timestamp"] == "live"


def test_the_sentinel_changes_the_cache_fingerprint_not_at_all():
    """``market_request`` is NOT part of ``_query_fingerprint``.

    Worth knowing before an intraday series is cached next to a daily one: the
    fingerprint covers tenor, dates, structure, value, ``structure_kwargs``,
    name, risk weight and ``value_kwargs`` — not ``market_request``. So a daily
    and an intraday query for the same instrument hash **identically**, and only
    the timestamp in the cache key separates them. That is fine for the mapping
    cache, which is keyed by epoch-ns, and is a trap for anything that keys on
    the fingerprint alone.
    """
    from TB.IRSwapsTB import _query_fingerprint

    assert _query_fingerprint(_q()) == _query_fingerprint(
        _q(market_request={"timestamp": "now"})), (
        "market_request has entered the fingerprint; the note in this test is "
        "now wrong and intraday/daily rows no longer collide"
    )
# ===========================================================================
# The intraday CA path -- transport, guards, and one real number
# ===========================================================================
# Everything below runs OFFLINE. The pure-function tests need nothing; the
# integration tests read the local diskcache and the local CurveStore and skip
# if either is cold, because a machine without the warm is a different machine,
# not a failure.

import pandas as pd                                              # noqa: E402

from RVUtils.ConvexityRV import ca_intraday as CI                 # noqa: E402

CT = zoneinfo.ZoneInfo("America/Chicago")
ET = zoneinfo.ZoneInfo("America/New_York")

#: The pinned instant. 2026-08-19 15:00 ET = 14:00 CT = 19:00 UTC. Chosen
#: because it is the deepest, densest date on the local minute tape (1,384
#: distinct minute stamps, contiguous strip depth 17) and because the value it
#: produces is quoted in the module docstring of ``ca_intraday``.
PINNED = datetime.datetime(2026, 8, 19, 15, 0, tzinfo=ET)

#: WHITES at ``PINNED``, quarterly/quarterly matched swap, measured 2026-08-20
#: with network blocked. Recomputed here rather than trusted: the point of the
#: number is that the transport is deterministic.
PINNED_WHITES_BP = 0.25301331915636993


# --------------------------------------------------------------------------
# Instants and keys
# --------------------------------------------------------------------------
def test_a_naive_timestamp_is_refused_rather_than_localised():
    """The single most expensive mistake available on this path.

    ``STIRFutureMDP._as_datetime`` localises a naive datetime to *New York*. The
    tape is keyed in Chicago wall clock, so a naive request is both an hour out
    and a cache miss -- and a miss on this source is a Barchart crawl (measured:
    20 blocked calls for ONE symbol). Guessing a zone is therefore not a
    convenience, it is the bug.
    """
    with pytest.raises(CI.IntradayTimestampError, match="naive"):
        CI.tape_instant(datetime.datetime(2026, 8, 19, 14, 0))


def test_a_date_and_a_sentinel_are_refused_too():
    """A date means the 17:00 settle; 'live'/'now' mean the vendor."""
    with pytest.raises(CI.IntradayTimestampError):
        CI.tape_instant(datetime.date(2026, 8, 19))
    with pytest.raises(CI.IntradayTimestampError):
        CI.tape_instant("now")


def test_the_key_spelling_follows_daylight_saving():
    """A frozen UTC offset is correct for half the year and a crawl for the other.

    The tape stamps ``-05:00`` in August and ``-06:00`` in January, so the zone
    has to be a ``ZoneInfo`` name. Both spellings are verified against keys that
    exist on this machine (2026-08-19 and 2026-01-15 both carry a 14:00 Chicago
    bar).
    """
    aug = CI.tape_key(datetime.datetime(2026, 8, 19, 15, 0, tzinfo=ET), "SR3U26")
    jan = CI.tape_key(datetime.datetime(2026, 1, 15, 15, 0, tzinfo=ET), "SR3H26")
    assert aug == "2026-08-19T14:00:00-05:00-SR3U26-BARCHART_TOS_LIVE_STIRF-RL"
    assert jan == "2026-01-15T14:00:00-06:00-SR3H26-BARCHART_TOS_LIVE_STIRF-RL"


def test_both_key_families_are_probed_and_utc_goes_first():
    """The tape is written in two spellings and neither covers it alone.

    Scanned over all 12,772,278 local keys: 2018-2021 is a UTC tape, 2026 is
    predominantly a Chicago one, and 741 of 1,667 dates carry both. Probing one
    family silently halves the reachable universe -- and the MDP itself probes
    UTC first, so the order here is not cosmetic: it decides which spelling gets
    recorded as a row's provenance.
    """
    keys = CI.tape_keys(PINNED, "SR3U26")
    assert len(keys) == 2
    assert keys[0].startswith("2026-08-19T19:00:00+00:00")
    assert keys[1].startswith("2026-08-19T14:00:00-05:00")


def test_the_two_spellings_parse_back_to_one_instant():
    """What makes 'did every leg resolve to the same minute' answerable."""
    a, b = CI.tape_keys(PINNED, "SR3U26")
    assert CI.key_stamp(a, "SR3U26") == CI.key_stamp(b, "SR3U26")
    assert CI.key_stamp(a, "SR3U26") == pd.Timestamp("2026-08-19T19:00:00Z")


def test_a_sub_minute_request_lands_on_the_bar_that_covers_it():
    """The tape is one bar a minute; a request at 15:00:37 means that bar.

    Not flooring would be worse than an error: the key would carry the seconds,
    miss every candidate, and the miss goes to Barchart. So the seconds are
    dropped here rather than left to fail 20 HTTP requests later.
    """
    exact = CI.tape_instant(datetime.datetime(2026, 8, 19, 15, 0, 37, 500000, tzinfo=ET))
    assert exact == CI.tape_instant(PINNED)
    assert CI.tape_key(datetime.datetime(2026, 8, 19, 15, 0, 37, tzinfo=ET), "SR3U26") \
        == "2026-08-19T14:00:00-05:00-SR3U26-BARCHART_TOS_LIVE_STIRF-RL"


def test_an_instant_close_to_now_is_refused():
    """Inside 15 minutes the MDP stops reading the cache at all.

    ``_should_use_live_quotes`` returns True, which sets ``read_cache=False``
    and answers from the Schwab quote API. That is network *and* a third price
    source inside a series that claims to be Barchart minute bars, so a cached
    minute in that window is not a defence.
    """
    now = datetime.datetime(2026, 8, 19, 19, 5, tzinfo=datetime.timezone.utc)
    with pytest.raises(CI.IntradayTimestampError, match="live"):
        CI.assert_offline_instant(PINNED, now=now)
    # ... and one comfortably in the past is fine
    later = datetime.datetime(2026, 8, 20, 19, 0, tzinfo=datetime.timezone.utc)
    assert CI.assert_offline_instant(PINNED, now=later).hour == 14


def test_the_settle_source_is_refused_as_an_intraday_source():
    """A settle source answers a datetime with the 17:00 mark and says nothing."""
    with pytest.raises(ValueError, match="not an intraday quote feed"):
        CI.assert_intraday_source("BARCHART_STIRF-RL")
    assert CI.assert_intraday_source("BARCHART_TOS_LIVE_STIRF-RL")


# --------------------------------------------------------------------------
# The splice guard
# --------------------------------------------------------------------------
def _intraday_frame(v=1.0):
    return pd.DataFrame({"timestamp": [pd.Timestamp("2026-08-19T19:00:00Z")],
                         "cvx_adj_bp": [v],
                         CI.PRICE_SOURCE_COL: [CI.PRICE_SOURCE_INTRADAY]})


def test_an_untagged_frame_reads_as_a_settle_frame():
    """The safe direction, and not a guess: the daily path is the only producer
    of untagged CA frames and it is settle-marked by construction."""
    assert CI.price_source_of(pd.DataFrame({"x": [1.0]})) == CI.PRICE_SOURCE_SETTLE


def test_concat_refuses_to_splice_intraday_onto_settles():
    """Measured on 2026-08-19: the settle strip and the 15:00 ET minute strip
    differ by up to 3.5 bp of price, and the REDS CA computed off each differs
    by 4.59 bp against a level of 0.8 bp. That is not noise added to a signal,
    it is two signals interleaved."""
    with pytest.raises(CI.IntradaySpliceError):
        CI.concat_ca_frames([_intraday_frame(), CI.tag_settle_frame(_intraday_frame())])
    with pytest.raises(CI.IntradaySpliceError):
        CI.concat_ca_frames([_intraday_frame(), pd.DataFrame({"cvx_adj_bp": [2.0]})])
    # two intraday frames are fine
    out = CI.concat_ca_frames([_intraday_frame(1.0), _intraday_frame(2.0)])
    assert len(out) == 2


def test_a_frame_that_already_mixes_sources_is_rejected_on_sight():
    mixed = pd.concat([_intraday_frame(), CI.tag_settle_frame(_intraday_frame())])
    with pytest.raises(CI.IntradaySpliceError):
        CI.price_source_of(mixed)


def test_tag_settle_frame_does_not_mutate_its_input():
    """``sfr_cvx_adj``'s own output must stay exactly the shape callers expect."""
    src = pd.DataFrame({"cvx_adj_bp": [1.0]})
    CI.tag_settle_frame(src)
    assert list(src.columns) == ["cvx_adj_bp"]


# --------------------------------------------------------------------------
# The shared label vocabulary
# --------------------------------------------------------------------------
def test_the_intraday_path_resolves_packs_the_way_the_daily_path_does():
    """One vocabulary, not two.

    These used to be closures inside ``sfr_cvx_adj``; the intraday method needs
    the same rules, and a second copy would diverge invisibly because both
    copies return four plausible IMM codes.
    """
    from TB.IRSwapsTB import CVX_PACK_MAP, _cvx_col_name, _cvx_ranks_for_label

    assert _cvx_ranks_for_label("WHITES") == [1, 2, 3, 4]
    assert _cvx_ranks_for_label("GOLDS") == [17, 18, 19, 20]
    assert _cvx_ranks_for_label("SFR9") == [9]
    assert _cvx_ranks_for_label("BUNDLE2") == list(range(5, 21))
    assert _cvx_ranks_for_label("H26") is None            # IMM, handled separately
    assert CVX_PACK_MAP["BLUES"] == (13, 16)
    assert _cvx_col_name("USD-SOFR-1D", "WHITES") == "USD-SOFR-1D WHITES PACKS CVX_ADJ"


# --------------------------------------------------------------------------
# Integration -- the real local stores, no network
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def tb():
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from TB.IRSwapsTB import IRSwapsTB

    return IRSwapsTB(mdp=IRSwapsMDP(source="CITIVELO_EXCEL"), show_tqdm=False,
                     use_ts_cache=False,
                     cache_stem="IRSwapsTB_TEST_convexity_rv_intraday")


@pytest.fixture(scope="module")
def warm(tb):
    """Skip the integration tests on a machine without the warm."""
    from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP

    mdp = STIRFutureMDP(source=CI.INTRADAY_FUTURES_SOURCE)
    mdp._ensure_pricer_cache()
    probe = CI.mdp_key_probe(mdp)
    if not CI.tape_present(probe, PINNED, ["SR3U26"]):
        pytest.skip("SR3 minute tape is cold on this machine for the pinned instant")
    return True


def test_whites_prices_intraday_with_no_network(tb, warm):
    """One real number, offline, with both legs' instants pinned.

    ``sfr_cvx_adj_intraday_failures`` being empty is what proves the futures leg
    never went out: the whole call runs inside ``cache_only()``, so a leg that
    needed Barchart would have raised and been recorded as a failure rather than
    returning a row.
    """
    out = tb.sfr_cvx_adj_intraday(["WHITES"], [PINNED])
    assert tb.sfr_cvx_adj_intraday_failures == {}
    assert len(out) == 1
    row = out.iloc[0]

    assert row["cvx_adj_bp"] == pytest.approx(PINNED_WHITES_BP, abs=1e-9)
    assert row[CI.PRICE_SOURCE_COL] == CI.PRICE_SOURCE_INTRADAY
    assert row["futures_source"] == CI.INTRADAY_FUTURES_SOURCE
    # requested vs served, both legs
    assert row["futures_stamp"] == "2026-08-19T14:00:00-05:00"
    assert pd.Timestamp(row["timestamp_utc"]) == pd.Timestamp("2026-08-19T19:00:00Z")
    assert pd.Timestamp(row["curve_stamp"]) == pd.Timestamp("2026-08-19T19:00:00Z")
    assert row["snapshot_lag_seconds"] == 0.0
    assert row["curve_asset"] == "USD-SOFR-1D-CITIVELOEXCELMIN"
    assert row["curve_mode"] == "intraday"
    assert row["contracts"] == "SFRU26,SFRZ26,SFRH27,SFRM27"


def test_the_recorded_stamp_is_the_key_that_answered_not_the_one_assumed(tb, warm):
    """Provenance has to be MEASURED, and this is the date that proves it.

    2026-05-07 is written in the **UTC** spelling only: all 17 contracts of the
    front strip carry a ``...T19:00:00+00:00`` key at 15:00 ET and none of them
    carries the Chicago one. (312 such (date, hour) pairs exist locally, spread
    over 2026-05.) A row that ASSUMED the Chicago spelling would record a key
    that does not exist, and nothing downstream could catch it -- the pricer the
    MDP returns exposes a reference date and never the minute.

    The value still comes back, because the MDP probes the UTC spelling first;
    only the recorded provenance would be a fiction.
    """
    from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP

    inst = datetime.datetime(2026, 5, 7, 15, 0, tzinfo=ET)
    mdp = STIRFutureMDP(source=CI.INTRADAY_FUTURES_SOURCE)
    mdp._ensure_pricer_cache()
    probe = CI.mdp_key_probe(mdp)
    utc_key, ct_key = CI.tape_keys(inst, "SR3M26")
    if not (probe(utc_key) and not probe(ct_key)):
        pytest.skip("this machine's 2026-05-07 tape is not UTC-only")

    out = tb.sfr_cvx_adj_intraday(["WHITES"], [inst])
    assert len(out) == 1, tb.sfr_cvx_adj_intraday_failures
    row = out.iloc[0]
    assert row["futures_key_family"] == "utc"
    assert row["futures_stamp"] == "2026-05-07T19:00:00+00:00"
    # ... and both spellings still name one instant
    assert pd.Timestamp(row["timestamp_utc"]) == pd.Timestamp("2026-05-07T19:00:00Z")


def test_the_futures_source_is_pinned_and_a_settle_source_is_refused(tb):
    with pytest.raises(ValueError, match="not an intraday quote feed"):
        tb.sfr_cvx_adj_intraday(["WHITES"], [PINNED], futures_source="BARCHART_STIRF-RL")


def test_golds_fails_loud_with_the_depth_it_needed_and_the_depth_that_exists(tb, warm):
    """Never a shallower pack served under the deeper pack's name.

    The LOCAL intraday tape reaches contiguous depth 20 on ZERO dates in every
    year 2018-2026 and its maximum anywhere is 17, so GOLDS (rank 17, needs
    depth 20) cannot be priced off what is cached. The failure has to name both
    numbers or the reader cannot tell "not today" from "not ever".

    It is the first of those. The 17 is a REQUEST ceiling -- the deepest-rank
    histogram spikes on 12/13/17, the instrument counts of the three curves the
    nightly intraday job builds -- and asked directly the vendor priced ranks
    18-20 at the requested minute. So this test pins the REFUSAL, not an
    impossibility: once a depth-20 intraday warm runs, GOLDS should price and
    this test should be the thing that has to change.
    """
    with pytest.raises(CI.IntradayRankUnavailable) as ei:
        tb.sfr_cvx_adj_intraday(["GOLDS"], [PINNED])
    msg = str(ei.value)
    assert "depth 20" in msg and "17" in msg

    # ... and per-rank, not per-call: WHITES still prices in the same request
    out = tb.sfr_cvx_adj_intraday(["WHITES", "GOLDS"], [PINNED], strict_ranks=False)
    assert list(out["label"]) == ["WHITES"]
    assert out.iloc[0]["cvx_adj_bp"] == pytest.approx(PINNED_WHITES_BP, abs=1e-9)
    reason = tb.sfr_cvx_adj_intraday_failures["GOLDS"][pd.Timestamp(
        CI.tape_instant(PINNED)).isoformat()]
    assert "17" in reason and "20" in reason


def test_blues_is_reachable_intraday_and_the_depth_is_recorded(tb, warm):
    """The reachable/unreachable boundary is measured, not assumed: BLUES needs
    depth 16 and the pinned instant carries 17."""
    out = tb.sfr_cvx_adj_intraday(["BLUES"], [PINNED])
    assert len(out) == 1
    assert out.iloc[0]["strip_depth"] >= 16
    assert out.iloc[0]["contracts"] == "SFRU29,SFRZ29,SFRH30,SFRM30"


def test_the_intraday_path_writes_nothing(tb, warm):
    """No mapping-cache row, no ``data/ts`` row.

    Both would be a splice surface rather than a cache: ``_ts_symbol_for_query``
    is ``IRS::{source}::{curve}::{fingerprint}`` and ``market_request`` is not
    in ``_query_fingerprint`` (asserted at the top of this file), so an intraday
    row and a settle row for the same pack land in the SAME symbol.
    """
    mapping = getattr(tb, tb._cache_attr)
    before = len(mapping)

    def _boom(*a, **k):                                          # pragma: no cover
        raise AssertionError("the intraday path wrote to data/ts")

    orig = tb._computed_ts_store.append_many_rows
    tb._computed_ts_store.append_many_rows = _boom
    try:
        out = tb.sfr_cvx_adj_intraday(["WHITES"], [PINNED])
    finally:
        tb._computed_ts_store.append_many_rows = orig

    assert len(out) == 1
    assert len(mapping) == before, "the intraday path added mapping-cache rows"


def test_a_non_intraday_curve_is_refused_rather_than_priced(tb, warm):
    """If the swap leg is not a minute-store curve it is not an intraday CA.

    The realistic failure is the store declining and the request being answered
    by the day's CLOSE -- up to two hours after the futures mark, in a
    difference whose whole magnitude is a couple of basis points.
    """
    class _EodCurve:
        def __init__(self, inner):
            self._inner = inner

        def meta(self):
            m = dict(self._inner.meta() or {})
            m["mode"] = "eod"
            m["from_curve_store"] = False
            return m

        def __getattr__(self, name):
            return getattr(self._inner, name)

    class _Wrap:
        source = "CITIVELO_EXCEL"

        def __init__(self, inner):
            self._inner = inner

        def _get_curve(self, **kw):
            return _EodCurve(self._inner._get_curve(**kw))

    out = tb.sfr_cvx_adj_intraday(["WHITES"], [PINNED], swaps_mdp=_Wrap(tb.mdp),
                                  strict_ranks=False)
    assert len(out) == 0
    reason = tb.sfr_cvx_adj_intraday_failures["WHITES"][pd.Timestamp(
        CI.tape_instant(PINNED)).isoformat()]
    assert "not a minute-store intraday curve" in reason


def test_a_curve_source_with_no_minute_store_is_refused(tb):
    class _Barchart:
        source = "BARCHART_STIRF-RL"

    with pytest.raises(ValueError, match="no minute store"):
        tb.sfr_cvx_adj_intraday(["WHITES"], [PINNED], swaps_mdp=_Barchart())


def test_a_minute_with_no_tape_is_recorded_not_invented(tb, warm):
    """Absence stays absence -- no nearest minute, no settle standing in.

    17:30 ET is inside CME's daily maintenance halt (16:01-16:59 Chicago), and
    it is a real hole rather than a contrived one: exactly 59 of the 1,440
    Chicago minutes of 2026-08-19 are absent from the tape and they are
    precisely that window, in both key spellings.
    """
    quiet = datetime.datetime(2026, 8, 19, 17, 30, tzinfo=ET)
    out = tb.sfr_cvx_adj_intraday(["WHITES"], [quiet], strict_ranks=False)
    if len(out):                     # the tape does carry it on some machines
        pytest.skip("this machine's tape carries the quiet minute")
    reason = tb.sfr_cvx_adj_intraday_failures["WHITES"][pd.Timestamp(
        CI.tape_instant(quiet)).isoformat()]
    assert "depth" in reason or "no minute bar" in reason


def test_the_fixings_fallback_does_not_move_a_forward_starting_pack(tb, warm):
    """Why ``block_network=True`` is safe even though it blocks the fixings fetch.

    Under ``cache_only()`` the official (publisher) fixing source is unreachable
    and the Citi curve falls back to Citi's published series with a warning.
    That warning is cosmetic *for this geometry* and the claim is tested rather
    than argued: every leg of a pack and both legs of the matched swap start at a
    future IMM date, so no historical fixing enters any cashflow.

    The shock is asserted to have LANDED before the invariance is believed -- the
    first version of this check assigned to a frozen dataclass field, silently
    did nothing, and reported a pass.
    """
    import dataclasses

    import MDP.IRSwaps.CITIVELO_EXCEL.fixings as FX

    base = tb.sfr_cvx_adj_intraday(["WHITES"], [PINNED]).iloc[0]["cvx_adj_bp"]

    seen = {"n": 0, "changed": 0}
    orig = FX.fixings_for

    def _shocked(*a, **k):
        res = orig(*a, **k)
        seen["n"] += 1
        before = res.series
        out = dataclasses.replace(res, series=before + 200.0)
        if len(before) and not out.series.equals(before):
            seen["changed"] += 1
        return out

    FX.fixings_for = _shocked
    FX.reset_fixings_cache()
    try:
        from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
        from TB.IRSwapsTB import IRSwapsTB

        tb2 = IRSwapsTB(mdp=IRSwapsMDP(source="CITIVELO_EXCEL"), show_tqdm=False,
                        use_ts_cache=False,
                        cache_stem="IRSwapsTB_TEST_convexity_rv_intraday_shock")
        shocked = tb2.sfr_cvx_adj_intraday(["WHITES"], [PINNED]).iloc[0]["cvx_adj_bp"]
    finally:
        FX.fixings_for = orig
        FX.reset_fixings_cache()

    assert seen["n"] > 0, "fixings_for was never called; the shock reached nothing"
    assert seen["changed"] > 0, "the shock did not change any non-empty series"
    assert shocked == pytest.approx(base, abs=1e-12)

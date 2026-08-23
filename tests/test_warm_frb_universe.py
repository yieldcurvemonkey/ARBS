"""The FedInvest warm now covers the whole coupon curve, by maturity alias.

Two things are pinned here and they fail in opposite directions.

The SYMBOL SET has to address every live bond exactly once, in tokens that keep
meaning the same bond forever - the computed-timeseries key is a hash of the
cusip token as typed, so the token chosen IS the series identity.

The AMBIGUITY PATH has to raise. It used to swallow: an alias naming two bonds
was dropped from the returned mapping with no exception and no log line, so the
caller got a shorter dict than it asked for and nothing said which alias went
missing. A maturity alias that can silently stop meaning what it meant is worse
than no maturity alias.

Hermetic: the reference frame is synthetic, so nothing here fetches, and the
cases are the ones that are hard to find in live data (a month with three
original-issue buckets, a bond that has not settled yet).
"""

import datetime
import importlib.util
import os
import sys

import pandas as pd
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AS_OF = datetime.date(2026, 8, 21)


@pytest.fixture(scope="module")
def warmer():
    spec = importlib.util.spec_from_file_location(
        "daily_cache_warmer_frb_under_test",
        os.path.join(REPO_ROOT, "scripts", "daily_cache_warmer.py"),
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _row(cusip, oi, maturity, issue, cpn=4.0):
    return {
        "record_date": AS_OF,
        "label": cusip,
        "cusip": cusip,
        "oi": oi,
        "auction_date": issue - datetime.timedelta(days=7),
        "issue_date": issue,
        "maturity_date": maturity,
        "cpn": cpn,
        "inflation_index_security": "No",
        "floating_rate": "No",
        "reopened_term_months": None,
        "reopened_issue_date": None,
    }


#: Deliberately awkward. 08/2050 is reachable only as a 30y; 02/2045 carries
#: BOTH a 30y and a 20y, which is the real collision measured on this machine
#: ('0245' meant the 30y as-of 2020/2022/2024 and became ambiguous in 2026);
#: 05/2036 carries three buckets; and one bond is not issued yet on AS_OF.
SYNTHETIC = [
    _row("912810SP4", "30-Year", datetime.date(2050, 8, 15), datetime.date(2020, 8, 17)),
    _row("912810RK6", "30-Year", datetime.date(2045, 2, 15), datetime.date(2015, 2, 17)),
    _row("912810UJ5", "20-Year", datetime.date(2045, 2, 15), datetime.date(2025, 2, 18)),
    _row("AAA111AA1", "30-Year", datetime.date(2036, 5, 15), datetime.date(2006, 5, 15)),
    _row("BBB222BB2", "20-Year", datetime.date(2036, 5, 15), datetime.date(2016, 5, 16)),
    _row("CCC333CC3", "10-Year", datetime.date(2036, 5, 15), datetime.date(2026, 5, 15)),
    _row("DDD444DD4", "10-Year", datetime.date(2036, 8, 15), datetime.date(2026, 8, 17)),
    # Auctioned but not settled on AS_OF: _filter_and_rank_ref_df drops it, so it
    # must not appear in the symbol set either.
    _row("EEE555EE5", "10-Year", datetime.date(2036, 11, 15), datetime.date(2026, 11, 16)),
]


@pytest.fixture
def synthetic_ref(monkeypatch):
    # Date columns stay ``object`` holding ``datetime.date``, which is what the
    # cached fiscaldata parquet actually carries. Converting them to datetime64
    # makes _filter_and_rank_ref_df's `>= as_of` comparison raise TypeError --
    # a fixture that does not match production is a test of nothing.
    frame = pd.DataFrame(SYNTHETIC)
    for col in ("auction_date", "issue_date", "maturity_date", "record_date"):
        frame[col] = frame[col].map(lambda d: d if isinstance(d, datetime.date) else d)
    import MDP.FixedRateBonds.reference_data_cache.ust_reference_data as urd

    monkeypatch.setattr(urd, "update_reference_data", lambda **kw: frame.copy())
    return frame


def _live_cusips(warmer):
    from MDP.FixedRateBonds.FixedRateBondsMDP import _filter_and_rank_ref_df
    import MDP.FixedRateBonds.reference_data_cache.ust_reference_data as urd

    return set(
        _filter_and_rank_ref_df(urd.update_reference_data(source="fiscaldata"), AS_OF)["cusip"]
    )


# ── the symbol set ───────────────────────────────────────────────────

def test_the_constant_maturity_ranks_are_still_there(warmer, synthetic_ref):
    symbols = warmer._frb_universe_symbols(AS_OF)
    for rank in warmer._FRB_CUSIPS:
        assert rank in symbols, f"{rank} must survive - it is a different series"


def test_every_live_bond_gets_an_oi_qualified_alias(warmer, synthetic_ref):
    symbols = set(warmer._frb_universe_symbols(AS_OF))
    assert {"0850-30", "0245-30", "0245-20", "0536-30", "0536-20", "0536-10",
            "0836-10"} <= symbols


def test_a_bond_that_has_not_settled_yet_is_not_warmed(warmer, synthetic_ref):
    symbols = set(warmer._frb_universe_symbols(AS_OF))
    assert not any(s.startswith("1136") for s in symbols), (
        "EEE555EE5 issues in November; the reference filter drops it and so must this"
    )


def test_the_bare_alias_is_emitted_only_while_it_names_one_bond(warmer, synthetic_ref):
    symbols = set(warmer._frb_universe_symbols(AS_OF))
    # 08/2050 has exactly one bond -- the user's own example, and it must be
    # typable as '0850'.
    assert "0850" in symbols
    assert "0836" in symbols
    # 02/2045 and 05/2036 have two and three. A bare alias there would name a
    # different bond depending on the reference vintage.
    assert "0245" not in symbols
    assert "0536" not in symbols


def test_the_symbol_set_has_no_duplicates(warmer, synthetic_ref):
    symbols = warmer._frb_universe_symbols(AS_OF)
    assert len(symbols) == len(set(symbols))


def test_every_emitted_token_resolves_to_exactly_one_bond(warmer, synthetic_ref):
    """The whole point: no token may be ambiguous, and none may silently vanish."""
    from MDP.FixedRateBonds.FixedRateBondsMDP import (
        FixedRateBondsMDP, _filter_and_rank_ref_df,
    )
    import MDP.FixedRateBonds.reference_data_cache.ust_reference_data as urd

    symbols = [s for s in warmer._frb_universe_symbols(AS_OF)
               if s not in warmer._FRB_CUSIPS]  # ranks need a full ref frame
    ref = _filter_and_rank_ref_df(urd.update_reference_data(source="fiscaldata"), AS_OF)
    mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-RL")
    resolved, _ = mdp._resolve_aliases_bulk(list(symbols), AS_OF, ref_df=ref)

    missing = [s for s in symbols if s not in resolved]
    assert not missing, f"tokens that did not resolve: {missing}"
    # And the oi-qualified pair really does split the collision.
    assert resolved["0245-30"] == "912810RK6"
    assert resolved["0245-20"] == "912810UJ5"


# ── the ambiguity path ───────────────────────────────────────────────

def test_an_ambiguous_bare_alias_raises_instead_of_vanishing(synthetic_ref):
    """The regression this file exists for.

    Before the fix the inner ``raise`` landed in an outer ``except Exception``
    that set ``cusip = alias``; the reference lookup then failed and the loop
    ``continue``d. Measured: a seven-token call came back with four keys and no
    exception.
    """
    from MDP.FixedRateBonds.FixedRateBondsMDP import (
        FixedRateBondsMDP, _filter_and_rank_ref_df,
    )
    import MDP.FixedRateBonds.reference_data_cache.ust_reference_data as urd

    ref = _filter_and_rank_ref_df(urd.update_reference_data(source="fiscaldata"), AS_OF)
    mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-RL")

    with pytest.raises(AssertionError, match="Ambiguous alias"):
        mdp._resolve_aliases_bulk(["0245"], AS_OF, ref_df=ref)


def test_an_unknown_token_still_falls_through_to_raw_cusip(synthetic_ref):
    """Only AMBIGUITY escalates. A token that is simply not an alias is a CUSIP."""
    from MDP.FixedRateBonds.FixedRateBondsMDP import (
        FixedRateBondsMDP, _filter_and_rank_ref_df,
    )
    import MDP.FixedRateBonds.reference_data_cache.ust_reference_data as urd

    ref = _filter_and_rank_ref_df(urd.update_reference_data(source="fiscaldata"), AS_OF)
    mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-RL")
    resolved, _ = mdp._resolve_aliases_bulk(["912810SP4", "NOTATHING"], AS_OF, ref_df=ref)
    assert resolved["912810SP4"] == "912810SP4"
    assert "NOTATHING" not in resolved


# ── the guards ───────────────────────────────────────────────────────

def _run_job_against(warmer, monkeypatch, frame):
    """Drive the job with a stubbed TimeseriesBuilder returning ``frame``.

    The job body does its imports INSIDE the function, so every name is
    re-resolved from its own module per call and ``monkeypatch.setattr(warmer,
    ...)`` is never consulted. The source module is what has to be patched.
    """
    import TB.TimeseriesBuilder as tbmod

    class _StubTB:
        def get_timeseries(self, **kwargs):
            return frame

    monkeypatch.setattr(tbmod, "TimeseriesBuilder", _StubTB)
    monkeypatch.setattr(warmer, "_FRB_FULL_UNIVERSE", False)
    return warmer.warm_frb_fedinvest_eod(AS_OF, AS_OF)


def test_an_empty_frame_is_a_failure_not_a_success(warmer, monkeypatch):
    with pytest.raises(RuntimeError, match="priced NOTHING"):
        _run_job_against(warmer, monkeypatch, pd.DataFrame())


def test_a_mostly_missing_day_is_refused(warmer, monkeypatch):
    """The FedInvest all-zeros tape arrives here as missing columns."""
    cols = [f"{c} OUTRIGHT YTM" for c in warmer._FRB_CUSIPS[:5]]  # 5 of 28 = 18%
    frame = pd.DataFrame([[4.0] * len(cols)], index=[AS_OF], columns=cols)
    with pytest.raises(RuntimeError, match="under the .* floor"):
        _run_job_against(warmer, monkeypatch, frame)


def test_a_full_day_passes(warmer, monkeypatch):
    cols = [f"{c} OUTRIGHT YTM" for c in warmer._FRB_CUSIPS]
    frame = pd.DataFrame([[4.0] * len(cols)], index=[AS_OF], columns=cols)
    out = _run_job_against(warmer, monkeypatch, frame)
    assert out.shape == (1, len(warmer._FRB_CUSIPS))

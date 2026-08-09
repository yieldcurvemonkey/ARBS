r"""What the citivelo intraday timeseries warm must not get wrong.

The warm's whole output is a set of Parquet rows filed under a sha1 symbol. That
makes almost every way it can fail SILENT: a wrong symbol writes a cache nobody
reads, a wrong weight writes plausible numbers that disagree with the same query
priced directly, and a resume that trusts the wrong thing skips a day it never
did. None of those raise, and none of them show up in a row count. So the tests
here assert identities and values, never durations.

Five shapes are pinned.

1. **The symbol a warm writes is the symbol a user reads.** The fingerprint does
   not normalise tenor case, so this is a real constraint, not a formality -
   ``10y`` and ``10Y`` are two different symbols and two different columns.
2. **A derived structure equals the reader's own synthesis.** The warm writes
   curves and flies as arithmetic on outrights; if that arithmetic drifted from
   ``IRSwapsTB._decompose_rate_into_outright_legs``, the value a caller got would
   depend on whether the structure happened to be cached.
3. **The universe is closed.** Every derived leg must be an outright the warm
   actually prices, or the structure produces no rows and the run still reports
   success.
4. **Resume is keyed on the config.** Two runs with different universes must not
   be able to look like one complete run.
5. **A shared quotes object is not closed by its borrower.** The process-wide
   default exists so a pool worker cannot reach Excel; closing it after the first
   call would leave the rest of the run reading through a torn-down client.
"""

from __future__ import annotations

import datetime
import json
import zoneinfo
from pathlib import Path

import pandas as pd
import pytest

from scripts import citivelo_intraday_ts_warm as warm

ET = zoneinfo.ZoneInfo("America/New_York")


# ------------------------------------------------------------------ #
#              1. the symbol a warm writes is the one read           #
# ------------------------------------------------------------------ #


@pytest.fixture(scope="module")
def tb():
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from TB.IRSwapsTB import IRSwapsTB

    return IRSwapsTB(IRSwapsMDP(source=warm.SOURCE), show_tqdm=False, use_duckdb=False)


@pytest.mark.parametrize("tenor", ["10y", "5y/10y", "5y/10y/30y", "5yx5y", "5yx5y/10yx10y"])
def test_warm_symbol_matches_a_user_unified_query(tb, tenor):
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue
    from TB.TimeseriesBuilder import _normalize_query_like

    warm_q = IRSwapQuery(curve=warm.CURVE, tenor=tenor, value=IRSwapValue.RATE)
    user_q = _normalize_query_like(
        UnifiedQuery(curve=warm.CURVE, tenor=tenor, value=UnifiedValue.IRS_RATE)
    )[0]
    assert tb._ts_symbol_for_query(warm.CURVE, warm_q) == tb._ts_symbol_for_query(
        warm.CURVE, user_q
    )


def test_the_swap_spread_query_carries_no_value_kwargs(tb):
    """``value_kwargs`` is inside the fingerprint.

    Passing ``quotes=`` or ``offline=`` there - the obvious way to keep a batch
    off Excel - would fork every symbol away from the one a plain user query
    reads. That is why the offline default is process-wide instead.
    """
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue
    from TB.TimeseriesBuilder import _normalize_query_like

    warm_q = IRSwapQuery(curve=warm.CURVE, tenor="10Y", value=IRSwapValue.CITIVELO_SWAP_SPREAD)
    assert not warm_q.value_kwargs
    user_q = _normalize_query_like(
        UnifiedQuery(curve=warm.CURVE, tenor="10Y", value=UnifiedValue.IRS_CITIVELO_SWAP_SPREAD)
    )[0]
    assert tb._ts_symbol_for_query(warm.CURVE, warm_q) == tb._ts_symbol_for_query(
        warm.CURVE, user_q
    )

    forked = IRSwapQuery(
        curve=warm.CURVE, tenor="10Y", value=IRSwapValue.CITIVELO_SWAP_SPREAD,
        value_kwargs={"offline": True},
    )
    assert tb._ts_symbol_for_query(warm.CURVE, forked) != tb._ts_symbol_for_query(
        warm.CURVE, warm_q
    ), "value_kwargs must fork the symbol - if it stopped doing so this test is the wrong guard"


def test_case_is_load_bearing_in_the_symbol(tb):
    """Not a wish - a measured property the ``--case-aliases`` copies exist for."""
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    lower = IRSwapQuery(curve=warm.CURVE, tenor="10y", value=IRSwapValue.RATE)
    upper = IRSwapQuery(curve=warm.CURVE, tenor="10Y", value=IRSwapValue.RATE)
    assert tb._ts_symbol_for_query(warm.CURVE, lower) != tb._ts_symbol_for_query(warm.CURVE, upper)
    assert lower.col_name(warm.CURVE) != upper.col_name(warm.CURVE)


# ------------------------------------------------------------------ #
#          2. derivation reproduces the reader's own synthesis       #
# ------------------------------------------------------------------ #


def test_decompose_matches_the_readers_weights():
    from TB.IRSwapsTB import _decompose_rate_into_outright_legs
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    for tenor in ("5y/10y", "5y/10y/30y", "1yx1y/2yx1y", "1yx1y/2yx1y/3yx1y"):
        query = IRSwapQuery(curve=warm.CURVE, tenor=tenor, value=IRSwapValue.RATE)
        assert list(warm.decompose(tenor)) == [
            tuple(x) for x in _decompose_rate_into_outright_legs(query)
        ]


def test_decompose_refuses_an_outright():
    assert warm.decompose("10y") is None
    assert warm.decompose("5yx5y") is None
    assert warm.decompose("a/b/c/d") is None


def test_derive_value_is_the_readers_formula():
    """``sum(w * abs(leg)) * 100`` - the line in ``IRSwapsTB.get_timeseries``."""
    legs = warm.decompose("5y/10y")
    assert warm.derive_value(legs, {"5y": 4.0, "10y": 4.25}) == pytest.approx(25.0)

    fly = warm.decompose("5y/10y/30y")
    assert warm.derive_value(fly, {"5y": 4.0, "10y": 4.25, "30y": 4.4}) == pytest.approx(10.0)


def test_derive_value_reports_a_missing_leg_as_none_not_as_zero():
    legs = warm.decompose("5y/10y")
    assert warm.derive_value(legs, {"5y": 4.0}) is None


# ------------------------------------------------------------------ #
#                     3. the universe is closed                      #
# ------------------------------------------------------------------ #


def test_every_derived_leg_is_an_outright_we_price():
    known = set(warm.OUTRIGHT_TENORS)
    for tenor in warm.STRUCTURE_TENORS:
        for leg in tenor.split("/"):
            assert leg in known, f"{tenor!r} needs outright {leg!r}"


def test_the_closure_check_actually_fires(monkeypatch):
    """The guard is only worth having if a broken universe trips it."""
    monkeypatch.setattr(warm, "OUTRIGHT_TENORS", ("10y",))
    monkeypatch.setattr(warm, "STRUCTURE_TENORS", ("10y/30y",))
    with pytest.raises(AssertionError, match="30y"):
        warm._assert_universe_is_closed()


def test_no_forward_reaches_past_the_curves_last_node():
    """Citi's USD par grid ends at 50Y; a 40yx15y would be extrapolation."""

    def years(token: str) -> float:
        unit = token[-1].lower()
        return float(token[:-1]) * {"y": 1.0, "m": 1.0 / 12.0}[unit]

    for tenor in warm.FORWARD_TENORS:
        forward, tail = tenor.split("x")
        assert years(forward) + years(tail) <= 50.0, tenor


def test_structures_are_unique():
    assert len(set(warm.STRUCTURE_TENORS)) == len(warm.STRUCTURE_TENORS)
    assert len(set(warm.OUTRIGHT_TENORS)) == len(warm.OUTRIGHT_TENORS)


# ------------------------------------------------------------------ #
#                4. resume is keyed on the config                    #
# ------------------------------------------------------------------ #


def test_fingerprint_moves_with_the_universe():
    base = warm.WarmConfig()
    assert base.fingerprint() == warm.WarmConfig().fingerprint()
    assert base.fingerprint() != warm.WarmConfig(outrights=("10y",)).fingerprint()
    assert base.fingerprint() != warm.WarmConfig(omit_unused_fixings=False).fingerprint()
    assert base.fingerprint() != warm.WarmConfig(case_aliases=False).fingerprint()
    assert base.fingerprint() != warm.WarmConfig(structures=False).fingerprint()


def test_ledger_only_returns_days_written_at_this_config(tmp_path: Path):
    ledger = warm.Ledger(tmp_path / "l.jsonl")
    ledger.record(warm.DayStat(date="2026-07-29", status="ok", cfg="AAA"))
    ledger.record(warm.DayStat(date="2026-07-30", status="ok", cfg="BBB"))
    done = ledger.completed(cfg_fingerprint="AAA")
    assert set(done) == {datetime.date(2026, 7, 29)}


def test_a_non_business_day_is_finished_not_failed(tmp_path: Path):
    """A Sunday prices nothing BY DESIGN - USD-SOFR-1D filters its points away.

    Recording it as an error meant 12 of the first 51 days of a run read as
    failures, and retrying it on every run kept a complete run from ever
    reporting complete.
    """
    ledger = warm.Ledger(tmp_path / "l.jsonl")
    ledger.record(warm.DayStat(date="2026-07-26", status="non_business", cfg="AAA"))
    ledger.record(warm.DayStat(date="2026-07-27", status="empty", cfg="AAA"))
    ledger.record(warm.DayStat(date="2026-07-28", status="error", cfg="AAA", error="boom"))
    done = ledger.completed(cfg_fingerprint="AAA")
    assert set(done) == {datetime.date(2026, 7, 26), datetime.date(2026, 7, 27)}


def test_progress_does_not_count_a_sunday_as_an_error():
    progress = warm.Progress(total_days=3)
    progress.record(warm.DayStat(date="2026-07-26", status="non_business"))
    progress.record(warm.DayStat(date="2026-07-27", status="ok"))
    progress.record(warm.DayStat(date="2026-07-28", status="error"))
    assert (progress.errors, progress.skipped) == (1, 1)


def test_a_later_failure_un_completes_a_day(tmp_path: Path):
    """A day re-run that failed must stop counting as done.

    Append-only means the old success line is still on disk; reading it as the
    answer would skip a day whose data was later found to be bad.
    """
    ledger = warm.Ledger(tmp_path / "l.jsonl")
    ledger.record(warm.DayStat(date="2026-07-29", status="ok", cfg="AAA"))
    ledger.record(warm.DayStat(date="2026-07-29", status="error", cfg="AAA", error="boom"))
    assert ledger.completed(cfg_fingerprint="AAA") == {}


def test_a_torn_last_line_is_not_fatal(tmp_path: Path):
    path = tmp_path / "l.jsonl"
    ledger = warm.Ledger(path)
    ledger.record(warm.DayStat(date="2026-07-29", status="ok", cfg="AAA"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"date": "2026-07-30", "sta')
    assert set(ledger.completed(cfg_fingerprint="AAA")) == {datetime.date(2026, 7, 29)}


def test_completed_windows_ignores_a_partial_record(tmp_path: Path):
    path = tmp_path / "spreads.jsonl"
    path.write_text(
        json.dumps({"window": "2026-07-01/2026-07-06", "status": "ok"}) + "\n"
        + json.dumps({"window": "2026-07-06/2026-07-11", "status": "error"}) + "\n",
        encoding="utf-8",
    )
    assert warm._completed_windows(path) == {"2026-07-01/2026-07-06"}


# ------------------------------------------------------------------ #
#                    5. the day-sliced quotes stub                   #
# ------------------------------------------------------------------ #


def _spread_frame() -> pd.DataFrame:
    index = pd.date_range("2026-07-24", "2026-07-30", freq="h")
    return pd.DataFrame(
        {
            "RATES.OIS.USD_SOFR.SWAP_SPREAD.10Y": range(len(index)),
            "RATES.OIS.USD_SOFR.SWAP_SPREAD.5Y": range(len(index)),
        },
        index=index,
        dtype=float,
    )


def test_day_quotes_serves_only_the_tags_it_has():
    quotes = warm.DayQuotes(_spread_frame())
    out = quotes.frame(
        ["RATES.OIS.USD_SOFR.SWAP_SPREAD.10Y", "RATES.OIS.USD_SOFR.SWAP_SPREAD.30Y"], "MI01"
    )
    assert list(out.columns) == ["RATES.OIS.USD_SOFR.SWAP_SPREAD.10Y"]


def test_day_quotes_honours_the_window_bounds():
    quotes = warm.DayQuotes(_spread_frame())
    out = quotes.frame(
        ["RATES.OIS.USD_SOFR.SWAP_SPREAD.10Y"], "MI01",
        start=datetime.datetime(2026, 7, 28), end=datetime.datetime(2026, 7, 29),
    )
    assert out.index.min() == pd.Timestamp("2026-07-28")
    assert out.index.max() == pd.Timestamp("2026-07-29")


def test_the_day_slice_reaches_back_a_whole_lookback():
    """Cut at the day boundary and the session's first minutes lose their print."""
    frame = _spread_frame()
    lookback = datetime.timedelta(days=5)
    sliced = warm.slice_spreads_for_day(frame, datetime.date(2026, 7, 29), lookback=lookback)
    assert sliced.index.min() <= pd.Timestamp("2026-07-24")
    assert sliced.index.max() >= pd.Timestamp("2026-07-29 23:00")


_TAGS = {"10Y": "TAG10", "3M": "TAG3M"}


def _session_frame() -> pd.DataFrame:
    """Friday 09:00-17:59 for 10Y; 3M also prints through Monday's small hours."""
    friday = pd.date_range("2026-07-24 09:00", "2026-07-24 17:59", freq="min")
    monday_early = pd.date_range("2026-07-27 01:00", "2026-07-27 02:00", freq="min")
    index = friday.union(monday_early)
    frame = pd.DataFrame(index=index, dtype=float)
    frame["TAG10"] = [1.0 if ts in friday else float("nan") for ts in index]
    frame["TAG3M"] = 1.0
    return frame


def test_fresh_spread_minutes_drops_the_monday_small_hours():
    """The curve store holds Monday 01:44; Citi's newest 10Y print is Friday 17:59.

    The value map refuses that as 55.8 h stale - one raised exception per (tenor,
    minute), each logged with a full traceback inside IRSwapsTB. Filtering ahead
    of it changes no value.
    """
    frame = _session_frame()
    monday = [
        datetime.datetime(2026, 7, 27, 1, 44, tzinfo=ET),
        datetime.datetime(2026, 7, 27, 2, 0, tzinfo=ET),
    ]
    out = warm.fresh_spread_minutes(monday, frame, _TAGS)
    assert "10Y" not in out


def test_fresh_spread_minutes_is_per_tenor_not_per_row():
    """Measured 2024-09-23 01:44: 1M/3M/6M/1Y print while 2Y-30Y are NaN.

    A row-level test (``dropna(how='all')``) passed that minute and the seven long
    tenors raised anyway; an all-tenors-must-be-fresh rule would instead have
    thrown away the money-market coverage that genuinely exists there.
    """
    frame = _session_frame()
    monday = [datetime.datetime(2026, 7, 27, 1, 44, tzinfo=ET)]
    out = warm.fresh_spread_minutes(monday, frame, _TAGS)
    assert out == {"3M": monday}


def test_fresh_spread_minutes_keeps_an_overnight_gap_inside_the_limit():
    frame = _session_frame()
    # 07-25 01:00 is 7 h after Friday's last 10Y print - inside the 12 h limit.
    minute = [datetime.datetime(2026, 7, 25, 1, 0, tzinfo=ET)]
    assert warm.fresh_spread_minutes(minute, frame, _TAGS)["10Y"] == minute


def test_fresh_spread_minutes_drops_everything_before_the_first_print():
    frame = _session_frame()
    out = warm.fresh_spread_minutes(
        [datetime.datetime(2026, 7, 24, 8, 0, tzinfo=ET)], frame, _TAGS
    )
    assert "10Y" not in out


def test_fresh_spread_minutes_skips_a_tag_the_slice_does_not_carry():
    frame = _session_frame().drop(columns=["TAG10"])
    out = warm.fresh_spread_minutes(
        [datetime.datetime(2026, 7, 24, 12, 0, tzinfo=ET)], frame, _TAGS
    )
    assert set(out) == {"3M"}


def test_the_day_slice_survives_an_empty_frame():
    assert warm.slice_spreads_for_day(pd.DataFrame(), datetime.date(2026, 7, 29),
                                      lookback=datetime.timedelta(days=5)).empty


# ------------------------------------------------------------------ #
#         6. the process-wide quotes default and its ownership       #
# ------------------------------------------------------------------ #


@pytest.fixture
def ss_mod():
    from MDP.IRSwaps.CITIVELO_EXCEL import swap_spreads as module

    module.set_default_quotes(None)
    module.set_force_offline(None)
    yield module
    module.set_default_quotes(None)
    module.set_force_offline(None)


def test_the_installed_default_is_returned_and_not_owned(ss_mod):
    sentinel = object()
    ss_mod.set_default_quotes(sentinel)
    quotes = ss_mod._default_quotes(offline=False, client_kwargs=None)
    assert quotes is sentinel
    assert ss_mod._owns_quotes(quotes) is False, (
        "a borrower that closes the shared default leaves every later call in the "
        "run reading through a torn-down client"
    )


def test_a_lazily_built_quotes_object_is_owned(ss_mod):
    quotes = ss_mod._default_quotes(offline=True, client_kwargs=None)
    assert ss_mod._owns_quotes(quotes) is True
    assert quotes.offline is True


def test_the_shared_default_survives_a_fetch(ss_mod):
    """The end-to-end shape of the ownership rule: one install, many calls."""
    import datetime as _dt

    import pandas as _pd

    index = _pd.date_range("2026-07-24", "2026-07-30", freq="h")
    tag = "RATES.OIS.USD_SOFR.SWAP_SPREAD.10Y"
    frame = _pd.DataFrame({tag: range(len(index))}, index=index, dtype=float)
    installed = warm.DayQuotes(frame)
    ss_mod.set_default_quotes(installed)

    first = ss_mod.fetch_swap_spread("USD_SOFR", "10Y", _dt.datetime(2026, 7, 29, 12, 0))
    second = ss_mod.fetch_swap_spread("USD_SOFR", "10Y", _dt.datetime(2026, 7, 29, 13, 0))
    assert second.value > first.value
    assert ss_mod.default_quotes() is installed


def test_force_offline_pins_a_lazily_built_object(ss_mod, monkeypatch):
    monkeypatch.delenv("ARBS_CITIVELO_QUOTES_OFFLINE", raising=False)
    assert ss_mod.force_offline() is False
    ss_mod.set_force_offline(True)
    quotes = ss_mod._default_quotes(offline=False, client_kwargs=None)
    assert quotes.offline is True


def test_force_offline_reads_the_env_when_unset(ss_mod, monkeypatch):
    monkeypatch.setenv("ARBS_CITIVELO_QUOTES_OFFLINE", "1")
    ss_mod.set_force_offline(None)
    assert ss_mod.force_offline() is True


# ------------------------------------------------------------------ #
#                        7. the minute grid                          #
# ------------------------------------------------------------------ #


class _StubStore:
    def __init__(self, stamps):
        self._frame = pd.DataFrame({"timestamp_utc": stamps})

    def read_raw_nodes(self, asset, start, end):  # noqa: ARG002 - stub
        return self._frame


def test_session_minutes_floors_dedupes_and_localises():
    stamps = pd.to_datetime(
        [
            "2026-07-29T13:00:00Z",
            "2026-07-29T13:00:30Z",  # same minute, different second
            "2026-07-29T13:01:00Z",
        ],
        utc=True,
    )
    minutes = warm.session_minutes(_StubStore(stamps), datetime.date(2026, 7, 29))
    assert len(minutes) == 2
    assert all(m.tzinfo is not None for m in minutes)
    assert minutes[0].astimezone(ET).hour == 9
    assert minutes == sorted(minutes)


def test_session_minutes_is_empty_for_an_unwarmed_day():
    assert warm.session_minutes(_StubStore(pd.to_datetime([], utc=True)),
                                datetime.date(2026, 7, 29)) == []


def test_default_end_stays_out_of_the_staleness_window():
    """``IRSwapsTB`` evicts and reprices anything newer, so warming it is waste."""
    from TB.IRSwapsTB import IRSwapsTB

    lag = (datetime.date.today() - warm.default_end()).days
    assert lag >= IRSwapsTB._STALE_THRESHOLD_DAYS

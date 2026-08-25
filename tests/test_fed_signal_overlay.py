"""Tests for the macro-state overlay on the intraday Fed speaker book.

The failure this suite exists to prevent is a conditioning rule that quietly
does nothing: a book that is indistinguishable from an unconditioned one, and
that reports "no edge" when what it actually found was a broken join.

Every test name is a sentence stating the invariant; every docstring says what
breaks silently without it. Where a defect was measured while building this, its
number is in the docstring.
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
STUDY = REPO / "notebooks" / "backtests" / "intraday_fed_hawk_dove"
for _p in (str(REPO), str(REPO / "notebooks" / "rv"), str(STUDY)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fed_signal_overlay as SIG  # noqa: E402


# ---- fixtures -------------------------------------------------------------
@pytest.fixture(scope="module")
def state() -> pd.Series:
    """A W-FRI weekly state. Deliberately synthetic and sign-alternating so the
    agree/disagree partition has something to partition."""
    idx = pd.date_range("2022-01-07", periods=120, freq="W-FRI")
    v = np.where(np.arange(len(idx)) % 20 < 10, 1.5, -1.5)
    return pd.Series(v, index=idx, name="state")


def _pos_week(state: pd.Series) -> pd.Timestamp:
    """A Friday on which the state is POSITIVE, found rather than assumed.

    Hard-coding an index makes the test depend on the fixture's phase, and the
    first version of this file did exactly that and asserted the wrong sign.
    """
    return state.index[int(np.flatnonzero(state.to_numpy() > 0)[20])]


def _ev(when: str, bucket: int, tag: str = "T") -> dict:
    ts = pd.Timestamp(when, tz="America/New_York")
    return {"tag": tag, "bucket": bucket, "speech_ts": ts, "entry_ts": ts,
            "exit_ts": ts + pd.Timedelta(hours=4), "side": -1.0 if bucket > 0 else 1.0}


# ---- config validation ----------------------------------------------------
def test_a_typo_in_the_signal_block_raises_rather_than_falling_through_to_off():
    """A misspelled mode that silently became a no-op would produce a book
    indistinguishable from a conditioned one that found no edge -- which is the
    exact failure the module's own flip validation exists to prevent."""
    for bad in ({"mode": "FLIP"}, {"mode": "fade"}, {"state": "macro"},
                {"when": "agrees"}, {"threshold": -1.0}):
        with pytest.raises(ValueError):
            SIG.normalise(bad)


def test_the_default_block_is_a_perfect_no_op():
    """`mode='off'` must leave every reading of the state inert. This is the
    property that lets the knob ship without touching any existing config."""
    sig = SIG.normalise(None)
    assert sig["mode"] == "off"
    attrs = {"state_value": 3.0, "state_sign": 1}
    assert SIG.signal_sign(attrs, 1, sig) == 1.0
    assert SIG.signal_size(attrs, 1, sig) == 1.0
    assert SIG.keeps(attrs, 1, sig) is True


def test_the_cache_key_covers_everything_that_changes_the_series():
    """Two configs pointing at different states in one process must not collide.
    `hawk_dove_config._ROLE_CACHE` is keyed by a constant and is config-blind,
    which is why this cache is separate and keyed properly."""
    a = SIG.normalise({"state": "data", "lead_w": 5})
    b = SIG.normalise({"state": "data", "lead_w": 11})
    c = SIG.normalise({"state": "detach", "lead_w": 5})
    d = SIG.normalise({"state": "data", "lead_w": 5, "construction": "resid"})
    assert len({SIG.cache_key(x) for x in (a, b, c, d)}) == 4
    # mode/when/threshold change how the series is READ, not the series
    e = SIG.normalise({"state": "data", "lead_w": 5, "mode": "gate",
                       "when": "disagree", "threshold": 2.0})
    assert SIG.cache_key(a) == SIG.cache_key(e)


# ---- the join -------------------------------------------------------------
def test_a_friday_morning_entry_cannot_read_that_fridays_close(state):
    """THE LEAK THIS SUITE WAS WRITTEN FOR.

    A W-FRI weekly value is the last daily observation in the (Sat..Fri] bin --
    a number computed at that Friday's CLOSE -- but it is stamped at that
    Friday's midnight. Comparing an entry TIMESTAMP against the stamp lets a
    position opened at 09:00 on a Friday read a number that does not exist until
    16:00 that day, a look-ahead of most of a session on every Friday speech.

    The cutoff is therefore the entry DAY. A Friday entry reads the PREVIOUS
    Friday.
    """
    friday = state.index[50]
    ev = _ev(f"{friday.date()} 09:00", bucket=1)
    a = SIG.attach(ev, state, SIG.normalise({"mode": "flip"}))
    assert pd.Timestamp(a["state_week"]) == state.index[49]
    assert pd.Timestamp(a["state_week"]) < friday


def test_a_monday_entry_reads_the_friday_three_days_earlier(state):
    """The other side of the same rule: a Friday close IS readable from the next
    session on, so a Monday entry must get it. A rule that pushed the cutoff a
    whole week back would throw away five days of information on every event."""
    friday = state.index[50]
    monday = friday + pd.Timedelta(days=3)
    a = SIG.attach(_ev(f"{monday.date()} 09:00", 1), state,
                   SIG.normalise({"mode": "flip"}))
    assert pd.Timestamp(a["state_week"]) == friday


def test_an_event_before_the_state_starts_is_missing_not_zero(state):
    """Missing and zero are different. A missing state must leave the event
    alone; treating it as a zero-signed state would silently trade a rule the
    data cannot support."""
    a = SIG.attach(_ev("2019-06-03 09:00", 1), state, SIG.normalise({"mode": "flip"}))
    assert a["state_missing"] is True
    assert a["state_sign"] == 0
    assert np.isnan(a["state_value"])
    assert SIG.agrees(a, 1) is None
    assert SIG.signal_sign(a, 1, SIG.normalise({"mode": "flip"})) == 1.0


def test_the_threshold_is_a_band_not_a_sign_flip(state):
    """Inside the band the rule has nothing to say, and `agrees` must return
    None rather than False. Unknown is not disagreement -- the same distinction
    `hawk_dove_config` already makes for an unknown voting status."""
    sig = SIG.normalise({"mode": "flip", "threshold": 2.0})   # |state| is 1.5
    a = SIG.attach(_ev(f"{(state.index[50] + pd.Timedelta(days=3)).date()} 09:00", 1),
                   state, sig)
    assert not a["state_missing"]
    assert a["state_sign"] == 0
    assert SIG.agrees(a, 1) is None


def test_gate_cutoff_gate_FIRES_on_a_same_day_read(state, monkeypatch):
    """The paired anti-vacuity test: break the cutoff back to at-or-before and
    require G-S2 to catch it. Without this the gate could be a no-op."""
    real = SIG._asof_position

    def leaky(st, when):
        idx = st.index.values
        return int(np.searchsorted(idx, np.datetime64(pd.Timestamp(when)),
                                   side="right")) - 1

    monkeypatch.setattr(SIG, "_asof_position", leaky)
    evs = [_ev(f"{d.date()} 09:00", 1, tag=f"T{i}")
           for i, d in enumerate(state.index[30:60])]
    with pytest.raises(AssertionError, match="G-S2 FAILED"):
        SIG.gate_cutoff_is_before_entry(evs, state, SIG.normalise({"mode": "flip"}))
    monkeypatch.setattr(SIG, "_asof_position", real)


def test_the_point_in_time_gate_refuses_to_pass_vacuously(state):
    """G-S3. `gate_cutoff_is_before_entry` returns only the events whose state
    EXISTS, so on a state whose history starts after most of the book it can
    return an empty frame and pass. Measured while building this: the `detach`
    gate reported PASS having checked 0 of 400 events, because the first 400
    events of the raw book all predate 2023."""
    with pytest.raises(AssertionError, match="G-S3 FAILED"):
        SIG.gate_join_is_not_vacuous(pd.DataFrame(), name="empty")
    with pytest.raises(AssertionError, match="G-S3 FAILED"):
        SIG.gate_join_is_not_vacuous(pd.DataFrame({"x": [1, 2, 3]}), name="thin")
    assert SIG.gate_join_is_not_vacuous(pd.DataFrame({"x": range(40)})) == 40


def test_gate_cutoff_samples_across_the_book_not_a_prefix(state):
    """...and the sampling that makes G-S3 satisfiable: taking the first n
    events checks a prefix, which on a late-starting state is all misses."""
    early = [_ev(f"{d.date()} 09:00", 1, tag=f"E{i}")
             for i, d in enumerate(pd.date_range("2019-01-07", periods=300, freq="W-MON"))]
    late = [_ev(f"{d.date()} 09:00", 1, tag=f"L{i}")
            for i, d in enumerate(state.index[10:60] + pd.Timedelta(days=3))]
    out = SIG.gate_cutoff_is_before_entry(early + late, state,
                                          SIG.normalise({"mode": "flip"}), n=100)
    assert len(out) > 5, "a prefix-only sample would check zero matched events"


# ---- reading the state ----------------------------------------------------
def test_agree_means_the_speech_says_what_the_data_already_said(state):
    sig = SIG.normalise({"mode": "flip", "when": "agree"})
    d = _pos_week(state) + pd.Timedelta(days=3)
    hawk = SIG.attach(_ev(f"{d.date()} 09:00", +1), state, sig)
    assert hawk["state_sign"] == +1, "the fixture must give a positive state here"
    assert SIG.agrees(hawk, +1) is True
    assert SIG.agrees(hawk, -1) is False
    assert SIG.signal_sign(hawk, +1, sig) == -1.0    # the hawk is faded
    assert SIG.signal_sign(hawk, -1, sig) == +1.0    # the dove is not


def test_agree_and_disagree_flip_disjoint_complementary_subsets(state):
    """Two readings of one state must partition the in-band events, or the pair
    is not a partition and the search is not a search over two hypotheses."""
    sa = SIG.normalise({"mode": "flip", "when": "agree"})
    sd = SIG.normalise({"mode": "flip", "when": "disagree"})
    for i, d in enumerate(state.index[20:80] + pd.Timedelta(days=3)):
        for bucket in (-2, -1, 1, 2):
            ev = _ev(f"{d.date()} 09:00", bucket)
            a = SIG.attach(ev, state, sa)
            fa, fd = SIG.signal_sign(a, bucket, sa), SIG.signal_sign(a, bucket, sd)
            assert not (fa < 0 and fd < 0), "no event may be flipped by both"
            if a["state_sign"] != 0:
                assert (fa < 0) != (fd < 0), "exactly one reading must flip it"
            else:
                assert fa == fd == 1.0, "an out-of-band event is never flipped"


def test_the_size_mode_never_returns_zero_and_is_capped(state):
    """A zero-sized trade is still BOOKED as a trade, and a booked zero halves
    the hit rate, shrinks the standard deviation and thereby inflates the Sharpe
    of a book that did nothing. Standing aside is `mode='gate'`, which removes
    the event and counts it."""
    sig = SIG.normalise({"mode": "size", "size_cap": 2.0, "threshold": 0.0})
    big = pd.Series(np.full(len(state), 50.0), index=state.index)
    d = state.index[50] + pd.Timedelta(days=3)   # `big` is positive everywhere
    a = SIG.attach(_ev(f"{d.date()} 09:00", 1), big, sig)
    assert SIG.signal_size(a, 1, sig) == pytest.approx(2.0)
    b = SIG.attach(_ev("2019-01-07 09:00", 1), big, sig)     # missing state
    assert SIG.signal_size(b, 1, sig) == 1.0
    assert SIG.signal_size(a, -1, sig) == 1.0                # the other side


def test_a_gate_drops_an_event_with_no_state_rather_than_keeping_it(state):
    """`keeps` must be False when the state is unknown. Keeping such an event
    would make a gated book silently include everything before the state's
    history starts."""
    sig = SIG.normalise({"mode": "gate", "when": "agree"})
    missing = SIG.attach(_ev("2019-01-07 09:00", 1), state, sig)
    assert SIG.keeps(missing, 1, sig) is False
    d = _pos_week(state) + pd.Timedelta(days=3)
    live = SIG.attach(_ev(f"{d.date()} 09:00", 1), state, sig)
    assert live["state_sign"] == +1
    assert SIG.keeps(live, +1, sig) is True
    assert SIG.keeps(live, -1, sig) is False


# ---- the join report ------------------------------------------------------
def test_the_join_report_shows_the_match_rate_per_year(state):
    """FED events are business-day only and the state grid lands on Fridays, so
    an equality join matches ZERO events and a drop-if-missing filter would then
    return an empty book WITHOUT raising. The match rate has to be printed, not
    assumed."""
    evs = ([_ev(f"{d.date()} 09:00", 1, tag=f"E{i}")
            for i, d in enumerate(pd.date_range("2019-01-07", periods=50, freq="W-MON"))]
           + [_ev(f"{d.date()} 09:00", -1, tag=f"L{i}")
              for i, d in enumerate(state.index[10:60] + pd.Timedelta(days=3))])
    rep = SIG.join_report(evs, state, SIG.normalise({"mode": "flip"}))
    assert "ALL" in rep.index
    assert float(rep.loc[2019, "match_rate"]) == 0.0, (
        "the fixture must contain unmatched years for this to test anything")
    assert float(rep.loc["ALL", "match_rate"]) > 0.4
    assert int(rep.loc["ALL", "events"]) == len(evs)


# ---- the real states build ------------------------------------------------
@pytest.mark.parametrize("kind", ["data", "detach"])
def test_the_real_state_builds_and_is_trailing_only(kind):
    """G-S1 on the shipped estimators. Skipped rather than failed when the JPM
    corpus is absent, because it lives outside this repo."""
    sig = SIG.normalise({"mode": "flip", "state": kind, "lead_w": 5})
    try:
        st, prov = SIG.build_state(sig)
    except RuntimeError as e:
        pytest.skip(f"state {kind!r} unavailable here: {e}")
    assert len(st) > 100
    assert st.index.is_monotonic_increasing
    probes = list(st.index[-200::40])
    out = SIG.gate_state_is_trailing(sig, probe_dates=probes)
    assert not out.empty
    assert float(out["abs_diff"].max()) < 1e-9


def test_build_state_raises_RuntimeError_not_KeyError_on_a_bad_state():
    """`hawk_dove_config.compare` catches RuntimeError and nothing else. A
    KeyError from a data problem kills a whole comparison instead of reporting
    one bad row."""
    with pytest.raises(ValueError):
        SIG.build_state({"state": "nonsense"})

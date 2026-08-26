"""Tests for the Warsh-guidance information study.

The study's whole content is a before/after contrast on one date, measured on a
quantity that has to be roll-safe. So the invariants worth testing are the ones
that would leave the contrast looking fine while making it wrong: a meeting
resolving inside a measurement window, a degeneracy distance that is not
bounded, an era split that drifts, and a bucket assignment that double-counts.
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
RV = REPO / "notebooks" / "rv"
for _p in (str(REPO), str(RV)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fed_event_conditioning as FEC  # noqa: E402
import warsh_guidance_information as W  # noqa: E402


def _hist(rows):
    """Long ladder frame from ``(as_of, effective, jump_bp, stale)`` tuples."""
    df = pd.DataFrame(rows, columns=["as_of", "effective", "jump_bp", "stale"])
    df["as_of"] = pd.to_datetime(df["as_of"])
    df["effective"] = pd.to_datetime(df["effective"])
    df["n_live"] = df.groupby("as_of")["stale"].transform(lambda s: (~s).sum())
    df["contract"] = "ZQX"
    return df


# ---------------------------------------------------------------- roll safety
def test_a_daily_step_never_differences_across_a_resolution():
    """The roll discipline, and the single most dangerous failure here.

    Between two sessions a meeting can resolve. If the step takes "the next two
    meetings" fresh on each side it books the ROLL as a repricing, and on an
    FOMC day the roll is the entire decision -- which is exactly the day this
    study weighs most. Every step must read meetings strictly after its own
    LATER session, present on both marks.
    """
    # M1 resolves between the two sessions; only M2/M3 are legal for the step
    h = _hist([
        ("2026-01-05", "2026-01-06", 10.0, False),   # M1 -- resolves
        ("2026-01-05", "2026-03-17", 20.0, False),   # M2
        ("2026-01-05", "2026-04-28", 30.0, False),   # M3
        ("2026-01-06", "2026-03-17", 25.0, False),
        ("2026-01-06", "2026-04-28", 33.0, False),
    ])
    d = W.daily_path_change(h, n_meetings=2)
    assert len(d) == 1
    row = d.iloc[0]
    assert row["dpath_bp"] == pytest.approx((25.0 - 20.0) + (33.0 - 30.0))
    assert "2026-01-06" not in row["meetings"], (
        "the resolving meeting must not appear in the step's meeting set")
    assert row["meetings"] == "2026-03-17/2026-04-28"


def test_a_step_is_dropped_when_a_meeting_is_missing_on_the_later_mark():
    """A meeting priced on one side and absent on the other cannot be
    differenced. Silently substituting the next one available would fabricate a
    move, so the step must drop entirely."""
    h = _hist([
        ("2026-01-05", "2026-03-17", 20.0, False),
        ("2026-01-05", "2026-04-28", 30.0, False),
        ("2026-01-06", "2026-03-17", 25.0, False),   # 04-28 missing
    ])
    assert W.daily_path_change(h, n_meetings=2).empty


def test_stale_legs_never_enter_a_step():
    """`meeting_step_history` keeps stale legs and flags them; a stale ZQ pair
    gives a jump of exactly 0.00 that is indistinguishable from a genuinely flat
    meeting. Reading one as real would report a resolved meeting where there is
    no quote at all."""
    h = _hist([
        ("2026-01-05", "2026-03-17", 20.0, False),
        ("2026-01-05", "2026-04-28", 0.0, True),     # stale
        ("2026-01-05", "2026-06-16", 30.0, False),
        ("2026-01-06", "2026-03-17", 25.0, False),
        ("2026-01-06", "2026-04-28", 0.0, True),
        ("2026-01-06", "2026-06-16", 33.0, False),
    ])
    d = W.daily_path_change(h, n_meetings=2)
    assert len(d) == 1
    assert d.iloc[0]["meetings"] == "2026-03-17/2026-06-16"
    assert d.iloc[0]["dpath_bp"] == pytest.approx(5.0 + 3.0)


# ------------------------------------------------------- the degeneracy metric
@pytest.mark.parametrize("jump,want", [
    (0.0, 0.0), (25.0, 0.0), (-25.0, 0.0), (50.0, 0.0),
    (12.5, 12.5), (-12.5, 12.5),
    (10.0, 10.0), (20.0, 5.0), (30.0, 5.0),
])
def test_degeneracy_distance_is_distance_to_the_nearest_click(jump, want):
    """0 means the meeting is priced as a near-certain hold or a near-certain
    click; 12.5 -- half a click -- is the most undecided a meeting can be. If
    this were distance to zero instead, a fully-priced hike would read as
    maximum uncertainty and the whole T2 result would invert."""
    h = _hist([("2026-01-05", "2026-03-17", jump, False)])
    d = W.degeneracy_distance(h, n_meetings=1)
    assert d.iloc[0]["degen_dist_bp"] == pytest.approx(want)
    assert 0.0 <= d.iloc[0]["degen_dist_bp"] <= W.MAX_DEGENERACY_DISTANCE + 1e-9


def test_degeneracy_only_reads_meetings_AFTER_the_session():
    """A meeting effective today or earlier is not a forward-looking price. If
    past legs leaked in, the measure would carry resolved meetings whose jump is
    frozen, damping exactly the movement the study is looking for."""
    h = _hist([
        ("2026-03-17", "2026-01-06", 12.0, False),   # in the past
        ("2026-03-17", "2026-04-28", 12.5, False),
    ])
    d = W.degeneracy_distance(h, n_meetings=1)
    assert len(d) == 1
    assert d.iloc[0]["degen_dist_bp"] == pytest.approx(12.5)


def test_fixed_window_degeneracy_reads_ONE_meeting_set_at_every_horizon():
    """Every horizon t+0..t+5 must read the same meetings, chosen strictly after
    t+5. If the set were re-chosen per horizon, the t+5 column would contain a
    roll that the t+0 column does not, and the DiD at t+5 -- the study's headline
    -- would be measuring the roll."""
    sess = pd.bdate_range("2026-01-05", periods=10)   # 2026-01-05 .. 2026-01-16
    # T = sess[2] = 2026-01-07, so the horizons run out to sess[7] = 2026-01-14.
    # The meeting that must be excluded is one landing INSIDE that span.
    inside = sess[5].date()                            # 2026-01-12
    assert sess[2] < pd.Timestamp(inside) <= sess[7], "fixture must straddle"
    rows = []
    for i, d in enumerate(sess):
        rows.append((d, str(inside), 5.0, False))      # resolves inside the span
        rows.append((d, "2026-09-15", 6.0 + i, False))
        rows.append((d, "2026-10-27", 7.0, False))
    r = W.fixed_window_degeneracy(_hist(rows), sess[2], pre_days=1, max_post=5,
                                  n_meetings=2)
    assert r is not None
    assert str(inside) not in r["meetings"]
    assert r["meetings"] == "2026-09-15/2026-10-27"
    for k in range(6):
        assert np.isfinite(r[f"d_degen_t{k}"])


# --------------------------------------------------------------- era + class
def test_the_era_boundary_is_the_day_after_the_june_announcement():
    """The whole study is a before/after on this one date. Drifting it by a
    meeting would still produce numbers."""
    assert W.WARSH_BOUNDARY == pd.Timestamp("2026-06-18")
    e = W.era_of(["2026-06-17", "2026-06-18", "2026-06-19"])
    assert list(e) == ["guidance", "warsh", "warsh"]


def test_scheduled_and_discretionary_partition_the_event_types():
    """The scheduled/discretionary split IS the identification for the selection
    objection. A type landing in the wrong bucket -- or in neither -- would put
    an event Warsh can decline into the class defined as one he cannot."""
    got = W.klass_of(list(FEC.EVENT_TYPES))
    for t, k in zip(FEC.EVENT_TYPES, got):
        assert k == ("scheduled" if t in FEC.SETPIECE_TYPES else "discretionary")
    assert set(got) == {"scheduled", "discretionary"}
    assert W.klass_of(["speech"])[0] == "discretionary"
    assert W.klass_of(["press_conference"])[0] == "scheduled"


# ------------------------------------------------------------------- buckets
def test_variance_buckets_partition_the_days_and_speaker_wins_collisions():
    """Speaker days must take precedence on collision, which makes the speaker
    bucket the GENEROUS one -- so a finding that the speaker share FELL could
    not have been produced by the assignment. Days must also partition: a day
    counted twice inflates one share and deflates another."""
    idx = pd.bdate_range("2026-01-05", periods=6)
    dp = pd.DataFrame({"dpath_bp": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
                       "meetings": "x", "n_live": 8}, index=idx)
    ev = pd.DatetimeIndex([idx[0], idx[1]])
    rel = pd.DatetimeIndex([idx[1], idx[2]])          # idx[1] collides
    out = W.variance_buckets(dp, ev, rel, boundary=pd.Timestamp("2100-01-01"))
    assert int(out["days"].sum()) == len(idx)
    assert out["var_share_pct"].sum() == pytest.approx(100.0)
    sp = out[out["bucket"] == "speaker"]["days"].iloc[0]
    assert sp == 2, "the colliding day must go to the speaker bucket"
    assert out[out["bucket"] == "release"]["days"].iloc[0] == 1


def test_silence_gaps_contain_no_speech_days_and_respect_the_minimum():
    """A 'silence gap' with a speech in it is not silence, and the H2 test reads
    exactly these runs. Off-by-one here would fold speech days into the quiet
    measurement and blunt the very contrast being tested."""
    idx = pd.bdate_range("2026-01-05", periods=12)
    dp = pd.DataFrame({"dpath_bp": np.ones(12), "meetings": "x", "n_live": 8},
                      index=idx)
    scores = pd.DataFrame({"date": [idx[0], idx[5], idx[6]]})
    g = W.silence_gaps(scores, dp, boundary=pd.Timestamp("2100-01-01"),
                       min_gap_bd=3)
    assert len(g) > 0
    spoke = {pd.Timestamp(d).normalize() for d in scores["date"]}
    for _, r in g.iterrows():
        span = pd.DatetimeIndex(idx[(idx >= r["start"]) & (idx <= r["end"])])
        assert not (set(span) & spoke), "a gap contains a speech day"
        assert r["len_bd"] >= 3
        assert r["abs_move_bp"] == pytest.approx(float(r["len_bd"]))


# --------------------------------------------------------------------- gates
def test_the_boundary_gate_rejects_a_date_that_is_not_a_meeting():
    """G-W1 exists because a drifted boundary produces a complete set of results
    that mean nothing. The gate must actually fail on a bad date -- if it passes
    everything it proves nothing."""
    real = W.WARSH_BOUNDARY
    try:
        W.WARSH_BOUNDARY = pd.Timestamp("2026-07-04")   # no FOMC within 3 days
        with pytest.raises(AssertionError, match="G-W1"):
            W.gate_boundary_is_a_real_meeting(pd.DataFrame())
    finally:
        W.WARSH_BOUNDARY = real
    # ...and passes on the real one
    assert W.gate_boundary_is_a_real_meeting(pd.DataFrame())["boundary"] == \
        real.date()


def test_the_resolution_gate_fires_on_a_frame_that_violates_it():
    """G-W2 protects the finding it is most able to fake. A gate that cannot be
    made to fail is decoration, so this hands it a step whose meeting resolves
    inside itself and requires the assertion."""
    h = _hist([
        ("2026-01-05", "2026-03-17", 20.0, False),
        ("2026-01-06", "2026-03-17", 25.0, False),
    ])
    bad = pd.DataFrame({"dpath_bp": [5.0], "meetings": ["2026-01-06"],
                        "n_live": [8]},
                       index=pd.DatetimeIndex([pd.Timestamp("2026-01-06")]))
    with pytest.raises(AssertionError, match="G-W2"):
        W.gate_dpath_never_spans_a_resolution(h, bad, sample=10)


def test_the_empty_warsh_gate_fires_when_a_class_is_missing():
    """A before/after whose 'after' is empty returns NaN, and a NaN read as 'no
    difference' is this study's most likely silent failure."""
    p = pd.DataFrame({"date": pd.to_datetime(["2024-01-05", "2026-07-06"]),
                      "type": ["speech", "speech"], "y": [1.0, 2.0]})
    # discretionary present in both eras -> passes
    assert W.gate_warsh_window_is_not_empty(p)
    p2 = pd.DataFrame({"date": pd.to_datetime(["2024-01-05", "2024-02-05"]),
                       "type": ["speech", "fomc_decision"], "y": [1.0, 2.0]})
    with pytest.raises(AssertionError, match="G-W3"):
        W.gate_warsh_window_is_not_empty(p2)


# ------------------------------------------------------------- arrival rate
def test_arrival_rate_matches_the_SAME_calendar_window_in_every_year():
    """Season matching is the difference between a result and an artefact here:
    the window contains the summer recess and the Jackson Hole run-up, so an
    all-season base rate would find 'Warsh speaks less' for a chair who behaved
    identically. Each matched row must cover the same month/day span."""
    dates = []
    for y in (2023, 2024, 2025, 2026):
        dates += list(pd.bdate_range(f"{y}-06-18", f"{y}-08-25")[:10])
        dates += list(pd.bdate_range(f"{y}-01-05", f"{y}-02-05"))   # off-window
    sc = pd.DataFrame({"date": pd.to_datetime(dates)})
    a = W.arrival_rate(sc, years=(2023, 2024, 2025))
    assert len(a) == 4
    for _, r in a.iterrows():
        lo, hi = [pd.Timestamp(x) for x in r["window"].split("..")]
        assert (lo.month, lo.day) == (6, 18)
        assert (hi.month, hi.day) == (8, 25)
        assert r["speeches"] == 10, "off-window dates must not be counted"
    assert bool(a[a["year"] == 2026]["is_warsh"].iloc[0])
    assert a.attrs["ratio"] == pytest.approx(1.0, abs=0.05)


def test_arrival_rate_drops_years_where_the_corpus_is_not_dense():
    """The JPM book carries rows back to 2008 but only becomes dense in 2023. A
    sparse matched year would read as a low arrival rate that is a property of
    the corpus, not of the Fed, and would make Warsh look normal by comparison."""
    dates = []
    for y in (2021, 2024, 2025, 2026):
        dates += list(pd.bdate_range(f"{y}-06-18", f"{y}-08-25")[:8])
    sc = pd.DataFrame({"date": pd.to_datetime(dates)})
    a = W.arrival_rate(sc, years=(2021, 2024, 2025),
                       dense_from=pd.Timestamp("2023-01-01"))
    assert 2021 not in set(a["year"]), "a pre-dense year must be dropped"
    assert set(a["year"]) == {2024, 2025, 2026}


def test_decidable_date_moves_forward_and_is_flat_once_reached():
    n = W.decidable_date(6, 20, per_month=2.65)
    assert n > pd.Timestamp("2026-08-25")
    assert W.decidable_date(30, 20, per_month=2.65) == pd.Timestamp("2026-08-25")

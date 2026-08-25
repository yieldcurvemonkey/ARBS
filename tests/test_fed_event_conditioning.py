"""Tests for the Fedspeak event-conditioning study.

Every test name states the invariant; every docstring says what breaks silently
without it, and where a defect was actually measured while building the study,
the number is in the docstring.
"""
from __future__ import annotations

import dataclasses
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

import fed_event_conditioning as E  # noqa: E402


# ---- fixtures -------------------------------------------------------------
def _hist(dates, meetings) -> pd.DataFrame:
    """A synthetic ladder history: every date prices every meeting."""
    rows = []
    for i, d in enumerate(dates):
        for j, m in enumerate(meetings):
            rows.append({"as_of": pd.Timestamp(d), "effective": pd.Timestamp(m),
                         "jump_bp": float(i + j), "stale": False,
                         "n_live": len(meetings), "contract": f"ZQ{j}"})
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def sent() -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-01", periods=200)
    rng = np.random.default_rng(4)
    s = pd.Series(np.cumsum(rng.normal(size=len(idx))), index=idx)
    return pd.DataFrame({"sentiment": s, "z": (s - s.mean()) / s.std()})


# ---- the dependent variable ----------------------------------------------
def test_y_is_a_FIXED_pair_of_meetings_that_survive_the_window(sent):
    """THE defect this study is most exposed to.

    At an FOMC event a meeting RESOLVES inside the window, so "the next two
    meetings" at entry and at exit are different meetings. Differencing those
    two sums measures the roll, not the repricing -- and on a decision day the
    roll IS the decision, which this study measures at **17.4x** the
    non-decision language effect. The panel must therefore pick meetings
    strictly after the EXIT session and match them by effective date.
    """
    dates = pd.bdate_range("2024-03-01", periods=20)
    meetings = ["2024-03-06", "2024-05-01", "2024-06-12", "2024-07-31"]
    hist = _hist(dates, meetings)
    # an event straddling the 2024-03-06 meeting
    ev = pd.DataFrame([{"date": pd.Timestamp("2024-03-05"), "type": "fomc_decision",
                        "speaker": None, "score": np.nan, "derived": False}])
    cfg = dataclasses.replace(E.PRIMARY, n_meetings=2)
    panel, _r = E.event_panel(ev, hist, sent, cfg)
    assert len(panel) == 1
    used = str(panel.iloc[0]["meetings"]).split("/")
    exit_ = pd.Timestamp(panel.iloc[0]["exit"])
    assert all(pd.Timestamp(m) > exit_ for m in used), used
    # the resolving meeting must NOT be one of them
    assert "2024-03-06" not in used
    E.gate_y_is_a_fixed_pair(panel)


def test_gate_y_is_a_fixed_pair_FIRES_when_a_meeting_resolves_inside(sent):
    """The paired anti-vacuity test: hand the gate a panel whose meeting legs
    sit inside their own window and require it to raise. Without this the gate
    could be a no-op and every run would pass."""
    bad = pd.DataFrame([{"date": pd.Timestamp("2024-03-05"),
                         "exit": pd.Timestamp("2024-03-08"),
                         "meetings": "2024-03-06/2024-05-01"}])
    with pytest.raises(AssertionError, match="G-E3 FAILED"):
        E.gate_y_is_a_fixed_pair(bad)


def test_an_event_is_dropped_when_a_meeting_is_not_priced_on_both_marks(sent):
    """Half a difference is not a difference. A meeting priced at entry and
    missing at exit would otherwise contribute its entry level as if it were a
    change."""
    dates = list(pd.bdate_range("2024-03-01", periods=20))
    # four meetings, so the min_live_meetings guard is satisfied and the drop
    # that fires is the one this test is about -- with two, the event was
    # correctly dropped for the WRONG reason and the test proved nothing
    meetings = ["2024-06-12", "2024-07-31", "2024-09-18", "2024-11-07"]
    hist = _hist(dates, meetings)
    # drop one meeting on the exit side of an event
    drop = pd.Timestamp(dates[6])
    hist = hist[~((hist["as_of"] == drop) &
                  (hist["effective"] == pd.Timestamp("2024-07-31")))]
    ev = pd.DataFrame([{"date": pd.Timestamp(dates[5]), "type": "speech",
                        "speaker": None, "score": np.nan, "derived": False}])
    panel, reasons = E.event_panel(ev, hist, sent, E.PRIMARY)
    assert panel.empty
    assert reasons.get("meeting not priced on both marks", 0) == 1


def test_stale_ladder_legs_are_dropped_not_traded(sent):
    """The ladder FLAGS stale meetings and never drops them, by design. A stale
    ZQ pair produces a jump of exactly 0.00 that is indistinguishable from a
    genuinely flat meeting, so the consumer has to filter."""
    dates = list(pd.bdate_range("2024-03-01", periods=10))
    hist = _hist(dates, ["2024-06-12", "2024-07-31"])
    hist.loc[hist["effective"] == pd.Timestamp("2024-06-12"), "stale"] = True
    on = pd.Timestamp(dates[3])
    got = E.steps_on(hist, on)
    assert pd.Timestamp("2024-06-12") not in got.index
    assert pd.Timestamp("2024-07-31") in got.index


# ---- the sample floor -----------------------------------------------------
def test_asking_for_a_ladder_before_the_registry_starts_raises():
    """An unregistered meeting month is silently treated as a non-meeting ANCHOR
    month, which CORRUPTS the anchor-walk rather than truncating it -- so a
    ladder before 2021-01-27 is wrong, not merely absent, and must refuse."""
    with pytest.raises(RuntimeError, match="registry starts"):
        E.meeting_step_history("2019-01-02", "2019-06-30")


# ---- the forward read -----------------------------------------------------
def test_forward_read_looks_back_exactly_the_lead():
    """The arithmetic the Jackson Hole answer rests on: at a lead of L weeks the
    data surfacing on date D is the composite as it stood L weeks BEFORE D. An
    off-by-sign here would reverse the entire conclusion."""
    try:
        out = E.forward_read(["2026-08-28"], leads_w=(5, 11, 14))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"surprise snapshot unavailable: {exc}")
    r = out.iloc[0]
    D = pd.Timestamp("2026-08-28")
    for Lw in (5, 11, 14):
        read = pd.Timestamp(r[f"reads_data_of_L{Lw}"])
        gap = (D - read).days
        # the weekly grid means the read lands in [L, L+7) days back
        assert 7 * Lw <= gap < 7 * Lw + 7, (Lw, gap)


# ---- the shared calendar --------------------------------------------------
def test_the_calendar_gives_both_arms_the_same_setpiece_universe():
    """The JPM corpus has NO field identifying the kind of communication.
    Measured before this was fixed: its set-piece universe was decisions and
    minutes only, so the JPM slope was -6.22 while FedLock's was +2.01 -- a
    difference of universe masquerading as a difference of judge. With one
    shared calendar both arms read +1.7 to +2.2."""
    try:
        cal = E.setpiece_calendar("2023-01-01", "2024-12-31")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"calendar sources unavailable: {exc}")
    types = set(cal["type"])
    assert {"fomc_decision", "minutes", "press_conference"} <= types, types
    assert cal["date"].is_monotonic_increasing
    assert not cal.duplicated(subset=["date", "type"]).any()


def test_minutes_land_three_weeks_after_the_decision_on_a_business_day():
    """The release rule since early 2005. Before then minutes followed the NEXT
    meeting, which is why the sample floor matters for this too."""
    try:
        cal = E.setpiece_calendar("2023-01-01", "2024-12-31")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"calendar sources unavailable: {exc}")
    dec = sorted(cal.loc[cal["type"] == "fomc_decision", "date"])
    mins = set(cal.loc[cal["type"] == "minutes", "date"])
    assert len(dec) >= 8
    hit = 0
    for d in dec:
        want = d + pd.Timedelta(days=21)
        while want.weekday() >= 5:
            want += pd.Timedelta(days=1)
        if want in mins:
            hit += 1
    assert hit >= len(dec) - 2, f"{hit} of {len(dec)}"


def test_gate_jackson_hole_FIRES_on_a_date_nothing_happened_on(monkeypatch):
    """The JH dates are the only hand-typed input. A wrong one would put an
    event on a day nothing happened and the study could not notice by itself, so
    the hand entry is turned into a claim the corpus has to corroborate."""
    try:
        cal = E.setpiece_calendar("2023-01-01", "2024-12-31")
        import fedlock_data as F

        sp, _ = F.load_speeches()
        scores = F.to_score_book(sp, score_column="m")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"corpus unavailable: {exc}")
    E.gate_jackson_hole(cal, scores)          # the real table passes
    monkeypatch.setattr(E, "JACKSON_HOLE", {**E.JACKSON_HOLE, 2024: "2024-12-25"})
    with pytest.raises(AssertionError, match="G-E2 FAILED"):
        E.gate_jackson_hole(cal, scores)


# ---- the regression -------------------------------------------------------
def test_ols_recovers_a_planted_slope():
    rng = np.random.default_rng(1)
    x = rng.normal(size=400)
    y = 3.0 * x + rng.normal(size=400) * 0.5
    o = E.ols(y, x)
    assert abs(o["beta"] - 3.0) < 0.1
    assert o["t"] > 10
    assert o["r2"] > 0.9


def test_ols_returns_nan_rather_than_a_number_on_too_few_points():
    """A slope from six events is not a slope. Returning NaN keeps a thin cut
    out of the tables instead of putting a confident-looking number in one."""
    o = E.ols(np.arange(5.0), np.arange(5.0))
    assert not np.isfinite(o["beta"])


def test_the_verdict_requires_all_three_tests():
    """ALIVE needs a positive slope, a CI excluding zero AND beating the
    non-event null. Any two of three is not a result, and the rule is applied
    mechanically so that reading the table cannot soften it."""
    good = {"primary": {"beta": 5.0, "t": 3.0},
            "primary_boot": {"lo": 1.0, "hi": 9.0},
            "null": {"beta_q95": 2.0}}
    assert E.verdict(good)["alive"] is True
    for key, patch in (("primary", {"beta": -5.0, "t": -3.0}),
                       ("primary_boot", {"lo": -1.0, "hi": 9.0}),
                       ("null", {"beta_q95": 99.0})):
        bad = {**good, key: patch}
        assert E.verdict(bad)["alive"] is False, key


def test_the_matched_null_buffers_on_setpiece_events_only(sent):
    """An ordinary speech day is deliberately eligible as a CONTROL: the claim
    is that the effect concentrates at scheduled communications, and excluding
    every speech day would test something weaker. It also broke the null --
    measured, the pool collapsed to 154 days when every speech was buffered."""
    dates = list(pd.bdate_range("2024-01-01", periods=150))
    hist = _hist(dates, ["2025-01-29", "2025-03-19", "2025-05-07"])
    ev = pd.DataFrame(
        [{"date": pd.Timestamp(d), "type": "speech", "speaker": None,
          "score": np.nan, "derived": False} for d in dates[::2]]
        + [{"date": pd.Timestamp(dates[10]), "type": "minutes", "speaker": None,
            "score": np.nan, "derived": True}])
    panel, _r = E.event_panel(ev[ev["type"] == "minutes"], hist, sent, E.PRIMARY)
    out = E.matched_non_event_null(panel, ev, hist, sent, E.PRIMARY, draws=5)
    # with only ONE set-piece event buffered, the pool must be nearly all days
    assert out.get("pool_days", 0) > 100, out


# ---- the power arithmetic -------------------------------------------------
def test_power_scales_as_the_square_of_the_t_ratio():
    """n* = n (t_target / t_obs)^2. This is the number the whole verdict turns
    on -- the study dies at the standard error, not at the cost line -- so the
    arithmetic is pinned rather than trusted."""
    panel = pd.DataFrame({
        "date": pd.bdate_range("2024-01-01", periods=40),
        "type": "minutes", "is_decision": False, "is_setpiece": True,
        "x": np.linspace(-1, 1, 40),
        "x_dev": np.nan,
        "y": np.linspace(-1, 1, 40) * 2.0 + np.random.default_rng(2).normal(size=40),
    })
    res = E.study_a(panel, panel, _hist(list(panel["date"]), ["2026-01-28"]),
                    pd.DataFrame({"sentiment": [], "z": []}), E.PRIMARY,
                    null_draws=0)
    pw, pr = res["power"], res["primary"]
    want = pr["n"] * (2.0 / pr["t"]) ** 2
    assert abs(pw["events_for_abs_t_2"] - want) < 1e-6
    assert pw["extra_events_needed"] == pytest.approx(want - pr["n"])


def test_the_size_block_compares_against_a_real_round_trip():
    """`beta` is bp per SD OF THE INDEX; a trade collects `beta * sd(x)`. Quoting
    the first as if it were the second overstates the edge by 1/sd(x) -- about
    2x on this data."""
    panel = pd.DataFrame({
        "date": pd.bdate_range("2024-01-01", periods=40),
        "type": "minutes", "is_decision": False, "is_setpiece": True,
        "x": np.linspace(-0.5, 0.5, 40), "x_dev": np.nan,
        "y": np.linspace(-0.5, 0.5, 40) * 4.0,
    })
    res = E.study_a(panel, panel, _hist(list(panel["date"]), ["2026-01-28"]),
                    pd.DataFrame({"sentiment": [], "z": []}), E.PRIMARY,
                    null_draws=0)
    s = res["size"]
    assert s["sr3_round_trip_bp"] == 0.50
    assert s["bp_per_1sd_of_x"] == pytest.approx(
        res["primary"]["beta"] * s["sd_of_x"])
    assert s["clears_the_spread"] is bool(abs(s["bp_per_1sd_of_x"]) > 0.50)

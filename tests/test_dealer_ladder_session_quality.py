"""Session-quality gate tests.

The gate removes whole sessions from the study, so the failure that matters is not "it crashed"
but "it silently removed the wrong days" — either dropping good sessions (power lost, and a
filter that tracks the calendar becomes a selection effect) or keeping bad ones (the defects it
exists to remove flow straight into the signal).

Each detector is therefore tested against an input whose correct verdict is already known, and
the boundaries are tested from both sides.
"""
import datetime

import pandas as pd
import pytest

from BT.dealer_ladder import session_quality as sq


def _row(d, *, last_hour=17, median=-0.35, n_outrights=400, large_packages=50, units=500):
    """One session's measured metrics, defaulting to a healthy day."""
    return {
        "session_date": d,
        "units": units,
        "last_et": pd.Timestamp(f"{d} {last_hour:02d}:30:00"),
        "n_outrights": n_outrights,
        "median_spread_bp": median,
        "pct_suspect": 15.0,
        "large_packages": large_packages,
        "max_legs": 60,
    }


@pytest.fixture
def assess(monkeypatch):
    """Call the REAL `assess_sessions`, with the metrics query stubbed.

    Re-implementing the flag logic in the test would leave every assertion below passing
    against a copy of the rules rather than the rules themselves — a bug in `assess_sessions`
    would be invisible. Stubbing only `pd.read_sql` keeps the DB out and puts the actual
    detector code, thresholds and early-close exemption under test.
    """
    def _run(rows, config=None):
        frame = pd.DataFrame(rows)
        monkeypatch.setattr(sq.pd, "read_sql",
                            lambda *a, **k: frame.copy(), raising=True)
        return sq.assess_sessions(object(), (D(2026, 1, 12), D(2026, 7, 29)),
                                  config or sq.SessionQualityConfig())
    return _run


D = datetime.date


# ----------------------------------------------------------------- D1 truncation
def test_healthy_session_is_kept(assess):
    out = assess([_row(D(2026, 3, 10))])
    assert not out["excluded"].iloc[0]


def test_truncated_session_is_flagged(assess):
    """2026-07-24: the feed died at 06:55 ET with the cash session missing."""
    out = assess([_row(D(2026, 7, 24), last_hour=6, large_packages=0)])
    assert out["d1_truncated"].iloc[0]


def test_scheduled_early_close_is_not_a_defect(assess):
    """Good Friday closes early. Flagging it would drop a real session.

    This is a regression test: the first scan called 2026-04-03 a dead feed.
    """
    assert D(2026, 4, 3) in sq.EARLY_CLOSE
    out = assess([_row(D(2026, 4, 3), last_hour=11)])
    assert not out["d1_truncated"].iloc[0]
    assert not out["excluded"].iloc[0]


def test_d1_boundary_is_exclusive_from_both_sides(assess):
    cfg = sq.SessionQualityConfig()
    late = assess([_row(D(2026, 3, 10), last_hour=cfg.min_last_hour_et)])
    early = assess([_row(D(2026, 3, 11), last_hour=cfg.min_last_hour_et - 1)])
    assert not late["d1_truncated"].iloc[0]
    assert early["d1_truncated"].iloc[0]


# ----------------------------------------------------------------- D2 packaging
def test_zero_large_packages_is_flagged(assess):
    """From 2026-07-21 the tape stopped emitting packages with more than four legs."""
    out = assess([_row(D(2026, 7, 22), large_packages=0)])
    assert out["d2_pkg_broken"].iloc[0]


def test_one_large_package_is_enough_to_pass(assess):
    """The test fires only on TOTAL loss, deliberately — it is the weakest form."""
    out = assess([_row(D(2026, 7, 22), large_packages=1)])
    assert not out["d2_pkg_broken"].iloc[0]


def test_missing_package_count_is_not_treated_as_broken(assess):
    """No evidence is not evidence of a defect.

    Treating a NULL as zero would fail every session the tape has not been ingested for.
    """
    out = assess([_row(D(2026, 3, 10), large_packages=None)])
    assert not out["d2_pkg_broken"].iloc[0]


# ----------------------------------------------------------------- D3 displaced mid
def test_displaced_mid_is_flagged(assess):
    out = assess([_row(D(2026, 6, 22), median=-9.78)])
    assert out["d3_mid_displaced"].iloc[0]


def test_clean_mid_is_kept(assess):
    out = assess([_row(D(2026, 1, 20), median=-0.32)])
    assert not out["d3_mid_displaced"].iloc[0]


@pytest.mark.parametrize("median,flagged", [
    (-1.913, False),   # the largest clean session measured over the window
    (-2.092, True),    # the smallest displaced session measured
    (2.092, True),     # sign must not matter: it is |median| that is tested
    (-2.0, False),     # strictly greater-than, so exactly at the threshold is kept
])
def test_d3_threshold_sits_between_the_two_measured_clusters(assess, median, flagged):
    out = assess([_row(D(2026, 5, 8), median=median)])
    assert bool(out["d3_mid_displaced"].iloc[0]) is flagged


def test_thin_session_is_not_judged_on_an_unreliable_median(assess):
    """A median of a dozen trades cannot support the test, so D1/D2 judge the day instead."""
    out = assess([_row(D(2026, 3, 10), median=-9.0, n_outrights=12)])
    assert not out["d3_mid_displaced"].iloc[0]


# ----------------------------------------------------------------- wiring
def test_gate_is_disabled_by_default_in_the_study_config():
    """The pre-registered spec must run unchanged unless the arm is explicitly asked for."""
    from BT.dealer_ladder import config as cfg
    assert cfg.LadderStudyConfig().session_quality.enabled is False


def test_disabled_gate_excludes_nothing_without_touching_the_db():
    cfg = sq.SessionQualityConfig(enabled=False)
    assert sq.excluded_sessions(None, (D(2026, 1, 12), D(2026, 7, 29)), cfg) == set()


def test_reason_string_names_every_detector_that_fired(assess):
    df = assess([_row(D(2026, 7, 24), last_hour=6, large_packages=0, median=-12.5)])
    reason = ",".join(n for n, f in (("TRUNCATED", df["d1_truncated"].iloc[0]),
                                     ("PKG_BROKEN", df["d2_pkg_broken"].iloc[0]),
                                     ("MID_DISPLACED", df["d3_mid_displaced"].iloc[0])) if f)
    assert reason == "TRUNCATED,PKG_BROKEN,MID_DISPLACED"


def test_summarize_reports_the_cost_split_by_segment(assess):
    """The split matters more than the total: a filter that removes mostly from the holdout
    changes what the holdout can certify, which an aggregate number would hide."""
    rows = [_row(D(2026, 2, d), units=100) for d in (2, 3, 4)]           # in-sample, clean
    rows += [_row(D(2026, 6, 15), units=100, large_packages=0)]          # lockout, broken
    rows += [_row(D(2026, 6, 16), units=100)]                            # lockout, clean
    table = assess(rows)
    table["reason"] = ""
    out = sq.summarize(table, lockout_start=D(2026, 6, 10))
    ins = out[out["segment"] == "in-sample"].iloc[0]
    lok = out[out["segment"] == "lockout"].iloc[0]
    assert ins["sessions"] == 3 and ins["kept"] == 3
    assert lok["sessions"] == 2 and lok["kept"] == 1
    assert lok["pct_sessions_kept"] == 50.0
    assert lok["units_kept"] == 100


def test_summarize_on_empty_input_is_empty_not_an_error():
    assert sq.summarize(pd.DataFrame()).empty

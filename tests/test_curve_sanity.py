"""Curve-snapshot sanity predicates.

Each test encodes a case measured on the stored
``USD-OIS-Q12xM12STIRT-SERFFX-MIX23`` history over 2026-05-07..2026-08-07; the
docstrings name the trading date it came from so a future change can be checked
against the same evidence. Pure functions -- no store, no network, no rateslib.
"""

import datetime

import numpy as np
import pandas as pd
import pytest

from Caching.curve_sanity import (
    ANCHOR_BLOCK_JUMP,
    ANCHOR_MISMATCH,
    DEGENERATE_IDENTITY,
    NEGATIVE_FORWARD,
    NON_FINITE_DF,
    NON_POSITIVE_DF,
    OFF_MODAL_SHAPE,
    READ_DROP_CODES,
    WRITE_REJECT_CODES,
    filter_raw_frame,
    frame_defects,
    reference_rate,
    shape_signature,
    snapshot_defects,
)

D = datetime.date
ANCHOR = D(2026, 7, 21)

# A plausible MIX23 shape: anchor, FOMC-dated nodes, SR3 IMM tail, and the
# ref+2Y / ref+3Y mixed-spline boundary nodes.
FOMC_NODES = [D(2026, 7, 29), D(2026, 9, 16), D(2026, 10, 28), D(2026, 12, 9), D(2027, 1, 27)]
IMM_TAIL = [D(2028, 3, 15), D(2028, 6, 21), D(2028, 9, 20), D(2028, 12, 20)]
BOUNDARY = [D(2028, 7, 21), D(2029, 7, 21)]


def _curve(anchor=ANCHOR, nodes=None, rate=0.038):
    """Node dates + discount factors for a flat ``rate`` curve."""
    nodes = sorted(nodes if nodes is not None else FOMC_NODES + IMM_TAIL + BOUNDARY)
    dates = [anchor] + [n for n in nodes if n > anchor]
    dfs = [float(np.exp(-rate * (d - anchor).days / 360.0)) for d in dates]
    return dates, dfs


# ── single-snapshot predicates ──


def test_healthy_curve_has_no_defects():
    dates, dfs = _curve()
    assert snapshot_defects(dates, dfs, trading_date=ANCHOR) == ()


def test_identity_curve_is_degenerate():
    """2026-07-01: all 1,381 minutes stored with every discount factor 1.0."""
    dates, _ = _curve()
    assert DEGENERATE_IDENTITY in snapshot_defects(dates, [1.0] * len(dates))


def test_single_node_curve_is_not_called_degenerate():
    """A one-node curve is trivially all-ones; that is not the 07-01 failure."""
    assert DEGENERATE_IDENTITY not in snapshot_defects([ANCHOR], [1.0])


def test_non_finite_and_non_positive_discount_factors():
    dates, dfs = _curve()
    nan_dfs = list(dfs)
    nan_dfs[3] = float("nan")
    assert NON_FINITE_DF in snapshot_defects(dates, nan_dfs)

    neg_dfs = list(dfs)
    neg_dfs[3] = -0.5
    assert NON_POSITIVE_DF in snapshot_defects(dates, neg_dfs)


def test_mismatched_lengths_and_empty_input_are_rejected():
    dates, dfs = _curve()
    assert snapshot_defects(dates, dfs[:-1]) == ("empty_nodes",)
    assert snapshot_defects([], []) == ("empty_nodes",)


def test_negative_forward_is_reported_but_never_quarantined():
    """2026-05-29: 34 minutes of mixed-spline overshoot, implied fwd -0.2512%.

    Mild, confined to the extrapolated region, and a modelling call -- so it
    must surface in the codes and stay out of both action sets.
    """
    dates, dfs = _curve()
    dfs[-1] = dfs[-2] * 1.02  # discount factor rises => forward goes negative
    codes = snapshot_defects(dates, dfs)
    assert NEGATIVE_FORWARD in codes
    assert NEGATIVE_FORWARD not in READ_DROP_CODES
    assert NEGATIVE_FORWARD not in WRITE_REJECT_CODES


def test_anchor_mismatch_is_reported_but_never_quarantined():
    """The evening block anchors a calendar day early on every session.

    2026-06-18's evening anchors on 2026-06-17 -- the June FOMC effective date,
    the worst case for this -- with a complete roster, and reads within 1.3bp of
    the rest of its session. The mismatch is visible, not actionable.
    """
    dates, dfs = _curve()
    codes = snapshot_defects(dates, dfs, trading_date=ANCHOR + datetime.timedelta(days=1))
    assert ANCHOR_MISMATCH in codes
    assert ANCHOR_MISMATCH not in READ_DROP_CODES
    assert ANCHOR_MISMATCH not in WRITE_REJECT_CODES


# ── shape signature ──


def test_shape_signature_drops_anchor_and_spline_boundary_nodes():
    dates, _ = _curve()
    assert shape_signature(dates) == tuple(sorted(FOMC_NODES + IMM_TAIL))


def test_shape_signature_is_stable_across_the_evening_anchor_roll():
    """The evening block anchors a day early; its boundary nodes move with it.

    Both blocks price the same instruments, so both must fingerprint the same --
    otherwise the shape rule flags ~420 rows of every healthy session.
    """
    day_dates, _ = _curve(anchor=D(2026, 7, 21), nodes=FOMC_NODES + IMM_TAIL + BOUNDARY)
    eve_dates, _ = _curve(
        anchor=D(2026, 7, 20),
        nodes=FOMC_NODES + IMM_TAIL + [D(2028, 7, 20), D(2029, 7, 20)],
    )
    assert shape_signature(day_dates) == shape_signature(eve_dates)


# ── session-relative predicates ──


def _frame(rows):
    """rows: list of (timestamp, trading_date, node_dates, dfs)."""
    return pd.DataFrame(
        [
            {"timestamp_utc": ts, "trading_date": td, "node_dates": nd, "discount_factors": dfs}
            for ts, td, nd, dfs in rows
        ]
    )


def _session(anchor, trading_date, n, nodes=None, rate=0.038, start_hour=0):
    dates, dfs = _curve(anchor=anchor, nodes=nodes, rate=rate)
    base = datetime.datetime(trading_date.year, trading_date.month, trading_date.day, start_hour)
    return [(base + datetime.timedelta(minutes=i), trading_date, dates, dfs) for i in range(n)]


def test_off_modal_shape_flags_the_minority_build_when_it_moves_the_level():
    """2026-07-21: 93 minutes dropped the SR3 IMM tail and priced 30bp away."""
    td = D(2026, 7, 21)
    good = _session(ANCHOR, td, 60, rate=0.038)
    bad = _session(ANCHOR, td, 8, nodes=FOMC_NODES + BOUNDARY, rate=0.0411, start_hour=3)
    codes = frame_defects(_frame(good + bad))
    flagged = [OFF_MODAL_SHAPE in c for c in codes]
    assert sum(flagged) == 8
    assert all(flagged[60:])


def test_off_modal_shape_spares_a_minority_build_that_prices_the_same():
    """Shape alone is not a defect.

    Of 60 hourly points the shape rule removed before this condition existed,
    19 sat within 1bp of their clean neighbours -- a different instrument set
    that happened to agree. Not worth a gap in the series.
    """
    td = D(2026, 7, 16)
    good = _session(ANCHOR, td, 60, rate=0.038)
    same = _session(ANCHOR, td, 8, nodes=FOMC_NODES + BOUNDARY, rate=0.038, start_hour=3)
    codes = frame_defects(_frame(good + same))
    assert not any(OFF_MODAL_SHAPE in c for c in codes)


def test_off_modal_shape_does_not_compare_across_anchor_blocks():
    """Regression: 2026-06-24, 07-27 and 08-03 lost their whole evening block.

    Crossing a calendar day rolls one IMM or FOMC node in or out, so the evening
    and day blocks of a healthy session differ by one node. Grouping by trading
    date alone flagged 420 rows on each of those days -- all false.
    """
    td = D(2026, 7, 21)
    day = _session(ANCHOR, td, 60)
    evening = _session(
        D(2026, 7, 20), td,
        40,
        nodes=FOMC_NODES + IMM_TAIL[:-1] + [D(2028, 7, 20), D(2029, 7, 20)],
        start_hour=3,
    )
    codes = frame_defects(_frame(day + evening))
    assert not any(OFF_MODAL_SHAPE in c for c in codes)


def test_ambiguous_shape_day_is_surfaced_not_quarantined():
    """A 50/50 split means no shape is the session; dropping half is a guess."""
    td = D(2026, 7, 21)
    a = _session(ANCHOR, td, 30)
    b = _session(ANCHOR, td, 30, nodes=FOMC_NODES + BOUNDARY, start_hour=6)
    codes = frame_defects(_frame(a + b))
    assert not any(OFF_MODAL_SHAPE in c for c in codes)


def test_small_group_is_not_judged_on_shape():
    """Reads are often a sampled grid; 3 rows cannot establish a mode."""
    td = D(2026, 7, 21)
    rows = _session(ANCHOR, td, 2) + _session(ANCHOR, td, 1, nodes=FOMC_NODES + BOUNDARY, start_hour=5)
    codes = frame_defects(_frame(rows))
    assert not any(OFF_MODAL_SHAPE in c for c in codes)


def test_anchor_block_jump_flags_a_displaced_evening_block():
    """2026-07-30: 450 evening minutes sat 78bp off the rest of the session."""
    td = D(2026, 7, 30)
    main = _session(D(2026, 7, 30), td, 60, rate=0.038)
    evening = _session(D(2026, 7, 29), td, 25, rate=0.0305, start_hour=3)  # ~75bp low
    codes = frame_defects(_frame(main + evening))
    flagged = [ANCHOR_BLOCK_JUMP in c for c in codes]
    assert sum(flagged) == 25
    assert all(flagged[60:])


def test_anchor_block_jump_ignores_an_ordinary_overnight_gap():
    """Median |gap| across the 64-day sample was 1.45bp; worst clean day 8.0bp."""
    td = D(2026, 7, 21)
    main = _session(ANCHOR, td, 60, rate=0.038)
    evening = _session(D(2026, 7, 20), td, 25, rate=0.0388, start_hour=3)  # ~8bp
    codes = frame_defects(_frame(main + evening))
    assert not any(ANCHOR_BLOCK_JUMP in c for c in codes)


def test_anchor_block_jump_does_not_fire_when_the_block_is_the_session():
    """A majority block is the session; it cannot be the outlier off itself."""
    td = D(2026, 7, 30)
    small = _session(D(2026, 7, 30), td, 20, rate=0.038)
    big = _session(D(2026, 7, 29), td, 60, rate=0.030, start_hour=3)
    codes = frame_defects(_frame(small + big))
    assert sum(ANCHOR_BLOCK_JUMP in c for c in codes) == 20


# ── frame filter ──


def test_filter_returns_the_same_frame_when_nothing_trips():
    df = _frame(_session(ANCHOR, D(2026, 7, 21), 30))
    assert filter_raw_frame(df) is df


def test_filter_drops_only_the_defective_rows():
    td = D(2026, 7, 21)
    good = _session(ANCHOR, td, 60)
    dates, _ = _curve()
    dead = [(datetime.datetime(2026, 7, 21, 5, i), td, dates, [1.0] * len(dates)) for i in range(5)]
    out = filter_raw_frame(_frame(good + dead))
    assert len(out) == 60


def test_filter_is_a_no_op_on_an_empty_frame():
    empty = pd.DataFrame(columns=["timestamp_utc", "trading_date", "node_dates", "discount_factors"])
    assert filter_raw_frame(empty).empty


# ── reference rate ──


def test_reference_rate_recovers_a_flat_curve():
    """``_curve`` builds DF = exp(-r*t); the predicate reports a SIMPLE ACT/360
    rate, so the target is the simple equivalent of 4% continuous, not 4%."""
    dates, dfs = _curve(rate=0.04)
    expected = (np.exp(0.04 * 365.0 / 360.0) - 1.0) / (365.0 / 360.0) * 100.0
    assert reference_rate(dates, dfs) == pytest.approx(expected, abs=1e-6)


def test_reference_rate_is_nan_when_the_horizon_is_not_covered():
    dates, dfs = _curve(nodes=[D(2026, 7, 29)])
    assert np.isnan(reference_rate(dates, dfs))

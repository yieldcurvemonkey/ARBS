"""Known-answer tests for synthetic (broker-managed) iceberg detection.

Every sequence here is hand-built and every expected chain worked out by hand, so
a failure points at the detector rather than at the data.

The rule under test is a *timing* rule, not a structural one, and that is what the
tests are shaped around.  Native detection is exact -- one order id, one order,
one answer -- but a synthetic iceberg reaches the feed as a run of unrelated
order ids, and the only evidence tying them together is that each arrived at the
same price and size within ``dt`` of the last one being traded out.  So the tests
that matter most are the ones that pin the **arbitrary** parts: the inclusive
edge of the window, which of two candidates is taken, which of two claimants wins
a contested successor, and that the loser of that contest is flagged rather than
quietly reported as a completed iceberg.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from RVUtils.MBO.analytics.icebergs import (
    SYNTHETIC_CHAIN_COLUMNS,
    detect_synthetic,
    synthetic_summary,
)
from RVUtils.MBO.book import F_SNAPSHOT
from RVUtils.MBO.lifecycle import replay_lifecycle
from tests.test_mbo_book import L, make

S = 1_000_000_000          # one second in nanoseconds
MS = 1_000_000
DT = 300 * MS              # the paper's dt, in nanoseconds


def _tranche(add, oid, exit_ts=None, kind="FILLED", px=96.01, sz=5, side="A",
             traded=None, flags=L):
    """The MBO records one tranche produces over its life.

    ``kind`` is its fate: traded out in full, cancelled untouched, partly filled
    and then pulled, or still resting when the data ends.
    """
    opp = "B" if side == "A" else "A"
    out = [(add, "A", side, px, sz, oid, flags)]
    v = sz if traded is None else traded
    if kind == "OPEN":
        return out
    if kind == "FILLED":
        out += [(exit_ts, "T", opp, px, v, 900_000 + oid, 0),
                (exit_ts, "F", side, px, v, oid, 0),
                (exit_ts, "C", side, px, sz, oid, L)]
    elif kind == "CANCELLED":
        out += [(exit_ts, "C", side, px, sz, oid, L)]
    elif kind == "PARTIAL":
        out += [(exit_ts, "T", opp, px, v, 900_000 + oid, 0),
                (exit_ts, "F", side, px, v, oid, 0),
                (exit_ts, "C", side, px, v, oid, 0),
                (exit_ts, "C", side, px, sz - v, oid, L)]
    else:  # pragma: no cover -- a typo in a test, not a code path
        raise AssertionError(f"unknown tranche kind {kind!r}")
    return out


def _orders(specs):
    """One instrument's order table, from a list of tranche specifications."""
    rows = []
    for s in specs:
        rows += _tranche(**s)
    rows.sort(key=lambda r: r[0])          # stable: same-stamp rows keep their order
    return replay_lifecycle(make(rows)).orders


def _run(n, gap=100 * MS, hold=S, t0=0, oid0=101, **kw):
    """``n`` tranches in a row, each placed ``gap`` after the last was traded out."""
    specs = []
    t = t0
    for k in range(n):
        specs.append(dict(add=t, exit_ts=t + hold, oid=oid0 + k, **kw))
        t = t + hold + gap
    return specs


# --------------------------------------------------------------------------- #
# the rule itself
# --------------------------------------------------------------------------- #

def test_a_clean_three_tranche_chain_is_one_iceberg():
    """Three unrelated order ids, same price and size, each refilled 100 ms after
    the last was traded out: the paper's rule says one iceberg of 15."""
    o = _orders(_run(3))
    ch = detect_synthetic(o)
    assert len(ch) == 1
    row = ch.iloc[0]
    assert row["n_tranches"] == 3
    assert row["total_volume"] == 15
    assert row["size"] == 5
    assert row["side"] == "A"
    assert row["price"] == pytest.approx(96.01)
    assert bool(row["complete"])
    assert row["status"] == "COMPLETE"
    assert row["first_order_id"] == 101
    assert row["last_order_id"] == 103
    assert row["span_ns"] == 3 * S + 2 * (100 * MS)
    assert not bool(row["ambiguous"])
    assert row["n_alt_children"] == 0
    assert row["n_contested"] == 0
    assert not bool(row["ended_by_contest"])


def test_the_frame_carries_exactly_the_documented_columns():
    ch = detect_synthetic(_orders(_run(3)))
    assert tuple(ch.columns) == SYNTHETIC_CHAIN_COLUMNS


def test_a_chain_whose_last_tranche_is_cancelled_is_incomplete():
    """The paper: "if a tranche is placed and later cancelled, the whole iceberg
    is considered cancelled".  Its volume is then only a lower bound on its size,
    which is the whole reason the size distribution needs Kaplan-Meier."""
    specs = _run(3)
    specs[-1]["kind"] = "CANCELLED"
    ch = detect_synthetic(_orders(specs))
    assert len(ch) == 1
    assert ch.iloc[0]["status"] == "CANCELLED"
    assert not bool(ch.iloc[0]["complete"])
    assert ch.iloc[0]["total_volume"] == 10      # the cancelled tranche traded none


def test_a_chain_still_resting_at_the_end_is_truncated_not_complete():
    specs = _run(3)
    specs[-1]["kind"] = "OPEN"
    specs[-1].pop("exit_ts")
    ch = detect_synthetic(_orders(specs))
    assert len(ch) == 1
    assert ch.iloc[0]["status"] == "TRUNCATED"
    assert not bool(ch.iloc[0]["complete"])


def test_the_dt_window_is_inclusive_at_exactly_dt():
    """A refill arriving at exactly ``dt`` after the removal still links.  The
    boundary has to be pinned because it is arbitrary: 0.3 s was fitted to one
    2019 session on one instrument."""
    ch = detect_synthetic(_orders(_run(3, gap=DT)))
    assert len(ch) == 1
    assert ch.iloc[0]["n_tranches"] == 3


def test_one_nanosecond_past_dt_breaks_the_chain():
    specs = _run(3, gap=DT)
    # push only the third tranche one nanosecond beyond the window
    specs[2]["add"] += 1
    specs[2]["exit_ts"] += 1
    o = _orders(specs)
    assert detect_synthetic(o).empty                       # 2 tranches < min 3
    ch = detect_synthetic(o, min_tranches=2)
    assert len(ch) == 1
    assert ch.iloc[0]["n_tranches"] == 2
    assert ch.iloc[0]["last_order_id"] == 102


def test_a_different_size_is_not_the_same_iceberg():
    """"Their volumes are expected to be equal to the initial tranche volume,
    which is taken to be the iceberg display quantity"."""
    specs = _run(3)
    specs[1]["sz"] = 6
    assert detect_synthetic(_orders(specs), min_tranches=2).empty


def test_a_different_price_is_not_the_same_iceberg():
    specs = _run(3)
    specs[1]["px"] = 96.02
    assert detect_synthetic(_orders(specs), min_tranches=2).empty


def test_the_opposite_side_is_not_the_same_iceberg():
    specs = _run(3)
    specs[1]["side"] = "B"
    assert detect_synthetic(_orders(specs), min_tranches=2).empty


def test_a_partly_filled_predecessor_does_not_continue_the_chain():
    """The rule is trade *and* removal.  An order pulled after a partial fill was
    cancelled, not traded out, and under the paper's completion rule that ends the
    iceberg rather than continuing it."""
    specs = _run(3)
    specs[1]["kind"] = "PARTIAL"
    specs[1]["traded"] = 2
    o = _orders(specs)
    assert detect_synthetic(o).empty
    ch = detect_synthetic(o, min_tranches=2)
    assert len(ch) == 1
    assert ch.iloc[0]["n_tranches"] == 2
    assert ch.iloc[0]["total_volume"] == 7       # 5 traded out, then 2 of 5
    assert ch.iloc[0]["status"] == "CANCELLED"


def test_min_tranches_is_the_only_defence_against_a_coincidence():
    o = _orders(_run(2))
    assert detect_synthetic(o, min_tranches=3).empty
    assert len(detect_synthetic(o, min_tranches=2)) == 1


# --------------------------------------------------------------------------- #
# the tree: what rests on an arbitrary choice
# --------------------------------------------------------------------------- #

def test_of_two_candidates_the_earliest_arrival_wins_and_the_other_is_recorded():
    """Two orders at the same price and size land inside one window.  The paper's
    assumption is that the true refill is the faster one, so the earlier arrival
    is taken -- and the alternative it beat is counted, because a caller has to be
    able to see that the answer rested on a choice."""
    specs = _run(3)
    # a decoy arriving 50 ms after the first tranche's refill did, with a LOWER
    # order id, so a wrong tie-break on id rather than arrival would be visible
    specs.append(dict(add=specs[1]["add"] + 50 * MS, exit_ts=10 * S, oid=99,
                      kind="CANCELLED"))
    ch = detect_synthetic(_orders(specs))
    assert len(ch) == 1
    row = ch.iloc[0]
    assert row["n_tranches"] == 3
    assert row["first_order_id"] == 101 and row["last_order_id"] == 103
    assert row["n_alt_children"] == 1
    assert bool(row["ambiguous"])
    assert not bool(row["ended_by_contest"])


def test_a_contested_successor_goes_to_the_nearest_predecessor():
    """Two chains, one refill that could belong to either.  It goes to whichever
    tranche was removed latest, and -- the point of the test -- the chain that
    lost is flagged, because its last tranche WAS followed by a refill inside dt
    and only the tie-break made it look finished."""
    specs = [
        dict(add=0, exit_ts=400 * MS, oid=201),            # chain A, tranche 1
        dict(add=500 * MS, exit_ts=900 * MS, oid=202),     # chain A, tranche 2
        dict(add=S, exit_ts=2 * S, oid=203),               # chain A, tranche 3
        dict(add=1900 * MS, exit_ts=2050 * MS, oid=301),   # the rival predecessor
        dict(add=2100 * MS, exit_ts=3 * S, oid=302, kind="CANCELLED"),
    ]
    ch = detect_synthetic(_orders(specs), min_tranches=2).set_index("first_order_id")
    assert list(ch.index) == [201, 301]

    lost = ch.loc[201]
    assert lost["n_tranches"] == 3
    assert lost["last_order_id"] == 203
    assert bool(lost["ended_by_contest"])
    assert bool(lost["ambiguous"])
    # 203 was traded out and a refill DID follow within dt, so "complete" here is
    # an artefact of the tie-break -- the flag is the only thing that says so
    assert bool(lost["complete"])
    assert lost["n_alt_children"] == 1

    won = ch.loc[301]
    assert won["n_tranches"] == 2
    assert won["last_order_id"] == 302
    assert won["n_contested"] == 1
    assert not bool(won["ended_by_contest"])
    assert bool(won["ambiguous"])


def test_chains_are_disjoint_so_their_volumes_add():
    """Two independent chains at different prices: no tranche is counted twice,
    which is exactly what the paper's overlapping-paths treatment cannot promise."""
    specs = _run(3) + _run(3, t0=10 * S, oid0=201, px=96.02)
    ch = detect_synthetic(_orders(specs))
    assert len(ch) == 2
    assert list(ch["n_tranches"]) == [3, 3]
    assert ch["total_volume"].sum() == 30


def test_orders_sharing_one_nanosecond_link_in_feed_order_and_never_in_a_loop():
    """When a tranche is placed and traded out inside one packet, its refill can
    carry the same timestamp.  The successor is then decided by the feed's own
    sequence, which is a strict order, so the pair cannot claim each other.

    The order ids here run **backwards** against the sequence deliberately: a
    detector that fell back on the id would build the chain the other way round,
    and an exchange-assigned id is not a statement about who arrived first.
    """
    specs = [
        dict(add=S, exit_ts=S, oid=403),
        dict(add=S, exit_ts=S, oid=402),
        dict(add=S, exit_ts=2 * S, oid=401),
    ]
    ch = detect_synthetic(_orders(specs), min_tranches=2)
    assert len(ch) == 1
    assert ch.iloc[0]["n_tranches"] == 3
    assert ch.iloc[0]["first_order_id"] == 403
    assert ch.iloc[0]["last_order_id"] == 401


def test_the_answer_does_not_depend_on_the_order_of_the_rows():
    o = _orders(_run(4) + _run(3, t0=20 * S, oid0=201, px=96.02))
    a = detect_synthetic(o)
    b = detect_synthetic(o.sample(frac=1.0, random_state=7))
    pd.testing.assert_frame_equal(a, b)


# --------------------------------------------------------------------------- #
# exclusions that would otherwise manufacture links
# --------------------------------------------------------------------------- #

def test_a_snapshot_order_is_not_a_tranche():
    """Its entry stamp is the snapshot's, not an arrival, so a whole book of them
    would sit inside one dt window and link to anything."""
    specs = _run(3)
    specs[1]["flags"] = F_SNAPSHOT
    assert detect_synthetic(_orders(specs), min_tranches=2).empty


def test_an_order_that_moved_price_is_not_a_tranche():
    """The frame records where it ended, not where it joined, so the same-price
    test would be asked about the wrong level."""
    rows = _tranche(add=0, exit_ts=S, oid=101)
    rows += [(1100 * MS, "A", "A", 96.00, 5, 102, L),           # joins elsewhere
             (1150 * MS, "M", "A", 96.01, 5, 102, L)]           # then moves in
    rows += _tranche(add=2 * S, exit_ts=3 * S, oid=102)[1:]
    rows += _tranche(add=2100 * MS, exit_ts=4 * S, oid=103)
    rows.sort(key=lambda r: r[0])
    o = replay_lifecycle(make(rows)).orders
    assert bool((o.set_index("order_id").loc[102, "n_price_move"]) == 1)
    assert detect_synthetic(o, min_tranches=2).empty


def test_a_tranche_that_is_itself_a_native_iceberg_is_counted_not_hidden():
    """The two detectors disagreeing about one order is a fact worth seeing.  It
    also pins total_volume to what traded rather than to what was displayed."""
    specs = _run(3)
    specs[0]["traded"] = 9                     # the first tranche is one too,
    specs[1]["traded"] = 12                    # so a root-only count is visible
    ch = detect_synthetic(_orders(specs))
    assert len(ch) == 1
    assert ch.iloc[0]["n_native_tranches"] == 2
    assert ch.iloc[0]["total_volume"] == 26    # 9 + 12 + 5, not 3 * 5


# --------------------------------------------------------------------------- #
# refusals
# --------------------------------------------------------------------------- #

def test_an_empty_frame_gives_a_typed_empty_result():
    out = detect_synthetic(pd.DataFrame())
    assert out.empty
    assert tuple(out.columns) == SYNTHETIC_CHAIN_COLUMNS
    assert str(out["total_volume"].dtype) == "int64"


def test_an_empty_result_concatenates_with_a_real_one():
    """The reason the empty frame is typed at all: a caller sweeping sessions
    concatenates them, and one quiet day must not turn an int64 column into
    object and every count into a float."""
    full = detect_synthetic(_orders(_run(3)))
    empty = detect_synthetic(pd.DataFrame())
    assert list(full.dtypes.astype(str)) == list(empty.dtypes.astype(str))
    both = pd.concat([empty, full], ignore_index=True)
    assert list(both.dtypes.astype(str)) == list(full.dtypes.astype(str))


def test_no_chains_still_gives_a_typed_empty_result():
    out = detect_synthetic(_orders(_run(1, hold=S)))
    assert out.empty
    assert tuple(out.columns) == SYNTHETIC_CHAIN_COLUMNS


def test_a_missing_column_is_named_along_with_the_fix():
    """Pandas would raise a bare ``KeyError('exit_reason')`` here on its own, so
    matching the column name alone would pass whether the check exists or not.
    The error has to name where the column comes from."""
    o = _orders(_run(3)).drop(columns=["exit_reason"])
    with pytest.raises(KeyError, match="exit_reason.*replay_lifecycle"):
        detect_synthetic(o)


def test_two_instruments_in_one_frame_raise():
    o = _orders(_run(3))
    o["symbol"] = ["ZNU6", "ZNU6", "ZFU6"]
    with pytest.raises(ValueError, match="symbol"):
        detect_synthetic(o)


@pytest.mark.parametrize("dt_s", [0.0, -0.3, float("nan")])
def test_a_non_positive_window_raises(dt_s):
    with pytest.raises(ValueError, match="dt_s"):
        detect_synthetic(_orders(_run(3)), dt_s=dt_s)


def test_a_chain_of_one_is_not_a_chain():
    with pytest.raises(ValueError, match="min_tranches"):
        detect_synthetic(_orders(_run(3)), min_tranches=1)


def test_a_null_timestamp_raises_rather_than_windowing_from_the_epoch():
    o = _orders(_run(3))
    o.loc[1, "exit_ts"] = pd.NaT
    with pytest.raises(ValueError, match="exit_ts"):
        detect_synthetic(o)


def test_an_exit_before_an_entry_raises():
    o = _orders(_run(3))
    o.loc[1, "exit_ts"] = o.loc[1, "entry_ts"] - pd.Timedelta("1s")
    with pytest.raises(ValueError, match="exit before"):
        detect_synthetic(o)


# --------------------------------------------------------------------------- #
# the summary
# --------------------------------------------------------------------------- #

def _chains(rows):
    base = dict(first_ts=pd.Timestamp("2026-07-15", tz="UTC"),
                last_ts=pd.Timestamp("2026-07-15 00:00:03", tz="UTC"),
                side="A", price=96.01, size=5, n_tranches=3, total_volume=15,
                complete=True, status="COMPLETE", span_ns=3 * S,
                n_alt_children=0, n_contested=0, ended_by_contest=False,
                ambiguous=False, n_native_tranches=0,
                first_order_id=101, last_order_id=103)
    return pd.DataFrame([{**base, **r} for r in rows])


def test_the_summary_divides_by_traded_volume_not_posted_volume():
    """The paper's denominator: "we divide the total volume of all iceberg orders
    by the total traded volume of all orders... and not the total daily limit
    order volume"."""
    chains = _chains([
        {"total_volume": 15},
        {"total_volume": 5, "n_tranches": 2, "status": "CANCELLED",
         "complete": False},
        {"total_volume": 4, "n_tranches": 2, "status": "CANCELLED",
         "complete": False},
    ])
    # six orders traded 100 lots between them; the chains account for 24 of it
    orders = pd.DataFrame({"filled_size": [5, 5, 5, 3, 2, 80],
                           "size_initial": [5, 5, 5, 5, 5, 500]})
    s = synthetic_summary(chains, orders)
    assert s["n_chains"] == 3
    assert s["n_tranches"] == 7
    assert s["synthetic_volume"] == 24
    assert s["traded_volume"] == 100
    assert s["volume_share"] == pytest.approx(0.24)
    assert s["n_complete"] == 1 and s["n_cancelled"] == 2
    assert s["complete_share"] == pytest.approx(1 / 3)
    # median, not mean: 5 rather than 8
    assert s["median_volume"] == pytest.approx(5.0)
    assert s["mean_tranches"] == pytest.approx(7 / 3)
    assert s["max_tranches"] == 3
    assert s["tranche_share"] == pytest.approx(7 / 6)


def test_the_summary_says_how_much_rests_on_an_arbitrary_choice():
    chains = _chains([
        {"total_volume": 10},
        {"total_volume": 30, "ambiguous": True, "ended_by_contest": True},
    ])
    orders = pd.DataFrame({"filled_size": [40]})
    s = synthetic_summary(chains, orders)
    assert s["n_ambiguous"] == 1
    assert s["ambiguous_share"] == pytest.approx(0.5)
    # three quarters of the headline volume rests on a tie-break, which the count
    # of chains alone would not have told you
    assert s["ambiguous_volume_share"] == pytest.approx(0.75)
    assert s["n_ended_by_contest"] == 1


def test_a_summary_of_no_chains_is_typed_not_an_error():
    s = synthetic_summary(detect_synthetic(pd.DataFrame()),
                          pd.DataFrame({"filled_size": [10, 20]}))
    assert s["n_chains"] == 0
    assert s["traded_volume"] == 30
    assert np.isnan(s["volume_share"])


def test_the_summary_refuses_a_frame_that_is_not_a_chain_frame():
    with pytest.raises(KeyError, match="ended_by_contest"):
        synthetic_summary(pd.DataFrame({"total_volume": [1]}),
                          pd.DataFrame({"filled_size": [1]}))


def test_the_summary_refuses_orders_with_no_traded_volume_column():
    with pytest.raises(KeyError, match="filled_size"):
        synthetic_summary(detect_synthetic(pd.DataFrame()), pd.DataFrame({"x": [1]}))


def test_end_to_end_on_a_replayed_book():
    """Two icebergs and one ordinary order, straight off the replay kernel."""
    specs = _run(4) + _run(3, t0=30 * S, oid0=201, px=96.02) + [
        dict(add=50 * S, exit_ts=51 * S, oid=301, px=96.03, sz=40),
    ]
    o = _orders(specs)
    ch = detect_synthetic(o)
    s = synthetic_summary(ch, o)
    assert s["n_chains"] == 2
    assert s["n_tranches"] == 7
    assert s["synthetic_volume"] == 35
    assert s["traded_volume"] == 35 + 40
    assert s["volume_share"] == pytest.approx(35 / 75)
    assert s["n_orders"] == 8

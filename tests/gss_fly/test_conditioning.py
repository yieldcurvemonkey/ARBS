"""The conditioning metrics, and the planted nulls that police the whole study.

Two kinds of test here.

**Algebra**, on inputs whose answer is known by construction — the cost-multiplier closed form and
the trade-set Jaccard.

**Planted nulls.** ``fallback_repo_pct``, ``backtest.entry_abs_z`` and
``universe.recent_issue_days`` are declared in the config and read by nothing. They are the
control rods of the parameter sweep: sweeping them must move *nothing*, so if the sweep ever
reports them mattering, the harness is broken and every other number in the table is suspect.
Pinning them here turns that from a claim in a docstring into something enforced — and it catches
the opposite failure too, where someone later wires one of them up and silently invalidates the
control.
"""

from __future__ import annotations

import pathlib
import re

import numpy as np
import pandas as pd
import pytest

from BT.gss_fly.conditioning import (breakeven_cost_multiplier, equity_at_cost_multiplier,
                                     trade_key_set, trade_set_jaccard)

_ROOT = pathlib.Path(__file__).resolve().parents[2]


# ------------------------------------------------------------------ planted nulls
@pytest.mark.parametrize("knob", ["fallback_repo_pct", "entry_abs_z", "recent_issue_days"])
def test_the_planted_null_knobs_have_no_reader(knob):
    """Each must appear exactly once in the tree: its own declaration in config.py.

    These are the sweep's control rods. A reader appearing later would make the control silently
    meaningless, which is worse than not having it — the sweep would still print "zero variation"
    for a knob that now does something.
    """
    hits = []
    for path in _ROOT.rglob("*.py"):
        parts = set(path.parts)
        if parts & {"__pycache__", "tests", "scratchpad", ".git"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if re.search(rf"\b{re.escape(knob)}\b", line):
                hits.append(f"{path.relative_to(_ROOT)}:{i}")

    # conditioning.py and gss_grid.py mention them BY NAME as nulls; that is documentation
    real = [h for h in hits if not h.startswith(("BT/gss_fly/conditioning.py",
                                                 "BT\\gss_fly\\conditioning.py",
                                                 "scripts/gss_grid.py", "scripts\\gss_grid.py"))]
    assert len(real) == 1, f"{knob} should have exactly one site (its declaration); found {real}"
    assert "config.py" in real[0], real


# ------------------------------------------------------------- cost-multiplier algebra
def _equity_and_closed():
    """A book that pays 100 of fees on day 3 and 300 on day 6, ending at +500."""
    idx = pd.date_range("2025-01-01", periods=8, freq="D")
    # equity already NET of those fees
    eq = pd.Series([0, 50, 100, 50, 200, 300, 200, 500], index=idx, dtype=float)
    closed = pd.DataFrame({"closed_at": [idx[3], idx[6]],
                           "fee_allocated": [100.0, 300.0],
                           "realized_pnl": [0.0, 0.0]})
    return eq, closed


def test_cost_multiplier_of_one_is_the_identity():
    eq, closed = _equity_and_closed()
    got = equity_at_cost_multiplier(eq, closed, 1.0)
    pd.testing.assert_series_equal(got, eq, check_names=False)


def test_zero_cost_adds_back_every_fee():
    """m=0 is the gross curve: terminal equity rises by the total fee, and only after each date."""
    eq, closed = _equity_and_closed()
    got = equity_at_cost_multiplier(eq, closed, 0.0)
    assert got.iloc[-1] == pytest.approx(500 + 400)
    assert got.iloc[0] == pytest.approx(0.0)        # before any fee was paid
    assert got.iloc[2] == pytest.approx(100.0)      # still before the first unwind
    assert got.iloc[3] == pytest.approx(50 + 100)   # the day the first fee was charged


def test_halving_the_cost_returns_half_the_fee():
    eq, closed = _equity_and_closed()
    assert equity_at_cost_multiplier(eq, closed, 0.5).iloc[-1] == pytest.approx(500 + 200)


def test_breakeven_multiplier_is_gross_over_fees():
    """m* = 900/400 = 2.25: this book could pay 2.25x its charged cost and still break even."""
    eq, closed = _equity_and_closed()
    assert breakeven_cost_multiplier(eq, closed) == pytest.approx(900.0 / 400.0)


def test_breakeven_below_one_means_the_book_cannot_pay_its_own_costs():
    """The GSS case: gross 1,383,123 against fees 5,637,475 gives m* = 0.245."""
    idx = pd.date_range("2025-01-01", periods=4, freq="D")
    eq = pd.Series([0.0, 0.0, 0.0, 1_383_123.0 - 5_637_475.0], index=idx)
    closed = pd.DataFrame({"closed_at": [idx[3]], "fee_allocated": [5_637_475.0]})
    m = breakeven_cost_multiplier(eq, closed)
    assert m == pytest.approx(1_383_123.0 / 5_637_475.0, rel=1e-9)
    assert m < 1.0, "m* < 1 means no cost assumption inside the charged table saves it"


def test_an_open_position_is_charged_or_the_breakeven_is_biased_up():
    """`GSSExitAction` is the only fee hook, so a position that never unwound never paid."""
    eq, closed = _equity_and_closed()
    without = breakeven_cost_multiplier(eq, closed)
    with_open = breakeven_cost_multiplier(eq, closed, open_fee_usd=200.0)
    assert with_open < without


# --------------------------------------------------------------------- trade-set Jaccard
def _log(dates, flies):
    return pd.DataFrame({"date": pd.to_datetime(dates), "event": ["ENTER"] * len(flies),
                         "fly_id": flies})


def test_identical_trade_sets_have_jaccard_one():
    a = _log(["2025-01-02", "2025-02-03"], ["x/y/z", "p/q/r"])
    assert trade_set_jaccard(a, a.copy()) == pytest.approx(1.0)


def test_disjoint_trade_sets_have_jaccard_zero():
    a = _log(["2025-01-02"], ["x/y/z"])
    b = _log(["2025-06-02"], ["p/q/r"])
    assert trade_set_jaccard(a, b) == pytest.approx(0.0)


def test_half_overlap_is_a_third():
    """|A∩B| = 1, |A∪B| = 3."""
    a = _log(["2025-01-02", "2025-02-03"], ["x/y/z", "p/q/r"])
    b = _log(["2025-01-02", "2025-03-04"], ["x/y/z", "m/n/o"])
    assert trade_set_jaccard(a, b) == pytest.approx(1 / 3)


def test_date_tolerance_matches_the_same_fly_a_few_days_apart():
    """Separates "the knob moved the TIMING" from "the knob moved the SET" — different findings."""
    a = _log(["2025-01-02"], ["x/y/z"])
    b = _log(["2025-01-05"], ["x/y/z"])
    assert trade_set_jaccard(a, b, tolerance_days=0) == pytest.approx(0.0)
    assert trade_set_jaccard(a, b, tolerance_days=3) > 0.9


def test_trade_key_set_ignores_exits():
    a = pd.DataFrame({"date": pd.to_datetime(["2025-01-02", "2025-01-09"]),
                      "event": ["ENTER", "EXIT"], "fly_id": ["x/y/z", "x/y/z"]})
    assert len(trade_key_set(a)) == 1


def test_tolerance_is_matching_not_bucketing():
    """The bug the tolerance test caught: bucketing made the answer depend on the epoch offset.

    Under `epoch_days // tolerance`, a 3-day gap straddling a boundary scores 0 while a 2-day gap
    inside one bucket scores 1. Sweep every start date across a fortnight: with real matching,
    ANY pair within the tolerance must match, wherever it sits.
    """
    for offset in range(14):
        base = pd.Timestamp("2025-01-01") + pd.Timedelta(days=offset)
        a = _log([base], ["x/y/z"])
        b = _log([base + pd.Timedelta(days=3)], ["x/y/z"])
        assert trade_set_jaccard(a, b, tolerance_days=3) == pytest.approx(1.0), offset
        c = _log([base + pd.Timedelta(days=4)], ["x/y/z"])
        assert trade_set_jaccard(a, c, tolerance_days=3) == pytest.approx(0.0), offset


def test_tolerant_matching_is_one_to_one():
    """Two entries of the same fly in A must not both claim the single entry in B."""
    a = _log(["2025-01-02", "2025-01-03"], ["x/y/z", "x/y/z"])
    b = _log(["2025-01-02"], ["x/y/z"])
    # 1 match out of |A|+|B|-1 = 2
    assert trade_set_jaccard(a, b, tolerance_days=3) == pytest.approx(1 / 2)


def test_tolerance_never_matches_across_different_flies():
    a = _log(["2025-01-02"], ["x/y/z"])
    b = _log(["2025-01-02"], ["p/q/r"])
    assert trade_set_jaccard(a, b, tolerance_days=30) == pytest.approx(0.0)

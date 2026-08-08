"""Planted-value tests for the H13 conditional-book arithmetic (_book).

Every expectation is hand-computed from the fee/episode rules, never from the
implementation's output.
"""
import importlib.util
import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

_REPO = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "sv_citivelo_h13", _REPO / "scripts" / "sv_citivelo_h13.py")
h13 = importlib.util.module_from_spec(spec)
sys.modules["sv_citivelo_h13"] = h13
spec.loader.exec_module(h13)

PKG = h13.PKG_DV01  # 100_000


def _unit(n=10, carry=1.0):
    idx = pd.bdate_range("2024-01-01", periods=n)
    return pd.DataFrame({
        "carry": carry, "harvest": 0.0, "mtm": 0.0, "cross": 0.0,
        "hedge_dv01_usd": 0.0, "n_hedges": 0,
        "long_notional": 1.0, "dv01_long_unit": PKG, "position_age_years": 0.0,
    }, index=idx)


def test_two_episode_hand_arithmetic():
    unit = _unit()
    s = pd.Series([0, 0, 1, 1, 1, 0, 0, 1, 1, 0], index=unit.index, dtype=float)
    r = h13._book(unit, s, set(), initiate_bp=1.0, hedge_bp=0.3, roll_bp=0.3,
                  mult=1.0, roll_kind="roll")
    st = r["stats"]
    assert st["n_trades"] == 2
    assert st["n_days_held"] == 5
    assert st["occupancy"] == pytest.approx(0.5)
    # fees: 2 opens + 2 closes at 1.0bp x $100k = $100,000 each
    # ep1: gross 3.0 carry - 100k (open, in-window) - 100k (close, day after) = -199,997
    # ep2: gross 2.0 carry - 100k - 100k = -199,998
    tr = r["trades"]
    assert tr.iloc[0]["gross_bp"] == pytest.approx(3.0 / PKG)
    assert tr.iloc[0]["net_bp"] == pytest.approx(-199_997.0 / PKG)
    assert tr.iloc[1]["net_bp"] == pytest.approx(-199_998.0 / PKG)
    assert st["net_bp_total"] == pytest.approx((-199_997.0 - 199_998.0) / PKG)


def test_free_costs_leave_gross():
    unit = _unit()
    s = pd.Series([0, 1, 1, 1, 0, 0, 0, 0, 0, 0], index=unit.index, dtype=float)
    r = h13._book(unit, s, set(), initiate_bp=1.0, hedge_bp=0.3, roll_bp=0.3,
                  mult=0.0, roll_kind="roll")
    assert r["stats"]["net_bp_total"] == pytest.approx(3.0 / PKG)
    assert r["stats"]["gross_bp_total"] == pytest.approx(3.0 / PKG)


def test_boundary_roll_charged_only_when_held():
    unit = _unit()
    b = {unit.index[4]}
    s_on = pd.Series(1.0, index=unit.index)
    r_on = h13._book(unit, s_on, b, initiate_bp=1.0, hedge_bp=0.3, roll_bp=0.3,
                     mult=1.0, roll_kind="roll")
    # always-on: 1 open (day0), SYNTHETIC terminal exit at sample end (an
    # unexited final episode must not get a free leg), 1 roll at 0.3bp = $30k
    # gross 10 days x 1.0 = 10; net = 10 - 100_000 - 100_000 - 30_000
    assert r_on["stats"]["net_bp_total"] == pytest.approx((10.0 - 230_000.0) / PKG)
    s_off = pd.Series([1, 1, 1, 1, 0, 0, 0, 0, 0, 0], index=unit.index, dtype=float)
    r_off = h13._book(unit, s_off, b, initiate_bp=1.0, hedge_bp=0.3, roll_bp=0.3,
                      mult=1.0, roll_kind="roll")
    # state off at the boundary -> NO roll fee: 4 carry - open 100k - close 100k
    assert r_off["stats"]["net_bp_total"] == pytest.approx((4.0 - 200_000.0) / PKG)


def test_hedge_fee_scales_with_state():
    unit = _unit()
    unit.loc[unit.index[3], "hedge_dv01_usd"] = 50_000.0
    s = pd.Series([0, 0, 1, 1, 1, 0, 0, 0, 0, 0], index=unit.index, dtype=float)
    r = h13._book(unit, s, set(), initiate_bp=1.0, hedge_bp=0.4, roll_bp=0.4,
                  mult=1.0, roll_kind="roll")
    # hedge fee = 0.4bp x 50k = $20,000 inside the episode
    expected = (3.0 - 100_000.0 - 100_000.0 - 20_000.0) / PKG
    assert r["stats"]["net_bp_total"] == pytest.approx(expected)


def test_mutation_unlagged_state_changes_answer():
    """The engine must be fed a LAGGED state; feeding the unlagged one on a
    state that flips just before a P&L day changes the answer — proving the
    lag matters and the test harness can see it."""
    unit = _unit()
    unit.loc[unit.index[2], "mtm"] = 500.0  # P&L lands on day 2
    raw = pd.Series([0, 0, 1, 0, 0, 0, 0, 0, 0, 0], index=unit.index, dtype=float)
    lagged = raw.shift(1).fillna(0.0)
    r_raw = h13._book(unit, raw, set(), initiate_bp=0.0, hedge_bp=0.0,
                      roll_bp=0.0, mult=0.0, roll_kind="roll")
    r_lag = h13._book(unit, lagged, set(), initiate_bp=0.0, hedge_bp=0.0,
                      roll_bp=0.0, mult=0.0, roll_kind="roll")
    assert r_raw["stats"]["gross_bp_total"] != pytest.approx(
        r_lag["stats"]["gross_bp_total"])

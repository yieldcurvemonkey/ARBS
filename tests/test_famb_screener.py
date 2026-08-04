"""Synthetic, no-network tests for the family B screener.

The load-bearing one is `test_prereg_gate_matches_the_backtest`: a screener that
quietly gates differently from the backtest it cites is a different strategy
wearing the same provenance, so the pre-registered cell's entry rule is bound
directly to `famb_common.intra_quarter_backtest` on a planted richness path.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

BT = Path(__file__).resolve().parents[1] / "notebooks" / "backtests"
if str(BT) not in sys.path:
    sys.path.insert(0, str(BT))

import famb_common as fc                                     # noqa: E402
import famb_screener as scr                                  # noqa: E402


# ---------------------------------------------------------------------------
# the gate, bound to the backtest
# ---------------------------------------------------------------------------

def _holding(rich_path, mark_path=None, start="2026-01-05"):
    idx = pd.DatetimeIndex(pd.bdate_range(start, periods=len(rich_path)))
    rich = pd.Series(list(rich_path), index=idx, dtype=float)
    marks = (pd.Series(list(mark_path), index=idx, dtype=float)
             if mark_path is not None else pd.Series(10.0, index=idx))
    return fc.Holding(symbol="SFRZ26", start=idx[0], end=idx[-1],
                      legs=fc.structure_legs("STRG75", 96.25),
                      marks=marks, fair=marks - rich, terminal_bp=None)


@pytest.mark.parametrize("thr", [2.0, 4.0, 6.0])
def test_prereg_gate_matches_the_backtest(thr):
    """The screener must fire on exactly the sessions the backtest enters on."""
    path = [0.0, 1.0, 3.0, 4.5, 5.0, 2.0, 0.5, -4.2, -5.0, -1.0, 0.0, 6.0,
            6.5, 1.0, 0.2, 0.0, 0.0, 0.0]
    h = _holding(path)
    trades = fc.intra_quarter_backtest([h], thr_bp=thr, exit_frac=0.25,
                                       max_hold=15, n_legs=2)
    rich = (h.marks - h.fair).dropna()
    # the backtest observes at i and enters at i+1 (lag-1)
    entered_from = {rich.index[rich.index.get_loc(t["entry"]) - 1]
                    for t in trades}
    screener_on = {ts for ts, r in rich.items()
                   if scr.gate_state(float(r), float(r), 9.9, thr,
                                     prereg=True) == "ACTIONABLE"}
    # every session the backtest acted on was flagged by the screener
    assert entered_from <= screener_on
    # and the screener flags nothing the rule would not have taken
    assert all(abs(float(rich[ts])) >= thr for ts in screener_on)


def test_prereg_side_matches_the_backtest():
    path = [0.0, 5.0, 1.0, 0.0, -5.0, -1.0, 0.0, 0.0]
    h = _holding(path)
    trades = fc.intra_quarter_backtest([h], thr_bp=4.0, exit_frac=0.25,
                                       max_hold=15, n_legs=2)
    rich = (h.marks - h.fair).dropna()
    assert trades
    for t in trades:
        i = rich.index.get_loc(t["entry"]) - 1
        assert scr.gate_side(float(rich.iloc[i]), "fade") == int(t["side"])


def test_momentum_flips_the_side():
    assert scr.gate_side(3.0, "fade") == -1
    assert scr.gate_side(3.0, "momentum") == +1
    assert scr.gate_side(-3.0, "fade") == +1


# ---------------------------------------------------------------------------
# the exploratory gate: the standing-level correction
# ---------------------------------------------------------------------------

def test_standing_level_cannot_trigger_an_exploratory_cell():
    """A back-contract sitting AT its normal richness is not a signal.

    Rank-3 richness runs +19bp in the findings purely because the off-lattice
    premium grows with dte. A raw threshold would call that a screaming sell on
    every single day, which is the passive tail-short the referee killed.
    """
    assert scr.gate_state(rich=22.0, dev=0.0, z=0.0, thr=4.0,
                          prereg=False) == "WATCH"
    # ...while the same raw number on the pre-registered cell IS its rule
    assert scr.gate_state(rich=22.0, dev=0.0, z=0.0, thr=4.0,
                          prereg=True) == "ACTIONABLE"


def test_exploratory_needs_both_bp_and_sigma():
    assert scr.gate_state(20.0, 5.0, 2.0, 4.0, prereg=False) == "ACTIONABLE"
    assert scr.gate_state(20.0, 3.0, 2.0, 4.0, prereg=False) == "WATCH"   # bp
    assert scr.gate_state(20.0, 5.0, 0.4, 4.0, prereg=False) == "WATCH"   # sigma
    assert scr.gate_state(np.nan, 5.0, 2.0, 4.0, prereg=False) == "NO-DATA"
    assert scr.gate_state(5.0, np.nan, 2.0, 4.0, prereg=False) == "NO-DATA"


# ---------------------------------------------------------------------------
# instrument mechanics
# ---------------------------------------------------------------------------

def test_option_label_matches_the_vendor_convention():
    assert scr.option_label("SFRU26", 96.00, "C") == "SFRU26|9600C"
    assert scr.option_label("SFRZ26", 95.6250, "P") == "SFRZ26|9562P"


def test_short_fly_loss_is_capped_and_short_strangle_is_not():
    legs = fc.structure_legs("FLY25", 96.25)
    assert scr.short_max_loss_bp("FLY25", legs, mark_bp=9.0) == pytest.approx(16.0)
    strg = fc.structure_legs("STRG75", 96.25)
    assert scr.short_max_loss_bp("STRG75", strg, mark_bp=9.0) == np.inf


def test_ticket_signs_every_leg_from_the_trade_side():
    idea = _idea(book="FLY25", side=-1, center=96.25)
    t = idea.ticket(100)
    by = {(r["strike_price"], r["right"]): r for r in t}
    # short a 1/-2/1 fly = sell the wings, buy the body
    assert by[(96.00, "C")]["side"] == "SELL" and by[(96.00, "C")]["lots"] == 100
    assert by[(96.25, "C")]["side"] == "BUY" and by[(96.25, "C")]["lots"] == 200
    assert by[(96.50, "C")]["side"] == "SELL"
    # ...and long flips every one of them
    long_t = {(r["strike_price"], r["right"]): r
              for r in _idea(book="FLY25", side=1, center=96.25).ticket(100)}
    assert long_t[(96.00, "C")]["side"] == "BUY"
    assert long_t[(96.25, "C")]["side"] == "SELL"


# ---------------------------------------------------------------------------
# ranking and reporting
# ---------------------------------------------------------------------------

def _idea(book="STRG75", rank=1, side=-1, state="ACTIONABLE", net=1.0,
          prereg=False, center=96.25, rich=5.0, dev=5.0, z=2.0):
    return scr.Idea(
        book=book, rank=rank, symbol="SFRZ26", dte=100, center_px=center,
        legs=fc.structure_legs(book, center), mark_bp=10.0, fair_bp=5.0,
        rich_bp=rich, level_bp=rich - dev, dev_bp=dev, z_dev=z, thr_bp=4.0,
        side=side, state=state, n_contracts=fc.n_contracts(book),
        defined_risk=scr.DEFINED_RISK[book], max_loss_bp=10.0, cost_bp=0.5,
        gross_target_bp=net + 0.5, net_target_bp=net, edge_mult=3.0,
        exit_rich_bp=1.0, max_hold_date="2026-02-01", pct_holding=0.9,
        pct_pooled=0.9, z_pooled=z, n_hist=100, half_life_hint=12.0,
        prereg=prereg, stale_ladder=False)


def test_prereg_outranks_a_better_looking_exploratory_hit():
    """The discriminating case: the mandated cell is itself undefined-risk.

    Pitting a defined-risk exploratory hit with nine times the expected bp
    against the pre-registered strangle is the only arrangement that separates
    "mandate first" from "defined risk first" — the two rules agree on
    everything else.
    """
    ideas = scr.rank_ideas([
        _idea(book="FLY25", net=9.0, prereg=False),       # defined, bigger
        _idea(book="STRG75", net=0.6, prereg=True),       # undefined, mandated
    ])
    assert ideas[0].prereg, "the mandate must not be displaced by today's tape"
    assert not ideas[0].defined_risk


def test_defined_risk_outranks_undefined_among_exploratory_hits():
    ideas = scr.rank_ideas([
        _idea(book="STRG50", net=9.0, prereg=False),      # unbounded
        _idea(book="FLY25", net=2.0, prereg=False),       # capped
    ])
    assert ideas[0].book == "FLY25"


def test_actionable_outranks_watch_regardless_of_size():
    ideas = scr.rank_ideas([
        _idea(state="WATCH", net=50.0),
        _idea(state="ACTIONABLE", net=0.1),
    ])
    assert ideas[0].state == "ACTIONABLE"


def test_gate_note_names_the_gate_that_failed():
    bp_short = _idea(state="WATCH", prereg=False, dev=1.0, z=3.0)
    assert "more dev" in bp_short.gate_note
    z_short = _idea(state="WATCH", prereg=False, dev=9.0, z=0.3)
    assert "z" in z_short.gate_note and "short of" in z_short.gate_note
    assert _idea(state="ACTIONABLE").gate_note == ""


def test_report_shouts_when_nothing_could_be_priced():
    """The failure this screener shipped with once: silence read as a decision."""
    ctx = scr.Context(
        as_of=pd.Timestamp("2026-08-04"),
        dates=pd.DatetimeIndex(pd.bdate_range("2026-01-05", periods=60)),
        surface=pd.Series(dtype=float), fwd_idx=pd.Series(dtype=float),
        tree=None, quote_dates=pd.DatetimeIndex([]), live=True, fetched=True,
        settle_asof={})
    txt = scr.format_report(ctx, [_idea(state="NO-DATA")], None)
    assert "NO DATA" in txt and "NOT A 'NO TRADE'" in txt
    assert "NO TRADE. No cell" not in txt


def test_report_lists_cells_it_could_not_screen():
    """A cell that went dark must be visible as dark, not simply absent.

    On 2022-06-15 the thin chain leaves the PRE-REGISTERED strangle unmarked.
    Dropping it from the table would read as "quiet today" when the truth is
    the strategy was blind on the day it was most exposed.
    """
    ctx = scr.Context(
        as_of=pd.Timestamp("2022-06-15"),
        dates=pd.DatetimeIndex(pd.bdate_range("2022-01-05", periods=60)),
        surface=pd.Series(dtype=float), fwd_idx=pd.Series(dtype=float),
        tree=None, quote_dates=pd.DatetimeIndex([]), live=False, fetched=False,
        settle_asof={})
    dark = scr._blank_idea("STRG75", 1, "SFRU22", 4.0, "NO-DATA",
                           "no mark on 2022-06-15")
    txt = scr.format_report(ctx, [_idea(book="FLY25", state="WATCH"), dark],
                            None)
    assert "NOT SCREENED" in txt
    assert "STRG75 Q1 SFRU22" in txt and "no mark on 2022-06-15" in txt
    # ...and it must not be counted as a tradeable cell
    assert "NO TRADE" in txt


def test_screen_emits_a_row_for_a_cell_it_could_not_build(monkeypatch):
    """`screen` must MAKE the placeholder, not just render one it was handed."""
    monkeypatch.setattr(scr, "score_cell", lambda *a, **k: None)
    ctx = scr.Context(
        as_of=pd.Timestamp("2022-06-15"),
        dates=pd.DatetimeIndex(pd.bdate_range("2022-01-05", periods=60)),
        surface=pd.Series(dtype=float), fwd_idx=pd.Series(dtype=float),
        tree=None, quote_dates=pd.DatetimeIndex([]), live=False, fetched=False,
        settle_asof={})
    ideas = scr.screen(ctx, books=("STRG75",), ranks=(1,))
    assert len(ideas) == 1
    assert ideas[0].state == "NO-BOOK" and ideas[0].book == "STRG75"
    assert ideas[0].note


def test_blank_cells_sort_last_and_never_get_recommended():
    ideas = scr.rank_ideas([
        scr._blank_idea("STRG75", 1, "SFRU22", 4.0, "NO-BOOK", "x"),
        _idea(book="FLY25", state="WATCH", net=0.1),
    ])
    assert ideas[-1].state == "NO-BOOK"


def test_report_labels_an_exploratory_recommendation_as_unmandated():
    ctx = scr.Context(
        as_of=pd.Timestamp("2026-08-04"),
        dates=pd.DatetimeIndex(pd.bdate_range("2026-01-05", periods=60)),
        surface=pd.Series(dtype=float), fwd_idx=pd.Series(dtype=float),
        tree=None, quote_dates=pd.DatetimeIndex([]), live=False, fetched=False,
        settle_asof={})
    txt = scr.format_report(ctx, [_idea(prereg=False, state="ACTIONABLE")],
                            None)
    assert "EXPLORATORY" in txt
    assert "pre-registered cell is NOT triggered" in txt
    assert "SELECTION-ARTIFACT" in txt          # provenance always present


def test_report_warns_on_an_unbounded_short():
    ctx = scr.Context(
        as_of=pd.Timestamp("2026-08-04"),
        dates=pd.DatetimeIndex(pd.bdate_range("2026-01-05", periods=60)),
        surface=pd.Series(dtype=float), fwd_idx=pd.Series(dtype=float),
        tree=None, quote_dates=pd.DatetimeIndex([]), live=False, fetched=False,
        settle_asof={})
    txt = scr.format_report(ctx, [_idea(book="STRG75", side=-1, prereg=True,
                                        state="ACTIONABLE")], None)
    assert "UNBOUNDED" in txt
    txt2 = scr.format_report(ctx, [_idea(book="FLY25", side=-1, prereg=True,
                                         state="ACTIONABLE")], None)
    assert "defined" in txt2 and "UNBOUNDED" not in txt2


def test_expected_gross_is_the_convergence_arithmetic():
    """Target gross = (1 - exit_frac) x |signal|, which is what the exit rule
    delivers when the fair value does not move."""
    rich, exit_frac = 6.0, 0.25
    assert (1 - exit_frac) * abs(rich) == pytest.approx(4.5)
    h = _holding([rich, rich, rich * exit_frac, 0.0, 0.0, 0.0],
                 mark_path=[10.0, 10.0, 10.0 - (1 - exit_frac) * rich,
                            0.0, 0.0, 0.0])
    tr = fc.intra_quarter_backtest([h], thr_bp=4.0, exit_frac=exit_frac,
                                   max_hold=15, n_legs=2, cost_mult=0.0)
    assert tr and tr[0]["gross_bp"] == pytest.approx(4.5)

"""Known-answer tests for the long-end LISTED backtest composition.

The study runs ONE engine pass per structure (an always-on flattener) and
composes every gate mode's daily equity from it. That composition is the only
new arithmetic in the study, and everything downstream -- four equity curves,
their Sharpes, the cost sensitivity -- is wrong in a way nobody would notice if
it is wrong. So it is tested here against answers computed on paper.

Three tiers, so the fast gate stays fast:

* **Synthetic** (no I/O). A three-cohort "engine run" whose marks, gross P&L and
  fees are hand-chosen, so every composed number is known before the code runs.
* **Identities** (no I/O). Replaying the unit direction must reproduce the unit
  run; flipping the gate must negate the gross and NOT the cost; standing aside
  must be free; the lag must be applied exactly once.
* **Data-backed** (``slow``, skipped when the parquet is absent). The composed
  cohort book must equal ``strat1_threeway.apply_gate``'s -- separately tested
  code reached by a different expression -- and the composed ``always`` book
  must reproduce the engine's own ``mtm_history``.

**Verifying the checker itself.** A test that passes against mutated code does
not test anything, so eight plausible wrong implementations were planted in
``strat1_longend_listed.py`` and the suite re-run against each. Measured log:

==================================================  ========  ====================
mutation                                            result    caught by
==================================================  ========  ====================
fee term uses ``g`` instead of ``abs(g)``           CAUGHT    steepener_pays_cost
drop the lag in ``compose_gate_equity``             CAUGHT    lag_applied_exactly_once
charge the fee on untraded cohorts                  CAUGHT    standing_aside_is_free
charge the one-way cost once, not the round trip    CAUGHT    known_answer_composition
drop the ``closed`` step, fee charged every day     CAUGHT    decomposition_reproduces_equity
``breakeven_cost_bp`` divides by n, not 2n          CAUGHT    breakeven_cost_is_exact
``e_max_sharpe_null`` compared with ``<``           CAUGHT    scoreboard_bar_direction
``cohort_contributions`` skips the identity check   CAUGHT    decomposition_check_bites
==================================================  ========  ====================

All eight were caught. The mutation runs are in the session log, not committed.
"""

from __future__ import annotations

import math
import pathlib

import numpy as np
import pandas as pd
import pytest

from RVUtils.ConvexityRV import strat1_curve_gamma as s1
from RVUtils.ConvexityRV import strat1_longend_listed as ll
from RVUtils.ConvexityRV import strat1_threeway as tw

DATA = pathlib.Path(__file__).resolve().parents[1] / "notebooks" / "data" / "convexity_rv"
DV01 = 100_000.0
COST = 0.5                       # bp one way -> 1.0 bp round trip
FEE = 2.0 * COST * DV01          # $100,000 per closed cohort


# ---------------------------------------------------------------- the fixture


def _synthetic_unit_run():
    """A hand-built stand-in for one engine pass, obeying the engine's semantics.

    Ten business days. Three cohorts, all opened as flatteners (this is a UNIT
    run), with entries lagged one day off the signal grid exactly as
    ``build_backtest`` does:

    =======  =========  ========  ==================  ===============
    cohort   entry      exit      marks while open    gross at exit
    =======  =========  ========  ==================  ===============
    c0       day 1      day 5     10, 20, 30, 40      50,000
    c1       day 3      day 8     -5, -10, -15, -20   -30,000
    c2       day 6      (live)    7, 14, 21, 28, 35   n/a
    =======  =========  ========  ==================  ===============

    Equity is then, by the engine's own definition, the sum of open marks plus
    the NET realised of everything closed -- which is what the fixture builds, so
    the reconstruction being tested is not assumed anywhere in the fixture.
    """
    idx = pd.bdate_range("2020-01-01", periods=10)
    cohorts = pd.DataFrame([
        {"tag": "T_c0", "structure": "S", "entry": idx[1], "exit": idx[5],
         "direction": 1.0, "live_at_end": False, "closed": True,
         "gross_pnl_ccy": 50_000.0, "net_pnl_ccy": 50_000.0 - FEE},
        {"tag": "T_c1", "structure": "S", "entry": idx[3], "exit": idx[8],
         "direction": 1.0, "live_at_end": False, "closed": True,
         "gross_pnl_ccy": -30_000.0, "net_pnl_ccy": -30_000.0 - FEE},
        {"tag": "T_c2", "structure": "S", "entry": idx[5], "exit": pd.NaT,
         "direction": 1.0, "live_at_end": True, "closed": False,
         "gross_pnl_ccy": np.nan, "net_pnl_ccy": np.nan},
    ])
    marks = pd.DataFrame(0.0, index=idx, columns=["T_c0", "T_c1", "T_c2"])
    marks.loc[idx[1:5], "T_c0"] = [10.0, 20.0, 30.0, 40.0]
    marks.loc[idx[3:8], "T_c1"] = [-5.0, -10.0, -15.0, -20.0, -25.0]
    marks.loc[idx[5:10], "T_c2"] = [7.0, 14.0, 21.0, 28.0, 35.0]
    marks = marks.replace(0.0, np.nan)

    equity = pd.Series(0.0, index=idx)
    for _, r in cohorts.iterrows():
        m = marks[r["tag"]].fillna(0.0)
        equity = equity.add(m, fill_value=0.0)
        if bool(r["closed"]):
            equity.loc[idx >= r["exit"]] += float(r["net_pnl_ccy"])
    return idx, equity, cohorts, marks


@pytest.fixture
def unit_run():
    return _synthetic_unit_run()


@pytest.fixture
def cfg():
    return ll.strat1_config(cost_bp_one_way=COST, package_dv01=DV01)


# ------------------------------------------------------- the daily decomposition


def test_decomposition_reproduces_equity(unit_run, cfg):
    """sum_c contribution_c(t) == equity(t), which the whole study rests on."""
    idx, equity, cohorts, marks = unit_run
    raw, step, err = ll.cohort_contributions(equity, cohorts, marks, cfg=cfg)
    assert err < 1e-9, f"decomposition error ${err}"
    recon = raw.sum(axis=1) - FEE * step.sum(axis=1)
    pd.testing.assert_series_equal(recon, equity, check_names=False, atol=1e-9)


def test_raw_is_fee_free(unit_run, cfg):
    """``raw`` must be GROSS -- the gate re-applies cost, so a fee baked into the
    decomposition would be charged to cohorts the gate never traded."""
    idx, equity, cohorts, marks = unit_run
    raw, step, _ = ll.cohort_contributions(equity, cohorts, marks, cfg=cfg)
    assert raw.loc[idx[9], "T_c0"] == pytest.approx(50_000.0)
    assert raw.loc[idx[9], "T_c1"] == pytest.approx(-30_000.0)
    assert raw.loc[idx[9], "T_c2"] == pytest.approx(35.0)     # live: marked only
    assert step.loc[idx[9]].tolist() == [1.0, 1.0, 0.0]
    assert step.loc[idx[4]].tolist() == [0.0, 0.0, 0.0]       # nothing closed yet


def test_decomposition_check_bites(unit_run, cfg):
    """The identity check must FAIL on an equity curve that does not match.

    Without this, ``check=True`` could be a no-op and every composed curve would
    inherit whatever the engine actually did without anyone noticing.
    """
    idx, equity, cohorts, marks = unit_run
    with pytest.raises(AssertionError):
        ll.cohort_contributions(equity + 1_000.0, cohorts, marks, cfg=cfg)


# ------------------------------------------------------------- known answers


def test_known_answer_composition(unit_run, cfg):
    """Every composed number, computed on paper first.

    All three cohorts traded long at the base cost, so the book is the unit run:
    closed nets are 50,000-100,000 = -50,000 and -30,000-100,000 = -130,000, in
    bp of a $100k package -0.5 and -1.3, and terminal equity adds the live
    cohort's +35 mark: -180,000 + 35 = -179,965.
    """
    idx, equity, cohorts, marks = unit_run
    raw, step, _ = ll.cohort_contributions(equity, cohorts, marks, cfg=cfg)
    direction = pd.Series(1.0, index=idx)
    eq, book = ll.compose_gate_equity(raw, step, cohorts, direction, cfg=cfg)

    assert book["gate_direction"].tolist() == [1.0, 1.0, 1.0]
    assert book.loc[0, "net_bp"] == pytest.approx(-0.5)
    assert book.loc[1, "net_bp"] == pytest.approx(-1.3)
    assert np.isnan(book.loc[2, "net_bp"])                    # live: marked, not closed
    assert book.loc[2, "marked_bp"] == pytest.approx(35.0 / DV01)
    assert float(eq.iloc[-1]) == pytest.approx(-179_965.0)
    # and it is the unit run itself, so it must be the engine's own curve
    pd.testing.assert_series_equal(eq, equity, check_names=False, atol=1e-9)


def test_replaying_unit_direction_reproduces_unit_run(unit_run, cfg):
    """The known-answer property ``apply_gate`` has, at the DAILY level."""
    idx, equity, cohorts, marks = unit_run
    raw, step, _ = ll.cohort_contributions(equity, cohorts, marks, cfg=cfg)
    eq, _ = ll.compose_gate_equity(raw, step, cohorts, pd.Series(1.0, index=idx), cfg=cfg)
    assert float((eq - equity).abs().max()) < 1e-9


def test_flip_negates_gross_but_not_cost(unit_run, cfg):
    """A steepener must earn the mirrored gross and still PAY the round trip."""
    idx, equity, cohorts, marks = unit_run
    raw, step, _ = ll.cohort_contributions(equity, cohorts, marks, cfg=cfg)
    _, lng = ll.compose_gate_equity(raw, step, cohorts, pd.Series(1.0, index=idx), cfg=cfg)
    _, sht = ll.compose_gate_equity(raw, step, cohorts, pd.Series(-1.0, index=idx), cfg=cfg)
    assert sht.loc[0, "gross_bp"] == pytest.approx(-lng.loc[0, "gross_bp"])
    assert sht.loc[1, "gross_bp"] == pytest.approx(-lng.loc[1, "gross_bp"])
    assert sht["cost_bp"].tolist() == lng["cost_bp"].tolist()


def test_steepener_pays_cost(unit_run, cfg):
    """The ``abs(g)`` in the fee term, isolated.

    With ``g`` in place of ``abs(g)`` a short book would be PAID its transaction
    costs, which flatters exactly the structure (5Y/30Y) where the gates are
    two-sided and therefore exactly the number the study turns on.
    """
    idx, equity, cohorts, marks = unit_run
    raw, step, _ = ll.cohort_contributions(equity, cohorts, marks, cfg=cfg)
    eq_z, _ = ll.compose_gate_equity(raw, step, cohorts, pd.Series(-1.0, index=idx),
                                     cfg=cfg, cost_bp_one_way=0.0)
    eq_c, _ = ll.compose_gate_equity(raw, step, cohorts, pd.Series(-1.0, index=idx),
                                     cfg=cfg, cost_bp_one_way=COST)
    # two cohorts close; costing them must LOWER the short book's terminal value
    assert float(eq_c.iloc[-1]) == pytest.approx(float(eq_z.iloc[-1]) - 2.0 * FEE)


def test_standing_aside_is_free(unit_run, cfg):
    """A zero gate must contribute nothing and be charged nothing."""
    idx, equity, cohorts, marks = unit_run
    raw, step, _ = ll.cohort_contributions(equity, cohorts, marks, cfg=cfg)
    eq, book = ll.compose_gate_equity(raw, step, cohorts, pd.Series(0.0, index=idx), cfg=cfg)
    assert not book["traded"].any()
    assert book["cost_bp"].abs().max() == 0.0
    assert float(eq.abs().max()) == 0.0


def test_lag_applied_exactly_once(unit_run, cfg):
    """The gate is read off day t-1, so a signal that turns on ON the entry day
    must NOT trade, and one that turns on the day before must."""
    idx, equity, cohorts, marks = unit_run
    raw, step, _ = ll.cohort_contributions(equity, cohorts, marks, cfg=cfg)

    on_entry = pd.Series(0.0, index=idx)
    on_entry.loc[idx[1]] = 1.0                      # c0's entry day itself
    _, b0 = ll.compose_gate_equity(raw, step, cohorts, on_entry, cfg=cfg)
    assert b0.loc[0, "gate_direction"] == 0.0, "look-ahead: same-day signal traded"

    day_before = pd.Series(0.0, index=idx)
    day_before.loc[idx[0]] = 1.0
    _, b1 = ll.compose_gate_equity(raw, step, cohorts, day_before, cfg=cfg)
    assert b1.loc[0, "gate_direction"] == 1.0, "lagged signal failed to trade"

    # lag=0 must move it back -- proving the shift is real and not a coincidence
    _, b2 = ll.compose_gate_equity(raw, step, cohorts, on_entry, cfg=cfg, lag_days=0)
    assert b2.loc[0, "gate_direction"] == 1.0


def test_gate_dates_outside_the_grid_do_not_trade(unit_run, cfg):
    """A cohort whose entry is absent from the gate's own grid must stand aside.

    The gates live on the 1,901-day contracts grid and the cohorts on the
    1,908-day signal grid, so this is a real case, not a hypothetical.
    """
    idx, equity, cohorts, marks = unit_run
    raw, step, _ = ll.cohort_contributions(equity, cohorts, marks, cfg=cfg)
    partial = pd.Series(1.0, index=idx[:3])         # c1 and c2 entries missing
    _, book = ll.compose_gate_equity(raw, step, cohorts, partial, cfg=cfg)
    assert book["gate_direction"].tolist() == [1.0, 0.0, 0.0]


# ------------------------------------------------------------------- costs


def test_zero_cost_makes_net_equal_gross(unit_run, cfg):
    idx, equity, cohorts, marks = unit_run
    raw, step, _ = ll.cohort_contributions(equity, cohorts, marks, cfg=cfg)
    _, book = ll.compose_gate_equity(raw, step, cohorts, pd.Series(1.0, index=idx),
                                     cfg=cfg, cost_bp_one_way=0.0)
    cl = book[book["gate_closed"]]
    assert np.allclose(cl["net_bp"].to_numpy(float), cl["gross_bp"].to_numpy(float))


def test_cost_sensitivity_is_linear_and_monotone(unit_run, cfg):
    """Only the fee moves, so total net must fall by 2*dc per closed cohort."""
    idx, equity, cohorts, marks = unit_run
    raw, step, _ = ll.cohort_contributions(equity, cohorts, marks, cfg=cfg)
    cs = ll.cost_sensitivity(raw, step, cohorts, pd.Series(1.0, index=idx), cfg=cfg)
    assert cs["cost_multiple"].tolist() == [0.0, 0.5, 1.0, 2.0]
    n = int(cs.loc[0, "n_closed"])
    assert n == 2
    g = float(cs.loc[0, "total_net_bp"])            # 0x cost -> gross
    for _, r in cs.iterrows():
        assert float(r["total_net_bp"]) == pytest.approx(
            g - 2.0 * float(r["cost_bp_one_way"]) * n)
    assert cs["total_net_bp"].is_monotonic_decreasing


def test_breakeven_cost_is_exact(unit_run, cfg):
    """Composing AT the break-even cost must give a total of exactly zero."""
    idx, equity, cohorts, marks = unit_run
    raw, step, _ = ll.cohort_contributions(equity, cohorts, marks, cfg=cfg)
    _, book = ll.compose_gate_equity(raw, step, cohorts, pd.Series(1.0, index=idx), cfg=cfg)
    c = ll.breakeven_cost_bp(book)
    _, at_be = ll.compose_gate_equity(raw, step, cohorts, pd.Series(1.0, index=idx),
                                      cfg=cfg, cost_bp_one_way=c)
    tot = at_be.loc[at_be["gate_closed"], "net_bp"].sum()
    assert float(tot) == pytest.approx(0.0, abs=1e-9)
    # +0.2 bp gross over two closed cohorts -> break-even at 0.05 bp one way,
    # i.e. BELOW the 0.5 bp actually charged, which is exactly why the net book
    # loses money. Costs, not the signal, are what kill this one.
    assert c == pytest.approx(0.2 / 4.0)
    assert c < COST


def test_breakeven_cost_is_negative_when_the_book_loses_gross(unit_run, cfg):
    """A gross loser has a NEGATIVE break-even cost -- no cost level rescues it --
    and that must be reported rather than clipped to zero."""
    idx, equity, cohorts, marks = unit_run
    raw, step, _ = ll.cohort_contributions(equity, cohorts, marks, cfg=cfg)
    _, short = ll.compose_gate_equity(raw, step, cohorts, pd.Series(-1.0, index=idx), cfg=cfg)
    assert ll.breakeven_cost_bp(short) == pytest.approx(-0.2 / 4.0)


# --------------------------------------------------------------- gates & stats


def _synthetic_three():
    """A four-day, two-structure three-way frame with hand-set vols."""
    dates = pd.bdate_range("2020-01-01", periods=4)
    rows = []
    for st, curve in (("SAT", [0.5, 0.5, 0.5, 0.5]), ("MIX", [1.0, 9.0, 1.0, 9.0])):
        for d, c in zip(dates, curve):
            rows.append({"date": d, "structure": st, "breakeven_vol_bp_day": c,
                         "otc_atmf_bp_day": 5.0, "listed_atm_bp_day": 4.0})
    return tw.threeway_frame(pd.DataFrame(rows), ll.threeway_config(
        structures=(("SAT", "5Y", "30Y"), ("MIX", "5Y", "30Y"))))


def test_always_gate_consults_nothing():
    three = _synthetic_three()
    a = ll.gate_series(three, "MIX", ll.ALWAYS)
    assert set(a.unique()) == {1.0}
    assert len(a) == 4
    # while the benchmarked gate is genuinely two-sided on the same rows
    g = ll.gate_series(three, "MIX", "swaption_only")
    assert set(g.unique()) == {1.0, -1.0}


def test_saturation_table_separates_the_two():
    sat = ll.saturation_table(_synthetic_three()).set_index("structure")
    assert bool(sat.loc["SAT", "saturated"]) is True
    assert sat.loc["SAT", "both_frac_cheap"] == pytest.approx(1.0)
    assert bool(sat.loc["MIX", "saturated"]) is False
    assert sat.loc["MIX", "both_frac_cheap"] == pytest.approx(0.5)


def test_scoreboard_bar_direction():
    """More trials must RAISE the bar, and ``clears_max_null`` must compare the
    right way round -- getting either backwards turns the honesty check into a
    rubber stamp."""
    stats = pd.DataFrame({"sharpe_per_trade": [0.05, 0.9]})
    lo = ll.sharpe_scoreboard(stats, 10.0, n_trials=2)
    hi = ll.sharpe_scoreboard(stats, 10.0, n_trials=8)
    assert float(hi["e_max_sharpe_null"].iloc[0]) > float(lo["e_max_sharpe_null"].iloc[0])
    assert not bool(lo["clears_max_null"].iloc[0])
    assert bool(lo["clears_max_null"].iloc[1])
    # a smaller effective sample must also raise the bar
    assert (float(ll.sharpe_scoreboard(stats, 4.0, n_trials=4)["e_max_sharpe_null"].iloc[0])
            > float(ll.sharpe_scoreboard(stats, 40.0, n_trials=4)["e_max_sharpe_null"].iloc[0]))


def test_book_stats_keeps_live_cohorts_out_of_closed_statistics(unit_run, cfg):
    idx, equity, cohorts, marks = unit_run
    raw, step, _ = ll.cohort_contributions(equity, cohorts, marks, cfg=cfg)
    eq, book = ll.compose_gate_equity(raw, step, cohorts, pd.Series(1.0, index=idx), cfg=cfg)
    st = ll.book_stats(eq, book, cfg=cfg)
    assert st["n_cohorts"] == 3 and st["n_closed"] == 2 and st["n_live_marked"] == 1
    assert st["total_net_bp"] == pytest.approx(-1.8)
    assert st["hit_rate"] == pytest.approx(0.0)
    # the MTM curve includes the live cohort; the closed book does not
    assert st["mtm_final_bp"] == pytest.approx(-179_965.0 / DV01)


def test_certify_composition_detects_a_wrong_path():
    """Identical curves certify; a curve with the same terminal but a different
    path must FAIL on the daily-change correlation, which is the whole reason
    that column is reported next to the terminal gap."""
    idx = pd.bdate_range("2020-01-01", periods=60)
    rng = np.random.default_rng(0)
    a = pd.Series(np.cumsum(rng.normal(size=60)) * 1000.0, index=idx)
    same = ll.certify_composition(a, a.copy(), label="S", mode="m")
    assert same["terminal_gap_usd"] == pytest.approx(0.0)
    assert same["corr_daily_changes"] == pytest.approx(1.0)

    shuffled = pd.Series(rng.permutation(a.diff().fillna(0.0).to_numpy()), index=idx).cumsum()
    shuffled.iloc[-1] = a.iloc[-1]
    bad = ll.certify_composition(a, shuffled, label="S", mode="m")
    assert bad["terminal_gap_usd"] == pytest.approx(0.0, abs=1e-6)
    assert abs(bad["corr_daily_changes"]) < 0.5


# ----------------------------------------------------------------- data-backed


def _have(*names: str) -> bool:
    return all((DATA / n).exists() for n in names)


@pytest.mark.slow
@pytest.mark.skipif(not _have("strat1_contracts_panel.parquet"),
                    reason="contracts panel not built")
def test_real_benchmark_frame_is_uniquely_keyed_and_saturated():
    """The study's own headline claims, re-measured on the stored panel."""
    three = ll.load_threeway(DATA, benchmark="real")
    assert not three.index.duplicated().any()
    sat = ll.saturation_table(three).set_index("structure")
    assert bool(sat.loc["5Y/30Y", "saturated"]) is False
    for lb in ("30Y/50Y", "20Yx5Y/25Yx5Y", "10Yx10Y/20Yx10Y"):
        assert bool(sat.loc[lb, "saturated"]) is True, f"{lb} is no longer saturated"
        assert sat.loc[lb, "frac_signals_disagree"] == pytest.approx(0.0)


@pytest.mark.slow
@pytest.mark.skipif(not _have("strat1_le_unit_cohorts_5Y-30Y.parquet",
                              "strat1_le_unit_equity_5Y-30Y.parquet",
                              "strat1_le_unit_marks_5Y-30Y.parquet",
                              "strat1_contracts_panel.parquet"),
                    reason="unit engine run not built")
def test_composed_book_matches_apply_gate():
    """The composed cohort book must equal ``strat1_threeway.apply_gate``'s.

    Two independent expressions of the same idea: ``apply_gate`` multiplies the
    stored direction into ``gross_pnl_bp``, while the composition sums daily
    marks and re-applies the fee. Agreement to machine precision ties this
    module to code the suite already pins.
    """
    lb, safe = "5Y/30Y", "5Y-30Y"
    cfg = ll.strat1_config()
    eq = pd.read_parquet(DATA / f"strat1_le_unit_equity_{safe}.parquet")["equity_usd"]
    co = pd.read_parquet(DATA / f"strat1_le_unit_cohorts_{safe}.parquet")
    mk = pd.read_parquet(DATA / f"strat1_le_unit_marks_{safe}.parquet")
    raw, step, err = ll.cohort_contributions(eq, co, mk, cfg=cfg)
    assert err < 1e-6 * float(eq.abs().max())

    three = ll.load_threeway(DATA, benchmark="real")
    for mode in ("swaption_only", "listed_only", "both"):
        d = ll.gate_series(three, lb, mode)
        _, mine = ll.compose_gate_equity(raw, step, co, d, cfg=cfg)
        theirs = tw.apply_gate(co, d, cfg=ll.threeway_config())
        assert mine["gate_direction"].to_numpy().tolist() == \
            theirs["gate_direction"].to_numpy().tolist(), mode
        a = mine.loc[mine["gate_closed"], "net_bp"].to_numpy(float)
        b = theirs.loc[theirs["gate_closed"], "gate_net_bp"].to_numpy(float)
        assert np.allclose(a, b, atol=1e-9), f"{mode}: cohort P&L disagrees"


@pytest.mark.slow
@pytest.mark.skipif(not _have("strat1_le_unit_cohorts_5Y-30Y.parquet",
                              "strat1_le_unit_equity_5Y-30Y.parquet",
                              "strat1_le_unit_marks_5Y-30Y.parquet"),
                    reason="unit engine run not built")
def test_composed_always_reproduces_the_engine_curve():
    """The ``always`` book is the unit run, so composing it must return the
    engine's own daily mark-to-market with nothing lost in between."""
    safe = "5Y-30Y"
    cfg = ll.strat1_config()
    eq = pd.read_parquet(DATA / f"strat1_le_unit_equity_{safe}.parquet")["equity_usd"]
    eq.index = pd.to_datetime(eq.index)
    co = pd.read_parquet(DATA / f"strat1_le_unit_cohorts_{safe}.parquet")
    mk = pd.read_parquet(DATA / f"strat1_le_unit_marks_{safe}.parquet")
    raw, step, _ = ll.cohort_contributions(eq, co, mk, cfg=cfg)
    composed, _ = ll.compose_gate_equity(raw, step, co, pd.Series(1.0, index=eq.index),
                                         cfg=cfg)
    assert float((composed - eq).abs().max()) < 1e-6 * float(eq.abs().max())


@pytest.mark.slow
@pytest.mark.skipif(not _have("strat1_le_unit_cohorts_5Y-30Y.parquet",
                              "strat1_threeway_longend_unit_cohorts_5Y-30Y.parquet"),
                    reason="unit engine runs not built")
def test_fresh_unit_run_ties_to_the_stored_one():
    """An independent regression check: this study's own 5Y/30Y unit run against
    the one ``strat1_threeway`` stored months of work earlier."""
    a = pd.read_parquet(DATA / "strat1_le_unit_cohorts_5Y-30Y.parquet")
    b = pd.read_parquet(DATA / "strat1_threeway_longend_unit_cohorts_5Y-30Y.parquet")
    key = ["entry"]
    a2 = a.set_index(pd.to_datetime(a["entry"])).sort_index()
    b2 = b.set_index(pd.to_datetime(b["entry"])).sort_index()
    assert a2.index.equals(b2.index), "cohort entry dates diverged"
    m = a2["closed"].to_numpy(bool) & b2["closed"].to_numpy(bool)
    assert np.allclose(a2.loc[m, "gross_pnl_bp"].to_numpy(float),
                       b2.loc[m, "gross_pnl_bp"].to_numpy(float), atol=1e-6)

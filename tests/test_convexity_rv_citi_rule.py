"""Citi's published trade as one pre-specified rule.

The trial count is the whole point of a pre-registration, so it is asserted
against ``docs/convexityrv/citi-framework-preregistration.md`` and the document
is parsed rather than paraphrased: if the two drift, this fails.

Every state-machine test builds a context whose fixture leaves the path under
test a real hole -- a target that is reachable, a stop that is reachable, a
weight change that lands INSIDE a hold, a roll that carries a jump.
"""
from __future__ import annotations

import pathlib
import re

import numpy as np
import pandas as pd
import pytest

from RVUtils.ConvexityRV import citi_fv as FV
from RVUtils.ConvexityRV import citi_rule as R
from RVUtils.ConvexityRV import citi_screen as SC

PREREG = (pathlib.Path(__file__).resolve().parents[1]
          / "docs" / "convexityrv" / "citi-framework-preregistration.md")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _idx(n: int = 260) -> pd.DatetimeIndex:
    return pd.bdate_range("2022-01-03", periods=n)


def _ctx(label: str, *, ca: pd.Series, beta: float = 0.206,
         w2: float = 0.5, w10: float = 0.5, combo: pd.Series = None,
         ok_from: int = 5, rank: float = 3.0,
         ok_mask: pd.Series = None,
         restrikes: pd.DatetimeIndex = None) -> R.StructureContext:
    """A hand-built context: every series explicit, nothing inferred."""
    idx = ca.index
    if combo is None:
        combo = pd.Series(0.0, index=idx)
    b = pd.Series(beta, index=idx)
    w2s, w10s = pd.Series(w2, index=idx), pd.Series(w10, index=idx)
    conds = pd.DataFrame({c: True for c in R.CONDITIONS}, index=idx)
    if ok_mask is not None:
        for c in R.CONDITIONS:
            conds[c] = ok_mask.to_numpy()
    else:
        conds.iloc[:ok_from] = False
    ok = conds.all(axis=1)
    zeros = pd.Series(0.0, index=idx)
    r0 = pd.Series(2.0, index=idx)
    return R.StructureContext(
        label=label, ca_pnl=ca, beta=b, w2=w2s, w10=w10s, combo=combo,
        dcombo_held=combo.diff(), fitted=zeros, rich_bp=ca, z_fly=zeros + 3.0,
        z_model=zeros + rank, roll_3m=zeros + 1.0, impl_rlzd=zeros + 1.5,
        z_pos=zeros + 1.5, conds=conds, all_ok=ok,
        rank_metric=pd.Series(rank, index=idx),
        restrike_dates=(restrikes if restrikes is not None
                        else pd.DatetimeIndex([])),
        rates=(r0, r0 * 1.2, r0 * 1.4))


def _panel_for(idx: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame({c: 2.0 for c in FV.SPOT_COLS}, index=idx)


# ---------------------------------------------------------------------------
# 1. the declared cell list
# ---------------------------------------------------------------------------
def test_declared_cell_count_matches_the_arithmetic():
    cells = R.declared_cells()
    prim = [c for c in cells if c.tier == "primary"]
    sec = [c for c in cells if c.tier == "secondary"]
    diag = [c for c in cells if c.tier == "diagnostic"]
    assert (len(prim), len(sec), len(diag)) == (16, 2, 5)
    assert len(prim) == len(R.Z_LEVELS) * 2 * len(R.HEDGE_SCHEMES)
    assert len(diag) == len(R.CONDITIONS)
    assert len(cells) == 23


def test_the_threshold_ladder_is_two_declared_rungs_and_the_first_is_the_notes():
    assert R.Z_LEVELS[0] == 2.0, "the note's own printed 'about two sigmas'"
    assert R.LADDER_Z in R.Z_LEVELS and R.LADDER_Z < 2.0
    zs = {c.z_min for c in R.declared_cells()}
    assert zs == set(R.Z_LEVELS)


def test_only_the_two_sigma_rung_can_hold_the_headline():
    head = [c for c in R.declared_cells() if c.headline]
    assert len(head) == 1 and head[0].z_min == 2.0


def test_declared_count_matches_the_preregistration_document():
    """The document is the contract; the code must not quietly outgrow it."""
    txt = PREREG.read_text(encoding="utf-8")
    m = re.search(r"\*\*total declared\*\*\s*\|\s*\*\*(\d+)\*\*", txt)
    assert m, "could not find the declared total in the pre-registration"
    assert int(m.group(1)) == len(R.declared_cells())


def test_exactly_one_headline_and_it_is_the_faithful_rule():
    head = [c for c in R.declared_cells() if c.headline]
    assert len(head) == 1
    h = head[0]
    assert h.hedge == "fitted_refit"
    assert h.selection == "screen_best"
    assert h.conditions == R.CONDITIONS
    assert h.z_min == 2.0
    assert h.cell_id == "P|z2.0|screen_best|fitted_refit"


def test_each_diagnostic_drops_exactly_one_condition():
    diag = [c for c in R.declared_cells() if c.tier == "diagnostic"]
    dropped = []
    for c in diag:
        missing = set(R.CONDITIONS) - set(c.conditions)
        assert len(missing) == 1
        dropped.append(missing.pop())
    assert sorted(dropped) == sorted(R.CONDITIONS)


def test_cell_ids_are_unique_and_deterministic():
    a = [c.cell_id for c in R.declared_cells()]
    b = [c.cell_id for c in R.declared_cells()]
    assert a == b and len(set(a)) == len(a)


def test_cellspec_config_carries_its_own_axes_and_inherits_the_rest():
    base = R.RuleConfig(impl_rlzd_min=9.9, max_hold_bd=7)
    c = [x for x in R.declared_cells()
         if x.cell_id == "P|z1.0|blues|unhedged"][0]
    cfg = c.config(base)
    assert cfg.hedge == "unhedged" and cfg.selection == "blues"
    assert cfg.z_model_min == 1.0 and cfg.z_fly_min == 1.0
    assert cfg.impl_rlzd_min == 9.9 and cfg.max_hold_bd == 7
    assert cfg.universe() == ("BLUES",)


# ---------------------------------------------------------------------------
# 2. the note's own printed ticket
# ---------------------------------------------------------------------------
def test_target_and_stop_are_the_notes_printed_dollars():
    cfg = R.RuleConfig()
    assert cfg.ca_dv01 == 200_000.0
    assert cfg.target_usd == pytest.approx(600_000.0)
    assert cfg.stop_usd == pytest.approx(-350_000.0)


def test_the_book_is_short_only():
    assert R.RuleConfig().side == -1


def test_selection_universes_are_the_declared_ones():
    assert R.RuleConfig(selection="screen_best").universe() == ("GREENS", "BLUES",
                                                               "GOLDS")
    assert R.RuleConfig(selection="blues").universe() == ("BLUES",)
    assert R.RuleConfig(selection="screen_best_all5").universe() == \
        SC.SCREEN_STRUCTURES
    assert "WHITES" not in R.PRIMARY_UNIVERSE and "REDS" not in R.PRIMARY_UNIVERSE


# ---------------------------------------------------------------------------
# 3. the P&L identity
# ---------------------------------------------------------------------------
def test_episode_pnl_is_the_declared_identity():
    idx = _idx(40)
    ca = pd.Series(np.linspace(10.0, 8.0, 40), index=idx)
    combo = pd.Series(np.linspace(-18.0, -16.0, 40), index=idx)
    c = _ctx("BLUES", ca=ca, beta=0.206, combo=combo)
    cfg = R.RuleConfig(hedge="fitted_refit")
    ep = R.CitiEpisode("BLUES", idx[5], idx[6], idx[30], idx[31], -1,
                       200_000.0, 0.206, 0.5, 0.5, "target")
    p = R.episode_daily_pnl(ep, c, cfg)
    want = (-1 * (ca.diff() - 0.206 * combo.diff()) * 200_000.0
            ).loc[idx[6]:idx[31]].iloc[1:]
    assert float((p - want).abs().max()) < 1e-6
    assert p.index[0] == idx[7] and p.index[-1] == idx[31]


def test_the_published_trade_reproduces_its_own_recorded_pnl():
    """Blues, 9-Feb-2017 to 6-Jun-2017: 8.8 -> 6.6 bp CA, -18.2 -> -16.5 bp fly,
    $200k DV01, Citi's own table records +$552k (the alert says "net +$500k")."""
    idx = _idx(4)
    ca = pd.Series([8.8, 8.8, 6.6, 6.6], index=idx)
    combo = pd.Series([-18.2, -18.2, -16.5, -16.5], index=idx)
    c = _ctx("BLUES", ca=ca, beta=FV.CITI_FEB2017_B / 100.0, combo=combo)
    cfg = R.RuleConfig(hedge="fitted_refit")
    ep = R.CitiEpisode("BLUES", idx[0], idx[1], idx[1], idx[2], -1,
                       200_000.0, FV.CITI_FEB2017_B / 100.0, 0.705, 0.465,
                       "target")
    total = float(R.episode_daily_pnl(ep, c, cfg).sum())
    assert 4.7e5 < total < 5.6e5, total


def test_an_unhedged_cell_books_only_the_ca_leg():
    idx = _idx(10)
    ca = pd.Series(np.linspace(10.0, 8.0, 10), index=idx)
    combo = pd.Series(np.linspace(-18.0, -10.0, 10), index=idx)
    c = _ctx("BLUES", ca=ca, beta=0.206, combo=combo)
    ep = R.CitiEpisode("BLUES", idx[0], idx[1], idx[7], idx[8], -1,
                       200_000.0, 0.206, 0.5, 0.5, "target")
    p_un = R.episode_daily_pnl(ep, c, R.RuleConfig(hedge="unhedged"))
    p_h = R.episode_daily_pnl(ep, c, R.RuleConfig(hedge="fitted_refit"))
    want = (-1 * ca.diff() * 200_000.0).loc[idx[1]:idx[8]].iloc[1:]
    assert float((p_un - want).abs().max()) < 1e-6
    assert float((p_un - p_h).abs().max()) > 1.0, "the fixture must have a hedge"


def test_frozen_weights_and_refit_weights_diverge_when_the_weights_move():
    """The hole: a mid-hold weight change.  If ``fitted_frozen`` silently used
    the refit path these two would be identical."""
    idx = _idx(40)
    ca = pd.Series(np.linspace(10.0, 9.0, 40), index=idx)
    r0 = pd.Series(np.linspace(2.0, 2.5, 40), index=idx)
    r1 = pd.Series(np.linspace(2.4, 2.6, 40), index=idx)
    r2 = pd.Series(np.linspace(2.8, 3.4, 40), index=idx)
    w2 = pd.Series(0.2, index=idx)
    w2.iloc[20:] = 0.9
    w10 = 1.0 - w2
    combo = (-w2 * r0 + r1 - w10 * r2) * 100.0
    held = ((-w2.shift(1) * r0 + r1 - w10.shift(1) * r2) * 100.0
            - (-w2.shift(1) * r0.shift(1) + r1.shift(1)
               - w10.shift(1) * r2.shift(1)) * 100.0)
    c = R.StructureContext(
        label="BLUES", ca_pnl=ca, beta=pd.Series(0.2, index=idx), w2=w2,
        w10=w10, combo=combo, dcombo_held=held, fitted=ca * 0, rich_bp=ca,
        z_fly=ca * 0, z_model=ca * 0, roll_3m=ca * 0, impl_rlzd=ca * 0,
        z_pos=ca * 0, conds=pd.DataFrame({k: True for k in R.CONDITIONS},
                                         index=idx),
        all_ok=pd.Series(True, index=idx), rank_metric=pd.Series(1.0, index=idx),
        restrike_dates=pd.DatetimeIndex([idx[20]]), rates=(r0, r1, r2))
    ep = R.CitiEpisode("BLUES", idx[5], idx[6], idx[35], idx[36], -1,
                       200_000.0, 0.2, 0.2, 0.8, "max_hold")
    a = float(R.episode_daily_pnl(ep, c, R.RuleConfig(hedge="fitted_refit")).sum())
    b = float(R.episode_daily_pnl(ep, c, R.RuleConfig(hedge="fitted_frozen")).sum())
    assert abs(a - b) > 1.0


def test_a_frozen_context_without_rates_refuses_rather_than_guessing():
    idx = _idx(10)
    ca = pd.Series(1.0, index=idx)
    c = _ctx("BLUES", ca=ca)
    c.rates = (pd.Series(dtype=float),) * 3
    ep = R.CitiEpisode("BLUES", idx[0], idx[1], idx[5], idx[6], -1, 2e5,
                       0.2, 0.5, 0.5, "target")
    with pytest.raises(RuntimeError, match="no rate columns"):
        R.episode_daily_pnl(ep, c, R.RuleConfig(hedge="fitted_frozen"))


# ---------------------------------------------------------------------------
# 4. the state machine
# ---------------------------------------------------------------------------
def _run(ca: pd.Series, cfg: R.RuleConfig, **kw):
    c = _ctx("BLUES", ca=ca, **kw)
    ctx = {"BLUES": c}
    eps = R.episodes_from_contexts(ctx, cfg, panel=_panel_for(ca.index))
    return ctx, eps


def test_a_reachable_target_closes_the_trade_and_names_the_reason():
    idx = _idx(60)
    ca = pd.Series(10.0, index=idx)
    ca.iloc[20:] = 5.0                       # -5 bp on a short = +$1.0m
    cfg = R.RuleConfig(hedge="unhedged", selection="blues")
    _, eps = _run(ca, cfg)
    assert len(eps) >= 1
    e = eps[0]
    assert e.exit_reason == "target"
    assert e.side == -1
    assert e.entry_fill == idx[int(idx.get_loc(e.entry_decision)) + 1]
    assert e.exit_fill == idx[int(idx.get_loc(e.exit_decision)) + 1]


def test_a_reachable_stop_closes_the_trade():
    idx = _idx(60)
    ca = pd.Series(10.0, index=idx)
    ca.iloc[20:] = 14.0                      # +4 bp against a short = -$800k
    cfg = R.RuleConfig(hedge="unhedged", selection="blues")
    _, eps = _run(ca, cfg)
    assert eps and eps[0].exit_reason == "stop"


def test_max_hold_binds_when_nothing_else_does():
    idx = _idx(120)
    ca = pd.Series(10.0, index=idx)          # never moves: no target, no stop
    cfg = R.RuleConfig(hedge="unhedged", selection="blues", max_hold_bd=20)
    _, eps = _run(ca, cfg)
    assert eps and eps[0].exit_reason == "max_hold"
    assert eps[0].hold_bd == pytest.approx(21, abs=1)


def test_the_last_episode_is_closed_at_the_end_of_sample():
    idx = _idx(30)
    ca = pd.Series(10.0, index=idx)
    cfg = R.RuleConfig(hedge="unhedged", selection="blues", max_hold_bd=999)
    _, eps = _run(ca, cfg)
    assert eps and eps[-1].exit_reason == "end_of_sample"


def test_only_one_position_is_open_at_a_time():
    idx = _idx(200)
    ca = pd.Series(10.0 - 0.05 * np.arange(200), index=idx)
    cfg = R.RuleConfig(hedge="unhedged", selection="blues", max_hold_bd=15)
    _, eps = _run(ca, cfg)
    assert len(eps) > 3
    for a, b in zip(eps, eps[1:]):
        assert b.entry_fill > a.exit_fill, "positions overlapped"


def test_the_screen_picks_the_widest_structure():
    idx = _idx(60)
    ca = pd.Series(10.0, index=idx)
    ctx = {"GREENS": _ctx("GREENS", ca=ca, rank=1.0),
           "BLUES": _ctx("BLUES", ca=ca, rank=4.0),
           "GOLDS": _ctx("GOLDS", ca=ca, rank=2.5)}
    cfg = R.RuleConfig(hedge="unhedged", selection="screen_best")
    eps = R.episodes_from_contexts(ctx, cfg, panel=_panel_for(idx))
    assert eps and all(e.structure == "BLUES" for e in eps)


def test_a_structure_that_fails_the_conjunction_is_not_selected_however_wide():
    idx = _idx(60)
    ca = pd.Series(10.0, index=idx)
    wide = _ctx("GOLDS", ca=ca, rank=9.0)
    wide.conds["implied_rich"] = False
    wide.all_ok = wide.conds.all(axis=1)
    ctx = {"BLUES": _ctx("BLUES", ca=ca, rank=1.0), "GOLDS": wide}
    cfg = R.RuleConfig(hedge="unhedged", selection="screen_best")
    eps = R.episodes_from_contexts(ctx, cfg, panel=_panel_for(idx))
    assert eps and all(e.structure == "BLUES" for e in eps)


def test_dropping_a_condition_lets_the_refused_structure_back_in():
    """The drop-one diagnostics have to actually change the book."""
    idx = _idx(60)
    ca = pd.Series(10.0, index=idx)
    wide = _ctx("GOLDS", ca=ca, rank=9.0)
    wide.conds["implied_rich"] = False
    rest = tuple(c for c in R.CONDITIONS if c != "implied_rich")
    wide.all_ok = wide.conds[list(rest)].all(axis=1)
    ctx = {"BLUES": _ctx("BLUES", ca=ca, rank=1.0), "GOLDS": wide}
    cfg = R.RuleConfig(hedge="unhedged", selection="screen_best",
                       conditions=rest)
    eps = R.episodes_from_contexts(ctx, cfg, panel=_panel_for(idx))
    assert eps and all(e.structure == "GOLDS" for e in eps)


def test_nothing_opens_before_the_conjunction_is_satisfiable():
    idx = _idx(60)
    ca = pd.Series(10.0, index=idx)
    cfg = R.RuleConfig(hedge="unhedged", selection="blues")
    _, eps = _run(ca, cfg, ok_from=30)
    assert eps and eps[0].entry_decision == idx[30]


def test_same_day_fills_harvest_engineered_mark_noise_and_t_plus_one_kills_it():
    """A saw-tooth mark: on every day the conjunction fires, the CA is one bp
    HIGH and reverts the next.  That is precisely the situation the note's
    signal describes -- "the CA is wide" -- and a rule that SHORTS at the mark
    its own signal was computed from banks the reversion for free.  A t+1 fill
    cannot: by the time it trades, the mark has already reverted.

    The gap between the two IS the mark-noise harvest, and it is the reason
    ``exec_lag_bd = 1`` is the declared convention and 0 is a diagnostic.
    """
    idx = _idx(200)
    ca = pd.Series(10.0, index=idx)
    ca.iloc[::2] = 11.0                      # rich on even marks, fair on odd
    fires = pd.Series(False, index=idx)
    fires.iloc[6::2] = True                  # the signal fires only when rich

    def run(lag: int):
        cfg = R.RuleConfig(hedge="unhedged", selection="blues", exec_lag_bd=lag,
                           max_hold_bd=1, target_bp=99.0, stop_bp=-99.0)
        c = _ctx("BLUES", ca=ca, ok_mask=fires)
        eps = R.episodes_from_contexts({"BLUES": c}, cfg, panel=_panel_for(idx))
        return sum(float(R.episode_daily_pnl(e, c, cfg).sum()) for e in eps)

    p0, p1 = run(0), run(1)
    assert p0 > 1e6, f"same-day fills must harvest the engineered noise ({p0})"
    assert p1 < 0.1 * p0, f"the t+1 fill must give the harvest back ({p1})"


# ---------------------------------------------------------------------------
# 5. costs
# ---------------------------------------------------------------------------
def _ep(beta=0.206, w2=0.705, w10=0.465, restrikes=0):
    idx = _idx(5)
    return R.CitiEpisode("BLUES", idx[0], idx[1], idx[3], idx[4], -1,
                         200_000.0, beta, w2, w10, "target",
                         n_restrikes=restrikes)


def test_cost_is_the_declared_per_leg_arithmetic():
    cfg = R.RuleConfig(hedge="fitted_refit")
    c = R.episode_cost_usd(_ep(), cfg, mult=1.0)
    belly = 0.206 * 200_000.0
    want = ((R.FUT_RT_BP + R.SWAP_RT_BP) * 200_000.0
            + R.LEG_RT_BP * belly * (1 + 0.705 + 0.465))
    assert c == pytest.approx(want)


def test_a_restrike_costs_one_further_fly_round_trip():
    cfg = R.RuleConfig(hedge="fitted_refit")
    one = R.episode_cost_usd(_ep(restrikes=0), cfg)
    two = R.episode_cost_usd(_ep(restrikes=1), cfg)
    belly = 0.206 * 200_000.0
    assert two - one == pytest.approx(R.LEG_RT_BP * belly * (1 + 0.705 + 0.465))


def test_an_unhedged_episode_pays_no_fly_cost():
    c = R.episode_cost_usd(_ep(), R.RuleConfig(hedge="unhedged"))
    assert c == pytest.approx((R.FUT_RT_BP + R.SWAP_RT_BP) * 200_000.0)


def test_zero_cost_multiplier_is_free():
    assert R.episode_cost_usd(_ep(), R.RuleConfig(), mult=0.0) == 0.0


def test_book_daily_charges_the_cost_at_the_exit_fill():
    idx = _idx(40)
    ca = pd.Series(10.0, index=idx)
    c = _ctx("BLUES", ca=ca)
    cfg = R.RuleConfig(hedge="unhedged", selection="blues")
    ep = R.CitiEpisode("BLUES", idx[5], idx[6], idx[20], idx[21], -1,
                       200_000.0, 0.0, 0.5, 0.5, "target")
    d = R.book_daily([ep], {"BLUES": c}, cfg, index=idx, cost_mult=1.0)
    assert d.loc[idx[21]] == pytest.approx(-R.episode_cost_usd(ep, cfg))
    assert float(d.drop(idx[21]).abs().sum()) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 6. contexts built from a real-shaped panel
# ---------------------------------------------------------------------------
def _real_panel(n: int = 900, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2021-01-04", periods=n)
    p = pd.DataFrame(index=idx)
    p["r2y_pct"] = 2.0 + np.cumsum(rng.normal(0, 0.02, n))
    p["r5y_pct"] = 2.4 + np.cumsum(rng.normal(0, 0.02, n))
    p["r10y_pct"] = 2.8 + np.cumsum(rng.normal(0, 0.02, n))
    for k, lab in enumerate(SC.SCREEN_STRUCTURES):
        t1 = 0.25 * (4 * k + 2.5)
        l = lab.lower()
        p[f"{l}_w"] = t1 ** 2 + 0.3
        p[f"{l}_t1mean"] = t1
        p[SC.VOL_COL[lab]] = 100.0 + 10.0 * np.sin(np.arange(n) / 50.0)
        p[f"{l}_ca_bp"] = ((100.0 ** 2) * (t1 ** 2 + 0.3) / 2e4
                           + np.cumsum(rng.normal(0, 0.06, n)))
        p[f"{l}_fwd1y_pct"] = 2.5 + np.cumsum(rng.normal(0, 0.01, n))
    p["is_roll"] = False
    p["is_ca_roll"] = False
    rolls = idx[63::63]
    p.loc[rolls, ["is_roll", "is_ca_roll"]] = True
    for lab in SC.SCREEN_STRUCTURES:               # plant the roll jump
        col = f"{lab.lower()}_ca_bp"
        for r in rolls:
            p.loc[p.index >= r, col] += 0.95
    p["dealer_net"] = np.cumsum(rng.normal(0, 5e3, n)) + 3e5
    return p


def test_contexts_are_causal_in_their_conditions():
    p = _real_panel()
    s = SC.build_screen(p)
    cfg = R.RuleConfig()
    ctx = R.build_contexts(p, s, cfg)
    cut = p.index[700]
    p2 = p.copy()
    p2.loc[p2.index >= cut, "blues_ca_bp"] += 8.0
    s2 = SC.build_screen(p2)
    ctx2 = R.build_contexts(p2, s2, cfg)
    a = ctx["BLUES"].conds.loc[:p.index[699]]
    b = ctx2["BLUES"].conds.loc[:p.index[699]]
    pd.testing.assert_frame_equal(a, b)


def test_the_conditions_are_the_declared_inequalities():
    p = _real_panel()
    s = SC.build_screen(p)
    cfg = R.RuleConfig()
    c = R.build_contexts(p, s, cfg)["BLUES"]
    j = c.conds.copy()
    assert (j["wide_to_model"] == (c.z_model >= cfg.z_model_min).fillna(False)).all()
    assert (j["wide_to_fly"] == (c.z_fly >= cfg.z_fly_min).fillna(False)).all()
    assert (j["implied_rich"] == (c.impl_rlzd >= cfg.impl_rlzd_min).fillna(False)).all()
    assert (j["positioning_stretched"] == (c.z_pos >= cfg.z_pos_min).fillna(False)).all()


def test_a_missing_input_refuses_rather_than_confirming():
    p = _real_panel()
    p.loc[p.index[400:600], "dealer_net"] = np.nan
    s = SC.build_screen(p)
    c = R.build_contexts(p, s, R.RuleConfig())["BLUES"]
    win = c.conds.loc[p.index[500]:p.index[560], "positioning_stretched"]
    assert not win.any()


def test_the_splice_removes_the_planted_roll_jump_from_the_pnl_series():
    p = _real_panel()
    s = SC.build_screen(p)
    on = R.build_contexts(p, s, R.RuleConfig(splice_pnl=True))["BLUES"]
    off = R.build_contexts(p, s, R.RuleConfig(splice_pnl=False))["BLUES"]
    rolls = p.index[p["is_ca_roll"].astype(bool)]
    assert float(off.ca_pnl.diff().loc[rolls].mean()) > 0.8
    assert abs(float(on.ca_pnl.diff().loc[rolls].mean())) < 1e-9


def test_the_signal_and_the_pnl_use_DIFFERENT_series_by_default():
    """The declared convention: the screen z-scores the raw constant-rank CA
    (which is stationary because the roll pays the decay back), and the P&L
    marks the spliced one (which is the path a dated position walks).  A build
    that used one series for both would fail this."""
    p = _real_panel()
    s = SC.build_screen(p)
    cfg = R.RuleConfig()
    assert cfg.splice_signal is False and cfg.splice_pnl is True
    c = R.build_contexts(p, s, cfg)["BLUES"]
    raw = p["blues_ca_bp"].astype(float)
    assert float((c.ca_pnl - raw).abs().max()) > 1.0     # P&L series IS spliced
    rolls = p.index[p["is_ca_roll"].astype(bool)]
    assert abs(float(c.ca_pnl.diff().loc[rolls].mean())) < 1e-9
    # and the signal saw the RAW series: its fitted value tracks the raw level
    assert float((c.rich_bp + c.fitted - raw).abs().max()) < 1e-9


def test_splicing_the_signal_pushes_the_rolling_z_down_by_construction():
    """The measured reason the signal is NOT spliced: the spliced series carries
    the whole undone decay as a drift, so its own z sits below zero."""
    p = _real_panel()
    s = SC.build_screen(p)
    raw = R.build_contexts(p, s, R.RuleConfig(splice_signal=False))["BLUES"]
    spl = R.build_contexts(p, s, R.RuleConfig(splice_signal=True))["BLUES"]
    assert float(spl.z_model.median()) < float(raw.z_model.median()) - 0.3


def test_condition_binding_reports_which_gate_refuses():
    p = _real_panel()
    s = SC.build_screen(p)
    cfg = R.RuleConfig()
    ctx = R.build_contexts(p, s, cfg)
    b = R.condition_binding(ctx, cfg)
    assert set(b.index) == set(R.PRIMARY_UNIVERSE)
    for k in R.CONDITIONS:
        assert 0.0 <= float(b[f"pass_{k}"].min()) <= 1.0
        assert f"binds_alone_{k}" in b.columns
    assert (b["pass_all"] <= b[[f"pass_{k}" for k in R.CONDITIONS]].min(axis=1)
            + 1e-12).all()


def test_restrike_dates_are_the_refit_dates_and_are_counted_inside_a_hold():
    p = _real_panel()
    s = SC.build_screen(p)
    cfg = R.RuleConfig(hedge="fitted_refit", selection="blues",
                       max_hold_bd=200, z_model_min=-9.0, z_fly_min=-9.0,
                       impl_rlzd_min=-9.0, z_pos_min=-9.0)
    ctx = R.build_contexts(p, s, cfg)
    eps = R.episodes_from_contexts(ctx, cfg, panel=p)
    assert eps
    assert any(e.n_restrikes > 0 for e in eps), (
        "a 200 bd hold must straddle at least one quarterly refit")


def test_frozen_and_unhedged_never_book_a_restrike_cost():
    p = _real_panel()
    s = SC.build_screen(p)
    for h in ("fitted_frozen", "unhedged"):
        cfg = R.RuleConfig(hedge=h, selection="blues", max_hold_bd=200,
                           z_model_min=-9.0, z_fly_min=-9.0,
                           impl_rlzd_min=-9.0, z_pos_min=-9.0)
        ctx = R.build_contexts(p, s, cfg)
        eps = R.episodes_from_contexts(ctx, cfg, panel=p)
        assert eps and all(e.n_restrikes == 0 for e in eps)


# ---------------------------------------------------------------------------
# 7. statistics
# ---------------------------------------------------------------------------
def test_n_eff_is_the_smaller_of_the_two_clocks():
    idx = _idx(60)
    ca = pd.Series(10.0, index=idx)
    c = _ctx("BLUES", ca=ca)
    cfg = R.RuleConfig(hedge="unhedged", selection="blues")
    eps = [R.CitiEpisode("BLUES", idx[0], idx[1], idx[10], idx[11], -1, 2e5,
                         0.0, 0.5, 0.5, "target")]
    res = R.CellResult(R.declared_cells()[0], cfg, eps,
                       {0.0: R.book_daily(eps, {"BLUES": c}, cfg, index=idx)},
                       [1.0], 0.0, len(idx))
    f = R.stats_frame([res], span_years=5.0)
    assert float(f["n_eff"].iloc[0]) == 1.0            # 1 episode, not 5*252/8
    assert float(f["n_eff_hold_clock"].iloc[0]) > 1.0


def test_null_bar_rises_with_the_trial_count_and_falls_with_the_span():
    a = R.null_bars(1, n_eff=10, span_years=4.7)["emax_annualised"]
    b = R.null_bars(15, n_eff=10, span_years=4.7)["emax_annualised"]
    c = R.null_bars(15, n_eff=10, span_years=9.4)["emax_annualised"]
    assert b > a and c < b


def test_stats_frame_reports_every_exit_reason_and_the_cost_sweep():
    idx = _idx(60)
    ca = pd.Series(10.0, index=idx)
    c = _ctx("BLUES", ca=ca)
    cfg = R.RuleConfig(hedge="unhedged", selection="blues")
    eps = [R.CitiEpisode("BLUES", idx[0], idx[1], idx[10], idx[11], -1, 2e5,
                         0.0, 0.5, 0.5, "stop")]
    daily = {m: R.book_daily(eps, {"BLUES": c}, cfg, index=idx, cost_mult=m)
             for m in R.COST_MULTS}
    f = R.stats_frame([R.CellResult(R.declared_cells()[0], cfg, eps, daily,
                                    [0.0], 0.0, len(idx))], span_years=5.0)
    assert int(f["exit_stop"].iloc[0]) == 1
    assert int(f["exit_target"].iloc[0]) == 0
    for m in R.COST_MULTS:
        assert f"net_{m}" in f.columns and f"sharpe_{m}" in f.columns
    assert float(f["net_0.0"].iloc[0]) > float(f["net_2.0"].iloc[0])


# ---------------------------------------------------------------------------
# 8. the refit memo -- an optimisation that must not change an answer
# ---------------------------------------------------------------------------
def test_the_refit_memo_returns_the_same_answer_as_a_cold_fit():
    p = _real_panel()
    s = SC.build_screen(p)
    cfg = R.RuleConfig()
    R.clear_fv_memo()
    cold = R.build_contexts(p, s, cfg)["BLUES"]
    warm = R.build_contexts(p, s, cfg)["BLUES"]
    for attr in ("fitted", "rich_bp", "beta", "w2", "w10", "combo",
                 "dcombo_held", "z_fly"):
        a, b = getattr(cold, attr), getattr(warm, attr)
        assert a.equals(b) or float((a - b).abs().max()) < 1e-15, attr


def test_the_memo_hands_back_a_copy_so_a_caller_cannot_poison_it():
    p = _real_panel()
    s = SC.build_screen(p)
    cfg = R.RuleConfig()
    R.clear_fv_memo()
    first = R.build_contexts(p, s, cfg)["BLUES"]
    first.fitted.iloc[:] = -999.0
    second = R.build_contexts(p, s, cfg)["BLUES"]
    assert float(second.fitted.dropna().abs().max()) < 900.0


def test_the_memo_key_separates_structures_and_fit_kinds():
    p = _real_panel()
    s = SC.build_screen(p)
    R.clear_fv_memo()
    fly = R.build_contexts(p, s, R.RuleConfig(hedge="fitted_refit"))
    citi = R.build_contexts(p, s, R.RuleConfig(hedge="citi_2017"))
    # different structures must not share a fit
    assert not fly["BLUES"].fitted.equals(fly["GOLDS"].fitted)
    # and the fly-constrained fit is not Citi's fixed-weight one
    assert not fly["BLUES"].w2.equals(citi["BLUES"].w2)
    assert float(citi["BLUES"].w2.dropna().unique()[0]) == FV.CITI_FEB2017_W2


def test_a_changed_panel_does_not_hit_a_stale_memo_entry():
    """The key is a CONTENT fingerprint; an object id would be reused after a
    garbage collection and serve one panel's fit under another's name.

    Note the perturbation has to change the SHAPE: adding a constant to a
    regressor moves nothing, because the fitted intercept absorbs it exactly --
    which is worth knowing before reading any fair-value sensitivity.
    """
    p = _real_panel()
    s = SC.build_screen(p)
    cfg = R.RuleConfig()
    R.clear_fv_memo()
    a = R.build_contexts(p, s, cfg)["BLUES"].fitted
    level = p.copy()
    level["r5y_pct"] += 0.25
    lv = R.build_contexts(level, SC.build_screen(level), cfg)["BLUES"].fitted
    assert float((a - lv).abs().max()) < 1e-9, "the intercept absorbs a level shift"
    shape = p.copy()
    shape["r5y_pct"] = shape["r5y_pct"] * 1.5
    sh = R.build_contexts(shape, SC.build_screen(shape), cfg)["BLUES"].fitted
    assert float((a - sh).abs().max()) > 1e-6


def test_the_memo_fingerprint_separates_a_permutation_of_the_same_values():
    """A fingerprint built only from a sum would collide here."""
    p = _real_panel()
    cfg = R.RuleConfig()
    R.clear_fv_memo()
    a = R.build_contexts(p, SC.build_screen(p), cfg)["BLUES"].fitted
    q = p.copy()
    q["r5y_pct"] = q["r5y_pct"].to_numpy()[::-1]
    b = R.build_contexts(q, SC.build_screen(q), cfg)["BLUES"].fitted
    assert float((a - b).abs().max()) > 1e-6

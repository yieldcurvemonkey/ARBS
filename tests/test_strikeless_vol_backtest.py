"""Task 18: the backtest engine, the config grid and the league table.

The six binding requirements (Task 15) are tested here as CODE PATHS, not as
report strings: every one of them has a test that fails if the enforcement is
removed. See the task-18 report's mutation table.
"""
import numpy as np
import pandas as pd
import pytest

from RVUtils.StrikelessVol.backtest import (
    BacktestResult,
    PlaceboResult,
    RequirementFlags,
    audit_causal_betas,
    audit_rolling_sigma_z,
    audit_trailing_statistic,
    build_config_grid,
    causal_signals,
    entry_vintage_signals,
    random_walk_like,
    random_walk_placebo,
    run_grid,
    run_pair,
    with_placebo,
)
from RVUtils.StrikelessVol.costs import FREE, MAKER, TAKER, CostSchedule
from RVUtils.StrikelessVol.factors import (
    changes_regression,
    expanding_changes_residual,
    expanding_residual,
    levels_regression,
    residual_z,
)
from RVUtils.StrikelessVol.replication import ReplicationConfig
from RVUtils.StrikelessVol.report import (
    cost_table,
    league_table,
    ledger_attribution,
    per_year_attribution,
)
from RVUtils.StrikelessVol.strategy import SignalConfig


BASE_DV01 = 100_000.0


class SyntheticCtx:
    """Same closed-form world as tests/test_strikeless_vol_replication.py."""

    def __init__(self, path_bp, theta_per_day=-500.0, gamma=40.0,
                 start="2026-01-01"):
        self.dates = pd.bdate_range(start, periods=len(path_bp))
        self.path = dict(zip(self.dates, np.asarray(path_bp, dtype=float)))
        self.day_index = {d: i for i, d in enumerate(self.dates)}
        self.theta_per_day = theta_per_day
        self.k = gamma / 1e4

    def rate(self, date, leg):
        return (0.04 if leg == "long" else 0.045) + self.path[date] * 1e-4

    def dv01(self, date, leg):
        return 1.0 + self.k * self.path[date] if leg == "long" else 1.0

    def theta(self, date, nl, ns):
        return self.theta_per_day * (nl / BASE_DV01)

    def pv(self, date, nl, ns):
        dr = self.path[date]
        i = self.day_index[date]
        return (
            nl * (dr + 0.5 * self.k * dr * dr)
            - ns * dr
            + self.theta_per_day * i * (nl / BASE_DV01)
        )


def _signals(dates, sign=1, size=1.0):
    return pd.DataFrame(
        {"sign": sign, "size": size, "dv01_usd": sign * size * 100_000.0,
         "reason": "test"},
        index=dates,
    )


# ---------------------------------------------------------------- the brief's six


def test_run_pair_returns_a_complete_result():
    ctx = SyntheticCtx(list(np.linspace(0, 40, 60)))
    res = run_pair(ctx, _signals(ctx.dates), rep_cfg=ReplicationConfig(),
                   costs=FREE, pair_name="TEST")
    assert isinstance(res, BacktestResult)
    assert len(res.daily_pnl) == len(ctx.dates)
    assert {"carry", "harvest", "mtm", "cost", "cross", "total"} <= set(res.ledger.columns)
    assert res.stats["n"] == len(ctx.dates)


def test_zero_signal_produces_zero_pnl_and_no_costs():
    ctx = SyntheticCtx(list(np.linspace(0, 40, 60)))
    res = run_pair(ctx, _signals(ctx.dates, sign=0, size=0.0),
                   rep_cfg=ReplicationConfig(), costs=TAKER, pair_name="TEST")
    assert res.daily_pnl.abs().sum() == pytest.approx(0.0, abs=1e-9)


def test_sign_flip_flips_the_pnl():
    ctx = SyntheticCtx(list(np.linspace(0, 40, 60)))
    long_ = run_pair(ctx, _signals(ctx.dates, sign=1), rep_cfg=ReplicationConfig(),
                     costs=FREE, pair_name="TEST")
    short = run_pair(ctx, _signals(ctx.dates, sign=-1), rep_cfg=ReplicationConfig(),
                     costs=FREE, pair_name="TEST")
    assert long_.daily_pnl.sum() == pytest.approx(-short.daily_pnl.sum(), rel=1e-9)


def test_run_grid_reports_one_row_per_config():
    ctx = SyntheticCtx(list(np.linspace(0, 40, 60)))
    grid = [{"trigger_bp": t} for t in (10.0, 25.0, 40.0)]
    out = run_grid({"TEST": ctx}, {"TEST": _signals(ctx.dates)}, grid, costs=FREE)
    assert len(out) == 3
    assert set(out["trigger_bp"]) == {10.0, 25.0, 40.0}


def test_league_table_reports_costs_at_multiple_multipliers():
    # CHANGED from the brief: `cost_schedule=TAKER` added. The run is FREE, and
    # league_table now refuses to quote 1x/2x costs from a zero-cost run without
    # a schedule to reprice from (I5) -- scaling zero by two is still zero, and
    # net_2x_bp is the ALIVE gate's own input. The assertion is the brief's.
    ctx = SyntheticCtx(list(np.linspace(0, 40, 60)))
    res = run_pair(ctx, _signals(ctx.dates), rep_cfg=ReplicationConfig(),
                   costs=FREE, pair_name="TEST")
    tbl = league_table([res], cost_schedule=TAKER)
    assert {"net_1x_bp", "net_2x_bp", "dsr_prob", "verdict"} <= set(tbl.columns)


def test_ledger_attribution_exposes_the_harvest_flow_ratio():
    ctx = SyntheticCtx(list(np.linspace(0, 100, 101)))
    res = run_pair(ctx, _signals(ctx.dates), rep_cfg=ReplicationConfig(trigger_bp=25.0),
                   costs=FREE, pair_name="TEST")
    att = ledger_attribution([res])
    assert "harvest_flow_ratio" in att.columns
    assert "harvest_pnl_share" in att.columns
    assert att["harvest_flow_ratio"].iloc[0] >= 0.0


# ------------------------------------------------------- naming trap: usd vs bp


def test_trade_pnl_columns_do_not_wear_a_bp_name_on_dollar_values():
    """The dollar columns are named *_usd; the bp columns divide by REALISED DV01.

    A design-notional divisor is wrong -- the realised book here is not $100k.
    """
    ctx = SyntheticCtx(list(np.linspace(0, 100, 101)))
    res = run_pair(ctx, _signals(ctx.dates), rep_cfg=ReplicationConfig(trigger_bp=25.0),
                   costs=FREE, pair_name="TEST")
    t = res.trades
    assert {"gross_usd", "cost_usd", "net_usd", "gross_bp", "cost_bp", "net_bp",
            "avg_dv01_usd"} <= set(t.columns)
    row = t.iloc[0]
    # the bp figure is the dollar figure over the REALISED average DV01 ...
    assert row["gross_bp"] == pytest.approx(row["gross_usd"] / row["avg_dv01_usd"])
    # ... and the realised DV01 is NOT the design notional on this path
    assert abs(row["avg_dv01_usd"] - 100_000.0) > 1_000.0


def test_the_bp_divisor_is_the_realised_dv01_not_the_design_notional():
    """Two paths with the same design notional but different realised DV01 must
    not produce the same bp number for the same dollar P&L."""
    flat = SyntheticCtx([0.0] * 60)
    drift = SyntheticCtx(list(np.linspace(0.0, 80.0, 60)))
    a = run_pair(flat, _signals(flat.dates), rep_cfg=ReplicationConfig(),
                 costs=FREE, pair_name="A")
    b = run_pair(drift, _signals(drift.dates), rep_cfg=ReplicationConfig(),
                 costs=FREE, pair_name="B")
    assert a.stats["realised_dv01_mean_usd"] == pytest.approx(100_000.0, rel=1e-9)
    assert b.stats["realised_dv01_mean_usd"] != pytest.approx(100_000.0, rel=1e-3)


# --------------------------------------------------------------- cost accounting


def test_the_initiation_cost_is_charged_once_not_twice():
    """simulate() charges an initiate on day 0 AND the signal opens a position on
    day 0. Charging both double-counts the entry."""
    ctx = SyntheticCtx([0.0] * 40)
    res = run_pair(ctx, _signals(ctx.dates), rep_cfg=ReplicationConfig(),
                   costs=TAKER, pair_name="TEST")
    expected = TAKER.cost_usd("initiate", 100_000.0)
    assert res.ledger["cost"].iloc[0] == pytest.approx(-expected, rel=1e-9)


def test_the_full_round_trip_is_charged_on_a_complete_cycle():
    ctx = SyntheticCtx([0.0] * 40)
    sig = _signals(ctx.dates, sign=0, size=0.0)
    sig.loc[ctx.dates[5]:ctx.dates[19], ["sign", "size", "dv01_usd"]] = [1, 1.0, 100_000.0]
    res = run_pair(ctx, sig, rep_cfg=ReplicationConfig(), costs=TAKER, pair_name="TEST")
    round_trip = 2.0 * TAKER.cost_usd("initiate", 100_000.0)
    assert -res.ledger["cost"].sum() == pytest.approx(round_trip, rel=1e-9)
    # trades carry the fee as a positive magnitude; the ledger carries it signed
    assert res.trades["cost_usd"].sum() == pytest.approx(round_trip, rel=1e-9)


def test_cost_table_carries_the_roll_convention_as_its_own_row():
    ctx = SyntheticCtx(list(np.linspace(0, 40, 400)))
    res = run_pair(ctx, _signals(ctx.dates), rep_cfg=ReplicationConfig(roll_months=3),
                   costs=TAKER, pair_name="TEST")
    tbl = cost_table([res], schedule=TAKER)
    assert {"cost_multiplier", "roll_charged", "cost_usd", "net_usd"} <= set(tbl.columns)
    assert set(tbl["roll_charged"]) == {True, False}
    charged = tbl[(tbl["cost_multiplier"] == 1.0) & tbl["roll_charged"]]["cost_usd"].iloc[0]
    free = tbl[(tbl["cost_multiplier"] == 1.0) & ~tbl["roll_charged"]]["cost_usd"].iloc[0]
    assert charged > free  # the roll convention is worth something, and it shows


def test_cost_table_multipliers_scale_the_charge():
    ctx = SyntheticCtx(list(np.linspace(0, 100, 101)))
    res = run_pair(ctx, _signals(ctx.dates), rep_cfg=ReplicationConfig(trigger_bp=25.0),
                   costs=TAKER, pair_name="TEST")
    tbl = cost_table([res], schedule=TAKER, multipliers=(0.0, 1.0, 2.0))
    charged = tbl[tbl["roll_charged"]].set_index("cost_multiplier")["cost_usd"]
    assert charged.loc[0.0] == pytest.approx(0.0)
    assert charged.loc[2.0] == pytest.approx(2.0 * charged.loc[1.0], rel=1e-9)


def test_simulate_charges_exactly_the_fee_on_the_risk_it_records():
    """The invariant `cost_table` (and `sv_static_long_control`'s roll override)
    rely on: every dollar of `cost` is the fee on a recorded traded-risk volume.

    If a charge were ever booked without recording its volume -- or a volume
    recorded without being charged -- repricing a ledger at another schedule or
    the other roll convention would silently disagree with the run itself.
    """
    from RVUtils.StrikelessVol.costs import charge_usd
    from RVUtils.StrikelessVol.replication import simulate

    # steep enough that the trigger fires between rolls (the roll resets the
    # hedge anchor, so a shallow path would exercise the roll branch only)
    ctx = SyntheticCtx(list(np.linspace(0, 400, 400)), gamma=5.0)
    led = simulate(ctx, list(ctx.dates), ReplicationConfig(trigger_bp=25.0,
                                                           roll_months=3), TAKER)
    assert led["n_hedges"].sum() > 0 and led["n_rolls"].sum() > 0  # both paths live
    pd.testing.assert_series_equal(led["cost"], -charge_usd(led, TAKER),
                                   check_names=False)


def test_the_ledger_cost_reprices_to_the_cost_table_at_one_times():
    ctx = SyntheticCtx(list(np.linspace(0, 100, 101)))
    res = run_pair(ctx, _signals(ctx.dates), rep_cfg=ReplicationConfig(trigger_bp=25.0),
                   costs=MAKER, pair_name="TEST")
    tbl = cost_table([res], schedule=MAKER)
    one_x = tbl[(tbl["cost_multiplier"] == 1.0) & tbl["roll_charged"]]["cost_usd"].iloc[0]
    assert one_x == pytest.approx(-res.ledger["cost"].sum(), rel=1e-9)


# ------------------------------------------- requirement 5: distinct episodes


def test_a_continuously_held_position_is_one_episode_not_sixty():
    """The trap: counting overlapping windows as independent trades."""
    ctx = SyntheticCtx(list(np.linspace(0, 40, 60)))
    res = run_pair(ctx, _signals(ctx.dates), rep_cfg=ReplicationConfig(),
                   costs=FREE, pair_name="TEST")
    assert len(res.trades) == 1
    assert res.stats["n_distinct_episodes"] == 1


def test_two_separated_holds_are_two_episodes():
    ctx = SyntheticCtx([0.0] * 60)
    sig = _signals(ctx.dates, sign=0, size=0.0)
    for lo, hi in ((5, 14), (30, 44)):
        sig.loc[ctx.dates[lo]:ctx.dates[hi], ["sign", "size", "dv01_usd"]] = [
            1, 1.0, 100_000.0]
    res = run_pair(ctx, sig, rep_cfg=ReplicationConfig(), costs=FREE, pair_name="TEST")
    assert res.stats["n_distinct_episodes"] == 2


def test_episodes_never_overlap_even_on_a_direct_sign_flip():
    ctx = SyntheticCtx(list(np.linspace(0, 40, 60)))
    sig = _signals(ctx.dates, sign=1, size=1.0)
    sig.loc[ctx.dates[30]:, ["sign", "dv01_usd"]] = [-1, -100_000.0]
    res = run_pair(ctx, sig, rep_cfg=ReplicationConfig(), costs=FREE, pair_name="TEST")
    t = res.trades.sort_values("entry")
    assert len(t) == 2
    assert t["exit"].iloc[0] < t["entry"].iloc[1]


def test_overlapping_episodes_are_rejected_outright():
    from RVUtils.StrikelessVol.backtest import _assert_disjoint

    good = [(pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-05"), 1),
            (pd.Timestamp("2026-01-06"), pd.Timestamp("2026-01-09"), 1)]
    _assert_disjoint(good)
    bad = [(pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-07"), 1),
           (pd.Timestamp("2026-01-05"), pd.Timestamp("2026-01-09"), 1)]
    with pytest.raises(ValueError, match="overlap"):
        _assert_disjoint(bad)


# --------------------------- requirement 1/3: causal betas and rolling-sigma z


def _factor_frame(n=900, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    vol = pd.Series(60.0 + np.cumsum(rng.normal(0, 0.4, n)), index=idx)
    spread = pd.Series(-1.5 * vol.to_numpy() + 120.0
                       + np.cumsum(rng.normal(0, 0.6, n)), index=idx)
    return spread, {"vol": vol}


def test_expanding_residual_is_causal_under_a_future_shock():
    spread, drivers = _factor_frame()

    def fit(y, x):
        return expanding_residual(y, x, min_periods=252).residual

    audit = audit_causal_betas(fit, spread, drivers)
    assert audit["causal"] is True
    assert audit["max_abs_diff"] < 1e-9
    assert audit["n_compared"] > 100


def test_the_causality_audit_catches_a_full_sample_fit():
    """Verify the checker against an input whose answer is already known."""
    spread, drivers = _factor_frame()

    def fit(y, x):
        return levels_regression(y, x).residuals

    audit = audit_causal_betas(fit, spread, drivers)
    assert audit["causal"] is False
    assert audit["max_abs_diff"] > 1.0


def test_rolling_sigma_z_audit_rejects_a_full_sample_sigma_z():
    spread, drivers = _factor_frame()
    fit = expanding_residual(spread, drivers, min_periods=252)
    resid = fit.residual
    from RVUtils.StrikelessVol.factors import residual_z

    good = audit_rolling_sigma_z(residual_z(resid), resid)
    assert good["rolling"] is True

    bad_z = (resid - resid.mean()) / resid.std(ddof=1)     # full-sample sigma
    bad = audit_rolling_sigma_z(bad_z, resid)
    assert bad["rolling"] is False


def _full_sample_fit(spread, drivers):
    """A `WalkForwardFit` carrying a FULL-SAMPLE residual and betas.

    Shaped exactly like the causal article so it is accepted structurally --
    which is the whole point: it must be rejected on the evidence, not on duck
    typing.
    """
    from RVUtils.StrikelessVol.factors import WalkForwardFit

    lev = levels_regression(spread, drivers)
    resid = lev.residuals.reindex(spread.index)
    betas = pd.DataFrame({"const": lev.intercept}, index=spread.index)
    for k in drivers:
        betas[k] = lev.betas[k]
    betas["vintage_date"] = spread.index[-1]
    return WalkForwardFit(residual=resid, betas=betas, min_periods=252)


def test_causal_signals_refuses_a_full_sample_fit():
    """C1: the audit must certify the ARTIFACT, not a re-derivation of it.

    Before this, passing a full-sample fit was stamped
    `expanding_betas=True, causal_max_abs_diff=0.0` and `run_pair` reported
    every requirement met but the placebo -- ~8.5bp/trade of look-ahead
    carrying the engine's own certificate.
    """
    spread, drivers = _factor_frame()
    panel = _panel_for(spread, drivers)
    with pytest.raises(ValueError, match="does not reproduce the audited causal fit"):
        causal_signals(panel, SignalConfig(), spread_bp=spread, drivers=drivers,
                       fit=_full_sample_fit(spread, drivers), min_periods=252)


def test_causal_signals_refuses_a_fit_built_with_different_parameters():
    spread, drivers = _factor_frame()
    panel = _panel_for(spread, drivers)
    mismatched = expanding_residual(spread, drivers, min_periods=300)
    with pytest.raises(ValueError, match="does not reproduce the audited causal fit"):
        causal_signals(panel, SignalConfig(), spread_bp=spread, drivers=drivers,
                       fit=mismatched, min_periods=252)


def test_the_fit_certification_numeric_leg_is_load_bearing():
    """The guard has two legs and the other two refusal tests both ride the
    NaN-pattern one, so `FIT_MATCH_TOL = 1e9` left the whole suite green.

    `refit_every=5` is the case the numeric leg exists for: identical defined
    dates, different values. Measured against the causal fit --

        candidate            same NaN pattern   max|diff|   leg tripped
        min_periods=300      False              0.0000      NaN-pattern only
        refit_every=5        True               0.3346      numeric only
        full-sample levels   False              6.9415      both
    """
    spread, drivers = _factor_frame()
    panel = _panel_for(spread, drivers)
    causal = expanding_residual(spread, drivers, min_periods=252).residual
    stale = expanding_residual(spread, drivers, min_periods=252,
                               refit_every=5).residual
    # the premise: same defined dates, materially different values
    assert (causal.isna() == stale.isna()).all()
    assert float((causal - stale).abs().max()) > 0.1

    with pytest.raises(ValueError, match="does not reproduce the audited causal fit"):
        causal_signals(panel, SignalConfig(), spread_bp=spread, drivers=drivers,
                       fit=expanding_residual(spread, drivers, min_periods=252,
                                              refit_every=5),
                       min_periods=252)


def test_causal_signals_accepts_a_matching_precomputed_fit():
    """The performance shortcut still works -- it just has to be the same fit."""
    spread, drivers = _factor_frame()
    panel = _panel_for(spread, drivers)
    fit = expanding_residual(spread, drivers, min_periods=252)
    reused = causal_signals(panel, SignalConfig(), spread_bp=spread,
                            drivers=drivers, fit=fit, min_periods=252)
    fresh = causal_signals(panel, SignalConfig(), spread_bp=spread,
                           drivers=drivers, min_periods=252)
    pd.testing.assert_frame_equal(reused, fresh)
    assert reused.attrs["expanding_betas"] is True


def test_a_non_causal_builder_is_refused_even_as_fit_fn():
    """The `fit_fn` shortcut cannot smuggle a non-causal fit past the gate."""
    spread, drivers = _factor_frame()
    panel = _panel_for(spread, drivers)

    def full_sample_builder(y, x):
        return _full_sample_fit(pd.Series(y), x)

    out = causal_signals(panel, SignalConfig(), spread_bp=spread, drivers=drivers,
                         fit_fn=full_sample_builder, min_periods=252)
    assert out.attrs["expanding_betas"] is False
    assert out.attrs["causal_max_abs_diff"] > 1.0
    assert out.attrs["rolling_sigma_z"] is False     # the z inherits the leak

    ctx = SyntheticCtx([0.0] * len(spread), start=spread.index[0])
    res = run_pair(ctx, out, rep_cfg=ReplicationConfig(), costs=FREE,
                   pair_name="TEST")
    assert res.requirements.expanding_betas is False
    assert res.requirements.rolling_sigma_z is False


def test_the_causality_audit_requires_the_shock_to_have_moved_the_tail():
    """An unmoved head is only evidence of causality if the shock moved
    ANYTHING. Pins the three-way separation, so a future change that weakens
    the requirement to `tail >= 0` shows up here."""
    spread, drivers = _factor_frame()

    constant = expanding_residual(spread, drivers, min_periods=252).residual
    memoised = audit_causal_betas(lambda y, x: constant, spread, drivers)
    assert memoised["tail_max_abs_diff"] == 0.0
    assert memoised["probe_reached"] is False
    assert memoised["max_abs_diff"] == 0.0      # the head IS still
    assert memoised["causal"] is False          # ... and that is not enough

    genuine = audit_causal_betas(
        lambda y, x: expanding_residual(y, x, min_periods=252).residual,
        spread, drivers)
    assert genuine["tail_max_abs_diff"] > 0.0
    assert genuine["causal"] is True

    honest_full_sample = audit_causal_betas(
        lambda y, x: levels_regression(y, x).residuals, spread, drivers)
    assert honest_full_sample["tail_max_abs_diff"] > 0.0   # probe landed
    assert honest_full_sample["causal"] is False           # head moved


def test_a_builder_constant_in_its_input_is_refused_by_causal_signals():
    """C1, second doorway: `fit_fn` is called three times per invocation, so a
    memoising closure is the natural response to its cost -- and a closure over
    a precomputed full-sample fit was certified `expanding_betas=True`."""
    spread, drivers = _factor_frame()
    panel = _panel_for(spread, drivers)
    precomputed = _full_sample_fit(spread, drivers)
    calls = {"n": 0}

    def memoised(y, x):
        calls["n"] += 1
        return precomputed                      # ignores y entirely

    with pytest.raises(ValueError, match="never reached it"):
        causal_signals(panel, SignalConfig(), spread_bp=spread, drivers=drivers,
                       fit_fn=memoised, min_periods=252)
    assert calls["n"] >= 2                      # it really was invoked


def _centred_window_betas(spread, drivers, win=126):
    """Betas at t fitted on [t-win, t+win]: textbook look-ahead, and TIME-VARYING,
    so the frozen-z deviation gate cannot incidentally block it."""
    idx, vol = spread.index, drivers["vol"]
    rows = {}
    for i, ts in enumerate(idx):
        lo, hi = max(0, i - win), min(len(idx), i + win + 1)
        if hi - lo < 60:
            continue
        A = np.column_stack([np.ones(hi - lo), vol.iloc[lo:hi].to_numpy()])
        c = np.linalg.lstsq(A, spread.iloc[lo:hi].to_numpy(), rcond=None)[0]
        rows[ts] = {"const": c[0], "vol": c[1], "vintage_date": ts}
    return pd.DataFrame.from_dict(rows, orient="index").reindex(idx)


def test_betas_must_reproduce_the_certified_residual():
    """Doorway C: `entry_vintage_signals` rebuilds the entry z and the frozen
    hold from `betas`, NOT from the residual `causal_signals` certifies.

    A fit carrying the genuine causal residual beside centred-window betas was
    granted requirements 1, 2 AND 3 -- with the hedge "frozen at entry vintage"
    frozen at a vintage that saw 126 days of the future.
    """
    from RVUtils.StrikelessVol.factors import WalkForwardFit

    spread, drivers = _factor_frame()
    panel = _panel_for(spread, drivers)
    honest = expanding_residual(spread, drivers, min_periods=252)

    leaky = WalkForwardFit(residual=honest.residual,
                           betas=_centred_window_betas(spread, drivers),
                           min_periods=252)
    with pytest.raises(ValueError, match="does not reproduce"):
        causal_signals(panel, SignalConfig(), spread_bp=spread, drivers=drivers,
                       fit=leaky, min_periods=252)


def test_full_sample_betas_beside_a_causal_residual_are_refused():
    """Doorway B, the weaker form: every position would claim a vintage dated
    the last day of the sample. It was blocked only incidentally before, by the
    deviation gate firing because constant betas make frozen z == live z."""
    from RVUtils.StrikelessVol.factors import WalkForwardFit

    spread, drivers = _factor_frame()
    panel = _panel_for(spread, drivers)
    honest = expanding_residual(spread, drivers, min_periods=252)
    lev = levels_regression(spread, drivers)
    betas = pd.DataFrame({"const": lev.intercept, "vol": lev.betas["vol"]},
                         index=spread.index)
    betas["vintage_date"] = spread.index[-1]

    with pytest.raises(ValueError, match="does not reproduce"):
        causal_signals(panel, SignalConfig(), spread_bp=spread, drivers=drivers,
                       fit=WalkForwardFit(residual=honest.residual, betas=betas,
                                          min_periods=252),
                       min_periods=252)


def test_betas_missing_where_the_residual_is_defined_are_refused():
    """The consistency check has a coverage leg as well as a numeric one: betas
    that are absent on dates the residual covers would silently produce a NaN
    entry z on exactly those dates, and the value comparison cannot see it
    because it runs on the overlap."""
    from RVUtils.StrikelessVol.factors import WalkForwardFit

    spread, drivers = _factor_frame()
    panel = _panel_for(spread, drivers)
    honest = expanding_residual(spread, drivers, min_periods=252)
    holed = honest.betas.copy()
    dated = honest.residual.dropna().index
    holed.loc[dated[50:120], ["const", "vol"]] = np.nan
    # the premise: values still agree wherever both are defined
    assert holed.loc[dated, ["const", "vol"]].isna().any(axis=1).sum() == 70

    with pytest.raises(ValueError, match="does not reproduce"):
        causal_signals(panel, SignalConfig(), spread_bp=spread, drivers=drivers,
                       fit=WalkForwardFit(residual=honest.residual, betas=holed,
                                          min_periods=252),
                       min_periods=252)


def _leaky_frozen_builder(spread, drivers):
    """Doorway A: a pure pointwise transform of y with FULL-SAMPLE coefficients
    baked in before the builder is ever called. Plausible as an accident --
    "I already have the betas, just apply them"."""
    from RVUtils.StrikelessVol.factors import WalkForwardFit

    lev = levels_regression(spread, drivers)
    c0, b0 = float(lev.intercept), float(lev.betas["vol"])

    def builder(y, x):
        resid = pd.Series(y).astype(float) - (c0 + b0 * x["vol"])
        betas = pd.DataFrame({"const": c0, "vol": b0}, index=resid.index)
        betas["vintage_date"] = resid.index[-1]
        return WalkForwardFit(residual=resid, betas=betas, min_periods=252)

    return builder


def test_a_frozen_coefficient_builder_fails_the_head_shock_probe():
    """Doorway A passes both earlier legs -- still head, moved tail -- yet its
    residual is bit-identical to a full-sample one. Shocking the HEAD and
    requiring the TAIL to respond separates it: a genuinely refitting builder
    must change its later coefficients, a frozen-coefficient one cannot."""
    spread, drivers = _factor_frame()
    builder = _leaky_frozen_builder(spread, drivers)

    leaky = audit_causal_betas(lambda y, x: builder(y, x).residual, spread, drivers)
    assert leaky["max_abs_diff"] == pytest.approx(0.0)       # head still ...
    assert leaky["tail_max_abs_diff"] > 0.0                  # ... tail moved ...
    assert leaky["probe_reached"] is True                    # ... probe landed
    assert leaky["head_shock_tail_response"] == 0.0          # but no history
    assert leaky["responds_to_history"] is False
    assert leaky["causal"] is False

    # its residual really is the full-sample one, which is the point
    full = levels_regression(spread, drivers).residuals.reindex(spread.index)
    assert float((builder(spread, drivers).residual - full).abs().max()) < 1e-9

    # both legitimate builders respond to their own history
    for fn in (lambda y, x: expanding_residual(y, x, min_periods=252).residual,
               lambda y, x: levels_regression(y, x).residuals):
        assert audit_causal_betas(fn, spread, drivers)["head_shock_tail_response"] > 0.0


def test_a_frozen_coefficient_builder_is_not_certified_by_causal_signals():
    spread, drivers = _factor_frame()
    panel = _panel_for(spread, drivers)
    out = causal_signals(panel, SignalConfig(), spread_bp=spread, drivers=drivers,
                         fit_fn=_leaky_frozen_builder(spread, drivers),
                         min_periods=252)
    assert out.attrs["expanding_betas"] is False
    # requirement 3 inherits requirement 1's verdict: a trailing-sigma z of a
    # leaking residual is still a z of a leaking residual
    assert out.attrs["rolling_sigma_z"] is False


def test_causal_signals_stamps_verified_provenance():
    spread, drivers = _factor_frame()
    panel = _panel_for(spread, drivers)
    sig = causal_signals(panel, SignalConfig(), spread_bp=spread, drivers=drivers,
                         min_periods=252)
    assert sig.attrs["expanding_betas"] is True
    assert sig.attrs["rolling_sigma_z"] is True
    assert sig.attrs["entry_vintage_hedge"] is True
    assert "beta_vintage_date" in sig.columns


def test_the_certificate_carries_the_number_for_every_leg_it_asserts():
    """`expanding_betas` is a conjunction of three measurements plus a betas
    check, and stamping only the head-shock number let a fit that failed a
    DIFFERENT leg carry `causal_max_abs_diff: 0.0` -- which reads as a clean
    pass. The frozen-coefficient builder is exactly that case: its head really
    does not move under a future shock; it fails because its tail does not
    respond to its own history."""
    spread, drivers = _factor_frame()
    panel = _panel_for(spread, drivers)

    honest = causal_signals(panel, SignalConfig(), spread_bp=spread,
                            drivers=drivers, min_periods=252)
    leaky = causal_signals(panel, SignalConfig(), spread_bp=spread, drivers=drivers,
                           fit_fn=_leaky_frozen_builder(spread, drivers),
                           min_periods=252)

    for attrs in (honest.attrs, leaky.attrs):
        for key in ("causal_max_abs_diff", "causal_probe_reached",
                    "causal_tail_max_abs_diff", "causal_responds_to_history",
                    "causal_head_shock_tail_response",
                    "betas_reproduce_residual_max_abs_diff"):
            assert key in attrs, f"{key} is asserted but never stamped"

    # The failing leg is identifiable FROM THE CERTIFICATE, not just from the flag.
    assert leaky.attrs["expanding_betas"] is False
    assert leaky.attrs["causal_max_abs_diff"] == pytest.approx(0.0)   # looks clean
    assert leaky.attrs["causal_probe_reached"] is True
    assert leaky.attrs["causal_responds_to_history"] is False          # the real cause
    assert leaky.attrs["causal_head_shock_tail_response"] == 0.0

    assert honest.attrs["causal_responds_to_history"] is True
    assert honest.attrs["causal_head_shock_tail_response"] > 0.0
    assert honest.attrs["causal_tail_max_abs_diff"] > 0.0
    assert honest.attrs["betas_reproduce_residual_max_abs_diff"] == pytest.approx(
        0.0, abs=1e-9)


def _panel_for(spread, drivers):
    idx = spread.index
    return pd.DataFrame(
        {
            "be_over_realized": 0.7,
            "drift_t": 0.0,
            "residual_z": 0.0,          # replaced by causal_signals
            "spread_vol_bp_day": 1.32,
            "iv_z": 0.0,
        },
        index=idx,
    )


# ------------------- the OTHER four signal inputs `residual_z` does not cover


def _drift_t_from(changes_resid, window=63):
    from RVUtils.StrikelessVol.factors import drift
    return drift(changes_resid, window=window)["t_stat"]


def test_a_certified_residual_z_does_not_certify_the_signal():
    """`signal_state` reads five columns. The certificate must say which of them
    it actually covers, because four passes of this module attached the
    certificate to something adjacent to the object the signal is built from."""
    spread, drivers = _factor_frame()
    sig = causal_signals(_panel_for(spread, drivers), SignalConfig(),
                         spread_bp=spread, drivers=drivers, min_periods=252)
    assert sig.attrs["certified_signal_inputs"] == ("residual_z",)
    assert set(sig.attrs["uncertified_signal_inputs"]) == {
        "be_over_realized", "drift_t", "spread_vol_bp_day", "iv_z", "drivers"}


def test_supplying_only_the_sources_certifies_the_transform_and_says_so():
    """A source with no builder certifies the TRANSFORM and nothing more.

    This is the honesty half of the amendment. The fact is real -- `drift_t`
    IS a trailing 63-day NW-t of the series it was handed -- but the series
    itself is unaudited, and a leaky source reproduces its own transform
    perfectly. So the certificate must name what it covers (`drift_t(source
    uncertified)`) and name the source among what it does not.
    """
    spread, drivers = _factor_frame()
    rng = np.random.default_rng(11)
    changes_resid = pd.Series(rng.normal(0, 1.0, len(spread)), index=spread.index)
    iv = pd.Series(60.0 + np.cumsum(rng.normal(0, 0.4, len(spread))),
                   index=spread.index)

    panel = _panel_for(spread, drivers)
    panel["drift_t"] = _drift_t_from(changes_resid)
    panel["iv_z"] = residual_z(iv, window=252, min_periods=126)

    sig = causal_signals(panel, SignalConfig(), spread_bp=spread, drivers=drivers,
                         min_periods=252, changes_resid=changes_resid,
                         iv_bp_day=iv)
    assert set(sig.attrs["certified_signal_inputs"]) == {
        "residual_z", "drift_t(source uncertified)", "iv_z(source uncertified)"}
    # the bare column names must NOT appear -- that is the over-read
    assert "drift_t" not in sig.attrs["certified_signal_inputs"]
    assert "iv_z" not in sig.attrs["certified_signal_inputs"]
    assert set(sig.attrs["uncertified_signal_inputs"]) == {
        "be_over_realized", "spread_vol_bp_day", "drivers",
        "changes_resid", "iv_bp_day"}
    assert sig.attrs["drift_t_max_abs_diff"] == pytest.approx(0.0, abs=1e-8)
    assert sig.attrs["iv_z_max_abs_diff"] == pytest.approx(0.0, abs=1e-8)
    # `*_max_abs_diff` is <= tol by construction (a mismatch raises), so the
    # number that can actually carry evidence is the count.
    assert sig.attrs["drift_t_n_compared"] > 100
    assert sig.attrs["iv_z_n_compared"] > 100


# ---------------- the HIGH finding: certifying the transform is not enough


def _changes_builder(min_periods=252):
    return lambda y, x: expanding_changes_residual(
        y, x, min_periods=min_periods).residual


def _leaky_changes_builder():
    """The repo's ONLY changes-regression builder before this fix: full sample."""
    return lambda y, x: changes_regression(y, x).residuals


def test_the_walk_forward_changes_residual_is_causal_and_the_full_sample_one_is_not():
    """Verify the source probe against inputs whose answers are already known.

    `factors.changes_regression` fits one set of betas on the whole sample, so
    shocking the last 25% of the spread moves the FIRST 75% of its residual --
    and the `drift_t` built on it moves 6.1 t-units in that head, against a
    veto gate of 2.0.
    """
    spread, drivers = _factor_frame()

    honest = audit_causal_betas(_changes_builder(), spread, drivers)
    assert honest["causal"] is True
    assert honest["max_abs_diff"] == 0.0
    assert honest["probe_reached"] is True
    assert honest["responds_to_history"] is True
    assert honest["n_compared"] > 100

    leaky = audit_causal_betas(_leaky_changes_builder(), spread, drivers)
    assert leaky["causal"] is False
    assert leaky["max_abs_diff"] > 1.0        # measured 2.628

    # ... and what that is worth where it is READ: the veto column itself.
    from RVUtils.StrikelessVol.factors import drift as _drift
    cut = int(len(spread) * 0.75)
    shocked = spread.copy()
    shocked.iloc[cut:] = shocked.iloc[cut:] + 250.0
    head = spread.index[:cut]
    base_t = _drift(_leaky_changes_builder()(spread, drivers))["t_stat"]
    sh_t = _drift(_leaky_changes_builder()(shocked, drivers))["t_stat"]
    pair = pd.concat([base_t.reindex(head).rename("a"),
                      sh_t.reindex(head).rename("b")], axis=1).dropna()
    assert float((pair["a"] - pair["b"]).abs().max()) > 2.0   # the veto gate


def test_expanding_changes_residual_is_a_changes_fit_not_a_levels_one():
    """Pin the arithmetic, not just the causality: the residual at t is dy_t
    minus the prediction of an OLS fitted on rows STRICTLY BEFORE t, with BOTH
    sides differenced. A builder that forgot to difference one side would still
    be causal, and every causality test would still pass."""
    spread, drivers = _factor_frame(n=400)
    fit = expanding_changes_residual(spread, drivers, min_periods=100)
    dy, dx = spread.diff(), drivers["vol"].diff()

    i = 300
    ts = spread.index[i]
    hist = pd.concat([dy.rename("y"), dx.rename("x")], axis=1).iloc[:i].dropna()
    A = np.column_stack([np.ones(len(hist)), hist["x"].to_numpy()])
    coef = np.linalg.lstsq(A, hist["y"].to_numpy(), rcond=None)[0]
    expected = float(dy.loc[ts]) - (coef[0] + coef[1] * float(dx.loc[ts]))
    assert float(fit.residual.loc[ts]) == pytest.approx(expected, abs=1e-12)

    # the planted relation is in LEVELS, so the two fits are different objects
    levels = expanding_residual(spread, drivers, min_periods=100).residual
    assert float((fit.residual - levels).abs().max()) > 1.0
    assert fit.kind == "expanding_changes"
    assert fit.residual.iloc[:100].isna().all()      # warmup, not back-filled


def test_a_full_sample_changes_residual_source_is_refused_by_causal_signals():
    """THE finding. The transform leg alone accepts this at 0.0 -- so the test
    first proves the old check passes it, then that the new one does not."""
    spread, drivers = _factor_frame()
    leaky = _leaky_changes_builder()(spread, drivers)

    panel = _panel_for(spread, drivers)
    panel["drift_t"] = _drift_t_from(leaky)

    # premise: the column IS the declared trailing statistic of that source,
    # to float zero, over hundreds of dates. Leg 1 cannot see the hazard.
    transform_only = audit_trailing_statistic(
        panel["drift_t"], leaky, label="drift_t",
        recompute=lambda s: _drift_t_from(s))
    assert transform_only["matched"] is True
    assert transform_only["max_abs_diff"] == pytest.approx(0.0, abs=1e-9)
    assert transform_only["source_causal"] is None      # nothing was asked
    assert transform_only["certified"] is False

    with pytest.raises(ValueError, match="changes_resid_fn` is not causal"):
        causal_signals(panel, SignalConfig(), spread_bp=spread, drivers=drivers,
                       min_periods=252, changes_resid=leaky,
                       changes_resid_fn=_leaky_changes_builder())


def test_a_walk_forward_changes_residual_source_is_certified():
    """The honest counterpart, so the refusal above is not simply 'refuses
    everything' -- the trap in a source check is that both builders pass."""
    spread, drivers = _factor_frame()
    resid = expanding_changes_residual(spread, drivers, min_periods=252).residual

    panel = _panel_for(spread, drivers)
    panel["drift_t"] = _drift_t_from(resid)

    sig = causal_signals(panel, SignalConfig(), spread_bp=spread, drivers=drivers,
                         min_periods=252, changes_resid=resid,
                         changes_resid_fn=_changes_builder())
    assert set(sig.attrs["certified_signal_inputs"]) == {
        "residual_z", "drift_t", "changes_resid"}
    assert "drift_t" not in sig.attrs["uncertified_signal_inputs"]
    assert "changes_resid" not in sig.attrs["uncertified_signal_inputs"]
    # certifying the SOURCE's builder does not certify the drivers it regresses
    # on: `audit_causal_betas` shocks only the dependent variable.
    assert "drivers" in sig.attrs["uncertified_signal_inputs"]
    assert sig.attrs["changes_resid_causal_max_abs_diff"] == 0.0
    assert sig.attrs["changes_resid_artifact_max_abs_diff"] == pytest.approx(
        0.0, abs=1e-9)


def test_an_honest_builder_beside_a_leaky_series_is_refused():
    """The same defect one level down: audit a builder, then build the signal
    from a different object. That is how `fit=` leaked in the first place."""
    spread, drivers = _factor_frame()
    leaky = _leaky_changes_builder()(spread, drivers)

    panel = _panel_for(spread, drivers)
    panel["drift_t"] = _drift_t_from(leaky)

    with pytest.raises(ValueError, match="is not what `changes_resid_fn` produces"):
        causal_signals(panel, SignalConfig(), spread_bp=spread, drivers=drivers,
                       min_periods=252, changes_resid=leaky,
                       changes_resid_fn=_changes_builder())     # honest builder


def test_a_back_filled_source_is_not_the_builders_output():
    """The same accident as the back-filled COLUMN, one level up on the SOURCE.

    Every numeric leg agrees: the two series are identical wherever the builder
    defines anything, and the transform reproduces to float zero. What differs
    is which dates are defined -- so the `drift_t` built on it starts 250 days
    early, on residuals that were invented by `bfill`. Only the NaN-pattern leg
    of the artifact tie sees it.
    """
    spread, drivers = _factor_frame()
    honest = expanding_changes_residual(spread, drivers, min_periods=252).residual
    filled = honest.bfill()

    assert honest.isna().sum() > 200 and filled.isna().sum() == 0
    assert float((filled - honest).abs().max()) == 0.0   # nothing numeric to see

    panel = _panel_for(spread, drivers)
    panel["drift_t"] = _drift_t_from(filled)

    with pytest.raises(ValueError, match="is not what `changes_resid_fn` produces"):
        causal_signals(panel, SignalConfig(), spread_bp=spread, drivers=drivers,
                       min_periods=252, changes_resid=filled,
                       changes_resid_fn=_changes_builder())


def test_a_smoothed_iv_source_is_refused_once_its_builder_is_probed():
    """`iv_z`'s milder form. Leg 1 catches a full-sample sigma because the raw
    vol series is an observable; it cannot catch a CENTRED-window smoothing of
    that observable, which is a realistic 'clean up the series' step."""
    spread, drivers = _factor_frame()
    rng = np.random.default_rng(31)
    raw_iv = pd.Series(60.0 + np.cumsum(rng.normal(0, 0.4, len(spread))),
                       index=spread.index)

    def centred(y, _drivers):
        return pd.Series(y).rolling(21, center=True, min_periods=1).mean()

    smoothed = centred(raw_iv, {})
    panel = _panel_for(spread, drivers)
    panel["iv_z"] = residual_z(smoothed, window=252, min_periods=126)

    # premise: leg 1 certifies the smoothed series at float zero
    transform_only = audit_trailing_statistic(
        panel["iv_z"], smoothed, label="iv_z",
        recompute=lambda s: residual_z(s, window=252, min_periods=126))
    assert transform_only["matched"] is True
    assert transform_only["max_abs_diff"] == pytest.approx(0.0, abs=1e-12)

    with pytest.raises(ValueError, match="iv_bp_day_fn` is not causal"):
        causal_signals(panel, SignalConfig(), spread_bp=spread, drivers=drivers,
                       min_periods=252, iv_bp_day=smoothed,
                       iv_bp_day_fn=centred, iv_bp_day_source=raw_iv)

    # and the honest counterpart -- a TRAILING smoother -- is certified
    def trailing(y, _drivers):
        return pd.Series(y).rolling(21, min_periods=1).mean()

    clean = trailing(raw_iv, {})
    panel2 = _panel_for(spread, drivers)
    panel2["iv_z"] = residual_z(clean, window=252, min_periods=126)
    sig = causal_signals(panel2, SignalConfig(), spread_bp=spread, drivers=drivers,
                         min_periods=252, iv_bp_day=clean,
                         iv_bp_day_fn=trailing, iv_bp_day_source=raw_iv)
    assert set(sig.attrs["certified_signal_inputs"]) == {
        "residual_z", "iv_z", "iv_bp_day"}


@pytest.mark.parametrize("kw", ["changes_resid_fn", "iv_bp_day_fn"])
def test_a_builder_without_its_series_is_not_silently_ignored(kw):
    """An argument that reads as 'I certified the source' and does nothing is
    this module's failure mode in miniature."""
    spread, drivers = _factor_frame()
    panel = _panel_for(spread, drivers)
    with pytest.raises(ValueError, match="without"):
        causal_signals(panel, SignalConfig(), spread_bp=spread, drivers=drivers,
                       min_periods=252, **{kw: lambda y, d: pd.Series(y)})


def test_a_pointwise_source_builder_is_refused_but_not_called_non_causal():
    """The identity is perfectly causal and still cannot pass a probe whose
    third leg asks whether the fit responds to its own history. Refusing it is
    right (the same shape is a frozen-coefficient fit, which is a full-sample
    residual in disguise); calling it "not causal" would not be."""
    spread, drivers = _factor_frame()
    rng = np.random.default_rng(33)
    iv = pd.Series(60.0 + np.cumsum(rng.normal(0, 0.4, len(spread))),
                   index=spread.index)
    panel = _panel_for(spread, drivers)
    panel["iv_z"] = residual_z(iv, window=252, min_periods=126)

    with pytest.raises(ValueError, match="POINTWISE transform of its input"):
        causal_signals(panel, SignalConfig(), spread_bp=spread, drivers=drivers,
                       min_periods=252, iv_bp_day=iv,
                       iv_bp_day_fn=lambda y, d: pd.Series(y), iv_bp_day_source=iv)

    # and the honest route for a raw observable: no builder, transform certified
    sig = causal_signals(panel, SignalConfig(), spread_bp=spread, drivers=drivers,
                         min_periods=252, iv_bp_day=iv)
    assert "iv_z(source uncertified)" in sig.attrs["certified_signal_inputs"]


def test_a_source_builder_without_its_input_is_refused():
    spread, drivers = _factor_frame()
    rng = np.random.default_rng(32)
    iv = pd.Series(60.0 + np.cumsum(rng.normal(0, 0.4, len(spread))),
                   index=spread.index)
    panel = _panel_for(spread, drivers)
    panel["iv_z"] = residual_z(iv, window=252, min_periods=126)
    with pytest.raises(ValueError, match="needs `iv_bp_day_source"):
        causal_signals(panel, SignalConfig(), spread_bp=spread, drivers=drivers,
                       min_periods=252, iv_bp_day=iv,
                       iv_bp_day_fn=lambda y, d: pd.Series(y))


def test_the_trailing_statistic_tolerance_is_tight():
    """`tol` could go 1e-8 -> 0.7 with zero test failures: the smallest
    mismatch any other test exercises is 0.676, so nothing separated 'this IS
    the declared statistic' from 'this is roughly it'."""
    spread, _drivers = _factor_frame()
    rng = np.random.default_rng(21)
    src = pd.Series(rng.normal(0, 1.0, len(spread)), index=spread.index)
    honest = _drift_t_from(src)
    recompute = _drift_t_from

    exact = audit_trailing_statistic(honest, src, recompute=recompute,
                                     label="drift_t")
    assert exact["matched"] is True

    noise = audit_trailing_statistic(honest + 1e-9, src, recompute=recompute,
                                     label="drift_t")
    assert noise["matched"] is True          # float noise is not a mismatch

    tiny = audit_trailing_statistic(honest + 1e-7, src, recompute=recompute,
                                    label="drift_t")
    assert tiny["matched"] is False          # ... and 1e-7 already is one
    assert tiny["max_abs_diff"] == pytest.approx(1e-7, rel=1e-3)


def test_a_source_on_the_wrong_index_is_refused_not_silently_matched():
    """Empty overlap is not agreement. A bare numpy array -- the natural way to
    lose a DatetimeIndex -- compares on zero dates."""
    spread, _drivers = _factor_frame()
    rng = np.random.default_rng(22)
    src = pd.Series(rng.normal(0, 1.0, len(spread)), index=spread.index)
    audit = audit_trailing_statistic(_drift_t_from(src), src.to_numpy(),
                                     recompute=_drift_t_from, label="drift_t")
    assert audit["n_compared"] == 0
    assert audit["matched"] is False
    assert audit["certified"] is False


def test_dates_infinite_on_both_sides_do_not_shrink_the_comparison():
    """`inf - inf` is NaN and `.max()` skips NaN, so those dates contributed
    nothing to the maximum while still being counted as compared."""
    idx = pd.bdate_range("2020-01-01", periods=10)
    got = pd.Series([np.inf] * 5 + [1.0] * 5, index=idx)
    audit = audit_trailing_statistic(got, got, recompute=lambda s: s,
                                     label="probe")
    assert audit["n_compared"] == 10
    assert audit["n_differenced"] == 5
    assert audit["matched"] is False


def test_a_column_defined_on_a_single_date_is_not_certified():
    """`max_abs_diff = 0.0` over ONE observation is not a certificate."""
    spread, drivers = _factor_frame()
    rng = np.random.default_rng(23)
    src = pd.Series(rng.normal(0, 1.0, len(spread)), index=spread.index)
    honest = _drift_t_from(src)
    last = honest.dropna().index[-1]
    sparse = honest.where(honest.index == last)

    # premise: every other leg passes it
    audit = audit_trailing_statistic(sparse, src, recompute=_drift_t_from,
                                     label="drift_t")
    assert audit["matched"] is True and audit["n_compared"] == 1

    panel = _panel_for(spread, drivers)
    panel["drift_t"] = sparse
    with pytest.raises(ValueError, match="compared on only 1 dates"):
        causal_signals(panel, SignalConfig(), spread_bp=spread, drivers=drivers,
                       min_periods=252, changes_resid=src)


def test_a_source_for_a_column_the_panel_does_not_have_says_so():
    spread, drivers = _factor_frame()
    rng = np.random.default_rng(24)
    src = pd.Series(rng.normal(0, 1.0, len(spread)), index=spread.index)
    panel = _panel_for(spread, drivers).drop(columns=["drift_t"])
    with pytest.raises(ValueError, match="no `drift_t` column to certify"):
        causal_signals(panel, SignalConfig(), spread_bp=spread, drivers=drivers,
                       min_periods=252, changes_resid=src)


def test_a_full_sample_iv_z_is_refused():
    """A z on a full-sample sigma is exactly the look-ahead requirement 3
    refuses -- one column across. It must not survive by living in `iv_z`."""
    spread, drivers = _factor_frame()
    rng = np.random.default_rng(12)
    iv = pd.Series(60.0 + np.cumsum(rng.normal(0, 0.4, len(spread))),
                   index=spread.index)

    panel = _panel_for(spread, drivers)
    panel["iv_z"] = (iv - iv.mean()) / iv.std(ddof=1)      # full-sample z

    with pytest.raises(ValueError, match="iv_z"):
        causal_signals(panel, SignalConfig(), spread_bp=spread, drivers=drivers,
                       min_periods=252, iv_bp_day=iv)


def test_a_drift_t_from_the_wrong_residual_is_refused():
    spread, drivers = _factor_frame()
    rng = np.random.default_rng(13)
    honest_resid = pd.Series(rng.normal(0, 1.0, len(spread)), index=spread.index)
    other_resid = pd.Series(rng.normal(0, 1.0, len(spread)), index=spread.index)

    panel = _panel_for(spread, drivers)
    panel["drift_t"] = _drift_t_from(other_resid)          # not what we declare

    with pytest.raises(ValueError, match="drift_t"):
        causal_signals(panel, SignalConfig(), spread_bp=spread, drivers=drivers,
                       min_periods=252, changes_resid=honest_resid)


def test_a_backfilled_warmup_is_refused_even_though_it_agrees_where_both_exist():
    """The realistic accident: someone back-fills the warmup so the column has
    no NaNs. Every date the recomputation defines agrees to float zero, so an
    overlap-only check passes it -- while the first 62 days carry a statistic
    the trade date could not have computed."""
    spread, drivers = _factor_frame()
    rng = np.random.default_rng(15)
    changes_resid = pd.Series(rng.normal(0, 1.0, len(spread)), index=spread.index)

    panel = _panel_for(spread, drivers)
    honest = _drift_t_from(changes_resid)
    panel["drift_t"] = honest.bfill()
    assert honest.isna().sum() > 0 and panel["drift_t"].isna().sum() == 0

    with pytest.raises(ValueError, match="drift_t"):
        causal_signals(panel, SignalConfig(), spread_bp=spread, drivers=drivers,
                       min_periods=252, changes_resid=changes_resid)


def test_a_longer_drift_window_is_refused_as_a_different_statistic():
    """Right source, wrong window: the column is a trailing statistic, just not
    the declared one. A check that only asked 'is it trailing?' would pass it."""
    spread, drivers = _factor_frame()
    rng = np.random.default_rng(14)
    changes_resid = pd.Series(rng.normal(0, 1.0, len(spread)), index=spread.index)

    panel = _panel_for(spread, drivers)
    panel["drift_t"] = _drift_t_from(changes_resid, window=126)

    with pytest.raises(ValueError, match="drift_t"):
        causal_signals(panel, SignalConfig(), spread_bp=spread, drivers=drivers,
                       min_periods=252, changes_resid=changes_resid,
                       drift_window=63)


# ----------------------------- requirement 2: the hedge frozen at entry vintage


def test_entry_vintage_signals_hold_one_beta_vintage_per_episode():
    spread, drivers = _factor_frame()
    panel = _panel_for(spread, drivers)
    fit = expanding_residual(spread, drivers, min_periods=252)
    out = entry_vintage_signals(panel, SignalConfig(z_entry=1.0), spread_bp=spread,
                                drivers=drivers, betas=fit.betas)
    held = out[out["sign"] != 0]
    assert len(held) > 20
    for _, block in held.groupby((out["sign"] != out["sign"].shift()).cumsum()):
        assert block["beta_vintage_date"].nunique() == 1


def test_the_hold_is_priced_on_the_entry_vintage_z_not_the_live_z():
    """Pins the FORMULA, not just the label: mid-hold size must be the size the
    entry-date beta implies, and that must differ from the live-beta size."""
    from RVUtils.StrikelessVol.factors import residual_z
    from RVUtils.StrikelessVol.strategy import signal_state

    spread, drivers = _factor_frame()
    panel = _panel_for(spread, drivers)
    cfg = SignalConfig(z_entry=1.0)
    fit = expanding_residual(spread, drivers, min_periods=252)
    out = entry_vintage_signals(panel, cfg, spread_bp=spread, drivers=drivers,
                                betas=fit.betas)

    block_id = (out["sign"] != out["sign"].shift()).cumsum()
    long_block = None
    for _, blk in out[out["sign"] != 0].groupby(block_id):
        if len(blk) >= 6:
            long_block = blk
            break
    assert long_block is not None, "need one episode at least 6 days long"

    entry, ts = long_block.index[0], long_block.index[5]
    b = fit.betas.loc[entry]
    frozen_resid = spread - (float(b["const"]) + float(b["vol"]) * drivers["vol"])
    z_frozen = float(residual_z(frozen_resid).shift(1).loc[ts])
    z_live = float(residual_z(fit.residual).shift(1).loc[ts])
    assert z_frozen != pytest.approx(z_live, abs=1e-6)

    row = panel.shift(1).loc[ts].copy()
    row["residual_z"] = z_frozen
    assert out.at[ts, "size"] == pytest.approx(signal_state(row, cfg)["size"])


def test_re_estimating_during_the_hold_changes_the_result():
    """If the frozen beta made no difference, requirement 2 would be untestable."""
    spread, drivers = _factor_frame()
    panel = _panel_for(spread, drivers)
    fit = expanding_residual(spread, drivers, min_periods=252)
    frozen = entry_vintage_signals(panel, SignalConfig(z_entry=1.0), spread_bp=spread,
                                   drivers=drivers, betas=fit.betas)
    from RVUtils.StrikelessVol.factors import residual_z
    from RVUtils.StrikelessVol.strategy import build_signals

    live = panel.copy()
    live["residual_z"] = residual_z(fit.residual)
    rehedged = build_signals(live, SignalConfig(z_entry=1.0))
    assert not frozen["dv01_usd"].equals(rehedged["dv01_usd"])


def test_a_claimed_flag_without_evidence_does_not_open_the_gate():
    """attrs are a claim; the audit's own number is the evidence.

    A caller who stamps ``expanding_betas=True`` with no measured causality gap
    -- or with a gap that failed -- gets no credit for requirements 1 or 3.
    """
    ctx = SyntheticCtx(list(np.linspace(0, 40, 60)))
    forged = _signals(ctx.dates)
    forged.attrs.update({"expanding_betas": True, "rolling_sigma_z": True})
    res = run_pair(ctx, forged, rep_cfg=ReplicationConfig(), costs=FREE,
                   pair_name="TEST")
    assert res.requirements.expanding_betas is False
    assert res.requirements.rolling_sigma_z is False

    failed = _signals(ctx.dates)
    failed.attrs.update({"expanding_betas": True, "causal_max_abs_diff": 3.7,
                         "rolling_sigma_z": True, "rolling_z_max_abs_diff": 1.1})
    res2 = run_pair(ctx, failed, rep_cfg=ReplicationConfig(), costs=FREE,
                    pair_name="TEST")
    assert res2.requirements.expanding_betas is False
    assert res2.requirements.rolling_sigma_z is False

    passed = _signals(ctx.dates)
    passed.attrs.update(_causal_evidence())
    res3 = run_pair(ctx, passed, rep_cfg=ReplicationConfig(), costs=FREE,
                    pair_name="TEST")
    assert res3.requirements.expanding_betas is True
    assert res3.requirements.rolling_sigma_z is True


def _causal_evidence(**over):
    """The full set of numbers `causal_signals` stamps for requirements 1 and 3."""
    ev = {"expanding_betas": True, "causal_max_abs_diff": 0.0,
          "causal_probe_reached": True, "causal_tail_max_abs_diff": 250.0,
          "causal_responds_to_history": True,
          "causal_head_shock_tail_response": 216.0,
          "betas_reproduce_residual_max_abs_diff": 0.0,
          "rolling_sigma_z": True, "rolling_z_max_abs_diff": 0.0}
    ev.update(over)
    return ev


@pytest.mark.parametrize(
    "broken, why",
    [
        ({"causal_probe_reached": False}, "the shock never reached the builder"),
        ({"causal_tail_max_abs_diff": 0.0}, "nothing moved, so nothing was tested"),
        ({"causal_responds_to_history": False}, "frozen coefficients"),
        ({"causal_head_shock_tail_response": 0.0}, "frozen coefficients, measured"),
        ({"betas_reproduce_residual_max_abs_diff": 15.3}, "centred betas"),
        ({"causal_probe_reached": None}, "stamp absent, not merely false"),
        ({"betas_reproduce_residual_max_abs_diff": float("nan")}, "no number at all"),
    ],
)
def test_every_stamped_number_the_certificate_asserts_is_required(broken, why):
    """Stamping the numbers is worth nothing if the gate reads only the flag.

    Measured before this: an `attrs` claiming `causal_probe_reached=False`,
    `causal_responds_to_history=False` and a betas gap of 15.3 still returned
    `expanding_betas=True`, because `_derive_requirements` consulted one of the
    six numbers `causal_signals` stamps. That frame is reachable without hand
    editing -- `run_grid`'s prebuilt-signals path passes the caller's attrs
    straight through.
    """
    ctx = SyntheticCtx(list(np.linspace(0, 40, 60)))
    sig = _signals(ctx.dates)
    ev = _causal_evidence()
    for k, v in broken.items():
        if v is None:
            ev.pop(k)
        else:
            ev[k] = v
    sig.attrs.update(ev)
    res = run_pair(ctx, sig, rep_cfg=ReplicationConfig(), costs=FREE,
                   pair_name="TEST")
    assert res.requirements.expanding_betas is False, why
    # requirement 3's substance is a trailing z OF A CAUSAL RESIDUAL, so it
    # inherits requirement 1's verdict in the gate as well as in the stamp
    assert res.requirements.rolling_sigma_z is False, why


def test_run_pair_marks_entry_vintage_unmet_when_the_column_is_absent():
    ctx = SyntheticCtx(list(np.linspace(0, 40, 60)))
    res = run_pair(ctx, _signals(ctx.dates), rep_cfg=ReplicationConfig(),
                   costs=FREE, pair_name="TEST")
    assert res.requirements.entry_vintage_hedge is False


def _vintage_evidence(deviation=0.5):
    return {"entry_vintage_hedge": True,
            "entry_vintage_frozen_z_deviation": deviation}


def test_run_pair_rejects_a_vintage_that_moves_inside_an_episode():
    ctx = SyntheticCtx(list(np.linspace(0, 40, 60)))
    sig = _signals(ctx.dates)
    sig["beta_vintage_date"] = list(ctx.dates)     # re-hedged every single day
    sig.attrs.update(_vintage_evidence())
    res = run_pair(ctx, sig, rep_cfg=ReplicationConfig(), costs=FREE, pair_name="TEST")
    assert res.requirements.entry_vintage_hedge is False

    sig2 = _signals(ctx.dates)
    sig2["beta_vintage_date"] = ctx.dates[0]
    sig2.attrs.update(_vintage_evidence())
    res2 = run_pair(ctx, sig2, rep_cfg=ReplicationConfig(), costs=FREE, pair_name="TEST")
    assert res2.requirements.entry_vintage_hedge is True


def test_a_constant_vintage_label_alone_does_not_grant_requirement_two():
    """I4: requirement 2 was the one gate a hand-made frame could walk through.

    A constant nonsense label satisfied the per-episode constancy check, so
    `beta_vintage_date = 1999-01-01` returned True -- asymmetric with
    requirements 1 and 3, which refuse a flag with no measured evidence. And
    mutation M8 shows the label is the wrong thing to check on its own: it stays
    frozen while the hold is priced on the live z.
    """
    ctx = SyntheticCtx(list(np.linspace(0, 40, 60)))
    forged = _signals(ctx.dates)
    forged["beta_vintage_date"] = pd.Timestamp("1999-01-01")
    res = run_pair(ctx, forged, rep_cfg=ReplicationConfig(), costs=FREE,
                   pair_name="TEST")
    assert res.requirements.entry_vintage_hedge is False

    # the stamp must be present AND finite, not merely truthy
    half = _signals(ctx.dates)
    half["beta_vintage_date"] = pd.Timestamp("1999-01-01")
    half.attrs.update({"entry_vintage_hedge": True,
                       "entry_vintage_frozen_z_deviation": float("nan")})
    res2 = run_pair(ctx, half, rep_cfg=ReplicationConfig(), costs=FREE,
                    pair_name="TEST")
    assert res2.requirements.entry_vintage_hedge is False

    # ... and strictly positive: 0.0 is exactly what a freeze that was never
    # applied produces, so accepting it accepts what the stamp exists to detect
    zero = _signals(ctx.dates)
    zero["beta_vintage_date"] = pd.Timestamp("1999-01-01")
    zero.attrs.update(_vintage_evidence(deviation=0.0))
    res3 = run_pair(ctx, zero, rep_cfg=ReplicationConfig(), costs=FREE,
                    pair_name="TEST")
    assert res3.requirements.entry_vintage_hedge is False


def test_entry_vintage_signals_stamp_the_deviation_they_measured():
    spread, drivers = _factor_frame()
    panel = _panel_for(spread, drivers)
    fit = expanding_residual(spread, drivers, min_periods=252)
    out = entry_vintage_signals(panel, SignalConfig(z_entry=1.0), spread_bp=spread,
                                drivers=drivers, betas=fit.betas)
    assert out.attrs["entry_vintage_hedge"] is True
    assert np.isfinite(out.attrs["entry_vintage_frozen_z_deviation"])
    # the freeze genuinely bit on this data -- otherwise the stamp is vacuous
    assert out.attrs["entry_vintage_frozen_z_deviation"] > 0.0
    assert out.attrs["entry_vintage_episodes"] > 0


# ------------------------------------ requirement 4: spread-leg, never residual


def test_daily_pnl_is_the_spread_leg_ledger_not_a_residual():
    ctx = SyntheticCtx(list(np.linspace(0, 40, 60)))
    res = run_pair(ctx, _signals(ctx.dates), rep_cfg=ReplicationConfig(),
                   costs=FREE, pair_name="TEST")
    assert res.pnl_source == "spread_leg_ledger"
    pd.testing.assert_series_equal(res.daily_pnl, res.ledger["total"],
                                   check_names=False)
    assert res.requirements.spread_leg_pnl is True


# --------------------------------------- requirement 6: the random-walk placebo


def test_random_walk_like_keeps_the_index_and_the_level_dispersion():
    idx = pd.bdate_range("2020-01-01", periods=500)
    s = pd.Series(np.cumsum(np.random.default_rng(0).normal(0, 1, 500)) * 3.0, index=idx)
    out = random_walk_like(s, np.random.default_rng(1))
    assert out.index.equals(idx)
    assert out.std(ddof=1) == pytest.approx(s.std(ddof=1), rel=1e-9)
    assert not np.allclose(out.to_numpy(), s.to_numpy())


def test_the_placebo_passes_when_the_headline_beats_the_nulls():
    pl = random_walk_placebo(10.0, lambda rng: float(rng.normal(0.0, 1.0)),
                             n_sims=200, seed=0)
    assert isinstance(pl, PlaceboResult)
    assert pl.n_sims == 200
    assert pl.p_value < 0.05
    assert pl.passes is True


def test_the_placebo_fails_when_a_null_with_no_signal_beats_the_headline():
    pl = random_walk_placebo(0.0, lambda rng: float(rng.normal(5.0, 1.0)),
                             n_sims=200, seed=0)
    assert pl.p_value > 0.5
    assert pl.passes is False


def test_the_placebo_is_seed_reproducible():
    a = random_walk_placebo(1.0, lambda rng: float(rng.normal()), n_sims=50, seed=7)
    b = random_walk_placebo(1.0, lambda rng: float(rng.normal()), n_sims=50, seed=7)
    assert a.placebo_headlines == b.placebo_headlines


# --------------------------------------------------- the league table's honesty


def _alive_looking_result(pair="TEST", n=400, costs=MAKER):
    """A result engineered to clear every one of verdict()'s numeric tests.

    Flat curve, positive carry: 20 disjoint 9-day episodes, every one a winner
    AFTER a real round-trip charge at 2x. It exists to show that clearing the
    ARITHMETIC is not enough to be ALIVE.

    Deliberately NOT a FREE run: a zero-cost result makes `net_2x_bp` -- the
    ALIVE gate's own input -- identical to `gross_bp`, so an "ALIVE" from it
    would be an ALIVE at zero cost (league_table now refuses to quote one).
    """
    ctx = SyntheticCtx([0.0] * n, theta_per_day=+50_000.0)
    sig = _signals(ctx.dates, sign=0, size=0.0)
    for k in range(0, n - 8, 20):
        sig.loc[ctx.dates[k]:ctx.dates[k + 8], ["sign", "size", "dv01_usd"]] = [
            1, 1.0, 100_000.0]
    return run_pair(ctx, sig, rep_cfg=ReplicationConfig(trigger_bp=25.0),
                    costs=costs, pair_name=pair)


def _harvesting_result(pair="SAW", n=200):
    """A book that actually scalps gamma, so its harvest share differs from
    the flat-carry fixture's (which is exactly zero)."""
    path = list(np.tile(list(np.linspace(0, 30, 5)) + list(np.linspace(24, 6, 4)),
                        n // 9 + 1))[:n]
    ctx = SyntheticCtx(path, theta_per_day=+50_000.0)
    sig = _signals(ctx.dates, sign=0, size=0.0)
    for k in range(0, n - 8, 20):
        sig.loc[ctx.dates[k]:ctx.dates[k + 8], ["sign", "size", "dv01_usd"]] = [
            1, 1.0, 100_000.0]
    return run_pair(ctx, sig, rep_cfg=ReplicationConfig(trigger_bp=25.0),
                    costs=MAKER, pair_name=pair)


def _mixed_size_result(pair="MIX", n=200):
    """Episodes held at DIFFERENT sizes, so realised DV01 varies across them.

    Measured on this fixture: per-episode avg DV01 spans $25,561..$105,004
    (4.11x), which is the shape Task 13 found on real curves ($52.7k-$148.9k).
    A fixture whose episodes all carry the SAME realised DV01 cannot tell a
    per-episode normalisation from a run-level one -- the sawtooth fixture has
    them equal to float noise, and an m3 test built on it let the mutation
    through.
    """
    ctx = SyntheticCtx(list(np.linspace(0.0, 300.0, n)), theta_per_day=+50_000.0)
    sig = _signals(ctx.dates, sign=0, size=0.0)
    for j, k in enumerate(range(0, n - 8, 20)):
        size = 1.0 if j % 2 == 0 else 0.25
        sig.loc[ctx.dates[k]:ctx.dates[k + 8], ["sign", "size", "dv01_usd"]] = [
            1, size, size * 100_000.0]
    return run_pair(ctx, sig, rep_cfg=ReplicationConfig(trigger_bp=25.0),
                    costs=MAKER, pair_name=pair)


def _grid_for(pairs, n=4):
    return pd.DataFrame({
        "pair": [p for p in pairs for _ in range(n)],
        "sharpe": np.linspace(0.1, 0.4, n * len(pairs)),
        "total_net_bp": np.linspace(1.0, 4.0, n * len(pairs)),
    })


_ALL_MET = RequirementFlags(expanding_betas=True, entry_vintage_hedge=True,
                            rolling_sigma_z=True, spread_leg_pnl=True,
                            distinct_episodes=True, random_walk_placebo=True)


def test_a_row_that_cannot_report_the_six_requirements_is_never_alive():
    res = _alive_looking_result()
    tbl = league_table([res], grid=_grid_for(["TEST"]), n_trials=4)
    assert not bool(tbl["requirements_met"].iloc[0])
    assert tbl["verdict"].iloc[0] != "ALIVE"
    assert "INELIGIBLE" in tbl["verdict"].iloc[0]


def test_every_league_row_reports_all_six_requirements():
    res = _alive_looking_result()
    tbl = league_table([res], grid=_grid_for(["TEST"]), n_trials=4)
    for name in ("expanding_betas", "entry_vintage_hedge", "rolling_sigma_z",
                 "spread_leg_pnl", "distinct_episodes", "random_walk_placebo"):
        assert f"req_{name}" in tbl.columns


def test_all_six_met_restores_eligibility():
    """I2: with the SAME grid as the downgrade test, so the base verdict really
    is ALIVE and the assertion is live in both directions.

    Without `grid=`, dsr_prob is NaN, the base verdict is SELECTION-ARTIFACT,
    and `"INELIGIBLE" not in verdict` holds no matter what the downgrade logic
    does -- a mutation that downgrades EVERY ALIVE row survived that version.
    """
    res = _alive_looking_result().with_requirements(_ALL_MET)
    tbl = league_table([res], grid=_grid_for(["TEST"]), n_trials=4)
    assert bool(tbl["requirements_met"].iloc[0]) is True
    assert tbl["verdict"].iloc[0] == "ALIVE"


def test_league_table_costs_actually_scale_with_the_multiplier():
    """I1: net_2x_bp is `verdict`'s net_bp_at_taker -- the ALIVE gate's primary
    numeric input -- and nothing checked its value."""
    res = _alive_looking_result(costs=TAKER)
    row = league_table([res], grid=_grid_for(["TEST"]), n_trials=4).iloc[0]
    assert row["cost_1x_usd"] > 0.0
    assert row["net_2x_bp"] < row["net_1x_bp"] < row["gross_bp"]
    assert row["net_2x_bp"] == pytest.approx(
        row["gross_bp"] - 2.0 * (row["gross_bp"] - row["net_1x_bp"]))
    assert row["net_1x_usd"] == pytest.approx(row["gross_usd"] - row["cost_1x_usd"])
    assert row["net_2x_usd"] == pytest.approx(
        row["gross_usd"] - 2.0 * row["cost_1x_usd"])


def test_every_league_bp_column_shares_one_divisor():
    """m3: gross_bp summed PER-EPISODE bp while the cost was normalised at the
    run level. The two only compose when realised DV01 is stable across
    episodes, which Task 13 measured that it is not ($52.7k-$148.9k)."""
    res = _mixed_size_result("MIX")
    dv01s = res.trades["avg_dv01_usd"]
    # The fixture must actually be able to tell the two apart. Measured here:
    # a 4.1x spread in per-episode realised DV01, giving a 0.45% gap between
    # the per-episode sum and the run-level figure -- far above approx's
    # tolerance. A fixture with a flat DV01 makes this test unfalsifiable.
    assert dv01s.max() / dv01s.min() > 3.0
    per_episode_bp = float(res.trades["gross_bp"].sum())

    row = league_table([res], grid=_grid_for(["MIX"]), n_trials=4).iloc[0]
    dv01 = row["realised_dv01_mean_usd"]
    assert row["gross_bp"] == pytest.approx(row["gross_usd"] / dv01)
    assert row["net_1x_bp"] == pytest.approx(row["net_1x_usd"] / dv01)
    assert row["net_2x_bp"] == pytest.approx(row["net_2x_usd"] / dv01)
    assert row["gross_bp"] != pytest.approx(per_episode_bp)   # they DO differ


def test_league_table_refuses_to_quote_costs_from_a_zero_cost_run():
    """I5: scaling a FREE run's realised charge by 2 is still zero, so
    net_2x_bp would equal gross_bp and the ALIVE gate would read a cost-free
    number."""
    res = _alive_looking_result(costs=FREE)
    with pytest.raises(ValueError, match="cost multiplier 0"):
        league_table([res], grid=_grid_for(["TEST"]), n_trials=4)
    # ... unless it is repriced from the ledger's traded-risk volumes
    row = league_table([res], grid=_grid_for(["TEST"]), n_trials=4,
                       cost_schedule=TAKER).iloc[0]
    assert row["cost_1x_usd"] > 0.0
    assert row["net_2x_bp"] < row["gross_bp"]


def test_league_table_refuses_a_grid_that_is_only_one_pairs_slice():
    """The DSR trap: deflating by the per-pair trial count, not the full one."""
    a, b = _alive_looking_result("A"), _alive_looking_result("B")
    with pytest.raises(ValueError, match="per-pair"):
        league_table([a, b], grid=_grid_for(["A"]), n_trials=4)


def test_ranking_one_pair_against_its_own_grid_needs_a_declared_count():
    """I3: the per-pair league table is the natural shape of the trap, and it
    used to pass silently reporting n_trials = one pair's sweep."""
    a = _alive_looking_result("A")
    with pytest.raises(ValueError, match="single pair"):
        league_table([a], grid=_grid_for(["A"]))


def test_league_table_deflates_by_the_full_trial_count():
    a, b = _alive_looking_result("A"), _alive_looking_result("B")
    tbl = league_table([a, b], grid=_grid_for(["A", "B"]))
    assert set(tbl["n_trials"]) == {8}


def test_a_cross_family_trial_count_can_be_declared_above_the_grid():
    """I3: `n_trials` must be allowed to EXCEED the frame in hand -- that is how
    'across all pairs and families' is stated when the other families' grids are
    not concatenated here. It must also reach the deflation, not just be
    cross-checked."""
    a = _alive_looking_result("A")
    small = league_table([a], grid=_grid_for(["A"]), n_trials=8).iloc[0]
    huge = league_table([a], grid=_grid_for(["A"]), n_trials=2916).iloc[0]
    assert small["n_trials"] == 8 and huge["n_trials"] == 2916
    assert huge["dsr_prob"] < small["dsr_prob"]     # the penalty actually bit


def test_league_table_rejects_a_declared_trial_count_below_the_grid():
    a = _alive_looking_result("A")
    with pytest.raises(ValueError, match="n_trials"):
        league_table([a], grid=_grid_for(["A"]), n_trials=3)


@pytest.mark.parametrize("key", ["sharpe", "sharpe_annualised", "skew",
                                 "kurtosis", "resid_skew", "t_stat"])
def test_league_table_refuses_every_forbidden_ranking_key(key):
    res = _alive_looking_result()
    with pytest.raises(ValueError, match="refusing to rank"):
        league_table([res], rank_by=(key,))


def test_league_table_ranks_on_the_permitted_keys():
    """m4: the two fixtures must have genuinely DIFFERENT shares, or the
    sorted-check holds under any ordering."""
    flat = _alive_looking_result("FLAT")          # no hedges -> harvest is 0
    saw = _harvesting_result("SAW")               # scalps gamma -> harvest > 0
    tbl = league_table([flat, saw], grid=_grid_for(["FLAT", "SAW"]),
                       rank_by=("harvest_pnl_share",))
    shares = list(tbl["harvest_pnl_share"])
    assert shares[0] != pytest.approx(shares[1])  # the test can fail
    assert shares == sorted(shares, reverse=True)
    assert tbl["pair"].iloc[0] == "SAW"


def test_league_table_carries_the_carry_sign_and_the_harvest_share():
    res = _alive_looking_result()
    tbl = league_table([res], grid=_grid_for(["TEST"]), n_trials=4)
    assert {"carry_sign", "harvest_pnl_share", "book"} <= set(tbl.columns)


# --------------------------------------------------------- ledger attribution


def test_ledger_attribution_does_not_reintroduce_harvest_to_mtm():
    ctx = SyntheticCtx(list(np.linspace(0, 100, 101)))
    res = run_pair(ctx, _signals(ctx.dates), rep_cfg=ReplicationConfig(trigger_bp=25.0),
                   costs=FREE, pair_name="TEST")
    att = ledger_attribution([res])
    assert "harvest_to_mtm" not in att.columns


def test_the_flow_ratio_is_a_book_size_measure_and_the_share_is_signed():
    """A path whose harvest is negative must give a NEGATIVE pnl share and a
    POSITIVE flow ratio -- they are different objects."""
    # a short-convexity book: harvest is paid away, not collected
    path = list(np.linspace(0.0, 50.0, 51)) + list(np.linspace(49.0, 0.0, 50))
    ctx = SyntheticCtx(path)
    res = run_pair(ctx, _signals(ctx.dates, sign=-1),
                   rep_cfg=ReplicationConfig(trigger_bp=25.0), costs=FREE,
                   pair_name="TEST")
    att = ledger_attribution([res]).iloc[0]
    assert att["harvest"] < 0.0
    assert att["harvest_pnl_share"] < 0.0
    assert att["harvest_flow_ratio"] > 0.0


# ------------------------------------------------------------- per-year detail


def test_per_year_attribution_makes_a_concentrated_year_visible():
    n = 520
    idx = pd.bdate_range("2021-01-04", periods=n)
    pnl = pd.Series(0.0, index=idx)
    pnl.loc["2022"] = 5.0
    pnl.loc["2021"] = -4.0
    res = BacktestResult(
        pair_name="TEST", config={}, daily_pnl=pnl,
        ledger=pd.DataFrame({"total": pnl}, index=idx),
        trades=pd.DataFrame(), stats={"realised_dv01_mean_usd": 100_000.0},
    )
    out = per_year_attribution([res]).set_index("year")
    assert out.loc[2022, "pnl_usd"] > 0
    assert out.loc[2022, "share_of_lifetime"] > 1.0   # more than the whole total
    assert out.loc[2022, "lifetime_ex_year_usd"] < 0.0


# ------------------------------------------------------------------- the grid


def test_the_config_grid_is_972_configs():
    grid = build_config_grid()
    assert len(grid) == 972
    assert len({tuple(sorted(c.items())) for c in grid}) == 972


def test_the_grid_sweeps_every_named_axis():
    grid = build_config_grid()
    df = pd.DataFrame(grid)
    assert set(df["trigger_bp"]) == {10.0, 15.0, 20.0, 25.0, 30.0, 40.0}
    assert set(df["be_cheap"]) == {0.6, 0.8, 0.9}
    assert set(df["be_rich"]) == {1.1, 1.2, 1.5}
    assert set(df["z_entry"]) == {1.0, 1.5, 2.0}
    assert set(df["drift_t_gate"]) == {1.5, 2.0, float("inf")}
    assert set(df["short_side_enabled"]) == {True, False}


def test_run_grid_builds_signals_per_config_when_given_a_raw_panel():
    ctx = SyntheticCtx(list(np.linspace(0, 40, 60)))
    panel = pd.DataFrame(
        {"be_over_realized": 0.7, "drift_t": 0.0, "residual_z": 2.5,
         "spread_vol_bp_day": 1.32, "iv_z": 0.0},
        index=ctx.dates,
    )
    grid = [{"trigger_bp": 25.0, "short_side_enabled": True},
            {"trigger_bp": 25.0, "be_cheap": 0.5}]   # 0.7 is no longer cheap
    out = run_grid({"TEST": ctx}, {"TEST": panel}, grid, costs=FREE)
    assert len(out) == 2
    assert out["n_trades"].iloc[0] == 1
    assert out["n_trades"].iloc[1] == 0


def test_run_grid_reuses_one_simulation_per_replication_config():
    """972 configs must not mean 972 repricings: simulate depends only on the
    replication config, and the pricer is the expensive part."""
    ctx = SyntheticCtx(list(np.linspace(0, 40, 60)))
    calls = {"n": 0}
    real_pv = ctx.pv

    def counting_pv(*a, **k):
        calls["n"] += 1
        return real_pv(*a, **k)

    ctx.pv = counting_pv
    panel = pd.DataFrame(
        {"be_over_realized": 0.7, "drift_t": 0.0, "residual_z": 2.5,
         "spread_vol_bp_day": 1.32, "iv_z": 0.0},
        index=ctx.dates,
    )
    grid = [{"trigger_bp": 25.0, "z_entry": z} for z in (1.0, 1.5, 2.0)]
    run_grid({"TEST": ctx}, {"TEST": panel}, grid, costs=FREE)
    one = calls["n"]
    calls["n"] = 0
    run_grid({"TEST": ctx}, {"TEST": panel}, grid[:1], costs=FREE)
    assert one == calls["n"]        # three configs, one simulation


def test_run_grid_refuses_signal_axes_against_a_prebuilt_frame():
    """m1: a prebuilt frame is reused for every config, so the signal axes are
    swept in the output columns and nowhere else."""
    ctx = SyntheticCtx(list(np.linspace(0, 40, 60)))
    grid = [{"trigger_bp": 25.0, "z_entry": z} for z in (1.0, 2.0)]
    with pytest.raises(ValueError, match="PREBUILT"):
        run_grid({"TEST": ctx}, {"TEST": _signals(ctx.dates)}, grid, costs=FREE)


def test_run_grid_refuses_an_unknown_config_key():
    """m2: `{"zz_entry": ...}` used to give two rows, one distinct result, and a
    tidy column to read the non-difference off."""
    ctx = SyntheticCtx(list(np.linspace(0, 40, 60)))
    with pytest.raises(ValueError, match="zz_entry"):
        run_grid({"TEST": ctx}, {"TEST": _signals(ctx.dates)},
                 [{"trigger_bp": 25.0, "zz_entry": 1.0}], costs=FREE)


def test_memoised_simulations_are_still_keyed_on_the_trigger_width():
    """Reuse is only safe if the key is the whole replication config: a wider
    trigger must actually produce a different path."""
    ctx = SyntheticCtx(list(np.linspace(0, 100, 101)))
    out = run_grid({"TEST": ctx}, {"TEST": _signals(ctx.dates)},
                   [{"trigger_bp": 10.0}, {"trigger_bp": 50.0}], costs=TAKER)
    by_trigger = out.set_index("trigger_bp")
    assert by_trigger.loc[10.0, "harvest_usd"] != by_trigger.loc[50.0, "harvest_usd"]
    assert by_trigger.loc[10.0, "cost_usd"] != by_trigger.loc[50.0, "cost_usd"]


def test_run_grid_reports_the_zero_convexity_comparator_as_its_own_book():
    real = SyntheticCtx(list(np.linspace(0, 60, 80)), gamma=40.0)
    twin = SyntheticCtx(list(np.linspace(0, 60, 80)), gamma=0.0)
    out = run_grid({"TEST": real}, {"TEST": _signals(real.dates)},
                   [{"trigger_bp": 25.0}], costs=FREE,
                   comparator_ctx_by_pair={"TEST": twin})
    assert set(out["book"]) == {"package", "zero_convexity"}
    zc = out[out["book"] == "zero_convexity"].iloc[0]
    assert zc["harvest_usd"] == pytest.approx(0.0, abs=1e-6)


def test_with_placebo_returns_a_new_result_carrying_the_flag():
    res = _alive_looking_result()
    assert res.requirements.random_walk_placebo is False
    pl = random_walk_placebo(10.0, lambda rng: float(rng.normal()), n_sims=50, seed=1)
    out = with_placebo(res, pl)
    assert out.requirements.random_walk_placebo is True
    assert res.requirements.random_walk_placebo is False   # frozen, not mutated


def test_run_grid_uses_the_supplied_signal_builder():
    """The study's grid must be able to run the CAUSAL builder, not only the
    panel-reading one -- build_signals alone satisfies none of requirements 1-3."""
    ctx = SyntheticCtx(list(np.linspace(0, 40, 60)))
    panel = pd.DataFrame(
        {"be_over_realized": 0.7, "drift_t": 0.0, "residual_z": 2.5,
         "spread_vol_bp_day": 1.32, "iv_z": 0.0},
        index=ctx.dates,
    )

    def flat_builder(p, cfg):
        out = pd.DataFrame({"sign": 0, "size": 0.0, "reason": "builder"},
                           index=p.index)
        out["dv01_usd"] = 0.0
        out.attrs.update(_causal_evidence())
        return out

    out = run_grid({"TEST": ctx}, {"TEST": panel}, [{"trigger_bp": 25.0}],
                   costs=FREE, signal_builder=flat_builder)
    assert out["n_trades"].iloc[0] == 0            # the builder was used
    assert bool(out["req_expanding_betas"].iloc[0]) is True   # its attrs survived


def test_run_pair_refuses_a_reused_simulation_from_a_different_date_range():
    from RVUtils.StrikelessVol.replication import simulate

    ctx = SyntheticCtx(list(np.linspace(0, 40, 60)))
    short = simulate(ctx, list(ctx.dates[:30]), ReplicationConfig(), FREE)
    with pytest.raises(ValueError, match="same dates"):
        run_pair(ctx, _signals(ctx.dates), rep_cfg=ReplicationConfig(), costs=FREE,
                 pair_name="TEST", unit=short)


def test_run_pair_refuses_an_unsorted_signal_index():
    ctx = SyntheticCtx(list(np.linspace(0, 40, 60)))
    sig = _signals(ctx.dates).iloc[::-1]
    with pytest.raises(ValueError, match="sorted"):
        run_pair(ctx, sig, rep_cfg=ReplicationConfig(), costs=FREE, pair_name="TEST")


def test_causal_signals_survive_the_full_requirement_check_end_to_end():
    """Requirements 1-5 met from data, 6 only once a placebo has actually run."""
    n = 700
    rng = np.random.default_rng(5)
    ctx = SyntheticCtx(list(np.cumsum(rng.normal(0, 1.2, n))))
    idx = ctx.dates
    vol = pd.Series(60.0 + np.cumsum(rng.normal(0, 0.4, n)), index=idx)
    spread = pd.Series(-1.5 * vol.to_numpy() + 120.0
                       + np.cumsum(rng.normal(0, 0.6, n)), index=idx)
    panel = pd.DataFrame(
        {"be_over_realized": 0.7, "drift_t": 0.0, "residual_z": np.nan,
         "spread_vol_bp_day": 1.32, "iv_z": 0.0},
        index=idx,
    )
    sigs = causal_signals(panel, SignalConfig(z_entry=1.5), spread_bp=spread,
                          drivers={"vol": vol})
    res = run_pair(ctx, sigs, rep_cfg=ReplicationConfig(), costs=TAKER,
                   pair_name="USD")
    assert res.requirements.unmet == ("random_walk_placebo",)
    pl = random_walk_placebo(1e18, lambda r: float(r.normal()), n_sims=50, seed=2)
    assert with_placebo(res, pl).requirements.all_met is True


def test_cost_schedule_multiplier_is_respected_end_to_end():
    ctx = SyntheticCtx(list(np.linspace(0, 100, 101)))
    one = run_pair(ctx, _signals(ctx.dates), rep_cfg=ReplicationConfig(trigger_bp=25.0),
                   costs=TAKER, pair_name="TEST")
    two = run_pair(ctx, _signals(ctx.dates), rep_cfg=ReplicationConfig(trigger_bp=25.0),
                   costs=CostSchedule(initiate_bp=TAKER.initiate_bp,
                                      hedge_bp=TAKER.hedge_bp, roll_bp=TAKER.roll_bp,
                                      multiplier=2.0),
                   pair_name="TEST")
    assert two.ledger["cost"].sum() == pytest.approx(2.0 * one.ledger["cost"].sum(),
                                                     rel=1e-9)

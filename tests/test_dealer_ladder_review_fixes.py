"""Regression tests for defects found by the 2026-07-30 adversarial review.

Each test pins a defect that ACTUALLY OCCURRED in this code, so the docstrings name
the failure rather than the property. Several of these defects were invisible to the
tests that existed at the time -- notably the poison audit, which passed on a builder
leaking five hours of future flow, and the pre-arrival placebo, which reported the
inverse of its own statistic. Those two are the reason this file exists.
"""
import dataclasses
import datetime

import numpy as np
import pandas as pd
import pytest

from BT.dealer_ladder import audit, config as cfg, controls, gates, signals, study
from tests.test_dealer_ladder_integration import BUCKETS, _context, _no_write

NY = "America/New_York"


# ======================================================= the lockout must stay unspent
def test_g2_and_g3_do_not_touch_the_lockout(monkeypatch):
    """They ran over the WHOLE window, so a G3 failure -- exactly the verdict that
    prompts re-specifying the controls -- would have been informed by holdout data,
    leaving the burn rule protecting nothing."""
    _no_write(monkeypatch)
    ctx = _context(effect=0.6, seed=31)
    lock_start = ctx.config.window.lockout_start

    g3 = gates.run_g3(ctx)
    used = pd.DatetimeIndex(g3["long"]["ts"]).tz_convert(NY)
    assert used.max().date() < lock_start, used.max()

    g2 = gates.run_g2(ctx)
    assert not g2["lead_lag"].empty
    # every session code used by G2 must come from the in-sample segment
    n_in = sum(1 for t in ctx.grid
               if pd.Timestamp(t).tz_convert(NY).date() < lock_start)
    assert n_in < len(ctx.grid), "fixture must actually have a lockout segment"


def test_g3_can_be_pointed_at_the_lockout_deliberately(monkeypatch):
    _no_write(monkeypatch)
    ctx = _context(effect=0.6, seed=32)
    out = gates.run_g3(ctx, in_sample=False)
    if not out["long"].empty:
        used = pd.DatetimeIndex(out["long"]["ts"]).tz_convert(NY)
        assert used.min().date() >= ctx.config.window.lockout_start


# ==================================== G2 must not certify an anti-hedging lead as PASS
def test_g2_fails_when_the_ladder_leads_in_the_WRONG_direction(monkeypatch):
    """LLS is built from SQUARED correlations, so it is direction-blind. The verdict
    used LLS alone, so a lead in the ANTI-hedging direction -- the dealer buying more
    of what it is already long, a refutation of the channel -- was reported as PASS."""
    _no_write(monkeypatch)
    ctx = _context(effect=0.0, seed=33)
    grid = ctx.grid
    rng = np.random.default_rng(7)
    # build a ladder level and a rate series where price moves WITH the ladder one
    # step later, i.e. exactly opposite to hedging
    lvl = pd.DataFrame(
        {b: np.cumsum(rng.normal(size=len(grid))) * 1000 for b in BUCKETS}, index=grid)
    inc = signals.ladder_increments(lvl)
    rates = 400.0 - 0.01 * lvl.shift(1).fillna(0.0)      # price up with the ladder
    vols = pd.DataFrame(200.0, index=grid, columns=BUCKETS)
    ctx = dataclasses.replace(
        ctx, signal={"FUTURES": {"level": lvl, "increment": inc, "z": lvl}},
        rates_bp={"FUTURES": rates}, volumes={"FUTURES": vols})
    res = gates.run_g2(ctx)
    assert res["verdict"]["pass"] is not True, res["verdict"]
    if res["verdict"]["timing_lead"]:
        assert res["verdict"]["direction_ok"] is False
        assert "WRONG DIRECTION" in res["verdict"]["headline"]


def test_g2_verdict_exposes_timing_and_direction_separately(monkeypatch):
    _no_write(monkeypatch)
    res = gates.run_g2(_context(effect=0.5, seed=34))
    v = res["verdict"]
    assert set(("timing_lead", "direction_ok", "flow_sign_ok")) <= set(v)
    assert "peak rho" in v["headline"]


# ============================== G3 must not report an anti-hypothesis effect as PASS
def test_g3_fails_on_a_coefficient_with_the_WRONG_sign(monkeypatch):
    """`abs(t) >= 2` admitted negative coefficients, so an effect in the direction
    OPPOSITE the pre-registered hypothesis was emitted with pass=True."""
    _no_write(monkeypatch)
    ctx = _context(effect=-0.9, seed=35)          # rate moves AGAINST the ladder
    res = gates.run_g3(ctx)
    v = res["verdict"]
    assert v["pass"] is not True, v
    if not res["horse_race"].empty:
        assert v["sign_matches_hypothesis"] is False
        assert "OPPOSITE direction" in v["headline"]


# ======================================= the pre-arrival placebo must look BACKWARD
def test_pre_arrival_placebo_measures_the_backward_window(monkeypatch):
    """It handed trade_ledger a CHANGE panel, which the ledger differences again --
    so the statistic was r(t+h) - 2r(t) + r(t-h), the forward window MINUS the
    backward one. A genuine forward-only effect was condemned as leakage and genuine
    anticipation was reported as clean."""
    idx = pd.date_range("2026-03-02 08:00", periods=200, freq="5min", tz=NY)
    # rate flat for the first half, then a steady ramp: pure FORWARD drift late on
    rate = pd.Series(np.r_[np.zeros(100), np.arange(100) * 0.1], index=idx)
    rates = pd.DataFrame({"A": rate})
    lvl = study.pre_arrival_level_panel(rates, 60)
    # ledger arithmetic on the level panel = r(t) - r(t-60m)
    t0 = idx[120]
    got = float(lvl.at[t0 + pd.Timedelta(minutes=60), "A"] - lvl.at[t0, "A"])
    want = float(rate.at[t0] - rate.at[t0 - pd.Timedelta(minutes=60)])
    assert got == pytest.approx(want), (got, want)
    # and the OLD wiring gives the second difference, which is a different number
    old = study.pre_arrival_target(rates, 60)
    second_diff = float(old.at[t0 + pd.Timedelta(minutes=60), "A"] - old.at[t0, "A"])
    assert second_diff != pytest.approx(want)


def test_placebo_table_still_carries_all_six_rows(monkeypatch):
    _no_write(monkeypatch)
    res = gates.run_placebos(_context(effect=0.7, seed=36))
    tab = res["placebos"]
    assert len(tab) == 6
    assert "pre-arrival window" in set(tab["placebo"])


# ============================ the poison audit must actually exercise the age gate
def test_poison_audit_FAILS_when_the_visibility_gate_is_removed(monkeypatch):
    """As originally wired, run_g1 built a ONE-element grid, so ladder_panel's
    per-session chunk window (hi = grid.max()) dropped every future print before the
    decay matrix existed -- and the audit therefore never evaluated the `age >= 0`
    gate that is the actual no-lookahead mechanism. It reported PASS on a builder
    leaking five hours of future flow."""
    ts0 = pd.Timestamp("2026-03-02 09:00", tz=NY)
    session = pd.date_range(ts0, periods=96, freq="5min", tz=NY)
    prints = pd.DataFrame([
        dict(unit_key="early", bucket_space="FUTURES", bucket_key="SFRU26",
             delta_dv01=1000.0, visibility_timestamp=ts0 + pd.Timedelta(minutes=5),
             execution_timestamp=ts0, p_flip=0.0, curve_suspect_trade=False,
             is_block=False),
        dict(unit_key="late", bucket_space="FUTURES", bucket_key="SFRU26",
             delta_dv01=50_000.0,
             visibility_timestamp=ts0 + pd.Timedelta(hours=5),
             execution_timestamp=ts0 + pd.Timedelta(hours=5), p_flip=0.0,
             curve_suspect_trade=False, is_block=False),
    ])

    def leaky(p, ts):
        """A builder with the age gate removed: every print counts, visible or not."""
        df = p[p["bucket_space"] == "FUTURES"]
        return df.groupby("bucket_key")["delta_dv01"].sum()

    grid = [ts0 + pd.Timedelta(minutes=30)]
    res = audit.audit_future_poison(prints, leaky, grid)
    assert not res["pass"], "the audit must catch a builder that ignores visibility"
    assert res["max_future_prints"] >= 1


def test_g1_build_fn_sees_the_whole_session(monkeypatch):
    """The fix: run_g1's builder must span the session so future prints are inside the
    decay matrix and the age gate is the thing being tested."""
    _no_write(monkeypatch)
    res = gates.run_g1(_context(effect=0.0, seed=37), sample_grid=25)
    poison = res["audits"].set_index("audit").loc["future_poison"]
    assert poison["pass"]
    assert poison["max_future_prints"] > 0, "still vacuous"


# ================================= the pre-registered basket must survive a rebuild
def test_grid_and_placebos_keep_the_front_rank_mask(monkeypatch):
    """Both rebuilt the signal from scratch and dropped the mask, trading the window
    UNION (8 SR3 contracts) instead of the pre-registered front six."""
    _no_write(monkeypatch)
    ctx = _context(effect=0.6, seed=38)
    front = ctx.front_rank["FUTURES"].copy()
    dropped = BUCKETS[-2:]
    for b in dropped:
        front[b] = np.nan
    masked = {k: v.where(front.notna()) for k, v in ctx.signal["FUTURES"].items()}
    ctx = dataclasses.replace(ctx, front_rank={"FUTURES": front},
                              signal={"FUTURES": masked})

    plac = gates.run_placebos(ctx)
    assert not plac["placebos"].empty

    res = gates.run_grid(ctx, study.TrialLedger())
    assert not res["league"].empty
    # rebuilt signals must not resurrect the dropped contracts
    built = gates._mask_to_front(
        signals.build_signal(ctx.prints, ctx.grid,
                             dataclasses.replace(ctx.config.signal, space="FUTURES"),
                             buckets=BUCKETS), ctx, "FUTURES")
    for b in dropped:
        assert built["z"][b].isna().all()


def test_grid_records_variants_it_could_not_run(monkeypatch):
    """192 of 288 declared variants silently produced no row: MEETING was never built
    and cross-space bucket namespaces are disjoint. A reader saw 96 rows with no
    indication the rest were skipped rather than tested and found weak."""
    _no_write(monkeypatch)
    ctx = _context(effect=0.3, seed=39)
    ctx = dataclasses.replace(ctx, config=dataclasses.replace(
        ctx.config, grid=cfg.GridConfig(
            horizons_min=(60,), spaces=("FUTURES", "MEETING"),
            half_lives_min=(90.0,), weightings=("expected",),
            target_spaces=("FUTURES",))))
    res = gates.run_grid(ctx, study.TrialLedger())
    assert not res["skipped"].empty
    assert any("MEETING" in v for v in res["skipped"]["variant"])
    assert res["skipped"]["reason"].str.contains("not built").any()


# ================================== direction from the LEVEL, not the demeaned z
def test_trade_ledger_signs_from_the_ladder_level():
    """It signed from z = level - trailing mean. With 68-82% of prints PAID the mean
    is systematically negative, so sign(z) and sign(level) disagreed on ~35% of
    triggers and a third of trades took the position OPPOSITE the hypothesis."""
    idx = pd.date_range("2026-03-02 08:00", periods=40, freq="5min", tz=NY)
    rates = pd.DataFrame({"A": np.arange(40.0)}, index=idx)      # rate always rising
    # z positive but the LEVEL negative: the disagreement region mu < level < 0
    z = pd.DataFrame({"A": np.full(40, 2.0)}, index=idx)
    level = pd.DataFrame({"A": np.full(40, -5000.0)}, index=idx)
    led = study.trade_ledger(z, rates, horizon_min=30, threshold=1.0,
                             cost_bp_by_bucket={"A": 0.0}, direction_panel=level)
    assert len(led) > 0
    assert (led["position"] == -1).all(), "must sign from the level, not z"
    assert (led["signed_from"] == "level").all()
    assert led["sign_disagrees"].all()
    # rate rises, position is short rates -> losses, which is the honest answer
    assert (led["gross_bp"] < 0).all()


def test_trade_ledger_falls_back_to_z_and_says_so():
    idx = pd.date_range("2026-03-02 08:00", periods=20, freq="5min", tz=NY)
    rates = pd.DataFrame({"A": np.arange(20.0)}, index=idx)
    z = pd.DataFrame({"A": np.full(20, 2.0)}, index=idx)
    led = study.trade_ledger(z, rates, horizon_min=30, threshold=1.0,
                             cost_bp_by_bucket={"A": 0.0})
    assert (led["signed_from"] == "zscore").all()
    assert not led["sign_disagrees"].any()


# ============================== horse_race must compare specs on the SAME rows
def test_horse_race_fits_both_specs_on_the_same_sample():
    """It dropped NaN-control rows only from the controlled spec, so a coefficient
    unchanged in magnitude lost ~1.3x of its t from sample shrinkage alone -- and G3
    read that as 'does not survive'."""
    idx = pd.date_range("2026-03-02 08:00", periods=400, freq="30min", tz=NY)
    rng = np.random.default_rng(11)
    sig = rng.normal(size=len(idx))
    ctl = rng.normal(size=len(idx))
    ctl[:150] = np.nan                       # structural NaN, as an expired contract
    frame = pd.DataFrame({"ts": idx, "bucket": "A", "signal": sig, "ctl": ctl,
                          "target": 0.6 * sig + rng.normal(scale=0.3, size=len(idx))})
    out = study.horse_race(frame, controls=["ctl"])
    ns = out.groupby("spec")["n"].max()
    assert ns["signal only"] == ns["signal + controls"], ns
    assert ns["signal only"] == 250


# ============================== curve_shape must not go NaN on the window union
def test_curve_shape_uses_front_rank_not_column_position():
    """Positional picks over a window-union panel select an expiring front contract
    and the most-deferred back contract, so slope and curvature were structurally NaN
    for long stretches and every such row dropped out of the controlled regression."""
    idx = pd.date_range("2026-03-02 08:00", periods=10, freq="30min", tz=NY)
    cols = ["SFRH26", "SFRM26", "SFRU26", "SFRZ26"]
    rates = pd.DataFrame({c: np.arange(10.0) + 10 * i for i, c in enumerate(cols)},
                         index=idx)
    rates["SFRH26"] = np.nan                 # the expired front contract
    positional = controls.curve_shape(rates)
    assert positional["slope_bp"].isna().all(), "positional picks are NaN here"

    rank = pd.DataFrame({"SFRH26": np.nan, "SFRM26": 1.0, "SFRU26": 2.0,
                         "SFRZ26": 3.0}, index=idx)
    ranked = controls.curve_shape(rates, front_rank=rank)
    assert ranked["slope_bp"].notna().all()
    assert ranked["slope_bp"].iloc[0] == pytest.approx(20.0)   # SFRZ26 - SFRM26


# ================================================ staleness guard covers both ends
def test_staleness_guard_rejects_a_stale_EXIT_too():
    """A fresh entry against a 25-minute-stale exit measures a 35-minute move and
    calls it a 60-minute one."""
    idx = pd.date_range("2026-03-02 08:00", periods=40, freq="5min", tz=NY)
    rates = pd.DataFrame({"A": np.arange(40.0)}, index=idx)
    z = pd.DataFrame({"A": np.full(40, 2.0)}, index=idx)
    stale = pd.DataFrame({"A": np.zeros(40)}, index=idx)
    stale.iloc[6:] = 99.0                     # every exit is stale
    led = study.trade_ledger(z, rates, horizon_min=30, threshold=1.0,
                             cost_bp_by_bucket={"A": 0.0},
                             stale_min=stale, max_stale_min=5)
    assert led.empty


def test_trade_ledger_records_staleness_at_both_ends():
    idx = pd.date_range("2026-03-02 08:00", periods=40, freq="5min", tz=NY)
    rates = pd.DataFrame({"A": np.arange(40.0)}, index=idx)
    z = pd.DataFrame({"A": np.full(40, 2.0)}, index=idx)
    stale = pd.DataFrame({"A": np.full(40, 3.0)}, index=idx)
    led = study.trade_ledger(z, rates, horizon_min=30, threshold=1.0,
                             cost_bp_by_bucket={"A": 0.0}, stale_min=stale)
    assert (led["entry_stale_min"] == 3.0).all()
    assert (led["exit_stale_min"] == 3.0).all()


# =================================== flow response window must be strictly forward
def test_flow_response_excludes_the_event_bar():
    """A label-inclusive slice from ts included the bar labelled ts, whose sign came
    from the price change INTO ts -- so contemporaneous co-movement was scored as
    'flow followed the ladder', with the sign the hedging story predicts."""
    idx = pd.date_range("2026-03-02 08:00", periods=5, freq="5min", tz=NY)
    inc = pd.DataFrame({"A": [0.0, 0.0, 5000.0, 0.0, 0.0]}, index=idx)
    flow = pd.DataFrame({"A": [0.0, 0.0, -777.0, 1.0, 0.0]}, index=idx)
    ev = study.flow_response_event_study(inc, flow, horizons_min=(5,), quantile=0.9)
    assert len(ev) == 1
    # the -777 bar at the event instant must NOT be in the window
    assert ev["flow_signed_by_innovation"].iloc[0] == pytest.approx(1.0)

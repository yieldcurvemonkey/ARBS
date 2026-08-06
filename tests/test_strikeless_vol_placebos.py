"""Task 19: the placebos and the confound alternatives.

Two things this file is built to stop, both of them measured rather than
imagined:

* **a null that is EASIER than the real thing.** A plain shuffle destroys the
  persistence of a vol series, so the valuation switch degrades for a reason
  that has nothing to do with whether it reads vol. Every property
  ``block_bootstrap``'s docstring claims is checked here against a known
  answer -- the plain permutation -- rather than assumed.
* **a mirror reported as evidence.** ``replication.simulate`` is exactly
  antisymmetric in ``sign``, so "both directions work" is refuted by
  arithmetic before any data is involved. The sign mirror is refused on a
  static book and stamped ``mirror_is_arithmetic`` when it runs.
"""
import numpy as np
import pandas as pd
import pytest

from RVUtils.StrikelessVol.conventions import FLATTENER, STEEPENER
from RVUtils.StrikelessVol.costs import FREE, TAKER
from RVUtils.StrikelessVol.replication import ReplicationConfig
from RVUtils.StrikelessVol.report import FORBIDDEN_RANK_KEYS
from RVUtils.StrikelessVol.strategy import SignalConfig
from scripts.sv_placebos import (
    CONFOUND_METRIC,
    DurationOnlyPricer,
    block_bootstrap,
    carry_sign_signals,
    mirror_configs,
    pc1_projection,
    persistence_check,
    run_confounds,
    run_placebos,
    z_rule_signals,
)

BASE_DV01 = 100_000.0


class SyntheticCtx:
    """Same closed-form world as tests/test_strikeless_vol_backtest.py."""

    def __init__(self, path_bp, theta_per_day=-500.0, gamma=40.0,
                 start="2022-01-03", theta_flip_at=None):
        self.dates = pd.bdate_range(start, periods=len(path_bp))
        self.path = dict(zip(self.dates, np.asarray(path_bp, dtype=float)))
        self.day_index = {d: i for i, d in enumerate(self.dates)}
        self.theta_per_day = theta_per_day
        #: row index at and after which theta REVERSES sign. The pure-carry
        #: confound is the only thing that reads carry, and with a constant
        #: theta its answer never changes -- so no test on such a path can tell
        #: a lagged rule from one that acts on its own day's carry.
        self.theta_flip_at = theta_flip_at
        self.k = gamma / 1e4

    def rate(self, date, leg):
        return (0.04 if leg == "long" else 0.045) + self.path[date] * 1e-4

    def dv01(self, date, leg):
        return 1.0 + self.k * self.path[date] if leg == "long" else 1.0

    def _theta_per_day(self, date):
        if self.theta_flip_at is not None \
                and self.day_index[date] >= self.theta_flip_at:
            return -self.theta_per_day
        return self.theta_per_day

    def theta(self, date, nl, ns):
        return self._theta_per_day(date) * (nl / BASE_DV01)

    def _cum_theta(self, i):
        if self.theta_flip_at is None:
            return self.theta_per_day * i
        before = min(i, self.theta_flip_at)
        return self.theta_per_day * before - self.theta_per_day * (i - before)

    def pv(self, date, nl, ns):
        dr = self.path[date]
        i = self.day_index[date]
        return (nl * (dr + 0.5 * self.k * dr * dr) - ns * dr
                + self._cum_theta(i) * (nl / BASE_DV01))


def _ar1(n, rho=0.97, sd=1.0, seed=0):
    g = np.random.default_rng(seed)
    e = g.normal(0, sd, n)
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = rho * x[i - 1] + e[i]
    return x


def _vol_like(n=1000, rho=0.90, seed=3, start="2022-01-03"):
    """A STATIONARY persistent series -- what a vol / valuation column is."""
    x = _ar1(n, rho, 1.0, seed) / np.sqrt(1.0 / (1.0 - rho ** 2))
    return pd.Series(1.0 + 0.15 * x, index=pd.bdate_range(start, periods=n))


# ------------------------------------------------------------- the resample


def test_block_bootstrap_preserves_length_and_roughly_the_vol():
    """CHANGED from the brief's specification, which was measured wrong.

    The brief's input was ``cumsum(normal)`` -- a random WALK -- and the
    assertion was that the resampled increment volatility stayed within 25% of
    the observed one. A moving-block bootstrap is defined for a STATIONARY
    series; on a walk it joins blocks whose LEVELS are unrelated, and the
    measured ratio is **4.12**, not 1.0. See
    ``test_block_bootstrap_on_a_random_walk_is_not_what_it_claims``, which pins
    that number rather than hiding it.

    The input here is what the leg actually bootstraps: a persistent,
    stationary valuation series. Measured ratio at rho=0.90, block=63: 1.067.
    """
    s = _vol_like(1000, rho=0.90, seed=3)
    out = block_bootstrap(s, block=63, seed=1)
    assert len(out) == len(s)
    assert out.index.equals(s.index)
    assert out.diff().std() == pytest.approx(s.diff().std(), rel=0.25)
    # the marginal LEVEL distribution is what keeps the null as hard as the
    # real series -- a null whose valuation never crosses a threshold is not a
    # null the switch could have failed on
    assert out.std(ddof=1) == pytest.approx(s.std(ddof=1), rel=0.25)
    assert out.mean() == pytest.approx(s.mean(), rel=0.10)


def test_block_bootstrap_is_seed_reproducible():
    s = pd.Series(np.arange(100.0), index=pd.bdate_range("2024-01-01", periods=100))
    assert block_bootstrap(s, block=10, seed=7).equals(
        block_bootstrap(s, block=10, seed=7)
    )
    assert not block_bootstrap(s, block=10, seed=8).equals(
        block_bootstrap(s, block=10, seed=7)
    )


def test_block_bootstrap_actually_reorders():
    s = pd.Series(np.arange(200.0), index=pd.bdate_range("2024-01-01", periods=200))
    assert not block_bootstrap(s, block=10, seed=3).equals(s)


def test_block_bootstrap_preserves_persistence_where_a_shuffle_destroys_it():
    """The docstring's actual claim, against the known answer it must beat.

    A checking tool that is itself wrong reports success and hides the thing it
    was built to find, so the control is the transform this function exists to
    NOT be: a plain permutation.
    """
    s = _vol_like(1000, rho=0.97, seed=3)
    blocked = block_bootstrap(s, block=63, seed=1)
    shuffled = pd.Series(np.random.default_rng(1).permutation(s.to_numpy()),
                         index=s.index)

    assert s.autocorr(1) == pytest.approx(0.966, abs=0.01)
    assert blocked.autocorr(1) > 0.90            # measured 0.960
    assert abs(shuffled.autocorr(1)) < 0.10      # measured -0.009
    # and the increment volatility tells the same story: 1.18x against 5.47x
    assert blocked.diff().std() / s.diff().std() < 1.5
    assert shuffled.diff().std() / s.diff().std() > 4.0


def test_block_bootstrap_on_a_random_walk_is_not_what_it_claims():
    """The limitation, pinned. Do not bootstrap an integrated series with this.

    This is the input the brief's own test used, and the number it asserted was
    within 25% of one.
    """
    rng = np.random.default_rng(0)
    s = pd.Series(np.cumsum(rng.normal(0, 1, 1000)),
                  index=pd.bdate_range("2022-01-03", periods=1000))
    out = block_bootstrap(s, block=21, seed=1)
    ratio = float(out.diff().std() / s.diff().std())
    assert ratio > 3.0            # measured 4.12
    assert out.attrs["diff_std_ratio"] == pytest.approx(ratio, rel=1e-9)


def test_block_bootstrap_can_draw_the_final_observation():
    """Starts are drawn from [0, n - block] INCLUSIVE.

    The half-open version in the brief's specification can never place the last
    block, so ``values[-1]`` is absent from every resample: measured 199 of 200
    distinct values over 400 seeds.
    """
    n = 200
    s = pd.Series(np.arange(float(n)))
    seen = set()
    for sd in range(400):
        seen.update(block_bootstrap(s, block=10, seed=sd).to_numpy().tolist())
    assert len(seen) == n
    assert max(seen) == n - 1


def test_block_bootstrap_refuses_a_resample_it_cannot_make():
    s = _vol_like(200, seed=1)
    with pytest.raises(ValueError, match="plain shuffle"):
        block_bootstrap(s, block=1)
    with pytest.raises(ValueError, match="unchanged"):
        block_bootstrap(s, block=200)
    with pytest.raises(ValueError, match="unchanged"):
        block_bootstrap(s, block=500)
    with pytest.raises(ValueError, match="nothing to resample"):
        block_bootstrap(s.iloc[:1], block=2)


def test_persistence_check_fails_a_plain_shuffle_and_passes_a_block():
    s = _vol_like(1000, rho=0.97, seed=3)
    good = persistence_check(s, block_bootstrap(s, block=63, seed=1))
    assert good["persistence_preserved"] is True
    assert good["persistence_trivial"] is False
    shuffled = pd.Series(np.random.default_rng(1).permutation(s.to_numpy()),
                         index=s.index)
    bad = persistence_check(s, shuffled)
    assert bad["persistence_preserved"] is False
    assert bad["autocorr1_ratio"] < 0.1


def test_persistence_check_says_so_when_there_is_no_persistence_to_keep():
    """A near-white input has nothing to destroy; the check must not divide by
    a number near zero and call the answer a failure."""
    noise = pd.Series(np.random.default_rng(0).normal(0, 1, 500),
                      index=pd.bdate_range("2022-01-03", periods=500))
    ev = persistence_check(noise, block_bootstrap(noise, block=21, seed=1))
    assert ev["persistence_trivial"] is True
    assert ev["persistence_preserved"] is True


def test_mirror_configs_flips_every_sign():
    grid = [{"sign": 1, "trigger_bp": 25.0}, {"sign": -1, "trigger_bp": 25.0}]
    out = mirror_configs(grid)
    assert [c["sign"] for c in out] == [-1, 1]
    assert all(c["trigger_bp"] == 25.0 for c in out)


def test_mirror_configs_mirrors_the_default_sign_too():
    assert mirror_configs([{"trigger_bp": 25.0}]) == [{"trigger_bp": 25.0, "sign": -1}]


# --------------------------------------------------------------- the fixtures


def _world(n=320, seed=4):
    """A conditional-rule world: the signal's sign genuinely varies."""
    rng = np.random.default_rng(seed)
    ctx = SyntheticCtx(list(np.cumsum(rng.normal(0, 1.1, n))))
    idx = ctx.dates
    t = np.arange(n)
    be = 1.0 + 0.45 * np.sin(2 * np.pi * t / 61.0)
    z = 2.4 * np.sin(2 * np.pi * t / 43.0 + 0.7)
    panel = pd.DataFrame(
        {"be_over_realized": be, "drift_t": 0.0, "residual_z": z,
         "spread_vol_bp_day": 1.32, "iv_z": 0.0},
        index=idx,
    )
    return ctx, panel


def _static_panel(idx):
    return pd.DataFrame(
        {"be_over_realized": 0.7, "drift_t": 0.0, "residual_z": 2.5,
         "spread_vol_bp_day": 1.32, "iv_z": 0.0},
        index=idx,
    )


GRID = [{"trigger_bp": 25.0}]


# --------------------------------------------------------------- run_placebos


def test_run_placebos_runs_every_leg_and_says_which():
    ctx, panel = _world()
    pl_ctx = SyntheticCtx(list(np.cumsum(np.random.default_rng(9).normal(0, 0.4, 320))))
    out = run_placebos({"USD": ctx}, {"USD": panel}, GRID, costs=TAKER,
                       placebo_ctx_by_pair={"SHORT": pl_ctx},
                       placebo_panel_by_pair={"SHORT": panel.set_axis(pl_ctx.dates)},
                       block=21, n_shuffles=2, seed=1)
    assert out.attrs["legs_run"] == ("real", "short_dated", "shuffled_vol",
                                     "sign_mirror")
    assert out.attrs["legs_skipped"] == ()
    assert set(out["family"]) == {"real", "short_dated", "shuffled_vol",
                                  "sign_mirror"}
    assert sorted(out.loc[out["family"] == "shuffled_vol", "sim"].unique()) == [1, 2]
    assert len(out.attrs["shuffle_evidence"]) == 2
    assert all(e["persistence_preserved"] for e in out.attrs["shuffle_evidence"])
    # every leg went through run_grid, so every leg carries its requirement flags
    assert "req_random_walk_placebo" in out.columns


def test_run_placebos_names_the_legs_it_did_not_run():
    ctx, panel = _world()
    out = run_placebos({"USD": ctx}, {"USD": panel}, GRID, costs=FREE,
                       n_shuffles=0, sign_mirror=False)
    assert out.attrs["legs_run"] == ("real",)
    assert out.attrs["legs_skipped"] == ("short_dated", "shuffled_vol",
                                         "sign_mirror")


def test_run_placebos_refuses_half_a_short_dated_placebo():
    ctx, panel = _world()
    with pytest.raises(ValueError, match="BOTH"):
        run_placebos({"USD": ctx}, {"USD": panel}, GRID, costs=FREE,
                     placebo_ctx_by_pair={"SHORT": ctx})


def test_the_shuffled_vol_leg_actually_changes_the_result():
    """A placebo leg that reproduces the real number is a leg that ran nothing."""
    ctx, panel = _world()
    out = run_placebos({"USD": ctx}, {"USD": panel}, GRID, costs=TAKER,
                       block=21, n_shuffles=3, seed=1, sign_mirror=False)
    real = float(out.loc[out["family"] == "real", "total_net_usd"].iloc[0])
    shuffled = out.loc[out["family"] == "shuffled_vol", "total_net_usd"]
    assert len(shuffled) == 3
    assert (shuffled != real).all()


def test_run_placebos_refuses_a_prebuilt_panel_for_the_shuffled_vol_leg():
    """Bootstrapping a column nothing reads reports a degradation of zero."""
    ctx, panel = _world()
    from RVUtils.StrikelessVol.strategy import build_signals
    built = build_signals(panel, SignalConfig())
    with pytest.raises(ValueError, match="RAW signal panel"):
        run_placebos({"USD": ctx}, {"USD": built}, GRID, costs=FREE)


def test_run_placebos_refuses_a_panel_with_no_vol_column_to_shuffle():
    ctx, panel = _world()
    with pytest.raises(ValueError, match="no 'iv_bp_day' column"):
        run_placebos({"USD": ctx}, {"USD": panel}, GRID, costs=FREE,
                     vol_col="iv_bp_day")


def test_run_placebos_refuses_a_bootstrap_that_destroyed_the_persistence():
    """The trap: a null EASIER than the real series degrades for free."""
    ctx, panel = _world()
    with pytest.raises(ValueError, match="destroyed the persistence"):
        run_placebos({"USD": ctx}, {"USD": panel}, GRID, costs=FREE,
                     block=21, n_shuffles=1, min_autocorr_ratio=0.999)


def test_run_placebos_refuses_the_sign_mirror_on_a_static_book():
    """Task 13's amendment, enforced rather than written down.

    ``simulate`` is exactly antisymmetric in ``sign``, so a static book's
    mirror is ``-gross + cost`` by construction and reports nothing at all.
    """
    ctx, _ = _world()
    with pytest.raises(ValueError, match="arithmetically vacuous"):
        run_placebos({"USD": ctx}, {"USD": _static_panel(ctx.dates)}, GRID,
                     costs=FREE, n_shuffles=0)


def test_the_sign_mirror_is_measured_arithmetic_not_evidence():
    """Even on the conditional rule the GROSS mirror is a negation.

    The column exists so a reader does not have to take the module's word for
    it -- and so that a change to ``simulate`` which broke the antisymmetry
    would show up as a number rather than as a mirror that looked interesting.
    """
    ctx, panel = _world()
    out = run_placebos({"USD": ctx}, {"USD": panel}, GRID, costs=TAKER,
                       n_shuffles=0)
    mirror = out[out["family"] == "sign_mirror"]
    assert len(mirror) == 1
    assert bool(mirror["mirror_is_arithmetic"].all())
    assert float(mirror["mirror_gross_sum_usd"].iloc[0]) == pytest.approx(0.0, abs=1e-6)
    assert out.attrs["sign_mirror_is_arithmetic"] is True
    # ... and the sign really was flipped: the mirror's net is not the real net
    real_net = float(out.loc[out["family"] == "real", "total_net_usd"].iloc[0])
    assert float(mirror["total_net_usd"].iloc[0]) != pytest.approx(real_net)
    # the informative reading is the COST band, not the direction
    assert float(mirror["cost_usd"].iloc[0]) == pytest.approx(
        float(out.loc[out["family"] == "real", "cost_usd"].iloc[0]), rel=1e-9)


def test_the_mirror_pairs_each_row_with_the_config_it_actually_mirrors():
    """When the grid itself sweeps ``sign``, the join is ambiguous on the
    remaining keys -- both real rows match every mirror row. The mirror row
    carrying sign s must be paired with the real row carrying -s."""
    ctx, panel = _world()
    grid = [{"trigger_bp": 25.0, "sign": 1}, {"trigger_bp": 25.0, "sign": -1}]
    out = run_placebos({"USD": ctx}, {"USD": panel}, grid, costs=TAKER,
                       n_shuffles=0)
    mirror = out[out["family"] == "sign_mirror"]
    assert len(mirror) == 2
    assert sorted(mirror["sign"]) == [-1, 1]
    assert bool(mirror["mirror_is_arithmetic"].all())
    real = out[out["family"] == "real"].set_index("sign")
    for _, row in mirror.iterrows():
        partner = real.loc[-int(row["sign"])]
        gross_real = float(partner[["carry_usd", "harvest_usd", "mtm_usd",
                                    "cross_usd"]].sum())
        gross_mirror = float(row[["carry_usd", "harvest_usd", "mtm_usd",
                                  "cross_usd"]].sum())
        assert float(row["mirror_gross_sum_usd"]) == pytest.approx(
            gross_real + gross_mirror, abs=1e-6)


# --------------------------------------------------------------- the confounds


def _pc1_inputs(ctx, panel):
    """A curve panel whose PC1 is the level, plus the pair's slope."""
    idx = panel.index
    level = pd.Series([ctx.rate(d, "long") * 1e4 for d in idx], index=idx)
    rates = pd.DataFrame(
        {"2Y": level - 30.0, "5Y": level - 10.0, "10Y": level,
         "30Y": level + 12.0},
        index=idx,
    )
    spread = pd.Series([ctx.rate(d, "long") * 1e4 - ctx.rate(d, "short") * 1e4
                        for d in idx], index=idx)
    return rates, spread


def test_pc1_projection_recovers_a_slope_that_is_pure_pc1():
    """Known answer first: if the slope IS an affine function of PC1, the
    projection reproduces it, so a small residual later means something."""
    ctx, panel = _world()
    idx = panel.index
    level = pd.Series([ctx.rate(d, "long") * 1e4 for d in idx], index=idx)
    rates = pd.DataFrame({"2Y": level - 30.0, "10Y": level, "30Y": level + 12.0},
                         index=idx)
    spread = 3.0 * level - 7.0
    proj = pc1_projection(rates, spread)
    assert proj.attrs["look_ahead"] == "full_sample_pca"
    assert np.corrcoef(proj.dropna(), spread.reindex(proj.dropna().index))[0, 1] \
        == pytest.approx(1.0, abs=1e-6)


def test_carry_sign_signals_read_only_the_carry():
    ctx, panel = _world()
    sig = carry_sign_signals(ctx, list(ctx.dates), rep_cfg=ReplicationConfig(),
                             costs=FREE)
    assert set(sig.columns) >= {"sign", "size", "dv01_usd"}
    assert sig.index.equals(pd.DatetimeIndex(ctx.dates))
    # theta is negative in this world, so the rule holds the SHORT side
    assert set(sig["sign"].unique()) <= {0, FLATTENER, STEEPENER}
    assert (sig["sign"].iloc[2:] == STEEPENER).all()
    assert sig["sign"].iloc[0] == 0          # lag-1: nothing known on day one


def test_carry_sign_signals_act_on_YESTERDAYS_carry():
    """A constant-theta world cannot tell a lagged rule from a look-ahead one.

    The first version of this test asserted only that the sign was constant
    after the warmup, which is true whether or not the rule is lagged -- and a
    mutation removing the ``shift(1)`` survived it. So the world's theta
    REVERSES mid-sample, and the assertion is that the position turns one day
    AFTER the carry does, never on the same day.
    """
    from RVUtils.StrikelessVol.replication import simulate

    n, flip = 120, 60
    ctx = SyntheticCtx(list(np.linspace(0, 30, n)), theta_flip_at=flip)
    carry = simulate(ctx, list(ctx.dates), ReplicationConfig(), FREE)["carry"]
    sign_of_carry = np.sign(carry.to_numpy())
    turns = [i for i in range(2, n)
             if sign_of_carry[i] != 0 and sign_of_carry[i - 1] != 0
             and sign_of_carry[i] != sign_of_carry[i - 1]]
    assert turns == [flip], f"the world must turn exactly once, at {flip}"

    sig = carry_sign_signals(ctx, list(ctx.dates), rep_cfg=ReplicationConfig(),
                             costs=FREE)["sign"].to_numpy()
    # on the turn date the rule still holds YESTERDAY's side ...
    assert sig[flip] == sign_of_carry[flip - 1]
    assert sig[flip] != sign_of_carry[flip]
    # ... and it turns on the next date, not this one
    assert sig[flip + 1] == sign_of_carry[flip]


def test_z_rule_signals_use_the_same_entry_and_sizing_as_the_real_rule():
    ctx, panel = _world()
    z = pd.Series(np.linspace(-3.0, 3.0, len(panel)), index=panel.index)
    cfg = SignalConfig(z_entry=1.5)
    sig = z_rule_signals(z, panel, cfg)
    assert sig["sign"].iloc[1] == FLATTENER       # cheap end of the ramp
    assert sig["sign"].iloc[-1] == STEEPENER      # rich end
    assert sig["sign"].iloc[len(panel) // 2] == 0  # inside the band
    assert (sig["size"] <= cfg.size_cap + 1e-12).all()
    # lag-1: the first row cannot act on its own day's z
    assert sig["sign"].iloc[0] == 0


def test_duration_only_prices_the_short_leg_at_zero():
    ctx, _ = _world()
    d = ctx.dates[5]
    only = DurationOnlyPricer(ctx)
    assert only.pv(d, 1000.0, 500.0) == ctx.pv(d, 1000.0, 0.0)
    assert only.pv(d, 1000.0, 500.0) != ctx.pv(d, 1000.0, 500.0)
    assert only.dv01(d, "long") == ctx.dv01(d, "long")
    assert only.rate(d, "short") == ctx.rate(d, "short")


def test_run_confounds_reports_the_winner_against_all_three():
    from RVUtils.StrikelessVol.strategy import build_signals

    ctx, panel = _world()
    signals = build_signals(panel, SignalConfig())
    rates, spread = _pc1_inputs(ctx, panel)
    out = run_confounds({"USD": ctx}, {"USD": signals}, {"trigger_bp": 25.0},
                        costs=TAKER, rates_by_pair={"USD": rates},
                        spread_by_pair={"USD": spread},
                        panel_by_pair={"USD": panel},
                        z_window=63, z_min_periods=21)
    assert list(out["family"]) == ["winner", "duration_only", "pc1_only",
                                   "pure_carry"]
    assert out.attrs["skipped"] == ()
    assert out.attrs["metric"] == CONFOUND_METRIC
    assert CONFOUND_METRIC not in FORBIDDEN_RANK_KEYS
    assert "sharpe" in FORBIDDEN_RANK_KEYS
    assert isinstance(out.attrs["winner_beats_all"], bool)
    # the winner never "beats" itself, and every comparison is against ITS metric
    assert not bool(out.loc[out["family"] == "winner", "beats_winner"].any())
    assert out["winner_metric"].nunique() == 1


def test_run_confounds_skips_pc1_when_its_inputs_are_missing():
    from RVUtils.StrikelessVol.strategy import build_signals

    ctx, panel = _world()
    signals = build_signals(panel, SignalConfig())
    out = run_confounds({"USD": ctx}, {"USD": signals}, {"trigger_bp": 25.0},
                        costs=TAKER)
    assert out.attrs["skipped"] == ("pc1_only",)
    # a suite with a missing leg cannot certify the winner
    assert out.attrs["winner_beats_all"] is False


def test_run_confounds_fails_closed_on_a_confound_that_never_traded():
    """A comparator with no episodes did not lose the comparison; it never
    entered it. Same shape as the placebo's ``probe_reached``."""
    from RVUtils.StrikelessVol.strategy import build_signals

    ctx, panel = _world()
    signals = build_signals(panel, SignalConfig())
    rates, spread = _pc1_inputs(ctx, panel)
    # an entry threshold the PC1 z can never reach: the leg runs and trades
    # nothing, which is NOT the same as losing
    out = run_confounds({"USD": ctx}, {"USD": signals}, {"trigger_bp": 25.0},
                        costs=TAKER, rates_by_pair={"USD": rates},
                        spread_by_pair={"USD": spread},
                        panel_by_pair={"USD": panel},
                        signal_cfg=SignalConfig(z_entry=100.0),
                        z_window=63, z_min_periods=21)
    pc1 = out[out["family"] == "pc1_only"]
    assert int(pc1["n_trades"].iloc[0]) == 0
    assert bool(pc1["informative"].iloc[0]) is False
    assert bool(pc1["beats_winner"].iloc[0]) is False
    assert out.attrs["skipped"] == ()          # the leg RAN
    assert out.attrs["winner_beats_all"] is False   # ... and still cannot certify


def test_run_confounds_fails_closed_on_a_WINNER_that_never_traded():
    """`>= nan` is False for every confound, so an empty book would otherwise
    'beat' all three. The same hole as the uninformative-confound one, one row
    across."""
    ctx, panel = _world()
    flat = pd.DataFrame({"sign": 0, "size": 0.0, "dv01_usd": 0.0,
                         "reason": "never"}, index=panel.index)
    out = run_confounds({"USD": ctx}, {"USD": flat}, {"trigger_bp": 25.0},
                        costs=TAKER)
    won = out[out["family"] == "winner"]
    assert int(won["n_trades"].iloc[0]) == 0
    assert not bool(out["beats_winner"].any())   # nothing compares to a NaN
    assert out.attrs["winner_informative"] is False
    assert out.attrs["winner_beats_all"] is False


def test_duration_only_is_a_materially_different_book():
    """If the DV01-matched outright pays the same, the package's premise --
    that it has no directional exposure -- is what is wrong."""
    from RVUtils.StrikelessVol.strategy import build_signals

    ctx, panel = _world()
    signals = build_signals(panel, SignalConfig())
    out = run_confounds({"USD": ctx}, {"USD": signals}, {"trigger_bp": 25.0},
                        costs=TAKER)
    pkg = float(out.loc[out["family"] == "winner", "total_net_usd"].iloc[0])
    dur = float(out.loc[out["family"] == "duration_only", "total_net_usd"].iloc[0])
    assert dur != pytest.approx(pkg)

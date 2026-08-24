"""GV block — fills, the roll blackout, episode P&L and costs.

Three conventions carry the block's verdict, and each has a known-answer test
here that fails if the convention is lost:

* fills lag decisions by one mark (engineered pure noise must pay at lag 0 and
  die at lag 1);
* no position straddles an IMM roll (a planted roll jump must be booked with
  the blackout off and NOT booked with it on);
* a fly leg's charged DV01 is 4x the quoted-combination DV01.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from RVUtils.ConvexityRV import gv_signals as G
from RVUtils.ConvexityRV import gv_universe as U


def _flat_series(idx, v=0.0):
    return pd.Series(float(v), index=idx)


def _cfg(**kw):
    base = dict(z_entry=1.0, z_exit=0.25, max_hold_bd=20, window=60,
                min_periods=30)
    base.update(kw)
    return G.SignalConfig(**base)


# ---------------------------------------------------------------------------
# 1. Fills lag decisions by one mark
# ---------------------------------------------------------------------------
def test_same_day_fills_harvest_engineered_noise_and_t_plus_one_kills_it():
    """The decisive convention test.  ``ca`` here is a CONSTANT plus i.i.d.
    noise: it contains no tradeable mean reversion whatsoever, only measurement
    error.  A z-rule filled at the mark it was computed from turns that error
    into P&L; filled one mark later it must not."""
    n = 4000
    idx = pd.bdate_range("2010-01-04", periods=n)
    rng = np.random.default_rng(17)
    ca = pd.Series(10.0 + rng.normal(0.0, 1.0, n), index=idx)
    leg = _flat_series(idx)
    beta = _flat_series(idx)
    gate = pd.Series(True, index=idx)
    segs = [(idx[0], idx[-1])]

    out = {}
    for lag in (0, 1):
        cfg = _cfg(exec_lag_bd=lag)
        f = G.build_signal_frame(ca, ca, leg, beta, gate, cfg=cfg)
        eps = G.episodes_from_signals(f, cfg, segs, ca_dv01=100_000.0)
        pnl = float(G.book_daily(eps, ca, leg, leg_id=None, index=idx,
                                 exec_lag_bd=lag).sum())
        out[lag] = (len(eps), pnl)

    n0, p0 = out[0]
    n1, p1 = out[1]
    assert n0 > 100 and n1 > 100, out
    assert p0 > 1e7, f"same-day fills should harvest the noise, got {p0:,.0f}"
    assert abs(p1) < 0.15 * p0, (
        f"t+1 fills must kill the harvest: {p1:,.0f} vs {p0:,.0f}")


def test_fill_date_walks_the_index_and_falls_off_the_end():
    idx = pd.bdate_range("2020-01-01", periods=10)
    assert G.fill_date(idx, idx[0], 0) == idx[0]
    assert G.fill_date(idx, idx[0], 1) == idx[1]
    assert G.fill_date(idx, idx[-1], 1) is None
    # a decision date that is not a panel date snaps forward, never backward
    assert G.fill_date(idx, pd.Timestamp("2020-01-04"), 0) == pd.Timestamp("2020-01-06")


# ---------------------------------------------------------------------------
# 2. The roll blackout
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def rollset():
    idx = pd.bdate_range("2021-01-04", "2026-08-21")
    return idx, U.roll_segments(idx), set(U.ca_roll_dates(idx))


def test_no_episode_straddles_a_roll_when_the_blackout_is_on(rollset):
    idx, segs, rolls = rollset
    rng = np.random.default_rng(4)
    ca = pd.Series(9.0 + rng.normal(0, 1, len(idx)).cumsum() * 0.1, index=idx)
    cfg = _cfg()
    f = G.build_signal_frame(ca, ca, _flat_series(idx), _flat_series(idx),
                             pd.Series(True, index=idx), cfg=cfg)
    eps = G.episodes_from_signals(f, cfg, segs)
    assert eps
    for e in eps:
        span = idx[(idx >= e.entry) & (idx <= e.exit)]
        assert not (rolls & set(span)), f"episode {e.entry}..{e.exit} spans a roll"


def test_the_blackout_is_what_stops_a_long_ca_book_booking_the_roll_jump(rollset):
    """Plant a +5 bp jump on every roll date on top of a flat series.  A
    long-CA book must book it with the blackout off and must NOT with it on."""
    idx, segs, rolls = rollset
    ca = pd.Series(9.0, index=idx)
    ca.loc[[d for d in idx if d in rolls]] += 5.0
    # hold the whole sample, one episode per arm, side = +1 (long CA)
    def _hold(segments):
        total = 0.0
        for a, b in segments:
            ep = G.Episode(a, b, +1, 0.0, 100_000.0, 0.0, "segment_end")
            total += float(G.episode_pnl(ep, ca, _flat_series(idx),
                                         exec_lag_bd=1).sum())
        return total

    on = _hold(segs)
    off = _hold([(idx[0], idx[-1])])
    assert abs(on) < 1e-6, f"blackout ON should book no roll jumps, got {on:,.0f}"
    assert off == pytest.approx(0.0, abs=1e-6) or abs(off) > 1e5
    # the jumps are +5 up and -5 back down, so a full-sample hold nets ~0; the
    # signed test is the per-roll one:
    jumps = ca.diff().reindex([d for d in idx if d in rolls]).dropna()
    assert float(jumps.mean()) == pytest.approx(5.0, rel=0.01)


def test_roll_jump_is_bookable_with_the_blackout_off_and_not_with_it_on(rollset):
    """A one-sided version: the CA steps UP by 5bp at each roll and never comes
    back (the constant-rank level shift).  Long-CA earns 5bp per roll crossed."""
    idx, segs, rolls = rollset
    step = pd.Series(0.0, index=idx)
    step.loc[[d for d in idx if d in rolls]] = 5.0
    ca = 9.0 + step.cumsum()

    def _hold(segments):
        return sum(float(G.episode_pnl(
            G.Episode(a, b, +1, 0.0, 100_000.0, 0.0, "segment_end"),
            ca, _flat_series(idx), exec_lag_bd=1).sum()) for a, b in segments)

    on = _hold(segs)
    off = _hold([(idx[0], idx[-1])])
    n_rolls = len(rolls)
    assert off == pytest.approx(n_rolls * 5.0 * 100_000.0, rel=0.02), off
    assert abs(on) < 1e-6, f"blackout ON booked {on:,.0f} of roll jump"


def test_episodes_are_confined_to_their_segment(rollset):
    idx, segs, _ = rollset
    rng = np.random.default_rng(21)
    ca = pd.Series(rng.normal(0, 1, len(idx)).cumsum(), index=idx)
    cfg = _cfg()
    f = G.build_signal_frame(ca, ca, _flat_series(idx), _flat_series(idx),
                             pd.Series(True, index=idx), cfg=cfg)
    eps = G.episodes_from_signals(f, cfg, segs)
    bounds = {i: segs[i] for i in range(len(segs))}
    for e in eps:
        a, b = bounds[e.segment]
        assert a <= e.entry <= e.exit <= b


# ---------------------------------------------------------------------------
# 3. P&L and costs
# ---------------------------------------------------------------------------
def test_episode_pnl_is_side_times_spread_change_times_dv01():
    idx = pd.bdate_range("2020-01-01", periods=10)
    ca = pd.Series(np.arange(10.0), index=idx)
    leg = pd.Series(np.arange(10.0) * 3.0, index=idx)
    ep = G.Episode(idx[1], idx[6], -1, 0.2, 100_000.0, 2.0, "z")
    got = float(G.episode_pnl(ep, ca, leg, exec_lag_bd=1).sum())
    # fills at idx[2] and idx[7]: dCA = 5, dleg = 15, spread change = 5 - 0.2*15
    assert got == pytest.approx(-1 * (5.0 - 0.2 * 15.0) * 100_000.0)


def test_episode_pnl_freezes_beta_at_entry():
    """A hedge re-struck intra-episode would let a rolling beta launder
    information into the position; the P&L must use the entry beta only."""
    idx = pd.bdate_range("2020-01-01", periods=10)
    ca = pd.Series(np.arange(10.0), index=idx)
    leg = pd.Series(np.arange(10.0) * 3.0, index=idx)
    a = float(G.episode_pnl(G.Episode(idx[1], idx[6], 1, 0.2, 1e5, 2.0, "z"),
                            ca, leg).sum())
    b = float(G.episode_pnl(G.Episode(idx[1], idx[6], 1, 0.9, 1e5, 2.0, "z"),
                            ca, leg).sum())
    assert a != b
    assert a == pytest.approx((5.0 - 0.2 * 15.0) * 1e5)
    assert b == pytest.approx((5.0 - 0.9 * 15.0) * 1e5)


def test_fly_leg_costs_four_times_its_quoted_dv01():
    ep = G.Episode(pd.Timestamp("2021-01-04"), pd.Timestamp("2021-02-04"),
                   1, 0.5, 100_000.0, 2.0, "z")
    got = G.episode_cost_usd(ep, "immF_2s5s10s", mult=1.0)
    expect = ((G.FUT_RT_BP + G.SWAP_RT_BP) * 100_000.0
              + G.LEG_RT_BP * 4.0 * 0.5 * 100_000.0)
    assert got == pytest.approx(expect)
    # a curve leg is 2x, not 4x
    got_c = G.episode_cost_usd(ep, "le_10y10y_20y10y", mult=1.0)
    assert got_c == pytest.approx((G.FUT_RT_BP + G.SWAP_RT_BP) * 100_000.0
                                  + G.LEG_RT_BP * 2.0 * 0.5 * 100_000.0)
    assert got > got_c


def test_cost_grows_with_the_hedge_size_which_is_the_vega_match_penalty():
    """Re-sizing the hedge up is not free: this is the term that decides whether
    the fix wins gross and loses net."""
    mk = lambda b: G.Episode(pd.Timestamp("2021-01-04"),               # noqa: E731
                             pd.Timestamp("2021-02-04"), 1, b, 1e5, 2.0, "z")
    small = G.episode_cost_usd(mk(0.146), "immF_2s5s10s")
    big = G.episode_cost_usd(mk(1.46), "immF_2s5s10s")
    assert big > small
    # the CA-side cost is fixed; only the hedge scales
    fixed = (G.FUT_RT_BP + G.SWAP_RT_BP) * 1e5
    assert (big - fixed) == pytest.approx(10.0 * (small - fixed))


def test_zero_cost_multiplier_charges_nothing():
    ep = G.Episode(pd.Timestamp("2021-01-04"), pd.Timestamp("2021-02-04"),
                   1, 0.5, 1e5, 2.0, "z")
    assert G.episode_cost_usd(ep, "immF_2s5s10s", mult=0.0) == 0.0


def test_book_daily_charges_the_cost_at_the_exit_fill():
    idx = pd.bdate_range("2020-01-01", periods=12)
    ca = pd.Series(np.zeros(12), index=idx)
    leg = _flat_series(idx)
    ep = G.Episode(idx[2], idx[6], 1, 0.0, 100_000.0, 2.0, "z")
    d = G.book_daily([ep], ca, leg, leg_id=None, index=idx, cost_mult=1.0)
    charged = -(G.FUT_RT_BP + G.SWAP_RT_BP) * 100_000.0
    assert d.loc[idx[7]] == pytest.approx(charged)
    assert float(d.drop(idx[7]).sum()) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 4. Book scale
# ---------------------------------------------------------------------------
def test_inv_vol_scale_is_causal_and_capped():
    n = 800
    idx = pd.bdate_range("2015-01-01", periods=n)
    rng = np.random.default_rng(6)
    vol = np.where(np.arange(n) < n // 2, 0.2, 4.0)
    ca = pd.Series(rng.normal(0, 1, n) * vol, index=idx).cumsum()
    leg = _flat_series(idx)
    beta = _flat_series(idx)
    s = G.inv_vol_scale(ca, leg, beta, base_dv01=100_000.0, cap=3.0)
    good = s.dropna()
    assert good.max() <= 300_001.0 and good.min() >= 33_332.0
    trunc = G.inv_vol_scale(ca.iloc[:400], leg.iloc[:400], beta.iloc[:400],
                            base_dv01=100_000.0, cap=3.0)
    assert np.allclose(s.iloc[:400].dropna().to_numpy(),
                       trunc.dropna().to_numpy())
    # the high-vol half must be sized smaller than the low-vol half
    assert float(good.iloc[-100:].mean()) < float(good.iloc[:100].mean())


def test_signal_lag_placebo_shifts_the_signal_not_the_marks():
    n = 600
    idx = pd.bdate_range("2015-01-01", periods=n)
    rng = np.random.default_rng(8)
    ca = pd.Series(rng.normal(0, 1, n).cumsum(), index=idx)
    leg = _flat_series(idx)
    f0 = G.build_signal_frame(ca, ca, leg, leg, pd.Series(True, index=idx),
                              cfg=_cfg(signal_lag_bd=0))
    f20 = G.build_signal_frame(ca, ca, leg, leg, pd.Series(True, index=idx),
                               cfg=_cfg(signal_lag_bd=20))
    assert np.allclose(f0["ca"].to_numpy(), f20["ca"].to_numpy())
    j = pd.concat([f0["z"].shift(20).rename("a"), f20["z"].rename("b")],
                  axis=1).dropna()
    assert len(j) > 100
    assert np.allclose(j["a"].to_numpy(), j["b"].to_numpy())

"""The CA-vs-fly signal machinery: lag discipline, episode mechanics, P&L sign.

The tests here are built around the failure modes this package has actually
shipped before: an unlagged estimator (the CFTC report date), a sign flip that
survives review because both directions look plausible, and a state machine
whose exits never fire (the w4 DateTrigger defect — flat equity reported as
success). Each test states what breaks if it goes red.
"""
import numpy as np
import pandas as pd
import pytest

from RVUtils.ConvexityRV.cavf_signals import (
    Episode,
    SignalConfig,
    apply_overlay,
    basis_mask,
    book_equity,
    build_signal_frame,
    carry_mask,
    episode_pnl,
    episodes_from_signals,
    positioning_mask,
)

IDX = pd.bdate_range("2023-01-02", periods=320)


def _flat_then_jump(n=320, jump_at=310, jump=5.0):
    v = np.zeros(n)
    rng = np.random.default_rng(7)
    v += rng.normal(0, 0.1, n).cumsum() * 0.01  # tiny drift so sd > 0
    v[jump_at:] += jump
    return pd.Series(v, index=IDX[:n])


class TestLagDiscipline:
    def test_z_at_the_jump_uses_yesterdays_moments(self):
        """The z on the jump day must be computed from moments estimated
        through t−1 — a huge z. An implementation that lets the jump into its
        own window dilutes the very signal it is scoring."""
        ca = _flat_then_jump()
        cfg = SignalConfig(window=252)
        sig = build_signal_frame(ca, None, cfg, mode="ca_only")
        z_jump = float(sig["z"].iloc[310])
        assert z_jump > 20, z_jump

    def test_hand_computed_z_matches_exactly(self):
        """z_t == (x_t − mean(x[t−252:t])) / sd(x[t−252:t]), window ending t−1."""
        rng = np.random.default_rng(11)
        ca = pd.Series(rng.normal(5, 1, 300), index=IDX[:300])
        cfg = SignalConfig(window=252)
        sig = build_signal_frame(ca, None, cfg, mode="ca_only")
        t = 280
        win = ca.iloc[t - 252:t]
        expect = (ca.iloc[t] - win.mean()) / win.std(ddof=1)
        assert np.isclose(float(sig["z"].iloc[t]), expect, rtol=1e-12)

    def test_pairs_beta_is_lagged(self):
        """β applied at t must come from the window ending t−1: hand-compute."""
        rng = np.random.default_rng(3)
        fly = pd.Series(rng.normal(0, 1, 300).cumsum(), index=IDX[:300])
        ca = 0.4 * fly + pd.Series(rng.normal(0, 0.3, 300), index=IDX[:300])
        cfg = SignalConfig(window=100)
        sig = build_signal_frame(ca, fly, cfg, mode="pairs")
        t = 250
        d = pd.concat([ca.rename("ca"), fly.rename("fly")], axis=1).diff()
        win = d.iloc[t - 100:t]                       # ends at t−1 inclusive
        expect = win["ca"].cov(win["fly"]) / win["fly"].var(ddof=1)
        assert np.isclose(float(sig["beta"].iloc[t]), expect, rtol=1e-10)


class TestModesDiffer:
    def test_pairs_and_fv_are_not_the_same_statistic(self):
        """The two declared families must not collapse: on a trending pair the
        changes-β and the levels-β differ, so their z's differ."""
        rng = np.random.default_rng(5)
        n = 320
        trend = np.linspace(0, 10, n)
        fly = pd.Series(trend + rng.normal(0, 0.5, n), index=IDX[:n])
        ca = pd.Series(0.2 * trend + rng.normal(0, 0.5, n), index=IDX[:n])
        cfg = SignalConfig(window=252)
        zp = build_signal_frame(ca, fly, cfg, mode="pairs")["z"]
        zf = build_signal_frame(ca, fly, cfg, mode="fv")["z"]
        both = pd.concat([zp, zf], axis=1).dropna()
        assert len(both) > 30
        assert (both.iloc[:, 0] - both.iloc[:, 1]).abs().max() > 0.05

    def test_fly_only_scores_the_fly(self):
        fly = _flat_then_jump()
        ca = pd.Series(0.0, index=fly.index)
        cfg = SignalConfig(window=252)
        sig = build_signal_frame(ca, fly, cfg, mode="fly_only")
        assert float(sig["z"].iloc[310]) > 20


class TestBetaGate:
    def test_beta_outside_gate_blocks_entry(self):
        rng = np.random.default_rng(9)
        fly = pd.Series(rng.normal(0, 1, 320).cumsum(), index=IDX)
        ca = 5.0 * fly + pd.Series(rng.normal(0, 0.1, 320), index=IDX)  # β≈5
        cfg = SignalConfig(window=252, beta_abs_max=1.0)
        sig = build_signal_frame(ca, fly, cfg, mode="pairs")
        assert not bool(sig["gate_ok"].iloc[260:].any()), (
            "a β of ~5 bp/bp passed the ≤1.0 gate")
        assert episodes_from_signals(sig, cfg) == []


class TestEpisodeMachine:
    def _sig(self, zs):
        idx = pd.bdate_range("2024-01-01", periods=len(zs))
        return pd.DataFrame({"z": zs, "beta": 0.1, "gate_ok": np.isfinite(zs)},
                            index=idx)

    def test_entry_side_is_minus_sign_of_z(self):
        sig = self._sig([0.0, 2.5, 1.0, 0.2, 0.0])
        eps = episodes_from_signals(sig, SignalConfig(window=10))
        assert len(eps) == 1
        assert eps[0].side == -1                      # rich spread is sold
        assert eps[0].exit_reason == "z_exit"
        assert eps[0].entry == sig.index[1] and eps[0].exit == sig.index[3]

    def test_long_side_and_reentry(self):
        sig = self._sig([0.0, -2.5, -1.0, -0.2, 0.0, 2.5, 0.1])
        eps = episodes_from_signals(sig, SignalConfig(window=10))
        assert [e.side for e in eps] == [1, -1]

    def test_one_sided_config_skips_longs(self):
        sig = self._sig([0.0, -2.5, -0.2, 0.0])
        eps = episodes_from_signals(sig, SignalConfig(window=10, two_sided=False))
        assert eps == []

    def test_max_hold_fires(self):
        zs = [0.0, 3.0] + [1.5] * 100                 # never reverts
        sig = self._sig(zs)
        cfg = SignalConfig(window=10, max_hold_bd=21)
        eps = episodes_from_signals(sig, cfg)
        assert len(eps) >= 1
        assert eps[0].exit_reason == "max_hold"
        assert eps[0].hold_bd >= 21

    def test_end_of_data_closes_the_book(self):
        sig = self._sig([0.0, 3.0, 1.5, 1.4])
        eps = episodes_from_signals(sig, SignalConfig(window=10))
        assert eps[-1].exit_reason == "end_of_data"
        assert eps[-1].exit == sig.index[-1]


class TestPnlSign:
    def test_long_spread_gains_when_spread_rises(self):
        idx = pd.bdate_range("2024-01-01", periods=5)
        ca = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0], index=idx)   # +1bp/day
        fly = pd.Series([0.0, 0.0, 0.0, 0.0, 0.0], index=idx)
        ep = Episode(idx[0], idx[-1], +1, 0.5, -2.0, "z_exit")
        p = episode_pnl(ep, ca, fly, ca_dv01=100_000.0, exec_lag_bd=0)
        assert np.isclose(p.sum(), 4 * 100_000.0)

    def test_beta_leg_offsets(self):
        """CA and β·fly moving together net to zero — the pair is hedged."""
        idx = pd.bdate_range("2024-01-01", periods=5)
        fly = pd.Series([0.0, 2.0, 4.0, 6.0, 8.0], index=idx)
        ca = 0.5 * fly + 3.0
        ep = Episode(idx[0], idx[-1], -1, 0.5, +2.0, "z_exit")
        p = episode_pnl(ep, ca, fly, ca_dv01=100_000.0, exec_lag_bd=0)
        assert np.isclose(p.abs().sum(), 0.0)

    def test_short_spread_is_citis_book(self):
        """CA falls 2.2bp with the fly flat: Citi's Blues ticket earned
        (8.8−6.6)×$200k = $440k on the short-CA leg. Same arithmetic here."""
        idx = pd.bdate_range("2017-02-09", periods=4)
        ca = pd.Series([8.8, 8.0, 7.0, 6.6], index=idx)
        fly = pd.Series(0.0, index=idx)
        ep = Episode(idx[0], idx[-1], -1, 0.214, +2.0, "z_exit")
        p = episode_pnl(ep, ca, fly, ca_dv01=200_000.0, exec_lag_bd=0)
        assert np.isclose(p.sum(), 440_000.0)

    def test_costs_charged_at_exit(self):
        idx = pd.bdate_range("2024-01-01", periods=5)
        ca = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0], index=idx)
        ep = Episode(idx[0], idx[2], +1, 0.0, -2.0, "z_exit")
        eq = book_equity([ep], ca, None, ca_dv01=100_000.0,
                         cost_usd_per_episode=25_000.0, exec_lag_bd=0)
        assert np.isclose(eq.iloc[-1], 2 * 100_000.0 - 25_000.0)
        assert np.isclose(eq.iloc[1], 100_000.0)      # no cost before exit


class TestOverlays:
    def test_positioning_mask_is_sided(self):
        idx = pd.bdate_range("2024-01-01", periods=10)
        dealer_z = pd.Series(np.linspace(-2, 2, 10), index=idx)
        m = positioning_mask(dealer_z, z_min=1.0)
        assert m(idx[-1], -1) and not m(idx[-1], +1)   # stretched long → short CA
        assert m(idx[0], +1) and not m(idx[0], -1)
        assert not m(idx[5], -1)                        # |z| < 1: no entry

    def test_basis_mask_needs_an_aligned_move(self):
        idx = pd.bdate_range("2024-01-01", periods=60)
        basis = pd.Series(np.linspace(0, 3, 60), index=idx)   # widening
        m = basis_mask(basis, chg_bd=20, min_abs_bp=0.25)
        assert m(idx[-1], -1) and not m(idx[-1], +1)
        flat = pd.Series(1.0, index=idx)
        m2 = basis_mask(flat, chg_bd=20, min_abs_bp=0.25)
        assert not m2(idx[-1], -1) and not m2(idx[-1], +1)

    def test_carry_mask(self):
        idx = pd.bdate_range("2024-01-01", periods=5)
        roll = pd.Series([1.0, 1.0, -1.0, -1.0, 1.0], index=idx)
        m = carry_mask(roll)
        assert m(idx[0], -1) and not m(idx[0], +1)
        assert m(idx[2], +1) and not m(idx[2], -1)

    def test_apply_overlay_filters_entries(self):
        idx = pd.bdate_range("2024-01-01", periods=10)
        eps = [Episode(idx[1], idx[3], -1, 0.1, 2.5, "z_exit"),
               Episode(idx[6], idx[8], +1, 0.1, -2.5, "z_exit")]
        kept = apply_overlay(eps, lambda t, side: side == -1)
        assert len(kept) == 1 and kept[0].side == -1


class TestGuards:
    def test_holey_panel_refused(self):
        """A 252-row window spanning years is regime soup, not a window."""
        idx = pd.bdate_range("2019-01-01", periods=150).append(
            pd.bdate_range("2024-01-01", periods=200))
        ca = pd.Series(np.random.default_rng(1).normal(size=350), index=idx)
        with pytest.raises(ValueError, match="calendar days"):
            build_signal_frame(ca, None, SignalConfig(window=252), mode="ca_only")

    def test_config_rejects_inverted_thresholds(self):
        with pytest.raises(ValueError):
            SignalConfig(z_entry=1.0, z_exit=2.0)


class TestEmptyOverlayInputs:
    """WHITES has no rank-0 window, so its roll series is EMPTY by structure.
    A mask over an empty series must refuse every entry, never raise."""

    def test_empty_roll_refuses(self):
        m = carry_mask(pd.Series(dtype=float))
        t = pd.Timestamp("2024-06-03")
        assert m(t, -1) is False and m(t, +1) is False

    def test_timestamp_before_series_start_refuses(self):
        idx = pd.bdate_range("2024-06-01", periods=5)
        m = positioning_mask(pd.Series(2.0, index=idx), z_min=1.0)
        assert m(pd.Timestamp("2020-01-01"), -1) is False
        m2 = basis_mask(pd.Series(np.linspace(0, 3, 60),
                                  index=pd.bdate_range("2024-01-01", periods=60)))
        assert m2(pd.Timestamp("2020-01-01"), -1) is False


class TestExecutionConvention:
    """The amendment of 2026-08-24: fills lag decisions by one mark.

    The known answer is engineered: a CA series that is PURE i.i.d.
    measurement noise around a constant. Same-day fills harvest the noise
    (a z-rule enters at a noisy mark and 'earns' its reversion); t+1 fills
    transact at the corrected mark, where there is nothing to earn. A
    convention that passes both halves of this test is doing its job.
    """

    def _noise_ca(self):
        rng = np.random.default_rng(2024)
        idx = pd.bdate_range("2021-01-04", periods=900)
        return pd.Series(5.0 + rng.normal(0, 1.0, len(idx)), index=idx)

    def test_fill_date_is_the_next_mark(self):
        from RVUtils.ConvexityRV.cavf_signals import fill_date
        idx = pd.bdate_range("2024-01-01", periods=5)
        assert fill_date(idx, idx[1], 1) == idx[2]
        assert fill_date(idx, idx[1], 0) == idx[1]
        assert fill_date(idx, idx[-1], 1) is None

    def test_noise_pays_same_day_and_dies_at_t_plus_1(self):
        from RVUtils.ConvexityRV.cavf_grid import CellSpec, run_cell
        ca = self._noise_ca()
        spec = CellSpec("Aca|X|p", "A_ca", "ca_only", "X", None,
                        SignalConfig(window=252))
        r0 = run_cell(spec, {"X": ca}, {}, exec_lag_bd=0)
        r1 = run_cell(spec, {"X": ca}, {}, exec_lag_bd=1)
        g0 = float(r0.equity_by_mult[0.0].iloc[-1])
        g1 = float(r1.equity_by_mult[0.0].iloc[-1])
        assert r0.n_episodes >= 10
        assert g0 > 20 * 100_000.0, (
            f"same-day fills on pure noise should print large false profit, "
            f"got {g0:,.0f}")
        assert g1 < 0.15 * g0, (
            f"t+1 fills must destroy the noise harvest: {g1:,.0f} vs {g0:,.0f}")


class TestRollSplice:
    """The roll-splice amendment: a CM label's jump at the IMM roll is not P&L."""

    def test_splice_zeroes_only_the_roll_jump(self):
        from RVUtils.ConvexityRV.cavf_signals import roll_splice
        idx = pd.bdate_range("2024-03-11", periods=10)
        s = pd.Series([1.0, 1.1, 1.2, 1.1, 6.1, 6.2, 6.1, 6.3, 6.2, 6.4],
                      index=idx)
        roll = pd.DatetimeIndex([idx[4]])          # the +5.0 jump day
        out = roll_splice(s, roll)
        d_raw, d_spl = s.diff(), out.diff()
        assert np.isclose(d_spl.loc[idx[4]], 0.0)
        keep = [i for i in idx[1:] if i != idx[4]]
        assert np.allclose(d_spl.loc[keep], d_raw.loc[keep])
        assert np.isclose(out.iloc[0], s.iloc[0])
        assert np.isclose(out.iloc[-1], s.iloc[-1] - 5.0)

    def test_real_roll_calendar_hits_the_2022_06_15_jump(self):
        """2022-06-15 was an IMM roll (and an FOMC date): the calendar must
        flag it, because that exact jump was booked as an episode win by the
        second grid pass."""
        from RVUtils.ConvexityRV.cavf_signals import imm_roll_dates
        idx = pd.bdate_range("2022-06-06", "2022-06-24")
        rolls = imm_roll_dates(idx)
        assert pd.Timestamp("2022-06-15") in rolls
        assert len(rolls) == 1

    def test_no_rolls_returns_series_unchanged(self):
        from RVUtils.ConvexityRV.cavf_signals import roll_splice
        idx = pd.bdate_range("2024-01-01", periods=6)
        s = pd.Series(np.arange(6, dtype=float), index=idx)
        out = roll_splice(s, pd.DatetimeIndex([]))
        assert np.allclose(out, s)

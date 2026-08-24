"""The declared grid: cell counts against the pre-registration, cost
arithmetic, cell mechanics on engineered series, and the hypothesis matrix.

The cell-count test IS the pre-registration's enforcement arm: if someone adds
cells without amending the doc, this test is the tripwire that keeps the trial
count honest — the mechanism by which every previous grid winner here died was
an understated N.
"""
import numpy as np
import pandas as pd
import pytest

from RVUtils.ConvexityRV.cavf_grid import (
    COST_MULTS,
    CellSpec,
    declared_cells,
    episode_cost_usd,
    fs_hypothesis_matrix,
    grid_stats_frame,
    null_bars,
    run_cell,
    run_grid,
)
from RVUtils.ConvexityRV.cavf_signals import Episode, SignalConfig

IDX = pd.bdate_range("2021-01-04", periods=900)


def _ou(rng, n, mu=0.0, theta=0.05, sigma=0.5):
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = x[i - 1] + theta * (mu - x[i - 1]) + sigma * rng.normal()
    return x


class TestDeclaredCells:
    def test_total_is_the_preregistered_515(self):
        cells = declared_cells()
        assert len(cells) == 515, (
            f"{len(cells)} cells generated vs 515 declared in "
            "docs/convexityrv/cavf-grid-preregistration.md — either the doc or "
            "the generator changed without the other")

    def test_family_counts_match_the_table(self):
        cells = declared_cells()
        counts = pd.Series([c.family for c in cells]).value_counts().to_dict()
        assert counts["A"] == 168
        assert counts["B"] == 168
        assert counts["B_jpm"] == 84
        assert counts["A_ca"] == 28
        assert counts["A_fly"] == 36
        assert counts["B_pinned"] == 1
        overlay_total = sum(v for k, v in counts.items()
                            if k.startswith(("C_", "D_", "E_")))
        assert overlay_total == 30

    def test_cell_ids_unique(self):
        ids = [c.cell_id for c in declared_cells()]
        assert len(ids) == len(set(ids))

    def test_every_overlay_base_exists(self):
        cells = declared_cells()
        ids = {c.cell_id for c in cells}
        for c in cells:
            if c.base_cell is not None:
                assert c.base_cell in ids, c.cell_id


class TestCostArithmetic:
    def _ep(self, beta):
        return Episode(pd.Timestamp("2024-01-02"), pd.Timestamp("2024-02-02"),
                       -1, beta, 2.5, "z_exit")

    def _spec(self, mode):
        return CellSpec("x", "A", mode, "BLUES", "2s5s10s", SignalConfig())

    def test_pairs_cost(self):
        """0.75bp on $100k CA DV01 + 1.0bp on the |β|·DV01 belly."""
        c = episode_cost_usd(self._spec("pairs"), self._ep(0.2),
                             ca_dv01=100_000.0, mult=1.0)
        assert np.isclose(c, 0.75 * 100_000 + 1.0 * 20_000)

    def test_ca_only_cost_has_no_fly_legs(self):
        c = episode_cost_usd(self._spec("ca_only"), self._ep(0.0),
                             ca_dv01=100_000.0, mult=1.0)
        assert np.isclose(c, 0.75 * 100_000)

    def test_fly_only_cost_has_no_package_legs(self):
        c = episode_cost_usd(self._spec("fly_only"), self._ep(0.0),
                             ca_dv01=100_000.0, mult=1.0)
        assert np.isclose(c, 1.0 * 100_000)

    def test_zero_mult_is_free_and_scaling_is_linear(self):
        s, e = self._spec("pairs"), self._ep(0.5)
        assert episode_cost_usd(s, e, ca_dv01=1e5, mult=0.0) == 0.0
        assert np.isclose(episode_cost_usd(s, e, ca_dv01=1e5, mult=2.0),
                          2 * episode_cost_usd(s, e, ca_dv01=1e5, mult=1.0))


class TestRunCell:
    def _panels(self):
        rng = np.random.default_rng(42)
        fly = pd.Series(_ou(rng, len(IDX), sigma=1.0), index=IDX) + 10
        # CA rides the fly at β=0.3 plus its own strongly mean-reverting noise
        resid = pd.Series(_ou(rng, len(IDX), theta=0.2, sigma=0.6), index=IDX)
        ca = 5.0 + 0.3 * fly + resid
        return {"BLUES": ca}, {"2s5s10s": fly}

    def test_pairs_cell_trades_and_orders_costs(self):
        ca_by, fly_by = self._panels()
        spec = CellSpec("A|BLUES|2s5s10s|p", "A", "pairs", "BLUES", "2s5s10s",
                        SignalConfig())
        r = run_cell(spec, ca_by, fly_by)
        assert r.n_episodes >= 3, "an engineered OU residual never traded"
        t = {m: float(r.equity_by_mult[m].iloc[-1]) for m in COST_MULTS}
        assert t[0.0] > t[0.5] > t[1.0] > t[2.0]
        assert t[0.0] > 0, "mean reversion engineered in, gross must be positive"

    def test_placebo_lag_degrades_the_engineered_edge(self):
        ca_by, fly_by = self._panels()
        spec = CellSpec("A|BLUES|2s5s10s|p", "A", "pairs", "BLUES", "2s5s10s",
                        SignalConfig())
        live = run_cell(spec, ca_by, fly_by)
        lagged = run_cell(spec, ca_by, fly_by, signal_lag_bd=20)
        assert (float(lagged.equity_by_mult[0.0].iloc[-1])
                < 0.5 * float(live.equity_by_mult[0.0].iloc[-1]))

    def test_overlay_needs_base(self):
        ca_by, fly_by = self._panels()
        spec = CellSpec("C|A|BLUES|2s5s10s|p", "C_posit", "pairs", "BLUES",
                        "2s5s10s", SignalConfig(), overlay="positioning",
                        base_cell="A|BLUES|2s5s10s|p")
        with pytest.raises(ValueError, match="base_episodes"):
            run_cell(spec, ca_by, fly_by, masks={"positioning": lambda t, s: True})

    def test_run_grid_wires_overlays_from_their_base(self):
        ca_by, fly_by = self._panels()
        base = CellSpec("A|BLUES|2s5s10s|p", "A", "pairs", "BLUES", "2s5s10s",
                        SignalConfig())
        ov = CellSpec("C|A|BLUES|2s5s10s|p", "C_posit", "pairs", "BLUES",
                      "2s5s10s", SignalConfig(), overlay="positioning",
                      base_cell="A|BLUES|2s5s10s|p")
        res = run_grid([ov, base], ca_by, fly_by,
                       masks={"positioning": lambda t, s: s == -1})
        assert all(e.side == -1 for e in res[ov.cell_id].episodes)
        assert (len(res[ov.cell_id].episodes)
                <= len(res[base.cell_id].episodes))

    def test_stats_frame_shapes(self):
        ca_by, fly_by = self._panels()
        spec = CellSpec("A|BLUES|2s5s10s|p", "A", "pairs", "BLUES", "2s5s10s",
                        SignalConfig())
        res = run_grid([spec], ca_by, fly_by)
        st = grid_stats_frame(res)
        assert set(["gross_usd", "net_1x", "ann_sharpe", "n_eff", "hit",
                    "be_mult"]).issubset(st.columns)
        assert st.loc[spec.cell_id, "n_ep"] >= 3


class TestNullBars:
    def test_more_trials_raise_the_bar_and_annualised_is_harder_here(self):
        a = null_bars(6, n_eff=27.0, span_years=5.6)
        b = null_bars(515, n_eff=27.0, span_years=5.6)
        assert b["emax_perhold"] > a["emax_perhold"]
        # holds ~ a month: n_eff >> span_years, so the annualised clock is the
        # harder bar — the flattering-direction check w2b documented
        assert a["emax_annualised"] > a["emax_perhold"]


class TestHypothesisMatrix:
    def test_planted_start_wins(self):
        """CA driven by the 3Y-start fly must score its highest R² there."""
        rng = np.random.default_rng(1)
        flies = {}
        for start in (0.0, 1.0, 2.0, 3.0, 4.0, 5.0):
            fid = "2s5s10s" if start == 0.0 else f"2s5s10s@{start:.0f}Y"
            flies[fid] = pd.Series(rng.normal(0, 1, len(IDX)).cumsum(),
                                   index=IDX)
        ca = 0.5 * flies["2s5s10s@3Y"] + pd.Series(
            rng.normal(0, 0.05, len(IDX)), index=IDX)
        m = fs_hypothesis_matrix({"GREENS": ca}, flies, shapes=("2s5s10s",))
        g = m[m["structure"] == "GREENS"].set_index("start_y")["r2"]
        assert g.idxmax() == 3.0
        assert g.loc[3.0] > 0.9 and g.drop(3.0).max() < 0.5

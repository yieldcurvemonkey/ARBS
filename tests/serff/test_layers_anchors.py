"""Prototype validation anchors — regression tests on the captured panel.

The fixture is the prototype's exact sample (2018-04-02 .. 2026-06-30,
contemporaneous alignment).  Anchor bands are deliberately loose where the
requirements said "roughly"; exact values as fitted on capture date are
asserted tighter to catch silent refactoring drift.
"""

import pytest

from BT.serff.config import SerffModelConfig
from BT.serff.layers import fit_layers


@pytest.fixture(scope="module")
def fit(serff_panel):
    return fit_layers(serff_panel, SerffModelConfig())


class TestPanelShape:
    def test_prototype_sample(self, serff_panel):
        assert len(serff_panel) == 2059
        assert str(serff_panel.index.min().date()) == "2018-04-02"
        assert str(serff_panel.index.max().date()) == "2026-06-30"


class TestLayer1Anchors:
    def test_abundance_regime_slope(self, fit):
        # prototype: -0.35 in 2021-23 abundance (curve dead flat, R2 ~ 0)
        row = fit.level.per_regime.loc["r2_rrp_abundance"]
        assert row["slope"] == pytest.approx(-0.35, abs=0.25)
        assert row["r2"] < 0.05

    def test_postadjustment_regime_slope(self, fit):
        # prototype: ~ -17 post-2024 (steepening as liquidity drains)
        row = fit.level.per_regime.loc["r4_postadj_RMO"]
        assert row["slope"] == pytest.approx(-17.0, abs=5.0)

    def test_qt2_drain_slope(self, fit):
        assert fit.level.per_regime.loc["r3_QT2_drain", "slope"] == pytest.approx(-9.3, abs=3.0)

    def test_mid_month_dummy(self, fit):
        # prototype: +2.3bp (t=2.0) mid-month settlement pressure
        assert float(fit.level.model.params["is_mid"]) == pytest.approx(2.3, abs=1.0)

    def test_exact_capture_values(self, fit):
        # tight guards against silent numerical drift (capture 2026-07-02)
        assert fit.level.n_obs == 1762
        assert fit.level.per_regime.loc["r2_rrp_abundance", "slope"] == pytest.approx(-0.347, abs=0.02)
        assert fit.level.per_regime.loc["r4_postadj_RMO", "slope"] == pytest.approx(-17.07, abs=0.25)


class TestLayer2Anchors:
    def test_sample_counts(self, fit):
        assert fit.turn.n_month_ends == 99
        assert fit.turn.n_quarter_ends == 33

    def test_logit_zstats(self, fit):
        z = dict(zip(fit.turn.logit.params.index, fit.turn.logit.tvalues))
        assert z["ln_liq"] == pytest.approx(-4.7, abs=1.0)
        assert z["is_qe"] == pytest.approx(2.1, abs=0.8)

    def test_q90_tail_steepens_faster(self, fit):
        q50 = fit.turn.quantiles[0.50].params["ln_liq"]
        q90 = fit.turn.quantiles[0.90].params["ln_liq"]
        assert q90 == pytest.approx(-17.6, abs=4.0)
        assert q90 < q50 < 0  # tail fattens faster than the median

    def test_current_state_probabilities(self, fit, serff_panel):
        ln_liq = float(serff_panel["ln_liq"].iloc[-1])
        me = fit.turn.predict(ln_liq, False)
        qe = fit.turn.predict(ln_liq, True)
        assert me["p_hit"] == pytest.approx(0.46, abs=0.08)
        assert qe["p_hit"] == pytest.approx(0.74, abs=0.08)
        assert qe["q50"] == pytest.approx(7.2, abs=1.5)

    def test_jun30_2026_sanity_check(self, serff_panel, fit):
        # one-observation sanity check, not proof: realized +6bp vs q50 +7.2bp
        row = serff_panel.loc["2026-06-30"]
        assert bool(row["is_qe"])
        assert row["spike"] == pytest.approx(6.0, abs=0.6)
        pred = fit.turn.predict(float(serff_panel["ln_liq"].iloc[-1]), True)
        assert abs(row["spike"] - pred["q50"]) < 4.0

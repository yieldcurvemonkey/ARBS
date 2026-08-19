"""Tests for the Citi Vol Lab Figure 8 / Figure 9 reproduction.

Three kinds, and the distinction decides what a green run proves:

**Pure logic** -- the fly identity, the OLS -> (alpha, beta, w2, w10) rewrite,
the correlation and dislocation statistics. No market data, always runs. The
regression tests are *synthetic-recovery* tests: build ``y = alpha + beta*fly``
exactly, hand it to :func:`refit`, and demand the original constants back to
1e-9. A regression test that only checks "R^2 is high" cannot tell a correct
rewrite from a transposed one.

**Known-answer** -- Citi's own printed numbers, with no market data on either
side. [TI-FEB9] prints its entry CA (8.8bp), its entry fly level (-18.2bp) and
its fitted line (``9.7+20.6*fly``), and then says the CA is *"about 3bp ... wide
to the fly"*. Feeding the note its own numbers must return its own 3bp. This is
the check that the published alpha/beta really do describe the published line.

**Data-dependent** -- the three loaders against the local stores, skipped with an
explicit reason when a store or a built panel is absent, so the suite stays green
on a machine without them rather than silently passing.

Mutation-checked: each pure-logic assertion was confirmed to FAIL when the
corresponding line in ``citi_fig89.py`` was perturbed (fly sign flipped, w2/w10
transposed, ``-b2/b5`` sign dropped, ``.diff()`` removed from the changes
correlation).
"""
from __future__ import annotations

import datetime
import math
import pathlib

import numpy as np
import pandas as pd
import pytest

from RVUtils.ConvexityRV import citi_fig89 as CF

_REPO = pathlib.Path(__file__).resolve().parents[1]
_DATA = _REPO / "notebooks" / "data" / "convexity_rv"
_RATES = _DATA / "citi_fig89_rates.parquet"
_VOL_CUBE = _DATA / "citi_fig89_vol_cube_3Y1Y.parquet"
_Q20_PANEL = _DATA / "strat2_q20_panel.parquet"
_Q20_RATES = _DATA / "strat2_q20_rates.parquet"


# ===========================================================================
# Fixtures -- a deterministic, non-degenerate rate panel
# ===========================================================================
def _synthetic_rates(n: int = 400, seed: int = 20170117) -> pd.DataFrame:
    """A 2y/5y/10y panel with three genuinely independent drivers.

    Non-degeneracy is the point: if the three columns were a level plus noise
    the OLS design would be near-singular and a recovery test would pass or fail
    on conditioning rather than on the arithmetic under test. Here level, slope
    and curvature each carry their own random walk.
    """
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2021-01-04", periods=n)
    level = 1.0 + np.cumsum(rng.normal(0, 0.03, n))
    slope = 0.5 + np.cumsum(rng.normal(0, 0.02, n))
    curve = 0.1 + np.cumsum(rng.normal(0, 0.015, n))
    return pd.DataFrame(
        {"2Y": level, "5Y": level + 0.5 * slope + curve, "10Y": level + slope},
        index=idx)


@pytest.fixture(scope="module")
def rates() -> pd.DataFrame:
    return _synthetic_rates()


# ===========================================================================
# Pure logic: the fly
# ===========================================================================
def test_fly_level_is_the_literal_expression(rates):
    """``fly = -w2*2y + 5y - w10*10y``, in percent, with positive quoted weights."""
    got = CF.fly_level(rates, 0.73, 0.47).to_numpy(float)
    want = (-0.73 * rates["2Y"] + rates["5Y"] - 0.47 * rates["10Y"]).to_numpy(float)
    assert np.allclose(got, want, atol=0, rtol=0)


def test_fly_weights_are_not_interchangeable(rates):
    """Transposing w2 and w10 must change the answer.

    Guards the exact failure the two figures invite: Fig 8 is 0.71/0.18 and
    Fig 9 is 0.73/0.47, and a swapped pair still 'looks like a fly'.
    """
    a = CF.fly_level(rates, 0.71, 0.18)
    b = CF.fly_level(rates, 0.18, 0.71)
    assert float((a - b).abs().max()) > 0.1


def test_fly_level_rejects_a_panel_missing_a_tenor(rates):
    with pytest.raises(KeyError, match="5Y"):
        CF.fly_level(rates.drop(columns=["5Y"]), 0.73, 0.47)


def test_scaled_fly_is_alpha_plus_beta_times_fly(rates):
    spec = CF.CITI_FIG9
    got = CF.scaled_fly(rates, spec).to_numpy(float)
    want = (spec.alpha + spec.beta * CF.fly_level(rates, spec.w2, spec.w10)).to_numpy(float)
    assert np.allclose(got, want, atol=1e-12)


def test_a_zero_fly_returns_alpha():
    """A degenerate panel where the fly is identically zero pins the intercept."""
    idx = pd.bdate_range("2021-01-04", periods=5)
    flat = pd.DataFrame({"2Y": 1.0, "5Y": 1.2, "10Y": 1.0}, index=idx)
    # -0.2*1 + 1.2 - 1.0*1 = 0
    assert np.allclose(CF.fly_level(flat, 0.2, 1.0).to_numpy(float), 0.0, atol=1e-12)
    assert np.allclose(CF.scaled_fly(flat, CF.FlyScaling(w2=0.2, w10=1.0, alpha=10.2,
                                                         beta=21.4)).to_numpy(float),
                       10.2, atol=1e-12)


# ===========================================================================
# Pure logic: the published annotations
# ===========================================================================
@pytest.mark.parametrize("spec,text", [
    (CF.CITI_FIG8, "59.7+60.5*(-0.71*2y+5y-0.18*10y)"),
    (CF.CITI_FIG9, "10.2+21.4*(-0.73*2y+5y-0.47*10y)"),
    (CF.CITI_TI_FEB9, "9.7+20.6*(-0.705*2y+5y-0.465*10y)"),
])
def test_annotation_reproduces_the_published_string(spec, text):
    """The chart annotations, verbatim from the PDF text layer.

    ``print (6).pdf.md`` line 263 for the first two, ``print (4).pdf.md`` line
    136 for the third. If a constant is ever edited this fails on the string.
    """
    assert spec.annotation() == text


def test_the_two_figures_use_different_weights():
    """Stated explicitly in the brief and true in the note: each figure is fitted
    to its own left-hand series, so they are not two views of one butterfly."""
    assert (CF.CITI_FIG8.w2, CF.CITI_FIG8.w10) != (CF.CITI_FIG9.w2, CF.CITI_FIG9.w10)


def test_citi_reestimates_between_publications():
    """0.73/0.47 with beta 21.4 on 13-Jan became 0.705/0.465 with beta 20.6 on
    9-Feb -- 27 days. The printed constants are a sample of a procedure."""
    assert CF.CITI_FIG9.w2 != CF.CITI_TI_FEB9.w2
    assert CF.CITI_FIG9.beta != CF.CITI_TI_FEB9.beta
    assert abs(CF.CITI_FIG9.beta - CF.CITI_TI_FEB9.beta) < 1.0


# ===========================================================================
# Known-answer: [TI-FEB9] prints every term of its own line
# ===========================================================================
def test_ti_feb9_published_line_reproduces_its_own_stated_richness():
    """CA 8.8bp, fly -18.2bp, line 9.7 + 20.6*fly  ->  "about 3bp ... wide".

    No market data on either side. This is the check demanded of the notebook:
    that the published alpha/beta reproduce Citi's own fitted line on a sample
    date.
    """
    gap = CF.ti_feb9_dislocation_bp()
    assert math.isclose(gap, 8.8 - (9.7 + 20.6 * -0.182), rel_tol=0, abs_tol=1e-12)
    assert abs(gap - CF.TI_FEB9_TIEOUT["stated_gap_bp"]) <= CF.TI_FEB9_TIEOUT["stated_gap_tol_bp"]
    assert 2.3 <= gap <= 3.5, gap


def test_ti_feb9_tieout_pins_the_units_convention_and_alpha_but_only_loosely_beta():
    """What the tie-out above actually constrains -- measured, not asserted by
    hope. This is the "verify your own check" step: a known-answer test that
    would pass under a wrong implementation proves nothing.

    ``gap = CA - (alpha + beta*fly)`` at ``fly = -0.182``, so

    * ``d(gap)/d(alpha) = -1``  -> a 1bp error in alpha breaks the 0.5bp band.
      **Tight.**
    * ``d(gap)/d(beta) = 0.182`` -> beta must be wrong by 2.75 (13%) to break
      it. **Loose** -- so this check does NOT independently validate beta to
      better than ~13%, and the docstring must not claim it does.
    * the **units** are pinned hard: feeding the fly in bp rather than percent
      moves the gap from 2.85bp to 3.7e2 bp.
    """
    tol = CF.TI_FEB9_TIEOUT["stated_gap_tol_bp"]
    base = CF.TI_FEB9_TIEOUT["stated_gap_bp"]

    off_alpha = CF.ti_feb9_dislocation_bp(
        CF.FlyScaling(w2=0.705, w10=0.465, alpha=9.7 + 1.0, beta=20.6))
    assert abs(off_alpha - base) > tol

    # beta sensitivity is |fly| = 0.182 bp per unit; 10% is NOT enough.
    off_beta_10 = CF.ti_feb9_dislocation_bp(
        CF.FlyScaling(w2=0.705, w10=0.465, alpha=9.7, beta=20.6 * 1.10))
    assert abs(off_beta_10 - base) < tol
    off_beta_30 = CF.ti_feb9_dislocation_bp(
        CF.FlyScaling(w2=0.705, w10=0.465, alpha=9.7, beta=20.6 * 1.30))
    assert abs(off_beta_30 - base) > tol

    # the units convention, which is what the check really nails down
    wrong_units = CF.TI_FEB9_TIEOUT["ca_entry_bp"] - (9.7 + 20.6 * -18.2)
    assert abs(wrong_units - base) > 100.0


def test_jan13_implied_fly_is_consistent_with_the_feb9_printed_level():
    """[VL-JAN17]: Blues CA 9.96bp and "about 4bp ... wide to the fly" imply a fly
    at (9.96 - 4 - 10.2)/21.4 = -0.198% = -19.8bp; [TI-FEB9] printed -18.2bp 27
    days later. Consistency check on the two published figures, not a tie-out."""
    implied_bp = 100.0 * (9.96 - 4.0 - CF.CITI_FIG9.alpha) / CF.CITI_FIG9.beta
    assert abs(implied_bp - CF.TI_FEB9_TIEOUT["fly_entry_bp"]) < 3.0
    assert implied_bp < 0


# ===========================================================================
# Pure logic: the refit
# ===========================================================================
def test_refit_recovers_an_exact_relationship(rates):
    """Synthetic recovery: build ``y = alpha + beta*fly`` exactly, get it back.

    This is the test that pins the OLS -> fly rewrite. ``beta = b5``,
    ``w2 = -b2/b5``, ``w10 = -b10/b5``; every sign and every quotient is
    load-bearing and a transposition survives an R^2 check.
    """
    truth = CF.FlyScaling(w2=0.73, w10=0.47, alpha=10.2, beta=21.4)
    y = truth.scaled(rates)
    fit = CF.refit(y, rates, label="recovery")
    assert fit.n == len(rates)
    for name, want in (("w2", truth.w2), ("w10", truth.w10),
                       ("alpha", truth.alpha), ("beta", truth.beta)):
        got = getattr(fit, name)
        assert abs(got - want) < 1e-9, f"{name}: {got} != {want}"
    assert fit.r_squared > 1 - 1e-12
    assert fit.resid_sd < 1e-9


@pytest.mark.parametrize("truth", [
    CF.CITI_FIG8, CF.CITI_FIG9, CF.CITI_TI_FEB9,
    CF.FlyScaling(w2=-0.30, w10=1.40, alpha=-5.0, beta=-8.0),
])
def test_refit_recovers_every_published_line_and_a_pathological_one(rates, truth):
    """Including a NEGATIVE w2 and a negative beta. Those are findings the code
    must report faithfully, not repair, so the recovery has to survive them."""
    fit = CF.refit(truth.scaled(rates), rates)
    assert abs(fit.w2 - truth.w2) < 1e-9
    assert abs(fit.w10 - truth.w10) < 1e-9
    assert abs(fit.alpha - truth.alpha) < 1e-9
    assert abs(fit.beta - truth.beta) < 1e-9


def test_refit_rewrite_is_algebraically_identical_to_the_raw_ols(rates):
    """``alpha + beta*(-w2*r2 + r5 - w10*r10) == a + b2*r2 + b5*r5 + b10*r10``."""
    rng = np.random.default_rng(7)
    y = (2.0 + 3.0 * rates["2Y"] - 1.5 * rates["5Y"] + 0.75 * rates["10Y"]
         + pd.Series(rng.normal(0, 0.4, len(rates)), index=rates.index))
    fit = CF.refit(y, rates)
    lhs = fit.scaled(rates).to_numpy(float)
    rhs = (fit.alpha + fit.b2 * rates["2Y"] + fit.b5 * rates["5Y"]
           + fit.b10 * rates["10Y"]).to_numpy(float)
    assert np.allclose(lhs, rhs, atol=1e-9)


def test_refit_r_squared_is_between_zero_and_one_with_noise(rates):
    rng = np.random.default_rng(11)
    y = CF.CITI_FIG9.scaled(rates) + pd.Series(rng.normal(0, 2.0, len(rates)),
                                               index=rates.index)
    fit = CF.refit(y, rates)
    assert 0.0 < fit.r_squared < 1.0
    assert fit.resid_sd > 0.5


def test_refit_uses_only_the_overlapping_finite_rows(rates):
    """``n`` is what entered the regression, never what was requested."""
    y = CF.CITI_FIG9.scaled(rates)
    y.iloc[:50] = np.nan
    fit = CF.refit(y.iloc[:300], rates)
    assert fit.n == 250
    assert abs(fit.beta - CF.CITI_FIG9.beta) < 1e-9


def test_refit_returns_nan_rather_than_raising_when_starved(rates):
    fit = CF.refit(CF.CITI_FIG9.scaled(rates).iloc[:3], rates)
    assert fit.n == 3
    assert math.isnan(fit.beta) and math.isnan(fit.w2)


# ===========================================================================
# Pure logic: correlations
# ===========================================================================
def test_corr_table_separates_levels_from_changes():
    """Two series can be perfectly correlated in levels and uncorrelated in
    changes; the whole point of reporting both is that Citi quotes only the
    first. Constructed so the answer is known: a shared trend, independent
    increments.
    """
    n = 600
    idx = pd.bdate_range("2021-01-04", periods=n)
    rng = np.random.default_rng(3)
    trend = np.linspace(0, 50, n)
    a = pd.Series(trend + rng.normal(0, 0.5, n), index=idx)
    b = pd.Series(trend + rng.normal(0, 0.5, n), index=idx)
    out = CF.corr_table(a, b, name="trend")
    assert out["corr_levels"] > 0.99
    assert abs(out["corr_changes"]) < 0.2
    assert out["n_levels"] == n
    assert out["n_changes"] == n - 1


def test_corr_table_recovers_a_perfect_relationship(rates):
    y = CF.CITI_FIG8.scaled(rates)
    out = CF.corr_table(y, CF.scaled_fly(rates, CF.CITI_FIG8))
    assert out["corr_levels"] > 1 - 1e-9
    assert out["corr_changes"] > 1 - 1e-9


def test_corr_table_signs_an_inverse_relationship(rates):
    y = -CF.CITI_FIG8.scaled(rates)
    out = CF.corr_table(y, CF.scaled_fly(rates, CF.CITI_FIG8))
    assert out["corr_levels"] < -1 + 1e-9


def test_rolling_corr_tracks_a_regime_change():
    """First half correlated, second half anti-correlated. A full-sample number
    would average these to ~0 and report 'no relationship'."""
    n = 500
    idx = pd.bdate_range("2021-01-04", periods=n)
    rng = np.random.default_rng(5)
    x = pd.Series(np.cumsum(rng.normal(0, 1, n)), index=idx)
    y = x.copy()
    y.iloc[n // 2:] = -x.iloc[n // 2:]
    rc = CF.rolling_corr(y, x, window=100, min_periods=60)
    assert rc.iloc[120] > 0.9
    assert rc.iloc[-1] < -0.9


# ===========================================================================
# Pure logic: dislocation statistics
# ===========================================================================
def test_dislocation_stats_counts_sign_changes():
    s = pd.Series([1.0, 2.0, -1.0, -2.0, 3.0])          # + + - - +  => 2 flips
    out = CF.dislocation_stats(s, name="x")
    assert out["n"] == 5
    assert out["sign_changes"] == 2
    assert out["pct_positive"] == pytest.approx(60.0)
    assert out["median"] == pytest.approx(1.0)


def test_dislocation_stats_ignores_exact_zeros_when_counting_flips():
    """A zero is neither a sign nor a flip; counting it as one would double-count
    every crossing."""
    assert CF.dislocation_stats(pd.Series([1.0, 0.0, 1.0]))["sign_changes"] == 0
    assert CF.dislocation_stats(pd.Series([1.0, 0.0, -1.0]))["sign_changes"] == 1


def test_dislocation_stats_on_an_all_positive_series():
    out = CF.dislocation_stats(pd.Series([1.0, 2.0, 3.0, 4.0]))
    assert out["sign_changes"] == 0
    assert out["pct_positive"] == 100.0


def test_dislocation_stats_is_empty_safe():
    assert CF.dislocation_stats(pd.Series(dtype=float))["n"] == 0


def test_regression_table_shape():
    fit = CF.FlyFit(w2=0.1, w10=0.2, alpha=1.0, beta=2.0, label="f",
                    r_squared=0.5, n=100)
    tbl = CF.regression_table([CF.CITI_FIG9, fit])
    assert list(tbl.columns) == ["source", "w2", "w10", "alpha", "beta", "r_squared", "n"]
    assert math.isnan(tbl.iloc[0]["r_squared"])       # published rows carry no R^2
    assert tbl.iloc[1]["r_squared"] == 0.5


def test_colour_rank_ladder_matches_the_sofr_pack_convention():
    """Whites 1, Reds 5, Greens 9, Blues 13, Golds 17 -- the ED colour ladder
    mapped onto SOFR strip position. Blues is contracts 13..16."""
    assert CF.COLOUR_RANK == {"Whites": 1, "Reds": 5, "Greens": 9,
                              "Blues": 13, "Golds": 17}
    assert all(v % 4 == 1 for v in CF.COLOUR_RANK.values())


# ===========================================================================
# Data-dependent
# ===========================================================================
@pytest.mark.skipif(not _RATES.exists(), reason="rate panel not built")
def test_real_rate_panel_satisfies_the_fly_identity():
    r = pd.read_parquet(_RATES)
    r.index = pd.to_datetime(r.index)
    assert list(r.columns) == list(CF.RATE_TENORS)
    assert len(r) > 1000
    for spec in (CF.CITI_FIG8, CF.CITI_FIG9):
        lhs = CF.fly_level(r, spec.w2, spec.w10).to_numpy(float)
        rhs = (-spec.w2 * r["2Y"] + r["5Y"] - spec.w10 * r["10Y"]).to_numpy(float)
        assert float(np.nanmax(np.abs(lhs - rhs))) <= 1e-12


@pytest.mark.skipif(not (_RATES.exists() and _Q20_RATES.exists()),
                    reason="rate panels not built")
def test_tb_rate_panel_matches_the_independently_built_q20_rates():
    """Two different code paths -- TimeseriesBuilder+IRSwapsTB here,
    ``_swap_par_rate`` per date in ``scripts/strat2_q20_build.py`` -- must agree
    on the same curve. Measured 4.4e-14 %."""
    a = pd.read_parquet(_RATES)
    a.index = pd.to_datetime(a.index)
    b = pd.read_parquet(_Q20_RATES)
    b.index = pd.to_datetime(b.index)
    j = a.join(b, rsuffix="_q20", how="inner")
    assert len(j) > 300
    for t in CF.RATE_TENORS:
        assert float((j[t] - j[f"{t}_q20"]).abs().max()) < 1e-9


#: Measured with ``IRSwaptionsTB(IRSwaptionMDP(source="CITIVELO-RL",
#: curve_source="CITIVELO_EXCEL"))``, query 3Yx1Y / ATMF / STRADDLE / NVOL --
#: 633.3 s for these five dates, i.e. 126.7 s/date, ~49 h for the 1,404-date
#: window. The cube store returns the same values from local parquet.
_IRSWAPTIONSTB_PROBE = {
    datetime.date(2022, 6, 13): 138.597,
    datetime.date(2022, 6, 14): 139.702,
    datetime.date(2022, 6, 15): 134.066,
    datetime.date(2022, 6, 16): 140.373,
    datetime.date(2022, 6, 17): 139.348,
}


@pytest.mark.skipif(not _VOL_CUBE.exists(), reason="3Y1Y vol cube slice not built")
def test_cube_atmf_equals_the_irswaptionstb_value():
    """The fallback path is not an approximation of the router -- it is the same
    number from the same Citi Velocity store, which is what licenses using it."""
    v = CF.load_vol_3y1y(cache_path=_VOL_CUBE)
    for d, want in _IRSWAPTIONSTB_PROBE.items():
        assert abs(float(v.loc[pd.Timestamp(d)]) - want) < 1e-3, d


@pytest.mark.skipif(not _VOL_CUBE.exists(), reason="3Y1Y vol cube slice not built")
def test_3y1y_vol_is_normal_vol_in_bp_and_covers_the_window():
    v = CF.load_vol_3y1y(datetime.date(2021, 1, 1), datetime.date(2026, 8, 31),
                         cache_path=_VOL_CUBE)
    assert len(v) > 1300
    assert v.index.min() <= pd.Timestamp("2021-01-05")
    assert v.index.max() >= pd.Timestamp("2026-08-01")
    assert 10.0 < float(v.min()) and float(v.max()) < 400.0     # bp normal, not %


@pytest.mark.skipif(not _Q20_PANEL.exists(), reason="Q20 deep-pack panel not built")
def test_blues_coverage_is_the_binding_constraint():
    """The finding, asserted so it cannot rot: Blues exists over 2021-01..2026-07
    but the SR3 strip stops reaching 16 contiguous contracts after mid-2023."""
    _, fit = CF.load_ca_panel(_Q20_PANEL, start=datetime.date(2021, 1, 1),
                              end=datetime.date(2026, 8, 31))
    blues = CF.colour_frame(fit, "Blues")
    assert 480 <= len(blues) <= 530
    by_year = blues.groupby(blues.index.year).size()
    assert by_year.loc[2021] > 200 and by_year.loc[2022] > 150
    assert by_year.loc[2023] < 80, "the 2023 collapse is the finding"
    assert blues.index.max() >= pd.Timestamp("2025-01-01")


@pytest.mark.skipif(not _Q20_PANEL.exists(), reason="Q20 deep-pack panel not built")
def test_ca_panel_ties_out_to_the_published_sofr_screen():
    """Citi Figure 58, close 6/9/2023, 13 rows. The CA column reproduces; the
    MODEL column does not and must not -- this repo fits sigma to the CA cross
    section while Citi calibrates to cap/floor vols, so ours sits ABOVE."""
    from RVUtils.ConvexityRV.strat2_q20 import CITI_SOFR_20230609

    _, fit = CF.load_ca_panel(_Q20_PANEL, start=datetime.date(2023, 6, 1),
                              end=datetime.date(2023, 6, 30))
    day = fit[fit["date"] == pd.Timestamp("2023-06-09")]
    assert len(day) == 13
    ours = day.set_index("pack")["ca_bp"]
    citi = pd.Series({k: v["ca_bp"] for k, v in CITI_SOFR_20230609.items()})
    common = ours.index.intersection(citi.index)
    assert len(common) == 13
    assert float(ours[common].corr(citi[common])) >= 0.95
    assert float((ours[common] - citi[common]).abs().max()) <= 3.5
    assert abs(float(ours["M6-H7"]) - 15.40) < 1.0          # Blues

    model = day.set_index("pack")["ca_model_bp"]
    citi_model = pd.Series({k: v["model_bp"] for k, v in CITI_SOFR_20230609.items()})
    assert (model[common] > citi_model[common]).all()


@pytest.mark.skipif(not (_RATES.exists() and _Q20_PANEL.exists()),
                    reason="panels not built")
def test_citis_ninety_percent_does_not_reproduce_on_2021_2026():
    """The headline result, pinned. With Citi's OWN published weights the levels
    correlation is NEGATIVE on both figures, against the stated +0.90."""
    r = pd.read_parquet(_RATES)
    r.index = pd.to_datetime(r.index)
    _, fit = CF.load_ca_panel(_Q20_PANEL, start=datetime.date(2021, 1, 1),
                              end=datetime.date(2026, 8, 31))
    ca = CF.colour_frame(fit, "Blues")["ca_bp"]
    out = CF.corr_table(ca, CF.scaled_fly(r, CF.CITI_FIG9))
    assert out["n_levels"] > 400
    assert out["corr_levels"] < 0.0, out
    assert abs(out["corr_changes"]) < 0.25, out


@pytest.mark.skipif(not (_RATES.exists() and _VOL_CUBE.exists()),
                    reason="panels not built")
def test_fig8_published_weights_are_anticorrelated_on_2021_2026():
    r = pd.read_parquet(_RATES)
    r.index = pd.to_datetime(r.index)
    v = CF.load_vol_3y1y(datetime.date(2021, 1, 1), datetime.date(2026, 8, 31),
                         cache_path=_VOL_CUBE)
    out = CF.corr_table(v, CF.scaled_fly(r, CF.CITI_FIG8))
    assert out["n_levels"] > 1300
    assert out["corr_levels"] < 0.0, out

    refit = CF.refit(v, r)
    assert refit.r_squared > 0.6            # fit recovers ...
    assert refit.w2 < 0.2                   # ... but the 2y wing has vanished

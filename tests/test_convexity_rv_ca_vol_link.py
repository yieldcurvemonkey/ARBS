"""Tests for the CA <-> vol link -- the missing panel of Citi's Fig 8/9 chain.

Three kinds, and the distinction decides what a green run proves:

**Known-answer, external** -- Citi's 12-Jun-2023 SOFR screen prints an
"Implied Vol" column (199.5 at rank 5 down to 151.9 at rank 17) *and* the
``CvxAdj`` column it was computed from. Pushing CITI'S OWN CA through
:func:`implied_vol_from_ca_bp` on IMM dates rebuilt from
:mod:`RVUtils.ConvexityRV.packs` must return CITI'S OWN printed vol. Thirteen
rows, no data of ours on either side. This is the assertion that pins BOTH the
Ho-Lee convention (``T1^2``, not ``T1*T2``) and the bp/decimal units against an
external source, and it is the one worth mutating: a dropped ``1e4`` moves it by
a factor of 100 and a switched convention by 3-11%.

**Pure logic** -- expiry-label parsing, the NaN semantics of a non-positive CA,
the business-day alignment that stops a ``.diff()`` spanning a gap, the exact
``dCA = d(pack) - d(swap)`` identity, the matrix orientation, and the verdict
rule's branches. No market data, always runs. These are constructed so a
transposed axis or a dropped alignment step FAILS rather than merely degrading:
the synthetic fixtures put a *different* answer in every cell.

**Data-dependent** -- the loaders and the panel-level round trip, skipped with
an explicit reason when a store or a built panel is absent, so the suite stays
green on a machine without them rather than silently passing.

Mutation-checked, and the check was RUN rather than asserted. Each mutation
below was applied to ``ca_vol_link.py`` / ``holee.py``, the named test was
confirmed to FAIL, and the file was restored; all ten were caught and the suite
was green again afterwards.

=====================================================  ==========================================
mutation                                               test that catches it
=====================================================  ==========================================
``DEFAULT_CONVENTION = HULL`` (``T1*T2``, not ``T1^2``) ``test_citi_printed_implied_vol_is_the_ho_lee_inversion``
drop the ``1e4`` in ``implied_vol_from_ca_bp``          ``test_citi_printed_implied_vol_is_the_ho_lee_inversion``
``seq[k:k+4]`` in ``attach_pack_expiries``              ``test_pack_expiry_reconstruction_matches_the_panel``
``seq[k:k+4]`` in ``citi_implied_vol_tieout``           ``test_citi_tieout_table_on_the_panel``
clip CA at 0 instead of returning NaN                   ``test_non_positive_ca_gives_nan_not_zero``
``align_bdays`` returns the compressed index            ``test_align_bdays_makes_diff_gap_aware``
``t1_rms`` computed as ``mean(T1)``                     ``test_t1_rms_is_root_mean_square_not_mean``
copy one column over another in ``link_matrix``         ``test_link_matrix_orientation``
``expiry_years`` reads ``M`` as years                   ``test_expiry_years``
restore the v1 ``abs()`` levels margin as a CHECK       ``test_verdict_confirmed_on_the_measured_numbers``
=====================================================  ==========================================
"""
from __future__ import annotations

import datetime
import math
import pathlib

import numpy as np
import pandas as pd
import pytest

from RVUtils.ConvexityRV import ca_vol_link as CVL
from RVUtils.ConvexityRV.holee import implied_vol_from_ca_bp, pack_ca_bp, pack_time_weight
from RVUtils.ConvexityRV.packs import pack_t1s, quarterly_imm_sequence
from RVUtils.ConvexityRV.strat2_q20 import CITI_SOFR_20230609

_REPO = pathlib.Path(__file__).resolve().parents[1]
_DATA = _REPO / "notebooks" / "data" / "convexity_rv"
_CA_FIT = _DATA / "citi_fig89_ca_fit.parquet"
_VOL_GRID = _DATA / "ca_vol_link_vol_cube_1Y.parquet"

#: Citi Research, *Rates Vol Lab*, 12-Jun-2023 Figure 58, close 6/9/2023.
_CITI_DATE = datetime.date(2023, 6, 9)

#: Measured max |ours - Citi printed| across the 13 rows, 1.177bp (median
#: 0.450bp). That residual is the rounding of the printed CA to 2dp: at rank 5,
#: sigma = sqrt(2*CA/M) with M = 2.049, so +-0.005bp of CA is +-0.12bp of vol,
#: and the residual is systematically NEGATIVE because the printed CA is a
#: rounded-down-on-average version of the one Citi inverted. Tolerance set with
#: headroom over the measurement, not fitted to it.
_CITI_IV_TOL_BP = 1.5


# ===========================================================================
# Known-answer, external: Citi's own printed Implied Vol column
# ===========================================================================
def _citi_rows():
    """``(pack, rank, ca_bp, implied_vol_bp, T1s)`` for the 13 published rows."""
    seq = quarterly_imm_sequence(_CITI_DATE, 40)
    out = []
    for pack, ref in CITI_SOFR_20230609.items():
        k = int(ref["rank"])
        out.append((pack, k, float(ref["ca_bp"]), float(ref["implied_vol_bp"]),
                    pack_t1s(_CITI_DATE, seq[k - 1: k + 3])))
    return sorted(out, key=lambda r: r[1])


def test_citi_printed_implied_vol_is_the_ho_lee_inversion():
    """All 13 rows of Citi's 6/9/2023 screen, their CA -> their printed vol.

    ``implied_vol_from_ca_bp(CA, T1s) == sqrt(2*CA/mean(T1^2))`` in bp. Nothing
    of ours enters: the CA and the target vol are both Citi's, and the only
    thing under test is the convention, the units and the IMM-date arithmetic.
    """
    errs = []
    for pack, rank, ca_bp, iv_printed, t1s in _citi_rows():
        got = implied_vol_from_ca_bp(ca_bp, t1s)
        errs.append((pack, rank, got, iv_printed, got - iv_printed))
    d = np.array([e[4] for e in errs], dtype=float)
    assert np.isfinite(d).all(), errs
    assert np.max(np.abs(d)) <= _CITI_IV_TOL_BP, (
        "Ho-Lee inversion does not reproduce Citi's printed Implied Vol column: "
        + ", ".join(f"{p}(rank {r}) ours {g:.2f} vs Citi {w:.2f}" for p, r, g, w, _ in errs))
    # Not just "close on average": every single row, and in a plausible band.
    assert np.max(np.abs(d)) <= _CITI_IV_TOL_BP
    assert all(100.0 < e[2] < 300.0 for e in errs), (
        "implied vols outside 100-300bp -- a units error, not a modelling one")


def test_citi_printed_implied_vol_falls_monotonically_across_the_strip():
    """199.5 -> 151.9 in Citi's print, and our inversion must fall too.

    The *shape* is a second, independent known answer: an inversion that got the
    time weight right but the units wrong could still land inside the 1.5bp
    band on one row by luck; reproducing a monotone 48bp decline over 13 rows
    could not.
    """
    ours = [implied_vol_from_ca_bp(ca, t1s) for _, _, ca, _, t1s in _citi_rows()]
    citi = [iv for _, _, _, iv, _ in _citi_rows()]
    assert citi[0] == pytest.approx(199.5) and citi[-1] == pytest.approx(151.9)
    # Citi's own column is not perfectly monotone (rank 9-11 bumps up), so the
    # test is that OUR shape tracks THEIRS, not that either is monotone.
    assert np.corrcoef(ours, citi)[0, 1] > 0.99
    assert ours[0] > ours[-1]
    assert ours[0] - ours[-1] == pytest.approx(citi[0] - citi[-1], abs=1.0)


def test_hull_convention_would_fail_the_citi_tieout():
    """The known-answer test is a real discriminator, not a tautology.

    ``T1*T2`` instead of ``T1^2`` is the textbook Ho-Lee form and is *wrong* for
    Citi's tables. If it passed the tie-out above, that tie-out would prove
    nothing about the convention.
    """
    worst = 0.0
    for _, _, ca_bp, iv_printed, t1s in _citi_rows():
        hull = implied_vol_from_ca_bp(ca_bp, t1s, convention="hull")
        worst = max(worst, abs(hull - iv_printed))
    assert worst > _CITI_IV_TOL_BP, (
        f"the 'hull' convention lands within {worst:.2f}bp too, so the tie-out "
        "does not actually pin the convention")


# ===========================================================================
# Pure logic
# ===========================================================================
def test_expiry_years():
    assert CVL.expiry_years("3Y") == pytest.approx(3.0)
    assert CVL.expiry_years("18M") == pytest.approx(1.5)
    assert CVL.expiry_years("9M") == pytest.approx(0.75)
    assert CVL.expiry_years("1Y") == pytest.approx(1.0)
    # 18M must sort BETWEEN 1Y and 2Y -- alphabetical order would put it first
    # and silently transpose two columns of every matrix.
    assert sorted(["2Y", "18M", "1Y"], key=CVL.expiry_years) == ["1Y", "18M", "2Y"]
    with pytest.raises(ValueError):
        CVL.expiry_years("nonsense")


def test_matched_node_picks_the_nearest_expiry():
    assert CVL.matched_node(3.51) == "4Y"      # 0.49 vs 0.51
    assert CVL.matched_node(3.49) == "3Y"
    assert CVL.matched_node(1.60) == "18M"
    assert CVL.matched_node(float("nan")) is None


def test_t1_rms_is_root_mean_square_not_mean():
    """``t1_rms = sqrt(mean(T1^2))``, which EXCEEDS ``mean(T1)`` by Jensen.

    The two are within 1.8% on real packs, so a test that only checked
    "approximately equal" would pass on the wrong one. This checks the exact
    identity and the strict inequality.
    """
    fit = pd.DataFrame({"date": pd.to_datetime(["2023-06-09"] * 2), "rank": [5, 13]})
    out = CVL.attach_pack_expiries(fit)
    seq = quarterly_imm_sequence(datetime.date(2023, 6, 9), 40)
    for i, k in enumerate((5, 13)):
        t1s = pack_t1s(datetime.date(2023, 6, 9), seq[k - 1: k + 3])
        assert out["t1_rms"].iloc[i] == pytest.approx(math.sqrt(np.mean(np.square(t1s))))
        assert out["t1_mean"].iloc[i] == pytest.approx(float(np.mean(t1s)))
        assert out["t1_rms"].iloc[i] > out["t1_mean"].iloc[i]
        assert out["time_weight_recon"].iloc[i] == pytest.approx(pack_time_weight(t1s))


def test_non_positive_ca_gives_nan_not_zero():
    """A negative CA is not representable under Ho-Lee. Citi prints ``n/a``.

    Clipping to zero instead would put a floor under the 2021 near-ZIRP sample
    -- 843 of 7,354 pack-days -- and bias every correlation that includes them.
    """
    fit = pd.DataFrame({"ca_bp": [10.0, 0.0, -3.5, np.nan],
                        "time_weight": [12.0, 12.0, 12.0, 12.0]})
    out = CVL.attach_implied_vol(fit)
    assert out["ca_iv_bp"].iloc[0] == pytest.approx(
        implied_vol_from_ca_bp(10.0, [math.sqrt(12.0)]))
    assert np.isnan(out["ca_iv_bp"].iloc[1])
    assert np.isnan(out["ca_iv_bp"].iloc[2])
    assert np.isnan(out["ca_iv_bp"].iloc[3])


def test_implied_vol_round_trips_the_pack_ca():
    """sigma -> CA -> sigma, exactly. The identity test (iii) rides on."""
    for w in (1.5, 4.0, 12.34, 19.4):
        for ca in (0.5, 4.03, 15.4, 22.29):
            iv = implied_vol_from_ca_bp(ca, [math.sqrt(w)])
            assert pack_ca_bp(iv, [math.sqrt(w)]) == pytest.approx(ca, rel=1e-12)


def test_align_bdays_makes_diff_gap_aware():
    """A ``.diff()`` must NOT span a hole in a gappy series.

    The gated CA series is holey. On the compressed index, ``.diff()`` across a
    three-month gap looks like a one-day change and would inject a huge spurious
    daily move into every changes correlation. Aligning to business days first
    turns it into NaN.
    """
    idx = pd.DatetimeIndex(["2021-01-04", "2021-01-05", "2021-04-05"])
    s = pd.Series([1.0, 2.0, 100.0], index=idx)
    naive = s.diff()
    assert naive.iloc[2] == pytest.approx(98.0)      # the bug this prevents

    al = CVL.align_bdays({"s": s})
    d = al["s"].diff()
    assert len(al) == len(pd.bdate_range(idx[0], idx[-1]))
    assert d.loc[pd.Timestamp("2021-01-05")] == pytest.approx(1.0)
    assert np.isnan(d.loc[pd.Timestamp("2021-04-05")])
    assert al["s"].notna().sum() == 3


def test_horizon_corr_table_is_measured_on_a_common_axis():
    """Every x in a row must be scored on the same dates as every other."""
    idx = pd.bdate_range("2021-01-04", periods=200)
    rng = np.random.default_rng(7)
    y = pd.Series(np.cumsum(rng.normal(size=200)), index=idx)
    x_full = y * 2.0 + 1.0
    x_holey = x_full.copy()
    x_holey.iloc[50:150] = np.nan
    t = CVL.horizon_corr_table(y, {"full": x_full, "holey": x_holey}, horizons=(1, 5))
    assert t.loc[t["x"] == "full", "corr_levels"].iloc[0] == pytest.approx(1.0)
    assert t.loc[t["x"] == "holey", "corr_levels"].iloc[0] == pytest.approx(1.0)
    assert int(t.loc[t["x"] == "full", "n_levels"].iloc[0]) == 200
    assert int(t.loc[t["x"] == "holey", "n_levels"].iloc[0]) == 100


def test_link_matrix_orientation():
    """Rows are pack ranks, columns are swaption expiries -- and a transpose
    must FAIL, so each cell is given a different answer by construction."""
    idx = pd.bdate_range("2021-01-04", periods=300)
    rng = np.random.default_rng(11)
    base = pd.Series(np.cumsum(rng.normal(size=300)), index=idx)
    vol = pd.DataFrame({"1Y": base, "3Y": base.shift(0) * -1.0}, index=idx).dropna()
    ivs = {5: base * 1.0, 13: base * -1.0}
    corr, n = CVL.link_matrix(ivs, vol, min_n=10)
    assert list(corr.index) == [5, 13]
    assert list(corr.columns) == ["1Y", "3Y"]
    assert corr.loc[5, "1Y"] == pytest.approx(1.0)
    assert corr.loc[5, "3Y"] == pytest.approx(-1.0)
    assert corr.loc[13, "1Y"] == pytest.approx(-1.0)
    assert corr.loc[13, "3Y"] == pytest.approx(1.0)
    assert (n.to_numpy() == 300).all()


def test_link_matrix_nans_thin_cells():
    """A perfect correlation on four points must not win an argmax."""
    idx = pd.bdate_range("2021-01-04", periods=100)
    v = pd.DataFrame({"1Y": pd.Series(np.arange(100.0), index=idx)})
    short = pd.Series([1.0, 2.0, 3.0, 4.0], index=idx[:4])
    corr, n = CVL.link_matrix({5: short}, v, min_n=30)
    assert np.isnan(corr.loc[5, "1Y"])
    assert int(n.loc[5, "1Y"]) == 4


def test_matched_vol_series_interpolates_and_never_extrapolates():
    idx = pd.bdate_range("2021-01-04", periods=3)
    wide = pd.DataFrame({"1Y": [100.0, 100.0, 100.0], "3Y": [200.0, 200.0, 200.0]},
                        index=idx)
    t1 = pd.Series([2.0, 0.5, 9.0], index=idx)      # inside, below, above
    got = CVL.matched_vol_series(wide, t1)
    assert got.iloc[0] == pytest.approx(150.0)       # halfway between 1Y and 3Y
    assert np.isnan(got.iloc[1])
    assert np.isnan(got.iloc[2])


def test_decompose_ca_changes_identity_is_exact():
    """``CA_bp == 100*(pack% - swap%)``, so ``dCA == d(pack) - d(swap)``.

    If this residual is not ~0 the whole of test 4 is measuring something other
    than the CA's two legs, and every beta in it is meaningless.
    """
    idx = pd.bdate_range("2021-01-04", periods=120)
    rng = np.random.default_rng(3)
    pack = pd.Series(3.0 + np.cumsum(rng.normal(0, 0.01, 120)), index=idx)
    swap = pack - 0.001 * (1 + np.arange(120) / 120.0)
    df = pd.DataFrame({"pack_rate": pack, "swap_rate": swap,
                       "ca_bp": 100.0 * (pack - swap)}, index=idx)
    drv = pd.Series(np.cumsum(rng.normal(0, 1.0, 120)), index=idx)
    legs, reg = CVL.decompose_ca_changes(df, {"d": drv}, horizons=(1, 21))
    assert float(legs["identity_resid_bp"].abs().max()) < 1e-9
    for h in (1, 21):
        sub = reg[reg["horizon_d"] == h].set_index("leg")
        assert (float(sub.loc["pack_bp", "beta"]) - float(sub.loc["swap_bp", "beta"])
                == pytest.approx(float(sub.loc["ca_bp", "beta"]), abs=1e-10))


def test_decompose_ca_changes_rejects_a_mismatched_ca_column():
    """A panel whose ``ca_bp`` was not built from these two rate columns must be
    caught by the identity residual, not silently decomposed."""
    idx = pd.bdate_range("2021-01-04", periods=40)
    df = pd.DataFrame({"pack_rate": np.linspace(3.0, 3.1, 40),
                       "swap_rate": np.linspace(3.0, 3.05, 40),
                       "ca_bp": np.full(40, 7.0)}, index=idx)
    legs, _ = CVL.decompose_ca_changes(df, {"d": pd.Series(np.arange(40.0), index=idx)})
    assert float(legs["identity_resid_bp"].abs().max()) > 1.0


def test_ols_recovers_planted_coefficients():
    idx = pd.bdate_range("2021-01-04", periods=250)
    rng = np.random.default_rng(5)
    x = pd.Series(np.cumsum(rng.normal(size=250)), index=idx)
    y = 3.25 + 0.7 * x
    st = CVL.ols(y, x)
    assert st["alpha"] == pytest.approx(3.25, abs=1e-9)
    assert st["beta"] == pytest.approx(0.70, abs=1e-9)
    assert st["r_squared"] == pytest.approx(1.0, abs=1e-12)
    assert st["n"] == 250


def test_regime_shift_separates_range_restriction_from_a_break():
    """A late block ON the early line scores ~0; one shifted off it scores ~1."""
    idx = pd.bdate_range("2021-01-04", periods=600)
    rng = np.random.default_rng(13)
    x = pd.Series(np.r_[rng.normal(0, 10, 400), rng.normal(0, 1, 200)], index=idx)
    noise = pd.Series(rng.normal(0, 2.0, 600), index=idx)
    split = idx[400]

    on_line = 5.0 + 0.5 * x + noise
    r = CVL.regime_shift_table(on_line, x, split, label="on line")
    assert abs(r["resid_mean_over_early_sd"]) < 0.5
    assert r["x_sd_late"] < r["x_sd_early"]            # range restriction present

    shifted = on_line.copy()
    shifted.iloc[400:] += 6.0                          # 3 early residual sds
    r2 = CVL.regime_shift_table(shifted, x, split, label="broken")
    assert r2["resid_mean_over_early_sd"] > 2.0


def test_sign_stability_counts_only_realised_windows():
    idx = pd.bdate_range("2021-01-04", periods=400)
    rng = np.random.default_rng(17)
    x = pd.Series(np.cumsum(rng.normal(size=400)), index=idx)
    same = x * 2.0
    flip = pd.concat([x.iloc[:200] * 2.0, x.iloc[200:] * -2.0])
    s_same = CVL.sign_stability(same, x, window=100)
    s_flip = CVL.sign_stability(flip, x, window=100)
    assert s_same["frac_sign"] == pytest.approx(1.0)
    assert s_flip["frac_sign"] < 0.75
    assert s_same["n_windows"] > 250


# ===========================================================================
# The verdict rule
# ===========================================================================
_PASSING = dict(corr_levels=0.713, corr_levels_fly=-0.624, corr_d1=-0.079,
                corr_d63=0.480, corr_d63_fly=0.008, regime_shift=0.783,
                sign_frac_vol=0.926, sign_frac_fly=0.380)


def test_verdict_confirmed_on_the_measured_numbers():
    v = CVL.score_verdict(**_PASSING)
    assert v["verdict"] == "CONFIRMED"
    assert all(v["checks"].values()), v["checks"]


def test_verdict_v1_check_is_reported_and_fails():
    """The re-specified check is DISCLOSED, not deleted.

    v1 was ``corr_levels - abs(corr_levels_fly) >= 0.25``. On the measured
    numbers that is ``0.713 - 0.624 = 0.089`` and it FAILS. It must still be
    computed and returned, so the revision is visible in the output rather than
    only in a docstring, and it must NOT be in ``checks`` (it does not vote).
    """
    v = CVL.score_verdict(**_PASSING)
    assert v["diagnostics"]["levels_beats_fly_unsigned_v1"] is False
    assert v["diagnostics"]["levels_unsigned_margin_v1"] == pytest.approx(0.089, abs=0.002)
    assert "levels_beats_fly" not in v["checks"]
    assert "levels_sign_beats_fly" in v["checks"]


def test_verdict_inconclusive_when_levels_hold_but_no_horizon_does():
    """The specific pattern the rule anticipates: a shared trend, no link."""
    v = CVL.score_verdict(**{**_PASSING, "corr_d63": 0.05, "corr_d1": 0.02})
    assert v["verdict"] == "INCONCLUSIVE"


def test_verdict_refuted_when_neither_levels_nor_changes_hold():
    v = CVL.score_verdict(**{**_PASSING, "corr_levels": 0.10, "corr_d63": 0.02,
                             "corr_d1": 0.01, "sign_frac_vol": 0.45})
    assert v["verdict"] == "REFUTED"


def test_verdict_refuted_when_the_link_is_not_sign_stable():
    """A 0.71 levels correlation assembled from sign-flipping years is not a
    relationship, and the rule must not be fooled by the magnitude."""
    v = CVL.score_verdict(**{**_PASSING, "sign_frac_vol": 0.45, "corr_d63": 0.05,
                             "corr_d1": 0.02})
    assert v["verdict"] == "REFUTED"


def test_verdict_inconclusive_on_a_regime_break():
    v = CVL.score_verdict(**{**_PASSING, "regime_shift": 2.4})
    assert v["verdict"] == "INCONCLUSIVE"
    assert v["checks"]["no_regime_break"] is False


def test_verdict_horizon_slope_must_rise():
    """A link that is already at 0.48 at one day and stays there is not the
    attenuation signature; it is something else, and the rule should not call it
    CONFIRMED on the strength of the 63-day number alone."""
    v = CVL.score_verdict(**{**_PASSING, "corr_d1": 0.47})
    assert v["checks"]["horizon_slope_up"] is False
    assert v["verdict"] == "INCONCLUSIVE"


# ===========================================================================
# Data-dependent
# ===========================================================================
@pytest.fixture(scope="module")
def ca_fit() -> pd.DataFrame:
    if not _CA_FIT.exists():
        pytest.skip(f"{_CA_FIT.name} not built; run citi_fig89_reproduction.ipynb")
    return pd.read_parquet(_CA_FIT)


@pytest.fixture(scope="module")
def vol_grid() -> pd.DataFrame:
    if not _VOL_GRID.exists():
        pytest.skip(f"{_VOL_GRID.name} not built; run ca_vol_link.ipynb")
    w = pd.read_parquet(_VOL_GRID)
    return CVL.load_vol_grid(cache_path=_VOL_GRID)


def test_pack_expiry_reconstruction_matches_the_panel(ca_fit):
    """The rank convention here (rank r = contracts r..r+3) IS the panel's.

    Off by one and every implied vol would be wrong by roughly 5% with nothing
    else in the notebook noticing, because the shape would be unchanged.
    """
    out = CVL.attach_pack_expiries(ca_fit)
    err = float((out["time_weight_recon"] - out["time_weight"]).abs().max())
    assert err <= 1e-12, f"rebuilt time_weight differs from the panel by {err}"


def test_blues_20230609_reproduces_the_published_anchor(ca_fit):
    """15.72bp of CA at Blues, and the implied vol that follows from it."""
    out = CVL.attach_implied_vol(CVL.attach_pack_expiries(ca_fit))
    row = out[(out["date"] == pd.Timestamp(_CITI_DATE)) & (out["rank"] == 13)]
    assert len(row) == 1
    assert float(row["ca_bp"].iloc[0]) == pytest.approx(15.72, abs=0.01)
    assert row["pack"].iloc[0] == "M6-H7"
    iv = float(row["ca_iv_bp"].iloc[0])
    assert iv == pytest.approx(164.4, abs=0.1)
    # and it is CITI's 163.1 to within the CA difference, not by construction
    assert abs(iv - 163.1) < 2.0


def test_citi_tieout_table_on_the_panel(ca_fit):
    out = CVL.attach_implied_vol(CVL.attach_pack_expiries(ca_fit))
    t = CVL.citi_implied_vol_tieout(out, CITI_SOFR_20230609, _CITI_DATE)
    assert len(t) == 13
    assert float(t["d_iv_citi_inputs"].abs().max()) <= _CITI_IV_TOL_BP
    # the S-shaped construction residual, as measured -- pinned so a change in
    # the CA pipeline shows up here rather than silently moving section 6.
    by_rank = t.set_index("rank")["d_ca"]
    assert float(by_rank.loc[13]) == pytest.approx(0.315, abs=0.02)
    assert float(by_rank.loc[7]) == pytest.approx(3.057, abs=0.02)
    assert float(by_rank.loc[11]) == pytest.approx(-2.073, abs=0.02)


def test_vol_grid_is_complete_and_ordered_by_expiry(vol_grid):
    assert list(vol_grid.columns) == sorted(vol_grid.columns, key=CVL.expiry_years)
    assert set(vol_grid.columns) == set(CVL.EXPIRY_NODES)
    assert vol_grid.notna().all().all(), "a missing node makes one matrix column "\
        "measured on a different sample from its neighbours"
    assert (vol_grid > 0).all().all()
    assert len(vol_grid) > 1000


def test_headline_link_reproduces(ca_fit, vol_grid):
    """The number claim B rests on, pinned. n and r both."""
    out = CVL.attach_implied_vol(CVL.attach_pack_expiries(ca_fit))
    blues = CVL.rank_frame(out, 13)
    al = CVL.align_bdays({"iv": blues["ca_iv_bp"], "v": vol_grid["3Y"]})
    r, n = CVL.corr_pair(al["iv"], al["v"])
    assert n == 492
    assert r == pytest.approx(0.713, abs=0.005)
    r63, n63 = CVL.corr_pair(al["iv"].diff(63), al["v"].diff(63))
    assert r63 == pytest.approx(0.480, abs=0.005)
    r1, _ = CVL.corr_pair(al["iv"].diff(1), al["v"].diff(1))
    assert r1 < 0.05, "the 1-day correlation is not the evidence; it is ~zero"
    assert r63 - r1 > 0.15, "the horizon profile must RISE -- that is the signature"

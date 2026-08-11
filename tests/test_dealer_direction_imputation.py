"""The capped-notional imputation, pinned.

Three things can go wrong here and none of them announce themselves:

* the **fitter** can be quietly wrong -- a censored MLE that does not recover a
  known parameter still returns a number, and every downstream table is then
  precise and false. So the fitter is validated against simulated data whose
  answer is known before it is allowed near the tape (sections 1-2);
* the **frozen calibration** can be mis-transcribed -- the multipliers were
  measured in ``scratch/partB_*``; here they are recomputed from the stored
  ``(mu, sigma, cap)`` so a typo cannot survive (section 3);
* the **application** can double-count -- scaling notional before pricing runs
  the multiplier through the pricing path a second time, so the only sanctioned
  application is to the signed KRD, and the module must not expose any other
  (section 5).

Everything here is offline and seeded: no DB, no network, so it runs in the
fast gate.
"""
from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import pytest

from SDRUtils.dealer_direction import imputation as imp
from SDRUtils.dealer_direction import types as ddt


# --------------------------------------------------------------------------
# 1. The fitter recovers known parameters. This is the self-test.
# --------------------------------------------------------------------------

def _lognormal_sample(rng, mu, sigma, u, cap, n):
    """A left-truncated lognormal sample split the way the tape splits it."""
    z = np.exp(rng.normal(mu, sigma, n))
    z = z[z >= u]
    return z[z < cap], int((z >= cap).sum())


def test_lognormal_censored_mle_recovers_known_parameters():
    """The estimator the module ships, against an answer known in advance.

    Simulate a lognormal, censor it at the cap exactly as Part 43 does, hand
    the fitter the sub-cap observations plus the *count* above the cap, and
    require the generating parameters back.

    The mu tolerance is 0.30, not 0.15, and the reason is not slack in the
    fitter. At (mu=16, sigma=1.8) the window ``[u, C)`` starts 0.96 sigma ABOVE
    mu, so only the top ~16% of the distribution is ever observed and mu is
    weakly identified: the fit returns 15.74, and its log-likelihood on that
    sample is HIGHER than the true parameters' (-366731.9 vs -366734.7). An MLE
    that beats the truth on the truth's own sample is working; the residual is
    identification, not bias. That is asserted below rather than assumed, and
    the estimand -- which is what the module actually consumes -- is checked to
    5% in :func:`test_lognormal_mean_above_matches_the_simulated_conditional_mean`.
    """
    rng = np.random.default_rng(20260811)
    u, cap = 5e7, 5e8
    for mu_true, sigma_true in ((17.0, 1.2), (16.0, 1.8), (18.0, 0.9)):
        sub, n_cap = _lognormal_sample(rng, mu_true, sigma_true, u, cap, 120_000)
        w = np.ones_like(sub)
        mu, sigma = imp.lognormal_censored_mle(sub, w, u, cap, n_cap)
        assert mu == pytest.approx(mu_true, abs=0.30)
        assert sigma == pytest.approx(sigma_true, abs=0.12)

        stats = imp._suffstats(np.log(sub), w)
        args = (stats, np.log(u), np.log(cap), float(n_cap))
        assert (imp._ln_negll([mu, np.log(sigma)], *args)
                <= imp._ln_negll([mu_true, np.log(sigma_true)], *args))


def test_censored_fit_reproduces_the_capped_count_and_truncation_only_does_not():
    """Why the censored MLE is the one that ships.

    The truncation-only MLE never sees how many prints landed at the cap, so
    nothing stops its implied tail mass from disagreeing with the observed one
    -- measured on the tape at -72% to +2400%. The censored fit uses that count
    as data, so its prediction cannot wander far from it.
    """
    rng = np.random.default_rng(7)
    u, cap = 5e7, 5e8
    sub, n_cap = _lognormal_sample(rng, 17.4, 1.5, u, cap, 200_000)
    w = np.ones_like(sub)

    mu_c, s_c = imp.lognormal_censored_mle(sub, w, u, cap, n_cap)
    mu_t, s_t = imp.lognormal_truncated_mle(sub, w, u, cap)

    pred_c = imp.predicted_capped_count(w.sum(), imp.lognormal_tail_ratio(mu_c, s_c, u, cap))
    pred_t = imp.predicted_capped_count(w.sum(), imp.lognormal_tail_ratio(mu_t, s_t, u, cap))

    assert abs(pred_c / n_cap - 1.0) < 0.05
    # not a claim that the truncation-only fit is useless, a claim that it is
    # unconstrained where it matters: it is the worse of the two on this test.
    assert abs(pred_c / n_cap - 1.0) < abs(pred_t / n_cap - 1.0)


def test_lognormal_mean_above_matches_the_simulated_conditional_mean():
    """E[N | N > C] is the estimand; check it against the sample it came from."""
    rng = np.random.default_rng(11)
    u, cap = 5e7, 5e8
    z = np.exp(rng.normal(17.4, 1.5, 400_000))
    z = z[z >= u]
    sub, above = z[z < cap], z[z >= cap]
    mu, sigma = imp.lognormal_censored_mle(sub, np.ones_like(sub), u, cap, len(above))
    fitted = imp.lognormal_mean_above(mu, sigma, cap)
    assert fitted == pytest.approx(above.mean(), rel=0.05)


def test_pareto_censored_mle_recovers_alpha_where_naive_hill_is_biased():
    """The tail index is reported, so it too has to be right.

    The naive Hill estimator ignores the right truncation at the cap and reads
    the tail as thinner than it is; the censored MLE carries the truncation
    term. If Hill were unbiased here the test would not be exercising the
    correction, so that is asserted as well.
    """
    rng = np.random.default_rng(3)
    u, cap = 5e7, 5e8
    for alpha_true in (0.8, 1.2, 1.8):
        z = u * (rng.random(150_000) ** (-1.0 / alpha_true))
        sub, n_cap = z[z < cap], int((z >= cap).sum())
        w = np.ones_like(sub)
        alpha = imp.pareto_censored_mle(sub, w, u, cap, n_cap)
        hill = len(sub) / np.sum(np.log(sub / u))
        assert alpha == pytest.approx(alpha_true, rel=0.05)
        assert abs(hill - alpha_true) > 0.05 * alpha_true


def test_grouped_frequency_path_equals_the_raw_path():
    """The tape is fed to the fitter as (value, count), not as rows.

    Part 43 notionals are rounded onto a round-number lattice, so the tape
    collapses to a few thousand distinct values and the fit is run weighted.
    Weighted and unweighted must be the same estimator or the whole calibration
    is off by an unknown amount.
    """
    rng = np.random.default_rng(5)
    u, cap = 5e7, 5e8
    z = u * (rng.random(200_000) ** (-1.0 / 1.7))
    sub, n_cap = z[z < cap], int((z >= cap).sum())
    lattice = np.round(sub / 1e6) * 1e6
    lattice = lattice[(lattice >= u) & (lattice < cap)]
    values, counts = np.unique(lattice, return_counts=True)

    a_raw = imp.pareto_censored_mle(lattice, np.ones_like(lattice), u, cap, n_cap)
    a_grp = imp.pareto_censored_mle(values, counts.astype(float), u, cap, n_cap)
    m_raw = imp.lognormal_censored_mle(lattice, np.ones_like(lattice), u, cap, n_cap)
    m_grp = imp.lognormal_censored_mle(values, counts.astype(float), u, cap, n_cap)

    assert a_raw == pytest.approx(a_grp, abs=1e-9)
    e_raw = imp.lognormal_mean_above(*m_raw, cap)
    e_grp = imp.lognormal_mean_above(*m_grp, cap)
    assert e_raw == pytest.approx(e_grp, rel=1e-3)


def test_fit_cell_refuses_a_sample_too_small_to_fit():
    """A cell with no tail is not fitted with a wide prior; it returns nothing."""
    rng = np.random.default_rng(1)
    u, cap = 5e7, 5e8
    z = np.exp(rng.normal(17.0, 1.0, 300))
    sub = z[(z >= u) & (z < cap)][:20]
    assert imp.fit_cell(sub, np.ones_like(sub), u, cap, 3.0) is None


# --------------------------------------------------------------------------
# 2. The infinite-mean trap, kept visible.
# --------------------------------------------------------------------------

def test_pareto_mean_is_infinite_below_alpha_one_and_says_so():
    """alpha <= 1 has no mean. It is reported as inf, never as a number."""
    assert imp.pareto_mean_above(0.75, 1e8) == float("inf")
    assert imp.pareto_mean_above(1.0, 1e8) == float("inf")
    assert np.isfinite(imp.pareto_mean_above(1.4, 1e8))
    assert imp.pareto_mean_above(2.0, 1e8) == pytest.approx(2e8)


def test_every_band_reports_a_tail_index_and_whether_its_mean_exists():
    """Requirement: report the fitted tail index and state if the mean exists.

    The trap fired at u = C/10 (alpha < 1 in 10 of 18 cells) and has not fully
    cleared at the shipped u = C/4: two short-tenor V1 cells still sit below 1.
    That is a statement about ``[u, C)`` being the *body* of the distribution,
    not about a monstrous tail -- and it does not touch the lognormal headline,
    which is why both numbers travel together on every band.
    """
    below_one = 0
    for band in imp.CAP_BANDS:
        assert band.tail_index > 0.0
        assert band.tail_mean_exists == (band.tail_index > 1.0)
        below_one += band.tail_index <= 1.0
    assert below_one == 2, "the alpha<1 cells at u=C/4 are V1 <=46d and V1 46d-3m"


# --------------------------------------------------------------------------
# 3. The frozen calibration is what was measured.
# --------------------------------------------------------------------------

def test_frozen_multiplier_is_recomputable_from_the_stored_parameters():
    """A mis-transcribed multiplier is invisible; a recomputed one is not.

    ``multiplier = E[N | N > C] / C`` is a deterministic function of the stored
    ``(mu, sigma, cap)``, so storing all four lets the table check itself.
    """
    for band in imp.CAP_BANDS:
        recomputed = imp.lognormal_mean_above(band.ln_mu, band.ln_sigma, band.cap) / band.cap
        assert recomputed == pytest.approx(band.multiplier, rel=1e-3), band.label


def test_the_calibration_covers_the_measured_schedule():
    """Nine bands, two vintages, distinct caps within a vintage."""
    assert len(imp.CAP_BANDS) == 18
    for vintage in (imp.VINTAGE_V1, imp.VINTAGE_V2):
        bands = imp.bands_for_vintage(vintage)
        assert len(bands) == 9
        caps = [b.cap for b in bands]
        assert len(set(caps)) == 9, "notional-matching needs caps unique per vintage"
        assert caps == sorted(caps, reverse=True), "cap falls monotonically in tenor"
        los = [b.lo for b in bands]
        assert los == sorted(los) and los[0] == 0.0


def test_every_multiplier_is_above_one_and_not_absurd():
    """An imputed size below the cap would contradict the censoring itself.

    The upper guard is the measured range (1.6-4.0); anything outside it means
    the fit collapsed onto a power-law mimic and extrapolated, which is the
    failure mode ``ln_degenerate`` was built to catch.
    """
    for band in imp.CAP_BANDS:
        assert 1.0 < band.multiplier < 5.0, band.label
        assert band.expected_notional == pytest.approx(band.multiplier * band.cap)


def test_the_fit_reproduces_the_capped_count_in_every_cell():
    """The censored fit's own test, carried as a stored diagnostic.

    +-19% in every cell at u = C/4. If a future refit widens this, the number
    moves here first and the failure is loud.
    """
    for band in imp.CAP_BANDS:
        assert abs(band.capped_count_error) <= 0.19, band.label


def test_headline_shares_sit_inside_the_quoted_sensitivity_band():
    lo, hi = imp.SENSITIVITY_DV01_SHARE
    assert lo < imp.IMPUTED_DV01_SHARE <= hi
    lo_n, hi_n = imp.SENSITIVITY_NOTIONAL_SHARE
    assert lo_n < imp.IMPUTED_NOTIONAL_SHARE <= hi_n


def test_the_two_families_fail_about_equally_so_the_band_is_within_family():
    """The quoted band is threshold sensitivity, and that is not the big risk.

    Absolute KS is 0.07-0.28 for the lognormal *and* the Pareto -- notional is
    rounded onto a round-number lattice and no continuous law fits a lattice --
    and at the shipped u = C/4 the Pareto is the closer of the two in 10 of 18
    cells, by at most 0.020. So the family choice is not an empirical win, and
    the sensitivity band does not contain the uncertainty it creates. Both
    statistics are stored per band so this stays checkable rather than asserted
    in prose.
    """
    ks_ln = [b.ks_lognormal for b in imp.CAP_BANDS]
    ks_par = [b.ks_pareto for b in imp.CAP_BANDS]
    for series in (ks_ln, ks_par):
        assert 0.069 <= min(series) and max(series) <= 0.276

    lognormal_wins = sum(a < b for a, b in zip(ks_ln, ks_par))
    assert lognormal_wins == 6, "at u=C/4 the lognormal is NOT the better KS fit"
    assert max(abs(a - b) for a, b in zip(ks_ln, ks_par)) < 0.021


def test_direction_neutrality_is_recorded_as_unresolved_not_as_neutral():
    """Requirement 5: capped x direction, and what the answer actually was.

    Two odds ratios are stored because two methods disagree: the curve-based
    classifiers say capped prints are 1.34x more likely to be labelled RECEIVED
    (CI excludes 1), the curve-free tick rule says 0.88 (CI includes 1). Their
    intervals do not overlap, so this is not one estimate with noise around it,
    and the module must not be read as having shown neutrality. The assertion
    below is the disagreement itself: if a future measurement makes the two
    agree, this fails and the docstring gets rewritten deliberately.
    """
    curve_or, curve_lo, curve_hi = imp.CAPPED_RECEIVED_ODDS_RATIO_CURVE_BASED
    tick_or, tick_lo, tick_hi = imp.CAPPED_RECEIVED_ODDS_RATIO_CURVE_FREE

    assert curve_lo > 1.0, "the curve-based 2x2 does show a skew"
    assert tick_lo < 1.0 < tick_hi, "the curve-free 2x2 does not"
    assert tick_hi < curve_lo, "the two intervals must be disjoint for the claim to hold"
    assert 0.0 < imp.UNCLASSIFIABLE_SHARE_OF_IMPUTED_DV01 < 0.10
    assert imp.IMPUTED_SHARE_OF_UNCLASSIFIABLE_DV01 > 0.25, (
        "the overlap is the point: most unclassifiable DV01 is capped DV01")


# --------------------------------------------------------------------------
# 4. The schedule lookup.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("day", "vintage"),
    [
        (datetime.date(2024, 3, 1), imp.VINTAGE_V1),
        (datetime.date(2024, 10, 4), imp.VINTAGE_V1),   # last V1 print
        (datetime.date(2024, 10, 5), imp.VINTAGE_V1),   # the weekend between
        (datetime.date(2024, 10, 6), imp.VINTAGE_V1),
        (datetime.date(2024, 10, 7), imp.VINTAGE_V2),   # first V2 print
        (datetime.date(2026, 8, 7), imp.VINTAGE_V2),
    ],
)
def test_vintage_boundary_is_the_measured_changeover(day, vintage):
    """Measured: last V1 print 2024-10-04, first V2 print 2024-10-07, no overlap."""
    assert imp.vintage_for(day) == vintage


def test_cap_lookup_is_total_over_tenor():
    """Every tenor gets a cap.

    The empirically merged bands have holes (V1 10.5-10.75, nothing capped
    beyond 41y) because bins with n < 25 were dropped. A lookup with a hole in
    it returns None on a live print, so the bands are contiguous by
    construction: each runs from its own ``lo`` to the next band's, the last one
    to infinity.
    """
    for day in (datetime.date(2024, 5, 1), datetime.date(2025, 5, 1)):
        for tenor in (0.003, 0.12, 0.5, 1.0, 2.0, 2.25, 10.6, 30.0, 41.5, 60.0):
            cap = imp.cap_for(tenor, day)
            assert cap is not None and cap > 0


def test_cap_falls_with_tenor_and_rose_at_the_2024_recalibration():
    """Both directions of the measured schedule, on one assertion each."""
    day1, day2 = datetime.date(2024, 5, 1), datetime.date(2025, 5, 1)
    assert imp.cap_for(0.05, day1) == 6.4e9
    assert imp.cap_for(0.05, day2) == 17e9
    assert imp.cap_for(7.0, day1) == 170e6
    assert imp.cap_for(7.0, day2) == 470e6
    caps = [imp.cap_for(t, day2) for t in (0.05, 0.2, 0.4, 0.8, 1.5, 3.0, 7.0, 20.0, 35.0)]
    assert caps == sorted(caps, reverse=True)


def test_the_tenor_mismatch_flag_fires_on_the_measured_edge_case():
    """1.92% of capped legs have keys that disagree, and they are surfaced.

    A V1 print at $170mm (the 5y-10y cap) with a tenor of 25y is a real row on
    the tape, not a hypothetical -- 173 legs carry that cap at tenors from 5.06
    to 25.02 years. It is still imputed, off the cap that was actually applied,
    but a consumer restricting to the fit's own population needs to see it.
    """
    legs = pd.DataFrame({
        "notional": [170e6, 170e6],
        "as_of_date": [datetime.date(2024, 5, 1)] * 2,
        "tenor_years": [7.0, 25.0],
        "is_capped": [True, True],
    })
    out = imp.impute_frame(legs)
    assert list(out["notional_imputed"]) == [True, True]
    assert list(out["notional_impute_factor"]) == [pytest.approx(3.9537, abs=1e-3)] * 2
    assert bool(out.loc[0, "notional_cell_tenor_mismatch"]) is False
    assert bool(out.loc[1, "notional_cell_tenor_mismatch"]) is True
    # and it is absent, not guessed, when there is no tenor column
    assert "notional_cell_tenor_mismatch" not in imp.impute_frame(
        legs.drop(columns="tenor_years")).columns


def test_a_capped_print_is_identified_by_its_notional_not_its_tenor():
    """Measured: 68,945 of 68,946 capped prints sit exactly on a schedule value.

    The tenor edges are fuzzy where the regulator's tenor and the tape's
    date-derived ``tenor_years`` disagree -- six V1 prints at 11.008y carry the
    5y-10y cap of $170mm, and two at 31.5y carry the 10y-30y cap. The printed
    notional IS the cap, so it is the identifier; tenor is the fallback.
    """
    day = datetime.date(2024, 5, 1)
    band = imp.band_for_capped_notional(170e6, day)
    assert band is not None and band.cap == 170e6
    assert imp.band_for_tenor(11.008, day).cap == 120e6      # tenor disagrees
    assert imp.tenor_band_agrees(170e6, 11.008, day) is False
    assert imp.tenor_band_agrees(170e6, 7.0, day) is True


def test_an_unrecognised_cap_value_is_flagged_not_scaled():
    """The one measured exception: a $78,613,002 print flagged capped on
    2025-09-17 at 0.25y, where the V2 cap is $7.5bn. Nothing about that print
    says how it was censored, so it is not imputed -- it is named.
    """
    r = imp.impute(78_613_002.0, datetime.date(2025, 9, 17), is_capped=True,
                   tenor_years=0.246575)
    assert r.notional_imputed is False
    assert r.notional_impute_factor is None
    assert r.reason == imp.REASON_CAP_UNRECOGNISED


# --------------------------------------------------------------------------
# 5. Application: flag, never silently substitute.
# --------------------------------------------------------------------------

def test_an_uncapped_leg_is_untouched():
    r = imp.impute(250e6, datetime.date(2025, 5, 1), is_capped=False, tenor_years=7.0)
    assert r.notional_imputed is False
    assert r.notional_impute_factor is None
    assert r.expected_notional is None
    assert r.reason == imp.REASON_NOT_CAPPED


def test_a_capped_leg_carries_its_multiplier_and_the_tail_index():
    r = imp.impute(470e6, datetime.date(2025, 5, 1), is_capped=True, tenor_years=7.0)
    assert r.notional_imputed is True
    assert r.notional_impute_factor > 1.0
    assert r.expected_notional == pytest.approx(r.notional_impute_factor * 470e6)
    assert r.tail_index > 0
    assert r.tail_mean_exists in (True, False)
    assert r.reason == imp.REASON_IMPUTED


def test_the_imputation_fields_are_the_provenance_fields():
    """The audit trail is the point: a consumer must be able to drop these rows.

    ``types.Provenance`` already declares ``notional_imputed`` and
    ``notional_impute_factor``; if the imputation ever stopped filling exactly
    those, the flag would go missing and the substitution would be silent.
    """
    r = imp.impute(470e6, datetime.date(2025, 5, 1), is_capped=True, tenor_years=7.0)
    fields = r.provenance_fields()
    assert set(fields) == {"notional_imputed", "notional_impute_factor"}
    prov = ddt.Provenance(
        unit_key="u", curve_name="c", curve_timestamp=pd.Timestamp("2025-05-01"),
        snapshot_lag_seconds=60.0, snapshot_policy="STRICT",
        pricing_clock_field="execution_timestamp", rule="RATE_VS_MID",
        risk_sanity_reason=None, tau_bucket=None, code_vintage="test", **fields)
    assert prov.notional_imputed is True
    assert prov.notional_impute_factor == r.notional_impute_factor


def test_impute_frame_adds_columns_and_never_edits_notional():
    """Requirement 3 mechanically: the imputed value lives in its own column.

    Row 2 is the vintage guard doing its job. $120mm IS a cap -- the V1 10y-30y
    one -- but on 2025-05-01 the schedule in force is V2, where the 10y-30y cap
    is $250mm. A lookup that ignored the date would happily impute it at 1.99x.
    """
    legs = pd.DataFrame({
        "notional": [470e6, 250e6, 120e6, 78_613_002.0],
        "as_of_date": [datetime.date(2025, 5, 1)] * 3 + [datetime.date(2025, 9, 17)],
        "tenor_years": [7.0, 20.0, 20.0, 0.246575],
        "is_capped": [True, False, True, True],
    })
    before = legs["notional"].copy()
    out = imp.impute_frame(legs)

    pd.testing.assert_series_equal(out["notional"], before)
    assert list(out["notional_imputed"]) == [True, False, False, False]
    assert list(out["notional_impute_reason"]) == [
        imp.REASON_IMPUTED, imp.REASON_NOT_CAPPED,
        imp.REASON_CAP_UNRECOGNISED, imp.REASON_CAP_UNRECOGNISED]
    assert np.isnan(out.loc[1, "notional_impute_factor"])
    assert np.isnan(out.loc[2, "notional_impute_factor"])
    assert out.loc[0, "notional_expected"] > out.loc[0, "notional"]
    # the tenor cross-check rides along when a tenor column is there: row 0 is
    # a 7y print at the V2 5y-10y cap, so its two keys agree
    assert out.loc[0, "notional_cell_tenor_mismatch"] is np.False_ or (
        out.loc[0, "notional_cell_tenor_mismatch"] is False)
    assert pd.isna(out.loc[1, "notional_cell_tenor_mismatch"]), "only imputed rows"
    # and the same frame through the scalar path, row for row
    for i, row in legs.iterrows():
        scalar = imp.impute(row["notional"], row["as_of_date"], row["is_capped"])
        assert scalar.notional_imputed == out.loc[i, "notional_imputed"]
        assert scalar.reason == out.loc[i, "notional_impute_reason"]


def test_the_multiplier_is_applied_to_the_signed_krd_not_to_notional():
    """Requirement 4, and the reason the module has no notional-scaling helper.

    ``risk`` and any repriced KRD are computed FROM the capped notional, so they
    carry the same right-censoring. Scaling notional first and then pricing runs
    the multiplier through the pricing path a second time.
    """
    krd = {"2Y": -1200.0, "5Y": 0.0, "10Y": 3400.0}
    scaled = imp.apply_to_signed_krd(krd, 2.5)
    assert scaled == {"2Y": -3000.0, "5Y": 0.0, "10Y": 8500.0}
    assert krd == {"2Y": -1200.0, "5Y": 0.0, "10Y": 3400.0}, "must not mutate"

    arr = np.array([-1200.0, 0.0, 3400.0])
    np.testing.assert_allclose(imp.apply_to_signed_krd(arr, 2.5), arr * 2.5)

    # sign is direction, set before this point, and the multiplier cannot move it
    for factor in (1.0, 1.7, 4.0):
        out = imp.apply_to_signed_krd(krd, factor)
        assert [np.sign(v) for v in out.values()] == [np.sign(v) for v in krd.values()]


@pytest.mark.parametrize("bad", [None, 0.0, 0.9, -2.0, float("nan")])
def test_apply_to_signed_krd_rejects_a_factor_that_is_not_an_imputation(bad):
    """A factor below 1 would shrink a censored position. There is no such case."""
    with pytest.raises(ValueError):
        imp.apply_to_signed_krd({"5Y": 100.0}, bad)


def test_the_module_exposes_no_way_to_scale_a_notional():
    """A helper that rewrote ``notional`` would be used, and would double-count."""
    public = [n for n in dir(imp) if not n.startswith("_")]
    for name in public:
        assert "scale_notional" not in name
        assert not name.startswith("apply_to_notional")

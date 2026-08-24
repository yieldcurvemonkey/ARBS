r"""Known-answer tests for the data-surprise -> Fedspeak lead study.

The point of this file is the third block. A cross-correlation argmax between
two *smoothed* series is not a measurement of anything until the pipeline has
been shown to return the right answer on data whose answer is known -- because
a backward-looking smoother on the response side manufactures an apparent lead
all by itself, and it does not announce itself.

So: plant a zero lead, measure what the pipeline reports (its own filter
offset); plant a five-week lead, require the report to move by five weeks. Only
the difference between those two numbers is evidence about the Fed.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(REPO / "notebooks" / "rv") not in sys.path:
    sys.path.insert(0, str(REPO / "notebooks" / "rv"))

import fed_sentiment_lead_data as D  # noqa: E402


# ---------------------------------------------------------------- helpers
# The synthetic world lives in the DATA module, not here. The notebook's
# calibration cell reads the same construction, and a deliverable notebook must
# not import from tests/ to be re-executable.
_ar1 = D.ar1_path
_synthetic_world = D.synthetic_world


def _measure(panel, book, cfg, transform="levels"):
    composite, _ = D.build_surprise_composite(panel, cfg)
    x = D.weekly_last(composite, cfg.week_anchor)
    grid = x.index
    sent = D.sentiment_index(book, grid, cfg, point_in_time=False)["sentiment"]
    xt, yt, _ = D.transform_pair(x, sent, transform)
    lags = cfg.lags()
    X, Y, _ = D.lag_matrix(xt, yt, lags)
    curve = D.lag_curve_common(X, Y, lags)
    j = int(np.nanargmax(curve["corr"].to_numpy()))
    return int(curve["lag_weeks"].iloc[j]), float(curve["corr"].iloc[j]), curve, (X, Y)


# ---------------------------------------------------------------- G5: trailing
def test_trailing_z_value_does_not_change_when_later_data_is_removed():
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2015-01-01", periods=2500)
    s = pd.Series(_ar1(len(idx), 0.99, rng), index=idx)
    cfg = D.LeadConfig()
    probes = [idx[1200], idx[1800], idx[2300]]
    out = D.gate_trailing_only(s, cfg, probe_dates=probes)
    assert len(out) == 3
    assert float(out["abs_diff"].max()) == 0.0


def test_trailing_z_gate_catches_a_full_sample_statistic():
    """The gate must FAIL on a statistic that is not trailing."""
    rng = np.random.default_rng(1)
    idx = pd.bdate_range("2015-01-01", periods=2000)
    s = pd.Series(_ar1(len(idx), 0.99, rng), index=idx)
    cfg = D.LeadConfig()

    real = D.trailing_z
    try:
        D.trailing_z = lambda x, w, m: (x - x.mean()) / x.std()  # full sample
        with pytest.raises(AssertionError, match="G5 FAILED"):
            D.gate_trailing_only(s, cfg, probe_dates=[idx[1500]])
    finally:
        D.trailing_z = real


# ---------------------------------------------------------------- G1/G2: vintage
def _vintage_book():
    return pd.DataFrame(
        {
            "central_bank": "FED",
            "date": pd.to_datetime(
                ["2023-01-10", "2023-06-01", "2023-06-15", "2023-07-01"]
            ),
            # row 0 is a re-scored old speech: published 300 days late
            "pub_date": pd.to_datetime(
                ["2023-11-06", "2023-06-01", "2023-06-15", "2023-07-01"]
            ),
            "speaker": ["A", "B", "C", "D"],
            "hawk_dove_score": [10.0, 20.0, -5.0, 3.0],
            "relevance_pct": 50.0,
        }
    )


def test_vintage_gate_removes_the_late_published_row():
    cfg = D.LeadConfig()
    grid = pd.DatetimeIndex(["2023-07-07"])
    out = D.gate_vintage(_vintage_book(), grid, cfg)
    assert int(out["n_as_published"].iloc[0]) == 4
    assert int(out["n_point_in_time"].iloc[0]) == 3
    assert int(out["n_removed"].iloc[0]) == 1


def test_vintage_gate_fails_loudly_when_nothing_is_removed():
    """`If it removes nothing you have not wired it up` -- as a test."""
    cfg = D.LeadConfig()
    book = _vintage_book()
    book["pub_date"] = book["date"]
    with pytest.raises(AssertionError, match="G1 FAILED"):
        D.gate_vintage(book, pd.DatetimeIndex(["2023-07-07"]), cfg)


def test_point_in_time_index_is_empty_before_the_corpus_starts():
    cfg = D.LeadConfig()
    rng = np.random.default_rng(3)
    _, book, _ = _synthetic_world(lead_days=0, rng=rng)
    # publish everything on 2023-05-02, whatever the speech date
    book = book.copy()
    book["pub_date"] = pd.Timestamp(cfg.corpus_start)
    grid = D.weekly_grid("2022-01-07", "2024-01-05", cfg.week_anchor)
    pit = D.sentiment_index(book, grid, cfg, point_in_time=True)["sentiment"]
    D.gate_no_pre_corpus(pit, cfg)  # must not raise
    assert pit[pit.index < pd.Timestamp(cfg.corpus_start)].dropna().empty


def test_pre_corpus_gate_catches_a_leaking_mask():
    cfg = D.LeadConfig()
    rng = np.random.default_rng(4)
    _, book, _ = _synthetic_world(lead_days=0, rng=rng)
    grid = D.weekly_grid("2022-06-03", "2023-06-02", cfg.week_anchor)
    leaked = D.sentiment_index(book, grid, cfg, point_in_time=False)["sentiment"]
    with pytest.raises(AssertionError, match="G2 FAILED"):
        D.gate_no_pre_corpus(leaked, cfg)


# ---------------------------------------------------------------- G3: surprise
def test_surprise_gate_rejects_an_identically_zero_leg():
    cfg = D.LeadConfig()
    idx = pd.bdate_range("2020-01-01", periods=800)
    panel = pd.DataFrame(
        {D.TAG_LABOUR: np.arange(800.0), D.TAG_PRICES: np.zeros(800)}, index=idx
    )
    with pytest.raises(AssertionError, match="G3 FAILED"):
        D.gate_surprise_sanity(panel, cfg)


def test_surprise_gate_rejects_a_mixed_frequency_pair():
    cfg = D.LeadConfig()
    daily = pd.bdate_range("2000-01-03", periods=6000)
    monthly = pd.date_range("2000-01-31", periods=280, freq="ME")
    panel = pd.DataFrame(index=daily.union(monthly), dtype=float)
    rng = np.random.default_rng(5)
    panel[D.TAG_LABOUR] = pd.Series(rng.normal(size=len(daily)), index=daily)
    panel[D.TAG_PRICES] = pd.Series(rng.normal(size=len(monthly)), index=monthly)
    with pytest.raises(AssertionError, match="do not share a frequency"):
        D.gate_surprise_sanity(panel, cfg)


def test_composite_is_nan_when_one_leg_is_missing():
    cfg = D.LeadConfig()
    rng = np.random.default_rng(6)
    idx = pd.bdate_range("2016-01-01", periods=1500)
    panel = pd.DataFrame(
        {
            D.TAG_LABOUR: _ar1(len(idx), 0.99, rng),
            D.TAG_PRICES: _ar1(len(idx), 0.99, rng),
        },
        index=idx,
    )
    panel.loc[idx[-10:], D.TAG_PRICES] = np.nan
    composite, _ = D.build_surprise_composite(panel, cfg)
    assert composite.loc[idx[-10:]].isna().all()
    assert composite.loc[idx[-200:-100]].notna().all()


# ---------------------------------------------------------------- the estimator
def test_lag_curve_argmax_ties_out_to_the_rvutils_estimator():
    """Our curve's winner must equal the repo's existing point estimate."""
    from RVUtils.lead_lag import xcorr_lead_lag

    rng = np.random.default_rng(7)
    n = 400
    idx = pd.date_range("2020-01-03", periods=n, freq="W-FRI")
    x = pd.Series(_ar1(n, 0.6, rng), index=idx)
    y = pd.Series(np.roll(x.to_numpy(), 4) + rng.normal(scale=0.4, size=n), index=idx)

    lags = np.arange(-13, 14)
    xt, yt, _ = D.transform_pair(x, y, "changes")
    X, Y, _ = D.lag_matrix(xt, yt, lags)
    ours = int(lags[int(np.nanargmax(D.lag_curve_common(X, Y, lags)["corr"].to_numpy()))])
    theirs = xcorr_lead_lag(x, y, max_lag=13)["lag"]
    assert ours == theirs == 4


def test_fit_ar_recovers_a_planted_ar2():
    """Known answer for the prewhitening filter."""
    rng = np.random.default_rng(0)
    n = 4000
    x = np.zeros(n)
    e = rng.normal(size=n)
    for i in range(2, n):
        x[i] = 0.6 * x[i - 1] - 0.3 * x[i - 2] + e[i]
    phi, p = D.fit_ar(x, max_p=8)
    assert p == 2, f"selected order {p}, expected 2"
    assert abs(phi[0] - 0.6) < 0.05 and abs(phi[1] + 0.3) < 0.05, phi


def test_fit_ar_scores_every_order_on_the_same_rows():
    """AIC across models fitted on different sample sizes is not comparable.

    Fitting AR(1) on n-1 rows and AR(6) on n-6 biases selection toward the short
    lag, because a likelihood computed on more observations is simply larger.
    The fix is a common sample -- the last ``n - max_p`` rows for every
    candidate -- and it has a consequence that can actually fail: when the
    selected order ``p`` is BELOW ``max_p``, the returned coefficients must
    equal an OLS fitted on rows ``[max_p:]``, not on rows ``[p:]``. Those two
    regressions differ, so this test distinguishes the two rules.
    """
    rng = np.random.default_rng(1)
    n = 300
    x = np.zeros(n)
    e = rng.normal(size=n)
    for i in range(2, n):
        x[i] = 0.55 * x[i - 1] - 0.35 * x[i - 2] + e[i]
    max_p = 8
    phi, p = D.fit_ar(x, max_p=max_p)
    assert 0 < p < max_p, f"need an interior selection to discriminate; got {p}"

    def _ols(start):
        Z = np.column_stack([x[start - j - 1 : n - j - 1] for j in range(p)])
        beta, *_ = np.linalg.lstsq(Z, x[start:], rcond=None)
        return beta

    common, per_order = _ols(max_p), _ols(p)
    assert not np.allclose(common, per_order, atol=1e-9), (
        "the two rules coincide on this sample, so the test proves nothing"
    )
    assert np.allclose(phi, common, atol=1e-9), (
        f"fit_ar returned {phi}, the common-sample fit is {common} and the "
        f"per-order fit is {per_order} -- it is using the wrong sample"
    )


def test_prewhitened_answer_is_not_a_property_of_the_order_cap():
    rng = np.random.default_rng(2)
    n = 300
    idx = pd.date_range("2020-01-03", periods=n, freq="W-FRI")
    drv = pd.Series(_ar1(n, 0.9, rng), index=idx)
    y = pd.Series(np.roll(drv.to_numpy(), 6) + rng.normal(scale=0.5, size=n), index=idx)
    lags = np.arange(-13, 14)
    args = set()
    for mp in (2, 4, 8, 12):
        xt, yt, _ = D.transform_pair(drv, y, "prewhitened", max_p=mp)
        X, Y, _ = D.lag_matrix(xt, yt, lags)
        c = D.lag_curve_common(X, Y, lags)
        args.add(int(c["lag_weeks"].iloc[int(np.nanargmax(c["corr"].to_numpy()))]))
    assert args == {6}, f"the order cap moved the recovered lead: {sorted(args)}"


def test_phase_randomisation_preserves_the_power_spectrum():
    rng = np.random.default_rng(8)
    x = _ar1(512, 0.95, rng)
    s = D.phase_randomise(x, rng)
    a = np.abs(np.fft.rfft(x - x.mean()))
    b = np.abs(np.fft.rfft(s - s.mean()))
    assert np.allclose(a, b, atol=1e-8)
    assert abs(np.corrcoef(x, s)[0, 1]) < 0.9  # it is a different path


@pytest.mark.parametrize("lag", [0, 5, 12])
def test_newey_west_matches_statsmodels_hac(lag):
    """External known-answer for the hand-rolled HAC sandwich."""
    sm = pytest.importorskip("statsmodels.api")
    rng = np.random.default_rng(9)
    n = 500
    e = np.zeros(n)
    shock = rng.normal(size=n)
    for i in range(1, n):
        e[i] = 0.8 * e[i - 1] + shock[i]  # serially correlated errors
    x = rng.normal(size=n)
    y = 0.7 * x + e
    ours = D.newey_west_t(y, x, lag=lag)
    fit = sm.OLS(y, sm.add_constant(x)).fit(
        cov_type="HAC", cov_kwds={"maxlags": lag, "use_correction": False}
    )
    assert abs(ours["beta"] - fit.params[1]) < 1e-9
    assert abs(ours["t"] - fit.tvalues[1]) < 1e-6, (
        f"ours {ours['t']:.6f} vs statsmodels {fit.tvalues[1]:.6f}"
    )


def test_stationary_bootstrap_index_is_in_range_and_blocky():
    rng = np.random.default_rng(10)
    idx = D.stationary_bootstrap_index(200, 8.0, rng)
    assert idx.min() >= 0 and idx.max() < 200
    consecutive = np.mean(np.diff(idx) == 1)
    assert consecutive > 0.6  # mean block 8 => ~7/8 of steps continue a block


# ---------------------------------------------------------------- G6: calibration
#: How far the pipeline's own smoothers shift the apparent lead, in weeks. The
#: sentiment EWMA looks BACKWARD with half-life 21 days, so its centre of mass
#: sits ~ halflife/ln2 = 30 days behind the grid date, truncation pulling that
#: to ~28 days -- about four weeks of apparent lead from the filter alone.
_EXPECTED_OFFSET_WEEKS = 4


def test_pipeline_reports_a_lead_even_when_the_true_lead_is_zero():
    """G6 -- the filter offset, measured rather than assumed.

    This is the test that decides whether any measured lead means anything. A
    contemporaneous relationship pushed through the production pipeline must
    still come out looking like a multi-week lead, and the size of that
    artefact is the baseline every real number is compared against.
    """
    rng = np.random.default_rng(11)
    panel, book, cfg = _synthetic_world(lead_days=0, rng=rng)
    lag, corr, _, _ = _measure(panel, book, cfg)
    assert corr > 0.5, f"synthetic relationship too weak to calibrate (corr {corr:.3f})"
    assert abs(lag - _EXPECTED_OFFSET_WEEKS) <= 2, (
        f"zero-lead calibration returned {lag}w, expected ~{_EXPECTED_OFFSET_WEEKS}w "
        f"from the EWMA centre of mass"
    )


def test_pipeline_moves_by_the_planted_lead():
    """G6 -- a five-week lead must show up as five weeks ABOVE the offset."""
    rng = np.random.default_rng(12)
    panel0, book0, cfg = _synthetic_world(lead_days=0, rng=rng)
    base, _, _, _ = _measure(panel0, book0, cfg)

    rng = np.random.default_rng(12)  # same draws, only the lead changes
    panel5, book5, cfg = _synthetic_world(lead_days=35, rng=rng)
    lead5, corr5, _, _ = _measure(panel5, book5, cfg)

    moved = lead5 - base
    assert corr5 > 0.5
    assert abs(moved - 5) <= 2, (
        f"planted a 5-week lead; the pipeline moved by {moved}w (base {base}w, "
        f"measured {lead5}w)"
    )


def test_shorter_sentiment_halflife_shortens_the_apparent_lead():
    """If the argmax tracks the smoother, the smoother is what is being seen."""
    rng = np.random.default_rng(13)
    panel, book, _ = _synthetic_world(lead_days=0, rng=rng)
    long_cfg = D.LeadConfig(ewma_halflife_days=42.0)
    short_cfg = D.LeadConfig(ewma_halflife_days=7.0)
    long_lag, _, _, _ = _measure(panel, book, long_cfg)
    short_lag, _, _, _ = _measure(panel, book, short_cfg)
    assert short_lag < long_lag, (
        f"halving the half-life did not shorten the apparent lead "
        f"({short_lag}w vs {long_lag}w)"
    )


def test_a_planted_lead_clears_the_shift_null_in_CHANGES():
    rng = np.random.default_rng(14)
    panel, book, cfg = _synthetic_world(lead_days=35, rng=rng)
    composite, _ = D.build_surprise_composite(panel, cfg)
    x = D.weekly_last(composite, cfg.week_anchor)
    y = D.sentiment_index(book, x.index, cfg, point_in_time=False)["sentiment"]
    lags = cfg.lags()
    xt, yt, _ = D.transform_pair(x, y, "changes")
    X, Y, _ = D.lag_matrix(xt, yt, lags)
    observed = float(np.nanmax(D.lag_curve_common(X, Y, lags)["corr"].to_numpy()))
    null = D.shift_null(x, y, lags, cfg, transform="changes", draws=300,
                        rng=np.random.default_rng(15))
    # the rotation set is FINITE and is enumerated in full, so the null is exact
    # and its p-value cannot go below 1/(distinct + 1)
    assert null["exhaustive"] is True
    assert null["draws_used"] == null["distinct_rotations"] > 100
    p = D.surrogate_pvalue(observed, null)
    assert p >= null["p_floor"], "a p-value finer than the reference set can resolve"
    assert p < 0.05, (
        f"a planted 5-week lead did not clear the shift null in changes "
        f"(max {observed:.3f}, null q95 {null['q95']:.3f}, p={p:.3f}, "
        f"floor {null['p_floor']:.4f})"
    )


def test_shift_null_enumerates_its_finite_reference_set():
    """A p-value can never be finer than 1/(distinct surrogates + 1).

    Sampling ~190 distinct rotations 1,500 times with replacement produces a
    reference set of at most 190 distinct curves, so quoting p = 0.001 off it
    claims a resolution that does not exist. The null now enumerates the whole
    set whenever it fits the draw budget, and reports the floor.
    """
    cfg = D.LeadConfig()
    rng = np.random.default_rng(41)
    n = 200
    idx = pd.date_range("2022-01-07", periods=n, freq="W-FRI")
    x = pd.Series(_ar1(n, 0.95, rng), index=idx)
    y = pd.Series(_ar1(n, 0.95, rng), index=idx)
    lags = cfg.lags()
    null = D.shift_null(x, y, lags, cfg, draws=5000, rng=np.random.default_rng(42))
    expected = n - 2 * (max(abs(lags.min()), abs(lags.max())) + 1)
    assert null["exhaustive"] is True
    assert null["distinct_rotations"] == expected
    assert null["draws_used"] == expected
    assert abs(null["p_floor"] - 1.0 / (expected + 1)) < 1e-12
    assert D.surrogate_pvalue(0.5, null) >= null["p_floor"] - 1e-12


def test_LEVELS_cannot_discriminate_even_a_planted_lead():
    """The finding that decides how the notebook may report its headline.

    A deliberately strong five-week lead reaches corr 0.92 in levels -- and the
    conservative null reaches 0.92 too, because two wandering series over ~150
    weekly points can be aligned to almost anything. The same relationship is
    unambiguous in changes. So the level correlation is a picture, not a
    measurement, and any lead quoted off it is quoted off a plateau of
    near-identical values.
    """
    rng = np.random.default_rng(14)
    panel, book, cfg = _synthetic_world(lead_days=35, rng=rng)
    composite, _ = D.build_surprise_composite(panel, cfg)
    x = D.weekly_last(composite, cfg.week_anchor)
    y = D.sentiment_index(book, x.index, cfg, point_in_time=False)["sentiment"]
    lags = cfg.lags()

    def _p(transform):
        xt, yt, _ = D.transform_pair(x, y, transform)
        X, Y, _ = D.lag_matrix(xt, yt, lags)
        obs = float(np.nanmax(D.lag_curve_common(X, Y, lags)["corr"].to_numpy()))
        null = D.shift_null(x, y, lags, cfg, transform=transform, draws=300,
                            rng=np.random.default_rng(15))
        return D.surrogate_pvalue(obs, null), obs

    p_lev, obs_lev = _p("levels")
    p_chg, obs_chg = _p("changes")
    assert obs_lev > 0.85, "the planted relationship should be visually overwhelming"
    assert p_lev > 0.05, (
        f"levels unexpectedly discriminated (p={p_lev:.3f}); if this starts "
        f"passing the null has become too easy"
    )
    assert p_chg < 0.05, f"changes failed to discriminate (p={p_chg:.3f})"


@pytest.mark.parametrize("transform,ceiling", [("changes", 0.15), ("levels", 0.20)])
def test_shift_null_size_is_near_nominal(transform, ceiling):
    """Calibration: how often does the null reject when nothing is there?

    The notebook measures all six null/transform sizes in a cell and prints
    Wilson intervals; this test only has to catch a null that has stopped
    working altogether. Run at 40 trials so the fast gate stays fast, with
    ceilings loose enough to absorb that sample.

    Do not re-hard-code a size here. The previously quoted 8.3%/5.0%/9.2% were
    measured before the rotations were enumerated exactly and before the AR
    order was selected on a common sample; both changed the answer, and a
    number frozen in a docstring does not change with them.
    """
    cfg = D.LeadConfig()
    lags = cfg.lags()
    trials, rejected = 40, 0
    for seed in range(trials):
        rng = np.random.default_rng(1000 + seed)
        n = 170
        idx = pd.date_range("2023-05-05", periods=n, freq="W-FRI")
        a = pd.Series(_ar1(n, 0.97, rng), index=idx)
        b = pd.Series(_ar1(n, 0.97, rng), index=idx)
        at, bt, _ = D.transform_pair(a, b, transform)
        X, Y, _ = D.lag_matrix(at, bt, lags)
        obs = float(np.nanmax(D.lag_curve_common(X, Y, lags)["corr"].to_numpy()))
        null = D.shift_null(a, b, lags, cfg, transform=transform, draws=120,
                            rng=np.random.default_rng(5000 + seed))
        rejected += D.surrogate_pvalue(obs, null) < 0.05
    rate = rejected / trials
    assert rate <= ceiling, (
        f"shift null on {transform} rejected {rejected}/{trials} = {rate:.3f} "
        f"when nothing was there"
    )


# ---------------------------------------------------------------- real inputs
@pytest.mark.skipif(
    not (REPO / "notebooks" / "rv" / "fed_sentiment_lead_citi_snapshot.parquet").exists(),
    reason="snapshot not built",
)
def test_snapshot_carries_both_legs_at_a_shared_daily_frequency():
    cfg = D.LeadConfig()
    panel, prov = D.load_surprise_panel()
    out = D.gate_surprise_sanity(panel, cfg)
    assert set(out["tag"]) == set(cfg.surprise_tags)
    assert (out["n_nonzero"] > 5000).all()
    assert prov["source"] in {"xlsx", "live CVTSHIST"}


@pytest.mark.skipif(
    not (REPO / "notebooks" / "rv" / "fed_sentiment_lead_citi_snapshot.parquet").exists(),
    reason="snapshot not built",
)
def test_a_hot_cpi_print_moves_the_prices_surprise_index_up():
    """G3's hand-check, as a test: a known hot CPI must lift the prices leg.

    Guarded on the SNAPSHOT, which is what it reads -- guarding it on the JPM
    corpus instead would silently skip the only content check on the committed
    parquet exactly where that corpus is absent, i.e. on every machine but one.
    """
    panel, _ = D.load_surprise_panel()
    prices = panel[D.TAG_PRICES].dropna()
    # 2024-04-10: March CPI printed 0.4% m/m core against 0.3% expected, and
    # the 10y sold off 18bp on the day.
    d = pd.Timestamp("2024-04-10")
    prev = prices[prices.index < d].iloc[-1]
    on = prices.asof(d)
    assert on > prev, f"hot CPI 2024-04-10 moved the prices leg {prev} -> {on}"

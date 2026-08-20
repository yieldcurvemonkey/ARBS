"""Unit tests for the AGGREGATE multi-issuer ladder.

Every test here names a way this construction can produce a confident wrong answer, and
each one has been mutation-checked -- the code it covers was deliberately broken and the
test was required to go red (``tests/_mutate_etf_aggregate.py``).

The two that matter most, and are called out in the task:

* **the different-denominator trap** -- adding active weights that are shares of
  different boards. Nothing about the dtypes or the ranges catches it; only comparing the
  benchmark vectors does.
* **the publication-lag lookahead** -- N-PORT is public 53-62 days after the date it
  describes, so a panel keyed on the as-of date hands SPTL and VGLT two months of the
  future. That is far larger than any edge being chased here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from RVUtils.ETFRebalance import aggregate as AG
from RVUtils.ETFRebalance import signals as SIG


# --------------------------------------------------------------------------- fixtures

def _universe(dates, cusips, *, ttms, float_usd=20e9, dv01_per_mm=1500.0):
    """A minimal priced 20y+ board: one row per (date, cusip)."""
    rows = []
    for d in dates:
        for c, t in zip(cusips, ttms):
            rows.append({"date": pd.Timestamp(d), "cusip": c, "ttm": float(t),
                         "free_float": float(float_usd), "outstanding_amt": float(float_usd),
                         "dv01_per_mm": float(dv01_per_mm), "clean_price": 100.0})
    return pd.DataFrame(rows)


def _obs(ticker, obs_date, available_from, pars, source="ishares_daily"):
    return pd.DataFrame([
        {"ticker": ticker, "obs_date": pd.Timestamp(obs_date),
         "available_from": pd.Timestamp(available_from), "cusip": c, "par": float(p),
         "source": source}
        for c, p in pars.items()
    ])


DATES = pd.date_range("2024-01-01", periods=10, freq="B")
CUSIPS = ["AAA", "BBB", "CCC", "DDD"]
TTMS = [20.1, 20.6, 21.1, 21.6]


# ---------------------------------------------------- the publication-lag lookahead

def test_an_nport_book_does_not_enter_the_panel_before_it_was_filed():
    """THE LOOKAHEAD TEST. N-PORT is public 53-62 days after its own as-of date.

    A book describing 2024-01-01 that was filed on 2024-01-08 must contribute NOTHING on
    2024-01-01..2024-01-05 and everything from 2024-01-08 on. Keying the join on the
    as-of date instead would silently hand the fund a week of the future here, and two
    months of it in production.
    """
    obs = _obs("SPTL", "2024-01-01", "2024-01-08", {"AAA": 1e9}, source="nport")
    got = AG.as_of_panel(obs, DATES)

    early = got[got["date"] < pd.Timestamp("2024-01-08")]
    assert early.empty, (
        f"{len(early)} rows leaked in before available_from -- the earliest is "
        f"{early['date'].min() if len(early) else None}, the filing date is 2024-01-08"
    )
    late = got[got["date"] >= pd.Timestamp("2024-01-08")]
    assert len(late) == (DATES >= pd.Timestamp("2024-01-08")).sum()
    assert (late["obs_date"] == pd.Timestamp("2024-01-01")).all()


def test_staleness_is_measured_from_the_book_date_not_the_filing_date():
    """``stale_days`` must say how old the BOOK is, which is the honest number.

    A book from 2024-01-01 read on 2024-01-10 is nine days old even though it was only
    filed two days earlier. Reporting the filing gap instead would make a 105-day-old
    N-PORT staircase look two days fresh.
    """
    obs = _obs("SPTL", "2024-01-01", "2024-01-08", {"AAA": 1e9}, source="nport")
    got = AG.as_of_panel(obs, DATES).sort_values("date")
    row = got[got["date"] == pd.Timestamp("2024-01-10")].iloc[0]
    assert row["stale_days"] == 9, row["stale_days"]


def test_the_freshest_published_book_wins_when_two_are_available():
    obs = pd.concat([
        _obs("SPTL", "2024-01-01", "2024-01-03", {"AAA": 1e9}, source="nport"),
        _obs("SPTL", "2024-01-08", "2024-01-09", {"AAA": 2e9}, source="nport"),
    ], ignore_index=True)
    got = AG.as_of_panel(obs, DATES)
    on_5th = got[got["date"] == pd.Timestamp("2024-01-05")].iloc[0]
    on_10th = got[got["date"] == pd.Timestamp("2024-01-10")].iloc[0]
    assert on_5th["par"] == 1e9
    assert on_10th["par"] == 2e9


def test_a_fund_set_starts_only_when_every_fund_in_it_has_published():
    """Before that date an "aggregate" is one of its funds wearing the aggregate's name.

    It matters because the score is a z against the bucket's OWN history: a fund
    switching on mid-sample is a level shift in that history, and the z reads it as a
    dislocation on every bucket simultaneously.
    """
    obs = pd.concat([
        _obs("TLT", d, d, {"AAA": 1e9}) for d in DATES
    ] + [_obs("SPTL", "2024-01-01", "2024-01-08", {"AAA": 1e9}, source="nport")],
        ignore_index=True)
    asof = AG.as_of_panel(obs, DATES)
    fs = AG.FundSet("t", daily=("TLT",), nport=("SPTL",))
    assert AG.first_complete_date(asof, fs) == pd.Timestamp("2024-01-08")


def test_first_complete_date_refuses_a_fund_that_never_reported():
    obs = _obs("TLT", "2024-01-01", "2024-01-01", {"AAA": 1e9})
    asof = AG.as_of_panel(obs, DATES)
    fs = AG.FundSet("t", daily=("TLT",), nport=("SPTL",))
    with pytest.raises(ValueError, match="SPTL"):
        AG.first_complete_date(asof, fs)


# ---------------------------------------------------- the different-denominator trap

def test_active_weights_measured_against_DIFFERENT_benchmarks_are_refused():
    """THE DENOMINATOR TEST, and the reason this module exists.

    ``holdings_panel.with_active_weight`` uses each fund's OWN spec, so TLT's ``w_i`` is a
    share of a 40-bond 20y+ board and SPTL's is a share of a ~100-bond 10y+ board. Both
    columns are called ``w_i``, both are in [0, 1], both sum to 1 over their own board.
    Adding the active weights built from them produces a plausible-looking number with no
    denominator at all -- and no shape, dtype or range check can see it.
    """
    tlt = pd.DataFrame({"date": [pd.Timestamp("2024-01-01")] * 2,
                        "cusip": ["AAA", "BBB"], "w_i": [0.50, 0.50]})
    sptl = pd.DataFrame({"date": [pd.Timestamp("2024-01-01")] * 2,
                         "cusip": ["AAA", "BBB"], "w_i": [0.20, 0.20]})
    with pytest.raises(AG.DifferentDenominators, match="different"):
        AG.assert_common_benchmark({"TLT": tlt, "SPTL": sptl})


def test_active_weights_on_ONE_common_benchmark_are_accepted():
    """The guard must not be a blanket refusal -- the whole construction depends on it
    passing when the funds genuinely share a board."""
    w = pd.DataFrame({"date": [pd.Timestamp("2024-01-01")] * 2,
                      "cusip": ["AAA", "BBB"], "w_i": [0.5, 0.5]})
    AG.assert_common_benchmark({"TLT": w.copy(), "SPTL": w.copy()})


def test_the_denominator_guard_only_compares_dates_the_funds_SHARE():
    """SPTL files calendar quarter-ends and VGLT files Feb/May/Aug/Nov -- measured, they
    NEVER share an observation date. A guard that demanded overlapping dates would refuse
    every real aggregate; one that ignored the dates it does share would never fire."""
    a = pd.DataFrame({"date": [pd.Timestamp("2024-01-01")], "cusip": ["AAA"], "w_i": [0.5]})
    b = pd.DataFrame({"date": [pd.Timestamp("2024-02-01")], "cusip": ["AAA"], "w_i": [0.9]})
    AG.assert_common_benchmark({"A": a, "B": b})       # no shared date -> nothing to compare


def test_the_active_ladder_gives_every_fund_the_same_benchmark_by_construction():
    """The positive form of the same claim, measured on the real code path.

    Two funds with completely different books must still be scored against one ``w_i``,
    so the residual of the aggregate is a deviation from a single board.
    """
    uni = _universe(DATES, CUSIPS, ttms=TTMS)
    obs = pd.concat(
        [_obs("TLT", d, d, {"AAA": 4e9, "BBB": 1e9, "CCC": 1e9, "DDD": 1e9}) for d in DATES]
        + [_obs("SPTL", d, d, {"AAA": 1e9, "BBB": 4e9}) for d in DATES],
        ignore_index=True)
    asof = AG.as_of_panel(obs, DATES)
    lad, off = AG.active_ladder(asof, uni, band=(20.0, 31.0), width_y=0.25,
                                lookback=5, min_periods=2)
    #: Four equal-float bonds on one board -> every index weight is exactly 1/4, so the
    #: aggregate active weights must sum to zero across the board on every date.
    s = lad.groupby("date")["active_agg"].sum()
    assert np.allclose(s.to_numpy(float), 0.0, atol=1e-12), s.to_dict()


def test_a_bond_no_fund_holds_carries_the_full_negative_index_weight():
    """The most underweight name on the board is the one nobody owns.

    An inner join would delete exactly the observations the signal is most about. The
    construction has to place such a bond at ``-w_i``, and with four equal-float bonds
    that is exactly -0.25.
    """
    uni = _universe(DATES, CUSIPS, ttms=TTMS)
    obs = pd.concat([_obs("TLT", d, d, {"AAA": 1e9, "BBB": 1e9, "CCC": 1e9}) for d in DATES],
                    ignore_index=True)          # DDD held by nobody
    asof = AG.as_of_panel(obs, DATES)
    lad, _ = AG.active_ladder(asof, uni, band=(20.0, 31.0), width_y=0.25,
                              lookback=5, min_periods=2)
    ddd_bucket = float(AG.bucket_of(pd.Series([21.6]), band_low=20.0, band_high=31.0,
                                    width_y=0.25).iloc[0])
    row = lad[(lad["date"] == DATES[0]) & (lad["bucket"] == ddd_bucket)].iloc[0]
    assert row["active_agg"] == pytest.approx(-0.25, abs=1e-12), row["active_agg"]


# ---------------------------------------------------- the off-slice residual

def test_the_offslice_residual_is_reported_and_not_silently_dropped():
    """Renormalising inside the common 20y+ slice deletes each fund's view on how much
    long end to hold at all. Measured on the real data that residual is 44-45% of SPTL and
    VGLT and 84% of GOVT -- far too large to leave implicit, so it comes back as data."""
    uni = _universe(DATES, CUSIPS, ttms=TTMS)
    obs = pd.concat(
        [_obs("TLT", d, d, {"AAA": 1e9, "BBB": 1e9}) for d in DATES]
        #: SPTL holds 1bn inside the slice and 3bn in a 12-year bond that is not on this
        #: board at all -- exactly the shape of a 10y+ fund seen through a 20y+ window.
        + [_obs("SPTL", d, d, {"AAA": 1e9, "ZZZ_12Y": 3e9}) for d in DATES],
        ignore_index=True)
    asof = AG.as_of_panel(obs, DATES)
    _, off = AG.active_ladder(asof, uni, band=(20.0, 31.0), width_y=0.25,
                              lookback=5, min_periods=2)
    s = off[(off["ticker"] == "SPTL") & (off["date"] == DATES[0])].iloc[0]
    assert s["book_par"] == pytest.approx(4e9)
    assert s["inslice_par"] == pytest.approx(1e9)
    assert s["offslice_share_par"] == pytest.approx(0.75, abs=1e-12)
    t = off[(off["ticker"] == "TLT") & (off["date"] == DATES[0])].iloc[0]
    assert t["offslice_share_par"] == pytest.approx(0.0, abs=1e-12)


# ---------------------------------------------------- ownership, the (a) construction

def test_ownership_is_dollars_over_dollars_and_therefore_adds_across_funds():
    """Construction (a) is denominator-consistent BY CONSTRUCTION, which is the whole
    reason it is the one the task names first: nothing in it depends on any fund's index
    band, so two funds with different bands contribute comparable dollars."""
    uni = _universe(DATES, ["AAA"], ttms=[20.1], float_usd=10e9)
    obs = pd.concat(
        [_obs("TLT", d, d, {"AAA": 1e9}) for d in DATES]
        + [_obs("SPTL", d, d, {"AAA": 0.5e9}) for d in DATES], ignore_index=True)
    asof = AG.as_of_panel(obs, DATES)
    lad = AG.ownership_ladder(asof, uni, band=(20.0, 31.0), width_y=0.25,
                              lookback=5, min_periods=2)
    row = lad[lad["date"] == DATES[0]].iloc[0]
    assert row["agg_par"] == pytest.approx(1.5e9)
    assert row["own"] == pytest.approx(0.15, abs=1e-12)


def test_a_missing_free_float_falls_back_and_is_FLAGGED_never_treated_as_zero():
    """A zero denominator is exactly the kind of plausible number that must never be
    confused with a missing one: it would make a bucket's ownership infinite, or drop it."""
    uni = _universe(DATES, ["AAA"], ttms=[20.1])
    uni["free_float"] = np.nan
    uni["outstanding_amt"] = 10e9
    obs = pd.concat([_obs("TLT", d, d, {"AAA": 1e9}) for d in DATES], ignore_index=True)
    asof = AG.as_of_panel(obs, DATES)
    lad = AG.ownership_ladder(asof, uni, band=(20.0, 31.0), width_y=0.25,
                              lookback=5, min_periods=2)
    row = lad[lad["date"] == DATES[0]].iloc[0]
    assert row["own"] == pytest.approx(0.10, abs=1e-12)
    assert row["n_float_fallback"] == 1


# ---------------------------------------------------- the z-score

def test_the_bucket_z_is_strictly_backward_looking():
    """``shift(1)`` before the rolling window, so the observation being scored is never
    inside the mean and standard deviation it is scored against.

    Constructed so the answer is known: a bucket sitting at a constant 0.10 for five days
    and then jumping to 0.20 must score a large POSITIVE z on the jump day -- which is
    only possible if the jump is excluded from its own scale. Include it and the z is
    bounded by the sample size instead.
    """
    n = 12
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    vals = [0.10] * (n - 1) + [0.20]
    f = pd.DataFrame({"date": dates, "bucket": 0.0, "own": vals})
    #: A constant prior series has zero standard deviation, which is a genuine NaN rather
    #: than an infinite z, so give the history a little jitter and check the ORDER of
    #: magnitude instead.
    rng = np.random.default_rng(7)
    f["own"] = f["own"] + np.r_[rng.normal(0, 1e-4, n - 1), 0.0]
    z = AG._rolling_z(f, "own", lookback=20, min_periods=5)
    assert z.iloc[-1] > 50, z.iloc[-1]
    #: and the scored value is genuinely absent from its own window: recomputing WITHOUT
    #: the shift gives a far smaller number.
    prior = f["own"]
    mu = prior.rolling(20, min_periods=5).mean()
    sd = prior.rolling(20, min_periods=5).std()
    z_leaky = ((f["own"] - mu) / sd).iloc[-1]
    assert z_leaky < z.iloc[-1] / 10.0, (z_leaky, z.iloc[-1])


def test_min_periods_is_honoured_so_a_z_is_never_built_on_two_observations():
    f = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=6, freq="B"),
                      "bucket": 0.0, "own": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]})
    z = AG._rolling_z(f, "own", lookback=20, min_periods=5)
    assert z.iloc[:5].isna().all()
    assert np.isfinite(z.iloc[5])


# ---------------------------------------------------- the buckets

def test_the_bucket_is_a_constant_maturity_offset_from_the_bands_lower_edge():
    """Bucket 0 is always "about to be deleted", whatever the calendar says. That is what
    makes a z of a bucket's measure comparable across ten years."""
    t = pd.Series([20.0, 20.24, 20.26, 21.0, 30.9, 40.0])
    b = AG.bucket_of(t, band_low=20.0, band_high=31.0, width_y=0.25)
    assert list(b[:4]) == [0.0, 0.0, 1.0, 4.0]
    #: above the band it SATURATES rather than running away, so a bond issued far outside
    #: gets the top bucket and not an unbounded index.
    assert b.iloc[-1] == b.max() == 44.0


def test_the_bucket_measure_is_broadcast_to_every_bond_in_the_bucket():
    uni = _universe(DATES, CUSIPS, ttms=[20.1, 20.2, 21.1, 21.2])
    lad = pd.DataFrame({"date": [DATES[0]] * 2, "bucket": [0.0, 4.0],
                        "own_z": [1.5, -2.5]})
    got = AG.attach(uni[uni["date"] == DATES[0]], lad, column="own_z",
                    out_column="agg", band=(20.0, 31.0), width_y=0.25)
    assert set(got[got["ttm"] < 21.0]["agg"]) == {1.5}
    assert set(got[got["ttm"] > 21.0]["agg"]) == {-2.5}


# ---------------------------------------------------- the signal hook

def test_precomputed_refuses_a_missing_column_instead_of_returning_all_nan():
    """An all-NaN score reads as "no signal here" when what happened is "no data here",
    and this repo has already paid for that confusion once (``par_per_share`` on the two
    issuers that publish no share count)."""
    df = pd.DataFrame({"date": [pd.Timestamp("2024-01-01")], "cusip": ["AAA"],
                       "agg_own__tlt_only__w025": [1.0]})
    with pytest.raises(KeyError, match="precomputed"):
        SIG.sig_precomputed(df, column="agg_own__coupon_long__w025")


def test_precomputed_applies_the_sign_it_was_given():
    df = pd.DataFrame({"date": [pd.Timestamp("2024-01-01")], "cusip": ["AAA"],
                       "col": [2.0]})
    assert SIG.sig_precomputed(df, column="col", sign=1.0).iloc[0] == 2.0
    assert SIG.sig_precomputed(df, column="col", sign=-1.0).iloc[0] == -2.0


def test_raw_z_mode_leaves_an_already_standardised_score_alone():
    """The aggregate score IS a z against the bucket's own history, so re-standardising it
    would silently change what ``structure.min_abs_score`` -- the entry threshold -- means.
    A cross-sectional z preserves the within-date RANKING, so the bond selection would look
    unchanged while every threshold moved: the kind of no-op that reads as working."""
    df = pd.DataFrame({"date": [pd.Timestamp("2024-01-01")] * 3,
                       "cusip": ["A", "B", "C"], "col": [1.0, 2.0, 3.0]})
    out = SIG.combine(df, {"precomputed": 1.0}, z_mode="raw",
                      signal_kwargs={"precomputed": {"column": "col"}})
    assert list(out["score"]) == [1.0, 2.0, 3.0]
    cs = SIG.combine(df, {"precomputed": 1.0}, z_mode="cross_section",
                     signal_kwargs={"precomputed": {"column": "col"}})
    assert list(cs["score"]) != [1.0, 2.0, 3.0]


def test_an_unknown_z_mode_is_refused_rather_than_falling_through_to_raw():
    df = pd.DataFrame({"date": [pd.Timestamp("2024-01-01")], "cusip": ["A"], "col": [1.0]})
    with pytest.raises(ValueError, match="z_mode"):
        SIG.combine(df, {"precomputed": 1.0}, z_mode="crosssection",
                    signal_kwargs={"precomputed": {"column": "col"}})


# ---------------------------------------------------- the matched-rarity placebo

def test_the_placebo_fires_on_a_CROSSING_not_on_everything_below_the_boundary():
    """A matched placebo needs the same shape AND the same rarity as the real signal.

    ``sig_deletion`` flags everything below its boundary, so at 24y inside a 20-31y
    universe it would fire on most of the board and be a maturity tilt rather than an
    event. The placebo must fire only on the narrow band a bond passes through.
    """
    d = pd.DataFrame({"date": [pd.Timestamp("2024-01-31")] * 5,
                      "ttm": [20.5, 22.0, 23.9, 24.05, 28.0]})
    cross = SIG.sig_crossing(d, boundary=24.0, horizon_m=3)
    delete = SIG.sig_deletion(d, band_low=24.0, horizon_m=3)
    assert (cross < 0).sum() < (delete < 0).sum(), (list(cross), list(delete))
    #: the bond just above the boundary is the one crossing it inside the horizon
    assert cross.iloc[3] < 0
    #: one already well below it is NOT an event any more
    assert cross.iloc[0] == 0.0

r"""Known-answer tests for the FedLock replication of the lead study.

Two jobs. First, the ordinary one: the loader must drop what it cannot date, the
era adjustment must reconstruct, and the published cross-section claims must
check out on the column they were made about.

Second, and more important: FedLock has **no publication axis**, and the
estimator it is fed into has a ``point_in_time`` switch. A reader who flips that
switch gets a series back, identical to the as-published one, with no error.
These tests pin that trap in place so it cannot be mistaken for a gate.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for _p in (str(REPO), str(REPO / "notebooks" / "rv")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fed_sentiment_lead_data as D  # noqa: E402
import fedlock_data as F  # noqa: E402

SNAP = REPO / "notebooks" / "rv" / "fedlock_v3_snapshot.parquet"
needs_snapshot = pytest.mark.skipif(not SNAP.exists(), reason="snapshot not built")


def _payload(rows, config=None):
    return {"speeches": rows, "config": config or {"builtOn": "2026-08-17",
                                                   "dataThrough": "2026-08-13"}}


def _row(d, m=50.0, ma=50.0, a="Jane Q Speaker", **kw):
    base = {"d": d, "m": m, "ma": ma, "s": 1.7, "n": 30, "a": a,
            "tt": "T " + str(d), "st": "prepared_remarks", "wc": 2000,
            "inst": "Board", "u": "", "src": "federalreserve.gov"}
    base.update(kw)
    return base


# ---------------------------------------------------------------- parsing
def test_year_only_rows_are_dropped_and_counted():
    """327 real rows carry a bare year; placing them would fabricate timing."""
    rows = [_row("2020-03-01"), _row("2008"), _row("2013"), _row("2021-06-02")]
    frame, prov = F.parse_payload(_payload(rows))
    assert len(frame) == 2
    assert prov["n_undated"] == 2 and prov["n_rows"] == 4
    assert set(frame["date"].dt.year) == {2020, 2021}


def test_parse_reports_who_the_undated_rows_belong_to():
    rows = [_row("2008", a="Richard W Fisher"), _row("2009", a="Richard W Fisher"),
            _row("2010", a="Janet L Yellen"), _row("2020-03-01")]
    _, prov = F.parse_payload(_payload(rows))
    assert prov["undated_by_speaker"]["Richard W Fisher"] == 2
    assert prov["undated_by_speaker"]["Janet L Yellen"] == 1


def test_date_parsing_does_not_depend_on_row_order():
    """pd.to_datetime infers one format from the first value.

    With a mix of "1985-07-25" and "2008" that makes the set of undated rows a
    property of the FILE ORDER rather than of the values. Real payloads start
    with a full date, so this would only have surfaced if the source ever
    reordered.
    """
    rows = [_row("2008", a="Early Year"), _row("2020-03-01", a="Real Date")]
    a_frame, a_prov = F.parse_payload(_payload(rows))
    b_frame, b_prov = F.parse_payload(_payload(list(reversed(rows))))
    assert a_prov["n_undated"] == b_prov["n_undated"] == 1
    assert set(a_frame["speaker"]) == set(b_frame["speaker"]) == {"Real Date"}
    assert list(a_prov["undated_by_speaker"]) == ["Early Year"]


# ---------------------------------------------------------------- G7
@needs_snapshot
def test_g7_asserts_the_dataset_has_no_publication_axis():
    speeches, prov = F.load_speeches()
    out = F.gate_single_vintage(speeches, prov)
    assert out["row_level_vintage_fields"] == 0
    assert out["built_on"] == "2026-08-17"


def test_g7_fails_if_a_real_vintage_field_ever_appears():
    """If FedLock later publishes a per-row date, the study must be re-gated."""
    frame = pd.DataFrame({"date": pd.to_datetime(["2020-01-01"]), "m": [50.0],
                          "ma": [50.0], "pub_date": pd.to_datetime(["2020-01-02"])})
    with pytest.raises(AssertionError, match="G7 FAILED"):
        F.gate_single_vintage(frame, {"built_on": "2026-08-17"})


def test_g7_fails_when_the_vintage_stamp_is_missing():
    frame = pd.DataFrame({"date": pd.to_datetime(["2020-01-01"]), "m": [50.0]})
    with pytest.raises(AssertionError, match="G7 FAILED"):
        F.gate_single_vintage(frame, {})


@needs_snapshot
def test_the_point_in_time_switch_is_INERT_on_fedlock():
    """The trap, pinned.

    ``to_score_book`` sets ``pub_date = date`` because there is nothing else to
    set it to. So ``sentiment_index(point_in_time=True)`` runs, returns a series
    and raises nothing -- and that series is byte-identical to the as-published
    one. It is not a point-in-time series; it is the same series with a gate that
    had nothing to remove. G1 in the first study asserted that a gate which
    removes nothing is not wired up; here nothing CAN be removed, which is why
    this study reports one vintage and no PIT column at all.
    """
    speeches, _ = F.load_speeches()
    book = F.to_score_book(speeches)
    cfg = D.LeadConfig()
    grid = D.weekly_grid("2015-01-02", "2016-01-01", cfg.week_anchor)
    ap = D.sentiment_index(book, grid, cfg, point_in_time=False)["sentiment"]
    pit = D.sentiment_index(book, grid, cfg, point_in_time=True)["sentiment"]
    pd.testing.assert_series_equal(ap, pit)
    with pytest.raises(AssertionError, match="G1 FAILED"):
        D.gate_vintage(book, grid, cfg)


# ---------------------------------------------------------------- G8
@needs_snapshot
def test_g8_era_adjustment_reconstructs_from_its_published_definition():
    speeches, _ = F.load_speeches()
    out = F.gate_era_adjustment(speeches)
    assert out["corr"] > 0.99
    assert out["mean_abs_resid"] < 0.5


def test_g8_fails_when_ma_is_not_the_published_transform():
    rng = np.random.default_rng(0)
    n = 400
    dates = pd.date_range("2010-01-01", periods=n, freq="10D")
    m = 50 + rng.normal(scale=6, size=n)
    frame = pd.DataFrame({"date": dates, "m": m, "ma": rng.normal(50, 5, n)})
    with pytest.raises(AssertionError, match="G8 FAILED"):
        F.gate_era_adjustment(frame)


# ------------------------------------------------- known-answer cross-section
@needs_snapshot
def test_published_speaker_claims_hold_on_the_ERA_ADJUSTED_column():
    """FedLock's Rankings tab is era-adjusted, and the claim is about that.

    Checking it on raw means produces a false failure, because raw is dominated
    by the era a speaker served in.
    """
    speeches, _ = F.load_speeches()
    _, info = F.known_answer_speaker_ranking(speeches, score_column="ma")
    for name in ("Hoenig", "Plosser", "Fisher", "Lacker"):
        rank = info["hawk_ranks"][name]
        assert rank is not None and rank <= 5, f"{name} ranked {rank}, expected top 5"
    # 91.2%, not 100%: two of FedLock's own labels invert. Waller is on the hawk
    # list and ranks 40/47; Bostic is on the dove list and ranks 15. Both are
    # 2020s figures, where the corpus is dense and the quarterly demeaning does
    # the most work. The claim under test -- the four named ZIRP-era hawks at the
    # top, Evans at the bottom -- holds; the roster as a whole does not, and that
    # is worth knowing before the series is used.
    assert info["pair_separation"] >= 0.85, (
        f"era-adjusted scores should order almost every hawk above almost every "
        f"dove; got {info['pair_separation']:.1%}"
    )
    assert info["hawk_ranks"]["Waller"] > 30, "the documented Waller inversion moved"
    assert info["dove_ranks"]["Evans"] >= 40


@needs_snapshot
def test_the_same_claims_FAIL_on_raw_scores_and_that_is_the_point():
    """Locks in why the column matters: raw is era-dominated."""
    speeches, _ = F.load_speeches()
    _, raw = F.known_answer_speaker_ranking(speeches, score_column="m")
    _, era = F.known_answer_speaker_ranking(speeches, score_column="ma")
    assert raw["pair_separation"] < era["pair_separation"]
    assert raw["hawk_ranks"]["Hoenig"] > era["hawk_ranks"]["Hoenig"]


@needs_snapshot
def test_the_published_timeline_peak_and_trough_reproduce():
    """Q3-2022 peak, Q2-2020 trough -- on the series this study actually uses."""
    speeches, _ = F.load_speeches()
    tr = F.gaussian_trend(speeches, score_column="m")
    tr = tr[tr.index >= "1995-01-01"]
    assert tr.idxmax().to_period("Q") == pd.Period("2022Q3"), tr.idxmax()
    assert tr.idxmin().to_period("Q") == pd.Period("2020Q2"), tr.idxmin()


# ---------------------------------------------------------------- plumbing
@needs_snapshot
def test_score_book_feeds_the_unchanged_estimator():
    speeches, _ = F.load_speeches()
    book = F.to_score_book(speeches)
    cfg = D.LeadConfig()
    grid = D.weekly_grid("2010-01-01", "2012-01-01", cfg.week_anchor)
    idx = D.sentiment_index(book, grid, cfg, point_in_time=False)
    assert idx["sentiment"].notna().mean() > 0.9
    assert idx["n_speeches"].median() >= cfg.min_speeches_in_window


@needs_snapshot
def test_filters_narrow_the_book_monotonically():
    speeches, _ = F.load_speeches()
    base = len(F.to_score_book(speeches))
    assert len(F.to_score_book(speeches, speech_types=("prepared_remarks",))) < base
    assert len(F.to_score_book(speeches, min_comparisons=25)) <= base
    assert len(F.to_score_book(speeches, max_sigma=1.8)) <= base


@needs_snapshot
def test_v2_v3_comparison_reproduces_the_published_rank_correlation():
    """The methodology claims rho = 0.82 between the two runs."""
    v2p = REPO / "notebooks" / "rv" / "fedlock_v2_snapshot.parquet"
    if not v2p.exists():
        pytest.skip("v2 snapshot not built")
    v3, _ = F.load_speeches()
    v2 = F.read_snapshot(v2p)
    out = F.compare_vintages(v2, v3)
    assert out["matched"] > 3000
    assert 0.78 <= out["m"]["spearman"] <= 0.88, out["m"]["spearman"]
    assert out["m"]["move_in_sd"] > 0.3, "a model swap that moves nothing is suspicious"


# ---------------------------------------------------------------- G6 at this density
def test_filter_offset_recalibrates_at_fedlocks_speech_density():
    """G6 must be re-run at 2.52 speeches/week, not inherited from 3.3.

    The offset is a property of how densely the response side is sampled, so
    importing the first study's +3w without re-measuring would be exactly the
    kind of borrowed constant this pair of studies exists to avoid.
    """
    cfg = D.LeadConfig()
    lags = cfg.lags()
    vals = []
    for seed in range(6):
        p0, b0, _ = D.synthetic_world(lead_days=0, rng=np.random.default_rng(900 + seed),
                                      speeches_per_week=2.52)
        c0, _ = D.build_surprise_composite(p0, cfg)
        x = D.weekly_last(c0, cfg.week_anchor)
        y = D.sentiment_index(b0, x.index, cfg, point_in_time=False)["sentiment"]
        xt, yt, _ = D.transform_pair(x, y, "levels")
        X, Y, _ = D.lag_matrix(xt, yt, lags)
        c = D.lag_curve_common(X, Y, lags)
        vals.append(int(c["lag_weeks"].iloc[int(np.nanargmax(c["corr"].to_numpy()))]))
    assert 1 <= float(np.median(vals)) <= 6, f"zero-lead argmax {vals}"


def test_speeches_per_week_actually_changes_the_book_size():
    a = D.synthetic_world(lead_days=0, rng=np.random.default_rng(1), speeches_per_week=1.0)[1]
    b = D.synthetic_world(lead_days=0, rng=np.random.default_rng(1), speeches_per_week=4.0)[1]
    assert len(b) > 3 * len(a)


@needs_snapshot
def test_snapshot_carries_the_documented_shape():
    speeches, prov = F.load_speeches()
    assert len(speeches) == prov["n_dated"] > 3500
    assert prov["n_undated"] > 300
    assert speeches["date"].min().year == 1985
    assert set(("m", "ma", "s", "n", "speaker", "speech_type")).issubset(speeches.columns)
    assert float((speeches["s"] < 2.0).mean()) > 0.95  # documented convergence

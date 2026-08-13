"""The Citi curve input: key conversion, the reference merge, and what gets dropped.

The bug this file exists for is worth stating, because it hid for the whole life of the function
and it hid *as a different bug*. `fetch_curveset_snapshot` took a reference frame and used its key
column as the Citi ISIN. Every UST reference frame in this repo is keyed by the 9-character CUSIP,
Citi keys bonds by the 12-character ISIN, so the tags built were `RATES.BOND.912810EX2.YIELD`
against a wire that answers to `RATES.BOND.US912810EX29.YIELD`. Nothing resolved, the call raised
"Citi returned no rows", and the notebook's `except` reported **"CVSNAP unavailable — run with
Excel signed in"**. A key-format bug read as a missing Excel bridge, and the fix was assumed to be
a human logging into a spreadsheet.

The merge had the same defect in its quieter half: `reference.rename(columns={"cusip": "isin"})`
relabels a 9-character key and left-joins it onto 12-character keys, so the join succeeds with
every reference column null. `ttm` all-NaN gives a spline with no x-axis — a blank result, not an
exception, which is the same shape as the `apply_universe_filter` null-column bug.

These tests use a fake quotes object, so they are hermetic: no Excel, no disk cache, no wire.
"""

from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import pytest

from BT.gss_fly.data import citi_curve_quotes, cusip_to_isin, fetch_curveset_snapshot

# CUSIP -> ISIN pairs read off the Velocity cache's own filenames, so these are observed values
# rather than a re-derivation of the check digit by the same algorithm under test.
KNOWN_ISINS = [
    ("912810EX2", "US912810EX29"),
    ("912810EY0", "US912810EY02"),
    ("91282CLG4", "US91282CLG41"),
]


class FakeQuotes:
    """Answers only to correctly-formed 12-character-ISIN tags, exactly as Citi does."""

    def __init__(self, isin_yields, stamp="2026-08-07"):
        self.isin_yields = dict(isin_yields)
        self.stamp = pd.Timestamp(stamp)
        self.asked = None

    def frame(self, tags, freq, start=None, end=None):
        self.asked = list(tags)
        data = {}
        for tag in tags:
            parts = tag.split(".")
            isin = parts[2] if len(parts) > 2 else ""
            if isin in self.isin_yields:
                data[tag] = [self.isin_yields[isin]]
        if not data:
            return pd.DataFrame()
        return pd.DataFrame(data, index=pd.DatetimeIndex([self.stamp]))


def _reference(n=40, key="cusip"):
    """A CUSIP-keyed reference frame shaped like the MDP's, with a realistic curve."""
    cusips = [f"91282C{i:02d}0"[:9] for i in range(n)]
    ttm = np.linspace(1.0, 29.0, n)
    df = pd.DataFrame({
        "cusip": cusips,
        "ttm": ttm,
        "cpn": np.full(n, 4.0),
        "rank": [0 if i < 3 else 9 for i in range(n)],
        "oi": np.full(n, 1.0),
    })
    if key == "isin":
        df["isin"] = [cusip_to_isin(c) for c in cusips]
    return df


def _yields(ref):
    """A smooth curve: 3.5% at 1y rising to 5.0% at 29y."""
    return {
        cusip_to_isin(c): 3.5 + 1.5 * (t - 1.0) / 28.0
        for c, t in zip(ref["cusip"], ref["ttm"])
    }


# --------------------------------------------------------------------- key conversion
@pytest.mark.parametrize("cusip,isin", KNOWN_ISINS)
def test_cusip_to_isin_matches_the_cache_filenames(cusip, isin):
    assert cusip_to_isin(cusip) == isin


def test_cusip_to_isin_passes_an_isin_through():
    assert cusip_to_isin("US912810EX29") == "US912810EX29"


def test_tags_are_built_from_isins_not_cusips():
    """The original bug, pinned directly: every tag must carry the 12-character key."""
    ref = _reference()
    q = FakeQuotes(_yields(ref))
    fetch_curveset_snapshot(pd.Timestamp("2026-08-07"), reference=ref, values=("YIELD",),
                            quotes=q, max_staleness=datetime.timedelta(days=2), strict=False)
    assert q.asked, "no tags were requested"
    for tag in q.asked:
        isin = tag.split(".")[2]
        assert len(isin) == 12 and isin.startswith("US"), f"tag {tag} is not ISIN-keyed"


# ------------------------------------------------------------------- the silent half
def test_reference_merge_survives_a_cusip_keyed_frame():
    """The quiet half: a renamed CUSIP joins onto nothing and every reference column goes null."""
    ref = _reference()
    snap = fetch_curveset_snapshot(pd.Timestamp("2026-08-07"), reference=ref, values=("YIELD",),
                                   quotes=FakeQuotes(_yields(ref)),
                                   max_staleness=datetime.timedelta(days=2), strict=False)
    assert len(snap) == len(ref)
    assert snap["ttm"].notna().all(), "reference merge produced null ttm — the join missed"
    assert snap["cusip"].notna().all()


def test_a_merge_that_matches_nothing_raises_instead_of_returning_nulls():
    """Reachable through `isins=`, where the tag set and the reference frame are supplied
    separately and so can disagree. Going through `reference=` alone the two now derive the same
    key, which is the structural half of the fix — a first version of this test tried it that way
    and tripped the earlier "Citi returned no rows" guard instead, proving the wrong thing.
    """
    ref = _reference()
    unrelated = _reference(n=12)
    unrelated["cusip"] = [f"999999{i:02d}0"[:9] for i in range(len(unrelated))]
    with pytest.raises(RuntimeError, match="matched 0"):
        fetch_curveset_snapshot(
            pd.Timestamp("2026-08-07"),
            isins=[cusip_to_isin(c) for c in ref["cusip"]],   # tags the wire DOES answer
            reference=unrelated,                              # reference it cannot join to
            values=("YIELD",), quotes=FakeQuotes(_yields(ref)),
            max_staleness=datetime.timedelta(days=2), strict=False,
        )


def test_an_isin_keyed_reference_still_works():
    ref = _reference(key="isin")
    snap = fetch_curveset_snapshot(pd.Timestamp("2026-08-07"), reference=ref, values=("YIELD",),
                                   quotes=FakeQuotes(_yields(ref)),
                                   max_staleness=datetime.timedelta(days=2), strict=False)
    assert snap["ttm"].notna().all()


# ------------------------------------------------------------------------- the filters
def test_the_outlier_cut_removes_a_corrupt_long_bond():
    """Citi served -0.679% for a May-2046 UST with its neighbours at 4-5% on 2026-07-15.

    That value is inside any absolute band wide enough to admit a real curve, which is why the
    cross-sectional cut exists.
    """
    ref = _reference(n=60)
    ys = _yields(ref)
    victim = cusip_to_isin(ref["cusip"].iloc[40])
    ys[victim] = -0.679064
    out, rep = citi_curve_quotes(pd.Timestamp("2026-08-07"), ref, values=("YIELD",),
                                 exclude_ranks=(), quotes=FakeQuotes(ys, "2026-08-07"),
                                 max_staleness=datetime.timedelta(days=2))
    assert rep["outlier_dropped"] == 1, rep
    assert ref["cusip"].iloc[40] in rep["outlier_cusips"]
    assert victim not in set(out["isin"])


def test_the_outlier_cut_keeps_a_clean_curve_intact():
    """The first attempt at this used median-absolute-deviations and ate 20 genuine bonds.

    MAD on this cross-section is ~0.4bp, so even 8 MADs cuts at ~3.2bp — inside the real dispersion
    that seasoned high-coupon issues produce, which is the richness the strategy trades.
    """
    ref = _reference(n=60)
    ys = _yields(ref)
    # Genuine seasoning spread: a few bonds 12bp off the local median, below the 100bp threshold.
    for i in (10, 25, 44):
        ys[cusip_to_isin(ref["cusip"].iloc[i])] += 0.12
    out, rep = citi_curve_quotes(pd.Timestamp("2026-08-07"), ref, values=("YIELD",),
                                 exclude_ranks=(), quotes=FakeQuotes(ys, "2026-08-07"),
                                 max_staleness=datetime.timedelta(days=2))
    assert rep["outlier_dropped"] == 0, rep["outlier_cusips"]
    assert rep["band_dropped"] == 0
    assert len(out) == len(ref)


def test_the_absolute_band_removes_an_impossible_value():
    ref = _reference(n=40)
    ys = _yields(ref)
    ys[cusip_to_isin(ref["cusip"].iloc[7])] = 10040.1  # a real value from the cache
    out, rep = citi_curve_quotes(pd.Timestamp("2026-08-07"), ref, values=("YIELD",),
                                 exclude_ranks=(), quotes=FakeQuotes(ys, "2026-08-07"),
                                 max_staleness=datetime.timedelta(days=2))
    assert rep["band_dropped"] == 1
    assert out["yield"].between(-1.0, 25.0).all()


def test_on_the_runs_are_excluded_from_the_fit_set():
    ref = _reference(n=40)          # ranks 0,1,2 on the first three
    out, rep = citi_curve_quotes(pd.Timestamp("2026-08-07"), ref, values=("YIELD",),
                                 quotes=FakeQuotes(_yields(ref), "2026-08-07"),
                                 max_staleness=datetime.timedelta(days=2))
    assert rep["after_universe_filter"] == len(ref) - 3
    assert len(out) == len(ref) - 3


def test_min_ttm_drops_the_bills():
    ref = _reference(n=40)
    ref.loc[ref.index[:5], "ttm"] = 0.25
    out, rep = citi_curve_quotes(pd.Timestamp("2026-08-07"), ref, values=("YIELD",),
                                 exclude_ranks=(), quotes=FakeQuotes(_yields(ref), "2026-08-07"),
                                 max_staleness=datetime.timedelta(days=2))
    assert rep["after_universe_filter"] == len(ref) - 5
    assert (out["ttm"] >= 1.0).all()


# ------------------------------------------------------------------------ the guards
def test_a_thin_date_raises_rather_than_fitting_a_handful():
    """Per-date coverage genuinely swings from 18 to 327 bonds; a 5-bond curve still plots."""
    ref = _reference(n=40)
    ys = _yields(ref)
    thin = {k: v for i, (k, v) in enumerate(ys.items()) if i < 5}
    with pytest.raises(RuntimeError, match="fittable Citi quotes"):
        citi_curve_quotes(pd.Timestamp("2026-08-07"), ref, values=("YIELD",), exclude_ranks=(),
                          quotes=FakeQuotes(thin, "2026-08-07"),
                          max_staleness=datetime.timedelta(days=2))


def test_a_stale_resolution_raises_and_is_measured_in_DAYS():
    """Citi resolves as-of. A DAILY series asked for 15:00 is 15h "stale" and perfectly fine —
    measuring the limit as a timedelta rejects every well-formed request, so the check is on dates.
    """
    ref = _reference(n=40)
    q = FakeQuotes(_yields(ref), stamp="2026-08-04")
    with pytest.raises(RuntimeError, match="stale"):
        citi_curve_quotes(pd.Timestamp("2026-08-07"), ref, values=("YIELD",), exclude_ranks=(),
                          quotes=q, max_staleness=datetime.timedelta(days=10))


def test_an_intraday_request_against_daily_data_is_not_stale():
    ref = _reference(n=40)
    q = FakeQuotes(_yields(ref), stamp="2026-08-07")
    out, rep = citi_curve_quotes(pd.Timestamp("2026-08-07 15:00"), ref, values=("YIELD",),
                                 exclude_ranks=(), quotes=q,
                                 max_staleness=datetime.timedelta(days=2))
    assert rep["stale_days"] == 0
    assert len(out) == len(ref)


def test_the_report_accounts_for_every_bond():
    ref = _reference(n=40)
    ys = _yields(ref)
    ys[cusip_to_isin(ref["cusip"].iloc[9])] = 10040.1
    out, rep = citi_curve_quotes(pd.Timestamp("2026-08-07"), ref, values=("YIELD",),
                                 exclude_ranks=(), quotes=FakeQuotes(ys, "2026-08-07"),
                                 max_staleness=datetime.timedelta(days=2))
    assert rep["quoted_by_citi"] - rep["band_dropped"] - rep["outlier_dropped"] == rep["fittable"]
    assert rep["fittable"] == len(out)

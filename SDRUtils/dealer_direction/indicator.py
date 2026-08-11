"""The daily street-positioning indicator.

WHAT THIS IS
------------
One number per **(tenor bucket, availability date, venue class, series)**: the
signed DV01 of model-labelled customer risk transfer that became public that
day, expressed against that cell's **own history**. It is the retarget the
pre-registered branch called for -- the intraday hedge-trigger and max-pain
components are gone; the tape reconstruction, the direction inference and the
change of basis are what feed it.

WHY THE API IS SHAPED LIKE THIS
-------------------------------
``docs/dealer_direction/2026-08-11-package-exclusion-skew.md`` measured that the
retained population is a **biased sample**, and that the bias is a fixed
function of the curve region: DV01 retention runs **0.761 at 0-1Y down to 0.495
at 15-20Y**, a **1.54x cross-bucket scaling distortion**. Two consequences, and
they are the whole design:

**1. A level may only be read against its own history.** Comparing the 0-1Y
level to the 15-20Y level compares 76% of one bucket's tape DV01 against 50% of
the other's. That comparison is one ``pivot`` away in any long frame, so this
module does not hand back a long frame with the level in a shared column. The
level lives in :func:`level_column` -- a **bucket-suffixed** name -- so that
concatenating two buckets produces a block-diagonal frame of NaNs rather than a
comparison, and :meth:`DailyPositioning.cross_section` /
:meth:`DailyPositioning.pivot_levels` exist only to refuse, with the measurement
in the error message.

**2. The z-score is the one cross-bucket-safe view, and only while retention
holds still.** Write the observed level as ``r_b * L`` for a retention factor
``r_b``. Then

::

    z = (r_b*L - r_b*mu) / (r_b*sigma) = (L - mu) / sigma

so **a constant retention factor cancels exactly**. That is why
:meth:`DailyPositioning.standardised` is allowed to put every bucket in one
frame while the level is not. The cancellation needs ``r_b`` constant, and the
skew doc measured one bucket where it is not: **1-2Y drifts at +5.07 pp/yr
(t = +3.21)** in its exclusion rate -- the meeting-dated front end, i.e. the
bucket that matters most here. So every published row carries its coverage
fraction, a measured drift trend, and a flag; :data:`PINNED_DRIFT_BUCKETS`
stands in when the consumer's window is too short to measure a 5 pp/yr slope
(a 30-day window cannot).

Both halves are pinned by known-answer tests: halve a bucket's level and z does
not move; drift the retention and it does.

THE TWO ALLOCATIONS ARE NOT THE SAME ALLOCATION
-----------------------------------------------
The **level** is key-rate risk, allocated across :data:`krd.PILLARS` by
rateslib's delta ladder and rolled up here. The **coverage fraction** is a
maturity-point allocation of gross ``|DV01|``, because an excluded unit has no
key-rate profile *by construction* -- that is why it was excluded. They answer
the same question on different grids and the numerator/denominator of coverage
must both come from the maturity-point grid. Do not read ``coverage_frac`` as
"the fraction of this cell's key-rate risk that was retained"; read it as "the
fraction of this bucket-day's gross tape DV01 that reached the ladder at all".

THE LEVEL IS RAW, AND THE ADJUSTED ONE SITS BESIDE IT
------------------------------------------------------
``delta_dv01`` is published unadjusted. Dividing by coverage to undo the drift
assumes the excluded flow has the **same directional mix** as the retained flow
-- the one assumption the skew doc says cannot be verified, and the same
assumption :meth:`DailyPositioning.rescale_for_cross_section` is made loud
about. Applying it silently to every row while refusing it loudly for
cross-sections would be incoherent, so the adjusted series is a *second* column
(:func:`level_column` with ``basis="cov_adj"``), the primary basis travels with
the number in ``primary_level_basis``, and the effect of the choice is measured
in ``docs/dealer_direction/INDICATOR.md``.

The adjustment divides by a **smoothed** coverage, not by the day's own
fraction: the defect is a ~5 pp/yr trend, and dividing by a noisy daily ratio
injects daily noise to fix a slow drift.

IT IS A FLOW SERIES AND IT WILL NOT CUMULATE
---------------------------------------------
Compression and allocation are never publicly reported, so risk leaves a
dealer's book with no offsetting print and a running sum carries an unbounded,
*monotone* error. :meth:`DailyPositioning.cumulate` and its three synonyms exist
so the attempt lands on a named refusal that points at
:func:`ladder.decayed_flow`, which has no default half-life for the same reason.

THE CLOCK, THE VENUES, THE WEIGHT
----------------------------------
Every row is stamped on ``Clocks.visibility`` (New York date) and a frame whose
``visibility_date`` disagrees with its own ``visibility_timestamp`` is refused:
dating a print on execution claims it was actionable before Part 43 published
it. D2C, D2D and ``VENUE_UNKNOWN`` are three series and are never merged --
"dealers are distributing risk" is its own signal. The weight is
``conventions.signed_weight(p) = 2p - 1``, never ``p``.
"""
from __future__ import annotations

import dataclasses
import datetime
import re

import numpy as np
import pandas as pd

from SDRUtils.dealer_direction import conventions as conv
from SDRUtils.dealer_direction import krd, ladder
from SDRUtils.dealer_direction import types as T

# --------------------------------------------------------------------------
# the vocabulary
# --------------------------------------------------------------------------

#: The bucket space this module publishes in. Not :data:`krd.BUCKET_SPACE` --
#: the 28-pillar grid is the change of basis, this is the reporting grid, and
#: they must not share a name or a rolled-up cell and a pillar cell would
#: aggregate together.
BUCKET_SPACE = "TENOR10"

#: The ten tenor buckets, verbatim from the skew document's §1 table. The
#: retention factors, the drift measurement and the coverage denominator only
#: *exist* on this vocabulary, so publishing on any other one would leave the
#: indicator with no measured bias to report.
TENOR_BUCKETS = ("0-1Y", "1-2Y", "2-3Y", "3-5Y", "5-7Y", "7-10Y", "10-15Y",
                 "15-20Y", "20-30Y", "30Y+")

#: Right edges, in years. **Right-edge inclusive**: a 10Y point is ``7-10Y``,
#: which is the skew document's own convention ("standard pillars on the right
#: edge (a 10Y spot swap is `7-10Y`)"), and it is checked against that extract's
#: own ``tenor_bucket`` column on every leg by ``scratch/ddind_coverage.py``
#: (GATE 1: 2,326,777/2,326,777 agree; the 4 legs with no extract bucket carry
#: zero DV01). Get this wrong and every measured retention factor is attached to
#: the wrong bucket.
_BUCKET_RIGHT_EDGE = ((1.0, "0-1Y"), (2.0, "1-2Y"), (3.0, "2-3Y"),
                      (5.0, "3-5Y"), (7.0, "5-7Y"), (10.0, "7-10Y"),
                      (15.0, "10-15Y"), (20.0, "15-20Y"), (30.0, "20-30Y"))

#: DV01 retention by bucket, from the skew document §1. **Deliberately not used
#: by any code path in this module.** It is here so the error messages can quote
#: it and a reader can find it; :meth:`DailyPositioning.rescale_for_cross_section`
#: makes the caller pass the factors in, so that undoing the distortion is an
#: act rather than a default.
MEASURED_RETENTION_FACTORS = {
    "0-1Y": 0.761, "1-2Y": 0.522, "2-3Y": 0.602, "3-5Y": 0.554, "5-7Y": 0.524,
    "7-10Y": 0.537, "10-15Y": 0.601, "15-20Y": 0.495, "20-30Y": 0.512,
    "30Y+": 0.612,
}

#: Buckets whose exclusion rate was measured to be drifting, with the finding.
#: A consumer running on a short window cannot detect a 5 pp/yr slope from the
#: data, so the measurement stands in for one that cannot be made.
PINNED_DRIFT_BUCKETS = {
    "1-2Y": ("exclusion rate +5.07 pp/yr (t = +3.21) over 2024-07..2026-07 "
             "(package-exclusion-skew §1); this bucket's LEVEL moves for "
             "sampling reasons and it is the meeting-dated front end"),
}

#: 2024-06 is the ingest transition month: the DV01 exclusion rate steps
#: -3.2 pp across it (local +-60 trading days) and the tape carries **no**
#: termination events at all before it, so a lifecycle series backfilled
#: earlier is empty for a reason that is not the market.
SAMPLE_FLOOR = datetime.date(2024, 7, 1)

#: The published key. ``venue_class`` and ``series`` are keys, not columns to
#: sum over -- ``ladder`` says why, and dropping either merges two things that
#: must never be added.
INDICATOR_KEYS = ("bucket_space", "bucket_key", "visibility_date",
                  "venue_class", "series")

#: Trailing window for the own-history statistics, in **observations of that
#: cell**, not calendar days -- a bucket that prints once a fortnight must not
#: be standardised against four observations because the window was measured in
#: days.
Z_WINDOW_OBS = 250
Z_MIN_OBS = 60

#: Trailing window for the coverage smoother used by the adjusted basis.
COVERAGE_SMOOTH_OBS = 63

#: Months of coverage history below which the drift trend is not estimated and
#: :data:`PINNED_DRIFT_BUCKETS` is used instead. Twelve, because the measured
#: slope is ~5 pp/yr against a within-bucket monthly sd of ~4.7 pp: on six
#: months the slope is not identified.
MIN_MONTHS_FOR_DRIFT = 12

#: |t| above which a measured coverage trend is called a drift. The skew doc's
#: own rule, and the reason it treats 1-2Y (t = 3.21) differently from the nine
#: buckets that are not distinguishable from flat.
DRIFT_T_THRESHOLD = 2.0

#: A coverage move "matters" when the multiplicative distortion it puts on the
#: level exceeds this many standard deviations of the level's own variation.
COVERAGE_MOVE_SIGMA = 0.25

#: Minimum observations for the stationarity test. Below it the answer is
#: ``None``, not ``True`` -- a short series is not evidence of stationarity.
MIN_ADF_OBS = 60

#: Dickey-Fuller 5% critical value, constant and no trend, large sample.
ADF_CRITICAL_5PCT = -2.86

_LEVEL_BASES = {"raw": "delta_dv01", "cov_adj": "delta_dv01_cov_adj",
                "gross": "abs_dv01"}

_PROV_FRACS = ("frac_dv01_block", "frac_dv01_capped", "frac_dv01_dead_zone",
               "frac_dv01_visibility_measured")

LEVEL_COLUMNS = ["delta_dv01", "delta_dv01_cov_adj", "abs_dv01"]

CELL_COLUMNS = (list(INDICATOR_KEYS) + ["observed"] + LEVEL_COLUMNS
                + ["n_units", "mean_abs_signed_weight", "z_raw", "z_cov_adj",
                   "pct_raw", "z_n_obs", "coverage_frac", "coverage_smooth",
                   "coverage_drift_flag", "coverage_trend_pp_per_yr",
                   "coverage_drift_source"]
                + list(_PROV_FRACS) + ["code_vintage", "primary_level_basis"])


# --------------------------------------------------------------------------
# refusals
# --------------------------------------------------------------------------

class CrossSectionalLevelComparison(ValueError):
    """A level was asked for across buckets. Measured, not stylistic."""


class CumulationRefused(ValueError):
    """A running sum was asked for. The offsetting print does not exist."""


class SampleFloorViolation(ValueError):
    """The window reaches before the ingest break at :data:`SAMPLE_FLOOR`."""


class CoverageGap(ValueError):
    """A published cell has no coverage row, so it cannot be gated on."""


class UnknownPillar(ValueError):
    """A risk row sits on a pillar with no bucket, so its DV01 has nowhere to go."""


class MisStampedRow(ValueError):
    """``visibility_date`` disagrees with ``visibility_timestamp``."""


_CROSS_SECTION_MESSAGE = (
    "the LEVEL is not comparable across tenor buckets and this object will not "
    "assemble that comparison. DV01 retention was measured at 0.761 at 0-1Y "
    "against 0.495 at 15-20Y -- a 1.54x cross-bucket scaling distortion -- so "
    "'the 0-1Y level exceeds the 15-20Y level' is a statement about which "
    "buckets survive package exclusion, not about what dealers hold. "
    "(docs/dealer_direction/2026-08-11-package-exclusion-skew.md §1, §8.1)\n"
    "  * to read one bucket against its own history: .bucket(key, "
    "venue_class=..., series=...)\n"
    "  * to compare buckets at all: .standardised(), whose z-score cancels a "
    "CONSTANT retention factor exactly -- read its drift flags first, because "
    "1-2Y's retention is not constant\n"
    "  * to insist on levels: .rescale_for_cross_section(retention_factors), "
    "which makes you supply the factors and assumes the excluded flow has the "
    "same directional mix as the retained flow, which cannot be verified"
)

_CUMULATION_MESSAGE = (
    "this is a FLOW series and it will not accumulate itself. Compression and "
    "allocation are never publicly reported, so risk leaves a dealer's book "
    "with no offsetting print and a running sum carries an unbounded, monotone "
    "error -- it only ever grows and nothing in the data pushes back. If you "
    "want a stock, name the assumption: ladder.decayed_flow(ladder_frame, "
    "half_life_days=...) has no default half_life because choosing one is "
    "choosing a belief about how fast the unobserved offset arrives."
)


# --------------------------------------------------------------------------
# the bucket map
# --------------------------------------------------------------------------

def bucket_for_years(years: float) -> str:
    """The tenor bucket a maturity point falls in. Right edge inclusive."""
    y = float(years)
    if y < 0:
        raise ValueError(f"negative maturity {years!r}")
    for edge, name in _BUCKET_RIGHT_EDGE:
        if y <= edge:
            return name
    return "30Y+"


#: Pillar -> bucket, materialised so it can be inspected and pinned by test.
PILLAR_BUCKET = {p: bucket_for_years(krd._years(p)) for p in krd.PILLARS}


def level_column(bucket_key: str, basis: str = "raw") -> str:
    """The **bucket-suffixed** name the level is published under.

    This is the control, not a naming convention. Two buckets' frames share no
    level column, so ``pd.concat`` of them is a block-diagonal frame of NaNs
    and ``pivot(values="delta_dv01")`` has nothing to pivot -- the cross-bucket
    comparison stops being a one-liner and starts being a decision.
    """
    if basis not in _LEVEL_BASES:
        raise ValueError(f"unknown basis {basis!r}; one of {sorted(_LEVEL_BASES)}")
    if bucket_key not in TENOR_BUCKETS:
        raise ValueError(f"unknown bucket {bucket_key!r}")
    return f"{_LEVEL_BASES[basis]}__{_slug(bucket_key)}"


def _slug(bucket_key: str) -> str:
    return bucket_key.replace("-", "_").replace("+", "plus")


# --------------------------------------------------------------------------
# roll-up and aggregation
# --------------------------------------------------------------------------

_UNIT_CONSTANT = ("venue_class", "series", "visibility_date", "signed_weight")


def roll_up_to_tenor_buckets(unit_rows) -> pd.DataFrame:
    """Sum a unit's key-rate pillars into the ten reporting buckets.

    A linear change of basis on an already-linear object: the pillars of one
    unit add, including the negative ones a tent shift produces. Rows already
    on :data:`BUCKET_SPACE` pass through, so the function is idempotent.

    **The addition is signed, so a unit's own offsetting pillars inside one
    bucket net away here** -- a +40/-40 tent across 6Y and 7Y leaves one row at
    zero, not two rows at 40. That is the right answer for ``delta_dv01`` (the
    unit really carries no net 5-7Y risk), but it means the downstream
    ``abs_dv01`` is a sum of per-unit *net-within-bucket* magnitudes rather than
    of per-pillar magnitudes: two units offsetting each other still show their
    gross, one unit offsetting itself inside a bucket does not.
    """
    rows = pd.DataFrame(unit_rows)
    if rows.empty:
        return rows.reindex(columns=ladder.UNIT_ROW_COLUMNS)
    for col in ("unit_key", "bucket_space", "bucket_key", "dv01_if_received",
                "delta_dv01"):
        if col not in rows.columns:
            raise ValueError(f"unit rows need a {col!r} column; pass the first "
                             "frame ladder.unit_ladder_rows() returns")

    spaces = set(rows["bucket_space"].astype(str))
    unknown = spaces - {krd.BUCKET_SPACE, BUCKET_SPACE}
    if unknown:
        raise UnknownPillar(f"unknown bucket space(s) {sorted(unknown)}")

    work = rows.copy()
    is_pillar = work["bucket_space"].astype(str) == krd.BUCKET_SPACE
    if is_pillar.any():
        keys = work.loc[is_pillar, "bucket_key"].astype(str)
        missing = sorted(set(keys) - set(PILLAR_BUCKET))
        if missing:
            raise UnknownPillar(
                f"pillar(s) {missing} have no tenor bucket; the grid this "
                f"module rolls up is krd.PILLARS and a foreign pillar's DV01 "
                "would be dropped from every published cell")
        work.loc[is_pillar, "bucket_key"] = keys.map(PILLAR_BUCKET).to_numpy()
        work.loc[is_pillar, "bucket_space"] = BUCKET_SPACE

    _assert_unit_constant(work)

    keys = ["unit_key", "bucket_space", "bucket_key"]
    num = (work.groupby(keys, sort=False, dropna=False)
               [["dv01_if_received", "delta_dv01"]].sum())
    other = [c for c in work.columns if c not in keys + list(num.columns)]
    meta = work.groupby(keys, sort=False, dropna=False)[other].first()
    out = pd.concat([num, meta], axis=1).reset_index()
    return out.reindex(columns=[c for c in ladder.UNIT_ROW_COLUMNS
                                if c in out.columns])


def _assert_unit_constant(rows) -> None:
    """One unit is one print: its key columns cannot vary between its pillars.

    Rolling up takes ``.first()`` for the metadata, so a unit whose rows
    disagree about the venue or the date would silently publish under whichever
    row sorted first and lose the other -- a per-unit corruption that no output
    column shows.
    """
    present = [c for c in _UNIT_CONSTANT if c in rows.columns]
    if not present:
        return
    varying = rows.groupby("unit_key", sort=False)[present].nunique(dropna=False)
    bad = varying[(varying > 1).any(axis=1)]
    if len(bad):
        cols = [c for c in present if (bad[c] > 1).any()]
        raise ValueError(
            f"{len(bad)} unit(s) carry more than one value of {cols}, e.g. "
            f"{sorted(map(str, bad.index))[:5]}; a unit is one print and the "
            "roll-up takes its metadata from the first pillar row, so the "
            "others would be discarded without a trace")


def _assert_stamped_on_visibility(rows) -> None:
    if "visibility_timestamp" not in rows.columns:
        return
    recomputed = rows["visibility_timestamp"].map(
        lambda t: None if pd.isna(t) else ladder.visibility_date(t))
    have = rows["visibility_date"]
    bad = recomputed.notna() & (recomputed != have)
    if bad.any():
        ex = rows.loc[bad].head(3)
        detail = [
            f"{r.unit_key}: visibility_date={r.visibility_date} but "
            f"visibility_timestamp={r.visibility_timestamp} is "
            f"{ladder.visibility_date(r.visibility_timestamp)} in New York "
            f"(execution_timestamp={getattr(r, 'execution_timestamp', None)})"
            for r in ex.itertuples()
        ]
        raise MisStampedRow(
            f"{int(bad.sum())} row(s) are not stamped on the availability "
            f"clock: {detail}. Dating a print on its execution claims it was "
            "actionable before Part 43 published it, which is lookahead of "
            "exactly the length of the legal delay -- and it is invisible "
            "downstream because every other column is right.")


def _assert_weight_is_2p_minus_1(rows) -> None:
    if not {"p", "signed_weight", "dv01_if_received", "delta_dv01"} <= set(rows.columns):
        return
    p = rows["p"].astype("float64")
    w = rows["signed_weight"].astype("float64")
    expect_w = 2.0 * p - 1.0
    bad_w = (w - expect_w).abs() > 1e-9
    if bad_w.any():
        raise ValueError(
            f"{int(bad_w.sum())} row(s) carry signed_weight != 2p-1; the "
            "indicator aggregates 2p-1, and a p-weighted call puts half a "
            "position behind a coin flip")
    got = rows["delta_dv01"].astype("float64")
    want = w * rows["dv01_if_received"].astype("float64")
    scale = np.maximum(want.abs(), 1.0)
    bad = ((got - want).abs() / scale) > 1e-9
    if bad.any():
        raise ValueError(
            f"{int(bad.sum())} row(s) have delta_dv01 != signed_weight * "
            "dv01_if_received, i.e. the level was not formed with the 2p-1 "
            "weight. Weighting by p rather than 2p-1 makes a coin flip "
            "contribute half a long position, and nothing downstream looks "
            "wrong (conventions.signed_weight)")


def daily_levels(unit_rows) -> pd.DataFrame:
    """The signed daily level per published cell, and the gross pond behind it.

    ``abs_dv01`` travels with ``delta_dv01`` because a net of zero over a $40mm
    gross is a different statement about the day than a net of zero over
    nothing, and only the second one means the cell is empty.
    """
    rows = pd.DataFrame(unit_rows)
    if rows.empty:
        return pd.DataFrame(columns=list(INDICATOR_KEYS) + [
            "delta_dv01", "abs_dv01", "n_units", "mean_abs_signed_weight",
            *_PROV_FRACS, "code_vintage"])
    for col in ("visibility_date", "venue_class", "series"):
        if col not in rows.columns:
            raise ValueError(f"unit rows need a {col!r} column")

    _assert_stamped_on_visibility(rows)
    _assert_weight_is_2p_minus_1(rows)
    work = roll_up_to_tenor_buckets(rows)

    work["_gross"] = work["dv01_if_received"].abs()
    work["_abs_delta"] = work["delta_dv01"].abs()
    for flag, name in (("is_block", "frac_dv01_block"),
                       ("is_capped", "frac_dv01_capped"),
                       ("in_dead_zone", "frac_dv01_dead_zone")):
        work["_w_" + name] = (work["_gross"]
                              * (work[flag].fillna(False).astype(bool)
                                 if flag in work.columns else False))
    measured = (work["visibility_source"].astype(str).str.contains("MEASURED")
                if "visibility_source" in work.columns else False)
    work["_w_frac_dv01_visibility_measured"] = work["_gross"] * measured

    g = work.groupby(list(INDICATOR_KEYS), dropna=False, sort=True)
    out = g.agg(
        delta_dv01=("delta_dv01", "sum"),
        abs_dv01=("_gross", "sum"),
        n_units=("unit_key", "nunique"),
        _abs_delta=("_abs_delta", "sum"),
        **{"_" + n: ("_w_" + n, "sum") for n in _PROV_FRACS},
    ).reset_index()
    denom = out["abs_dv01"].where(out["abs_dv01"] != 0)
    out["mean_abs_signed_weight"] = out["_abs_delta"] / denom
    for n in _PROV_FRACS:
        out[n] = out["_" + n] / denom

    if "code_vintage" in work.columns:
        vint = g["code_vintage"].agg(lambda s: sorted(set(map(str, s.dropna()))))
        out["code_vintage"] = [v[0] if len(v) == 1 else f"MIXED:{len(v)}"
                               for v in vint.to_numpy()]
    else:
        out["code_vintage"] = None

    keep = list(INDICATOR_KEYS) + ["delta_dv01", "abs_dv01", "n_units",
                                   "mean_abs_signed_weight", *_PROV_FRACS,
                                   "code_vintage"]
    return out[keep]


# --------------------------------------------------------------------------
# coverage
# --------------------------------------------------------------------------

COVERAGE_COLUMNS = ("bucket_key", "visibility_date", "venue_class", "series",
                    "dv01_kept", "dv01_total")


def coverage_fraction(coverage) -> pd.DataFrame:
    """Validate a coverage frame and attach ``coverage_frac = kept / total``."""
    cov = pd.DataFrame(coverage)
    missing = [c for c in COVERAGE_COLUMNS if c not in cov.columns]
    if missing:
        raise ValueError(
            f"coverage frame is missing {missing}. It must carry BOTH the kept "
            "and the total gross DV01 per (bucket, day, venue, series): a "
            "ratio alone cannot be re-aggregated, and the denominator is the "
            "only thing that knows about the units that were excluded")
    cov = cov.copy()
    total = cov["dv01_total"].astype("float64")
    kept = cov["dv01_kept"].astype("float64")
    if (total <= 0).any():
        raise ValueError(f"{int((total <= 0).sum())} coverage row(s) have a "
                         "non-positive total DV01; a coverage fraction over no "
                         "size reports nothing")
    if (kept > total * (1 + 1e-9)).any():
        raise ValueError(
            f"{int((kept > total * (1 + 1e-9)).sum())} coverage row(s) keep "
            "more DV01 than the tape carried; the numerator and the "
            "denominator came from different populations or different "
            "allocations")
    cov["coverage_frac"] = kept / total
    dup = cov.duplicated(subset=["bucket_key", "visibility_date", "venue_class",
                                 "series"])
    if dup.any():
        raise ValueError(f"{int(dup.sum())} duplicated coverage key(s)")
    return cov


def coverage_drift_table(coverage) -> pd.DataFrame:
    """Per cell-series: is the exclusion rate holding still, or trending?

    Monthly, DV01-weighted, exactly as the skew document measured it -- daily
    coverage is far too noisy to see a 5 pp/yr slope, and a slope fitted on
    daily points would be dominated by the day-to-day composition of the tape.
    """
    cov = coverage_fraction(coverage)
    out = []
    keys = ["bucket_key", "venue_class", "series"]
    for key, block in cov.groupby(keys, dropna=False, sort=True):
        b = block.copy()
        b["_m"] = pd.to_datetime(pd.Series(list(b["visibility_date"]))).dt.to_period("M").to_numpy()
        monthly = b.groupby("_m", sort=True).agg(
            kept=("dv01_kept", "sum"), total=("dv01_total", "sum"))
        monthly = monthly[monthly["total"] > 0]
        frac = (monthly["kept"] / monthly["total"]).to_numpy() * 100.0
        n_months = len(frac)
        slope, tstat = _ols_trend(frac, n_months)
        bucket = key[0]
        pinned = bucket in PINNED_DRIFT_BUCKETS
        measured = n_months >= MIN_MONTHS_FOR_DRIFT
        flag = bool(pinned or (measured and abs(tstat) > DRIFT_T_THRESHOLD))
        out.append({
            "bucket_key": bucket, "venue_class": key[1], "series": key[2],
            "n_months": n_months,
            "coverage_mean": float(np.nanmean(frac) / 100.0) if n_months else np.nan,
            "coverage_trend_pp_per_yr": slope,
            "coverage_trend_t": tstat,
            "coverage_drift_flag": flag,
            "coverage_drift_source": "MEASURED" if measured else "PINNED",
            "coverage_drift_note": PINNED_DRIFT_BUCKETS.get(bucket, ""),
        })
    return pd.DataFrame(out, columns=[
        "bucket_key", "venue_class", "series", "n_months", "coverage_mean",
        "coverage_trend_pp_per_yr", "coverage_trend_t", "coverage_drift_flag",
        "coverage_drift_source", "coverage_drift_note"])


def _ols_trend(y, n_months: int) -> tuple:
    """Slope per **year** and its t-stat, from monthly points. ``(nan, 0)`` if flat."""
    if n_months < 3:
        return (np.nan, 0.0)
    y = np.asarray(y, dtype="float64")
    x = np.arange(n_months, dtype="float64") / 12.0
    xc = x - x.mean()
    sxx = float((xc ** 2).sum())
    if sxx <= 0:
        return (np.nan, 0.0)
    slope = float((xc * (y - y.mean())).sum() / sxx)
    resid = y - (y.mean() + slope * xc)
    dof = n_months - 2
    sse = float((resid ** 2).sum())
    if dof <= 0 or sse <= 0:
        return (slope, 0.0)
    se = float(np.sqrt(sse / dof / sxx))
    return (slope, slope / se if se > 0 else 0.0)


# --------------------------------------------------------------------------
# the builder
# --------------------------------------------------------------------------

def build(unit_rows, *, coverage, session_dates=None,
          z_window_obs: int = Z_WINDOW_OBS, z_min_obs: int = Z_MIN_OBS,
          coverage_smooth_obs: int = COVERAGE_SMOOTH_OBS,
          allow_pre_floor: bool = False) -> "DailyPositioning":
    """The daily indicator from the ladder's per-unit rows.

    ``coverage`` is **required with no default**. A cell with no coverage is a
    cell a consumer cannot gate on, and defaulting it to 1.0 would report full
    coverage on a population that carries 57% of the tape's DV01 -- the
    self-flattering failure, and the one a reader would believe.

    ``session_dates`` reindexes each cell onto a calendar and fills the absent
    days with **zero flow and ``observed = False``**. Without it, a gap is a
    missing row and any autocorrelation computed over the rows treats a
    fortnight-old print as yesterday's.
    """
    levels = daily_levels(unit_rows)
    if levels.empty:
        raise ValueError("no unit rows reached the indicator; an empty ladder "
                         "is a run to investigate, not a series to publish")

    first = min(levels["visibility_date"])
    if not allow_pre_floor and first < SAMPLE_FLOOR:
        raise SampleFloorViolation(
            f"the window starts {first}, before the {SAMPLE_FLOOR} ingest "
            "break: the DV01 exclusion rate steps -3.2 pp across it and the "
            "tape carries no termination events at all before it, so a "
            "LIFECYCLE series is empty there for a reason that is not the "
            "market. Pass allow_pre_floor=True to publish it anyway")

    cov = coverage_fraction(coverage)
    drift = coverage_drift_table(cov)

    on = ["bucket_key", "visibility_date", "venue_class", "series"]
    # renamed on the way in, deliberately: these are a MATURITY-POINT
    # allocation of gross tape DV01 and ``abs_dv01`` is a KEY-RATE allocation of
    # retained risk. Left as `dv01_kept`/`dv01_total` they sit one column away
    # from `abs_dv01` and read as the same quantity on the same grid, which is
    # the silent lie the module docstring is about.
    merged = levels.merge(
        cov[on + ["coverage_frac", "dv01_kept", "dv01_total"]], on=on, how="left"
    ).rename(columns={"dv01_kept": "coverage_dv01_kept",
                      "dv01_total": "coverage_dv01_total"})
    gaps = merged["coverage_frac"].isna()
    if gaps.any():
        ex = merged.loc[gaps, on].head(5).to_dict("records")
        raise CoverageGap(
            f"{int(gaps.sum())} published cell(s) have no coverage row, e.g. "
            f"{ex}. A cell with unknown coverage cannot be gated on, and a "
            "missing coverage row is usually the denominator being built over "
            "a different population than the level")

    frame = _reindex_to_calendar(merged, session_dates)
    frame = _own_history(frame, z_window_obs=z_window_obs, z_min_obs=z_min_obs,
                         coverage_smooth_obs=coverage_smooth_obs)
    frame = frame.merge(
        drift[["bucket_key", "venue_class", "series", "coverage_drift_flag",
               "coverage_trend_pp_per_yr", "coverage_drift_source"]],
        on=["bucket_key", "venue_class", "series"], how="left")
    frame["primary_level_basis"] = "RAW"
    frame = frame.reindex(columns=[c for c in CELL_COLUMNS if c in frame.columns]
                          + [c for c in frame.columns if c not in CELL_COLUMNS])
    return DailyPositioning(
        _cells=frame.reset_index(drop=True), drift=drift,
        params={"z_window_obs": z_window_obs, "z_min_obs": z_min_obs,
                "coverage_smooth_obs": coverage_smooth_obs,
                "sample_floor": SAMPLE_FLOOR,
                "allow_pre_floor": bool(allow_pre_floor)})


def _group_keys() -> list:
    return ["bucket_space", "bucket_key", "venue_class", "series"]


def _reindex_to_calendar(frame, session_dates) -> pd.DataFrame:
    frame = frame.sort_values(_group_keys() + ["visibility_date"]).copy()
    frame["observed"] = True
    if session_dates is None:
        return frame
    cal = sorted({pd.Timestamp(d).date() for d in session_dates})
    blocks = []
    for key, block in frame.groupby(_group_keys(), dropna=False, sort=True):
        b = block.set_index("visibility_date").reindex(cal)
        b.index.name = "visibility_date"
        b = b.reset_index()
        for col, val in zip(_group_keys(), key):
            b[col] = val
        for col, val in (("delta_dv01", 0.0), ("abs_dv01", 0.0), ("n_units", 0)):
            b[col] = b[col].fillna(val)
        b["observed"] = b["observed"].isin([True]).astype(bool)
        blocks.append(b)
    return pd.concat(blocks, ignore_index=True)


def _own_history(frame, *, z_window_obs, z_min_obs, coverage_smooth_obs) -> pd.DataFrame:
    """Trailing z, trailing percentile, and the coverage-adjusted level.

    Trailing, never full-sample: a published z that used tomorrow's mean would
    be a backtest artefact, and the whole point of a daily indicator is that it
    exists on the day.
    """
    out = []
    for _, block in frame.groupby(_group_keys(), dropna=False, sort=True):
        b = block.sort_values("visibility_date").copy()
        lvl = b["delta_dv01"].astype("float64")
        roll = lvl.rolling(z_window_obs, min_periods=z_min_obs)
        sd = roll.std(ddof=1)
        b["z_raw"] = (lvl - roll.mean()) / sd.where(sd > 0)
        b["z_n_obs"] = lvl.rolling(z_window_obs, min_periods=1).count()
        b["pct_raw"] = lvl.rolling(z_window_obs, min_periods=z_min_obs).apply(
            _trailing_percentile, raw=True)

        cf = b["coverage_frac"].astype("float64")
        smooth = cf.rolling(coverage_smooth_obs,
                            min_periods=coverage_smooth_obs).mean()
        b["coverage_smooth"] = smooth
        ref = float(cf.mean()) if cf.notna().any() else np.nan
        b["delta_dv01_cov_adj"] = lvl * ref / smooth.where(smooth > 0)
        adj = b["delta_dv01_cov_adj"]
        aroll = adj.rolling(z_window_obs, min_periods=z_min_obs)
        asd = aroll.std(ddof=1)
        b["z_cov_adj"] = (adj - aroll.mean()) / asd.where(asd > 0)
        out.append(b)
    return pd.concat(out, ignore_index=True)


def _trailing_percentile(window) -> float:
    """Where the current observation sits in its own trailing window, 0..1."""
    if len(window) < 2:
        return np.nan
    prior = window[:-1]
    return float((prior < window[-1]).mean())


# --------------------------------------------------------------------------
# the object
# --------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class DailyPositioning:
    """The published indicator. Read one bucket against its own history.

    There is deliberately **no accessor that returns every bucket's level in
    one column**. :meth:`bucket` is the level path and it names the column for
    its bucket; :meth:`standardised` is the all-bucket path and it carries no
    level at all. See the module docstring for why those are different
    statements about the same data.
    """

    _cells: pd.DataFrame
    drift: pd.DataFrame
    params: dict

    # -- the within-bucket path ------------------------------------------
    @property
    def buckets(self) -> tuple:
        present = set(self._cells["bucket_key"])
        return tuple(b for b in TENOR_BUCKETS if b in present)

    @property
    def keys(self) -> pd.DataFrame:
        """The (bucket, venue, series) cells present, and how long each is."""
        g = self._cells.groupby(["bucket_key", "venue_class", "series"],
                                dropna=False, sort=True)
        return g.agg(n_days=("visibility_date", "nunique"),
                     first_day=("visibility_date", "min"),
                     last_day=("visibility_date", "max")).reset_index()

    def bucket(self, bucket_key: str, *, venue_class: str,
               series: str = ladder.SERIES_FLOW) -> pd.DataFrame:
        """One cell-series, with its level under a bucket-suffixed name.

        ``venue_class`` is keyword-only and has **no default**: a default would
        mean the object had an opinion about which venue class is "the" series,
        and D2C, D2D and VENUE_UNKNOWN are three answers to three different
        questions.
        """
        if bucket_key not in TENOR_BUCKETS:
            raise ValueError(f"unknown bucket {bucket_key!r}; one of {TENOR_BUCKETS}")
        if venue_class not in (T.VENUE_D2C, T.VENUE_D2D, T.VENUE_UNKNOWN):
            raise ValueError(f"unknown venue class {venue_class!r}")
        sel = self._cells[(self._cells["bucket_key"] == bucket_key)
                          & (self._cells["venue_class"] == venue_class)
                          & (self._cells["series"] == series)]
        if sel.empty:
            raise KeyError(f"no rows for ({bucket_key}, {venue_class}, {series})")
        out = sel.sort_values("visibility_date").reset_index(drop=True).rename(
            columns={base: level_column(bucket_key, basis)
                     for basis, base in _LEVEL_BASES.items()})
        return out

    def all_bucket_frames(self) -> dict:
        """Every cell-series as its own frame, keyed by ``(bucket, venue, series)``.

        The iteration path, and the persistence path. Concatenating these gives
        a **block-diagonal** frame -- one level column per bucket, NaN
        elsewhere -- which is the storage form this module intends: it round
        trips, and it cannot be pivoted back into a cross-sectional level
        comparison.
        """
        return {tuple(k): self.bucket(k[0], venue_class=k[1], series=k[2])
                for k in self.keys[["bucket_key", "venue_class",
                                    "series"]].to_numpy()}

    # -- the cross-bucket path, which carries no level --------------------
    def standardised(self) -> pd.DataFrame:
        """Every cell, as z / percentile against its **own** history.

        This is the one frame in which buckets may be compared, and the reason
        is arithmetic rather than editorial: for an observed level ``r_b * L``,
        ``z = (r_b*L - r_b*mu)/(r_b*sigma) = (L - mu)/sigma``, so a constant
        retention factor cancels exactly and the 1.54x cross-bucket distortion
        with it.

        **Read the drift columns before using it that way.** The cancellation
        needs ``r_b`` constant in time. ``coverage_drift_flag`` marks the cells
        where it was measured not to be -- 1-2Y above all, at +5.07 pp/yr
        (t = +3.21) -- and there the z-score inherits a trend that is
        measurement, not positioning.

        No level column, by construction: ``z`` is comparable and ``delta_dv01``
        is not, and putting them in one frame would invite exactly the read the
        object refuses elsewhere.
        """
        drop = set(LEVEL_COLUMNS)
        cols = [c for c in self._cells.columns if c not in drop]
        return self._cells[cols].copy()

    def properties(self) -> pd.DataFrame:
        """The series' own properties, per cell. See INDICATOR.md for the read.

        A positioning indicator whose level drifts for measurement reasons is
        worse than no indicator, so the three questions asked here are: how
        persistent is it (``ac1``, ``ac5``), does its level hold still
        (``level_stationary``), and does the coverage behind it move enough to
        matter (``n_coverage_moves_that_matter``).
        """
        rows = []
        for key, block in self._cells.groupby(
                ["bucket_key", "venue_class", "series"], dropna=False, sort=True):
            b = block.sort_values("visibility_date")
            lvl = b["delta_dv01"].astype("float64").to_numpy()
            cf = b["coverage_frac"].astype("float64").to_numpy()
            adf_stat, stationary = _adf(lvl)
            n_move, p95_move = _coverage_moves(cf, lvl)
            rows.append({
                "bucket_key": key[0], "venue_class": key[1], "series": key[2],
                "n_obs": int(len(lvl)),
                "frac_observed": float(np.mean(b["observed"].to_numpy())),
                "mean_level": float(np.nanmean(lvl)),
                "sd_level": float(np.nanstd(lvl, ddof=1)) if len(lvl) > 1 else np.nan,
                "ac1": _autocorr(lvl, 1), "ac5": _autocorr(lvl, 5),
                "adf_stat": adf_stat, "level_stationary": stationary,
                "coverage_mean": float(np.nanmean(cf)) if np.isfinite(cf).any() else np.nan,
                "coverage_sd": float(np.nanstd(cf, ddof=1)) if len(cf) > 1 else np.nan,
                "p95_abs_rel_coverage_move": p95_move,
                "n_coverage_moves_that_matter": n_move,
            })
        out = pd.DataFrame(rows)
        return out.merge(self.drift[["bucket_key", "venue_class", "series",
                                     "coverage_trend_pp_per_yr",
                                     "coverage_trend_t", "coverage_drift_flag",
                                     "coverage_drift_source"]],
                         on=["bucket_key", "venue_class", "series"], how="left")

    # -- the refusals ------------------------------------------------------
    def cross_section(self, date=None):
        """Refuses. One day's levels across buckets is the forbidden read."""
        raise CrossSectionalLevelComparison(_CROSS_SECTION_MESSAGE)

    def pivot_levels(self, *args, **kwargs):
        """Refuses, for the same measured reason as :meth:`cross_section`."""
        raise CrossSectionalLevelComparison(_CROSS_SECTION_MESSAGE)

    def cumulate(self, *args, **kwargs):
        """Refuses. The offsetting compression print does not exist."""
        raise CumulationRefused(_CUMULATION_MESSAGE)

    cumsum = cumulate
    position = cumulate
    inventory = cumulate

    def rescale_for_cross_section(self, retention_factors) -> pd.DataFrame:
        """Levels divided by **caller-supplied** retention factors.

        The escape hatch, and the friction is the point: the factors are not
        defaulted from :data:`MEASURED_RETENTION_FACTORS` because dividing by
        them assumes the excluded flow in a bucket has the **same directional
        mix** as the retained flow -- and per the skew document §8.1 that is
        precisely the thing that cannot be verified, since the excluded units
        are excluded exactly because their direction cannot be read. What is
        being rescaled is a *gross* DV01 share.

        The output column is named for the assumption so it cannot be quoted
        without it.
        """
        factors = dict(retention_factors)
        missing = [b for b in self.buckets if b not in factors]
        if missing:
            raise ValueError(
                f"no retention factor supplied for {missing}; every published "
                "bucket needs one or the rescaled frame is a comparison "
                "between rescaled and un-rescaled buckets, which is worse than "
                "the distortion it set out to remove. The measured values are "
                f"in MEASURED_RETENTION_FACTORS and in the skew document §1")
        bad = {b: f for b, f in factors.items() if not 0.0 < float(f) <= 1.0}
        if bad:
            raise ValueError(f"retention factors must be in (0, 1], got {bad}")
        out = self._cells.copy()
        out["tape_scaled_dv01_ASSUMES_SAME_DIRECTIONAL_MIX"] = (
            out["delta_dv01"].astype("float64")
            / out["bucket_key"].map(factors).astype("float64"))
        out["retention_factor_used"] = out["bucket_key"].map(factors)
        drop = [c for c in LEVEL_COLUMNS if c in out.columns]
        return (out.drop(columns=drop)
                   .sort_values(_group_keys() + ["visibility_date"])
                   .reset_index(drop=True))


# --------------------------------------------------------------------------
# the property meters
# --------------------------------------------------------------------------

def _autocorr(x, lag: int) -> float:
    x = np.asarray(x, dtype="float64")
    x = x[np.isfinite(x)]
    if len(x) <= lag + 2:
        return np.nan
    a, b = x[:-lag], x[lag:]
    xa, xb = a - a.mean(), b - b.mean()
    den = np.sqrt((xa ** 2).sum() * (xb ** 2).sum())
    return float((xa * xb).sum() / den) if den > 0 else np.nan


def _adf(x) -> tuple:
    """Augmented Dickey-Fuller with a constant: ``(t_rho, stationary_or_None)``.

    Written out rather than imported so the module carries no statistics
    dependency, and cross-checked against ``statsmodels.tsa.stattools.adfuller``
    on white noise, an AR(1) and a random walk in ``scratch/ddind_adf_check.py``
    -- a stationarity meter that is itself wrong reports a drifting level as
    stable, which is the failure this whole column exists to catch.
    """
    x = np.asarray(x, dtype="float64")
    x = x[np.isfinite(x)]
    n = len(x)
    if n < MIN_ADF_OBS:
        return (np.nan, None)
    # STANDARDISE FIRST. t_rho is exactly invariant to an affine rescaling of
    # the series -- rho's numerator and its standard error scale together, and
    # the intercept absorbs the shift -- but the *design matrix* is not: a
    # column of ones beside a column of 1e7 DV01s has a condition number around
    # 1e12, and the normal-equations inverse then returns a standard error that
    # is wrong by orders of magnitude. Measured on the real 610-day gross
    # series this returned -20.98 where the correct answer is -4.23, and on a
    # 1e7-scaled white noise -1086.7 against -4.96: a very confident,
    # arithmetic-generated "stationary". The unit-scale statsmodels cross-check
    # could not see it.
    sd = float(np.std(x, ddof=1))
    if not sd > 0:
        return (np.nan, None)
    x = (x - float(np.mean(x))) / sd
    lags = int(min(25, max(1, np.ceil(12.0 * (n / 100.0) ** 0.25))))
    dx = np.diff(x)
    if len(dx) <= lags + 3:
        return (np.nan, None)
    y = dx[lags:]
    cols = [np.ones(len(y)), x[lags:-1]]
    for i in range(1, lags + 1):
        cols.append(dx[lags - i:-i])
    X = np.column_stack(cols)
    if np.linalg.matrix_rank(X) < X.shape[1]:
        return (np.nan, None)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    dof = len(y) - X.shape[1]
    if dof <= 0:
        return (np.nan, None)
    s2 = float(resid @ resid) / dof
    xtx_inv = np.linalg.pinv(X.T @ X)
    se = float(np.sqrt(s2 * xtx_inv[1, 1]))
    if not se > 0:
        return (np.nan, None)
    t = float(beta[1] / se)
    return (t, bool(t < ADF_CRITICAL_5PCT))


def _coverage_moves(coverage_frac, level) -> tuple:
    """How often coverage moved enough to matter, against the level's own noise.

    A day-over-day coverage change of ``dc`` puts a multiplicative distortion of
    ``|dc| / c`` on the level. It "matters" when that distortion, applied to the
    level's own typical size, exceeds :data:`COVERAGE_MOVE_SIGMA` standard
    deviations of the level -- i.e. when the measurement moves the number by an
    appreciable fraction of what the market moves it by. An absolute
    percentage-point threshold cannot do this: 2 pp on a bucket whose level
    swings 3x day to day is nothing, and on a quiet bucket it is the signal.
    """
    c = np.asarray(coverage_frac, dtype="float64")
    lvl = np.asarray(level, dtype="float64")
    ok = np.isfinite(lvl)
    if ok.sum() < 3:
        return (0, np.nan)
    sd = float(np.nanstd(lvl[ok], ddof=1))
    rms = float(np.sqrt(np.nanmean(lvl[ok] ** 2)))
    rel = np.abs(np.diff(c)) / np.where(np.isfinite(c[:-1]) & (c[:-1] > 0),
                                        c[:-1], np.nan)
    rel = rel[np.isfinite(rel)]
    if rel.size == 0 or not sd > 0:
        return (0, np.nan)
    return (int((rel * rms > COVERAGE_MOVE_SIGMA * sd).sum()),
            float(np.percentile(rel, 95)))


__all__ = [
    "ADF_CRITICAL_5PCT", "BUCKET_SPACE", "CELL_COLUMNS", "COVERAGE_COLUMNS",
    "COVERAGE_MOVE_SIGMA", "COVERAGE_SMOOTH_OBS", "CoverageGap",
    "CrossSectionalLevelComparison", "CumulationRefused", "DRIFT_T_THRESHOLD",
    "DailyPositioning", "INDICATOR_KEYS", "LEVEL_COLUMNS",
    "MEASURED_RETENTION_FACTORS", "MIN_ADF_OBS", "MIN_MONTHS_FOR_DRIFT",
    "MisStampedRow", "PILLAR_BUCKET", "PINNED_DRIFT_BUCKETS",
    "SAMPLE_FLOOR", "SampleFloorViolation", "TENOR_BUCKETS", "UnknownPillar",
    "Z_MIN_OBS", "Z_WINDOW_OBS", "bucket_for_years", "build",
    "coverage_drift_table", "coverage_fraction", "daily_levels",
    "level_column", "roll_up_to_tenor_buckets",
]

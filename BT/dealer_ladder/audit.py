"""G1 — arrival integrity, verified by differential audit rather than assertion.

An assertion inside a feature builder proves only that the builder believes it is
not looking ahead. This module proves it from the outside, by changing data the
builder is not allowed to see and checking that its output does not move.

Three audits, weakest to strongest:

``audit_visibility_delays``
    Every persisted ``visibility_timestamp`` equals ``execution_timestamp`` plus
    the legal delay of its own Part 43 Appendix C class. Catches a stamp written
    by a stale convention -- e.g. rows carrying the pre-audit +1min/+15min
    two-bucket rule mixed in with Appendix C rows.

``audit_future_poison``
    THE load-bearing one. For each decision timestamp ``t``, take every print
    that is not yet visible at ``t``, multiply its ``delta_dv01`` by a huge
    factor and flip its sign, then rebuild the feature. If the value at ``t``
    changes at all, the builder read a print it could not have known -- and the
    magnitude tells you how much. This catches leakage no `<=` review can:
    an off-by-one on a merge key, a resampling boundary, a groupby that spans
    the decision instant, a z-score whose moments were computed on the full
    sample.

``audit_trailing_moments``
    Standardisation is the classic leak: a z-score against full-sample moments
    embeds the future in every observation. Poisons the tail of the panel and
    checks that early standardised values are unchanged.

All three return a verdict dict rather than raising, so a study can report
"G1: PASS" with numbers attached, and so a deliberately leaky builder can be used
in tests to prove the audits actually fire.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from SDRUtils.stir_flow import ladder_conventions as conv

POISON_FACTOR = -1.0e6


def _verdict(name, ok, **detail):
    return {"audit": name, "pass": bool(ok), **detail}


# --------------------------------------------------------------------------
# 1. the persisted stamps themselves
# --------------------------------------------------------------------------
def audit_visibility_delays(prints: pd.DataFrame) -> dict:
    """Each visibility_timestamp == execution_timestamp + its class's legal delay.

    ``prints`` needs ``execution_timestamp``, ``visibility_timestamp`` and enough
    of ``is_block``/``cleared``/``on_facility``/``is_capped`` to reclassify. When
    the classifying columns are absent (the ladder table stores only
    ``is_block``), the audit falls back to the weaker but still useful check that
    the realised delay is one of the enumerated legal delays and is never
    shorter than the minimum.
    """
    if prints.empty:
        return _verdict("visibility_delays", True, n=0, note="empty")
    delay_min = ((pd.to_datetime(prints["visibility_timestamp"])
                  - pd.to_datetime(prints["execution_timestamp"]))
                 .dt.total_seconds() / 60.0)
    legal = set(conv.VISIBILITY_DELAYS_MIN.values())
    shortest = min(legal)

    have_classifiers = {"cleared", "on_facility", "is_capped"} <= set(prints.columns)
    if have_classifiers:
        expected = [
            conv.VISIBILITY_DELAYS_MIN[conv.visibility_class(
                is_block=(r.is_block if r.is_block in (True, False) else False),
                cleared=r.cleared, on_facility=r.on_facility,
                is_capped=(r.is_capped if r.is_capped in (True, False) else False))]
            for r in prints.itertuples()
        ]
        bad = delay_min.to_numpy() != np.asarray(expected, dtype=float)
        return _verdict("visibility_delays", not bad.any(), n=int(len(prints)),
                        n_mismatched=int(bad.sum()), mode="exact-class",
                        observed_delays=sorted(set(delay_min.round(6))))
    observed = sorted(set(delay_min.round(6)))
    illegal = [d for d in observed if d not in legal]
    too_short = int((delay_min < shortest).sum())
    return _verdict("visibility_delays", not illegal and not too_short,
                    n=int(len(prints)), mode="delay-set-only",
                    observed_delays=observed, illegal_delays=illegal,
                    n_shorter_than_minimum=too_short)


# --------------------------------------------------------------------------
# 2. future poison — the real test
# --------------------------------------------------------------------------
def poison_not_yet_visible(prints: pd.DataFrame, ts, factor=POISON_FACTOR) -> pd.DataFrame:
    """Copy of ``prints`` with every not-yet-visible row's delta_dv01 corrupted.

    Rows visible at ``ts`` are untouched, so any builder that respects visibility
    produces an identical value; the corruption is huge and sign-flipped so that
    even a tiny weight on a future print shows up far outside float noise.
    """
    out = prints.copy()
    future = pd.to_datetime(out["visibility_timestamp"]) > pd.Timestamp(ts)
    out.loc[future, "delta_dv01"] = out.loc[future, "delta_dv01"].astype(float) * factor
    return out


def audit_future_poison(prints: pd.DataFrame, build_fn, grid, *, atol=1e-9) -> dict:
    """``build_fn(prints, ts) -> Series|float`` must be invariant to future poison.

    Returns the per-timestamp maximum absolute deviation and the count of
    timestamps that moved. ``n_future`` reports how many prints were actually
    poisoned at each step -- a grid whose every point sits after the last print
    would poison nothing and pass vacuously, so that number has to be looked at.
    """
    leaks, checked, poisoned_counts = [], 0, []
    for ts in grid:
        base = build_fn(prints, ts)
        n_future = int((pd.to_datetime(prints["visibility_timestamp"])
                        > pd.Timestamp(ts)).sum())
        poisoned_counts.append(n_future)
        alt = build_fn(poison_not_yet_visible(prints, ts), ts)
        dev = _max_abs_dev(base, alt)
        checked += 1
        if dev > atol:
            leaks.append({"ts": pd.Timestamp(ts), "max_abs_dev": float(dev),
                          "n_future_prints": n_future})
    return _verdict("future_poison", not leaks, n_timestamps=checked,
                    n_leaking=len(leaks),
                    min_future_prints=int(min(poisoned_counts)) if poisoned_counts else 0,
                    max_future_prints=int(max(poisoned_counts)) if poisoned_counts else 0,
                    leaks=leaks[:20])


def _max_abs_dev(a, b) -> float:
    """Max |a - b| over aligned Series, or scalars, treating missing as 0."""
    if isinstance(a, pd.Series) or isinstance(b, pd.Series):
        sa = a if isinstance(a, pd.Series) else pd.Series(dtype=float)
        sb = b if isinstance(b, pd.Series) else pd.Series(dtype=float)
        idx = sa.index.union(sb.index)
        diff = (sa.reindex(idx).fillna(0.0).astype(float)
                - sb.reindex(idx).fillna(0.0).astype(float)).abs()
        return float(diff.max()) if len(diff) else 0.0
    if a is None and b is None:
        return 0.0
    return abs(float(a or 0.0) - float(b or 0.0))


# --------------------------------------------------------------------------
# 3. standardisation moments
# --------------------------------------------------------------------------
def audit_trailing_moments(panel: pd.DataFrame, standardise_fn, *, split=0.5,
                           atol=1e-9) -> dict:
    """A z-score must not move when only LATER rows of the panel change.

    ``panel`` is time-indexed; ``standardise_fn(panel) -> DataFrame`` aligned to
    it. The tail after ``split`` is corrupted and the head is compared. Full-sample
    mean/std standardisation fails this immediately, which is the point: that leak
    is invisible in a code review because nothing in it references a future
    timestamp.
    """
    if len(panel) < 4:
        return _verdict("trailing_moments", True, n=len(panel), note="panel too short")
    cut = int(len(panel) * split)
    base = standardise_fn(panel)
    tainted = panel.copy()
    numeric = tainted.select_dtypes(include=[np.number]).columns
    tainted.iloc[cut:, tainted.columns.get_indexer(numeric)] *= POISON_FACTOR
    alt = standardise_fn(tainted)
    head_dev = (base.iloc[:cut][numeric].fillna(0.0)
                - alt.iloc[:cut][numeric].fillna(0.0)).abs().to_numpy()
    worst = float(np.nanmax(head_dev)) if head_dev.size else 0.0
    return _verdict("trailing_moments", worst <= atol, n=len(panel),
                    split_at=cut, max_abs_dev_in_head=worst)


# --------------------------------------------------------------------------
def run_g1_battery(prints, build_fn, grid, panel=None, standardise_fn=None) -> list:
    """Every G1 audit, as a list of verdicts ready to render into the findings doc."""
    out = [audit_visibility_delays(prints),
           audit_future_poison(prints, build_fn, grid)]
    if panel is not None and standardise_fn is not None:
        out.append(audit_trailing_moments(panel, standardise_fn))
    return out

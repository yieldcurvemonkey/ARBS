"""Sanity predicates for stored curve snapshots.

One place that answers "is this stored curve believable?", shared by three
callers so they cannot drift apart:

* the write gate in ``MDP/IRSwaps/BARCHART_STIRF/rl.py`` (reject before persisting),
* the read filter in ``Caching/curve_store.py`` (quarantine history already written),
* ``scripts/audit_curve_store_health.py`` (report).

Every predicate below was measured on ``USD-OIS-Q12xM12STIRT-SERFFX-MIX23`` over
2026-05-07..2026-08-07 -- 64 trading dates, 83,200 stored minutes -- and each
one is kept only because it separates known-bad rows from known-good ones on
that sample. Two candidate predicates were dropped for failing exactly that
test; they are documented at the bottom so nobody re-adds them.

``degenerate_identity``
    Trading date 2026-07-01 was stored with **every discount factor exactly
    1.0** for all 1,381 minutes -- rateslib's pre-solve state -- so every
    forward priced 0. ``_calibrate_chunk`` warm-starts each minute from the
    previous minute's nodes, so a single unsolved curve poisons the rest of the
    chunk. Nothing rejected it and the warm reported success.

``off_modal_shape``
    On 2026-07-21 the curve alternated minute-to-minute between a 21-node build
    (SR3 IMM tail 2028-03-15..2029-06-20) and a 16-node build carrying only the
    generic 2Y/3Y spline boundary nodes. The Sep-26 FOMC forward read
    3.8009% / 4.1056% / 3.8000% at 08:59 / 09:00 / 09:01, and discount factors
    differed at *every* shared front node -- the whole solve moved, not just the
    extrapolated tail. 93 minutes that day; 17 more on 07-15.

``anchor_block_jump``
    2026-07-30's first 450 minutes (18:00-01:59 ET, anchored a calendar day
    early) sit 78bp away from the rest of their own session on a 1Y reference
    rate: Sep-26 reads 3.7719% at the prior close, 3.6081% through the evening,
    then 3.7854% from 02:00 -- a round trip with nothing in between. Across all
    64 days the same statistic is 1.45bp median, 8.0bp at the worst clean day,
    so the 15bp threshold flags 2026-07-30 and nothing else.

Reported but NOT quarantined:

``negative_forward``
    2026-05-29 has 34 minutes whose discount factors rise between the 2Y and 3Y
    mixed-spline boundary nodes (implied forward -0.2512%). Real spline
    overshoot, but mild, confined to the extrapolated region, and a modelling
    call rather than corruption.

``anchor_mismatch``
    The builder anchors on ``timestamp.date()``, so the 18:00-23:59 ET Globex
    block carries the previous calendar day while the store partitions those
    rows under the next trading date. Present on ~420 rows of essentially every
    session. Reported for visibility only -- see below for why it is not a
    defect.

Two predicates that were tried and rejected:

``anchor_on_cb_date`` (rejected)
    The hypothesis was that anchoring on a just-passed FOMC effective date
    corrupts the front stub, which would have explained 2026-07-30. It does
    not. 2026-06-18's evening block anchors on 2026-06-17 -- the June FOMC
    effective date -- with a complete 20-node roster, and reads 3.8364% /
    3.8373% / 3.8213% through the evening against 3.8341% after the anchor
    rolls. Continuous. The anchor was innocent; 07-30's evening was a roster
    problem wearing the anchor's clothes, and is caught by
    ``anchor_block_jump`` instead.

Rolling-median outlier detection (audit only)
    Catches the 07-21/07-15 spikes, but by construction cannot see a sustained
    displacement like 07-30's 450-minute block, and risks flagging genuine
    policy repricing. It lives in the audit script where a human reads it.

Shape comparison normalises away the reference date twice over. A snapshot's
*shape signature* excludes node[0] and every spline boundary node, which sit at
exactly ref+2Y / ref+3Y and therefore move with the anchor; and shapes are
compared only within the same ``(trading date, anchor)`` group, because
crossing a calendar day legitimately rolls one IMM or FOMC node in or out.
Skipping either normalisation flagged the whole evening block of four clean
sessions -- 420 rows each, all false.
"""

from __future__ import annotations

import datetime
import logging
import math
import os
from typing import Any, Iterable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── defect codes ──
DEGENERATE_IDENTITY = "degenerate_identity"
NON_FINITE_DF = "non_finite_df"
NON_POSITIVE_DF = "non_positive_df"
EMPTY_NODES = "empty_nodes"
NEGATIVE_FORWARD = "negative_forward"
ANCHOR_MISMATCH = "anchor_mismatch"
OFF_MODAL_SHAPE = "off_modal_shape"
ANCHOR_BLOCK_JUMP = "anchor_block_jump"

#: Rejected before a snapshot is persisted. Only predicates that no legitimate
#: market can trip -- a curve that is structurally impossible, not merely odd.
#: ``anchor_mismatch`` is deliberately absent: the current builder produces it
#: on every evening row by design, and it is not a defect (see module docstring).
WRITE_REJECT_CODES: frozenset[str] = frozenset(
    {EMPTY_NODES, DEGENERATE_IDENTITY, NON_FINITE_DF, NON_POSITIVE_DF}
)

#: Quarantined on read. Adds the two session-relative predicates, which need
#: neighbouring rows and so cannot run at write time.
READ_DROP_CODES: frozenset[str] = frozenset(
    {EMPTY_NODES, DEGENERATE_IDENTITY, NON_FINITE_DF, NON_POSITIVE_DF, OFF_MODAL_SHAPE, ANCHOR_BLOCK_JUMP}
)

_IDENTITY_TOL = 1e-12
_DEFAULT_MIN_FORWARD = -0.005  # -50bp, as a decimal rate
_ANNIVERSARY_TOL_DAYS = 3
_SANITY_FILTER_ENV = "ARBS_CURVE_STORE_SANITY_FILTER"
#: Below this, no shape is dominant enough to call the others defective.
_MODAL_SHARE_FLOOR = 0.60
#: Fewer rows than this in a (trading date, anchor) group and we do not judge shape.
_MIN_SHAPE_GROUP = 6
#: bp. An off-modal shape only counts as a defect if it also moves the level
#: this far from its neighbours. 2026-07-21's flickers are 30-33bp out; the
#: benign off-modal snapshots measured under 1bp.
_SHAPE_PRICE_IMPACT_BP = 2.0
#: How many modal snapshots either side to compare an off-modal one against.
_LOCAL_MODAL_WINDOW = 40
#: bp. Worst clean day in the 64-day sample was 8.0bp; 2026-07-30 was 78.0bp.
_ANCHOR_BLOCK_JUMP_BP = 15.0
#: An anchor block bigger than this is the session, not an outlier off it.
_ANCHOR_BLOCK_MAX_SHARE = 0.50
_REFERENCE_HORIZON_DAYS = 365


def sanity_filter_enabled() -> bool:
    """Read-path quarantine on/off. Defaults on; set the env to 0 to disable."""
    raw = os.getenv(_SANITY_FILTER_ENV)
    if raw is None or raw == "":
        return True
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def _to_date(value: Any) -> Optional[datetime.date]:
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if hasattr(value, "to_pydatetime"):
        try:
            return value.to_pydatetime().date()
        except Exception:
            return None
    try:
        ts = pd.Timestamp(value)
    except Exception:
        return None
    if ts is None or pd.isna(ts):
        return None
    return ts.date()


def _as_dates(values: Any) -> list[datetime.date]:
    if values is None:
        return []
    out: list[datetime.date] = []
    try:
        iterator = list(values)
    except TypeError:
        return []
    for v in iterator:
        d = _to_date(v)
        if d is not None:
            out.append(d)
    return out


def _as_floats(values: Any) -> np.ndarray:
    if values is None:
        return np.asarray([], dtype=float)
    try:
        return np.asarray(list(values), dtype=float)
    except Exception:
        return np.asarray([], dtype=float)


def is_reference_anniversary(ref: datetime.date, node: datetime.date) -> bool:
    """True when ``node`` sits on a whole-year anniversary of ``ref``.

    Identifies the mixed-interpolation spline boundary nodes, which
    ``_ensure_mixed_support_nodes`` places at exactly ref+2Y and ref+3Y and
    which therefore shift whenever the anchor shifts. Matching the anniversary
    rather than a hard-coded 2/3 keeps this correct if the spline window moves.
    """
    if node <= ref:
        return False
    years = round((node - ref).days / 365.25)
    if years < 1:
        return False
    try:
        anniversary = ref.replace(year=ref.year + years)
    except ValueError:  # 29 Feb
        anniversary = ref.replace(year=ref.year + years, day=28)
    return abs((node - anniversary).days) <= _ANNIVERSARY_TOL_DAYS


def shape_signature(node_dates: Sequence[Any]) -> tuple[datetime.date, ...]:
    """Anchor-independent fingerprint of which market instruments built a curve.

    Drops node[0] (the reference date) and every ref-anchored spline boundary
    node, leaving only absolute FOMC/IMM dates.
    """
    dates = _as_dates(node_dates)
    if not dates:
        return ()
    ref = dates[0]
    return tuple(d for d in dates[1:] if not is_reference_anniversary(ref, d))


def implied_forwards(node_dates: Sequence[Any], discount_factors: Sequence[Any]) -> np.ndarray:
    """Simple ACT/360 forward rates (decimal) between consecutive nodes."""
    dates = _as_dates(node_dates)
    dfs = _as_floats(discount_factors)
    n = min(len(dates), len(dfs))
    if n < 2:
        return np.asarray([], dtype=float)
    out = np.full(n - 1, np.nan, dtype=float)
    for i in range(n - 1):
        days = (dates[i + 1] - dates[i]).days
        if days <= 0 or not math.isfinite(dfs[i]) or not math.isfinite(dfs[i + 1]) or dfs[i + 1] == 0.0:
            continue
        out[i] = (dfs[i] / dfs[i + 1] - 1.0) / (days / 360.0)
    return out


def reference_rate(
    node_dates: Sequence[Any],
    discount_factors: Sequence[Any],
    *,
    horizon_days: int = _REFERENCE_HORIZON_DAYS,
) -> float:
    """Simple ACT/360 rate (percent) from the anchor to anchor+horizon.

    Log-linear on the stored discount factors. A single comparable level for a
    curve whose node set changes shape from minute to minute -- a named FOMC
    forward would come and go with the meeting calendar.
    """
    dates = _as_dates(node_dates)
    dfs = _as_floats(discount_factors)
    n = min(len(dates), len(dfs))
    if n < 2 or not math.isfinite(dfs[0]) or dfs[0] <= 0.0:
        return float("nan")
    offsets = np.array([(d - dates[0]).days for d in dates[:n]], dtype=float)
    target = float(horizon_days)
    if target <= offsets[0] or target > offsets[-1]:
        return float("nan")
    values = dfs[:n]
    if not np.all(np.isfinite(values)) or np.any(values <= 0.0):
        return float("nan")
    df_target = float(np.exp(np.interp(target, offsets, np.log(values))))
    if df_target <= 0.0:
        return float("nan")
    return (values[0] / df_target - 1.0) / (target / 360.0) * 100.0


def snapshot_defects(
    node_dates: Sequence[Any],
    discount_factors: Sequence[Any],
    *,
    trading_date: Optional[datetime.date] = None,
    min_forward_rate: float = _DEFAULT_MIN_FORWARD,
) -> tuple[str, ...]:
    """Defect codes for a single stored curve snapshot, in isolation.

    Session-relative predicates (``off_modal_shape``, ``anchor_block_jump``)
    need neighbours and live in :func:`frame_defects`.
    """
    dates = _as_dates(node_dates)
    dfs = _as_floats(discount_factors)
    codes: list[str] = []

    if len(dates) == 0 or len(dfs) == 0 or len(dates) != len(dfs):
        return (EMPTY_NODES,)

    finite_mask = np.isfinite(dfs)
    if not np.all(finite_mask):
        codes.append(NON_FINITE_DF)
    if finite_mask.any() and np.any(dfs[finite_mask] <= 0.0):
        codes.append(NON_POSITIVE_DF)

    # An identity curve is rateslib's un-solved initial state, never a market.
    if len(dfs) > 1 and np.all(finite_mask) and np.allclose(dfs, 1.0, rtol=0.0, atol=_IDENTITY_TOL):
        codes.append(DEGENERATE_IDENTITY)

    fwds = implied_forwards(dates, dfs)
    if fwds.size and np.isfinite(fwds).any() and np.nanmin(fwds) < min_forward_rate:
        codes.append(NEGATIVE_FORWARD)

    if trading_date is not None and dates[0] != trading_date:
        codes.append(ANCHOR_MISMATCH)

    return tuple(codes)


def _column(df: pd.DataFrame, name: str) -> pd.Series:
    if name in df.columns:
        return df[name]
    return pd.Series([None] * len(df), index=df.index, dtype=object)


def _flag_off_modal_shape(
    df: pd.DataFrame,
    sigs: pd.Series,
    groups: pd.Series,
    rates: pd.Series,
    order: pd.Series,
) -> pd.Series:
    """Flag snapshots built from a minority instrument set AND priced away from it.

    Shape alone is not enough. Of 60 hourly points the shape rule removed on its
    own, 19 sat within 1bp of their clean neighbours -- structurally different
    builds that happened to price the same. Those are not worth a gap. The ones
    that matter move: 2026-07-21's four hourly flickers are 30-33bp out.
    """
    off_modal = pd.Series(False, index=df.index)
    for key, idx in groups.groupby(groups, dropna=False).groups.items():
        grp_sigs = sigs.loc[idx]
        if len(grp_sigs) < _MIN_SHAPE_GROUP:
            # Reads are often sampled (an hourly grid over a 1-minute store), so
            # a group can be a handful of rows -- too few to establish a mode.
            continue
        counts = grp_sigs.value_counts()
        if len(counts) < 2:
            continue
        if counts.iloc[0] / counts.sum() < _MODAL_SHARE_FLOOR:
            # No shape dominant enough to call the others wrong. Auto-dropping
            # here could delete half a session on a guess; surface it instead.
            logger.warning(
                "Curve shape is ambiguous for %s: %d shapes, modal share %.0f%% of %d "
                "snapshots -- not quarantining, this day needs a rebuild.",
                key, len(counts), 100 * counts.iloc[0] / counts.sum(), int(counts.sum()),
            )
            continue

        odd = grp_sigs != counts.index[0]
        if not odd.any():
            continue
        modal_idx = grp_sigs.index[~odd]
        modal_rates = rates.loc[modal_idx].dropna()
        modal_order = order.loc[modal_rates.index]
        if modal_rates.empty:
            continue

        for row_idx in grp_sigs.index[odd]:
            rate = rates.get(row_idx, float("nan"))
            if not math.isfinite(rate):
                # No comparable level: fall back to shape alone rather than
                # letting an unpriceable snapshot through.
                off_modal.loc[row_idx] = True
                continue
            # Compare against the nearest modal snapshots in time, not the whole
            # block: a session moves, and a day-wide median would flag ordinary
            # movement as a defect.
            distance = (modal_order - order.get(row_idx, 0)).abs().sort_values()
            local = modal_rates.loc[distance.index[:_LOCAL_MODAL_WINDOW]]
            if local.empty:
                continue
            if abs(rate - float(local.median())) * 100.0 > _SHAPE_PRICE_IMPACT_BP:
                off_modal.loc[row_idx] = True
    return off_modal


def _flag_anchor_block_jump(
    df: pd.DataFrame,
    anchors: pd.Series,
    day: pd.Series,
    rates: pd.Series,
    *,
    threshold_bp: float = _ANCHOR_BLOCK_JUMP_BP,
) -> pd.Series:
    """Flag a minority anchor block sitting at the wrong level for its session."""
    flagged = pd.Series(False, index=df.index)
    if rates.isna().all():
        return flagged

    for _, day_idx in day.groupby(day, dropna=False).groups.items():
        sub_anchors = anchors.loc[day_idx]
        sub_rates = rates.loc[day_idx]
        blocks = sub_anchors.groupby(sub_anchors, dropna=False).groups
        if len(blocks) < 2:
            continue
        medians = {k: float(np.nanmedian(sub_rates.loc[i])) for k, i in blocks.items()}
        sizes = {k: len(i) for k, i in blocks.items()}
        total = sum(sizes.values())
        # The largest block is the session; judge the others against it.
        main = max(sizes, key=lambda k: sizes[k])
        if not math.isfinite(medians[main]):
            continue
        for key, idx in blocks.items():
            if key == main or sizes[key] / total > _ANCHOR_BLOCK_MAX_SHARE:
                continue
            if not math.isfinite(medians[key]):
                continue
            if abs(medians[key] - medians[main]) * 100.0 > threshold_bp:
                logger.warning(
                    "Curve anchor block %s is %.1fbp off its session (%d of %d snapshots); quarantining.",
                    key, abs(medians[key] - medians[main]) * 100.0, sizes[key], total,
                )
                flagged.loc[idx] = True
    return flagged


def frame_defects(
    df: pd.DataFrame,
    *,
    check_shape: bool = True,
    check_anchor: bool = True,
    check_block_jump: bool = True,
    min_forward_rate: float = _DEFAULT_MIN_FORWARD,
) -> pd.Series:
    """Per-row defect-code tuples for a raw-store DataFrame.

    Session-relative predicates need the day in ``df``: a full-day read gives
    the intended answer, a sampled read degrades gracefully (see the group-size
    floor) rather than guessing.
    """
    if df is None or df.empty:
        return pd.Series([], dtype=object)

    node_col = _column(df, "node_dates")
    df_col = _column(df, "discount_factors")
    td_col = _column(df, "trading_date")

    codes: list[tuple[str, ...]] = [
        snapshot_defects(
            nd,
            dfv,
            trading_date=_to_date(td) if check_anchor else None,
            min_forward_rate=min_forward_rate,
        )
        for nd, dfv, td in zip(node_col, df_col, td_col)
    ]
    result = pd.Series(codes, index=df.index, dtype=object)

    if "node_dates" not in df.columns:
        return result

    anchors = node_col.map(lambda v: (_as_dates(v) or [None])[0])
    day = td_col.map(_to_date) if "trading_date" in df.columns else pd.Series("_all", index=df.index)
    rates = pd.Series(
        [reference_rate(nd, dfv) for nd, dfv in zip(node_col, df_col)], index=df.index, dtype=float
    )
    # Position in time, for "nearest modal snapshots". Falls back to row order
    # when the frame carries no usable timestamp.
    if "timestamp_utc" in df.columns:
        order = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce").astype("int64")
        if order.isna().any():
            order = pd.Series(np.arange(len(df)), index=df.index)
    else:
        order = pd.Series(np.arange(len(df)), index=df.index)

    extra = pd.Series([()] * len(df), index=df.index, dtype=object)
    if check_shape:
        sigs = node_col.map(shape_signature)
        groups = pd.Series(list(zip(day, anchors)), index=df.index, dtype=object)
        off_modal = _flag_off_modal_shape(df, sigs, groups, rates, order)
        extra = pd.Series(
            [t + ((OFF_MODAL_SHAPE,) if f else ()) for t, f in zip(extra, off_modal)],
            index=df.index, dtype=object,
        )
    if check_block_jump:
        jump = _flag_anchor_block_jump(df, anchors, day, rates)
        extra = pd.Series(
            [t + ((ANCHOR_BLOCK_JUMP,) if f else ()) for t, f in zip(extra, jump)],
            index=df.index, dtype=object,
        )

    return pd.Series(
        [tuple(a) + tuple(b) for a, b in zip(result, extra)], index=df.index, dtype=object
    )


def filter_raw_frame(
    df: pd.DataFrame,
    *,
    drop_codes: Iterable[str] = READ_DROP_CODES,
    curve_name: str = "",
) -> pd.DataFrame:
    """Drop unbelievable snapshots from a raw-store frame.

    Returns the frame unchanged when nothing trips. Logs one summary line per
    call, not one per row -- a bad day is 1,381 rows.
    """
    if df is None or df.empty:
        return df

    drop = set(drop_codes)
    codes = frame_defects(df)
    bad = codes.map(lambda cs: bool(drop.intersection(cs)))
    if not bad.any():
        return df

    reasons: dict[str, int] = {}
    for cs in codes[bad]:
        for c in cs:
            if c in drop:
                reasons[c] = reasons.get(c, 0) + 1
    logger.warning(
        "CurveStore sanity filter dropped %d/%d snapshot(s) for %s: %s",
        int(bad.sum()), len(df), curve_name or "<unknown curve>",
        ", ".join(f"{k}={v}" for k, v in sorted(reasons.items())),
    )
    return df.loc[~bad]


def usd_fedfunds_cb_dates() -> frozenset[datetime.date]:
    """USD central-bank effective dates. Used by the audit report only.

    Imported lazily: the builder module pulls in rateslib, and the read path
    must not pay that. Returns empty on failure rather than breaking a read.
    """
    try:
        from Query.IRSwaps._CENTRAL_BANK_DATES import _CENTRAL_BANK_DATES

        cb_map: Mapping[str, tuple[datetime.date, datetime.date]] = _CENTRAL_BANK_DATES.get("USD-FEDFUNDS", {})
        return frozenset(end for (_start, end) in cb_map.values())
    except Exception:
        logger.debug("Central-bank date lookup unavailable.", exc_info=True)
        return frozenset()

"""Aggregation: per-unit signed key-rate DV01 -> the dealer risk ladder.

THIS IS A FLOW SERIES. IT IS NOT AN INVENTORY.
---------------------------------------------
Read the ladder as "what customers handed the dealer community over this
window", never as "what the dealers are holding". The two differ by everything
the tape cannot see, and what it cannot see is not noise:

* **compression and allocation are never publicly reported**, so risk leaves a
  dealer's book with no offsetting print. Accumulating flow into a position
  therefore carries an unbounded, *monotone* error -- it only ever grows, and
  nothing in the data pushes back;
* prime-brokerage mirror legs cannot be de-duplicated where it matters (#99 is
  ``NR`` when the trade is cleared, and most of the tape is cleared), so the
  double-count is unbounded rather than merely unmeasured (F-21);
* Remedy-1 unwinds print as ordinary at-market offsetting trades with no
  ``TERM`` and no pointer, so they are invisible by construction.

:func:`decayed_flow` exists for a consumer who wants a stock rather than a
flow, and it **has no default half-life** for exactly this reason. Naming a
decay is naming an assumption about how fast the unobserved offset arrives.

THE WEIGHT IS ``2p - 1``
------------------------
``conventions.signed_weight``, not ``p``. At ``p = 0.5`` a ``p``-weighted
contribution is half a long position; ``2p - 1`` is zero, which is what a coin
flip has to be worth. The input risk is therefore the **hypothesis** profile
``dv01_if_received`` -- the profile the dealer would hold if the dealer received
fixed -- and the weight supplies both the sign and the confidence. Feeding in a
profile that is *already* signed by ``dealer_sign`` signs it twice and produces
a ladder that is positive everywhere; :class:`DoubleSignedKRD` refuses that
input rather than computing it.

THE CLOCK IS ``visibility``
---------------------------
Every row is stamped on ``Clocks.visibility`` and bucketed on its **New York**
date. Not execution: dating a print on when it was struck claims it was
actionable before Part 43 published it, which is lookahead of exactly the
length of the legal delay. Not the UTC date either -- 20:30 ET is 00:30Z, so a
UTC date pushes the whole US afternoon into tomorrow.

FOUR SERIES, NEVER POOLED
-------------------------
``venue_class`` (D2C / D2D / VENUE_UNKNOWN) and ``series`` (FLOW / LIFECYCLE)
are aggregation *keys*, not columns to sum over:

* **D2D is not customer flow.** Dealers recycling risk among themselves is a
  real signal in its own right -- it is what :mod:`.health` reads to check the
  classifier -- but it is not inventory being loaded onto the dealer community.
* **VENUE_UNKNOWN is a third series**, not a rounding of the other two. It is
  51,260 XXXX legs, 28,401 XOFF, 25,192 TREU and a long tail (F-7); assigning
  it to D2C manufactures customer flow and assigning it to D2D manufactures
  recycling.
* **Lifecycle prints are their own series** (D8). The sign is right, but a
  termination is priced against seasoned P&L rather than against bid-offer, so
  the confidence model calibrated on new trades does not transfer to it.

There is deliberately no function here that totals across those keys.
"""
from __future__ import annotations

import datetime

import pandas as pd
import pytz

from SDRUtils.dealer_direction import conventions as conv
from SDRUtils.dealer_direction import provenance as _prov
from SDRUtils.dealer_direction import types as T

NY = pytz.timezone("America/New_York")

SERIES_FLOW = "FLOW"
SERIES_LIFECYCLE = "LIFECYCLE"

#: The risk column the ladder consumes. Named for the hypothesis it holds, not
#: for what it is a delta of, because the name is the contract.
KRD_VALUE_COL = "dv01_if_received"

#: The aggregation key. Order matters only for readability; completeness is the
#: point -- drop ``venue_class`` or ``series`` and two things that must never be
#: added together get added together.
LADDER_KEYS = ("bucket_space", "bucket_key", "visibility_date",
               "venue_class", "series")

LADDER_COLUMNS = list(LADDER_KEYS) + [
    "delta_dv01", "abs_dv01", "n_units", "mean_abs_signed_weight",
]

#: Per-unit output. Emitted alongside the aggregate so nothing is lost: the
#: consumer wants the cell, the auditor wants the print behind it.
UNIT_ROW_COLUMNS = [
    "unit_key", "bucket_space", "bucket_key", "dv01_if_received", "delta_dv01",
    "p", "signed_weight", "dealer_sign", "rule", "tau_bucket", "in_dead_zone",
    "venue_class", "series", "visibility_date", "visibility_timestamp",
    "visibility_source", "execution_timestamp", "event_timestamp",
    "pricing_timestamp", "as_of_date", "rate_index", "kind", "n_legs",
    "is_block", "is_capped", "code_vintage",
]

EXCLUSION_COLUMNS = ["unit_key", "failure_reason", "venue_class", "series",
                     "visibility_date", "as_of_date"]


class DoubleSignedKRD(ValueError):
    """The risk frame looks like it is already signed by ``dealer_sign``.

    Multiplying a dealer-signed profile by ``2p - 1`` -- which carries the same
    sign by construction, since ``p > 0.5`` iff ``dealer_sign = +1`` -- yields
    ``|2p-1| * |dv01|``: a ladder that is positive in every bucket on every day,
    plausible-looking and completely wrong. Convert once, explicitly, with
    :func:`orient_to_received`.
    """


# --------------------------------------------------------------------------
# clocks
# --------------------------------------------------------------------------

def visibility_date(ts) -> datetime.date:
    """The New York session date a print became actionable on.

    The tape's three timestamp columns are ``timestamp with time zone`` and
    arrive as ``datetime64[ns, UTC]``, so a real print always converts
    unambiguously: 20:30 ET is 00:30Z, and bucketing on the UTC date would push
    the whole US afternoon session into the next day.

    **A tz-naive stamp is not converted at all**, and that is deliberate. The
    only way one reaches here is the date-only degradation: spec footnote 39
    lets #30 carry ``00:00:00`` when the time is unavailable,
    :func:`snapshot.pricing_timestamp` returns a bare ``date`` for those, and
    the visibility delay lands it at a naive 00:xx-01:xx. That object has no
    wall clock to convert *from*; reading it as UTC and shifting to New York
    hands back the **previous** calendar day, which is a whole day of lookahead
    manufactured by a timezone. It is the same trap ``snapshot._is_date_only``
    documents from the other direction, and the same answer: use the frame it
    was reported in.
    """
    if isinstance(ts, datetime.date) and not isinstance(ts, datetime.datetime):
        return ts
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        return t.date()
    return t.tz_convert(NY).date()


# --------------------------------------------------------------------------
# the risk input
# --------------------------------------------------------------------------

def orient_to_received(krd, *, value_col: str | None = None,
                       dealer_sign_col: str = "dealer_sign") -> pd.DataFrame:
    """Convert a dealer-signed risk frame into the hypothesis orientation.

    ``delta_dv01 = dealer_sign * dv01_if_received`` and ``dealer_sign`` is
    ``+-1``, so the conversion is a multiply -- but it is a multiply that must
    happen exactly once, in one place, which is why the ladder refuses to do it
    implicitly. A ``dealer_sign`` of 0 means no call was made and there is
    nothing to orient.
    """
    krd = pd.DataFrame(krd).copy()
    if dealer_sign_col not in krd.columns:
        raise ValueError(f"no {dealer_sign_col!r} column to orient by")
    if value_col is None:
        for cand in ("delta_dv01", "dv01", "dealer_dv01"):
            if cand in krd.columns:
                value_col = cand
                break
    if value_col is None or value_col not in krd.columns:
        raise ValueError(f"no risk column to orient; looked for {value_col!r}")

    signs = krd[dealer_sign_col].astype("float64")
    if (signs == 0).any():
        raise ValueError(
            f"{int((signs == 0).sum())} risk row(s) carry dealer_sign=0; a tie "
            "is not a side and has no orientation to undo"
        )
    krd[KRD_VALUE_COL] = krd[value_col].astype("float64") * signs
    return krd.drop(columns=[dealer_sign_col])


def _validated_krd(krd) -> pd.DataFrame:
    krd = pd.DataFrame(krd)
    if KRD_VALUE_COL in krd.columns:
        return krd
    if "dealer_sign" in krd.columns:
        raise DoubleSignedKRD(
            f"risk frame has no {KRD_VALUE_COL!r} but does carry a "
            "'dealer_sign' column, so it is already signed by the direction "
            "call; weighting it by 2p-1 would sign it twice. Call "
            "ladder.orient_to_received() first."
        )
    raise ValueError(
        f"risk frame must carry {KRD_VALUE_COL!r} -- the signed key-rate DV01 "
        "profile the dealer would hold IF the dealer received fixed"
    )


# --------------------------------------------------------------------------
# per-unit rows
# --------------------------------------------------------------------------

def unit_ladder_rows(units, calls, krd, *, drop_dead_zone: bool = False,
                     curve_source: str | None = None):
    """``(rows, excluded)`` -- the per-unit ladder contributions and the rest.

    Two frames rather than one, and the caller has to look at both. A single
    frame lets a unit vanish between the risk stage and the ladder with nothing
    recording that it did; ``excluded`` is what makes
    :func:`provenance.coverage_table` a partition instead of a list of successes
    with an unstated remainder.

    ``drop_dead_zone`` is off by default. ``2p - 1`` already makes a marginal
    call contribute almost nothing, so the dead zone is a monitoring flag and an
    opt-in filter for a consumer who wants a hard cut -- it is not what the
    aggregation depends on (DESIGN 1.3).
    """
    krd = _validated_krd(krd)
    by_unit = ({} if krd.empty
               else {k: v for k, v in krd.groupby("unit_key", sort=False)})

    call_map: dict = {}
    for call in calls:
        if call.unit_key in call_map:
            raise ValueError(f"two direction calls for unit {call.unit_key!r}")
        call_map[call.unit_key] = call

    vintage = _prov.code_vintage(curve_source)
    rows: list = []
    excluded: list = []

    for unit in units:
        key = unit.unit_key
        call = call_map.get(key)
        if call is None:
            raise ValueError(
                f"unit {key!r} has no direction call; every unit must carry one, "
                "including an excluded one, or the coverage accounting has a hole"
            )
        meta = _unit_meta(unit)

        if call.exclusion is not None:
            excluded.append(dict(meta, failure_reason=call.exclusion))
            continue
        if call.p is None or call.signed_weight is None:
            raise ValueError(
                f"unit {key!r} has no probability and no exclusion reason; a "
                "unit that cannot be called must say why"
            )
        _assert_weight_agrees_with_side(call)
        if drop_dead_zone and call.in_dead_zone:
            excluded.append(dict(meta, failure_reason=T.EXCL_DEAD_ZONE))
            continue

        legs = by_unit.get(key)
        if legs is None or legs.empty:
            # A call with no risk profile. Named rather than dropped: the risk
            # projection is a separate stage and it fails separately.
            excluded.append(dict(meta, failure_reason=T.EXCL_PRICING_ERROR))
            continue

        weight = float(call.signed_weight)
        for _, leg in legs.iterrows():
            dv01 = float(leg[KRD_VALUE_COL])
            rows.append(dict(
                meta,
                bucket_space=leg["bucket_space"],
                bucket_key=leg["bucket_key"],
                dv01_if_received=dv01,
                delta_dv01=weight * dv01,
                p=float(call.p),
                signed_weight=weight,
                dealer_sign=int(call.dealer_sign),
                rule=call.rule,
                tau_bucket=call.tau_bucket,
                in_dead_zone=bool(call.in_dead_zone),
                code_vintage=vintage,
            ))

    return (_frame(rows, UNIT_ROW_COLUMNS), _frame(excluded, EXCLUSION_COLUMNS))


def _assert_weight_agrees_with_side(call) -> None:
    """The weight is ``2p - 1`` and its sign is ``dealer_sign``, or the call is broken.

    Two checks, both of which have to be here rather than upstream.

    The first re-derives the weight from ``p`` through
    :func:`conventions.signed_weight`. A producer that set ``signed_weight = p``
    -- the exact mistake the convention exists to prevent -- would otherwise
    reach the ladder intact, and a coin flip would load half a position.

    The second is that ``p`` is p(dealer received), so ``p > 0.5`` iff the
    deviation was positive iff ``dealer_sign = +1``. If those disagree, one of
    them was computed against a flipped convention -- and downstream the
    disagreement is invisible, because the ladder only ever reads the weight.
    """
    w = float(call.signed_weight)
    expected = conv.signed_weight(float(call.p))
    if abs(w - expected) > 1e-12:
        raise ValueError(
            f"unit {call.unit_key!r}: signed_weight {w!r} is not 2p-1 = "
            f"{expected!r} for p={call.p!r}; the ladder aggregates 2p-1, and a "
            "p-weighted call would put half a position behind a coin flip"
        )
    side = int(call.dealer_sign)
    if w == 0.0 or side == 0:
        return
    if (w > 0) != (side > 0):
        raise ValueError(
            f"unit {call.unit_key!r}: signed_weight {w!r} and dealer_sign "
            f"{side!r} disagree on the side; one of them is against a flipped "
            "convention"
        )


def _unit_meta(unit) -> dict:
    c = unit.clocks
    return {
        "unit_key": unit.unit_key,
        "venue_class": unit.venue_class,
        "series": SERIES_LIFECYCLE if unit.is_lifecycle else SERIES_FLOW,
        "visibility_date": visibility_date(c.visibility),
        "visibility_timestamp": c.visibility,
        "visibility_source": c.visibility_source,
        "execution_timestamp": c.execution,
        "event_timestamp": c.event,
        "pricing_timestamp": c.pricing,
        "as_of_date": unit.as_of_date,
        "rate_index": unit.rate_index,
        "kind": unit.kind,
        "n_legs": unit.n_legs,
        "is_block": bool(unit.is_block),
        "is_capped": bool(unit.is_capped),
    }


def _frame(rows, columns) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows).reindex(columns=columns)


# --------------------------------------------------------------------------
# the ladder
# --------------------------------------------------------------------------

def aggregate(unit_rows) -> pd.DataFrame:
    """The ladder: one row per (bucket, availability date, venue class, series).

    ``abs_dv01`` is the gross pond the cell was formed from and ``delta_dv01``
    the signed net, so a reader can tell "no flow" from "two-sided flow" -- a
    net of zero over a $40mm gross is a different statement about the day than a
    net of zero over nothing, and only the second one means the ladder is empty.

    ``mean_abs_signed_weight`` is the gross-weighted mean ``|2p-1|``: how much
    of the pond actually survived the confidence weighting. It falls towards
    zero when the mid stops separating the two sides, which is the same
    degradation :mod:`.health` monitors from the other end.
    """
    unit_rows = pd.DataFrame(unit_rows)
    if unit_rows.empty:
        return pd.DataFrame(columns=LADDER_COLUMNS)

    work = unit_rows.copy()
    work["_abs"] = work[KRD_VALUE_COL].abs()
    work["_abs_delta"] = work["delta_dv01"].abs()
    grouped = work.groupby(list(LADDER_KEYS), dropna=False, sort=True)
    out = grouped.agg(
        delta_dv01=("delta_dv01", "sum"),
        abs_dv01=("_abs", "sum"),
        n_units=("unit_key", "nunique"),
        _abs_delta=("_abs_delta", "sum"),
    ).reset_index()
    out["mean_abs_signed_weight"] = (
        out["_abs_delta"] / out["abs_dv01"].where(out["abs_dv01"] != 0)
    )
    return out[LADDER_COLUMNS]


def customer_flow(ladder) -> pd.DataFrame:
    """The D2C flow series. A **selection**, never a sum over venue classes."""
    ladder = pd.DataFrame(ladder)
    if ladder.empty:
        return ladder
    return ladder[(ladder["venue_class"] == T.VENUE_D2C)
                  & (ladder["series"] == SERIES_FLOW)].reset_index(drop=True)


def interdealer_flow(ladder) -> pd.DataFrame:
    """The D2D series, kept separate. Input to :func:`health.d2d_recycling_kappa`."""
    ladder = pd.DataFrame(ladder)
    if ladder.empty:
        return ladder
    return ladder[(ladder["venue_class"] == T.VENUE_D2D)
                  & (ladder["series"] == SERIES_FLOW)].reset_index(drop=True)


def assert_series_disjoint(ladder) -> None:
    """The key is unique, so no cell is silently the sum of two series."""
    ladder = pd.DataFrame(ladder)
    missing = [k for k in LADDER_KEYS if k not in ladder.columns]
    if missing:
        raise ValueError(f"ladder is missing key column(s) {missing}")
    dup = ladder.duplicated(subset=list(LADDER_KEYS))
    if dup.any():
        raise ValueError(f"{int(dup.sum())} duplicated ladder key(s); the "
                         "aggregation key is incomplete")


# --------------------------------------------------------------------------
# the flow -> stock hook, which the caller has to ask for
# --------------------------------------------------------------------------

def decayed_flow(ladder, *, half_life_days, reconciliation=None) -> pd.DataFrame:
    """Exponentially decayed cumulative flow, per ladder series.

    **There is no default half-life, and that is the interface working.** The
    tape shows risk arriving and never shows it leaving -- compression and
    allocation are not publicly reported -- so a straight cumulative sum has an
    error that only grows. Naming a half-life is naming a belief about how fast
    the unobserved offset shows up, and the caller has to hold that belief
    explicitly. ``half_life_days=inf`` is pure accumulation and is allowed; it
    is just not the default.

    Decay runs on **calendar** days, not on row order: a Friday-to-Monday gap is
    three days of decay, and a bucket that prints once a fortnight must not be
    treated as if it printed daily. ``reconciliation``, if given, is called as
    ``f(key, date, accumulated) -> accumulated`` after each step -- the hook for
    a consumer who has an external position to snap back to.

    The output column is ``decayed_flow_dv01``, not ``position``, and it carries
    ``decay_half_life_days`` so the assumption travels with the number.
    """
    if half_life_days is None:
        raise ValueError(
            "half_life_days=None does not mean 'no decay' -- it means the "
            "assumption was not made. Pass a positive number of days, or "
            "float('inf') to accumulate without decay and say so."
        )
    half_life_days = float(half_life_days)
    if not half_life_days > 0.0:
        raise ValueError(f"half_life_days must be > 0, got {half_life_days!r}")

    ladder = pd.DataFrame(ladder)
    if ladder.empty:
        out = ladder.copy()
        out["decayed_flow_dv01"] = []
        out["decay_half_life_days"] = []
        return out

    group_keys = [k for k in LADDER_KEYS if k != "visibility_date"]
    out = ladder.sort_values(group_keys + ["visibility_date"]).copy()
    values: list = []
    for key, block in out.groupby(group_keys, dropna=False, sort=False):
        acc = 0.0
        prev = None
        for _, row in block.iterrows():
            day = row["visibility_date"]
            if prev is not None:
                gap = (pd.Timestamp(day) - pd.Timestamp(prev)).days
                acc *= 0.5 ** (gap / half_life_days)
            acc += float(row["delta_dv01"])
            if reconciliation is not None:
                acc = float(reconciliation(key, day, acc))
            values.append(acc)
            prev = day
    out["decayed_flow_dv01"] = values
    out["decay_half_life_days"] = half_life_days
    return out.reset_index(drop=True)


__all__ = [
    "DoubleSignedKRD", "EXCLUSION_COLUMNS", "KRD_VALUE_COL", "LADDER_COLUMNS",
    "LADDER_KEYS", "SERIES_FLOW", "SERIES_LIFECYCLE", "UNIT_ROW_COLUMNS",
    "aggregate", "assert_series_disjoint", "customer_flow", "decayed_flow",
    "interdealer_flow", "orient_to_received", "unit_ladder_rows",
    "visibility_date",
]

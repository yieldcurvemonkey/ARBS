"""What crossing this book actually cost, trade by trade.

Four measures, all of them per-instrument and all of them in the instrument's own
price units.  Nothing here rescales to basis points or dollars, because the store
already knows how: an outright quotes in index points and a differential
instrument quotes directly in basis points, so a single conversion constant baked
in here would be wrong for half the catalogue.  Scale the output with
``RVUtils.MBO.store.panel.scale_to`` if a common unit is wanted.

**The prevailing mid comes off the trade, never off a join.**  Every record inside
a CME packet carries the same timestamp, so an as-of join on time can pick up the
book the trade itself created and report a trade at the touch as a trade at the
mid.  The store solves this at write time: ``read_trades`` puts the book strictly
before the trade's own packet on the trade row as ``prev_mid``.  This module uses
that column and joins nothing to get it.

The *forward* mid is a different matter -- it genuinely is a lookup into the book
at ``t + h``, and there the as-of join is the right tool, because by then the
packet the trade sat in is long closed.

**Signs.**  ``d`` is ``+1`` for a buy-initiated trade and ``-1`` for a
sell-initiated one, taken from MBO's true aggressor flag rather than from a
tick-rule proxy, so the usual 15-20% misclassification is simply absent.  With
that convention every measure below is positive when the trade paid, whichever
side it was.

**One policy on a one-sided book, and it holds everywhere in this module: a mid
that did not exist is never replaced by one that did.**  Both places that need
the state of the book at a moment -- :func:`_forward_mid` at ``t + h`` and
:func:`kyle_lambda` at a bar close -- carry the state forward including the
absence of a mid, rather than reaching back for the last two-sided quote.  The
alternative is worse than it looks.  Filling a one-sided stretch with the last
real mid does not merely add noise: it manufactures an observation whose price
change is exactly zero, and it does so precisely in the stretches where liquidity
was worst, so every fabricated point pulls an impact estimate toward zero from
the direction that flatters it.  Measured on the fixture in
``tests/test_mbo_impact.py``, making a single bar one-sided moved ``lam`` from
1.00 to 0.75 and ``r2`` from 0.923 to 0.519 while ``n_bars`` stayed at 3 -- the
count, the one number a caller checks, gave no sign that a mid had been invented.
"""
from __future__ import annotations

from typing import Dict, Optional, Sequence

import numpy as np
import pandas as pd

__all__ = [
    "effective_spread",
    "impact_by_size",
    "kyle_lambda",
    "permanent_temporary",
]

def _only_symbol(*frames: Optional[pd.DataFrame]) -> None:
    """Refuse a frame set covering more than one instrument.

    The check pools the symbols of *every* frame rather than testing each one on
    its own, because the failure worth catching is a trades frame for one
    instrument passed alongside a book for another: two individually valid frames
    that together produce a number with no meaning and no NaN to give it away.
    """
    syms = set()
    for f in frames:
        if f is None or len(f) == 0 or "symbol" not in f.columns:
            continue
        syms.update(str(s) for s in pd.unique(f["symbol"]))
    if len(syms) > 1:
        raise ValueError(
            f"more than one instrument present ({sorted(syms)}); these measures are "
            f"per-instrument and pooling them is meaningless -- filter first, e.g. "
            f"trades[trades['symbol'] == {sorted(syms)[0]!r}]"
        )


def _require(frame: pd.DataFrame, cols: Sequence[str], what: str) -> None:
    missing = [c for c in cols if c not in frame.columns]
    if missing:
        raise KeyError(
            f"{what} is missing {missing}; the frames this module consumes are the "
            f"ones RVUtils.MBO.store.reader returns with decode=True (the default) "
            f"-- read with decode=False they carry tick indices and no prices"
        )


def _direction(trades: pd.DataFrame) -> np.ndarray:
    """``+1``/``-1``/NaN from the store's integer aggressor flag.

    An unknown aggressor becomes NaN rather than 0.  Zero would report an
    effective spread of exactly zero, which is indistinguishable from a genuine
    trade at the mid and would drag every median toward it.
    """
    a = trades["aggressor"]
    if a.dtype.kind not in "iuf":
        raise ValueError(
            "aggressor is not numeric; ReplayResult.trades carries the raw exchange "
            "side as 'B'/'A' bytes, while this module wants the store convention "
            "(+1 buy-initiated, -1 sell-initiated, 0 unknown) -- read the tape "
            "through RVUtils.MBO.store.reader.read_trades"
        )
    d = a.to_numpy(dtype=float)
    bad = ~np.isin(d, (-1.0, 0.0, 1.0))
    if bad.any():
        raise ValueError(
            f"aggressor takes values outside (-1, 0, +1): {sorted(set(d[bad]))[:5]}; "
            f"the sign of every measure here depends on it, so it is not guessed"
        )
    return np.where(d == 0.0, np.nan, d)


def _forward_mid(target: pd.Series, tob: pd.DataFrame) -> np.ndarray:
    """The top-of-book mid in force at each target time, as-of backward.

    Three choices, none of them the obvious one:

    * **One-sided states are kept.**  Dropping the rows whose mid is NaN first
      would silently mark a trade against the last *two-sided* mid, which can be
      minutes old -- a plausible number where in truth there was no mid at all.
      Keeping them lets the NaN propagate to the realised spread, which is the
      honest answer.  This is the module-wide policy stated at the top of the
      file; :func:`kyle_lambda` implements the same rule at a bar close.
    * **Beyond the last observation the answer is NaN, not the last quote.**  A
      backward as-of always finds something, so a trade forty seconds before the
      final quote of the day would otherwise get a sixty-second realised spread
      measured over forty seconds, and nothing would look wrong.
    * **Ties in ``ts_recv`` resolve to the highest ``sequence``.**  Backward
      as-of takes the last matching row of the right frame, so without sorting on
      sequence the "state at ``t+h``" would be whichever row happened to land
      last in the file.
    """
    sort_cols = ["ts_recv", "sequence"] if "sequence" in tob.columns else ["ts_recv"]
    right = (tob[sort_cols + ["mid"]]
             .sort_values(sort_cols, kind="stable")[["ts_recv", "mid"]]
             .reset_index(drop=True))

    pos = np.argsort(target.astype("int64").to_numpy(), kind="stable")
    left = target.iloc[pos].rename("_t").reset_index(drop=True).to_frame()
    joined = pd.merge_asof(left, right, left_on="_t", right_on="ts_recv",
                           direction="backward")

    out = np.empty(len(target), dtype=float)
    out[pos] = joined["mid"].to_numpy(dtype=float)
    out[(target > right["ts_recv"].iloc[-1]).to_numpy()] = np.nan
    return out


def _horizons(horizons_s: Sequence[float]) -> list:
    hs = [float(h) for h in horizons_s]
    bad = [h for h in hs if not np.isfinite(h) or h <= 0.0]
    if bad:
        raise ValueError(
            f"horizons must be finite and positive, got {bad}; a non-positive "
            f"horizon marks the trade against a book that existed before it, which "
            f"is the effective spread again and not a realised one"
        )
    return hs


def effective_spread(
    trades: pd.DataFrame,
    tob: Optional[pd.DataFrame] = None,
    horizons_s: Sequence[float] = (1.0, 10.0, 60.0),
) -> pd.DataFrame:
    """Per-trade effective spread, realised spread and price impact.

    For a trade at ``price`` with direction ``d``, prevailing mid ``m0`` and mid
    ``mh`` at ``t + h``::

        eff       = 2 * d * (price - m0)
        real_<h>s = 2 * d * (price - mh)
        impact_<h>s = eff - real_<h>s = 2 * d * (mh - m0)

    ``eff`` is what the trade paid against the mid it faced; ``real`` is what a
    market maker who took the other side and unwound at the mid ``h`` seconds
    later kept; ``impact`` is the part of the payment that was information rather
    than compensation.

    ``m0`` is read straight off ``trades['prev_mid']`` and is **not** re-joined
    from ``tob``.  Every record inside a packet shares a timestamp, so an as-of
    join on time can pick up the book the trade itself created -- which turns a
    trade that lifted the offer into a trade at the mid, silently and only
    sometimes.  The store captures the pre-packet book during replay precisely so
    that this join never has to happen.

    ``mh`` does need ``tob`` and is looked up as-of backward on ``ts_recv``.  With
    ``tob=None`` only ``eff`` is added and no realised or impact columns exist at
    all, rather than columns full of NaN that a caller might average.

    A ``mid_fwd_<h>s`` column is added alongside each pair so that a NaN realised
    spread is attributable: it distinguishes "the book was one-sided at ``t+h``"
    from "``t+h`` is past the end of the data".

    Over a multi-session frame the forward mid can reach across the overnight
    break and land on the previous session's close.  Read one session at a time
    if that matters.

    An empty tape is answered with an empty typed frame, but only *after* the
    book has been checked, never instead of checking it: an empty ``tob`` raises
    and a book covering a second instrument raises, whether the tape has rows or
    not.  Zero rows is not a licence to publish a column that was never measured.

    Returns ``trades`` with the new columns appended.  Row order, index and every
    existing column are preserved; nothing is dropped, including trades whose
    aggressor is unknown (their measures are NaN).
    """
    if trades is None:
        raise ValueError("trades is None; pass the frame from read_trades")
    hs = _horizons(horizons_s)

    # Everything that can be checked without the tape is checked before the tape
    # is looked at.  The empty-trades branch used to come first, so an empty tape
    # skipped both guards below: it returned ``real_`` and ``impact_`` columns
    # that had never been measured against any book -- the exact shape the
    # empty-``tob`` raise exists to refuse -- and it did so for a tape and a book
    # that need not have described the same instrument.  A column's presence is a
    # claim that it was measured, and no row count makes that claim cheaper.
    _only_symbol(trades, tob)
    if tob is not None:
        if len(tob) == 0:
            raise ValueError(
                "tob is empty, so there is no forward mid to measure a realised "
                "spread against; pass tob=None to compute the effective spread alone"
            )
        _require(tob, ("ts_recv", "mid"), "tob")

    if len(trades) == 0:
        out = trades.copy()
        out["eff"] = np.zeros(0, dtype=float)
        if tob is not None:
            for h in hs:
                tag = f"{h:g}s"
                out[f"mid_fwd_{tag}"] = np.zeros(0, dtype=float)
                out[f"real_{tag}"] = np.zeros(0, dtype=float)
                out[f"impact_{tag}"] = np.zeros(0, dtype=float)
        return out

    # The tape's own columns are required only once there is a tape.  A session
    # missing from the store comes back from ``read_trades`` as a frame with no
    # columns at all, and demanding ``prev_mid`` of it would turn a quiet day into
    # an exception in the middle of a sweep.
    _require(trades, ("ts_recv", "price", "prev_mid", "aggressor"), "trades")

    d = _direction(trades)
    price = trades["price"].to_numpy(dtype=float)
    m0 = trades["prev_mid"].to_numpy(dtype=float)

    out = trades.copy()
    eff = 2.0 * d * (price - m0)
    out["eff"] = eff
    if tob is None:
        return out

    for h in hs:
        tag = f"{h:g}s"
        mh = _forward_mid(out["ts_recv"] + pd.Timedelta(seconds=h), tob)
        out[f"mid_fwd_{tag}"] = mh
        real = 2.0 * d * (price - mh)
        out[f"real_{tag}"] = real
        out[f"impact_{tag}"] = eff - real
    return out


def impact_by_size(
    trades: pd.DataFrame,
    tob: Optional[pd.DataFrame] = None,
    horizon_s: float = 10.0,
    bins: Sequence[float] = (1, 2, 5, 10, 25, 100),
) -> pd.DataFrame:
    """Effective and realised spread bucketed by trade size.

    ``bins`` are left-closed edges with a final open-ended bucket, so
    ``(1, 2, 5)`` means ``[1, 2)``, ``[2, 5)``, ``[5, inf)``.

    Every bucket gets a row even when empty, because the shape of this frame is
    the same for every instrument-day and a sweep that concatenates a few hundred
    of them should not have to reindex.  Medians are taken over the finite values
    only, while ``n`` and ``volume`` count the whole bucket: a print with an
    unknown aggressor has a size but no signed cost, so it lands in ``n`` and in
    ``volume`` and in none of the medians.

    Medians rather than means, throughout.  The size distribution of futures
    trades is heavy enough that one 500-lot print at a bad moment moves a bucket
    mean by more than the rest of the bucket combined.

    With ``tob=None`` the realised and impact columns are present and NaN -- the
    columns are part of this frame's contract, and dropping them would make the
    two call shapes concatenate into a ragged table.

    A tape with no trades in it is a day on which every bucket was empty, and it
    is answered with the same one-row-per-bucket frame as any other day: the bins
    are an argument, so their shape is known before a single trade is read, and a
    zero-row frame here would break the very promise the fixed shape exists to
    make.  The book is not consulted on that path -- with nothing to measure there
    is nothing to measure it against -- so an empty ``tob`` alongside an empty
    tape is not an error here, unlike in :func:`effective_spread`.
    """
    cols = ["size_lo", "size_hi", "n", "volume",
            "eff_median", "real_median", "impact_median"]
    edges = np.asarray(bins, dtype=float)
    if edges.size == 0 or not np.all(np.diff(edges) > 0):
        raise ValueError(
            f"bins must be non-empty and strictly increasing, got {tuple(bins)}"
        )
    size_lo = edges
    size_hi = np.append(edges[1:], np.inf)

    if trades is None or len(trades) == 0:
        return pd.DataFrame({
            "size_lo": size_lo, "size_hi": size_hi,
            "n": np.zeros(edges.size, dtype="int64"),
            "volume": np.zeros(edges.size, dtype="int64"),
            "eff_median": np.full(edges.size, np.nan),
            "real_median": np.full(edges.size, np.nan),
            "impact_median": np.full(edges.size, np.nan),
        })[cols]

    _require(trades, ("size",), "trades")
    e = effective_spread(trades, tob, horizons_s=(horizon_s,))
    tag = f"{float(horizon_s):g}s"

    size = e["size"].to_numpy()
    # NaN fails every comparison, so it would slip past the bin-edge guard below,
    # land in the final open-ended bucket via searchsorted, and then become
    # INT64_MIN on the int64 cast -- a volume of -9.2e18 that poisons every sum
    # and share downstream.  The store returns int32 sizes, but this function
    # accepts any frame, and a size column that has been through a reindex, a
    # merge or a nullable-integer conversion arrives as float with NaN.
    if not np.isfinite(size).all():
        bad = int((~np.isfinite(size)).sum())
        raise ValueError(
            f"{bad} trade(s) have a non-finite size, which cannot be bucketed or "
            f"summed; drop or repair them before bucketing rather than letting "
            f"them land in the final bucket as a negative volume"
        )
    if size.min() < edges[0]:
        raise ValueError(
            f"trade size {size.min()} is below the first bin edge {edges[0]:g}, so it "
            f"belongs to no bucket; volume would go missing from the table -- pass "
            f"bins starting at or below the smallest size"
        )
    bucket = np.searchsorted(edges, size, side="right") - 1

    nan = np.full(len(e), np.nan)
    g = pd.DataFrame({
        "bucket": bucket,
        "size": size.astype("int64"),
        "eff": e["eff"].to_numpy(dtype=float),
        "real": e[f"real_{tag}"].to_numpy(dtype=float) if tob is not None else nan,
        "impact": e[f"impact_{tag}"].to_numpy(dtype=float) if tob is not None else nan,
    })
    grp = g.groupby("bucket", sort=True)
    full = pd.RangeIndex(len(edges))
    out = pd.DataFrame({
        "size_lo": size_lo,
        "size_hi": size_hi,
        "n": grp.size().reindex(full, fill_value=0).to_numpy(dtype="int64"),
        "volume": grp["size"].sum().reindex(full, fill_value=0).to_numpy(dtype="int64"),
        "eff_median": grp["eff"].median().reindex(full).to_numpy(dtype=float),
        "real_median": grp["real"].median().reindex(full).to_numpy(dtype=float),
        "impact_median": grp["impact"].median().reindex(full).to_numpy(dtype=float),
    })
    return out[cols]


def kyle_lambda(tob: pd.DataFrame, trades: pd.DataFrame,
                freq: str = "60s") -> Dict[str, float]:
    """Price impact per unit of signed volume: ``d_mid = alpha + lam * signed_volume``.

    Bars are cut on ``ts_recv`` at fixed ``freq`` boundaries anchored on the epoch,
    so the grid does not depend on which frame happens to start first and the book
    and the tape land in the same bars by construction.  ``freq`` must therefore be
    a fixed frequency -- ``'60s'``, ``'5min'`` -- and a calendar one raises.
    ``lam`` is in price units per signed lot.

    **Only bars in which something happened exist.**  A resample would manufacture
    one bar per minute of an overnight gap, and a listed butterfly that quotes for
    twenty minutes a day would contribute thousands of identical ``(0 volume, 0
    move)`` points.  Those do not shrink the true uncertainty in ``lam`` but they
    do shrink its standard error, which is the worst of both.

    **Bars that quoted but did not trade are kept.**  Dropping them conditions the
    sample on trading, and the bars where the mid moved without volume are exactly
    the ones that argue ``lam`` is smaller than the traded bars suggest.

    **The mid is differenced within a session, never across one.**  The first bar
    of each date has no predecessor, so a whole overnight gap is not charged to
    one minute of volume.  This needs the ``date`` column that ``read_tob`` adds.

    **A bar's mid is the state of the book at the bar's close, and a one-sided
    close has no mid.**  This is the module policy stated at the top of the file,
    and it is the same rule :func:`_forward_mid` applies at ``t + h``.  Two
    consequences follow, both deliberate.  The bar itself drops out, and so does
    the next one, because a difference needs both ends -- comparing the following
    bar against the last bar that *did* have a mid would charge a move spanning a
    one-sided stretch to a single bar's volume.  And a bar with no quote at all
    inherits the previous close *including its absence*: the book does not become
    two-sided by nobody touching it.  The ordinary forward-fill is what this
    replaces, and it is not a small correction -- see the module docstring for the
    measured 1.00-to-0.75 shift it produced with ``n_bars`` unchanged.

    **Bars are ordered before the close is taken.**  Every record inside a CME
    packet shares a timestamp, so without sorting on ``('ts_recv', 'sequence')``
    the "state at the close" would be whichever row of that packet happened to
    land last in the file.

    **Consecutive bars can be far apart, and ``d_mid`` does not know it.**  Only
    bars in which something happened exist, so a bar at 09:00 may be followed by
    one at 09:47, and the whole 47-minute mid move is then regressed on the second
    bar's volume alone.  Within a liquid session this is rare and harmless; on a
    listed butterfly that quotes in bursts it is the common case, and it inflates
    ``lam`` by attributing to one bar's flow a revaluation that took most of an
    hour.  There is no honest fix inside a single regression -- manufacturing the
    missing bars is the error this function refuses at the top -- so the caller
    who cares should either restrict to a contiguous stretch or read
    ``n_bars`` against the session length before believing the slope.

    A degenerate fit -- fewer than three bars, or no variation in signed volume --
    returns NaN values rather than raising.  This runs over a few hundred
    instrument-days at a time and a single quiet contract must not stop the sweep;
    ``n_bars`` is always the real count, so the caller can tell an untradeable day
    from a fitted one.
    """
    out: Dict[str, float] = {"lam": np.nan, "t_stat": np.nan, "r2": np.nan,
                             "n_bars": 0, "alpha": np.nan}
    if tob is None or len(tob) == 0:
        return out
    _only_symbol(tob, trades)
    _require(tob, ("ts_recv", "mid", "date"), "tob")

    sort_cols = ["ts_recv", "sequence"] if "sequence" in tob.columns else ["ts_recv"]
    q = tob[["date", "mid"] + sort_cols].sort_values(sort_cols, kind="stable").copy()
    q["bar"] = q["ts_recv"].dt.floor(freq)
    # The last row of the sorted bar, taken with ``drop_duplicates`` rather than
    # ``agg('last')``: the aggregation skips NaN, which would quietly close a
    # one-sided bar on the last two-sided quote inside it and hand the regression
    # a mid the book did not have at the close.
    close = (q.drop_duplicates(["date", "bar"], keep="last")
              .set_index(["date", "bar"])["mid"])
    # A one-sided close is carried through the fill as +inf and turned back into
    # NaN afterwards.  Leaving it NaN would make it indistinguishable from a bar
    # that simply had no quote in it, and the forward fill would then hand the
    # one-sided stretch the last real mid -- the fabrication this whole policy
    # exists to prevent, arriving one bar later than the obvious version of it.
    bars = close.fillna(np.inf).to_frame("mid")

    if trades is not None and len(trades) > 0:
        _require(trades, ("ts_recv", "size", "aggressor", "date"), "trades")
        t = trades[["date", "ts_recv", "size", "aggressor"]].copy()
        t["bar"] = t["ts_recv"].dt.floor(freq)
        # A print whose aggressor is unknown has size but no sign, so it adds
        # nothing to signed volume rather than adding it to an arbitrary side.
        t["signed"] = (np.nan_to_num(_direction(t), nan=0.0)
                       * t["size"].to_numpy(dtype=float))
        tb = t.groupby(["date", "bar"], sort=True).agg(signed_volume=("signed", "sum"))
        bars = bars.join(tb, how="outer")
    else:
        bars["signed_volume"] = 0.0

    bars = bars.sort_index()
    bars["signed_volume"] = bars["signed_volume"].fillna(0.0)
    # A bar with trades but no quote at all inherits the previous bar's closing
    # state: nothing touched the book, so its contribution is a real zero rather
    # than a hole.  What it inherits is the state, not a number -- if that state
    # was one-sided it arrives as the +inf sentinel and becomes NaN below.
    bars["mid"] = bars.groupby(level="date")["mid"].ffill()
    bars["mid"] = bars["mid"].mask(np.isinf(bars["mid"]))
    bars["d_mid"] = bars.groupby(level="date")["mid"].diff()

    use = bars["d_mid"].notna().to_numpy()
    y = bars.loc[use, "d_mid"].to_numpy(dtype=float)
    x = bars.loc[use, "signed_volume"].to_numpy(dtype=float)
    n = int(y.size)
    out["n_bars"] = n
    if n < 3:
        return out

    sxx = float(((x - x.mean()) ** 2).sum())
    if sxx <= 0.0:
        return out

    design = np.column_stack([np.ones(n), x])
    beta, *_ = np.linalg.lstsq(design, y, rcond=None)
    alpha, lam = float(beta[0]), float(beta[1])
    resid = y - design @ beta
    ss_res = float(resid @ resid)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    se = float(np.sqrt(ss_res / (n - 2) / sxx))
    # ``se`` is a Python float, so ``lam / se`` on a perfect fit raises
    # ZeroDivisionError -- np.errstate governs numpy's own arithmetic and does
    # nothing here.  The degenerate case is not exotic: a listed butterfly whose
    # mid never leaves one tick for a session while still trading produces
    # exactly it, and that is the most common quiet instrument-day in this
    # catalogue.  This function's contract is to return NaN and let a sweep over
    # a few hundred instrument-days continue, so it must not raise.
    t_stat = float(lam / se) if se > 0.0 else float("inf" if lam else "nan")
    out.update({
        "lam": lam,
        "alpha": alpha,
        # An exact fit has zero standard error and infinite t; that is reported as
        # inf rather than masked to NaN, because it means the regression is
        # interpolating too few distinct points and the caller should see it.
        "t_stat": float(t_stat),
        "r2": float(1.0 - ss_res / ss_tot) if ss_tot > 0.0 else np.nan,
    })
    return out


def permanent_temporary(trades: pd.DataFrame, tob: pd.DataFrame,
                        horizon_s: float = 300.0) -> Dict[str, float]:
    """Split the effective spread into what the market kept and what it paid back.

    The permanent component is the signed mid move over the horizon,
    ``2 * d * (mid_h - prev_mid)`` -- the same factor of two as the effective
    spread, so that ``permanent + temporary == eff`` holds trade by trade and the
    temporary part is exactly the realised spread.  The permanent part is the
    market's revision of fair value; the temporary part is inventory and
    liquidity compensation that a patient counterparty gets back.

    **What adds up, exactly, and what does not.**  Three statements, and the third
    is the one that costs people money:

    * per trade, ``permanent + temporary == eff``, to floating-point;
    * ``permanent_share + temporary_share == 1``, by construction, over the
      ``n_share`` trades that enter them;
    * ``permanent_median + temporary_median`` **need not equal** ``eff_median``,
      and routinely does not, because a median is not additive.  Measured on
      effective spreads of ``(1.0, 2.0, 3.0)`` with permanent components
      ``(0.9, 0.1, 2.9)``: ``eff_median`` 2.0, ``permanent_median`` 0.9,
      ``temporary_median`` 0.1 -- two components summing to half the spread they
      are supposed to decompose.  The three medians are each an honest central
      value of their own per-trade series and none of them is a share of another.

    That third point is why the shares here are medians of **per-trade** shares
    rather than a ratio of medians.  An earlier version divided
    ``permanent_median`` by ``eff_median`` and called the result
    ``permanent_share``, which invited exactly one reading -- that ``1 - share``
    was the temporary part -- and that reading was wrong by the arithmetic above.
    A per-trade share is a genuine decomposition of that trade's cost, and because
    ``temporary_i / eff_i`` is ``1 - permanent_i / eff_i``, a decreasing affine
    map, its median is exactly one minus the median of the permanent shares.
    ``temporary_share`` is returned as that complement so the identity is exact
    rather than merely close.

    A trade that printed at the mid has an effective spread of zero and a share
    that is a division by zero, so those trades are excluded from the shares and
    only from the shares; ``n_share`` reports how many remained, against ``n`` for
    the medians.  Shares are **not** confined to ``[0, 1]``: a trade that printed
    inside the mid, or one whose mid moved further than the trade paid, gives a
    share above one or below zero.  Taking the median rather than the mean is what
    keeps a handful of those from carrying the answer -- the same reason
    :func:`impact_by_size` reports medians.

    All three medians are taken over the same subset of trades -- those with a
    finite effective spread *and* a finite forward mid -- so the components are
    comparable.  Letting ``eff_median`` use the trades whose horizon ran past the
    end of the data would put the three on different samples, for a reason
    invisible in the output.
    """
    out: Dict[str, float] = {"n": 0, "eff_median": np.nan, "permanent_median": np.nan,
                             "temporary_median": np.nan, "n_share": 0,
                             "permanent_share": np.nan, "temporary_share": np.nan}
    # The book is demanded before the tape is counted, for the reason
    # :func:`effective_spread` documents: an empty tape used to return here first
    # and so answered "nothing to decompose" for a call that could never have
    # decomposed anything, book or no book.
    if tob is None or len(tob) == 0:
        raise ValueError(
            "permanent_temporary needs the book: the permanent component is a mid "
            "move measured at the horizon, and without tob there is nothing to "
            "measure it against"
        )
    if trades is None or len(trades) == 0:
        return out

    e = effective_spread(trades, tob, horizons_s=(horizon_s,))
    tag = f"{float(horizon_s):g}s"
    eff = e["eff"].to_numpy(dtype=float)
    perm = e[f"impact_{tag}"].to_numpy(dtype=float)
    temp = e[f"real_{tag}"].to_numpy(dtype=float)

    ok = np.isfinite(eff) & np.isfinite(perm) & np.isfinite(temp)
    n = int(ok.sum())
    out["n"] = n
    if n == 0:
        return out

    out.update({
        "eff_median": float(np.median(eff[ok])),
        "permanent_median": float(np.median(perm[ok])),
        "temporary_median": float(np.median(temp[ok])),
    })

    priced = ok & (eff != 0.0)
    n_share = int(priced.sum())
    out["n_share"] = n_share
    if n_share > 0:
        share = float(np.median(perm[priced] / eff[priced]))
        out["permanent_share"] = share
        out["temporary_share"] = 1.0 - share
    return out

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
      honest answer.
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

    Returns ``trades`` with the new columns appended.  Row order, index and every
    existing column are preserved; nothing is dropped, including trades whose
    aggressor is unknown (their measures are NaN).
    """
    if trades is None:
        raise ValueError("trades is None; pass the frame from read_trades")
    hs = _horizons(horizons_s)

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

    _only_symbol(trades, tob)
    _require(trades, ("ts_recv", "price", "prev_mid", "aggressor"), "trades")

    d = _direction(trades)
    price = trades["price"].to_numpy(dtype=float)
    m0 = trades["prev_mid"].to_numpy(dtype=float)

    out = trades.copy()
    eff = 2.0 * d * (price - m0)
    out["eff"] = eff
    if tob is None:
        return out

    if len(tob) == 0:
        raise ValueError(
            "tob is empty, so there is no forward mid to measure a realised spread "
            "against; pass tob=None to compute the effective spread alone"
        )
    _require(tob, ("ts_recv", "mid"), "tob")

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
    """
    cols = ["size_lo", "size_hi", "n", "volume",
            "eff_median", "real_median", "impact_median"]
    edges = np.asarray(bins, dtype=float)
    if edges.size == 0 or not np.all(np.diff(edges) > 0):
        raise ValueError(
            f"bins must be non-empty and strictly increasing, got {tuple(bins)}"
        )

    if trades is None or len(trades) == 0:
        return pd.DataFrame({
            "size_lo": np.zeros(0, dtype=float), "size_hi": np.zeros(0, dtype=float),
            "n": np.zeros(0, dtype="int64"), "volume": np.zeros(0, dtype="int64"),
            "eff_median": np.zeros(0, dtype=float),
            "real_median": np.zeros(0, dtype=float),
            "impact_median": np.zeros(0, dtype=float),
        })

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
        "size_lo": edges,
        "size_hi": np.append(edges[1:], np.inf),
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

    q = tob[["date", "ts_recv", "mid"]].copy()
    q["bar"] = q["ts_recv"].dt.floor(freq)
    # ``last`` skips NaN, so a bar that ended one-sided closes on its last
    # two-sided mid rather than on nothing.
    bars = q.groupby(["date", "bar"], sort=True).agg(mid=("mid", "last"))

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
    # A bar with trades but no quote change inherits the previous bar's mid: the
    # book did not move, so its contribution is a real zero rather than a hole.
    bars["mid"] = bars.groupby(level="date")["mid"].ffill()
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

    All three medians are taken over the same subset of trades -- those with a
    finite effective spread *and* a finite forward mid -- so the shares are
    comparable.  Letting ``eff_median`` use the trades whose horizon ran past the
    end of the data would make the decomposition not add up, for a reason invisible
    in the output.

    ``permanent_share`` is the ratio of the medians, not the median of the
    per-trade ratios.  A trade that printed at the mid has an effective spread of
    zero, and its share is a division by zero that no amount of winsorising makes
    meaningful.
    """
    out: Dict[str, float] = {"n": 0, "eff_median": np.nan, "permanent_median": np.nan,
                             "temporary_median": np.nan, "permanent_share": np.nan}
    if trades is None or len(trades) == 0:
        return out
    if tob is None or len(tob) == 0:
        raise ValueError(
            "permanent_temporary needs the book: the permanent component is a mid "
            "move measured at the horizon, and without tob there is nothing to "
            "measure it against"
        )

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

    eff_med = float(np.median(eff[ok]))
    out.update({
        "eff_median": eff_med,
        "permanent_median": float(np.median(perm[ok])),
        "temporary_median": float(np.median(temp[ok])),
        "permanent_share": (float(np.median(perm[ok])) / eff_med
                            if eff_med != 0.0 else np.nan),
    })
    return out

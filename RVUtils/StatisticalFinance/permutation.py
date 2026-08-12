"""Permutation sampling: destroy temporal structure, keep everything else.

A permutation test needs a null in which the *only* thing removed is the thing
the strategy claims to exploit. Resampling returns i.i.d. removes far more than
that -- it flattens volatility clustering, the fat tails, the intra-bar
geometry -- so a strategy can look significant merely because the null is a
worse description of the market than the data is.

The methods here permute the ORDER of log returns and leave the marginal
distribution exactly intact. The first and last price of every window survive
untouched, so a permuted series has the same start, the same end, the same set
of returns and the same histogram; only *when* each return happened changes.

Follows quantpylib's Statistical Finance notes
(https://quantpylib.hangukquant.com/learn/statistical_finance/), which in turn
follow Masters, *Permutation and Randomization Tests for Trading System
Development*.

Two deviations from the reference implementation, both deliberate:

* every entry point takes an explicit ``numpy.random.Generator``. A module that
  reads the global RNG is not reproducible when two callers interleave, and a
  seed that is "set once at the top" silently stops meaning anything the moment
  anything else draws from it.
* nothing mutates its argument. The reference ``permutation_member`` shuffles
  in place and returns the same object, which makes ``permute_price(prices)``
  destroy ``prices``.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

__all__ = [
    "permutation_index",
    "permute_price",
    "permute_multi_prices",
    "permute_bars",
    "permute_multi_bars",
    "permute_series_within_groups",
]


def permutation_index(n: int, rng: np.random.Generator) -> np.ndarray:
    """A uniformly random permutation of ``range(n)``.

    The reference uses a hand-rolled Fisher-Yates; ``Generator.permutation`` is
    the same distribution and is the one numpy tests.
    """
    return rng.permutation(int(n))


# ===========================================================================
# Univariate (price) permutations
# ===========================================================================
def permute_price(price: Sequence[float] | np.ndarray | pd.Series,
                  rng: Optional[np.random.Generator] = None,
                  index: Optional[np.ndarray] = None):
    """Permute a price series' log returns, preserving the first price.

        D_t = log(P_{t+1} / P_t)

    the ``D_t`` are shuffled, cumulatively summed onto ``log P_0`` and
    exponentiated. ``P_0`` is therefore exact and the multiset of log returns is
    exact; the LAST price is preserved only in distribution, because the sum of
    a permuted set is the sum of the set -- which means it is preserved exactly
    too, up to floating point.

    ``index`` lets several series share one permutation, which is what keeps
    cross-sectional correlation intact across instruments.
    """
    is_series = isinstance(price, pd.Series)
    values = np.asarray(price.values if is_series else price, dtype=float)
    if values.ndim != 1:
        raise ValueError("permute_price expects a 1-D price series")
    if len(values) < 3:
        return price.copy() if is_series else values.copy()
    if np.any(values <= 0):
        raise ValueError("permute_price works in log space and needs strictly positive prices")

    log_prices = np.log(values)
    diffs = np.diff(log_prices)
    if index is None:
        if rng is None:
            raise ValueError("permute_price needs either an rng or a permutation index")
        index = permutation_index(len(diffs), rng)
    index = np.asarray(index, dtype=int)
    if len(index) != len(diffs):
        raise ValueError(
            f"permutation index has length {len(index)} but the series has {len(diffs)} returns")

    permuted = np.concatenate(([log_prices[0]], log_prices[0] + np.cumsum(diffs[index])))
    out = np.exp(permuted)
    if is_series:
        return pd.Series(out, index=price.index, name=price.name)
    return out


def permute_multi_prices(prices: Sequence, rng: np.random.Generator) -> List:
    """Permute several equal-length price series with ONE shared index.

    Sharing the index is what separates this from permuting each series
    independently: the cross-sectional correlation between instruments survives,
    so a portfolio-level result is tested against a null that still has the
    market's co-movement in it.
    """
    lengths = {len(p) for p in prices}
    if len(lengths) != 1:
        raise ValueError(f"permute_multi_prices needs equal lengths, got {sorted(lengths)}")
    n = lengths.pop()
    if n < 3:
        return [p.copy() for p in prices]
    idx = permutation_index(n - 1, rng)
    return [permute_price(p, index=idx) for p in prices]


def permute_series_within_groups(series: pd.Series, groups: pd.Series,
                                 rng: np.random.Generator) -> pd.Series:
    """Permute log returns INSIDE each group, never across them.

    The group is normally the trading day. Permuting a multi-year minute series
    as one block would move a bar from a 2019 session into a 2026 one and shuffle
    the level of the whole strip; permuting within the day keeps every day's open
    and close, its realised volatility and its news, and destroys only *when
    inside that day* each move happened.

    That is the right null for an intraday event study: it asks whether the
    minute the release landed in was special, holding the day itself fixed.
    """
    out = series.copy().astype(float)
    for _key, idx in series.groupby(groups).groups.items():
        chunk = series.loc[idx]
        if len(chunk) < 3:
            continue
        out.loc[idx] = permute_price(chunk, rng=rng).values
    return out


# ===========================================================================
# Multivariate (bar) permutations
# ===========================================================================
_OHLC = ("open", "high", "low", "close")


def permute_bars(ohlcv: pd.DataFrame,
                 rng: Optional[np.random.Generator] = None,
                 index_inter_bar: Optional[np.ndarray] = None,
                 index_intra_bar: Optional[np.ndarray] = None) -> pd.DataFrame:
    """Permute an OHLCV frame, keeping each bar's own shape intact.

    A bar carries two separable pieces of information and they are permuted with
    two different indices:

        intra-bar geometry   dH = H_t - O_t,  dL = L_t - O_t,  dC = C_t - O_t
        inter-bar jump       d_OC,t = O_{t+1} - C_t

    all in log space. Shuffling them together would manufacture bars whose high
    is below their open; shuffling them separately produces bars that are each
    a real bar that really occurred, reassembled in a different order.

    The first and last bar are held fixed, so the frame starts and ends where
    the original did.
    """
    missing = [c for c in _OHLC if c not in ohlcv.columns]
    if missing:
        raise ValueError(f"permute_bars needs columns {_OHLC}, missing {missing}")
    n = len(ohlcv)
    if n < 4:
        return ohlcv.copy()

    if index_inter_bar is None:
        if rng is None:
            raise ValueError("permute_bars needs either an rng or both permutation indices")
        index_inter_bar = permutation_index(n - 1, rng)
    if index_intra_bar is None:
        if rng is None:
            raise ValueError("permute_bars needs either an rng or both permutation indices")
        index_intra_bar = permutation_index(n - 2, rng)
    index_inter_bar = np.asarray(index_inter_bar, dtype=int)
    index_intra_bar = np.asarray(index_intra_bar, dtype=int)

    log_data = np.log(ohlcv[list(_OHLC)].astype(float))
    o = log_data["open"].to_numpy()
    h = log_data["high"].to_numpy()
    l = log_data["low"].to_numpy()
    c = log_data["close"].to_numpy()

    d_h, d_l, d_c = h - o, l - o, c - o
    # The interior bars are shuffled; the first bar is emitted verbatim and the
    # last keeps its own geometry, which is what pins both ends of the window.
    dh = np.concatenate((d_h[1:-1][index_intra_bar], [d_h[-1]]))
    dl = np.concatenate((d_l[1:-1][index_intra_bar], [d_l[-1]]))
    dc = np.concatenate((d_c[1:-1][index_intra_bar], [d_c[-1]]))

    inter = (o[1:] - c[:-1])[index_inter_bar]

    new_o = [o[0]]
    new_h = [h[0]]
    new_l = [l[0]]
    new_c = [c[0]]
    last_close = c[0]
    for i_dh, i_dl, i_dc, i_jump in zip(dh, dl, dc, inter):
        op = last_close + i_jump
        new_o.append(op)
        new_h.append(op + i_dh)
        new_l.append(op + i_dl)
        new_c.append(op + i_dc)
        last_close = op + i_dc

    out = pd.DataFrame({"open": new_o, "high": new_h, "low": new_l, "close": new_c},
                       index=ohlcv.index)
    out = np.exp(out)

    if "volume" in ohlcv.columns:
        v = ohlcv["volume"].to_numpy()
        out["volume"] = np.concatenate(([v[0]], v[1:-1][index_intra_bar], [v[-1]]))
    for col in ohlcv.columns:
        if col not in out.columns:
            out[col] = ohlcv[col].to_numpy()
    return out[list(ohlcv.columns)]


def permute_multi_bars(bars: Sequence[pd.DataFrame],
                       rng: np.random.Generator) -> List[pd.DataFrame]:
    """Permute several OHLCV frames together.

    Aligned frames share one pair of indices, which preserves cross-sectional
    co-movement. Frames with DIFFERENT lifespans -- a dynamic universe, where
    instruments list and delist -- are partitioned into maximally overlapping
    windows in which the alive set is constant, and each window is permuted
    independently. Without that, a shared index would have to be defined over
    dates on which some instruments do not exist.
    """
    if not bars:
        return []
    index_sets = [set(b.index) for b in bars]
    if all(s == index_sets[0] for s in index_sets):
        n = len(bars[0])
        if n < 4:
            return [b.copy() for b in bars]
        inter = permutation_index(n - 1, rng)
        intra = permutation_index(n - 2, rng)
        return [permute_bars(b, index_inter_bar=inter, index_intra_bar=intra) for b in bars]

    # --- dynamic universe -------------------------------------------------
    date_pool = sorted(set().union(*index_sets))
    alive_at = {d: frozenset(i for i, s in enumerate(index_sets) if d in s) for d in date_pool}

    partitions: List[List] = []
    partition_members: List[List[int]] = []
    current: List = [date_pool[0]]
    current_set = alive_at[date_pool[0]]
    for d in date_pool[1:]:
        if alive_at[d] == current_set:
            current.append(d)
        else:
            partitions.append(current)
            partition_members.append(sorted(current_set))
            current, current_set = [d], alive_at[d]
    partitions.append(current)
    partition_members.append(sorted(current_set))

    chunks: Dict[int, List[pd.DataFrame]] = defaultdict(list)
    for dates, members in zip(partitions, partition_members):
        if not members:
            continue
        sub = [bars[i].loc[dates] for i in members]
        permuted = permute_multi_bars(sub, rng) if len(dates) >= 4 else [s.copy() for s in sub]
        for i, frame in zip(members, permuted):
            chunks[i].append(frame)

    out: List[Optional[pd.DataFrame]] = [None] * len(bars)
    for i in range(len(bars)):
        out[i] = pd.concat(chunks[i], axis=0) if chunks[i] else bars[i].copy()
    return out  # type: ignore[return-value]

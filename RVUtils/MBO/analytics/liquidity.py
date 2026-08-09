"""What it costs to stand in front of this book, measured off the stored touch.

Three decisions are made here once, because nearly every mistake in this area is
one of the three.

**Anything that is a property of the book over time is weighted by seconds, never
by events.**  A top-of-book row is a *change*, so a state that flickered twice in
a millisecond contributes two rows and a wide state that stood for ten minutes
contributes one.  An event-weighted mean quoted spread is therefore not the
spread anyone faced; it is a summary of how often the touch was rewritten.  The
same argument applies to the median, which is why the median here is the smallest
*observed* spread whose cumulative time reaches half the window rather than the
middle row of the frame.  It is never an interpolation between two neighbours:
prices sit on a tick lattice, and the average of two adjacent ticks is a spread
the instrument could not have quoted.

**Every touch statistic shares one time base -- the seconds the book was
two-sided.**  A spread is undefined with a side missing, so it has no choice; the
depth numbers follow it so that one summary describes one set of states and its
spread and its depth can be read against each other.  The alternative, weighting
each side by the time that side alone was present, gives a truer census of
displayed size but produces numbers that pair with nothing.  ``two_sided_frac``
and ``seconds`` are reported precisely so the coverage of that base is visible: a
half-tick market that exists for 4% of the session is not a half-tick market.

**Prices stay in the instrument's own units.**  The frames from
:func:`RVUtils.MBO.store.reader.read_tob` are in whatever the instrument quotes
in, and so is everything returned here.  For SR3 that is the difference between
an outright quoting index points on a 0.005 tick and a calendar or butterfly
quoting basis points directly on a 0.5 tick -- so a ``tick`` argument must come
from the same convention as the frame (the catalogue's ``tick`` over 1e9, or
``ProductSpec.tick_for(kind)``).  Passing an outright's tick for a fly reports a
one-tick market as a hundred ticks wide, and nothing about the number looks
wrong.

Every function takes a **single instrument's** frames.  Averaging the front SR3
outright with a deferred one produces a plausible number describing no market, so
a frame carrying more than one symbol raises rather than pooling.
"""
from __future__ import annotations

from typing import Dict, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

__all__ = ["depth_profile", "liquidity_summary", "quoted_spread", "resilience"]

#: The clock. ``ts_recv`` is when the state became knowable to a taker, which is
#: the clock a cost measurement belongs on; ``ts_event`` is the matching engine's
#: own stamp and the two do not mean the same thing across Databento's 2026-08-08
#: CME normalization change (see ``store.schema``).
_CLOCK = "ts_recv"

_TOB_COLS = ("ts_recv", "bid_px", "ask_px", "spread", "bid_sz", "ask_sz",
             "bid_ct", "ask_ct")
_TRADE_COLS = ("ts_recv", "size", "aggressor", "prev_bid_sz", "prev_ask_sz")

#: Keys :func:`quoted_spread` always returns, in order.  Always all of them: a
#: caller assembling one row per instrument-day must not get a ragged frame
#: because one instrument happened to be silent.
_SPREAD_KEYS = (
    "n_states", "two_sided_frac", "spread_mean", "spread_median", "spread_ticks",
    "frac_time_one_tick", "bid_sz_at_touch", "ask_sz_at_touch", "orders_at_touch",
    "seconds",
)

_DEPTH_COLS = ("side", "mean", "median", "p25", "p75", "p95", "seconds")
_RESILIENCE_COLS = ("horizon_s", "n", "median_ratio", "mean_ratio",
                    "frac_recovered")


# --------------------------------------------------------------------------- #
# input contracts
# --------------------------------------------------------------------------- #

def _require(frame: pd.DataFrame, cols: Sequence[str], what: str, fix: str) -> None:
    """Raise naming the missing columns and the call that produces them."""
    missing = [c for c in cols if c not in frame.columns]
    if missing:
        raise ValueError(
            f"{what} is missing {missing}; {fix}"
        )


def _one_instrument(*frames: Optional[pd.DataFrame]) -> None:
    """Refuse frames that between them carry more than one symbol.

    Pooling two instruments here would silently average two different books --
    the front SR3 outright and a back one differ by more than any effect worth
    measuring -- and the result looks like an ordinary number.  A frame with no
    ``symbol`` column is accepted: a :class:`~RVUtils.MBO.book.ReplayResult`
    carries one instrument by construction and has no such column.
    """
    syms = set()
    for f in frames:
        if f is None or f.empty or "symbol" not in f.columns:
            continue
        syms.update(pd.unique(f["symbol"]).tolist())
    if len(syms) > 1:
        names = ", ".join(repr(s) for s in sorted(syms))
        raise ValueError(
            f"these frames carry {len(syms)} instruments ({names}); every "
            "function in this module describes one book, and pooling them would "
            "average two different markets. Read one at a time -- "
            "read_tob(root, product, dates, symbols=[sym])"
        )


def _session_bounds(session: Optional[Sequence]) -> Optional[Tuple[pd.Timestamp,
                                                                   pd.Timestamp]]:
    """``(lo, hi)`` as UTC timestamps, half open ``[lo, hi)``, or ``None``."""
    if session is None:
        return None
    if len(session) != 2:
        raise ValueError(
            f"session must be a (start, end) pair, got {len(session)} value(s)"
        )
    lo, hi = (pd.Timestamp(x) for x in session)
    lo = lo.tz_localize("UTC") if lo.tz is None else lo.tz_convert("UTC")
    hi = hi.tz_localize("UTC") if hi.tz is None else hi.tz_convert("UTC")
    if hi <= lo:
        raise ValueError(
            f"session end {hi} is not after its start {lo}; pass (start, end)"
        )
    return lo, hi


def _in_session(ts: pd.Series, bounds) -> np.ndarray:
    """``[lo, hi)`` -- half open, so two adjacent windows partition the day."""
    if bounds is None:
        return np.ones(len(ts), dtype=bool)
    lo, hi = bounds
    return ((ts >= lo) & (ts < hi)).to_numpy()


def _ordered(frame: pd.DataFrame) -> pd.DataFrame:
    """Time order, ties broken by ``sequence``.

    Sorting rather than trusting the caller because a negative time weight -- what
    an out-of-order row produces -- is silent and poisons every average in the
    module.  ``sequence`` breaks ties so that the state an as-of lookup lands on
    at a shared timestamp is the last one of that packet, deterministically.
    """
    by = [_CLOCK] + (["sequence"] if "sequence" in frame.columns else [])
    return frame.sort_values(by, kind="stable")


def _live_seconds(frame: pd.DataFrame, bounds) -> np.ndarray:
    """Seconds each state stood, the last one running to the session end.

    Without a session the final state weighs zero: it stood until something that
    is not in this frame, and inventing a duration for it would put the closing
    book's spread into the average with a weight nobody chose.

    Note what a mid-session window does *not* do: a state established before
    ``lo`` is filtered out, so the stretch from ``lo`` to the first in-window
    state carries no weight at all.  For a quiet instrument in a short window that
    can be most of the window, which is why ``seconds`` is returned alongside
    every average rather than left implicit.
    """
    ts = frame[_CLOCK].astype("int64").to_numpy()
    if ts.size == 0:
        return np.zeros(0, dtype=np.float64)
    stop = ts[-1] if bounds is None else np.int64(bounds[1].value)
    nxt = np.concatenate([ts[1:], [stop]])
    return (nxt - ts).astype(np.float64) / 1e9


def _weighted_mean(values: np.ndarray, weights: np.ndarray) -> float:
    tot = float(weights.sum())
    if tot <= 0.0:
        return float("nan")
    return float(np.dot(values, weights) / tot)


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    """The smallest observed value whose cumulative weight reaches ``q``.

    Observed, not interpolated, and that is the point rather than a shortcut.
    Sizes are whole lots and spreads sit on a tick lattice, so the interpolated
    quantile that :func:`numpy.quantile` returns is routinely a value the book
    could not have shown -- a depth of 7.5 lots, a spread of a third of a tick.
    """
    if values.size == 0:
        return float("nan")
    tot = float(weights.sum())
    if tot <= 0.0:
        return float("nan")
    order = np.argsort(values, kind="stable")
    v = values[order]
    c = np.cumsum(weights[order])
    k = int(np.searchsorted(c, q * c[-1], side="left"))
    return float(v[min(k, v.size - 1)])


# --------------------------------------------------------------------------- #
# quoted spread and depth
# --------------------------------------------------------------------------- #

def quoted_spread(
    tob: pd.DataFrame,
    session: Optional[Sequence] = None,
    tick: Optional[float] = None,
) -> Dict[str, Optional[float]]:
    """Time-weighted quoted spread and touch depth for one instrument.

    Returns, always with the same keys:

    ``n_states``
        Top-of-book changes inside the window.  A count of *rewrites*, not of
        distinct markets, and it moves with message rate rather than with
        liquidity -- which is why nothing else here is normalised by it.
    ``two_sided_frac``
        Share of live seconds with both sides present.  Read it before anything
        else: a one-tick market that exists for a twentieth of the session is not
        a one-tick market, and every other number below is conditioned on this.
    ``spread_mean``, ``spread_median``
        Time-weighted, over two-sided seconds, in the instrument's own price
        units.  The median is the smallest spread whose cumulative time reaches
        half of that, never an average of two lattice values.
    ``spread_ticks``
        ``spread_mean / tick``.  ``None`` when no ``tick`` is given, because the
        tick belongs to the instrument and guessing it from the data would report
        a quiet instrument's coarse print grid as its quoting grid.
    ``frac_time_one_tick``
        Share of *two-sided* seconds at exactly one tick.  Multiply by
        ``two_sided_frac`` for the share of the whole window.  ``None`` without a
        ``tick``.
    ``bid_sz_at_touch``, ``ask_sz_at_touch``, ``orders_at_touch``
        Time-weighted over the same two-sided seconds; ``orders_at_touch`` is the
        two sides' order counts added, the number of resting orders you would be
        queueing behind at the touch in total.
    ``seconds``
        Live seconds in the window, the denominator of ``two_sided_frac``.  Not
        the window's length: see :func:`_live_seconds` on what a mid-session
        window leaves out.

    An empty window returns the same keys with zero counts and NaN averages
    rather than a shorter dict, so a frame built from many instrument-days has
    one shape.
    """
    _one_instrument(tob)
    if tick is not None and not (float(tick) > 0.0):
        raise ValueError(
            f"tick must be positive, got {tick!r}; pass the instrument's own tick "
            "in the same units as the frame's prices (catalogue tick / 1e9, or "
            "ProductSpec.tick_for(kind)), or None to omit the tick statistics"
        )
    empty: Dict[str, Optional[float]] = {
        "n_states": 0, "two_sided_frac": 0.0, "spread_mean": float("nan"),
        "spread_median": float("nan"),
        "spread_ticks": None if tick is None else float("nan"),
        "frac_time_one_tick": None if tick is None else float("nan"),
        "bid_sz_at_touch": float("nan"), "ask_sz_at_touch": float("nan"),
        "orders_at_touch": float("nan"), "seconds": 0.0,
    }
    if tob.empty:
        return empty
    _require(tob, _TOB_COLS, "tob",
             "read_tob(..., decode=True) produces the decoded price columns; a "
             "frame read with decode=False carries tick indices instead")

    bounds = _session_bounds(session)
    t = _ordered(tob)
    t = t[_in_session(t[_CLOCK], bounds)]
    if t.empty:
        return empty

    w = _live_seconds(t, bounds)
    sp = t["spread"].to_numpy(dtype=np.float64)
    two = np.isfinite(sp)
    wt = w * two
    tot = float(wt.sum())

    out: Dict[str, Optional[float]] = dict(empty)
    out["n_states"] = int(len(t))
    out["seconds"] = float(w.sum())
    out["two_sided_frac"] = float(tot / w.sum()) if w.sum() > 0 else 0.0
    if tot <= 0.0:
        return out

    sp_two, w_two = sp[two], w[two]
    out["spread_mean"] = _weighted_mean(sp_two, w_two)
    out["spread_median"] = _weighted_quantile(sp_two, w_two, 0.5)
    out["bid_sz_at_touch"] = _weighted_mean(
        t["bid_sz"].to_numpy(dtype=np.float64), wt)
    out["ask_sz_at_touch"] = _weighted_mean(
        t["ask_sz"].to_numpy(dtype=np.float64), wt)
    out["orders_at_touch"] = _weighted_mean(
        t["bid_ct"].to_numpy(dtype=np.float64)
        + t["ask_ct"].to_numpy(dtype=np.float64), wt)
    if tick is not None:
        tk = float(tick)
        out["spread_ticks"] = float(out["spread_mean"]) / tk
        # A tolerance is unavoidable and small: prices arrive decoded to float64
        # from integer tick indices, and SR3's 0.005 has no exact binary
        # representation, so "is this one tick" cannot be an equality on floats.
        # A millionth of a tick is far above the arithmetic's error and far below
        # anything the lattice can confuse it with.
        at_one = np.isclose(sp_two, tk, rtol=0.0, atol=tk * 1e-6)
        out["frac_time_one_tick"] = float(w_two[at_one].sum() / tot)
    return out


def depth_profile(
    tob: pd.DataFrame,
    session: Optional[Sequence] = None,
) -> pd.DataFrame:
    """Time-weighted distribution of size at the touch, one row per side.

    Columns: ``side``, ``mean``, ``median``, ``p25``, ``p75``, ``p95``,
    ``seconds``.  The quantiles are weighted by the seconds each state stood and
    are observed sizes rather than interpolations, so ``p95`` names a quantity
    that was really displayed and can be compared with an order you would send.

    The weighting base is the two-sided seconds used everywhere in this module,
    and ``seconds`` reports it so a side that was rarely quoted cannot be read as
    a thin one.  Mean and quantiles disagree hard in a healthy book -- one large
    resting order carries the mean while the median sits on the ordinary state --
    and that gap is the reason both are here.
    """
    _one_instrument(tob)
    empty = pd.DataFrame({
        "side": pd.Series(dtype="object"),
        **{c: pd.Series(dtype="float64") for c in _DEPTH_COLS[1:]},
    })
    if tob.empty:
        return empty
    _require(tob, _TOB_COLS, "tob",
             "read_tob(..., decode=True) produces the decoded price columns")

    bounds = _session_bounds(session)
    t = _ordered(tob)
    t = t[_in_session(t[_CLOCK], bounds)]
    if t.empty:
        return empty

    w = _live_seconds(t, bounds)
    two = np.isfinite(t["spread"].to_numpy(dtype=np.float64))
    wt = w[two]
    if wt.sum() <= 0.0:
        return empty

    rows = []
    for side, col in (("bid", "bid_sz"), ("ask", "ask_sz")):
        v = t[col].to_numpy(dtype=np.float64)[two]
        rows.append({
            "side": side,
            "mean": _weighted_mean(v, wt),
            "median": _weighted_quantile(v, wt, 0.50),
            "p25": _weighted_quantile(v, wt, 0.25),
            "p75": _weighted_quantile(v, wt, 0.75),
            "p95": _weighted_quantile(v, wt, 0.95),
            "seconds": float(wt.sum()),
        })
    return pd.DataFrame(rows, columns=list(_DEPTH_COLS))


# --------------------------------------------------------------------------- #
# resilience
# --------------------------------------------------------------------------- #

def resilience(
    tob: pd.DataFrame,
    trades: pd.DataFrame,
    horizons_s: Sequence[float] = (1.0, 5.0, 30.0),
    session: Optional[Sequence] = None,
) -> pd.DataFrame:
    """How fast displayed size at the touch returns after a trade consumes it.

    For each print, the size on the side that was hit immediately before the
    trade -- ``prev_ask_sz`` for a buy-initiated trade, ``prev_bid_sz`` for a
    sell-initiated one, both taken from the book strictly before the trade's own
    packet as the store recorded it -- against the size on that same side at
    ``t + h``.  One row per horizon: ``horizon_s``, ``n``, ``median_ratio``,
    ``mean_ratio``, ``frac_recovered`` (ratio at least 1).

    Four choices worth knowing about:

    * **The after-size is the size at the touch wherever the touch then is**, not
      the size still resting at the price the trade took.  The alternative
      measures level refill, which reads zero whenever the market simply moved,
      and so scores a clean repricing as a total failure to replenish.
    * **The horizon point must fall strictly inside the observation window**,
      which ends at ``session[1]`` or, without a session, at the last state in
      ``tob``.  Trades whose horizon lands beyond it are dropped from that
      horizon's row -- hence ``n`` per horizon rather than once.  Without this the
      thirty-second row reads the closing state for every late trade and scores it
      as full recovery.
    * **The lookup at ``t + h`` includes a state stamped exactly ``t + h``**,
      because a top-of-book row is the book from its timestamp onward.  That is
      the opposite of the strict join the store used to attach the *previous*
      book, and both are right: one asks what stood before a packet, this one asks
      what stands at an instant.
    * **Prints, not events.**  A sweep that takes three orders prints three trades
      sharing one previous book, and each is a row -- so ``n`` counts prints, and
      a heavily swept instrument weighs its sweeps accordingly.

    Trades with an unknown aggressor, and trades whose hit side showed nothing
    before them, are excluded: neither has a ratio, and a zero denominator would
    otherwise arrive as an infinity that a mean would happily propagate.  The
    ratios are averaged across trades, not across time -- each is a property of
    one event, not of the book over an interval.

    An empty ``tob`` or ``trades`` returns an empty typed frame; otherwise every
    horizon gets a row, with ``n = 0`` and NaN statistics where nothing qualified.
    """
    _one_instrument(tob, trades)
    empty = pd.DataFrame({
        "horizon_s": pd.Series(dtype="float64"),
        "n": pd.Series(dtype="int64"),
        **{c: pd.Series(dtype="float64") for c in _RESILIENCE_COLS[2:]},
    })
    if tob.empty or trades.empty:
        return empty
    _require(tob, _TOB_COLS, "tob", "read_tob(..., decode=True) produces them")
    _require(trades, _TRADE_COLS, "trades",
             "read_trades(..., decode=True) carries the previous book on each "
             "print, so nothing needs joining to get it")

    bounds = _session_bounds(session)
    book = _ordered(tob)
    book = book[_in_session(book[_CLOCK], bounds)]
    if book.empty:
        return empty
    end = book[_CLOCK].iloc[-1] if bounds is None else bounds[1]

    t = _ordered(trades)
    t = t[_in_session(t[_CLOCK], bounds)]
    if t.empty:
        return empty

    agg = t["aggressor"].to_numpy(dtype=np.int64)
    hit_ask = agg > 0
    before = np.where(hit_ask,
                      t["prev_ask_sz"].to_numpy(dtype=np.float64),
                      t["prev_bid_sz"].to_numpy(dtype=np.float64))
    usable = (agg != 0) & (before > 0)

    ts = t[_CLOCK]
    book_sz = book[[_CLOCK, "bid_sz", "ask_sz"]].reset_index(drop=True)

    rows = []
    for h in horizons_s:
        hs = float(h)
        target = (ts + pd.Timedelta(seconds=hs)).reset_index(drop=True)
        m = pd.merge_asof(
            pd.DataFrame({_CLOCK: target}),
            book_sz, on=_CLOCK, direction="backward", allow_exact_matches=True,
        )
        after = np.where(hit_ask,
                         m["ask_sz"].to_numpy(dtype=np.float64),
                         m["bid_sz"].to_numpy(dtype=np.float64))
        keep = usable & (target < end).to_numpy() & np.isfinite(after)
        ratio = after[keep] / before[keep]
        rows.append({
            "horizon_s": hs,
            "n": int(ratio.size),
            "median_ratio": float(np.median(ratio)) if ratio.size else float("nan"),
            "mean_ratio": float(np.mean(ratio)) if ratio.size else float("nan"),
            "frac_recovered": (float(np.mean(ratio >= 1.0)) if ratio.size
                               else float("nan")),
        })
    out = pd.DataFrame(rows, columns=list(_RESILIENCE_COLS))
    out["n"] = out["n"].astype("int64")
    return out


# --------------------------------------------------------------------------- #
# one flat summary
# --------------------------------------------------------------------------- #

def liquidity_summary(
    tob: pd.DataFrame,
    trades: pd.DataFrame,
    session: Optional[Sequence] = None,
    tick: Optional[float] = None,
) -> Dict[str, Optional[float]]:
    """:func:`quoted_spread` plus what actually traded, as one flat dict.

    Adds ``n_trades``, ``volume``, ``buy_volume``, ``sell_volume`` and
    ``mean_trade_size`` over the same window.  The buy/sell split is *exact*, not
    inferred: MBO carries the aggressing side, so no tick rule or Lee-Ready proxy
    is involved and their misclassification error is simply absent.  Prints whose
    aggressor is unknown count in ``volume`` and in neither side, so the two sides
    need not add up to the total and a gap between them is information rather than
    a bug.

    Flat and one instrument on purpose: this is the row you put in a frame with
    one row per instrument-day, next to the same row for the structure you would
    otherwise leg.  No rate is derived from ``seconds`` here -- a window whose
    live seconds are a fraction of its length (see :func:`_live_seconds`) would
    turn a thin instrument into a busy one on division.
    """
    _one_instrument(tob, trades)
    out = dict(quoted_spread(tob, session=session, tick=tick))

    bounds = _session_bounds(session)
    if trades.empty:
        t = trades
    else:
        _require(trades, ("ts_recv", "size", "aggressor"), "trades",
                 "read_trades(...) produces them")
        t = trades[_in_session(trades[_CLOCK], bounds)]

    if len(t) == 0:
        out.update({"n_trades": 0, "volume": 0, "buy_volume": 0, "sell_volume": 0,
                    "mean_trade_size": float("nan")})
        return out

    sz = t["size"].to_numpy(dtype=np.int64)
    agg = t["aggressor"].to_numpy(dtype=np.int64)
    out.update({
        "n_trades": int(sz.size),
        "volume": int(sz.sum()),
        "buy_volume": int(sz[agg > 0].sum()),
        "sell_volume": int(sz[agg < 0].sum()),
        "mean_trade_size": float(sz.mean()),
    })
    return out

"""Order flow at the touch: Cont-Kukanov-Stoikov OFI, and signed trade flow.

Two different things are measured here and the difference is the whole point.

**Order-flow imbalance** is a property of the *book*.  Every top-of-book change
contributes a signed quantity of lots: size that arrived on the bid, or left the
ask, is positive pressure.  It counts limit orders, cancellations and executions
together, because the book cannot tell them apart -- and neither can this
measure.  Cont, Kukanov and Stoikov say so explicitly (arXiv:1011.6402v3, p.4):
*a market sell order and a cancelled bid of the same size produce exactly the
same* ``e_n``.  OFI is therefore net pressure at the touch, not trading.

**Trade flow** is a property of the *tape*, and on MBO data it is exact.  The
aggressor side is carried by the exchange, so nothing here classifies anything:
no Lee-Ready, no tick rule, and none of their misclassification error.  Those
proxies exist because most datasets do not carry the field this one does.

Together they answer a question neither answers alone: how much of the pressure
that moves the price is trades, and how much is quoting.

**Units.**  OFI and every volume column are in *lots*.  ``mid``, ``d_mid`` and
anything derived from a price stay in the instrument's own price units, which
are index points for an SR3 outright or a bundle and basis points for every
differential instrument (see :mod:`RVUtils.MBO.products`).  That asymmetry is
deliberate: a correlation is unit-free, so :func:`flow_summary` is safe to read
across instruments, but a regression *coefficient* of ``d_mid`` on ``ofi`` is
not, and multiplying it by the wrong ``bp_per_unit`` is the classic hundredfold
error in this repo.  Convert before comparing coefficients, not after.

**Why nothing here is time-weighted.**  The quoted spread and the depth at the
touch are states, and averaging them over events rather than over time
over-counts what flickers; that is why :mod:`RVUtils.MBO.metrics` time-weights
them.  OFI and signed volume are *flows*: each event contributes a quantity of
lots that arrived or left, so a bar sums them and a longer-lived state has
already had its say by not generating events.  Time-weighting a flow would
double-count duration.
"""
from __future__ import annotations

from typing import Dict, Mapping, Sequence, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "flow_summary",
    "ofi_bars",
    "ofi_events",
    "trade_flow",
    "trade_sign_autocorrelation",
]

#: What :func:`RVUtils.MBO.store.reader.read_tob` serves and this module needs.
_TOB_COLS = ("symbol", "ts_recv", "sequence", "date",
             "bid_px", "bid_sz", "ask_px", "ask_sz", "mid")
_TRADE_COLS = ("symbol", "ts_recv", "sequence", "date", "size", "aggressor")

_OFI_BAR_DTYPES = {"ofi": "float64", "n_events": "int64", "mid_first": "float64",
                   "mid_last": "float64", "d_mid": "float64"}
_TRADE_BAR_DTYPES = {"signed_volume": "int64", "buy_volume": "int64",
                     "sell_volume": "int64", "n_trades": "int64",
                     "buy_trades": "int64", "sell_trades": "int64",
                     "signed_trade_imbalance": "int64"}


# --------------------------------------------------------------------------- #
# input contract
# --------------------------------------------------------------------------- #

def _require(frame: pd.DataFrame, cols: Sequence[str], what: str) -> None:
    """Fail on a missing column by name, rather than deeper and less legibly."""
    missing = [c for c in cols if c not in frame.columns]
    if missing:
        raise ValueError(
            f"{what} is missing {missing}; this module consumes the frame the "
            f"store reader returns. Call read_{what}(root, product, dates, "
            f"symbols=[sym]) and pass the result unmodified, or re-add the "
            f"columns if you sliced them off."
        )


def _single_symbol(frame: pd.DataFrame, what: str) -> str:
    """The one symbol in ``frame``, or a ValueError naming how to get to one.

    Order flow is a property of one book.  Summing OFI across two instruments
    produces a number with no interpretation at all, and because both frames
    concatenate cleanly nothing downstream would look wrong.
    """
    if "symbol" not in frame.columns:
        raise ValueError(f"{what} has no 'symbol' column, so it cannot be checked "
                         f"for holding a single instrument")
    syms = sorted(set(frame["symbol"].astype(str)))
    if len(syms) != 1:
        raise ValueError(
            f"{what} carries {len(syms)} instruments {syms[:5]}; order flow is a "
            f"property of one book. Pass symbols=[one_symbol] to the reader, or "
            f"call this once per instrument and concatenate the results."
        )
    return syms[0]


def _aggressor(trades: pd.DataFrame) -> np.ndarray:
    """The aggressor column as int64 in ``{-1, 0, +1}``, validated.

    The trap this catches is a frame from the wrong layer.  A raw
    :class:`~RVUtils.MBO.book.ReplayResult` carries ``'B'``/``'A'`` strings and
    the store writer is what maps them to ``+1``/``-1``; multiplying a size by a
    string does not fail in any way a reader would recognise, so the type is
    checked before it is used.
    """
    a = trades["aggressor"].to_numpy()
    if a.dtype.kind not in "iub":
        raise ValueError(
            "trades['aggressor'] is not integral. read_trades serves +1 (buy "
            "initiated), -1 (sell initiated) and 0 (unknown); a raw "
            "ReplayResult.trades frame instead carries 'B'/'A' strings. Pass the "
            "frame read_trades returned, or map B -> +1 and A -> -1 first."
        )
    a = a.astype(np.int64)
    bad = np.setdiff1d(np.unique(a), np.array([-1, 0, 1], dtype=np.int64))
    if bad.size:
        raise ValueError(
            f"trades['aggressor'] holds {bad.tolist()}; only +1, -1 and 0 have a "
            f"meaning. A side encoded any other way must be mapped before it is "
            f"used as a sign."
        )
    return a


def _ordered(frame: pd.DataFrame, cols: Sequence[str]) -> pd.DataFrame:
    """Sorted by session then arrival, because every measure here is a difference.

    Sorted on ``date`` first and only then on ``ts_recv``: a CME session crosses
    UTC midnight, so the store's session date is the outer key and wall-clock
    time alone would interleave two sessions if a caller ever asked for dates out
    of order.  ``sequence`` breaks the tie inside a packet-stamped nanosecond.
    """
    return frame.sort_values(list(cols), kind="stable").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# order-flow imbalance
# --------------------------------------------------------------------------- #

def _events(tob: pd.DataFrame) -> pd.DataFrame:
    """``date, ts_recv, mid, ofi`` for the two-sided states, in order.

    Shared by :func:`ofi_events` and :func:`ofi_bars` so that the bars cannot
    drift from the series they are the sum of.
    """
    _require(tob, _TOB_COLS, "tob")
    empty = pd.DataFrame({
        "date": pd.Series(dtype="object"),
        "ts_recv": pd.Series(dtype="datetime64[ns, UTC]"),
        "mid": pd.Series(dtype="float64"),
        "ofi": pd.Series(dtype="float64"),
    })
    if len(tob) == 0:
        return empty
    _single_symbol(tob, "tob")

    t = _ordered(tob, ("date", "ts_recv", "sequence"))
    live = (np.isfinite(t["bid_px"].to_numpy(dtype=np.float64))
            & np.isfinite(t["ask_px"].to_numpy(dtype=np.float64)))
    t = t.loc[live].reset_index(drop=True)
    if t.empty:
        return empty

    pb = t["bid_px"].to_numpy(dtype=np.float64)
    qb = t["bid_sz"].to_numpy(dtype=np.float64)
    pa = t["ask_px"].to_numpy(dtype=np.float64)
    qa = t["ask_sz"].to_numpy(dtype=np.float64)

    e = np.zeros(len(t), dtype=np.float64)
    if len(t) > 1:
        # Both indicators fire on equality, and that is the definition, not an
        # oversight: with the price unchanged the bid contributes q_n - q_{n-1}.
        e[1:] = (
            (pb[1:] >= pb[:-1]) * qb[1:] - (pb[1:] <= pb[:-1]) * qb[:-1]
            - (pa[1:] <= pa[:-1]) * qa[1:] + (pa[1:] >= pa[:-1]) * qa[:-1]
        )
        d = t["date"].to_numpy()
        e[1:] = np.where(d[1:] == d[:-1], e[1:], 0.0)

    return pd.DataFrame({"date": t["date"], "ts_recv": t["ts_recv"],
                         "mid": t["mid"].astype(np.float64), "ofi": e})


def ofi_events(tob: pd.DataFrame) -> pd.Series:
    """Per-event order-flow imbalance, in lots, indexed by ``ts_recv``.

    The Cont-Kukanov-Stoikov definition, reproduced from arXiv:1011.6402v3 p.4::

        e_n =  I{P_bid_n >= P_bid_{n-1}} * q_bid_n
             - I{P_bid_n <= P_bid_{n-1}} * q_bid_{n-1}
             - I{P_ask_n <= P_ask_{n-1}} * q_ask_n
             + I{P_ask_n >= P_ask_{n-1}} * q_ask_{n-1}

    **Both indicators fire on equality.**  An unchanged bid price with a changed
    bid size therefore contributes exactly ``q_n - q_{n-1}``, and the mirror on
    the ask.  Writing ``>`` and ``<`` instead reads as the obvious "improved,
    worsened, otherwise nothing" and is the classic error: it deletes every
    queue build and every queue pull at a standing price, which on a tick-bound
    contract like SR3 is most of what happens.  A price that does not move is
    the normal case, not the boundary case.

    **What this cannot see.**  CKS state it themselves: a market sell and a
    cancelled bid of the same size are indistinguishable to ``e_n``.  Both take
    the same number of lots off the bid and both produce the same number.  If you
    need the split, that is what :func:`trade_flow` is for -- the tape carries
    the true aggressor, so the traded part is exactly known and the residual is
    quoting.

    **One-sided states are dropped, so this can be shorter than ``tob``.**  A
    state with an empty side has no ``P`` and no ``q`` on that side, and the
    float comparisons against NaN are all false, which would silently contribute
    zero in both directions.  Consecutive here therefore means consecutive
    *two-sided* states, and that is the accurate choice rather than the
    convenient one.  Worked example: bid 10 @ 96.00 with ask 7 @ 96.01, then the
    ask is pulled entirely, then an ask of 3 returns at 96.01.  Comparing the two
    two-sided states gives ``-(3 - 7) = +4`` -- the ask queue is four lots
    thinner, which is upward pressure and is what happened.  Keeping the empty
    state in the sequence gives 0 for the pull and 0 for the return, and the
    whole episode disappears.

    The first event of each session emits 0: it has no predecessor, and pairing
    it with the previous session's close would score a whole overnight gap as one
    burst of flow.
    """
    ev = _events(tob)
    return pd.Series(
        ev["ofi"].to_numpy(dtype=np.float64),
        index=pd.DatetimeIndex(ev["ts_recv"], name="ts_recv"),
        name="ofi",
    )


# --------------------------------------------------------------------------- #
# the bar grid
# --------------------------------------------------------------------------- #

def _on_bar_grid(frame: pd.DataFrame, freq: str,
                 aggs: Mapping[str, Tuple[str, str]]) -> pd.DataFrame:
    """Aggregate onto a regular ``freq`` grid, one grid per session.

    Bins come from ``dt.floor``, not from ``resample``, and the difference
    matters twice.  ``floor`` refuses a non-fixed frequency ("ME", "W") outright
    instead of quietly producing month bars for something asked for in seconds.
    And the grid is rebuilt per session from that session's own first and last
    event, so an overnight gap produces no bars at all rather than the 8,640
    empty ten-second bars a naive resample would put between two sessions.

    Bars inside a session with no events are kept, with the aggregation NaN for
    the caller to fill.  They are real observations: nothing happened.
    """
    b = frame.assign(_bin=frame["ts_recv"].dt.floor(freq))
    agg = b.groupby(["date", "_bin"], sort=True).agg(**dict(aggs))

    spans = b.groupby("date", sort=True)["_bin"].agg(["min", "max"])
    ranges = [pd.date_range(lo, hi, freq=freq)
              for lo, hi in zip(spans["min"], spans["max"])]
    stamps = ranges[0].append(ranges[1:]) if len(ranges) > 1 else ranges[0]
    keys = np.repeat(np.asarray(list(spans.index), dtype=object),
                     [len(r) for r in ranges])
    full = pd.MultiIndex.from_arrays([keys, stamps], names=["date", "_bin"])
    return agg.reindex(full)


def _drop_session_level(bars: pd.DataFrame) -> pd.DataFrame:
    out = bars.droplevel(0)
    out.index.name = "ts_recv"
    return out


def _empty_bars(dtypes: Mapping[str, str]) -> pd.DataFrame:
    return pd.DataFrame(
        {c: pd.Series(dtype=d) for c, d in dtypes.items()},
        index=pd.DatetimeIndex([], tz="UTC", name="ts_recv"),
    )


def ofi_bars(tob: pd.DataFrame, freq: str = "10s") -> pd.DataFrame:
    """OFI summed over bars, with the mid change over the same bars.

    CKS aggregate ``e_n`` by plain sum over an interval and regress the mid-price
    change on the result; their ``Delta t`` is 10 s, hence the default here.

    Columns: ``ofi``, ``n_events``, ``mid_first``, ``mid_last``, ``d_mid``.

    **``d_mid`` is not ``mid_last - mid_first``**, and the difference is worth
    the paragraph.  CKS pair the flow in a bar with the change in the mid from
    the *end of the previous bar* to the end of this one, and that is what is
    computed: ``ffill(mid_last).diff()`` within each session.  The obvious
    within-bar reading is identically zero for any bar holding a single event,
    because that event supplies both the first and the last mid -- so it throws
    away precisely the price move that the bar's own flow caused, and it does so
    hardest where bars are sparse, which is where the signal is largest.  The
    forward fill is what makes an empty bar honest: no event means the prevailing
    mid did not change, so ``d_mid`` is 0.

    ``mid_first`` and ``mid_last`` are NaN in an empty bar while ``d_mid`` is 0.
    That is not an inconsistency: the first two report events, of which there
    were none, and the third reports the book, which stood still.

    ``n_events`` counts two-sided top-of-book states, which is what OFI is
    defined over -- see :func:`ofi_events` on why one-sided states are dropped.
    The first bar of each session has ``d_mid`` NaN: there is no previous bar in
    that session, and reaching into the previous one would price an overnight
    gap as a bar move.
    """
    ev = _events(tob)
    if ev.empty:
        return _empty_bars(_OFI_BAR_DTYPES)

    bars = _on_bar_grid(ev, freq, {
        "ofi": ("ofi", "sum"),
        "n_events": ("ofi", "size"),
        "mid_first": ("mid", "first"),
        "mid_last": ("mid", "last"),
    })
    bars["ofi"] = bars["ofi"].fillna(0.0).astype(np.float64)
    bars["n_events"] = bars["n_events"].fillna(0).astype(np.int64)
    prevailing = bars["mid_last"].groupby(level=0).ffill()
    bars["d_mid"] = prevailing.groupby(level=0).diff()
    return _drop_session_level(bars)[list(_OFI_BAR_DTYPES)]


# --------------------------------------------------------------------------- #
# trade flow
# --------------------------------------------------------------------------- #

def trade_flow(trades: pd.DataFrame, freq: str = "10s") -> pd.DataFrame:
    """Signed trade flow per bar, in lots, from the true aggressor side.

    MBO carries which side initiated, so nothing here is inferred.  Lee-Ready and
    the tick rule exist to guess this field from quote and trade prices when it
    is absent; both misclassify a few percent of prints, worst around the events
    that matter most, and none of that error is present in these columns.  If you
    ever find yourself reaching for a sign proxy on this data, the field is
    already there.

    Columns: ``signed_volume``, ``buy_volume``, ``sell_volume``, ``n_trades``,
    ``buy_trades``, ``sell_trades``, ``signed_trade_imbalance``.

    ``signed_trade_imbalance`` is CKS's ``TI`` -- buy size minus sell size -- and
    is kept under their name so that a regression written from the paper reads
    literally.  It equals ``signed_volume`` by construction, since a validated
    aggressor is +1, -1 or 0; the two columns are both here because the paper's
    name and the natural name are different, and if they ever disagree the
    aggressor column is carrying something it should not.

    A trade with ``aggressor == 0`` counts in ``n_trades`` and in neither
    ``buy_*`` nor ``sell_*``.  Unknown is not neutral, and splitting it or
    dropping it would both be inventions; leaving it visible in the count lets a
    caller see how much of the tape is unattributed.

    Bars are per session, regular at ``freq``, and zero-filled where no trade
    printed -- a quiet bar traded nothing, which is a measurement rather than a
    gap.
    """
    _require(trades, _TRADE_COLS, "trades")
    if len(trades) == 0:
        return _empty_bars(_TRADE_BAR_DTYPES)
    _single_symbol(trades, "trades")

    t = _ordered(trades, ("date", "ts_recv", "sequence"))
    a = _aggressor(t)
    size = t["size"].to_numpy(dtype=np.int64)
    zero = np.zeros(len(t), dtype=np.int64)

    frame = pd.DataFrame({
        "date": t["date"],
        "ts_recv": t["ts_recv"],
        "_signed": a * size,
        "_buy": np.where(a > 0, size, zero),
        "_sell": np.where(a < 0, size, zero),
        "_is_buy": (a > 0).astype(np.int64),
        "_is_sell": (a < 0).astype(np.int64),
        "_one": np.ones(len(t), dtype=np.int64),
    })
    bars = _on_bar_grid(frame, freq, {
        "signed_volume": ("_signed", "sum"),
        "buy_volume": ("_buy", "sum"),
        "sell_volume": ("_sell", "sum"),
        "n_trades": ("_one", "sum"),
        "buy_trades": ("_is_buy", "sum"),
        "sell_trades": ("_is_sell", "sum"),
    })
    for col in ("signed_volume", "buy_volume", "sell_volume", "n_trades",
                "buy_trades", "sell_trades"):
        bars[col] = bars[col].fillna(0).astype(np.int64)
    bars["signed_trade_imbalance"] = bars["buy_volume"] - bars["sell_volume"]
    return _drop_session_level(bars)[list(_TRADE_BAR_DTYPES)]


def trade_sign_autocorrelation(trades: pd.DataFrame,
                               max_lag: int = 20) -> pd.DataFrame:
    """Autocorrelation of the aggressor sign sequence, in trade time.

    Trade time, not clock time: lag 1 is the next trade, whether it came a
    millisecond or a minute later.  Sign persistence is a property of how orders
    are split and followed, and resampling it onto a clock would measure the
    arrival rate as much as the persistence.

    Columns: ``lag`` (1..``max_lag``), ``autocorr``, ``n`` (the number of pairs
    the estimate is built from).

    The estimator is the classic one: a single sample mean and a single
    denominator ``sum (s_t - s_bar)^2`` over the whole sequence, with the
    numerator summed over the overlapping pairs.  Recomputing the mean and the
    variance on each shifted window instead -- an ordinary Pearson correlation of
    ``s[:-k]`` against ``s[k:]`` -- looks more careful and is worse: the result
    is no longer a positive semi-definite function of the lag, so it can wander
    outside anything an autocovariance is allowed to be as the overlap shrinks.

    Trades with ``aggressor == 0`` are removed before the sequence is formed.  A
    zero is "unknown", not "neutral", and leaving it in would do two bad things:
    dilute the variance, and -- much worse -- insert a phantom element between
    two genuinely adjacent trades, which shifts every lag past it.

    Pairs that straddle a session boundary are excluded from the numerator and
    from ``n``.  The last trade of one session and the first of the next are
    adjacent in trade time but not in any sense the measure is about.

    ``autocorr`` is NaN with ``n`` 0 for a lag longer than the sequence, and NaN
    where the sequence is constant, rather than the 0 that ``0/0`` would produce
    if it were allowed through.
    """
    max_lag = int(max_lag)
    if max_lag < 1:
        raise ValueError(f"max_lag must be at least 1, got {max_lag}; lag 0 is 1 "
                         f"by definition and carries no information")
    _require(trades, _TRADE_COLS, "trades")
    empty = pd.DataFrame({"lag": pd.Series(dtype="int64"),
                          "autocorr": pd.Series(dtype="float64"),
                          "n": pd.Series(dtype="int64")})
    if len(trades) == 0:
        return empty
    _single_symbol(trades, "trades")

    t = _ordered(trades, ("date", "ts_recv", "sequence"))
    a = _aggressor(t)
    signed = a != 0
    s = a[signed].astype(np.float64)
    dates = t["date"].to_numpy()[signed]

    lags = np.arange(1, max_lag + 1, dtype=np.int64)
    ac = np.full(max_lag, np.nan, dtype=np.float64)
    counts = np.zeros(max_lag, dtype=np.int64)

    n_obs = s.size
    if n_obs:
        dev = s - s.mean()
        denom = float(dev @ dev)
        for i, k in enumerate(lags):
            if k >= n_obs:
                continue
            same = dates[k:] == dates[:-k]
            counts[i] = int(same.sum())
            if counts[i] and denom > 0.0:
                ac[i] = float((dev[:-k] * dev[k:])[same].sum()) / denom

    return pd.DataFrame({"lag": lags, "autocorr": ac, "n": counts})


# --------------------------------------------------------------------------- #
# the two together
# --------------------------------------------------------------------------- #

def _corr(x: pd.Series, y: pd.Series) -> float:
    """Pearson correlation over the bars where both are observed.

    Guarded rather than handed straight to pandas.  A flow column that never
    moves is an ordinary outcome -- a session with quotes but no prints leaves TI
    a constant zero -- and a zero denominator makes numpy emit a runtime warning
    on its way to the NaN.  The NaN is the right answer; the warning is noise
    that would fail a suite run under ``-W error``.
    """
    a = x.to_numpy(dtype=np.float64)
    b = y.to_numpy(dtype=np.float64)
    both = np.isfinite(a) & np.isfinite(b)
    a, b = a[both], b[both]
    if a.size < 2 or a.std() == 0.0 or b.std() == 0.0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def flow_summary(tob: pd.DataFrame, trades: pd.DataFrame,
                 freq: str = "10s") -> Dict[str, float]:
    """OFI and trade flow on one bar grid, each against the same bar's mid change.

    Keys: ``n_bars``, ``corr_ofi_dmid``, ``corr_ti_dmid``, ``ofi_total``,
    ``signed_volume_total``.

    The two correlations are the headline of the CKS result and the reason both
    measures are in one module: OFI usually explains a large share of the
    contemporaneous mid change, and signed trade volume alone explains markedly
    less, because most of the pressure on the touch is quoting rather than
    trading.  Reading only ``corr_ti_dmid`` is how a book gets called
    uninformative when it is merely not being traded.

    Correlations, not regression slopes, because ``ofi`` is in lots and ``d_mid``
    is in the instrument's own price units: a slope would need the instrument's
    ``bp_per_unit`` before it could be compared with another instrument's, and a
    correlation needs nothing.

    The two frames are joined on the union of their bar grids.  A bar with no
    quote change and no print contributes 0 to both flows; a bar outside the
    top-of-book span leaves ``d_mid`` NaN and drops out of the correlations
    pairwise rather than being filled with a fabricated zero move.

    Raises if ``tob`` and ``trades`` describe different instruments.  They
    concatenate and correlate perfectly happily, and the number means nothing.
    """
    tob_sym = _single_symbol(tob, "tob") if len(tob) else None
    trade_sym = _single_symbol(trades, "trades") if len(trades) else None
    if tob_sym is not None and trade_sym is not None and tob_sym != trade_sym:
        raise ValueError(
            f"tob is {tob_sym} but trades is {trade_sym}; correlating one "
            f"instrument's book pressure with another's tape is not a measure of "
            f"anything. Read both with symbols=[{tob_sym!r}]."
        )

    quotes = ofi_bars(tob, freq)
    tape = trade_flow(trades, freq)
    idx = quotes.index.union(tape.index)
    q = quotes.reindex(idx)
    p = tape.reindex(idx)

    ofi = q["ofi"].fillna(0.0)
    d_mid = q["d_mid"]
    ti = p["signed_trade_imbalance"].fillna(0).astype(np.float64)
    signed_volume = p["signed_volume"].fillna(0)

    return {
        "n_bars": int(len(idx)),
        "corr_ofi_dmid": _corr(ofi, d_mid),
        "corr_ti_dmid": _corr(ti, d_mid),
        "ofi_total": float(ofi.sum()),
        "signed_volume_total": float(signed_volume.sum()),
    }

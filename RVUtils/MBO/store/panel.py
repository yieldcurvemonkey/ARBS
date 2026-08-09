"""Aligned multi-product panels: one on a grid, one on the events themselves.

Both exist, and that is a considered choice rather than generosity.

The **grid panel** is what bar-based work needs, and what the existing
``RVUtils.lead_lag`` estimators consume. It forward-fills, because the book
between events *is* the last state.

The **event panel** imposes no grid at all. Sampling asynchronous series onto a
common clock biases measured comovement toward zero as the interval shrinks --
the Epps effect -- which is exactly the regime this dataset exists to reach. A
lead-lag study run only on the grid would find its answer pulled toward "no
relationship" by the sampling, not by the market, so the estimator that needs no
grid needs a frame that has none.

**Units.** ``ticks``, ``points`` and ``usd`` mean what they say. ``bp`` is a
linear rescaling chosen so that *differences* are yield basis points:

    bp = points * usd_per_point / dv01_per_contract

For SR3 that reduces to ``points * 100`` exactly, because the contract is
``100 - rate``. For a Treasury root it uses the day's cheapest-to-deliver DV01,
and the resulting *level* is not a yield -- only its differences, spreads and
changes are. That is stated rather than hidden because a level in "bp" invites
being read as a rate.
"""
from __future__ import annotations

import datetime
from typing import Dict, Iterable, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from RVUtils.MBO.products import PRODUCTS, root_of, spec_for
from RVUtils.MBO.store.reader import (
    DateLike,
    read_catalog,
    read_tob,
    symbols_by_product,
)

__all__ = ["UNITS", "panel", "panel_events", "scale_to"]

UNITS = ("points", "ticks", "usd", "bp")

_PRICE_FIELDS = frozenset({"bid", "ask", "mid", "spread"})
_FIELD_COLS = {"bid": "bid_px", "ask": "ask_px", "mid": "mid", "spread": "spread",
               "bid_sz": "bid_sz", "ask_sz": "ask_sz",
               "bid_ct": "bid_ct", "ask_ct": "ask_ct"}


def scale_to(units: str, root: str, kind: str,
             dv01_per_contract: Optional[float] = None) -> float:
    """Multiplier taking a price in the instrument's own points to ``units``."""
    if units not in UNITS:
        raise ValueError(f"units must be one of {UNITS}, not {units!r}")
    spec = spec_for(root)
    tick = float(spec.tick_for(kind))
    if units == "points":
        return 1.0
    if units == "ticks":
        return 1.0 / tick
    if units == "usd":
        return spec.usd_per_tick / tick
    # bp
    if spec.usd_per_bp_per_lot is not None:
        # A rate contract: one index point is a hundred basis points, exactly.
        return 100.0
    if dv01_per_contract is None or not np.isfinite(dv01_per_contract) \
            or dv01_per_contract == 0.0:
        raise ValueError(
            f"no DV01 for a {root} instrument, so it cannot be expressed in basis "
            f"points: a Treasury future is a price contract and a basis point of "
            f"yield is worth whatever the cheapest-to-deliver DV01 says that day. "
            f"Build the risk partition, or ask for units in "
            f"{('points', 'ticks', 'usd')}."
        )
    return (spec.usd_per_tick / tick) / float(dv01_per_contract)


def _session_mask(ts: pd.Series, session: Optional[Sequence]) -> pd.Series:
    if session is None:
        return pd.Series(True, index=ts.index)
    lo, hi = (pd.Timestamp(x, tz="UTC") if pd.Timestamp(x).tz is None
              else pd.Timestamp(x) for x in session)
    return (ts >= lo) & (ts < hi)


def _load(root: Optional[str], symbols: Sequence[str], dates: Iterable[DateLike],
          units: str, session: Optional[Sequence], clock: str,
          dv01: Optional[Dict[str, float]]) -> Tuple[pd.DataFrame, Dict[str, float]]:
    """All requested symbols' top-of-book events, scaled, on one clock."""
    if clock not in ("ts_recv", "ts_event"):
        raise ValueError("clock must be 'ts_recv' or 'ts_event'")
    dates = list(dates)
    frames = []
    scales: Dict[str, float] = {}
    for product, syms in symbols_by_product(symbols).items():
        tob = read_tob(root, product, dates, syms)
        if tob.empty:
            continue
        cat = read_catalog(root, product, dates, syms)
        kinds = dict(zip(cat["symbol"], cat["kind"])) if not cat.empty else {}
        for sym in syms:
            kind = kinds.get(sym, "OUTRIGHT")
            scales[sym] = scale_to(units, product, kind,
                                   None if dv01 is None else dv01.get(sym))
        frames.append(tob)
    if not frames:
        return pd.DataFrame(), scales

    df = pd.concat(frames, ignore_index=True)
    df = df[_session_mask(df[clock], session)]
    if df.empty:
        return df, scales

    k = df["symbol"].map(scales).to_numpy(dtype=float)
    for col in ("bid_px", "ask_px", "mid", "spread"):
        if col in df.columns:
            df[col] = df[col].to_numpy() * k
    return df.sort_values([clock, "sequence"], kind="stable"), scales


def panel(
    root: Optional[str],
    symbols: Sequence[str],
    dates: Iterable[DateLike],
    freq: str = "1s",
    fields: Sequence[str] = ("mid",),
    units: str = "points",
    session: Optional[Sequence] = None,
    clock: str = "ts_recv",
    dv01: Optional[Dict[str, float]] = None,
) -> pd.DataFrame:
    """A regular-grid panel, forward-filled from each symbol's own events.

    Columns are a ``(field, symbol)`` MultiIndex.  Values before a symbol's first
    quote are NaN rather than a fabricated flat line -- an instrument that had not
    started quoting had no price, and filling backwards would invent one.
    """
    bad = [f for f in fields if f not in _FIELD_COLS]
    if bad:
        raise KeyError(f"unknown fields {bad}; expected {sorted(_FIELD_COLS)}")

    df, _ = _load(root, symbols, dates, units, session, clock, dv01)
    if df.empty:
        return pd.DataFrame()

    out: Dict[Tuple[str, str], pd.Series] = {}
    idx = None
    for sym, g in df.groupby("symbol", sort=False):
        s = g.set_index(clock)
        r = s[[_FIELD_COLS[f] for f in fields]].resample(freq).last()
        idx = r.index if idx is None else idx.union(r.index)
        out[sym] = r

    frames = {}
    for f in fields:
        cols = {}
        for sym, r in out.items():
            cols[sym] = r[_FIELD_COLS[f]].reindex(idx).ffill()
        frames[f] = pd.DataFrame(cols, index=idx)

    wide = pd.concat(frames, axis=1)
    wide.columns.names = ["field", "symbol"]
    wide.index.name = clock
    return wide


def panel_events(
    root: Optional[str],
    symbols: Sequence[str],
    dates: Iterable[DateLike],
    units: str = "points",
    session: Optional[Sequence] = None,
    clock: str = "ts_recv",
    dv01: Optional[Dict[str, float]] = None,
) -> pd.DataFrame:
    """Every symbol's own events on one timeline, long-form, nothing resampled.

    This is the input for estimators that handle asynchrony directly
    (Hayashi-Yoshida and its lead-lag extension).  Nothing here is filled or
    interpolated: each row is an observation that happened.
    """
    df, _ = _load(root, symbols, dates, units, session, clock, dv01)
    if df.empty:
        return df
    cols = ["symbol", clock, "sequence", "bid_px", "ask_px", "mid", "spread",
            "bid_sz", "ask_sz"]
    keep = [c for c in cols if c in df.columns]
    return df[keep].reset_index(drop=True)

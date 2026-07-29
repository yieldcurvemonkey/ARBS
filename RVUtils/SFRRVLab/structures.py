"""Tradeable packages of listed SR3 legs, and how they are marked.

A :class:`Structure` is a weighted basket of listed legs. Options mark at their
LISTED settle premium (``premium_bp`` from the quotes panel); futures mark at
``price_bp = (100 - forward_rate) * 100``. Both are in the same units — basis
points of SR3 price — so a package's mark is a plain weighted sum and its
change is directly a P&L in bp, worth **$25 per contract per bp**.

Sign conventions
----------------
``weight > 0`` means long the leg (paid the premium / long the future). In
*price* space a call has positive delta and a put negative, so the delta-neutral
futures weight of a package is ``-sum(w_i * delta_i)``. Because SR3 price falls
when rates rise, a **put on price is a payer on rates** (the "hike wing") and a
**call on price is a receiver** (the "cut wing").

Marking never invents a price. A leg with no print on a date carries its last
observed premium forward and the fraction of forward-filled marks is reported
per trade (``stale_frac``) so a package held on dead strikes cannot masquerade
as a flat position.
"""
from __future__ import annotations

import dataclasses
from typing import Dict, Iterable, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

__all__ = ["Leg", "Structure", "MarkBook", "mark_structure", "structure_delta",
           "hedge_each_contract", "hedged_path", "package_contracts",
           "round_trip_cost_bp",
           "DOLLARS_PER_BP"]

#: dollars per basis point of SR3 price, per contract
DOLLARS_PER_BP = 25.0


@dataclasses.dataclass(frozen=True)
class Leg:
    """One listed leg. ``kind`` is ``'option'`` or ``'future'``."""

    kind: str
    symbol: str
    weight: float = 1.0
    right: Optional[str] = None            # 'C' | 'P' for options
    strike_price: Optional[float] = None   # listed strike in price terms

    def __post_init__(self) -> None:
        if self.kind not in ("option", "future"):
            raise ValueError(f"kind must be 'option' or 'future', got {self.kind!r}")
        if self.kind == "option":
            if self.right not in ("C", "P"):
                raise ValueError(f"option leg needs right in C/P, got {self.right!r}")
            if self.strike_price is None:
                raise ValueError("option leg needs a strike_price")

    @property
    def key(self) -> Tuple:
        if self.kind == "future":
            return ("F", self.symbol)
        return ("O", self.symbol, self.right, round(float(self.strike_price), 4))

    @property
    def label(self) -> str:
        if self.kind == "future":
            return f"{self.weight:+g}x{self.symbol}"
        return f"{self.weight:+g}x{self.symbol}{self.right}{self.strike_price:g}"


@dataclasses.dataclass(frozen=True)
class Structure:
    """A weighted basket of legs, plus the label used in reports."""

    legs: Tuple[Leg, ...]
    label: str = ""

    def __post_init__(self) -> None:
        if not self.legs:
            raise ValueError("a Structure needs at least one leg")
        object.__setattr__(self, "legs", tuple(self.legs))
        if not self.label:
            object.__setattr__(self, "label", " ".join(l.label for l in self.legs))

    @property
    def n_option_legs(self) -> float:
        return sum(abs(l.weight) for l in self.legs if l.kind == "option")

    @property
    def n_future_legs(self) -> float:
        return sum(abs(l.weight) for l in self.legs if l.kind == "future")

    def with_hedge(self, delta: float, symbol: str) -> "Structure":
        """Append a futures leg of weight ``-delta`` on ``symbol``."""
        if abs(delta) < 1e-12:
            return self
        return Structure(self.legs + (Leg("future", symbol, weight=-float(delta)),),
                         label=self.label + f" hedge{-delta:+.3f}")


class MarkBook:
    """Fast (leg, date) -> mark lookup built once from the panels.

    ``quotes`` needs (as_of, symbol, right, strike_price, premium_bp) and
    optionally ``delta_abs``; ``contracts`` needs (as_of, symbol, forward_rate).
    """

    def __init__(self, quotes: pd.DataFrame, contracts: pd.DataFrame):
        q = quotes.copy()
        q["as_of"] = pd.to_datetime(q["as_of"])
        q["strike_price"] = q["strike_price"].round(4)
        self._opt = (q.set_index(["symbol", "right", "strike_price", "as_of"])
                     ["premium_bp"].sort_index())
        if "delta_abs" in q.columns:
            signed = np.where(q["right"].to_numpy() == "C",
                              q["delta_abs"].to_numpy(), -q["delta_abs"].to_numpy())
            self._delta = pd.Series(
                signed,
                index=pd.MultiIndex.from_frame(
                    q[["symbol", "right", "strike_price", "as_of"]]),
            ).sort_index()
        else:
            self._delta = None
        c = contracts.copy()
        c["as_of"] = pd.to_datetime(c["as_of"])
        self._fut = ((100.0 - c.set_index(["symbol", "as_of"])["forward_rate"]) * 100.0
                     ).sort_index()
        self._cache: Dict[Tuple, pd.Series] = {}

    def series(self, leg: Leg) -> Optional[pd.Series]:
        """Full date-indexed mark history for a leg (None if the leg never printed)."""
        key = leg.key
        if key in self._cache:
            return self._cache[key]
        try:
            if leg.kind == "future":
                s = self._fut.loc[leg.symbol]
            else:
                s = self._opt.loc[(leg.symbol, leg.right, round(float(leg.strike_price), 4))]
        except KeyError:
            s = None
        if s is not None:
            s = s[~s.index.duplicated(keep="last")].sort_index()
        self._cache[key] = s
        return s

    def delta_series(self, leg: Leg) -> Optional[pd.Series]:
        if leg.kind == "future":
            return None
        if self._delta is None:
            return None
        try:
            s = self._delta.loc[(leg.symbol, leg.right,
                                 round(float(leg.strike_price), 4))]
        except KeyError:
            return None
        return s[~s.index.duplicated(keep="last")].sort_index()


def mark_structure(
    book: MarkBook, structure: Structure, dates: Sequence[pd.Timestamp]
) -> Tuple[np.ndarray, float]:
    """Package mark in bp on ``dates`` plus the forward-filled fraction.

    Returns ``(marks, stale_frac)``. A leg with no print at all contributes a
    constant (its first available value, else 0) and every one of its dates
    counts as stale, so ``stale_frac`` is an honest upper bound on how much of
    the package is being carried rather than observed.
    """
    idx = pd.DatetimeIndex(dates)
    total = np.zeros(len(idx), dtype=float)
    stale = np.zeros(len(idx), dtype=float)
    n_legs = len(structure.legs)
    for leg in structure.legs:
        s = book.series(leg)
        if s is None or s.empty:
            stale += 1.0
            continue
        r = s.reindex(idx)
        fresh = r.notna().to_numpy()
        r = r.ffill()
        if not np.isfinite(r.to_numpy()).any():
            stale += 1.0
            continue
        first = float(r.dropna().iloc[0])
        vals = r.fillna(first).to_numpy(dtype=float)
        total += leg.weight * vals
        stale += (~fresh).astype(float)
    return total, float(stale.sum() / max(n_legs * len(idx), 1))


def structure_delta(
    book: MarkBook, structure: Structure, date: pd.Timestamp
) -> float:
    """Net price-space delta of the option legs on ``date`` (futures excluded).

    Legs whose delta is unavailable contribute 0 — the caller sees a smaller
    hedge rather than a fabricated one.
    """
    d = 0.0
    ts = pd.Timestamp(date)
    for leg in structure.legs:
        if leg.kind != "option":
            continue
        s = book.delta_series(leg)
        if s is None or s.empty:
            continue
        r = s.reindex(s.index.union([ts])).sort_index().ffill()
        v = r.get(ts, np.nan)
        if np.isfinite(v):
            d += leg.weight * float(v)
    return d


def hedge_each_contract(
    book: MarkBook, structure: Structure, date: pd.Timestamp,
    *, min_abs_delta: float = 1e-6,
) -> Structure:
    """Neutralise every contract's option delta with that contract's own future.

    A package spanning two expiries needs two hedges, not one: hedging the net
    delta with a single future leaves the position long one contract and short
    the other, which is a curve trade. Hedging per contract removes first-order
    exposure to each contract's level and leaves only the cross-contract shape —
    the object a class-B framework claims to trade.

    Options whose listed delta is missing contribute nothing to the hedge (the
    caller gets a smaller hedge, never a fabricated one).
    """
    ts = pd.Timestamp(date)
    per: Dict[str, float] = {}
    for leg in structure.legs:
        if leg.kind != "option":
            continue
        s = book.delta_series(leg)
        if s is None or s.empty:
            continue
        r = s.reindex(s.index.union([ts])).sort_index().ffill()
        v = r.get(ts, np.nan)
        if np.isfinite(v):
            per[leg.symbol] = per.get(leg.symbol, 0.0) + leg.weight * float(v)
    extra = tuple(Leg("future", sym, weight=-d) for sym, d in per.items()
                  if abs(d) > min_abs_delta)
    if not extra:
        return structure
    return Structure(structure.legs + extra, label=structure.label + " +dhedge")


def hedged_path(
    book: MarkBook,
    structure: Structure,
    dates: Sequence[pd.Timestamp],
    *,
    rehedge_band: float = 0.0,
    future_cost_bp: float = 0.25,
) -> Tuple[np.ndarray, float, float]:
    """Value path of ``structure`` with each contract's delta re-hedged DAILY.

    A static hedge is worthless on a high-gamma package (a tight vertical scaled
    to one unit of probability has enormous gamma): the hedge set at entry stops
    matching within a day and what is left is a large outright futures position.
    This walks the path instead, holding ``-delta_t`` of each contract's own
    future over ``[t, t+1]`` — the delta observed at ``t``, never at ``t+1``.

    Returns ``(value, stale_frac, hedge_cost_total_bp)`` where ``value`` is the
    option package's mark plus cumulative hedge P&L minus cumulative re-hedge
    costs, so ``value[t] - value[0]`` is the trade's P&L in bp.
    """
    idx = pd.DatetimeIndex(dates)
    opt_legs = tuple(l for l in structure.legs if l.kind == "option")
    fut_legs = tuple(l for l in structure.legs if l.kind == "future")
    if not opt_legs:
        marks, stale = mark_structure(book, structure, idx)
        return marks, stale, 0.0
    base = Structure(opt_legs + fut_legs, label=structure.label)
    marks, stale = mark_structure(book, base, idx)

    # net option delta and futures price path, per contract
    symbols = sorted({l.symbol for l in opt_legs})
    delta = {s: np.zeros(len(idx)) for s in symbols}
    for leg in opt_legs:
        d = book.delta_series(leg)
        if d is None or d.empty:
            continue
        v = d.reindex(idx).ffill().bfill().fillna(0.0).to_numpy(dtype=float)
        delta[leg.symbol] += leg.weight * v
    # any futures already in the structure offset the hedge requirement
    for leg in fut_legs:
        if leg.symbol in delta:
            delta[leg.symbol] += leg.weight

    hedge_pnl = np.zeros(len(idx))
    hedge_cost = np.zeros(len(idx))
    for sym in symbols:
        f = book.series(Leg("future", sym))
        if f is None or f.empty:
            continue
        fp = f.reindex(idx).ffill().bfill().to_numpy(dtype=float)
        if not np.isfinite(fp).all():
            continue
        held = np.zeros(len(idx))
        cur = 0.0
        for t in range(len(idx)):
            target = -delta[sym][t]
            if t == 0 or abs(target - cur) > rehedge_band:
                hedge_cost[t] += abs(target - cur) * future_cost_bp
                cur = target
            held[t] = cur
        hedge_pnl[1:] += held[:-1] * np.diff(fp)

    value = marks + np.cumsum(hedge_pnl) - np.cumsum(hedge_cost)
    return value, stale, float(hedge_cost.sum())


def package_contracts(structure: Structure) -> float:
    """Total contracts traded in one package (sum of |weight| over all legs)."""
    return float(sum(abs(l.weight) for l in structure.legs))


def round_trip_cost_bp(
    structure: Structure,
    *,
    option_leg_bp: float = 0.5,
    future_leg_bp: float = 0.25,
) -> float:
    """Per-leg round-trip cost: 2 x (sum |w| x one-way leg cost)."""
    return 2.0 * (structure.n_option_legs * option_leg_bp
                  + structure.n_future_legs * future_leg_bp)

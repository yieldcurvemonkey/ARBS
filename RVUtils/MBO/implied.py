"""Synthesising a structure's book from its legs, and comparing it to the listed one.

To *buy* a structure with leg weights ``w`` you lift the ask on every positive
leg and hit the bid on every negative one, so::

    implied_ask = sum_{w>0} w * ask_i  +  sum_{w<0} w * bid_i
    implied_bid = sum_{w>0} w * bid_i  +  sum_{w<0} w * ask_i

and the implied size is ``min_i floor(size_i / |w_i|)`` -- the thinnest leg
sets the trade.  Note that ``implied_ask`` uses the *bid* of the short legs:
getting this backwards makes the synthetic book look tighter than the listed
one, which is exactly the conclusion the comparison is meant to test.

Sign convention is not assumed.  CME quotes a calendar spread as
first-leg-minus-second and a butterfly as ``A - 2B + C``, but rather than trust
that, :func:`compare_listed_vs_implied` fits both orientations against the
listed mid and reports which one it used.

**Everything in this module is in basis points**, because the two sides of the
comparison are not in the same units on the exchange: the legs quote in index
points and the listed structure quotes in bp.  Both are converted on the way
in, so the leg-implied fly and the listed fly are directly comparable and the
basis between them means what it says.
"""
from __future__ import annotations

import dataclasses
from typing import Dict, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.MBO.metrics import BP_PER_POINT

__all__ = ["ImpliedComparison", "align_leg_books", "compare_listed_vs_implied",
           "implied_structure_book"]


def align_leg_books(leg_tobs: Mapping[str, pd.DataFrame], freq: str = "1s",
                    session: Optional[Sequence] = None) -> Dict[str, pd.DataFrame]:
    """Put every leg's top of book on one grid, forward-filled from its own events."""
    out = {}
    for sym, tob in leg_tobs.items():
        t = tob
        if session is not None:
            lo, hi = (pd.Timestamp(x, tz="UTC") for x in session)
            t = t[(t["ts_recv"] >= lo) & (t["ts_recv"] < hi)]
        p = (
            t.set_index("ts_recv")[["bid_px", "bid_sz", "ask_px", "ask_sz"]]
            .resample(freq).last().ffill()
        )
        out[sym] = p
    idx = None
    for p in out.values():
        idx = p.index if idx is None else idx.union(p.index)
    return {s: p.reindex(idx).ffill() for s, p in out.items()}


def implied_structure_book(
    leg_tobs: Mapping[str, pd.DataFrame],
    legs: Sequence[str],
    weights: Sequence[int],
    freq: str = "1s",
    session: Optional[Sequence] = None,
    leg_bp_per_unit: float = BP_PER_POINT,
) -> pd.DataFrame:
    """Build the structure's synthetic book from its legs' books, **in bp**."""
    if len(legs) != len(weights):
        raise ValueError("legs and weights must align")
    missing = [s for s in legs if s not in leg_tobs]
    if missing:
        raise KeyError(f"no book for legs {missing}")

    aligned = align_leg_books({s: leg_tobs[s] for s in legs}, freq=freq, session=session)
    idx = next(iter(aligned.values())).index

    bid = np.zeros(len(idx))
    ask = np.zeros(len(idx))
    size = np.full(len(idx), np.inf)
    for sym, w in zip(legs, weights):
        p = aligned[sym]
        b, a = p["bid_px"].to_numpy(), p["ask_px"].to_numpy()
        bs, asz = p["bid_sz"].to_numpy(float), p["ask_sz"].to_numpy(float)
        if w > 0:
            bid += w * b
            ask += w * a
            size = np.minimum(size, np.floor(np.minimum(bs, asz) / abs(w)))
        else:
            bid += w * a
            ask += w * b
            size = np.minimum(size, np.floor(np.minimum(bs, asz) / abs(w)))

    out = pd.DataFrame(
        {
            "implied_bid": bid * leg_bp_per_unit,
            "implied_ask": ask * leg_bp_per_unit,
            "implied_sz": size,
        },
        index=idx,
    )
    out["implied_mid"] = (out["implied_bid"] + out["implied_ask"]) / 2.0
    out["implied_spread_bp"] = out["implied_ask"] - out["implied_bid"]
    return out


@dataclasses.dataclass
class ImpliedComparison:
    """Listed book beside its leg-implied twin, plus the summary that matters."""

    frame: pd.DataFrame
    orientation: int
    stats: Dict[str, float]

    def __repr__(self) -> str:
        s = self.stats
        return (
            f"<ImpliedComparison orientation={self.orientation:+d} "
            f"listed={s.get('listed_spread_bp', float('nan')):.3f}bp "
            f"implied={s.get('implied_spread_bp', float('nan')):.3f}bp "
            f"listed_tighter={s.get('frac_listed_tighter', float('nan')):.1%}>"
        )


def compare_listed_vs_implied(
    listed_tob: pd.DataFrame,
    leg_tobs: Mapping[str, pd.DataFrame],
    legs: Sequence[str],
    weights: Sequence[int],
    freq: str = "1s",
    session: Optional[Sequence] = None,
    listed_bp_per_unit: float = 1.0,
    leg_bp_per_unit: float = BP_PER_POINT,
) -> ImpliedComparison:
    """Where does the liquidity in this structure actually live?  All in bp.

    ``frac_listed_tighter`` is the share of grid points where the listed
    instrument's own spread is narrower than the leg-implied one.
    ``frac_listed_crossable`` counts the grid points where the listed bid is at
    or above the implied ask (or vice versa) -- states where the two books
    disagree by more than their combined width.  These are *observations, not
    trades*: the grid is one-second and neither side's size is checked here.
    """
    imp = implied_structure_book(leg_tobs, legs, weights, freq=freq, session=session,
                                 leg_bp_per_unit=leg_bp_per_unit)

    lt = listed_tob
    if session is not None:
        lo, hi = (pd.Timestamp(x, tz="UTC") for x in session)
        lt = lt[(lt["ts_recv"] >= lo) & (lt["ts_recv"] < hi)]
    listed = (
        lt.set_index("ts_recv")[["bid_px", "bid_sz", "ask_px", "ask_sz", "mid"]]
        .resample(freq).last().ffill()
        .reindex(imp.index).ffill()
        .rename(columns={"bid_px": "listed_bid", "ask_px": "listed_ask",
                         "bid_sz": "listed_bid_sz", "ask_sz": "listed_ask_sz",
                         "mid": "listed_mid"})
    )
    for c in ("listed_bid", "listed_ask", "listed_mid"):
        listed[c] = listed[c] * listed_bp_per_unit

    df = listed.join(imp)
    both = df.dropna(subset=["listed_mid", "implied_mid"])
    if both.empty:
        return ImpliedComparison(df, 1, {"n": 0})

    err_pos = float(np.nanmedian(np.abs(both["listed_mid"] - both["implied_mid"])))
    err_neg = float(np.nanmedian(np.abs(both["listed_mid"] + both["implied_mid"])))
    orientation = 1 if err_pos <= err_neg else -1
    if orientation < 0:
        df["implied_bid"], df["implied_ask"] = -df["implied_ask"], -df["implied_bid"]
        df["implied_mid"] = -df["implied_mid"]

    df["listed_spread_bp"] = df["listed_ask"] - df["listed_bid"]
    df["basis_bp"] = df["listed_mid"] - df["implied_mid"]

    v = df.dropna(subset=["listed_spread_bp", "implied_spread_bp"])
    stats = {
        "n": int(len(v)),
        "orientation": orientation,
        "mid_abs_err_bp": float(np.nanmedian(np.abs(v["basis_bp"]))),
        "listed_spread_bp": float(v["listed_spread_bp"].median()),
        "implied_spread_bp": float(v["implied_spread_bp"].median()),
        "frac_listed_tighter": float((v["listed_spread_bp"] < v["implied_spread_bp"]).mean()),
        "listed_sz_at_touch": float(
            np.nanmedian(v[["listed_bid_sz", "listed_ask_sz"]].to_numpy())
        ),
        "implied_sz_at_touch": float(np.nanmedian(v["implied_sz"].to_numpy())),
        "frac_listed_two_sided": float(
            df[["listed_bid", "listed_ask"]].notna().all(axis=1).mean()
        ),
        "frac_listed_crossable": float(
            ((v["listed_bid"] >= v["implied_ask"]) | (v["listed_ask"] <= v["implied_bid"])).mean()
        ),
    }
    return ImpliedComparison(df, orientation, stats)

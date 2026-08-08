"""Microstructure measures on a replayed book, in the units the desk argues in.

Units, stated once because every mistake in this area is a unit mistake:

* **Price units differ by instrument.**  An outright or a bundle quotes in index
  points (96.040, tick 0.005), so ``bp = price * 100``.  Every differential
  instrument -- calendar, butterfly, condor, double fly, bundle spread --
  quotes **directly in basis points** (6.500, tick 0.5), so ``bp = price``.
  Every function here therefore takes ``bp_per_unit``; pass
  ``ReplayResult.bp_per_unit`` and it is right by construction.  Assuming index
  points for a butterfly reports a one-tick market as **50 bp wide**.
* An SR3 outright is **$25 per bp per contract**.  A spread, butterfly or
  bundle *lot* is also **$25 per bp of its own price**, because the leg ratios
  are already inside that price -- a one-lot fly moving 1 bp is $25, not $100.
* ``n_contracts`` (``sum |weights|``) is what a *per-contract* charge multiplies:
  exchange and clearing fees, and the legged-execution cost assumption.  A
  butterfly is four contracts, not three.

The distinction in the last two bullets is the whole point of this module.  The
repo's standing assumption is that a fly costs 2.0 bp round trip, arrived at by
charging four contracts at half a basis point each.  That is the cost of
*legging* it.  A listed butterfly has its own bid and ask, and crossing that
costs the quoted spread once -- which is a different number, measured here.
"""
from __future__ import annotations

from typing import Dict, Iterable, Optional, Sequence

import numpy as np
import pandas as pd

__all__ = [
    "BP_PER_POINT",
    "IMM_TICK_VALUE_USD",
    "USD_PER_BP_PER_LOT",
    "cost_summary",
    "depth_profile",
    "effective_spread",
    "intraday_profile",
    "order_flow_imbalance",
    "quoted_spread_summary",
    "resample_tob",
    "trade_ohlcv",
]

BP_PER_POINT = 100.0
USD_PER_BP_PER_LOT = 25.0
#: One SR3 tick (0.005 index points = 0.5 bp) on one contract.
IMM_TICK_VALUE_USD = 12.50


def _time_weight(tob: pd.DataFrame, start: Optional[pd.Timestamp] = None,
                 end: Optional[pd.Timestamp] = None) -> np.ndarray:
    """Seconds each top-of-book state was live, for time-weighted averages.

    An event-weighted average of the quoted spread is not the spread you face:
    it over-counts the states that flicker and under-counts the wide state that
    stood for ten minutes.
    """
    ts = tob["ts_recv"].to_numpy(dtype="datetime64[ns]").astype(np.int64)
    if ts.size == 0:
        return np.zeros(0)
    stop = ts[-1] if end is None else pd.Timestamp(end).value
    nxt = np.concatenate([ts[1:], [stop]])
    return (nxt - ts).astype(np.float64) / 1e9


def _session_mask(frame: pd.DataFrame, session: Optional[Sequence] = None,
                  col: str = "ts_recv") -> pd.Series:
    if session is None:
        return pd.Series(True, index=frame.index)
    lo, hi = (pd.Timestamp(x, tz="UTC") if pd.Timestamp(x).tz is None else pd.Timestamp(x)
              for x in session)
    return (frame[col] >= lo) & (frame[col] < hi)


def quoted_spread_summary(
    tob: pd.DataFrame,
    n_contracts: int = 1,
    session: Optional[Sequence] = None,
    tick: Optional[float] = None,
    bp_per_unit: float = BP_PER_POINT,
) -> Dict[str, float]:
    """Time-weighted quoted spread and touch depth for one instrument.

    ``two_sided_frac`` is the share of session time with a live bid *and* ask.
    A tight spread that only exists 4% of the day is not a tradeable spread,
    and the mean would hide that.
    """
    t = tob[_session_mask(tob, session)].copy()
    if t.empty:
        return {"n_states": 0, "two_sided_frac": 0.0}

    end = pd.Timestamp(session[1], tz="UTC") if session is not None else None
    w = _time_weight(t, end=end)
    two = np.isfinite(t["spread"].to_numpy())
    wt = w * two
    tot = wt.sum()

    sp = t["spread"].to_numpy()
    out = {
        "n_states": int(len(t)),
        "two_sided_frac": float(tot / w.sum()) if w.sum() > 0 else 0.0,
        "spread_pts": float(np.nansum(sp * wt) / tot) if tot > 0 else np.nan,
        "spread_bp": float(np.nansum(sp * wt) / tot * bp_per_unit) if tot > 0 else np.nan,
        "spread_bp_median": float(np.nanmedian(sp[two]) * bp_per_unit) if two.any() else np.nan,
        "bid_sz_at_touch": float(np.nansum(t["bid_sz"].to_numpy() * wt) / tot) if tot > 0 else np.nan,
        "ask_sz_at_touch": float(np.nansum(t["ask_sz"].to_numpy() * wt) / tot) if tot > 0 else np.nan,
        "orders_at_touch": float(
            np.nansum((t["bid_ct"].to_numpy() + t["ask_ct"].to_numpy()) * wt) / tot
        ) if tot > 0 else np.nan,
    }
    out["roundtrip_usd_per_lot"] = out["spread_bp"] * USD_PER_BP_PER_LOT
    out["roundtrip_bp_per_contract"] = out["spread_bp"] / max(1, n_contracts)
    if tick:
        out["spread_ticks"] = out["spread_pts"] / tick
        at_one = np.isclose(sp, tick, atol=tick * 0.01)
        out["frac_time_one_tick"] = float(wt[at_one].sum() / tot) if tot > 0 else np.nan
    return out


def effective_spread(
    tob: pd.DataFrame,
    trades: pd.DataFrame,
    horizons_s: Sequence[float] = (1.0, 10.0, 60.0),
    session: Optional[Sequence] = None,
    bp_per_unit: float = BP_PER_POINT,
) -> pd.DataFrame:
    """Per-trade effective spread, realised spread and price impact, in bp.

    The prevailing mid is taken from the last top-of-book state *before* the
    packet the trade sits in, joined on record index rather than timestamp:
    every record inside a packet shares a timestamp, so an as-of join on time
    would sometimes pick up the book the trade itself created.
    """
    if trades.empty or tob.empty:
        return trades.assign(mid_prev=np.nan, eff_bp=np.nan)

    left = trades.sort_values("rec_idx")
    right = tob[["rec_idx", "ts_recv", "mid", "bid_px", "ask_px"]].sort_values("rec_idx")
    m = pd.merge_asof(
        left, right.rename(columns={"ts_recv": "ts_book", "mid": "mid_prev"}),
        on="rec_idx", direction="backward", allow_exact_matches=False,
    )

    d = np.where(m["aggressor"].to_numpy() == "B", 1.0,
                 np.where(m["aggressor"].to_numpy() == "A", -1.0, np.nan))
    m["direction"] = d
    m["eff_bp"] = 2.0 * d * (m["price"] - m["mid_prev"]) * bp_per_unit
    m["eff_usd_per_lot"] = m["eff_bp"] * USD_PER_BP_PER_LOT

    fwd = tob[["ts_recv", "mid"]].dropna().sort_values("ts_recv")
    for h in horizons_s:
        tgt = m[["ts_recv"]].copy()
        tgt["ts_recv"] = tgt["ts_recv"] + pd.Timedelta(seconds=float(h))
        j = pd.merge_asof(
            tgt.sort_values("ts_recv").reset_index().rename(columns={"index": "_i"}),
            fwd.rename(columns={"mid": f"mid_fwd_{h:g}s"}),
            on="ts_recv", direction="backward",
        ).set_index("_i").sort_index()
        fm = j[f"mid_fwd_{h:g}s"].to_numpy()
        m[f"realised_bp_{h:g}s"] = 2.0 * d * (m["price"].to_numpy() - fm) * bp_per_unit
        m[f"impact_bp_{h:g}s"] = m["eff_bp"] - m[f"realised_bp_{h:g}s"]

    if session is not None:
        m = m[_session_mask(m, session)]
    return m


def order_flow_imbalance(tob: pd.DataFrame, freq: str = "1min",
                         bp_per_unit: float = BP_PER_POINT) -> pd.DataFrame:
    """Cont-Kukanov-Stoikov order-flow imbalance from top-of-book changes.

    Each state transition contributes +bid size when the bid improves or grows,
    -bid size when it worsens or shrinks, and the mirror on the ask.  The sum
    over a bar is signed pressure at the touch in lots.
    """
    t = tob.dropna(subset=["bid_px", "ask_px"]).copy()
    if t.empty:
        return pd.DataFrame(columns=["ofi", "n_events", "mid_change_bp"])

    bp, bs = t["bid_px"].to_numpy(), t["bid_sz"].to_numpy().astype(float)
    ap, asz = t["ask_px"].to_numpy(), t["ask_sz"].to_numpy().astype(float)
    e_b = np.zeros(len(t))
    e_a = np.zeros(len(t))
    dpb, dpa = np.diff(bp), np.diff(ap)
    e_b[1:] = np.where(dpb > 0, bs[1:], np.where(dpb < 0, -bs[:-1], bs[1:] - bs[:-1]))
    e_a[1:] = np.where(dpa < 0, -asz[1:], np.where(dpa > 0, asz[:-1], -(asz[1:] - asz[:-1])))
    t["ofi_event"] = e_b + e_a

    g = t.set_index("ts_recv").resample(freq)
    out = pd.DataFrame(
        {
            "ofi": g["ofi_event"].sum(),
            "n_events": g["ofi_event"].size(),
            "mid_change_bp": g["mid"].last().diff() * bp_per_unit,
        }
    )
    return out


def resample_tob(tob: pd.DataFrame, freq: str = "1s",
                 session: Optional[Sequence] = None,
                 bp_per_unit: float = BP_PER_POINT) -> pd.DataFrame:
    """Last-observation panel of the touch on a regular grid -- the RV input.

    Forward-filled, because the book between events *is* the last state; but
    only after the first real quote, so the pre-open is NaN rather than a
    fabricated flat line.
    """
    t = tob[_session_mask(tob, session)]
    if t.empty:
        return pd.DataFrame()
    cols = ["bid_px", "bid_sz", "ask_px", "ask_sz", "mid", "spread"]
    p = t.set_index("ts_recv")[cols].resample(freq).last().ffill()
    p["spread_bp"] = p["spread"] * bp_per_unit
    p["mid_bp"] = p["mid"] * bp_per_unit
    return p


def trade_ohlcv(trades: pd.DataFrame, freq: Optional[str] = None) -> pd.DataFrame:
    """OHLCV from trade prints.  ``freq=None`` gives the single session bar.

    This is the tie-out surface: the session bar must reproduce the vendor EOD
    open/high/low/close for the same instrument and day.
    """
    if trades.empty:
        return pd.DataFrame()
    t = trades.set_index("ts_recv").sort_index()
    if freq is None:
        return pd.DataFrame(
            [{
                "open": t["price"].iloc[0], "high": t["price"].max(),
                "low": t["price"].min(), "close": t["price"].iloc[-1],
                "volume": int(t["size"].sum()), "n_trades": int(len(t)),
            }]
        )
    g = t.resample(freq)
    out = pd.DataFrame(
        {
            "open": g["price"].first(), "high": g["price"].max(),
            "low": g["price"].min(), "close": g["price"].last(),
            "volume": g["size"].sum(), "n_trades": g["price"].size(),
        }
    )
    return out[out["n_trades"] > 0]


def depth_profile(depth: dict, side: str = "bid") -> pd.DataFrame:
    """Grid depth as a tidy frame: one row per (grid time, level)."""
    px, sz = depth[f"{side}_px"], depth[f"{side}_sz"]
    n_t, n_l = px.shape
    return pd.DataFrame(
        {
            "ts": np.repeat(pd.to_datetime(depth["ts"], utc=True), n_l),
            "level": np.tile(np.arange(n_l), n_t),
            "price": px.ravel(),
            "size": sz.ravel(),
            "side": side,
        }
    ).dropna(subset=["price"])


def intraday_profile(tob: pd.DataFrame, trades: pd.DataFrame,
                     freq: str = "5min",
                     bp_per_unit: float = BP_PER_POINT) -> pd.DataFrame:
    """Spread, depth and volume by time of day -- when the book is worth using."""
    t = tob.dropna(subset=["spread"]).set_index("ts_recv")
    g = t.resample(freq)
    out = pd.DataFrame(
        {
            "spread_bp": g["spread"].mean() * bp_per_unit,
            "spread_bp_p25": g["spread"].quantile(0.25) * bp_per_unit,
            "spread_bp_p75": g["spread"].quantile(0.75) * bp_per_unit,
            "bid_sz": g["bid_sz"].mean(),
            "ask_sz": g["ask_sz"].mean(),
            "n_quote_events": g["spread"].size(),
        }
    )
    if not trades.empty:
        tg = trades.set_index("ts_recv").resample(freq)
        out["volume"] = tg["size"].sum()
        out["n_trades"] = tg["size"].size()
    return out.fillna({"volume": 0, "n_trades": 0})


def cost_summary(
    rows: Iterable[dict],
    legged_bp_per_contract: float = 0.5,
) -> pd.DataFrame:
    """Assemble per-instrument cost comparison: listed book versus legging it.

    ``legged_bp_per_contract`` is the repo's standing per-contract round-trip
    assumption.  ``legged_roundtrip_bp`` is that assumption applied to the
    structure (``n_contracts`` x the charge); ``listed_roundtrip_bp`` is what
    the instrument's own quoted spread actually costs.  ``cost_ratio`` below 1
    means the listed book is cheaper than the assumption the backtests carry.

    Rows may carry ``usd_per_bp`` (from ``ParsedSymbol.usd_per_bp_per_lot``).
    Without it the $25-per-bp default applies, which is right for outrights and
    every differential instrument but understates a bundle by its leg count.
    """
    df = pd.DataFrame(list(rows))
    if df.empty:
        return df
    usd = df["usd_per_bp"] if "usd_per_bp" in df else USD_PER_BP_PER_LOT
    df["legged_roundtrip_bp"] = df["n_contracts"] * legged_bp_per_contract
    df["listed_roundtrip_bp"] = df["spread_bp"]
    df["cost_ratio"] = df["listed_roundtrip_bp"] / df["legged_roundtrip_bp"]
    df["listed_roundtrip_usd"] = df["listed_roundtrip_bp"] * usd
    df["legged_roundtrip_usd"] = df["legged_roundtrip_bp"] * usd
    df["saving_bp"] = df["legged_roundtrip_bp"] - df["listed_roundtrip_bp"]
    df["saving_usd"] = df["saving_bp"] * usd
    return df

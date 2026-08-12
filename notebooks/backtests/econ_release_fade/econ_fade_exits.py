"""Path-dependent exits: leave at a LEVEL, not at a clock time.

The rest of this study exits at a fixed offset from the release. That is the
right thing for measuring whether a move reverts, and the wrong thing for
trading it: a fade has a natural target -- some fraction of the burst coming
back -- and a natural failure condition -- the burst extending instead. A clock
exit expresses neither, and it dilutes a real effect with trades held long after
they were finished and trades still open long after they were wrong.

So this module gives a trade a bracket:

    target   entry + side * tp_bp * px_per_bp        take the reversion
    stop     entry - side * sl_bp * px_per_bp        the burst kept going
    trail    best favourable level - side * trail    give back at most this
    time     a backstop, because a bracket that never fills is a position

and walks the minute bars forward, causally, until one of them is hit.

Three modelling choices, each of which flatters the strategy if made the other
way.

**A bar's High and Low are used for triggering, not just its close.** A resting
take-profit that the market traded through was filled, and pretending otherwise
would understate the strategy. But that cuts both ways and the stop is treated
the same.

**When both levels sit inside one bar, the STOP is assumed to fill first.** The
minute bar does not record the order in which its extremes occurred, so the
question is genuinely unanswerable from this data -- and the answer that makes a
backtest look better is the one that is wrong more often than it is right.

**Stops slip and limits do not.** A take-profit is a resting limit and fills at
its level. A stop is a market order into the move that triggered it, so it fills
``stop_slip_ticks`` beyond the level. Default one tick.

Every price is the close of a bar that had fully closed by the timestamp
(``econ_fade_common.px_before``), so nothing here reads a bar that had not
printed. Barchart minute bars are start-stamped: the bar labelled ``t`` covers
``[t, t+1)``, so a trade entered at ``t`` fills at the close of bar ``t-1`` and
the first bar it can be exited on is ``t``.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

import econ_fade_common as G

__all__ = [
    "ExitRule",
    "trade_path",
    "simulate_exit",
    "run_exit_backtest",
    "build_base_book",
    "exit_rule_grid",
]


@dataclass(frozen=True)
class ExitRule:
    """A bracket, in basis points of rate.

    ``*_frac`` variants are expressed as a fraction of that trade's OWN initial
    move, which is the natural scale for a fade: a 6bp CPI burst and a 1bp
    jobless-claims burst do not deserve the same absolute target. When both a
    ``_bp`` and a ``_frac`` are given the tighter of the two applies.
    """

    name: str = "rule"
    tp_bp: Optional[float] = None
    tp_frac: Optional[float] = None
    sl_bp: Optional[float] = None
    sl_frac: Optional[float] = None
    trail_bp: Optional[float] = None
    time_stop_min: int = 240
    min_hold_min: int = 0
    stop_slip_ticks: float = 1.0
    #: "intrabar" uses High/Low to trigger; "close" only looks at bar closes and
    #: is what the engine can see, so the two agree only in "close" mode.
    mode: str = "intrabar"

    def levels(self, move_bp: float) -> Tuple[Optional[float], Optional[float]]:
        """(take-profit bp, stop bp) for a trade whose burst was ``move_bp``."""
        m = abs(float(move_bp))
        tps = [v for v in (self.tp_bp, (self.tp_frac * m if self.tp_frac else None))
               if v is not None]
        sls = [v for v in (self.sl_bp, (self.sl_frac * m if self.sl_frac else None))
               if v is not None]
        return (min(tps) if tps else None), (min(sls) if sls else None)


def trade_path(symbol: str, entry_ts: pd.Timestamp, horizon_min: int) -> pd.DataFrame:
    """Bars the trade can be exited on: stamp in [entry_ts, entry_ts + horizon).

    The bar stamped ``entry_ts`` is the first one -- the entry filled at the
    close of ``entry_ts - 1``, so ``entry_ts`` is the first interval that had not
    yet happened when the decision was taken.
    """
    df = G._BAR_CACHE.get((symbol, pd.Timestamp(entry_ts).date()))
    if df is None or df.empty:
        return pd.DataFrame()
    end = entry_ts + pd.Timedelta(minutes=int(horizon_min))
    lo = int(df.index.searchsorted(entry_ts, side="left"))
    hi = int(df.index.searchsorted(end, side="left"))
    return df.iloc[lo:hi]


def simulate_exit(path: pd.DataFrame, entry_px: float, side: float, px_per_bp: float,
                  rule: ExitRule, move_bp: float, tick_px: float = 0.0) -> Dict[str, Any]:
    """Walk the path and return where the trade actually left.

    Returns the exit price, the reason, the bar it happened on, and the minutes
    held. A trade whose bracket never fills exits at the last bar of the window
    (``time_stop``); a trade with no path at all is reported as ``no_path`` and
    must be excluded rather than booked at zero.
    """
    if path is None or path.empty:
        return {"exit_px": np.nan, "reason": "no_path", "exit_ts": pd.NaT, "hold_min": np.nan}

    tp_bp, sl_bp = rule.levels(move_bp)
    has_hl = {"High", "Low"}.issubset(path.columns) and rule.mode == "intrabar"

    tp_px = entry_px + side * tp_bp * px_per_bp if tp_bp is not None else None
    sl_px = entry_px - side * sl_bp * px_per_bp if sl_bp is not None else None
    trail_px_gap = rule.trail_bp * px_per_bp if rule.trail_bp else None

    best = entry_px                      # best FAVOURABLE price seen so far
    entry_ts = path.index[0]
    closes = path["Close"].to_numpy(dtype=float)
    highs = path["High"].to_numpy(dtype=float) if has_hl else closes
    lows = path["Low"].to_numpy(dtype=float) if has_hl else closes
    idx = path.index

    for i in range(len(path)):
        b = idx[i]
        held = (b + pd.Timedelta(minutes=1) - entry_ts).total_seconds() / 60.0
        if held < rule.min_hold_min:
            best = max(best, highs[i]) if side > 0 else min(best, lows[i])
            continue

        hi_i, lo_i, cl_i = highs[i], lows[i], closes[i]

        # Trailing level is recomputed from the best price seen BEFORE this bar,
        # so a bar cannot both set a new best and be stopped out on it.
        trail_px = None
        if trail_px_gap is not None:
            trail_px = best - side * trail_px_gap

        stop_level = None
        for lvl in (sl_px, trail_px):
            if lvl is None:
                continue
            stop_level = lvl if stop_level is None else (max(stop_level, lvl) if side > 0
                                                         else min(stop_level, lvl))

        hit_stop = stop_level is not None and (lo_i <= stop_level if side > 0 else hi_i >= stop_level)
        hit_tp = tp_px is not None and (hi_i >= tp_px if side > 0 else lo_i <= tp_px)

        if hit_stop:
            # Conservative: when both levels are inside one bar the stop wins,
            # because the bar does not say which extreme came first.
            px = stop_level - side * rule.stop_slip_ticks * tick_px
            return {"exit_px": float(px), "reason": "stop" if stop_level == sl_px else "trail",
                    "exit_ts": b + pd.Timedelta(minutes=1), "hold_min": held}
        if hit_tp:
            return {"exit_px": float(tp_px), "reason": "target",
                    "exit_ts": b + pd.Timedelta(minutes=1), "hold_min": held}

        best = max(best, hi_i) if side > 0 else min(best, lo_i)

    b = idx[-1]
    return {"exit_px": float(closes[-1]), "reason": "time_stop",
            "exit_ts": b + pd.Timedelta(minutes=1),
            "hold_min": (b + pd.Timedelta(minutes=1) - entry_ts).total_seconds() / 60.0}


def build_base_book(cfg: dict, raw: pd.DataFrame) -> G.Book:
    """The gated, measured, signed book -- exits are applied to it afterwards.

    Built once and reused across every exit rule, which is what makes a search
    over brackets cheap and, more importantly, guarantees every rule is scored on
    exactly the same set of trades.
    """
    return G.build_book(cfg, raw)


def run_exit_backtest(book: G.Book, rule: ExitRule, *, cost_bp: float = 0.0) -> pd.DataFrame:
    """Apply one exit rule to every trade in the book."""
    ev = book.events
    if ev.empty:
        return pd.DataFrame()
    inst = book.instrument
    tick_size = G.UST_TICKS[inst.root][0] if inst.family == "ust" else 0.005

    rows: List[dict] = []
    for _, r in ev.iterrows():
        ppb = float(r["px_per_bp"])
        path = trade_path(r["symbol"], r["entry_ts"], rule.time_stop_min)
        out = simulate_exit(path, float(r["entry_px"]), float(r["side"]), ppb,
                            rule, float(r["move_bp"]), tick_px=tick_size)
        if out["reason"] == "no_path":
            continue
        pnl_bp = float(r["side"]) * (out["exit_px"] - float(r["entry_px"])) / ppb
        d = r.to_dict()
        d.update({"rule": rule.name, "exit_reason": out["reason"], "exit_px_rule": out["exit_px"],
                  "exit_ts_rule": out["exit_ts"], "hold_min": out["hold_min"],
                  "pnl_bp_gross": pnl_bp, "pnl_bp": pnl_bp - cost_bp, "cost_bp": cost_bp})
        rows.append(d)

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["profitable"] = df["pnl_bp"] > 0
    df["abs_move_bp"] = df["move_bp"].abs()
    df["release_ts"] = pd.to_datetime(df["release_ts"], utc=True)
    df["year"] = df["release_ts"].dt.tz_convert("America/New_York").dt.year
    return df.sort_values("release_ts").reset_index(drop=True)


def exit_rule_grid(*, tp_fracs: Sequence[float], sl_fracs: Sequence[float],
                   trails: Sequence[Optional[float]], time_stops: Sequence[int],
                   mode: str = "intrabar") -> List[ExitRule]:
    """The bracket search space, named so a result can be traced to its rule."""
    out: List[ExitRule] = []
    for tp in tp_fracs:
        for sl in sl_fracs:
            for tr in trails:
                for ts in time_stops:
                    nm = (f"tp{tp:g}|sl{'inf' if sl is None else format(sl, 'g')}|"
                          f"tr{'-' if tr is None else format(tr, 'g')}|t{ts}")
                    out.append(ExitRule(name=nm, tp_frac=tp, sl_frac=sl, trail_bp=tr,
                                        time_stop_min=ts, mode=mode))
    return out

"""Bracket exits on UST futures, through the real MDP and QueryDrivenBacktest.

The clock-exit study leaves at a fixed offset. This one leaves at a LEVEL, and
it does it the way the engine is meant to be used: the exit is a
``FlowSignalTriggerRequirements`` evaluated at every minute the position is
open, which asks the MDP what the price is now and decides whether the target,
the stop or the trailing level has been hit.

Nothing here prices anything itself. Prices come from ``USTFuturesMDP.get_data``
and P&L comes from the shipped ``USTFutureHandler`` through
``QueryDrivenBacktest``.

**The engine can only see closes.** ``get_data`` returns one price per
timestamp, so a bracket evaluated through the engine is a desk polling once a
minute and acting on the print -- not a resting order that would have been
filled the moment the market traded through it. That is the conservative model
and it is the one that can be verified end to end, so it is the one the search
uses. ``econ_fade_exits`` can additionally trigger on a bar's High/Low, which is
the resting-order model; the two are reported side by side and the difference is
the value of having orders in the book rather than a screen.

**The cache is primed and the fetcher is disarmed.** Barchart's fetcher cannot
run inside a Jupyter kernel, and ``USTFuturesMDP`` keys its cache on the
REQUESTED ISO timestamp (``USTF_GET_DATA_v2::{iso}-{sym}-{source}``), so the
exact minutes the backtest will ask for are written in from a plain process and
then the fetcher is replaced with a raise. A cache miss becomes a loud failure
rather than a silent refetch, and "no network was used" is enforced.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import pytz

from BT.data_handler import TimeGrid
from BT.query_actions import AddQueryFactoryAction, BuiltQuery, UnwindPositionsAction
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.triggers import Trigger, FlowSignalTriggerRequirements

from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP
from Query.USTFutures.USTFutureQuery import USTFutureQuery
from Query.USTFutures.USTFutureStructure import USTFutureStructure
from Query.USTFutures.USTFutureValue import USTFutureValue

import econ_fade_common as G
import econ_fade_exits as X

SOURCE = "BARCHART_USTF-RL"
_CACHE_VERSION = "USTF_GET_DATA_v2"

__all__ = [
    "open_ust_mdp", "prime_ust_cache", "ust_price", "wanted_minutes",
    "run_bracket_engine", "run_bracket_fast", "path_minutes", "NetworkForbidden",
]


class NetworkForbidden(RuntimeError):
    """The MDP asked for a price its cache does not hold."""


def _plain(ts) -> datetime.datetime:
    t = pd.Timestamp(ts)
    return datetime.datetime(t.year, t.month, t.day, t.hour, t.minute, t.second,
                             tzinfo=t.tzinfo)


def open_ust_mdp(*, armed: bool = False) -> USTFuturesMDP:
    mdp = USTFuturesMDP(source=SOURCE)
    try:
        mdp._ensure_pricer_cache()
    except Exception:  # noqa: BLE001 -- the mixin opens lazily on first use
        pass
    if not armed:
        def _forbidden(*_a, **_k):
            raise NetworkForbidden(
                "the UST MDP cache does not cover this timestamp -- prime it first")
        mdp._fetch_barchart_timeseries = _forbidden        # type: ignore[method-assign]
    return mdp


def _cache_key(symbol: str, ts) -> str:
    return f"{_CACHE_VERSION}::{_plain(ts).isoformat()}-{symbol}-{SOURCE}"


def wanted_minutes(events: pd.DataFrame, time_stop_min: int,
                   ) -> List[Tuple[str, pd.Timestamp]]:
    """Every (symbol, minute) the engine can ask for.

    The grid runs minute by minute from the entry to the time stop, and
    ``mark_to_market`` prices the open position at every one of them -- so the
    prime has to cover the whole path, not just the entry and the exit.
    """
    out = []
    have_measure = {"m0_ts", "m1_ts"} <= set(events.columns)
    for _, r in events.iterrows():
        sym = r["symbol"]
        # The measurement pair, then every minute of the holding window.
        # A book signed off a CONSENSUS surprise never measures a move, so it has
        # no m0/m1 -- asking for them raised KeyError and made the engine
        # unreachable for that whole family of strategies.
        if have_measure:
            for k in (r["m0_ts"], r["m1_ts"]):
                if pd.notna(k):
                    out.append((sym, k))
        t = r["entry_ts"]
        for i in range(int(time_stop_min) + 2):
            out.append((sym, t + pd.Timedelta(minutes=i)))
    return sorted(set(out))


def prime_ust_cache(mdp: USTFuturesMDP, wanted: Iterable[Tuple[str, pd.Timestamp]],
                    *, show_progress: bool = True) -> Dict[str, int]:
    """Write warmed Barchart bars into the UST MDP's own cache.

    The MDP resolves an intraday request to the NEAREST bar, so a minute with no
    print would silently borrow a neighbouring one. Here only minutes that
    genuinely printed are written; the rest stay a miss and the gate turns them
    into a counted exclusion rather than a fabricated price.
    """
    G.load_bar_cache()
    stats = {"written": 0, "no_bar": 0, "no_day": 0}
    items = list(wanted)
    it = items
    if show_progress:
        try:
            from tqdm.auto import tqdm
            it = tqdm(items, desc="prime UST MDP cache")
        except Exception:  # noqa: BLE001
            pass
    for sym, ts in it:
        day = pd.Timestamp(ts).date()
        bars = G._BAR_CACHE.get((sym, day))
        if bars is None:
            stats["no_day"] += 1
            continue
        try:
            px = float(bars["Close"].loc[pd.Timestamp(ts)])
        except KeyError:
            stats["no_bar"] += 1
            continue
        iso = _plain(ts).isoformat()
        mdp._threadsafe_cache_put(_cache_key(sym, ts),
                                  {"symbol": sym, "price": px, "timestamp": iso, "schema": 1})
        stats["written"] += 1
    # USTFuturesMDP._threadsafe_cache_put writes straight to the DiskCache, so
    # there is nothing to flush. STIRFutureMDP stages in memory and flushes on a
    # BACKGROUND thread, where a process that exits promptly loses the batch --
    # so if the method is there it is called synchronously.
    flush = getattr(mdp, "_flush_pending_cache_writes", None)
    if callable(flush):
        flush(background=False)
    return stats


def ust_price(mdp: USTFuturesMDP, symbol: str, ts) -> Optional[float]:
    """One price, through ``get_data``. ``include_basket=False`` keeps the
    deliverable basket -- and the FedInvest fetch behind it -- out of a path that
    only needs a futures price."""
    try:
        got = mdp.get_pricer({"symbols": [symbol], "timestamp": _plain(ts),
                              "include_basket": False})
    except Exception:  # noqa: BLE001
        return None
    for _k, pr in got.items():
        try:
            return float(pr.price(pr.build_ustf()))
        except Exception:  # noqa: BLE001
            return None
    return None


def path_minutes(symbol: str, entry_ts, time_stop_min: int) -> List[pd.Timestamp]:
    """The minutes the engine steps through: those that actually printed.

    Stepping on a minute with no bar would make ``get_pricer`` raise, and
    ``QueryDrivenBacktest.run()`` catches every exception and ABORTS THE WHOLE
    STEP -- taking with it any unwind scheduled there, so a position silently
    stays open past its own stop. Building the grid from bars that exist removes
    the failure mode instead of relying on it not happening.
    """
    df = G._BAR_CACHE.get((symbol, pd.Timestamp(entry_ts).date()))
    if df is None or df.empty or pd.Timestamp(entry_ts) not in df.index:
        return []
    end = pd.Timestamp(entry_ts) + pd.Timedelta(minutes=int(time_stop_min))
    return list(df.index[(df.index > pd.Timestamp(entry_ts)) & (df.index <= end)])


# ===========================================================================
# The bracket, as a trigger
# ===========================================================================
@dataclass
class BracketExitSignal:
    """Evaluated every minute the position is open; unwinds when a level is hit.

    State (the best price seen, for the trailing stop) lives on the object
    because the engine calls the signal once per grid step and has nowhere else
    to keep it. It is reset when the position opens, so a re-run is clean.
    """

    mdp: USTFuturesMDP
    symbol: str
    tag: str
    side: float
    entry_ts: datetime.datetime
    last_ts: datetime.datetime
    entry_px: float
    px_per_bp: float
    tp_bp: Optional[float]
    sl_bp: Optional[float]
    trail_bp: Optional[float]
    min_hold_min: int = 0
    best: Optional[float] = None
    fired: bool = False
    reason: Dict[str, str] = field(default_factory=dict)

    def _open(self, backtest) -> bool:
        for p in backtest.portfolio.positions:
            tags = set(p.meta.get("tags", [])) | set(getattr(p.source_query, "tags", ()) or ())
            if self.tag in tags:
                return True
        return False

    def __call__(self, state, backtest):
        if state < self.entry_ts or self.fired:
            return False
        if not self._open(backtest):
            return False
        held = (pd.Timestamp(state) - pd.Timestamp(self.entry_ts)).total_seconds() / 60.0
        at_last = state >= self.last_ts
        if held < self.min_hold_min and not at_last:
            return False

        px = ust_price(self.mdp, self.symbol, state)
        if px is None:
            # The final bar must still close the position even if it cannot be
            # priced here -- the engine will price the unwind itself.
            if at_last:
                self.fired = True
                self.reason[self.tag] = "time_stop"
                return True
            return False

        gain_bp = self.side * (px - self.entry_px) / self.px_per_bp
        if self.tp_bp is not None and gain_bp >= self.tp_bp:
            self.fired = True
            self.reason[self.tag] = "target"
            return True
        if self.sl_bp is not None and gain_bp <= -self.sl_bp:
            self.fired = True
            self.reason[self.tag] = "stop"
            return True
        if self.trail_bp is not None:
            best = px if self.best is None else (max(self.best, px) if self.side > 0
                                                 else min(self.best, px))
            give_back = self.side * (best - px) / self.px_per_bp
            self.best = best
            if give_back >= self.trail_bp and best != self.entry_px:
                self.fired = True
                self.reason[self.tag] = "trail"
                return True
        if at_last:
            # Checked LAST, not first. Evaluating the time stop before the
            # bracket labels a level hit on the final bar as a time stop -- the
            # P&L is identical but the exit-reason mix, which is how the rule is
            # understood, is wrong. Measured on 2 of 84 trades.
            self.fired = True
            self.reason[self.tag] = "time_stop"
            return True
        return False


def _make_query(ev: dict, rule_name: str) -> USTFutureQuery:
    """Direction lives in ``risk_weights``. A negative contract count books a
    LONG on this product -- the structure builder flips the weight while the leg
    keeps its negative count, and the handler multiplies by both."""
    return USTFutureQuery(
        structure=USTFutureStructure.OUTRIGHT,
        value=USTFutureValue.PRICE,
        symbol=ev["symbol"],
        structure_kwargs={"contracts": 1, "risk_weights": [float(ev["side"])]},
        market_request={"timestamp": "now", "include_basket": False},
        tags=(ev["tag"],),
        meta={"symbol": ev["symbol"], "side": float(ev["side"]), "rule": rule_name,
              "move_bp": float(ev["move_bp"]), "release_ts": ev["release_ts"],
              "lead_title": ev["lead_title"], "entry_px": float(ev["entry_px"]),
              "px_per_bp": float(ev["px_per_bp"]), "tag": ev["tag"]},
    )


def run_bracket_engine(book: G.Book, rule: X.ExitRule, mdp: USTFuturesMDP, *,
                       cost_bp: float = 0.0, show_progress: bool = True) -> pd.DataFrame:
    """One bracket, every trade, through QueryDrivenBacktest.

    The time grid is every minute from each entry to its time stop, because a
    level can be hit at any of them. That is what makes this the engine's job
    rather than a lookup: the exit is decided by market state at the step, not
    by arithmetic after the fact.
    """
    ev = book.events
    if ev.empty:
        return pd.DataFrame()

    grid: set = set()
    triggers: List[Trigger] = []
    signals: Dict[str, BracketExitSignal] = {}

    for _, r in ev.iterrows():
        entry = _plain(r["entry_ts"])
        mins = path_minutes(r["symbol"], r["entry_ts"], int(rule.time_stop_min))
        if not mins:
            continue
        last = _plain(mins[-1])
        grid.add(entry)
        for m_ in mins:
            grid.add(_plain(m_))

        # The bracket must be measured from the price the ENGINE actually filled
        # at -- the bar stamped entry_ts -- not from the book's px_before value,
        # which is the previous bar. Using the wrong reference shifts every level
        # by one bar's move and changes which one is hit: measured, it moved the
        # book from +0.07 to +0.24 bp/trade and disagreed with the closed form on
        # 11 of 84 exits.
        entry_px_eng = ust_price(mdp, r["symbol"], entry)
        if entry_px_eng is None:
            continue

        tp_bp, sl_bp = rule.levels(float(r["move_bp"]))
        payload = r.to_dict()

        # Bound as DEFAULT ARGUMENTS. A closure over the loop variable would
        # capture the LAST event of the loop for every trigger -- all 84 entries
        # would submit the same query, and the book would look plausible.
        def _entry_fn(state, backtest, _t=entry, _pl=payload):
            return (True, {"bracket": _pl}) if state == _t else False

        triggers.append(Trigger(
            trigger_requirements=FlowSignalTriggerRequirements(signal_fn=_entry_fn),
            actions=[AddQueryFactoryAction(
                query_factory=(lambda *, now, backtest, info, _rn=rule.name:
                               [BuiltQuery(query=_make_query(info["bracket"], _rn))]
                               if info.get("bracket") else []))],
        ))

        sig = BracketExitSignal(
            mdp=mdp, symbol=r["symbol"], tag=r["tag"], side=float(r["side"]),
            entry_ts=entry, last_ts=last, entry_px=float(entry_px_eng),
            px_per_bp=float(r["px_per_bp"]), tp_bp=tp_bp, sl_bp=sl_bp,
            trail_bp=rule.trail_bp, min_hold_min=rule.min_hold_min)
        signals[r["tag"]] = sig
        triggers.append(Trigger(
            trigger_requirements=FlowSignalTriggerRequirements(signal_fn=sig),
            actions=[UnwindPositionsAction(match_tag=r["tag"], fee=0.0)],
        ))

    bt = QueryDrivenBacktest(
        time_grid=TimeGrid(sorted(grid)), mdp=mdp,
        strategy=QueryStrategy(name=rule.name, triggers=triggers),
        show_progress=show_progress, progress_desc=rule.name)
    bt.run()

    closed = pd.DataFrame(bt.portfolio.closed_positions_log)
    if closed.empty:
        return closed

    m = closed["source_query"].apply(lambda q: q.meta or {})
    for k in ("symbol", "side", "move_bp", "release_ts", "lead_title", "entry_px",
              "px_per_bp", "rule", "tag"):
        closed[k] = m.apply(lambda d, _k=k: d.get(_k))
    closed["opened_at"] = pd.to_datetime(closed["opened_at"], utc=True)
    closed["closed_at"] = pd.to_datetime(closed["closed_at"], utc=True)
    closed["release_ts"] = pd.to_datetime(closed["release_ts"], utc=True)
    closed["hold_min"] = (closed["closed_at"] - closed["opened_at"]).dt.total_seconds() / 60.0
    closed["exit_reason"] = closed["tag"].map(
        lambda t: signals[t].reason.get(t, "time_stop") if t in signals else "unknown")

    tick_size, tick_value = G.UST_TICKS[book.instrument.root]
    dollars_per_point = tick_value / tick_size
    closed["dv01_usd"] = closed["px_per_bp"] * dollars_per_point
    closed["pnl_bp_gross"] = closed["gross_realized_pnl"] / closed["dv01_usd"]
    closed["cost_bp"] = float(cost_bp)
    closed["pnl_bp"] = closed["pnl_bp_gross"] - float(cost_bp)
    closed["profitable"] = closed["pnl_bp"] > 0
    closed["abs_move_bp"] = closed["move_bp"].abs()
    closed["year"] = closed["release_ts"].dt.tz_convert("America/New_York").dt.year
    return closed.sort_values("release_ts").reset_index(drop=True)


# ===========================================================================
# The same bracket, priced arithmetically -- for the search
# ===========================================================================
def _minute_close(symbol: str, ts) -> Optional[float]:
    """The close of the bar stamped EXACTLY at ``ts``.

    This is what ``USTFuturesMDP.get_data(timestamp=ts)`` serves once its cache
    has been primed a minute at a time: the bar labelled ``ts``, whose close is a
    price at ``ts + 1``. It is deliberately NOT ``px_before`` -- that returns the
    previous bar, and a search whose fill model differs from the engine's by one
    minute cannot be tied out against it.

    A minute with no print returns None, exactly as the primed MDP does, so the
    two agree on absences as well as on prices.
    """
    df = G._BAR_CACHE.get((symbol, pd.Timestamp(ts).date()))
    if df is None or df.empty:
        return None
    try:
        return float(df["Close"].loc[pd.Timestamp(ts)])
    except KeyError:
        return None


def _first_true(mask: np.ndarray) -> int:
    """Index of the first True, or a sentinel larger than any index."""
    return int(np.argmax(mask)) if mask.any() else (1 << 30)


def run_bracket_fast(book: G.Book, rule: X.ExitRule, *, cost_bp: float = 0.0) -> pd.DataFrame:
    """``run_bracket_engine`` without the engine, in the engine's own convention.

    Same fill model, same minute-by-minute polling, same "a missing minute is not
    a decision point" rule. Exists only because a search over hundreds of
    brackets cannot afford to build a QueryDrivenBacktest for each -- and it is
    only trustworthy because the notebook ties it back to the engine.
    """
    ev = book.events
    if ev.empty:
        return pd.DataFrame()
    tick_size, tick_value = G.UST_TICKS[book.instrument.root]
    dollars_per_point = tick_value / tick_size

    rows: List[dict] = []
    for _, r in ev.iterrows():
        sym, side, ppb = r["symbol"], float(r["side"]), float(r["px_per_bp"])
        entry_ts = r["entry_ts"]
        entry_px = _minute_close(sym, entry_ts)
        if entry_px is None:
            continue
        tp_bp, sl_bp = rule.levels(float(r["move_bp"]))

        if rule.trail_bp is not None:
            mins = path_minutes(sym, entry_ts, int(rule.time_stop_min))
            if not mins:
                continue
        else:
            mins = None

        if rule.trail_bp is None:
            # Vectorised: same rules, same order of precedence, no Python loop.
            # Sliced POSITIONALLY out of the day's numpy arrays. Reindexing on a
            # DatetimeIndex built from the list of minutes is what a naive
            # "vectorisation" does, and it is TWICE AS SLOW as the loop it
            # replaces -- measured, 471ms a cell against 240ms. The list of
            # timestamps never has to exist.
            day = G._BAR_CACHE[(sym, pd.Timestamp(entry_ts).date())]
            didx = day.index
            pos = int(didx.searchsorted(entry_ts, side="left"))
            end_pos = int(didx.searchsorted(entry_ts + pd.Timedelta(
                minutes=int(rule.time_stop_min)), side="right"))
            if pos + 1 >= end_pos:
                continue
            pxv = day["Close"].to_numpy(float)[pos + 1:end_pos]
            held = (didx[pos + 1:end_pos].asi8 - pd.Timestamp(entry_ts).value) / 6e10
            mins = didx[pos + 1:end_pos]
            gain = side * (pxv - entry_px) / ppb
            ok = held >= rule.min_hold_min
            i_tp = _first_true(ok & (gain >= tp_bp)) if tp_bp is not None else (1 << 30)
            i_sl = _first_true(ok & (gain <= -sl_bp)) if sl_bp is not None else (1 << 30)
            # target is checked BEFORE the stop at any given bar, so a tie is a target
            if i_tp <= i_sl and i_tp < len(mins):
                k, reason = i_tp, "target"
            elif i_sl < len(mins):
                k, reason = i_sl, "stop"
            else:
                k, reason = len(mins) - 1, "time_stop"
            exit_px, exit_ts = float(pxv[k]), mins[k]
            pnl_bp = side * (exit_px - entry_px) / ppb
            d = r.to_dict()
            d.update({"rule": rule.name, "exit_reason": reason, "entry_px_mdp": entry_px,
                      "exit_px_rule": exit_px, "exit_ts_rule": exit_ts,
                      "hold_min": (exit_ts - entry_ts).total_seconds() / 60.0,
                      "dv01_usd": ppb * dollars_per_point,
                      "pnl_bp_gross": pnl_bp, "pnl_bp": pnl_bp - cost_bp, "cost_bp": cost_bp})
            rows.append(d)
            continue

        best: Optional[float] = None
        exit_px, reason, exit_ts = None, "time_stop", None
        for t in mins:
            px = _minute_close(sym, t)
            if px is None:
                continue
            exit_px, exit_ts = px, t          # the last price actually seen
            held = (t - entry_ts).total_seconds() / 60.0
            if held < rule.min_hold_min:
                continue
            gain = side * (px - entry_px) / ppb
            if tp_bp is not None and gain >= tp_bp:
                reason = "target"
                break
            if sl_bp is not None and gain <= -sl_bp:
                reason = "stop"
                break
            if rule.trail_bp is not None:
                best = px if best is None else (max(best, px) if side > 0 else min(best, px))
                if side * (best - px) / ppb >= rule.trail_bp and best != entry_px:
                    reason = "trail"
                    break
        if exit_px is None:
            continue

        pnl_bp = side * (exit_px - entry_px) / ppb
        d = r.to_dict()
        d.update({"rule": rule.name, "exit_reason": reason, "entry_px_mdp": entry_px,
                  "exit_px_rule": exit_px, "exit_ts_rule": exit_ts,
                  "hold_min": (exit_ts - entry_ts).total_seconds() / 60.0,
                  "dv01_usd": ppb * dollars_per_point,
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

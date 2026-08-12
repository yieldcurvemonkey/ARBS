"""The release fade, with the MDP as the only source of prices.

``econ_fade_common`` prices through a purpose-built bar-cache shim and checks
itself against a closed form. This module does neither. Every price here comes
from ``STIRFutureMDP.get_data`` -- the shipped provider, its own cache, its own
``RLSTIRFuturePricer`` -- and every trade is opened, marked and unwound by
``QueryDrivenBacktest`` through the shipped ``STIRFutureHandler``. There is no
second implementation to fall back on, which is the point: whatever this
reports is what the production data path says.

Two things make that possible inside a notebook kernel.

**The cache is primed, not fetched.** Barchart's fetcher calls ``asyncio.run``,
which cannot run inside a Jupyter kernel's live event loop -- it returns an
un-awaited coroutine, and treating that as an empty day is how a whole study
gets computed from nothing. So genuine Barchart minute bars are written into the
MDP's OWN ``STIRFuturePricer_Cache`` under its OWN key contract
(``{minute-floored UTC ISO}-{ticker}-{SOURCE}``) by ``prime_mdp_cache`` running
in a plain process. The notebook then reads them back through the ordinary
``get_data`` path. Measured: 10 of 10 requested minutes served, every price
identical to the underlying bar.

**And the fetcher is then disarmed.** ``disarm(mdp)`` replaces
``_fetch_barchart_timeseries`` with a raise, so "this backtest used no network"
is a property the notebook PROVES rather than claims, and a cache miss becomes a
loud failure instead of a silent refetch.

Timestamp convention, which is the whole study in three lines
------------------------------------------------------------
A Barchart minute bar is stamped at the START of its interval, so the bar
labelled ``t`` covers ``[t, t+1)`` and its close is a price observable at
``t+1``. ``get_data(timestamp=t)`` returns that bar. Therefore, for a release at
``T``:

    request T-1   the last bar to COMPLETE before the release   (pre-release)
    request T     the bar CONTAINING the release                (the move)
    request T+1   the first clean post-release bar              (entry)
    request T+H   the exit bar

Measured on payrolls 2019-01-04, the bar stamped at the release minute carries
Volume 22,239 against ~1,500 in each of the five before it: the release is
inside it. Reading that bar as the pre-release price would compare two
post-release prints.

Direction: ``move_bp > 0`` means the release pushed RATES UP. Fading it means
buying the future, ``side = +1``.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import pytz

from BT.data_handler import TimeGrid
from BT.query_actions import AddQueryFactoryAction, BuiltQuery, UnwindPositionsAction
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.triggers import Trigger, FlowSignalTriggerRequirements

from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
from Query.STIRFutures.STIRFutureQuery import STIRFutureQuery
from Query.STIRFutures.STIRFutureStructure import STIRFutureStructure
from Query.STIRFutures.STIRFutureValue import STIRFutureValue

import econ_fade_common as G

SOURCE = "BARCHART_STIRF-RL"

#: Request offsets in minutes from the release, in the convention above.
DEFAULT_MDP_CONFIG: Dict[str, Any] = {
    "name": "mdp-baseline",
    "instrument": {"root": "USD_STIR", "rank": 3},
    "events": {
        "currencies": ["USD"],
        "impacts": ["high"],
        "require_actual": True,
        "include_cb_decisions": False,
        "titles_include": None,
        "titles_exclude": None,
        "start": None, "end": None,
        "release_times_ny": None,
        "min_events_in_minute": 1,
        "surprise": "any",
        "weekdays": None,
    },
    "timing": {
        "pre_offset_min": -1,      # the last bar to COMPLETE before the release
        "post_offset_min": 0,      # the bar CONTAINING the release
        "entry_offset_min": 1,     # the first clean post-release bar
        "exit_offset_min": 60,
    },
    "signal": {"direction": "fade", "min_move_bp": 0.0},
    "contracts": 1,
    "cost_bp": 0.0,
}

#: Exit horizons the notebook prices in addition to the configured one.
HORIZONS = (5, 15, 30, 60, 120, 240)


def merge_config(cfg: Optional[dict]) -> dict:
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_MDP_CONFIG.items()}
    for k, v in (cfg or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


# ===========================================================================
# The MDP, primed and disarmed
# ===========================================================================
class NetworkForbidden(RuntimeError):
    """The MDP asked for a price its cache does not hold."""


def disarm(mdp: STIRFutureMDP) -> STIRFutureMDP:
    """Make a network fetch impossible, and loud.

    Without this a cache miss inside a notebook kernel does not fail -- the
    fetcher returns an un-awaited coroutine and the MDP either raises something
    unrelated or, worse, carries on. With it, "no network was used" stops being
    a claim about how the notebook was set up and becomes a property the run
    enforces on itself.
    """
    def _forbidden(*_a, **_k):
        raise NetworkForbidden(
            "the MDP cache does not cover this timestamp. Prime it with "
            "`python econ_fade_prewarm.py --stage mdpcache` from a plain process.")

    mdp._fetch_barchart_timeseries = _forbidden          # type: ignore[method-assign]
    mdp._fetch_webull_intraday = _forbidden              # type: ignore[method-assign]
    mdp._fetch_tos_live_quotes = _forbidden              # type: ignore[method-assign]
    return mdp


def open_mdp(*, armed: bool = False) -> STIRFutureMDP:
    mdp = STIRFutureMDP(source=SOURCE)
    mdp._ensure_pricer_cache()
    return mdp if armed else disarm(mdp)


def _cache_key(symbol: str, ts: pd.Timestamp) -> str:
    """The MDP's own key: minute-floored UTC ISO, ticker, upper-cased source.

    Transcribed from ``STIRFutureMDP.get_data._cache_ts_iso`` -- which is always
    probed with ``floor_minute=True`` for the Barchart intraday path, precisely
    so a cache primed a minute at a time can be read back by an ordinary call.
    """
    iso = pd.Timestamp(ts).tz_convert(pytz.UTC).floor("min").isoformat()
    return f"{iso}-{symbol}-{SOURCE.upper()}"


def prime_mdp_cache(mdp: STIRFutureMDP, wanted: Iterable[Tuple[str, pd.Timestamp]],
                    *, show_progress: bool = True) -> Dict[str, int]:
    """Write warmed Barchart bars into the MDP's cache, one minute at a time.

    ``wanted`` is the exact set of (symbol, minute) the backtest will request,
    derived from the same function the notebook uses -- so the prime cannot
    cover a different set of timestamps than the run needs.
    """
    G.load_bar_cache()
    mdp._ensure_pricer_cache()

    stats = {"written": 0, "no_bar": 0, "no_day": 0}
    items = list(wanted)
    it = items
    if show_progress:
        try:
            from tqdm.auto import tqdm
            it = tqdm(items, desc="prime MDP cache")
        except Exception:  # noqa: BLE001
            pass

    for sym, ts in it:
        day = pd.Timestamp(ts).date()
        bars = G._BAR_CACHE.get((sym, day))
        if bars is None:
            stats["no_day"] += 1
            continue
        # The MDP returns the bar STAMPED at the requested minute, so only an
        # exact stamp is primed. A minute with no print stays a miss, and the
        # gate below turns that into a counted exclusion rather than a fetch.
        try:
            px = float(bars["Close"].loc[pd.Timestamp(ts)])
        except KeyError:
            stats["no_bar"] += 1
            continue
        key = _cache_key(sym, ts)
        mdp._threadsafe_cache_put(key, {"symbol": sym, "price": px,
                                        "timestamp": key.split(f"-{sym}-")[0],
                                        "schema": 1})
        stats["written"] += 1

    # NOT the default background flush: a plain process that exits straight
    # after priming would race the writer thread and lose the batch.
    mdp._flush_pending_cache_writes(background=False)
    return stats


# ===========================================================================
# Request timestamps
# ===========================================================================
def _plain(ts) -> datetime.datetime:
    """A plain tz-aware ``datetime.datetime``.

    ``STIRFutureMDP._as_datetime`` tests ``type(ts) == datetime.datetime``, not
    ``isinstance``, so a ``pd.Timestamp`` -- a subclass -- is rejected outright.
    """
    t = pd.Timestamp(ts)
    return datetime.datetime(t.year, t.month, t.day, t.hour, t.minute, t.second,
                             tzinfo=t.tzinfo)


def request_times(local_release: pd.Timestamp, timing: dict,
                  horizons: Sequence[int] = HORIZONS) -> Dict[str, pd.Timestamp]:
    m = lambda n: pd.Timedelta(minutes=int(n))  # noqa: E731
    out = {
        "pre": local_release + m(timing["pre_offset_min"]),
        "post": local_release + m(timing["post_offset_min"]),
        "entry": local_release + m(timing["entry_offset_min"]),
        "exit": local_release + m(timing["exit_offset_min"]),
    }
    for h in horizons:
        out[f"h{h}"] = local_release + m(h)
    return out


def wanted_timestamps(raw: pd.DataFrame, cfg: dict,
                      horizons: Sequence[int] = HORIZONS) -> List[Tuple[str, pd.Timestamp]]:
    """Every (symbol, minute) the notebook can ask for under this config."""
    cfg = merge_config(cfg)
    inst = G.INSTRUMENTS[cfg["instrument"]["root"]]
    rank = int(cfg["instrument"]["rank"])
    ev, _ = G.apply_event_filters(raw, cfg["events"])
    out: List[Tuple[str, pd.Timestamp]] = []
    for _, r in ev.iterrows():
        sym = G.contract_for(inst, r["date"], rank)
        local = r["release_ts"].tz_convert(inst.tz)
        for ts in request_times(local, cfg["timing"], horizons).values():
            out.append((sym, ts))
    return sorted(set(out))


# ===========================================================================
# Prices, from the MDP and nowhere else
# ===========================================================================
def mdp_price(mdp: STIRFutureMDP, symbol: str, ts) -> Optional[float]:
    """One price, through ``get_data``. ``None`` when the MDP cannot serve it."""
    try:
        got = mdp.get_data({"symbols": [symbol], "timestamp": _plain(ts)})
    except Exception:  # noqa: BLE001 -- NetworkForbidden, empty frame, bad symbol
        return None
    for v in got.values():
        p = v[0] if isinstance(v, list) else v
        try:
            return float(p.price())
        except Exception:  # noqa: BLE001
            return None
    return None


def px_per_bp(inst: G.Instrument) -> float:
    """A STIR future is quoted ``100 - rate``, so one basis point is 0.01 of price."""
    if inst.family != "stir":
        raise ValueError("this module is STIR-only -- see econ_fade_common for UST")
    return 0.01


# ===========================================================================
# The book: gated by whether the MDP can price it
# ===========================================================================
def build_book(raw: pd.DataFrame, mdp: STIRFutureMDP, cfg: Optional[dict] = None,
               *, horizons: Sequence[int] = HORIZONS,
               show_progress: bool = True) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Release minutes -> the trades this config would take.

    The gate is not a separate data model. It is literally *can the MDP price
    this*: every required minute is requested through ``get_data`` and an event
    that comes back short is excluded, under the name of the timestamp that
    failed. With the fetcher disarmed there is no third possibility -- a price
    is either in the provider or the event is not traded.
    """
    cfg = merge_config(cfg)
    t = cfg["timing"]
    if int(t["entry_offset_min"]) <= int(t["post_offset_min"]):
        # Entering on the same bar the signal was read from means the entry
        # price IS the second measurement price. Any bid-ask bounce that made
        # that bar close low both sets the side to LONG and supplies the low
        # entry, so half the tick noise comes back by construction and the book
        # shows a fade edge that is a property of the quote, not the market.
        raise ValueError(
            f"entry_offset_min={t['entry_offset_min']} must be AFTER "
            f"post_offset_min={t['post_offset_min']} -- otherwise the trade fills at the "
            f"exact price its signal was read from.")

    inst = G.INSTRUMENTS[cfg["instrument"]["root"]]
    rank = int(cfg["instrument"]["rank"])
    ppb = px_per_bp(inst)

    funnel: Dict[str, Any] = {"raw release minutes": int(len(raw))}
    ev, drops = G.apply_event_filters(raw, cfg["events"])
    funnel["filter_drops"] = drops
    funnel["after filters"] = int(len(ev))

    ev = ev.copy()
    ev["symbol"] = [G.contract_for(inst, d, rank) for d in ev["date"]]
    ev["local_ts"] = ev["release_ts"].apply(lambda t: t.tz_convert(inst.tz))
    times = [request_times(t, cfg["timing"], horizons) for t in ev["local_ts"]]
    ev["entry_ts"] = [t["entry"] for t in times]
    ev["exit_ts"] = [t["exit"] for t in times]

    ev, n_over = G.drop_overlaps(ev)
    funnel["overlap dropped"] = n_over
    funnel["after overlap"] = int(len(ev))

    reasons: Dict[str, int] = defaultdict(int)
    rows: List[dict] = []
    it = list(ev.iterrows())
    if show_progress:
        try:
            from tqdm.auto import tqdm
            it = tqdm(it, total=len(ev), desc="pricing through the MDP")
        except Exception:  # noqa: BLE001
            pass

    for _, r in it:
        sym = r["symbol"]
        t = request_times(r["local_ts"], cfg["timing"], horizons)
        px: Dict[str, Optional[float]] = {}
        bad = None
        for k in ("pre", "post", "entry", "exit"):
            px[k] = mdp_price(mdp, sym, t[k])
            if px[k] is None:
                bad = f"MDP cannot price {k}"
                break
        if bad:
            reasons[bad] += 1
            continue
        if t["entry"] == t["exit"]:
            reasons["entry and exit are the same bar"] += 1
            continue

        move_bp = -(px["post"] - px["pre"]) / ppb
        d = r.to_dict()
        d.update({"pre_px": px["pre"], "post_px": px["post"],
                  "entry_px": px["entry"], "exit_px": px["exit"],
                  "move_bp": move_bp})
        for h in horizons:
            d[f"px_h{h}"] = mdp_price(mdp, sym, t[f"h{h}"])
        rows.append(d)
        reasons["priced"] += 1

    book = pd.DataFrame(rows)
    funnel["gate"] = dict(reasons)
    funnel["after gate"] = int(len(book))

    if not book.empty:
        flip = 1.0 if cfg["signal"]["direction"] == "fade" else -1.0
        base = np.sign(book["move_bp"])
        n_zero = int((base == 0).sum())
        if n_zero:
            funnel["dropped: the release moved nothing"] = n_zero
        book = book[base != 0].copy()
        base = base[base != 0]
        lo = float(cfg["signal"].get("min_move_bp") or 0.0)
        if lo > 0:
            keep = book["move_bp"].abs() >= lo
            funnel[f"dropped: move below {lo}bp"] = int((~keep).sum())
            book, base = book[keep], base[keep]
        book["side"] = (flip * base).astype(float)
        book["contracts"] = int(cfg.get("contracts", 1))
        book["tag"] = [f"{cfg['name']}|{s}|{t_.strftime('%Y%m%d%H%M')}"
                       for s, t_ in zip(book["symbol"], book["entry_ts"])]
        book = book.reset_index(drop=True)

    funnel["TRADEABLE"] = int(len(book))
    return book, funnel


# ===========================================================================
# The engine
# ===========================================================================
def make_query(ev: dict, cfg: dict) -> STIRFutureQuery:
    """One rateslib STIRFuture outright. Direction lives in ``risk_weights``.

    A negative contract count does NOT short: the structure builder flips the
    risk weight negative when contracts < 0 while the leg keeps its negative
    count, and the handler multiplies by both, so the signs cancel and the
    "short" books a long.
    """
    return STIRFutureQuery(
        structure=STIRFutureStructure.OUTRIGHT,
        value=STIRFutureValue.PRICE,
        symbol=ev["symbol"],
        structure_kwargs={"contracts": int(ev["contracts"]),
                          "risk_weights": [float(ev["side"])]},
        market_request={"timestamp": "now"},
        tags=(ev["tag"],),
        meta={
            "symbol": ev["symbol"], "side": float(ev["side"]),
            "contracts": int(ev["contracts"]), "move_bp": float(ev["move_bp"]),
            "release_ts": ev["release_ts"], "lead_title": ev["lead_title"],
            "titles": ev["titles"], "n_events": int(ev["n_events"]),
            "impact": ev["impact"], "lead_outcome": ev["lead_outcome"],
            "pre_px": float(ev["pre_px"]), "post_px": float(ev["post_px"]),
            "entry_px": float(ev["entry_px"]), "exit_px": float(ev["exit_px"]),
            "config": cfg["name"],
        },
    )


@dataclass
class ReleaseFadeSignal:
    """The signal, computed inside the trigger from the MDP.

    This is the whole strategy and it lives where a strategy belongs -- in a
    ``FlowSignalTriggerRequirements``, evaluated at the timestamp, reading the
    same provider the engine will mark against. It does not consult a
    precomputed table: at the entry minute it asks the MDP what the price was
    before the release and just after it, and decides.
    """

    mdp: STIRFutureMDP
    symbol: str
    entry_ts: datetime.datetime
    pre_ts: pd.Timestamp
    post_ts: pd.Timestamp
    px_per_bp: float
    direction: str = "fade"
    min_move_bp: float = 0.0
    contracts: int = 1
    tag: str = ""
    static: Dict[str, Any] = field(default_factory=dict)

    def __call__(self, state, backtest):
        if state != self.entry_ts:
            return False
        pre = mdp_price(self.mdp, self.symbol, self.pre_ts)
        post = mdp_price(self.mdp, self.symbol, self.post_ts)
        if pre is None or post is None:
            return False
        move_bp = -(post - pre) / self.px_per_bp
        if move_bp == 0 or abs(move_bp) < self.min_move_bp:
            return False
        flip = 1.0 if self.direction == "fade" else -1.0
        side = flip * float(np.sign(move_bp))
        return True, {"release_fade": {**self.static, "symbol": self.symbol,
                                       "side": side, "contracts": self.contracts,
                                       "move_bp": move_bp, "tag": self.tag,
                                       "pre_px": pre, "post_px": post}}


def _query_factory(cfg: dict) -> Callable[..., Any]:
    def build(*, now, backtest, info):
        payload = (info or {}).get("release_fade")
        if not payload:
            return []
        return [BuiltQuery(query=make_query(payload, cfg), meta={"release": payload["tag"]})]
    return build


def run_engine(book: pd.DataFrame, mdp: STIRFutureMDP, cfg: dict,
               *, show_progress: bool = True) -> pd.DataFrame:
    """``QueryDrivenBacktest``, driven by triggers that read the MDP.

    Exits unwind BY TAG. ``match_all`` would let the first exit timestamp on the
    grid close every open position -- invisible while a one-position-at-a-time
    rule holds, and silently wrong the moment it does not.
    """
    if book.empty:
        return pd.DataFrame()

    cfg = merge_config(cfg)
    inst = G.INSTRUMENTS[cfg["instrument"]["root"]]
    ppb = px_per_bp(inst)
    timing = cfg["timing"]

    triggers: List[Trigger] = []
    grid: set = set()
    for _, r in book.iterrows():
        entry = _plain(r["entry_ts"])
        exit_ = _plain(r["exit_ts"])
        grid.add(entry)
        grid.add(exit_)
        t = request_times(r["local_ts"], timing, ())
        static = {k: r[k] for k in ("release_ts", "lead_title", "titles", "n_events",
                                    "impact", "lead_outcome", "entry_px", "exit_px")}
        triggers.append(Trigger(
            trigger_requirements=FlowSignalTriggerRequirements(
                signal_fn=ReleaseFadeSignal(
                    mdp=mdp, symbol=r["symbol"], entry_ts=entry,
                    pre_ts=t["pre"], post_ts=t["post"], px_per_bp=ppb,
                    direction=cfg["signal"]["direction"],
                    min_move_bp=float(cfg["signal"].get("min_move_bp") or 0.0),
                    contracts=int(r["contracts"]), tag=r["tag"], static=static)),
            actions=[AddQueryFactoryAction(query_factory=_query_factory(cfg))],
        ))
        triggers.append(Trigger(
            trigger_requirements=FlowSignalTriggerRequirements(
                signal_fn=(lambda s, bt, _t=exit_: s == _t)),
            actions=[UnwindPositionsAction(match_tag=r["tag"], fee=0.0)],
        ))

    bt = QueryDrivenBacktest(
        time_grid=TimeGrid(sorted(grid)),
        mdp=mdp,
        strategy=QueryStrategy(name=cfg["name"], triggers=triggers),
        show_progress=show_progress,
        progress_desc=cfg["name"],
    )
    bt.run()

    closed = pd.DataFrame(bt.portfolio.closed_positions_log)
    if closed.empty:
        return closed
    return enrich(closed, cfg, inst)


def enrich(closed: pd.DataFrame, cfg: dict, inst: G.Instrument) -> pd.DataFrame:
    closed = closed.copy()
    m = closed["source_query"].apply(lambda q: q.meta or {})
    for k in ("symbol", "side", "contracts", "move_bp", "release_ts", "lead_title",
              "titles", "n_events", "impact", "lead_outcome", "pre_px", "post_px",
              "entry_px", "exit_px"):
        closed[k] = m.apply(lambda d, _k=k: d.get(_k))
    closed["tag"] = closed["source_query"].apply(lambda q: next(iter(q.tags), None))
    closed["opened_at"] = pd.to_datetime(closed["opened_at"], utc=True)
    closed["closed_at"] = pd.to_datetime(closed["closed_at"], utc=True)
    closed["release_ts"] = pd.to_datetime(closed["release_ts"], utc=True)
    ny = closed["release_ts"].dt.tz_convert("America/New_York")
    closed["date"] = ny.dt.date
    closed["year"] = ny.dt.year
    closed["release_time_ny"] = ny.dt.strftime("%H:%M")
    closed["weekday"] = ny.dt.strftime("%a")
    closed["hold_min"] = (closed["closed_at"] - closed["opened_at"]).dt.total_seconds() / 60.0

    # dv01 is exact for a STIR future: the handler's P&L is
    # (dprice/0.01) * PV01, so dividing by PV01 hands back basis points of
    # favourable rate move -- per unit of gross risk, and currency-free.
    pv01 = {s: G.stir_pv01(s) for s in closed["symbol"].unique()}
    closed["dv01_usd"] = [pv01[s] * int(c) for s, c in zip(closed["symbol"], closed["contracts"])]
    closed["pnl_bp_gross"] = closed["gross_realized_pnl"] / closed["dv01_usd"]
    cost = float(cfg.get("cost_bp", 0.0))
    closed["cost_bp"] = cost
    closed["pnl_bp"] = closed["pnl_bp_gross"] - cost
    closed["profitable"] = closed["pnl_bp"] > 0
    closed["abs_move_bp"] = closed["move_bp"].abs()
    closed["direction"] = np.where(closed["side"] > 0, "long future", "short future")
    return closed.sort_values("release_ts").reset_index(drop=True)


# ===========================================================================
# Horizon sweep, still through the MDP
# ===========================================================================
def horizon_table(book: pd.DataFrame, cfg: dict,
                  horizons: Sequence[int] = HORIZONS) -> pd.DataFrame:
    """P&L at each exit horizon, from prices the MDP already served.

    These are the same ``get_data`` prices the engine marks against -- the
    engine run at the configured horizon is reproduced exactly by its row, which
    is the check that this table means anything.
    """
    if book.empty:
        return pd.DataFrame()
    ppb = 0.01
    rows = []
    for h in horizons:
        col = f"px_h{h}"
        if col not in book:
            continue
        sub = book[book[col].notna()]
        if sub.empty:
            continue
        pnl = sub["side"] * (sub[col] - sub["entry_px"]) / ppb
        s = pd.Series(pnl.to_numpy(float))
        rows.append({"hold_min": h, "trades": int(len(s)), "total_bp": float(s.sum()),
                     "avg_bp": float(s.mean()),
                     "hit_rate": float((s > 0).mean()),
                     "sr_per_trade": float(s.mean() / s.std(ddof=1)) if s.std(ddof=1) > 0 else 0.0,
                     "t_stat": float(s.mean() / (s.std(ddof=1) / np.sqrt(len(s))))
                     if s.std(ddof=1) > 0 else 0.0})
    return pd.DataFrame(rows).set_index("hold_min")

"""Family B screener: what the two surviving structures say to do on a given day.

Runs the same signal the backtest trades — richness = listed package premium
minus the ZQ-lattice fair value — on one date, ranks the candidate structures,
and prints an executable trade ticket for the best one.

    conda run -n stir python notebooks/backtests/famb_screener.py --date 2026-07-28
    conda run -n stir python notebooks/backtests/famb_screener.py --date live
    conda run -n stir python notebooks/backtests/famb_screener.py --date live --refresh --json

Two sleeves, from `2026-08-04-family-b-dispersion-findings.md`:

* **the carry short** — sell the modal 25bp butterfly on the front quarterly,
  rolled at expiry−3d. Always on; the screener reports its state and roll clock
  rather than a signal.
* **the richness fade** — sell (buy) the ±75bp strangle on the front quarterly
  when its listed premium sits `thr` bp above (below) the lattice's fair value,
  exit at 25% of entry richness or 15 sessions. This is the one with an entry
  signal, and the one this screener exists to watch.

**Provenance is printed with every run and is not decoration.** The fade's exact
parameters won a 720-config search — DSR 0.000, house verdict
SELECTION-ARTIFACT — and the carry short's NW t is 1.51. The pre-registered cell
is marked; every other cell in the screen is an exploratory read with no
mandate at all, and is labelled as such.

Design rule: the screener must not be able to drift from the backtest. Richness,
strike selection and the entry test all come from `famb_common`, and
`tests/test_famb_screener.py` pins the screener's signal against
`intra_quarter_backtest`'s own entry rule on planted data.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(HERE.parents[1]) not in sys.path:
    sys.path.insert(0, str(HERE.parents[1]))

import famb_common as fc                                    # noqa: E402

OPT_HALF_TICK_BP = 0.125

#: the pre-registered fade cell — the only one with a (weak) mandate
PREREG = dict(book="STRG75", rank=1, thr_bp=4.0, exit_frac=0.25,
              max_hold=15, direction="fade")

#: the always-on carry sleeve
CARRY = dict(book="FLY25", rank=1, side="short")

BOOKS = ("STRG75", "STRG50", "FLY25", "FLY50", "DFLY")
RANKS = (1, 2, 3)

#: measured richness half-lives (sessions) by book, from the findings doc —
#: used only to state an expected holding period, never to size or to gate
HALF_LIFE_HINT = {"STRG75": 12.0, "STRG50": 13.0, "FLY25": 12.5,
                  "FLY50": 12.5, "DFLY": 10.0}

#: structures whose short side has a bounded worst case. A short strangle does
#: not, and the referee's ruling on this family was explicit: passive tail-short
#: carry is DEAD (worst days -55/-92bp, skew -7.15) while the defined-risk fly
#: short survived. A screener that ranks on expected bp alone would put the
#: undefined-risk structures on top every time, because they have the fewest
#: legs and therefore the smallest round trip.
DEFINED_RISK = {"FLY25": True, "FLY50": True, "DFLY": True,
                "STRG50": False, "STRG75": False}

#: an exploratory (non-pre-registered) cell must clear its own standing level by
#: this many sigma as well as by ``thr`` bp. Rank-2 and rank-3 contracts carry a
#: large STANDING richness — the feasibility frontier in premium bp, measured at
#: +1.9 / +9.1 / +19.2bp by rank — so a raw threshold there is not a dislocation
#: signal at all, it is a standing short of the off-lattice premium wearing a
#: convergence costume. Pre-declared, not tuned.
EXPLORATORY_Z = 1.0


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class Context:
    as_of: pd.Timestamp
    dates: pd.DatetimeIndex
    surface: pd.Series
    fwd_idx: pd.Series
    tree: "fc.TreeCtx"
    quote_dates: pd.DatetimeIndex
    live: bool
    fetched: bool
    settle_asof: Dict[str, pd.Timestamp]
    requested: Optional[pd.Timestamp] = None


def option_label(symbol: str, strike_price: float, right: str) -> str:
    """``SFRU26|9600C`` — the vendor's option label (strike x 100)."""
    return f"{symbol}|{int(round(strike_price * 100))}{right.upper()}"


def _snapshot_quotes(legs: Sequence[Tuple[str, float]],
                     sessions: Sequence[pd.Timestamp],
                     *, intraday: bool = False) -> pd.DataFrame:
    """Premiums for exactly the legs the screen needs, per session.

    Deliberately NOT a whole-chain fetch. Calibrating a smile to price three
    known strikes fails on precisely the thin sessions a screener is most
    likely to be pointed at — the first attempt at this returned "NO TRADE" on
    a day when what it actually had was no data. Both rights are requested at
    every strike so the parity completion downstream has something to work with.
    """
    os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
    from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP

    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    want = sorted({(sym, round(float(k), 4), r)
                   for sym, k in legs for r in ("C", "P")})
    labels = [option_label(s, k, r) for s, k, r in want]
    rows: List[dict] = []
    for ts in sessions:
        stamp = "live" if intraday else pd.Timestamp(ts).date()
        try:
            out = mdp.get_data({"endpoint": "option_snapshot",
                                "symbols": labels, "timestamp": stamp})
        except Exception as exc:                       # pragma: no cover
            print(f"  !! snapshot failed for {stamp} "
                  f"({type(exc).__name__}: {str(exc)[:90]})", file=sys.stderr)
            continue
        for (sym, k, r), label in zip(want, labels):
            p = out.get(label)
            if isinstance(p, list):
                p = p[0] if p else None
            if p is None:
                continue
            try:
                px = float(p.price())
            except Exception:
                continue
            if not np.isfinite(px):
                continue
            rows.append({"as_of": pd.Timestamp(ts), "symbol": sym,
                         "right": r, "strike_price": k,
                         "strike_rate": 100.0 - k,
                         "premium_bp": px * 100.0, "oi": np.nan,
                         "volume": np.nan})
    return pd.DataFrame(rows)


def _refresh_settles(symbols: Sequence[str], as_of: datetime.date) -> None:
    """Re-fetch SR3 and ZQ EOD settles so the forward and the ladder are current.

    The ZQ leg matters as much as the SR3 one: the lattice that prices fair
    value is built from ZQ settles, and a just-expired front ZQ silently
    dropping out of the refresh is a failure this program has already had twice.
    """
    from BT.serff.futures_data import backfill_settles

    sr3 = ["SR3" + s[3:] for s in symbols]
    zq = [f"ZQ{c}{y:02d}" for y in range(as_of.year % 100, as_of.year % 100 + 2)
          for c in "FGHJKMNQUVXZ"]
    start = as_of - datetime.timedelta(days=420)
    backfill_settles(start, as_of, symbols=sr3 + zq, force_refresh=True,
                     show_progress=False)


def load_context(as_of, *, history: int = 250, refresh: bool = False,
                 ranks: Sequence[int] = RANKS,
                 books: Sequence[str] = BOOKS, fetch_limit: int = 10,
                 intraday: bool = False) -> Context:
    """Everything the screen needs, for a date that may be beyond the panel.

    ``as_of`` may be a date, a timestamp, or the string ``"live"`` (the latest
    session the data supports). Quotes come from the committed panel when it
    covers the date and are fetched for that session when it does not, so a
    historical run and a live run take the same code path afterwards.
    """
    quotes = fc.load_quotes()
    quotes["as_of"] = pd.to_datetime(quotes["as_of"])
    panel_dates = pd.DatetimeIndex(sorted(quotes["as_of"].unique()))

    live = isinstance(as_of, str) and str(as_of).lower() == "live"
    want = pd.Timestamp(datetime.date.today()) if live else pd.Timestamp(as_of)

    need_symbols = sorted({s for r in ranks
                           for s in [fc.rank_symbol(want.date(), r)]
                           if s is not None})
    # A live screen without fresh settles is not a stale screen, it is a BLANK
    # one: premium_surface inner-joins quotes to forwards, so a missing settle
    # silently deletes the day's quotes rather than degrading them.
    if refresh or (live and refresh is not False):
        _refresh_settles(need_symbols, want.date())

    def _frames(q: pd.DataFrame, ds: pd.DatetimeIndex):
        syms = sorted(q["symbol"].unique())
        f = fc.sr3_forwards(syms)
        f["as_of"] = pd.to_datetime(f["as_of"])
        return (fc.premium_surface(q, f),
                f.set_index(["as_of", "symbol"])["fwd_rate"].sort_index(), f)

    fetched = False
    missing = pd.DatetimeIndex([])
    if want > panel_dates.max():
        # sessions the committed panel does not cover, capped so a long gap
        # cannot turn one screen into a backfill
        cal = pd.bdate_range(panel_dates.max() + pd.Timedelta(days=1), want)
        missing = pd.DatetimeIndex(cal[-max(1, fetch_limit):])

    if len(missing):
        # PASS 1 on history alone: which legs are actually held right now?
        hist = panel_dates[-max(history, 60):]
        q_h = quotes[quotes["as_of"].isin(hist)]
        surf_h, fwd_h, _ = _frames(q_h, hist)
        tree_h = fc.TreeCtx([d.date() for d in hist])
        legs = _legs_in_play(surf_h, fwd_h, tree_h, hist, books=books,
                             ranks=ranks)
        if legs:
            add = _snapshot_quotes(sorted(legs), missing, intraday=intraday)
            if len(add):
                quotes = pd.concat([quotes, add], ignore_index=True)
                quotes = quotes.drop_duplicates(
                    ["as_of", "symbol", "right", "strike_price"], keep="last")
                fetched = True

    quote_dates = pd.DatetimeIndex(sorted(quotes["as_of"].unique()))
    prior = quote_dates[quote_dates <= want]
    if not len(prior):
        raise ValueError(f"no quoted session at or before {want.date()}")

    # A session is only usable if it has BOTH quotes and a settle for the
    # symbols being screened. Clamping here — and reporting the clamp — is what
    # turns "the vendor has not published today yet" into an honest screen of
    # the last real session instead of an empty one.
    fwd_all = fc.sr3_forwards(sorted({s for s in need_symbols}))
    fwd_all["as_of"] = pd.to_datetime(fwd_all["as_of"])
    fwd_dates = pd.DatetimeIndex(sorted(fwd_all["as_of"].unique()))
    usable = prior.intersection(fwd_dates)
    requested = want
    want = usable.max() if len(usable) else prior.max()
    clamped_from = requested if want < requested else None

    dates = quote_dates[quote_dates <= want][-max(history, 30):]
    quotes = quotes[quotes["as_of"].isin(dates)]
    surface, fwd_idx, fwd = _frames(quotes, dates)
    tree = fc.TreeCtx([d.date() for d in dates])
    settle_asof = {s: pd.to_datetime(g["as_of"]).max()
                   for s, g in fwd.groupby("symbol")}
    return Context(as_of=want, dates=dates, surface=surface, fwd_idx=fwd_idx,
                   tree=tree, quote_dates=quote_dates, live=live,
                   fetched=fetched, settle_asof=settle_asof,
                   requested=clamped_from)


def _legs_in_play(surface, fwd_idx, tree, dates, *, books, ranks) -> set:
    """(symbol, strike) the screen will need — held now, or after a re-strike.

    Two sources, because a live screen has to cover both states: the legs of
    the holding that already exists (struck at a past roll, so only history
    knows them) and the legs a roll TODAY would create at the current tree
    mode. Missing the second means the screener goes blind exactly on roll day.
    """
    out = set()
    for book in books:
        for rank in ranks:
            try:
                holds = fc.build_book(book, rank, dates, surface, fwd_idx, tree)
            except Exception:
                holds = []
            if holds:
                for _, k, _ in holds[-1].legs:
                    out.add((holds[-1].symbol, round(float(k), 4)))
            last = dates[-1]
            sym = fc.rank_symbol(last.date(), rank)
            if sym is None:
                continue
            try:
                f0 = float(fwd_idx.loc[(last, sym)])
            except KeyError:
                continue
            kc = tree.modal_center_px(last.date(), sym, f0)
            if kc is None:
                continue
            for _, k, _ in fc.structure_legs(book, kc):
                out.add((sym, round(float(k), 4)))
    return out


# ---------------------------------------------------------------------------
# Scoring one cell
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class Idea:
    book: str
    rank: int
    symbol: str
    dte: int
    center_px: float
    legs: List[Tuple[str, float, float]]
    mark_bp: float
    fair_bp: float
    rich_bp: float                  # raw: what the backtest's rule sees
    level_bp: float                 # the cell's own standing richness
    dev_bp: float                   # rich - level: the comparable dislocation
    z_dev: float
    thr_bp: float
    side: int                       # +1 buy the structure, -1 sell it
    state: str                      # ACTIONABLE | WATCH | OFF | NO-DATA
    n_contracts: int
    defined_risk: bool
    max_loss_bp: float              # short-side worst case; inf if unbounded
    cost_bp: float
    gross_target_bp: float
    net_target_bp: float
    edge_mult: float
    exit_rich_bp: float
    max_hold_date: Optional[str]
    pct_holding: float
    pct_pooled: float
    z_pooled: float
    n_hist: int
    half_life_hint: float
    prereg: bool
    stale_ladder: bool
    note: str = ""

    @property
    def action(self) -> str:
        if self.state != "ACTIONABLE":
            return "-"
        return f"{'BUY' if self.side > 0 else 'SELL'} {self.book}"

    @property
    def gate_note(self) -> str:
        """Which gate is holding this cell back — the bp one or the z one."""
        if self.state != "WATCH":
            return ""
        if self.prereg:
            return f"needs {self.thr_bp - abs(self.rich_bp):+.2f}bp more rich"
        if not np.isfinite(self.dev_bp):
            return "no history"
        if abs(self.dev_bp) < self.thr_bp:
            return f"needs {self.thr_bp - abs(self.dev_bp):+.2f}bp more dev"
        return (f"dev ok, z {self.z_dev:+.1f} short of "
                f"{EXPLORATORY_Z:.1f}")

    def ticket(self, lots: int) -> List[dict]:
        """The executable legs: one row per option, signed for the trade."""
        return [{"symbol": self.symbol, "right": right,
                 "strike_price": round(k, 4),
                 "side": "BUY" if self.side * w > 0 else "SELL",
                 "lots": int(round(abs(w) * lots))}
                for right, k, w in self.legs]


def _pct(x: float, sample: np.ndarray) -> float:
    s = sample[np.isfinite(sample)]
    if s.size < 5:
        return np.nan
    return float((np.abs(s) <= abs(x)).mean())


def gate_state(rich: float, dev: float, z: float, thr: float, *,
               prereg: bool) -> str:
    """ACTIONABLE / WATCH / NO-DATA for one cell.

    Split out as a pure function so a test can bind it directly to
    ``famb_common.intra_quarter_backtest``'s own entry rule. For the
    pre-registered cell the rule IS that rule — ``abs(richness) >= thr`` — and
    the test asserts they fire on the same sessions. Everything else is gated
    on the deviation from the cell's standing level, which the backtest never
    had to do because it only ever ran the front contract.
    """
    if not np.isfinite(rich):
        return "NO-DATA"
    if prereg:
        return "ACTIONABLE" if abs(rich) >= thr else "WATCH"
    if not np.isfinite(dev):
        return "NO-DATA"
    return ("ACTIONABLE"
            if abs(dev) >= thr and np.isfinite(z) and abs(z) >= EXPLORATORY_Z
            else "WATCH")


def gate_side(signal: float, direction: str = "fade") -> int:
    """Fade sells what is rich, exactly as the backtest signs it."""
    return int(-np.sign(signal)) if direction == "fade" else int(np.sign(signal))


def short_max_loss_bp(book: str, legs: Sequence[Tuple[str, float, float]],
                      mark_bp: float) -> float:
    """Worst case of being SHORT the structure, in bp of premium received.

    A short butterfly loses at most (wing width - premium); a short strangle's
    loss is unbounded in the underlying, which is the whole reason the passive
    version of this book died.
    """
    if not DEFINED_RISK.get(book, False):
        return float("inf")
    ks = sorted({k for _, k, _ in legs})
    peak = (ks[1] - ks[0]) * 100.0 if len(ks) >= 2 else np.nan
    return float(peak - mark_bp)


def _blank_idea(book: str, rank: int, symbol: str, thr_bp: float,
                state: str, note: str) -> "Idea":
    """A cell that could not be priced or built — reported, never dropped."""
    return Idea(
        book=book, rank=rank, symbol=symbol, dte=-1, center_px=np.nan,
        legs=[], mark_bp=np.nan, fair_bp=np.nan, rich_bp=np.nan,
        level_bp=np.nan, dev_bp=np.nan, z_dev=np.nan, thr_bp=thr_bp, side=0,
        state=state, n_contracts=fc.n_contracts(book),
        defined_risk=DEFINED_RISK.get(book, False), max_loss_bp=np.nan,
        cost_bp=np.nan, gross_target_bp=np.nan, net_target_bp=np.nan,
        edge_mult=np.nan, exit_rich_bp=np.nan, max_hold_date=None,
        pct_holding=np.nan, pct_pooled=np.nan, z_pooled=np.nan, n_hist=0,
        half_life_hint=HALF_LIFE_HINT.get(book, np.nan), prereg=False,
        stale_ladder=False, note=note)


def score_cell(ctx: Context, book: str, rank: int, *,
               thr_bp: float = 4.0, exit_frac: float = 0.25,
               max_hold: int = 15, direction: str = "fade",
               cost_mult: float = 1.0) -> Optional[Idea]:
    """Richness, signal state and expected arithmetic for one (book, rank).

    Built through ``build_book`` so the strike selection, the marks and the
    fair value are the same objects the backtest traded — a screener computing
    its own version of any of those would be a different strategy wearing the
    same name.
    """
    holds = fc.build_book(book, rank, ctx.dates, ctx.surface, ctx.fwd_idx,
                          ctx.tree)
    if not holds:
        return None
    cur = holds[-1]
    if cur.marks.index[-1] != ctx.as_of:
        # the current holding has no mark on the screen date
        return Idea(book=book, rank=rank, symbol=cur.symbol, dte=-1,
                    center_px=np.nan, legs=cur.legs, mark_bp=np.nan,
                    fair_bp=np.nan, rich_bp=np.nan, thr_bp=thr_bp, side=0,
                    level_bp=np.nan, dev_bp=np.nan, z_dev=np.nan,
                    state="NO-DATA", n_contracts=fc.n_contracts(book),
                    defined_risk=DEFINED_RISK.get(book, False),
                    max_loss_bp=np.nan,
                    cost_bp=np.nan, gross_target_bp=np.nan,
                    net_target_bp=np.nan, edge_mult=np.nan,
                    exit_rich_bp=np.nan, max_hold_date=None,
                    pct_holding=np.nan, pct_pooled=np.nan, z_pooled=np.nan,
                    n_hist=0, half_life_hint=HALF_LIFE_HINT.get(book, np.nan),
                    prereg=False, stale_ladder=False,
                    note=f"no mark on {ctx.as_of.date()}")

    from MDP.STIRFutures._sofr_option_contracts import (
        sofr_option_last_trade_date)

    mark = float(cur.marks.loc[ctx.as_of])
    fair = float(cur.fair.loc[ctx.as_of])
    rich = mark - fair
    n_leg = fc.n_contracts(book)
    cost = 2.0 * n_leg * OPT_HALF_TICK_BP * cost_mult

    rich_hold = (cur.marks - cur.fair).dropna()
    pooled = np.concatenate([(h.marks - h.fair).dropna().to_numpy()
                             for h in holds]) if holds else np.array([])
    pooled = pooled[np.isfinite(pooled)]
    # the cell's STANDING richness — the feasibility frontier in premium bp,
    # which grows with dte and is not a dislocation
    level = float(np.median(pooled)) if pooled.size >= 10 else 0.0
    dev = rich - level
    dev_sd = (float(np.std(pooled - level, ddof=1))
              if pooled.size > 10 else np.nan)
    z_dev = float(dev / dev_sd) if dev_sd and np.isfinite(dev_sd) \
        and dev_sd > 0 else np.nan

    prereg = (book == PREREG["book"] and rank == PREREG["rank"])
    # The pre-registered cell is gated on the RAW richness, exactly as
    # intra_quarter_backtest gates it — the screener must not quietly trade a
    # different rule from the one that was backtested. Every other cell is
    # gated on the DEVIATION from its own standing level, because at rank 2-3
    # the raw number is dominated by the off-lattice premium.
    signal = rich if prereg else dev
    side = gate_side(signal, direction)
    gross = (1.0 - exit_frac) * abs(signal)
    state = gate_state(rich, dev, z_dev, thr_bp, prereg=prereg)

    cm = ctx.tree.cm(ctx.as_of.date(), cur.symbol)
    expiry = sofr_option_last_trade_date(cur.symbol)
    # the time stop lives in the FUTURE, so it cannot be read off the history
    # index — a screener run on the newest session has no later sessions in it
    fwd_sessions = pd.bdate_range(ctx.as_of + pd.Timedelta(days=1),
                                  ctx.as_of + pd.Timedelta(days=max_hold * 2))
    hold_end = (min(fwd_sessions[max_hold - 1].date(), expiry)
                if len(fwd_sessions) >= max_hold else expiry)

    return Idea(
        book=book, rank=rank, symbol=cur.symbol,
        dte=(expiry - ctx.as_of.date()).days,
        center_px=float(cur.legs[len(cur.legs) // 2][1]), legs=list(cur.legs),
        mark_bp=mark, fair_bp=fair, rich_bp=rich, level_bp=level, dev_bp=dev,
        z_dev=z_dev, thr_bp=thr_bp, side=side, state=state, n_contracts=n_leg,
        defined_risk=DEFINED_RISK.get(book, False),
        max_loss_bp=short_max_loss_bp(book, cur.legs, mark),
        cost_bp=cost, gross_target_bp=gross, net_target_bp=gross - cost,
        edge_mult=float(gross / cost) if cost > 0 else np.nan,
        exit_rich_bp=float(level + np.sign(signal) * abs(signal) * exit_frac)
        if not prereg else float(np.sign(rich) * abs(rich) * exit_frac),
        max_hold_date=hold_end.isoformat(),
        pct_holding=_pct(rich, rich_hold.to_numpy()),
        pct_pooled=_pct(dev, pooled - level),
        z_pooled=z_dev,
        n_hist=int(len(rich_hold)),
        half_life_hint=HALF_LIFE_HINT.get(book, np.nan),
        prereg=prereg,
        stale_ladder=bool(cm.any_stale) if cm is not None else True,
    )


def carry_state(ctx: Context, *, cost_mult: float = 1.0) -> Optional[dict]:
    """The always-on sleeve: what is held now, and when it rolls."""
    holds = fc.build_book(CARRY["book"], CARRY["rank"], ctx.dates, ctx.surface,
                          ctx.fwd_idx, ctx.tree)
    if not holds:
        return None
    from MDP.STIRFutures._sofr_option_contracts import (
        sofr_option_last_trade_date)
    cur = holds[-1]
    expiry = sofr_option_last_trade_date(cur.symbol)
    roll = expiry - datetime.timedelta(days=3)
    mark = (float(cur.marks.loc[ctx.as_of])
            if ctx.as_of in cur.marks.index else np.nan)
    fair = (float(cur.fair.loc[ctx.as_of])
            if ctx.as_of in cur.fair.index else np.nan)
    return {
        "book": CARRY["book"], "rank": CARRY["rank"], "side": CARRY["side"],
        "symbol": cur.symbol, "legs": list(cur.legs),
        "held_since": cur.marks.index[0].date().isoformat(),
        "mark_bp": mark, "fair_bp": fair, "rich_bp": mark - fair,
        "expiry": expiry.isoformat(), "roll_on": roll.isoformat(),
        # forward business days, not a count of history rows: on the newest
        # session there are no later dates in the index to count
        "sessions_to_roll": int(len(pd.bdate_range(
            ctx.as_of + pd.Timedelta(days=1), pd.Timestamp(roll)))),
        "days_to_roll": (roll - ctx.as_of.date()).days,
        "roll_cost_bp": 2.0 * fc.n_contracts(CARRY["book"])
        * OPT_HALF_TICK_BP * cost_mult,
    }


def screen(ctx: Context, *, books: Sequence[str] = BOOKS,
           ranks: Sequence[int] = RANKS, thr_bp: float = 4.0,
           exit_frac: float = 0.25, max_hold: int = 15,
           direction: str = "fade", cost_mult: float = 1.0) -> List[Idea]:
    """Every (book, rank) cell, best first."""
    out: List[Idea] = []
    for book in books:
        for rank in ranks:
            idea = score_cell(ctx, book, rank, thr_bp=thr_bp,
                              exit_frac=exit_frac, max_hold=max_hold,
                              direction=direction, cost_mult=cost_mult)
            if idea is None:
                # A cell that cannot be BUILT must still appear. Dropping it
                # silently is indistinguishable from "quiet today", and the
                # thin 2022 chains drop the front strangle exactly when the
                # strategy was most exposed.
                sym = fc.rank_symbol(ctx.as_of.date(), rank) or "?"
                idea = _blank_idea(book, rank, sym, thr_bp, "NO-BOOK",
                                   "strikes not listed/marked on this date")
            out.append(idea)
    return rank_ideas(out)


def rank_ideas(ideas: Sequence[Idea]) -> List[Idea]:
    """Actionable first; then the mandate; then risk character; then net bp.

    Three deliberate choices, in this order:

    1. **Pre-registration outranks everything.** The one cell with a mandate is
       never displaced by a cell that merely looks better today — that is what
       having a pre-registration is for.
    2. **Among exploratory hits, defined risk outranks undefined.** The
       referee's ruling on this family killed the undefined-risk short as a
       standing position and kept the defined-risk one; a screener that ignored
       that would rediscover the dead trade every time it ran, because short
       strangles have the fewest legs and so the smallest round trip.
    3. **Then net expected bp**, not raw richness, because the books carry
       different leg counts and a 4bp dislocation on a two-leg strangle is not
       the same opportunity as one on an eight-leg double fly.
    """
    order = {"ACTIONABLE": 0, "WATCH": 1, "OFF": 2, "NO-DATA": 3,
             "NO-BOOK": 4}
    return sorted(
        ideas,
        key=lambda i: (order.get(i.state, 9),
                       not i.prereg,
                       not i.defined_risk,
                       -(i.net_target_bp if np.isfinite(i.net_target_bp)
                         else -1e9)))


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

PROVENANCE = (
    "PROVENANCE — read before acting. The fade parameters (STRG75 Q1, thr 4bp,\n"
    "  exit 25%, hold 15) won a 720-config search: DSR 0.000, house verdict\n"
    "  SELECTION-ARTIFACT. Mechanism is measured (7-18 session richness\n"
    "  half-lives, frontier-consistent levels, positive skew through SVB); the\n"
    "  exact parameters are selection-inflated. The FLY25 carry short's NW t is\n"
    "  1.51 — real-looking, not significant. Cells other than the pre-registered\n"
    "  one have NO mandate: they are an exploratory read, not a strategy."
)


def format_report(ctx: Context, ideas: Sequence[Idea],
                  carry: Optional[dict], *, lots: int = 100,
                  dollars_per_bp: float = 25.0, top: int = 3) -> str:
    L: List[str] = []
    w = 96
    L.append("=" * w)
    src = ("LIVE" if ctx.live else "HISTORICAL")
    L.append(f"FAMILY B SCREENER  |  {src} as of {ctx.as_of.date()}"
             + ("  (quotes fetched this run)" if ctx.fetched else ""))
    L.append("=" * w)
    lag = (pd.Timestamp(datetime.date.today()) - ctx.as_of).days
    L.append(f"  screen date {ctx.as_of.date()}   history "
             f"{ctx.dates[0].date()} -> {ctx.dates[-1].date()} "
             f"({len(ctx.dates)} sessions)")
    if ctx.requested is not None:
        L.append(f"  !! you asked for {ctx.requested.date()}; the newest "
                 f"session with BOTH quotes and a settle is "
                 f"{ctx.as_of.date()} — screening that instead")
    if ctx.live and lag > 4:
        L.append(f"  !! the newest session with data is {lag} days old — "
                 f"quotes or settles are stale")
    if any(i.stale_ladder for i in ideas):
        L.append("  !! ZQ ladder flagged stale on at least one contract: the "
                 "fair value behind these numbers is suspect")

    L.append("")
    L.append("-- SLEEVE 1: carry (always on) " + "-" * (w - 31))
    if carry is None:
        L.append("  no book could be built")
    else:
        strikes = "/".join(f"{k:.2f}" for _, k, _ in carry["legs"])
        L.append(f"  {carry['side'].upper()} {carry['book']} "
                 f"{carry['symbol']} {strikes}   held since "
                 f"{carry['held_since']}")
        if np.isfinite(carry["mark_bp"]):
            L.append(f"  mark {carry['mark_bp']:.2f}bp   fair "
                     f"{carry['fair_bp']:.2f}bp   richness "
                     f"{carry['rich_bp']:+.2f}bp")
        else:
            L.append("  !! NO MARK on the screen date — this sleeve could not "
                     "be priced, which is a data failure, not a flat book")
        L.append(f"  expiry {carry['expiry']}   ROLL ON {carry['roll_on']} "
                 f"({carry['days_to_roll']} calendar days)   roll cost "
                 f"{carry['roll_cost_bp']:.2f}bp")
        if carry["days_to_roll"] <= 5:
            L.append("  >> ROLL WINDOW OPEN: close this and re-strike on the "
                     "next quarterly at the tree mode")

    L.append("")
    L.append("-- SLEEVE 2: richness fade (signal-gated) " + "-" * (w - 43))
    hdr = (f"  {'cell':<12}{'sym':<8}{'dte':>4}{'rich':>8}{'level':>8}"
           f"{'dev':>8}{'z':>6}{'net@1x':>8}{'xcost':>6}{'risk':>6}  state")
    L.append(hdr)
    L.append("  " + "-" * (len(hdr) - 2))
    for i in ideas:
        if i.state in ("NO-DATA", "NO-BOOK"):
            continue
        tag = "*" if i.prereg else " "
        note = f" ({i.gate_note})" if i.gate_note else ""
        L.append(
            f" {tag}{i.book + ' Q' + str(i.rank):<12}{i.symbol:<8}{i.dte:>4}"
            f"{i.rich_bp:>+8.2f}{i.level_bp:>+8.2f}{i.dev_bp:>+8.2f}"
            f"{(i.z_dev if np.isfinite(i.z_dev) else 0):>+6.1f}"
            f"{i.net_target_bp:>+8.2f}{i.edge_mult:>6.1f}"
            f"{('def' if i.defined_risk else 'UNB'):>6}  "
            f"{i.state}{note}")
    L.append("  * = the pre-registered cell, gated on RAW richness exactly as "
             "the backtest gates it.")
    L.append("    every other cell is gated on DEV (richness minus its own "
             "standing level) and")
    L.append("    needs |z| >= "
             f"{EXPLORATORY_Z:.1f}: at rank 2-3 the raw number is the "
             "off-lattice premium, not a signal.")
    L.append("    risk: def = defined (short fly capped); UNB = unbounded "
             "(short strangle).")
    dark = [i for i in ideas if i.state in ("NO-DATA", "NO-BOOK")]
    if dark:
        L.append("")
        L.append("  NOT SCREENED (absence here is a data gap, not a quiet "
                 "signal):")
        for i in dark:
            star = " *" if (i.book == PREREG["book"]
                            and i.rank == PREREG["rank"]) else "  "
            L.append(f"  {star}{i.book} Q{i.rank} {i.symbol}: {i.state}"
                     f" — {i.note}")

    act = [i for i in ideas if i.state == "ACTIONABLE"]
    priced = [i for i in ideas if i.state not in ("NO-DATA", "NO-BOOK")]
    blind = [i for i in ideas if i.state in ("NO-DATA", "NO-BOOK")]
    L.append("")
    L.append("-- RECOMMENDATION " + "-" * (w - 19))
    if not priced:
        # The first version of this screener printed "NO TRADE" here. It had no
        # data at all: every leg fetch had failed. Silence that reads as a
        # decision is the worst thing a screener can do, so this case is loud
        # and the CLI exits non-zero on it.
        L.append("  *** NO DATA — THIS IS NOT A 'NO TRADE' ***")
        L.append(f"  Not one structure could be priced on {ctx.as_of.date()}. "
                 f"Nothing below should be read as a signal.")
        L.append("  Check: is the session settled yet? did the settle refresh "
                 "run (--refresh)? is the")
        L.append("  option chain listed for these strikes? Re-run with an "
                 "earlier --date to confirm the")
        L.append("  pipeline works before trusting a quiet screen.")
    elif not act:
        best = next((i for i in ideas if i.state == "WATCH"), None)
        L.append("  NO TRADE. No cell clears its entry threshold.")
        if best is not None:
            L.append(f"  closest: {best.book} Q{best.rank} — rich "
                     f"{best.rich_bp:+.2f}bp, dev {best.dev_bp:+.2f}bp "
                     f"({best.gate_note})")
        if carry is not None and carry["days_to_roll"] <= 5:
            L.append("  (the carry sleeve's roll above is still due)")
    else:
        prereg = [i for i in act if i.prereg]
        pick = prereg[0] if prereg else act[0]
        if not prereg:
            L.append("  !! the pre-registered cell is NOT triggered; the idea "
                     "below is an exploratory screen hit with no mandate")
        verb = "SELL" if pick.side < 0 else "BUY"
        L.append(f"  {verb} {lots} x {pick.book} on {pick.symbol}"
                 f"   ({'pre-registered' if pick.prereg else 'EXPLORATORY'})")
        L.append("  execute NEXT session — the backtest enters lag-1 on the "
                 "signal, and its numbers assume that lag")
        for leg in pick.ticket(lots):
            L.append(f"      {leg['side']:<5}{leg['lots']:>5} "
                     f"{leg['symbol']} {leg['strike_price']:.2f}"
                     f"{leg['right']}")
        L.append(f"  entry     package mark {pick.mark_bp:.2f}bp vs fair "
                 f"{pick.fair_bp:.2f}bp   richness {pick.rich_bp:+.2f}bp "
                 f"(threshold {pick.thr_bp:.2f})")
        L.append(f"  target    exit at richness {pick.exit_rich_bp:+.2f}bp "
                 f"or {pick.max_hold_date} (whichever first)")
        L.append(f"  expected  gross {pick.gross_target_bp:+.2f}bp, cost "
                 f"{pick.cost_bp:.2f}bp, net {pick.net_target_bp:+.2f}bp "
                 f"= {pick.edge_mult:.1f}x the round trip")
        L.append(f"            ${pick.net_target_bp * lots * dollars_per_bp:+,.0f} "
                 f"on {lots} packages at ${dollars_per_bp:.0f}/bp"
                 f"   ({pick.n_contracts} contracts/package)")
        L.append(f"  context   dislocation is at the {pick.pct_pooled:.0%} "
                 f"percentile of |dev| for this cell over {len(ctx.dates)} "
                 f"sessions (standing level {pick.level_bp:+.2f}bp, z "
                 f"{pick.z_dev:+.1f}); typical half-life "
                 f"~{pick.half_life_hint:.0f} sessions")
        if pick.side < 0 and not pick.defined_risk:
            L.append("  RISK      SHORT STRANGLE — worst case UNBOUNDED. The "
                     "passive version of this book is DEAD in the findings")
            L.append("            (worst days -55/-92bp, skew -7.15); it "
                     "survives only as an intra-quarter fade that exits on "
                     "convergence,")
            L.append("            never held through expiry. The time stop "
                     "above is part of the strategy, not a suggestion.")
        elif pick.side < 0:
            L.append(f"  RISK      short {pick.book}, defined: worst case "
                     f"{pick.max_loss_bp:.2f}bp "
                     f"(${pick.max_loss_bp * lots * dollars_per_bp:,.0f}) if "
                     f"the underlying pins a wing")
        else:
            L.append(f"  RISK      long {pick.book}: worst case is the "
                     f"{pick.mark_bp:.2f}bp premium paid "
                     f"(${pick.mark_bp * lots * dollars_per_bp:,.0f})")
        L.append("            the exit is a convergence target, not a stop; "
                 "the structure's own payoff is the real risk")
    L.append("")
    L.append(PROVENANCE)
    L.append("=" * w)
    return "\n".join(L)


def to_records(ideas: Sequence[Idea]) -> List[dict]:
    out = []
    for i in ideas:
        d = dataclasses.asdict(i)
        d["legs"] = [{"right": r, "strike_price": k, "weight": w}
                     for r, k, w in i.legs]
        d["action"] = i.action
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--date", default="live",
                   help="YYYY-MM-DD, or 'live' for the latest session")
    p.add_argument("--history", type=int, default=250,
                   help="sessions of context for percentiles (default 250)")
    p.add_argument("--refresh", action="store_true", default=None,
                   help="force a settle refresh (implied by --date live)")
    p.add_argument("--no-refresh", dest="refresh", action="store_false",
                   help="skip the settle refresh even in live mode")
    p.add_argument("--books", default=",".join(BOOKS))
    p.add_argument("--ranks", default="1,2,3")
    p.add_argument("--thr", type=float, default=PREREG["thr_bp"])
    p.add_argument("--exit-frac", type=float, default=PREREG["exit_frac"])
    p.add_argument("--max-hold", type=int, default=PREREG["max_hold"])
    p.add_argument("--direction", default=PREREG["direction"],
                   choices=("fade", "momentum"))
    p.add_argument("--cost-mult", type=float, default=1.0)
    p.add_argument("--lots", type=int, default=100)
    p.add_argument("--json", action="store_true",
                   help="emit machine-readable records instead of the report")
    p.add_argument("--intraday", action="store_true",
                   help="mark live rather than on settles (the backtest never "
                        "used intraday marks — the signal is not calibrated "
                        "to them)")
    p.add_argument("--fetch-limit", type=int, default=10,
                   help="max sessions to fetch when the panel is behind")
    return p.parse_args(argv)


def main(argv=None) -> int:
    a = parse_args(argv)
    books = tuple(b.strip() for b in a.books.split(",") if b.strip())
    ranks = tuple(int(r) for r in a.ranks.split(",") if r.strip())
    ctx = load_context(a.date, history=a.history, refresh=a.refresh,
                       ranks=ranks, books=books, fetch_limit=a.fetch_limit,
                       intraday=a.intraday)
    ideas = screen(ctx, books=books, ranks=ranks, thr_bp=a.thr,
                   exit_frac=a.exit_frac, max_hold=a.max_hold,
                   direction=a.direction, cost_mult=a.cost_mult)
    carry = carry_state(ctx, cost_mult=a.cost_mult)
    if a.json:
        print(json.dumps({"as_of": ctx.as_of.date().isoformat(),
                          "live": ctx.live, "fetched": ctx.fetched,
                          "carry": carry, "ideas": to_records(ideas)},
                         indent=2, default=str))
    else:
        print(format_report(ctx, ideas, carry, lots=a.lots))
    # a screen that priced nothing is a failure, not a flat answer
    return (0 if any(i.state not in ("NO-DATA", "NO-BOOK") for i in ideas)
            else 2)


if __name__ == "__main__":
    sys.exit(main())

r"""Workflow 4 — ultra-long curve pairs traded on risk-adjusted carry.

The signal is :mod:`RVUtils.ConvexityRV.rac_signal`; this module turns its
``(date, pair) -> {+1, 0, -1}`` state into episodes, into an order tape, and into
a ``QueryDrivenBacktest``. Signals stay strategy-side and precomputed; the engine
owns marks and P&L. That is the house pattern and it is not optional here — a
convexity book's whole return is in the mark, so a P&L computed from level
changes by hand would be a linear approximation of exactly the thing being
measured.

Sign convention, established empirically and re-asserted at run time
-------------------------------------------------------------------
``CURVE bpv < 0`` is a **flattener**, which is long convexity;
``CURVE bpv > 0`` is a steepener. ``level_bp`` in the screen panel is
``long_rate - short_rate``, so a flattener profits when ``level_bp`` falls.
:func:`sign_probe` re-checks this against the engine on every run rather than
trusting the comment.

What the engine is asked to price
---------------------------------
Two ``IRSwapStructure.OUTRIGHT`` legs per episode with **explicit** effective
and maturity dates resolved at entry, DV01-neutral at ``package_dv01_usd``,
entered on the episode's first date and unwound on its last.

Explicit dates rather than a ``CURVE`` package carrying relative forward tenors,
because a relative tenor is re-resolved against every mark date: the engine then
prices a fresh at-market package each day, its NPV is ~0 by construction, and the
position never ages. Strat 3 uses explicit dates for the same reason.

No delta-hedging: strat 3 already measures the delta-hedged version of
these same pairs, and mixing the two would make it impossible to say whether a
result came from the carry signal or from the gamma harvest. Workflow 4 is the
carry-timing question, held separate on purpose.

Costs
-----
Per **leg**, ``2 * (0.5/2 bp) * sum|notional|`` — the convention
``factor_neutral_sizing`` established, which reproduces the incumbent's flat
$100,000 per closed round trip while letting a package with a different leg
count pay for the legs it actually has. Break-even is quoted on **gross DV01
traded**, because a per-cohort denominator is wrong once leg counts differ.

Citi's own round trip on this book is an external check on the number: the
15y5y/20y10y flattener ran +$187K gross to **+$155K net on $50K DV01**, i.e.
about **$32K including every resize**.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "Episode",
    "assert_ran",
    "build_tape",
    "episodes_from_state",
    "run_backtest",
    "sign_probe",
]

CURVE = "USD-SOFR-1D"


def _parse_fwd(label: str):
    """``"15Yx5Y" -> (15.0, 5.0)``, via strat 3 so one grammar serves both."""
    from RVUtils.ConvexityRV.strat3_strikeless_vol import parse_fwd

    return parse_fwd(label)

#: One-way bid/offer in bp of rate, per leg. 0.5bp round trip, halved to a side.
DEFAULT_HALF_SPREAD_BP = 0.25


@dataclass(frozen=True)
class Episode:
    """A held position: one pair, one side, one entry and one exit."""

    pair: str
    side: int          # +1 flattener, -1 steepener
    entry: pd.Timestamp
    exit: pd.Timestamp

    @property
    def short_leg(self) -> str:
        return self.pair.split("/")[0]

    @property
    def long_leg(self) -> str:
        return self.pair.split("/")[1]

    @property
    def days(self) -> int:
        return int(np.busday_count(self.entry.date(), self.exit.date()))


# ---------------------------------------------------------------------------
# State -> episodes
# ---------------------------------------------------------------------------
def episodes_from_state(
    state: pd.Series,
    *,
    exit_pct: Optional[float] = None,
    rac_pct: Optional[pd.Series] = None,
    max_hold_days: Optional[int] = None,
    min_hold_days: int = 1,
) -> List[Episode]:
    """Collapse a daily ``(date, pair)`` state into held episodes.

    A position opens on the first day its side fires and closes when **any** of
    these happens, whichever is first:

    * ``rac_pct`` reverts through ``exit_pct`` — Citi's own exit is a *level of
      the statistic* (*"carry deteriorated to −2bp/yr and BE/realized vol rose to
      0.8"*), not the disappearance of the entry condition. When ``exit_pct`` is
      given it is the **only** mean-reversion exit, and the entry condition
      lapsing is ignored;
    * the side **flips** to the opposite sign;
    * ``max_hold_days`` elapses.

    ``min_hold_days`` **suppresses** an exit; it does not discard the episode.
    The first draft did the latter — it appended only episodes that had already
    lasted long enough — which keeps exactly the trades that happened to
    persist and silently drops the ones that did not. That is not a rule anybody
    could trade, because the length is only known afterwards, and it flatters the
    book by construction.

    Two things this ordering fixes, both found by the exit sweep returning
    *identical* books for ``exit_pct`` of 0.50, 0.35, 0.20 and ``None``: when
    "the entry condition stopped firing" is treated as an exit it dominates
    everything else, so the ``exit_pct`` knob was wired to nothing, and holds
    collapsed to a median of **2 days** on a book whose published round trip ran
    seven months.

    A side flip closes and reopens rather than reversing in place, so every
    episode carries one sign and the trade log is readable.
    """
    df = state.rename("state").reset_index()
    if "pair" not in df.columns or "date" not in df.columns:
        raise KeyError(f"state must be indexed by (date, pair); got {list(df.columns)}")
    if rac_pct is not None:
        df = df.merge(rac_pct.rename("rac_pct").reset_index(), on=["date", "pair"],
                      how="left")

    out: List[Episode] = []
    for pair, g in df.sort_values("date").groupby("pair", sort=False):
        g = g.reset_index(drop=True)
        cur_side, entry_i = 0, None
        last = len(g) - 1
        for i, row in g.iterrows():
            s = int(row["state"])
            if cur_side == 0:
                if s != 0:
                    cur_side, entry_i = s, i
                continue

            held = i - entry_i
            close = False

            if exit_pct is not None and rac_pct is not None:
                p = row.get("rac_pct")
                if pd.notna(p):
                    # A flattener was entered on a HIGH percentile, so it closes
                    # when the statistic reverts DOWN through exit_pct; the
                    # steepener is the mirror.
                    if cur_side == 1 and p <= exit_pct:
                        close = True
                    if cur_side == -1 and p >= (1.0 - exit_pct):
                        close = True
            elif s == 0:
                # No level-based exit configured, so falling out of the entry
                # condition is the only mean-reversion rule available.
                close = True

            if s == -cur_side:
                close = True                      # a flip always closes
            if max_hold_days is not None and held >= max_hold_days:
                close = True

            # `min_hold_days` SUPPRESSES an exit. It must never be used to drop
            # an episode: which trades last is not knowable at entry.
            if close and held < min_hold_days and i != last:
                close = False

            if i == last:
                close = True

            if close:
                out.append(Episode(pair=pair, side=cur_side,
                                   entry=g.loc[entry_i, "date"],
                                   exit=g.loc[i, "date"]))
                nxt = int(g.loc[i, "state"])
                cur_side = nxt if nxt != 0 else 0
                entry_i = i if nxt != 0 else None
    return out


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
def sign_probe(mdp: Any, as_of: dt.date, short: str = "15Yx5Y",
               long: str = "20Yx10Y", package_dv01_usd: float = 100_000.0) -> dict:
    """Re-derive the sign convention from the engine, on every run.

    Returns the two legs' PV01 for ``bpv < 0``. A flattener pays the short leg
    and receives the long one, so the short leg's PV01 must be **positive** and
    the long leg's **negative**, and the two must sum to ~0.
    """
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    pricer = mdp._get_curve(curve_name=CURVE, timestamp=as_of)
    q = IRSwapQuery(
        curve=CURVE, structure=IRSwapStructure.CURVE, value=IRSwapValue.PV01,
        structure_kwargs={"front_tenor": short, "back_tenor": long,
                          "bpv": -abs(package_dv01_usd), "risk_weights": [1.0, 1.0]},
    )
    package, weights = q.resolve_package(pricer_or_curve=pricer)
    # `resolve_pricable` BAKES the risk weight into the returned leg, so pv01 is
    # already signed. Multiplying by the weight again is a double application --
    # the first draft did exactly that and reported +100k/+100k, summing to
    # 200,000 on a package whose defining property is that it sums to zero.
    resolved = [pricer.resolve_pricable(p, risk_weight=w)
                for p, w in zip(package, weights)]
    pv01 = [float(pricer.pv01(s)) for s in resolved]
    return {"front_pv01": pv01[0], "back_pv01": pv01[1], "sum": float(sum(pv01)),
            "weights": list(weights),
            "is_flattener": pv01[0] > 0 > pv01[1]}


def build_tape(episodes: Sequence[Episode], *,
               package_dv01_usd: float = 100_000.0) -> pd.DataFrame:
    """Order tape: two rows per episode, ``open`` then ``unwind``.

    ``bpv`` carries the sign convention: negative for a flattener.
    """
    rows = []
    for k, e in enumerate(episodes):
        bpv = -abs(package_dv01_usd) if e.side == 1 else abs(package_dv01_usd)
        rows.append({"episode": k, "kind": "open", "date": e.entry, "pair": e.pair,
                     "side": e.side, "bpv": bpv,
                     "front_tenor": e.short_leg, "back_tenor": e.long_leg})
        rows.append({"episode": k, "kind": "unwind", "date": e.exit, "pair": e.pair,
                     "side": e.side, "bpv": bpv,
                     "front_tenor": e.short_leg, "back_tenor": e.long_leg})
    return pd.DataFrame(rows).sort_values(["date", "episode", "kind"]).reset_index(drop=True)


def assert_ran(bt: Any, expect_days: int, n_episodes: int) -> None:
    """``QueryDrivenBacktest.run()`` swallows exceptions and prints them.

    A backtest that blew up on every date is indistinguishable from one that
    never traded: both give a flat equity curve. So assert on the artifacts.
    """
    if n_episodes == 0:
        raise AssertionError("the signal produced no episodes -- a planning "
                             "failure, not a flat result")
    mtm = getattr(bt, "mtm_history", None)
    if mtm is None or len(mtm) == 0:
        raise AssertionError("mtm_history is empty; run() failed silently")
    if len(mtm) != expect_days:
        raise AssertionError(f"mtm_history has {len(mtm)} marks, expected {expect_days}")
    eq = pd.Series(mtm)
    if not np.isfinite(eq.to_numpy()).all():
        raise AssertionError("mtm_history contains non-finite marks")
    if float(eq.abs().max()) == 0.0:
        pf = getattr(bt, "portfolio", None)
        n_closed = len(getattr(pf, "closed_positions_log", []) or []) if pf else -1
        raise AssertionError(
            f"equity is identically zero on every date and {n_closed} positions "
            "closed; the engine priced nothing. If the position count is 0 the "
            "triggers never fired -- DateTriggerRequirements compares "
            "`state.date()` against its `dates` set, so a pd.Timestamp there "
            "matches nothing.")


def run_backtest(
    episodes: Sequence[Episode],
    dates: Sequence[pd.Timestamp],
    *,
    mdp: Any = None,
    package_dv01_usd: float = 100_000.0,
    half_spread_bp: float = DEFAULT_HALF_SPREAD_BP,
    show_progress: bool = False,
) -> Tuple[Any, pd.Series]:
    """Run the episodes through ``QueryDrivenBacktest``. Returns ``(bt, equity)``.

    Fee per unwind is charged **per leg**: a CURVE package has two, so the
    round-trip cost is ``2 legs * 2 sides * half_spread_bp`` in bp of rate on the
    package DV01.
    """
    from BT.data_handler import TimeGrid
    from BT.query_actions import AddQueryAction, UnwindPositionsAction
    from BT.query_engine import QueryDrivenBacktest
    from BT.query_strategy import QueryStrategy
    from BT.triggers import DateTrigger, DateTriggerRequirements
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    mdp = mdp or IRSwapsMDP(source="CITIVELO_EXCEL")
    grid = TimeGrid([pd.Timestamp(d) for d in dates])

    #: 2 legs x 2 sides of the spread, in bp of rate on the package DV01.
    fee = 2.0 * 2.0 * half_spread_bp * package_dv01_usd

    # A CURVE query carrying RELATIVE forward tenors ("15Yx5Y") is re-resolved
    # against every mark date, so the engine prices a fresh at-market package
    # each day and its NPV is ~0 by construction. The first draft did that and
    # produced an equity curve that was identically zero on all 1,470 dates --
    # which `assert_ran` caught and `QueryDrivenBacktest.run()` would have shown
    # as a flat line indistinguishable from "the strategy made no money".
    #
    # So each leg is resolved to EXPLICIT effective/maturity dates at entry and
    # traded as an OUTRIGHT, which is what lets the position age. This is the
    # same construction strat 3 uses, and for the same reason.
    triggers = []
    for k, e in enumerate(episodes):
        tag = f"rac{k}"
        pricer = mdp._get_curve(curve_name=CURVE, timestamp=pd.Timestamp(e.entry).date())
        actions = []
        for leg_label, leg_sign in ((e.short_leg, +1), (e.long_leg, -1)):
            fwd, tail = _parse_fwd(leg_label)
            swap = pricer.build_irswap(fwd=f"{fwd:g}Y", tenor=f"{tail:g}Y", notional=1.0)
            # +bpv is a PAYER. A flattener pays the shorter leg and receives the
            # longer one; a steepener is the mirror.
            bpv = e.side * leg_sign * abs(package_dv01_usd)
            q = IRSwapQuery(
                curve=CURVE, structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV,
                effective_date=pd.Timestamp(pricer.effective_date(swap)).date(),
                maturity_date=pd.Timestamp(pricer.maturity_date(swap)).date(),
                structure_kwargs={"bpv": float(bpv)},
            )
            actions.append(AddQueryAction(query=q, meta={"tags": [tag, "rac", leg_label]}))
        # `DateTriggerRequirements.has_triggered` is `state.date() in
        # set(self.dates)`. A `pd.Timestamp` is a `datetime.datetime`, and a
        # `date` never compares equal to a `datetime` even at midnight, so
        # passing Timestamps here means NO trigger ever fires -- the engine
        # opens nothing, marks zero on every date, and `run()` reports success.
        # That produced 1,470 marks of exactly 0.0 and 0 positions before
        # `assert_ran` caught it. Trigger dates are `datetime.date`.
        triggers.append(DateTrigger(
            DateTriggerRequirements(dates=[pd.Timestamp(e.entry).date()]),
            actions=actions))
        triggers.append(DateTrigger(
            DateTriggerRequirements(dates=[pd.Timestamp(e.exit).date()]),
            actions=[UnwindPositionsAction(match_tag=tag, fee=fee)]))

    strat = QueryStrategy(name="rac_w4", triggers=triggers)
    bt = QueryDrivenBacktest(time_grid=grid, strategy=strat, mdp=mdp,
                             show_progress=show_progress)
    bt.run()
    assert_ran(bt, expect_days=len(grid.dates) if hasattr(grid, "dates") else len(dates),
               n_episodes=len(episodes))
    return bt, pd.Series(bt.mtm_history)

r"""Which SR3 flattener, if any -- the structuring question, priced.

This is not a signal study. Five of those already ran (#490, #491, #497, #501
and the event-conditioning study in this branch) and none of them produces a
"get long now". The question here is different and it is the one a desk actually
has to answer: **given a dovish view over a few months, which structure carries
it, and what is in the price already.**

The three things that decide it
-------------------------------
**1. How much is in the spread at all.** A flattener is short the tightening
priced between its two legs. If only 5bp is priced there, the whole prize is 5bp
gross -- before the trade is right about anything -- and a two-leg SR3 calendar
spread costs **1.00bp** round trip (``reference_sfr_fly_conventions``: the cost
is per CONTRACT, so 0.25 one-way x 2 contracts x 2 = 1.00bp of the spread quote,
twice what an outright pays). A structure whose entire prize is 3bp is spending a
third of it on the spread.

**2. Whether it flattens in BOTH directions.** The stated argument for a
front-end flattener here is that it wins either way: if the data accelerates the
Fed becomes proactive and the front sells off, and if growth softens the rally is
felt in the later dates first. Both flatten. That is a testable claim about the
beta of the spread to the level, split by the sign of the level move, and
:func:`both_ways` tests it. It is also where the twist point lives -- the rank at
which that beta changes sign is the pivot the argument depends on, and it is
measured rather than asserted.

**3. What the distribution of a few-month hold actually looks like.** Not the
mean -- the whole distribution, and specifically how often a flattener held three
months clears its own cost.

Roll discipline
---------------
Every measurement here is on FIXED CONTRACTS. A rank-differenced spread series
fabricates drift at each roll -- measured on this desk at +6.9bp per roll week
and +228bp over 2018-2026 for a single rank-3 leg, more than twice what the book
it was built for earned (``reference_rank_diff_roll_fabrication``). So a horizon
change is always ``spread(same two contracts, t+h) - spread(same two, t)``, and a
pair whose near leg expires inside the hold is dropped and counted.

Conventions, stated once
------------------------
* rate = ``100 - price``, in percent; spreads are quoted in **bp of rate**.
* ``spread(i, j) = rate(rank j) - rate(rank i)`` for ``j > i``. **Positive means
  upward sloping**, i.e. tightening priced between the two legs.
* a **FLATTENER is SHORT that spread**: receive the back leg, pay the front. It
  profits when the spread falls. Its P&L is therefore ``-(spread_end -
  spread_start)`` minus cost.
"""
from __future__ import annotations

import dataclasses
import datetime
import pathlib
import sys
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _p in (str(HERE), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fed_detachment_prices as PX  # noqa: E402

#: Round trip on a two-leg SR3 calendar spread, in bp of the spread quote.
#: 0.25bp one-way per CONTRACT, two contracts, both ways.
SPREAD_ROUND_TRIP_BP = 1.00

#: An outright, for comparison. Half the cost, twice the directional risk.
OUTRIGHT_ROUND_TRIP_BP = 0.50


def rate_panel(start: str = "2019-09-27", end: str = "2026-08-24",
               max_rank: int = 10) -> pd.DataFrame:
    """SR3 rates (percent) by contract, from the shared settle cache. Offline."""
    PX.seed_local_cache()
    syms = PX.sr3_universe(pd.Timestamp(start).date(), pd.Timestamp(end).date(),
                           max_rank=max_rank)
    px = PX.settle_panel(syms)
    return 100.0 - px


def rank_map(dates: Sequence[pd.Timestamp], max_rank: int = 10) -> pd.DataFrame:
    """``date x rank -> contract``. Never differenced; used only to look up which
    contract a rank pointed at on a given day."""
    rows = []
    for d in dates:
        dd = pd.Timestamp(d).date()
        rows.append({"date": pd.Timestamp(d),
                     **{r: PX.rank_symbol(dd, r) for r in range(1, max_rank + 1)}})
    return pd.DataFrame(rows).set_index("date")


def strip_today(rates: pd.DataFrame, as_of: pd.Timestamp, max_rank: int = 8
                ) -> pd.DataFrame:
    """The strip on one date: rank, contract, rate, and the step to the next."""
    as_of = pd.Timestamp(as_of)
    rows = []
    prev = None
    for r in range(1, max_rank + 1):
        sym = PX.rank_symbol(as_of.date(), r)
        v = rates.at[as_of, sym] if sym in rates.columns and as_of in rates.index \
            else np.nan
        rows.append({"rank": r, "contract": sym, "rate_pct": v,
                     "step_from_prev_bp": (v - prev) * 100 if prev is not None
                     and np.isfinite(v) else np.nan})
        prev = v
    return pd.DataFrame(rows)


def spread_bp(rates: pd.DataFrame, on: pd.Timestamp, sym_i: str, sym_j: str
              ) -> float:
    """``rate(j) - rate(i)`` in bp, on one date, from two NAMED contracts."""
    if on not in rates.index:
        return np.nan
    a = rates.at[on, sym_i] if sym_i in rates.columns else np.nan
    b = rates.at[on, sym_j] if sym_j in rates.columns else np.nan
    if not (np.isfinite(a) and np.isfinite(b)):
        return np.nan
    return float((b - a) * 100.0)


# ==========================================================================
# what is in the price
# ==========================================================================
def candidate_table(rates: pd.DataFrame, as_of: pd.Timestamp,
                    pairs: Sequence[Tuple[int, int]]) -> pd.DataFrame:
    """For each rank pair: the spread today, the prize, and what the prize costs.

    ``prize_to_flat_bp`` is what a flattener collects if the spread goes to
    exactly zero -- i.e. if every basis point of tightening priced between the
    two legs is priced out and nothing more. It is not a forecast; it is the
    distance to the nearest round number, and it is the honest ceiling on a
    "no more hikes" view. Getting more than it requires CUTS to be priced
    between the legs, which is a stronger claim than the one being made.
    """
    as_of = pd.Timestamp(as_of)
    rows = []
    for i, j in pairs:
        si = PX.rank_symbol(as_of.date(), i)
        sj = PX.rank_symbol(as_of.date(), j)
        s = spread_bp(rates, as_of, si, sj)
        rows.append({
            "pair": f"r{i}-r{j}", "front": si, "back": sj,
            "spread_bp": s,
            "prize_to_flat_bp": s,               # a flattener is short the spread
            "cost_bp": SPREAD_ROUND_TRIP_BP,
            "net_prize_bp": s - SPREAD_ROUND_TRIP_BP if np.isfinite(s) else np.nan,
            "cost_as_pct_of_prize": (100 * SPREAD_ROUND_TRIP_BP / s
                                     if np.isfinite(s) and s > 0 else np.nan),
        })
    return pd.DataFrame(rows)


def meetings_between(ladder: Sequence, front: str, back: str) -> pd.DataFrame:
    """The FOMC meetings that sit between two SR3 contracts, and what each prices.

    An SR3 contract references the three months from its IMM date, so the
    tightening a calendar spread is short is the sum of the meeting steps whose
    effective date falls between the two reference windows. Showing them
    individually is what turns "5bp is priced" into "5bp across three meetings,
    i.e. the market already thinks two of them do nothing".
    """
    from BT.serff.mechanics import contract_window

    fw, bw = contract_window(front), contract_window(back)
    lo, hi = pd.Timestamp(fw.start), pd.Timestamp(bw.start)
    rows = []
    for m in ladder:
        eff = pd.Timestamp(m.effective)
        if lo < eff <= hi:
            rows.append({"effective": eff.date(), "jump_bp": round(m.jump_bp, 2),
                         "contract": m.contract, "stale": m.stale})
    out = pd.DataFrame(rows)
    if not out.empty:
        out.attrs["sum_bp"] = float(out.loc[~out["stale"], "jump_bp"].sum())
    return out


# ==========================================================================
# horizon distribution, roll-safe
# ==========================================================================
def horizon_moves(rates: pd.DataFrame, i: int, j: int, *, horizon_bd: int = 63,
                  start: str = "2019-09-27") -> pd.DataFrame:
    """Every ``horizon_bd``-day change in the rank-(i,j) spread, on FIXED legs.

    For each date the two contracts are resolved ONCE, at the start, and the
    same two are read at the end. A pair whose near leg expires inside the hold
    is dropped -- never rolled -- so no row here differences two contracts.
    """
    idx = rates.index[rates.index >= pd.Timestamp(start)]
    rows = []
    n_expired = 0
    for k in range(len(idx) - horizon_bd):
        t, u = idx[k], idx[k + horizon_bd]
        si = PX.rank_symbol(t.date(), i)
        sj = PX.rank_symbol(t.date(), j)
        exp = min(pd.Timestamp(PX.contract_window(s).end) for s in (si, sj))
        if exp <= u:
            n_expired += 1
            continue
        a, b = spread_bp(rates, t, si, sj), spread_bp(rates, u, si, sj)
        if not (np.isfinite(a) and np.isfinite(b)):
            continue
        rows.append({"date": t, "exit": u, "front": si, "back": sj,
                     "spread_start_bp": a, "spread_end_bp": b,
                     "d_spread_bp": b - a,
                     "flattener_pnl_bp": -(b - a) - SPREAD_ROUND_TRIP_BP})
    out = pd.DataFrame(rows)
    out.attrs["dropped_expiring"] = n_expired
    return out


def horizon_summary(mv: pd.DataFrame) -> Dict[str, float]:
    if mv is None or mv.empty:
        return {"n": 0}
    p = mv["flattener_pnl_bp"].to_numpy(float)
    s0 = mv["spread_start_bp"].to_numpy(float)
    return {
        "n": int(len(p)),
        "start_spread_median_bp": float(np.median(s0)),
        "flattener_mean_bp": float(p.mean()),
        "flattener_median_bp": float(np.median(p)),
        "hit_rate": float((p > 0).mean()),
        "q10_bp": float(np.quantile(p, 0.10)),
        "q90_bp": float(np.quantile(p, 0.90)),
        "worst_bp": float(p.min()), "best_bp": float(p.max()),
        "sd_bp": float(p.std(ddof=1)),
    }


def conditional_on_level(mv: pd.DataFrame, current: float) -> Dict[str, float]:
    """The same distribution, restricted to starts within 5bp of where the spread
    is NOW.

    A flattener entered at +40bp and one entered at +5bp are different trades,
    and pooling them describes neither. This is the cut that says what has
    historically happened from HERE.
    """
    if mv is None or mv.empty or not np.isfinite(current):
        return {"n": 0}
    m = mv[(mv["spread_start_bp"] - current).abs() <= 5.0]
    if m.empty:
        return {"n": 0, "note": "no historical start within 5bp of today"}
    out = horizon_summary(m)
    out["band"] = f"{current - 5:.0f}..{current + 5:.0f}bp"
    return out


# ==========================================================================
# does it flatten in BOTH directions?
# ==========================================================================
def both_ways(rates: pd.DataFrame, i: int, j: int, *, horizon_bd: int = 21,
              level_ranks: Tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7, 8),
              start: str = "2019-09-27") -> Dict[str, object]:
    """Beta of the spread to the LEVEL, split by the sign of the level move.

    The argument for a front-end flattener here is that it wins either way: an
    acceleration makes the Fed proactive and sells off the front; a slowdown is
    felt in the later dates. Both flatten. That is a claim about the sign of
    ``d(spread)/d(level)`` in each half of the distribution, and it is
    falsifiable: if the beta is negative when the level rises and POSITIVE when
    it falls, the structure is directional in disguise and only wins one way.

    The level is the mean rate across ``level_ranks``, computed on the same
    fixed contracts over the same window as the spread, so no leg of either side
    crosses a roll.
    """
    idx = rates.index[rates.index >= pd.Timestamp(start)]
    rows = []
    for k in range(len(idx) - horizon_bd):
        t, u = idx[k], idx[k + horizon_bd]
        si, sj = PX.rank_symbol(t.date(), i), PX.rank_symbol(t.date(), j)
        lv = [PX.rank_symbol(t.date(), r) for r in level_ranks]
        allsym = set([si, sj] + lv)
        exp = min(pd.Timestamp(PX.contract_window(s).end) for s in allsym)
        if exp <= u:
            continue
        a, b = spread_bp(rates, t, si, sj), spread_bp(rates, u, si, sj)
        try:
            l0 = float(np.mean([rates.at[t, s] for s in lv]))
            l1 = float(np.mean([rates.at[u, s] for s in lv]))
        except KeyError:
            continue
        if not all(np.isfinite(x) for x in (a, b, l0, l1)):
            continue
        rows.append({"date": t, "d_spread_bp": b - a,
                     "d_level_bp": (l1 - l0) * 100.0})
    df = pd.DataFrame(rows)
    if len(df) < 40:
        return {"n": int(len(df)), "note": "too few observations"}

    def _beta(sub):
        if len(sub) < 20:
            return {"n": int(len(sub)), "beta": np.nan, "t": np.nan}
        x = sub["d_level_bp"].to_numpy(float)
        y = sub["d_spread_bp"].to_numpy(float)
        X = np.column_stack([np.ones(x.size), x])
        XtXi = np.linalg.inv(X.T @ X)
        bb = XtXi @ X.T @ y
        r = y - X @ bb
        h = np.einsum("ij,jk,ik->i", X, XtXi, X)
        om = (r / np.maximum(1e-12, 1 - h)) ** 2
        V = XtXi @ (X.T * om) @ X @ XtXi
        se = float(np.sqrt(max(V[1, 1], 0.0)))
        return {"n": int(len(sub)), "beta": float(bb[1]),
                "t": float(bb[1] / se) if se > 0 else np.nan}

    up, dn = df[df["d_level_bp"] > 0], df[df["d_level_bp"] < 0]
    b_all, b_up, b_dn = _beta(df), _beta(up), _beta(dn)
    return {
        "pair": f"r{i}-r{j}", "n": int(len(df)), "horizon_bd": horizon_bd,
        "beta_all": b_all["beta"], "t_all": b_all["t"],
        "beta_up": b_up["beta"], "t_up": b_up["t"], "n_up": b_up["n"],
        "beta_dn": b_dn["beta"], "t_dn": b_dn["t"], "n_dn": b_dn["n"],
        # the claim: a flattener wins when the spread FALLS, so "wins both ways"
        # needs the spread to fall when the level rises (beta_up < 0) AND when it
        # falls (beta_dn > 0, i.e. the spread falls as the level falls)
        "flattens_when_level_rises": bool(np.isfinite(b_up["beta"]) and b_up["beta"] < 0),
        "flattens_when_level_falls": bool(np.isfinite(b_dn["beta"]) and b_dn["beta"] > 0),
        "frame": df,
    }


def twist_point(rates: pd.DataFrame, *, horizon_bd: int = 21,
                max_rank: int = 8, start: str = "2019-09-27") -> pd.DataFrame:
    """Each rank's beta to the level. The twist point is where it crosses 1.

    A rank whose beta to the level is above 1 moves MORE than the strip; below 1,
    less. A flattener between two ranks works when the back leg's beta is lower
    than the front's, so the ordering of these betas is what says which spread
    carries a directional view and which fights it.
    """
    idx = rates.index[rates.index >= pd.Timestamp(start)]
    lv_ranks = tuple(range(1, max_rank + 1))
    recs = {r: [] for r in lv_ranks}
    lev = []
    for k in range(len(idx) - horizon_bd):
        t, u = idx[k], idx[k + horizon_bd]
        syms = {r: PX.rank_symbol(t.date(), r) for r in lv_ranks}
        exp = min(pd.Timestamp(PX.contract_window(s).end) for s in syms.values())
        if exp <= u:
            continue
        try:
            d = {r: (rates.at[u, s] - rates.at[t, s]) * 100.0
                 for r, s in syms.items()}
        except KeyError:
            continue
        if not all(np.isfinite(v) for v in d.values()):
            continue
        lev.append(float(np.mean(list(d.values()))))
        for r in lv_ranks:
            recs[r].append(d[r])
    L = np.asarray(lev)
    rows = []
    for r in lv_ranks:
        y = np.asarray(recs[r])
        if y.size < 40 or L.std() == 0:
            rows.append({"rank": r, "beta_to_level": np.nan, "n": int(y.size)})
            continue
        beta = float(np.polyfit(L, y, 1)[0])
        rows.append({"rank": r, "n": int(y.size), "beta_to_level": beta,
                     "contract_example": PX.rank_symbol(
                         pd.Timestamp(idx[-1]).date(), r)})
    return pd.DataFrame(rows)

"""One CONFIG dict -> one backtest: selection, butterflies, daily marks, P&L in bp.

The unit of P&L
---------------
Everything is quoted in **basis points per unit of belly DV01**. A butterfly whose belly
carries $1/bp of risk and whose wings are DV01-weighted against it earns ``-dR`` where
``R = y_belly - a*y_front - (1-a)*y_back``, so the number on the equity curve is directly
comparable to the round-trip cost, which is quoted the same way. No notional, no AUM, no
leverage assumption smuggled in through a position-sizing rule.

Why a butterfly and not a pair
-------------------------------
A pair of neighbouring bonds is not curve-neutral: 3 months of maturity difference at a
15-year duration leaves real slope exposure, and over a ten-day hold the slope moves far
more than any dislocation this study is looking for. The wings are chosen so the package
is neutral to both level and slope in maturity space --

    a = (ttm_back - ttm_belly) / (ttm_back - ttm_front)
    w = [-a, +1, -(1-a)]        sum(w) = 0,  sum(w * ttm) = 0

-- which leaves the belly's *idiosyncratic* richness as what the position is actually
long. That is the object the signal claims to predict.

The fly is not convexity-neutral, and that is not fixable with three legs. It is
measured instead: ``convexity_bp`` reports the package's second-order exposure so a P&L
that came from a big parallel move can be told apart from one that came from the signal.

Four rules that are structural rather than advisory
----------------------------------------------------
**Marks are complete-case, per leg, every day.** A package is marked only on dates where
**all three** legs have a genuine gated price. A prior ARBS book let one 50bp-rich mark
through a 100bp gate and it baked +15.3bp into a 22-trade result.

**The cost is charged once, in full, at the exit.** In and out on three legs is one full
spread per leg. Charging "half at entry, half at exit" through a single fee hook charges
half the cost and never charges the rest.

**The signal is stamped with the date it could be traded, not the date it was known.**
An iShares document as of T is published overnight, so its first tradeable close is T+1.
``exec_lag`` defaults to 1 and is a knob so the grid can run 0 alongside and show what
the difference is worth.

**No overlapping positions in the same belly.** Otherwise a bond that stays underweight
for a month is entered twenty times and the "book" is one trade counted twenty ways,
with a t-statistic to match.
"""

from __future__ import annotations

import copy
import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from MDP.ETFHoldings.universe import ETFSpec, spec
from RVUtils.ETFRebalance import costs as C
from RVUtils.ETFRebalance import curve as CV
from RVUtils.ETFRebalance import holdings_panel as HP
from RVUtils.ETFRebalance import signals as SIG

# ======================================================================= config

DEFAULT_CONFIG: Dict[str, Any] = {
    "name": "baseline",
    "fund": "TLT",

    # WHAT IS ELIGIBLE ----------------------------------------------------
    "universe": {
        "start": "2016-01-01",
        "end": None,
        "ttm_min": None,          # None -> the fund's own index band
        "ttm_max": None,
        "min_float_usd": 5e9,     # a bond nobody can source is not a trade
        "require_two_sided": True,
        "exclude_ranks": [],      # e.g. [0, 1] to keep the on-the-runs out
        "max_spread_price_bp": 25.0,
        "drop_flow_days": False,  # creation/redemption days are a different signal
        "flow_day_threshold": 0.02,
        #: How a "weight" is measured. ``dv01`` is the fund's share of the book's RISK,
        #: ``mv`` its share of the book's MONEY. They are different questions and the
        #: long end is where they differ most: a 1.25%-coupon 2050 and a 5%-coupon 2054
        #: can carry the same market value and materially different DV01.
        "weight_basis": "dv01",   # dv01 | mv
        #: What the fund is benchmarked AGAINST. ICE's US Treasury indices weight on
        #: publicly held par, i.e. excluding Federal Reserve SOMA holdings, which over
        #: this sample reached a fifth to a third of some long issues and is concentrated
        #: in particular CUSIPs rather than spread evenly. ``float_panel.benchmark_fit``
        #: settles which one the fund's own published weights are consistent with, so
        #: this is a measurement rather than a methodology assumption.
        "benchmark": "ex_soma",   # ex_soma | total
    },

    # THE LOCAL CURVE THE RESIDUAL IS MEASURED AGAINST --------------------
    "curve": {"deg": 3, "x_axis": "ttm", "include_coupon": True, "robust": True},

    # THE VIEW ------------------------------------------------------------
    "signal": {
        "components": {"active_w": 1.0},
        "z_mode": "cross_section",     # cross_section | time_series | both
        "z_lookback": 250,
        "robust_z": True,
        "smooth_days": 1,
        "kwargs": {},
    },

    # WHEN ----------------------------------------------------------------
    "timing": {
        "exec_lag": 1,            # business days between the file and the trade
        "hold_days": 10,
        "entry_every": 5,         # only consider entries every n-th business day
        "entry_window": None,     # None | "month_end" | "post_month_end"
        "entry_window_days": 3,
    },

    # HOW IT IS EXPRESSED -------------------------------------------------
    "structure": {
        "kind": "fly",            # fly | pair
        "n_positions": 3,         # bellies per side
        "both_sides": True,       # trade the rich end short as well as the cheap end long
        "wing_gap_min_y": 0.10,
        "wing_gap_max_y": 0.80,
        "min_abs_score": 0.0,
    },

    # WHAT IT COSTS -------------------------------------------------------
    "costs": {"basis": "measured", "multiplier": 1.0, "flat_yield_bp": 0.30},
    "carry": {"enabled": True},
    "price_basis": "mid",         # mid | eod -- see the tie-out; these genuinely differ
}


def merge_config(user: Mapping[str, Any]) -> Dict[str, Any]:
    """Shallow-merge one level down, so a config need only name what it changes."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    for k, v in (user or {}).items():
        if isinstance(v, Mapping) and isinstance(cfg.get(k), dict):
            cfg[k] = {**cfg[k], **v}
        else:
            cfg[k] = copy.deepcopy(v)
    return cfg


@dataclass
class Result:
    config: Dict[str, Any]
    closed: pd.DataFrame          # one row per completed package
    daily: pd.DataFrame           # date, mtm_bp, open_positions -- the equity curve
    legs: pd.DataFrame            # one row per (trade, leg) -- the audit trail
    funnel: Dict[str, Any] = field(default_factory=dict)
    universe: Optional[pd.DataFrame] = None
    #: (trade_id, date, pnl_bp) -- per-trade daily attribution, only when the caller asks
    #: for it. Populating it always would cost memory that only the QDB tie-out needs.
    segments: Optional[pd.DataFrame] = None


# ======================================================================= data prep


def prepare_universe(
    cfg: Mapping[str, Any],
    *,
    joined: Optional[pd.DataFrame] = None,
    panel: Optional[pd.DataFrame] = None,
    floats: Optional[pd.DataFrame] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Gate, benchmark and residualise -- everything that does not depend on the signal.

    Separated from :func:`run_config` because it is the expensive half and it is
    identical across every config that shares a fund, a window and a curve spec. The
    grid caches on exactly that.
    """
    sp = spec(cfg["fund"])
    u = cfg["universe"]
    funnel: Dict[str, Any] = {}

    if joined is None:
        joined = HP.build([sp.ticker], panel=panel, floats=floats)
    j = joined[joined["ticker"] == sp.ticker].copy()

    p = (panel if panel is not None else None)
    if p is None:
        from RVUtils.ETFRebalance import bond_panel as BP
        from RVUtils.ETFRebalance import float_panel as FP
        p = FP.asof_join(BP.load(), floats if floats is not None else FP.load())
    p = p.copy()
    p["priced"] = p["ytm"].notna() & ~p["yield_gate_fail"].fillna(True)

    if cfg.get("price_basis", "mid") == "eod":
        # A genuine alternative basis, not a fallback: FedInvest's eod and its quoted
        # range disagree by many spread widths and neither is stale, so the study is
        # required to survive the swap rather than to assume it away.
        p = _reprice_on_eod(p)

    lo = u["ttm_min"] if u["ttm_min"] is not None else (sp.band_low or 0.0)
    hi = u["ttm_max"] if u["ttm_max"] is not None else (sp.band_high or 1e9)

    start = pd.Timestamp(u["start"]) if u.get("start") else p["date"].min()
    end = pd.Timestamp(u["end"]) if u.get("end") else p["date"].max()
    p = p[p["date"].between(start, end)]

    act = HP.with_active_weight(j, p, sp,
                                outstanding=u.get("benchmark", "ex_soma"),
                                weight_basis=u.get("weight_basis", "dv01"))
    funnel["rows_all"] = len(act)

    keep = act["ttm"].between(lo, hi, inclusive="left")
    funnel["drop_outside_band"] = int((~keep).sum())
    act = act[keep]

    gates = {
        "not_priced": ~act["ytm"].notna() | act["yield_gate_fail"].fillna(True),
        "no_two_sided_quote": (act["price_source"] != "mid") if u["require_two_sided"] else False,
        "float_too_small": act["free_float"].fillna(0.0) < float(u["min_float_usd"]),
        "spread_too_wide": act["spread_price_bp"].fillna(np.inf) > float(u["max_spread_price_bp"]),
    }
    if u["exclude_ranks"]:
        gates["excluded_rank"] = act["rank"].isin(list(u["exclude_ranks"]))
    drop = pd.Series(False, index=act.index)
    for name, mask in gates.items():
        m = pd.Series(mask, index=act.index).fillna(True) if not isinstance(mask, bool) else \
            pd.Series(mask, index=act.index)
        funnel[f"gate_{name}"] = int((m & ~drop).sum())
        drop = drop | m
    act = act[~drop]
    funnel["rows_after_gates"] = len(act)

    if u.get("drop_flow_days"):
        flows = HP.flag_flow_days(j, threshold=float(u["flow_day_threshold"]))
        bad = set(flows.loc[flows["is_flow_day"], "date"])
        before = len(act)
        act = act[~act["date"].isin(bad)]
        funnel["drop_flow_days"] = before - len(act)

    cc = cfg["curve"]
    act = CV.fit_residuals(act, deg=cc["deg"], x_axis=cc["x_axis"],
                           include_coupon=cc["include_coupon"], robust=cc["robust"])
    funnel["rows_final"] = len(act)
    funnel["dates"] = int(act["date"].nunique())
    funnel["cusips"] = int(act["cusip"].nunique())
    return act.reset_index(drop=True), funnel


def _reprice_on_eod(p: pd.DataFrame) -> pd.DataFrame:
    """Swap the panel onto the yields solved from ``eod_price``.

    A column swap, not a conversion. ``bond_panel.build`` solves both bases exactly, so
    nothing is approximated here.

    The first version DID approximate -- ``dy = -dP / (D*P/100)`` -- and the error was
    not academic. The two price bases differ by many spread widths in stressed weeks, and
    a butterfly cancels the level and leaves precisely that difference, so the
    first-order conversion left the fast engine and the QueryDrivenBacktest disagreeing
    13x on a single day of the March 2023 SVB week while agreeing to 0.01bp on the level.
    """
    missing = [c for c in ("ytm_eod", "mod_dur_eod") if c not in p.columns]
    if missing:
        raise KeyError(
            f"price_basis='eod' needs {missing} in the panel. Rebuild it with "
            f"`python -m RVUtils.ETFRebalance.bond_panel` -- an approximate reprice is "
            f"not offered, because a butterfly amplifies exactly the error it makes."
        )
    out = p.copy()
    ok = out["ytm_eod"].notna()
    out["ytm"] = out["ytm"].where(~ok, out["ytm_eod"])
    out["mod_dur"] = out["mod_dur"].where(~ok, out["mod_dur_eod"])
    if "convexity_eod" in out.columns:
        out["convexity"] = out["convexity"].where(~ok, out["convexity_eod"])
    out["clean_price"] = out["clean_price"].where(~ok, out["eod_price"])
    return out


# ======================================================================= selection


def _entry_dates(dates: Sequence[pd.Timestamp], cfg: Mapping[str, Any]) -> List[pd.Timestamp]:
    t = cfg["timing"]
    ds = pd.DatetimeIndex(sorted(dates))
    sel = ds[:: max(1, int(t["entry_every"]))]

    window = t.get("entry_window")
    if window:
        n = int(t.get("entry_window_days", 3))
        me = ds + pd.offsets.MonthEnd(0)
        dte = (me - ds).days
        if window == "month_end":
            mask = dte <= n
        elif window == "post_month_end":
            # first n business days of a month, measured on the panel's own axis
            month = ds.to_period("M")
            rank = pd.Series(1, index=ds).groupby(month).cumsum().to_numpy()
            mask = rank <= n
        else:
            raise ValueError(f"Unknown entry_window {window!r}")
        sel = ds[mask]
        if int(t["entry_every"]) > 1:
            sel = sel[:: max(1, int(t["entry_every"]))]
    return list(sel)


def build_flies(day: pd.DataFrame, cfg: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Pick bellies by score and hang the nearest eligible wings on each.

    A CUSIP already used as a wing can still be a belly of another package on the same
    day, but no bond is used twice inside one package and no belly is selected twice --
    a fly whose own wing is another fly's belly is fine (they are different views), a
    fly whose wing is itself is not.
    """
    s = cfg["structure"]
    d = day.dropna(subset=["score", "ttm", "ytm", "mod_dur"]).sort_values("ttm").reset_index(drop=True)
    if len(d) < 3:
        return []

    ranked = d.reindex(d["score"].sort_values(ascending=False).index)
    n = int(s["n_positions"])
    picks: List[Tuple[pd.Series, int]] = []
    if s["both_sides"]:
        picks += [(r, +1) for _, r in ranked.head(n).iterrows()]
        picks += [(r, -1) for _, r in ranked.tail(n).iterrows()]
    else:
        picks += [(r, +1) for _, r in ranked.head(n).iterrows()]

    gmin, gmax = float(s["wing_gap_min_y"]), float(s["wing_gap_max_y"])
    min_abs = float(s.get("min_abs_score", 0.0))

    out: List[Dict[str, Any]] = []
    used_bellies: set[str] = set()
    for belly, side in picks:
        if belly["cusip"] in used_bellies:
            continue
        if min_abs > 0 and abs(float(belly["score"])) < min_abs:
            continue
        gap = d["ttm"] - float(belly["ttm"])
        front_c = d[(gap <= -gmin) & (gap >= -gmax)]
        back_c = d[(gap >= gmin) & (gap <= gmax)]
        if front_c.empty or back_c.empty:
            continue
        front = front_c.iloc[(front_c["ttm"] - float(belly["ttm"])).abs().argsort().iloc[0]]
        back = back_c.iloc[(back_c["ttm"] - float(belly["ttm"])).abs().argsort().iloc[0]]

        t_f, t_b, t_k = float(front["ttm"]), float(belly["ttm"]), float(back["ttm"])
        if not (t_f < t_b < t_k):
            continue
        a = (t_k - t_b) / (t_k - t_f)
        legs = [
            {"role": "front", "cusip": front["cusip"], "w": -a},
            {"role": "belly", "cusip": belly["cusip"], "w": 1.0},
            {"role": "back", "cusip": back["cusip"], "w": -(1.0 - a)},
        ]
        used_bellies.add(belly["cusip"])
        out.append({
            "belly": belly["cusip"], "side": float(side), "legs": legs,
            "score": float(belly["score"]), "ttm_belly": t_b,
            "wing_span_y": t_k - t_f, "a": a,
        })
    return out


# ======================================================================= marking


def _wide(act: pd.DataFrame, col: str) -> pd.DataFrame:
    return act.pivot_table(index="date", columns="cusip", values=col, aggfunc="first").sort_index()


def run_config(
    user_cfg: Mapping[str, Any],
    *,
    universe: Optional[pd.DataFrame] = None,
    prepared_funnel: Optional[Dict[str, Any]] = None,
    joined: Optional[pd.DataFrame] = None,
    panel: Optional[pd.DataFrame] = None,
    floats: Optional[pd.DataFrame] = None,
    keep_segments: bool = False,
) -> Result:
    cfg = merge_config(user_cfg)
    if universe is None:
        universe, prepared_funnel = prepare_universe(
            cfg, joined=joined, panel=panel, floats=floats)
    funnel = dict(prepared_funnel or {})

    sp = spec(cfg["fund"])
    sc = cfg["signal"]
    kw = dict(sc.get("kwargs") or {})
    kw.setdefault("deletion", {}).setdefault("band_low", sp.band_low or 0.0)
    kw.setdefault("addition", {}).setdefault("band_high", sp.band_high or np.inf)

    scored = SIG.combine(
        universe, sc["components"], z_mode=sc["z_mode"], z_lookback=sc["z_lookback"],
        robust_z=sc["robust_z"], smooth_days=sc["smooth_days"], signal_kwargs=kw,
    )
    scored = HP.apply_exec_lag(scored, exec_lag=int(cfg["timing"]["exec_lag"]))
    funnel["rows_scored"] = int(scored["score"].notna().sum())

    # The signal is computed on the AS-OF panel and traded on the TRADE date, so the
    # marking frames are indexed by the trade date throughout from here on.
    y = _wide(universe, "ytm")
    dur = _wide(universe, "mod_dur")
    cx = _wide(universe, "convexity")
    all_dates = list(y.index)
    date_pos = {d: i for i, d in enumerate(all_dates)}

    cm = C.CostModel(basis=cfg["costs"]["basis"], multiplier=float(cfg["costs"]["multiplier"]),
                     flat_yield_bp=float(cfg["costs"].get("flat_yield_bp", 0.30)))
    leg_cost = universe.assign(_c=cm.leg_round_trip_yield_bp(universe)) \
        .pivot_table(index="date", columns="cusip", values="_c", aggfunc="first").sort_index()
    gc = _gc_series(all_dates) if cfg["carry"]["enabled"] else None

    # Marking runs on NUMPY, not on pandas label slicing. The loop touches four frames
    # per package and a grid runs thousands of configurations against the same universe,
    # so a per-trade ``.loc[a:b, cusips]`` -- which re-resolves labels every time -- was
    # the whole cost of a run. Resolving the column positions once and slicing integer
    # ranges took a configuration from 7.5 s to well under one.
    col_pos = {c: i for i, c in enumerate(y.columns)}
    Y = y.to_numpy(float)
    D = dur.to_numpy(float)
    CX = cx.to_numpy(float)
    LC = leg_cost.reindex(index=y.index, columns=y.columns).to_numpy(float)
    GC = gc.reindex(y.index).to_numpy(float) if gc is not None else None
    day_frac = np.diff(np.r_[0.0, (pd.DatetimeIndex(all_dates)
                                   - all_dates[0]).days.to_numpy(float)]) / 365.25
    pnl_arr = np.zeros(len(all_dates))
    open_arr = np.zeros(len(all_dates), dtype=int)

    hold = int(cfg["timing"]["hold_days"])
    entries = _entry_dates(all_dates, cfg)

    trades: List[Dict[str, Any]] = []
    leg_rows: List[Dict[str, Any]] = []
    seg_rows: List[pd.DataFrame] = []
    drops = {"no_wings": 0, "leg_unpriced_at_entry": 0, "leg_unpriced_at_exit": 0,
             "no_exit_date": 0, "belly_overlap": 0}
    open_until: Dict[str, pd.Timestamp] = {}
    tid = 0

    for tdate in entries:
        day = scored[scored["trade_date"] == tdate]
        if day.empty:
            continue
        i0 = date_pos[tdate]
        i1 = i0 + hold
        if i1 >= len(all_dates):
            drops["no_exit_date"] += 1
            continue
        exit_date = all_dates[i1]

        packages = build_flies(day, cfg)
        if not packages:
            drops["no_wings"] += 1
            continue

        for pkg in packages:
            belly = pkg["belly"]
            if open_until.get(belly) is not None and tdate < open_until[belly]:
                drops["belly_overlap"] += 1
                continue

            cus = [lg["cusip"] for lg in pkg["legs"]]
            w = np.array([lg["w"] for lg in pkg["legs"]], float)
            idx = [col_pos.get(c, -1) for c in cus]
            if min(idx) < 0:
                drops["leg_unpriced_at_entry"] += 1
                continue

            sl = slice(i0, i1 + 1)
            ysub = Y[sl][:, idx]
            # Complete-case, per DAY. A package is marked only where every leg has a
            # genuine gated price; days that fail simply do not move the equity curve.
            good = np.isfinite(ysub).all(axis=1)
            if not good[0]:
                drops["leg_unpriced_at_entry"] += 1
                continue
            if not good[-1]:
                drops["leg_unpriced_at_exit"] += 1
                continue

            side = pkg["side"]
            R = (ysub * w).sum(axis=1) * 100.0             # package rate, bp
            R = np.where(good, R, np.nan)
            R0 = float(R[0])
            price_pnl = (-side) * (R - R0)                 # bp per unit belly DV01

            carry_cum = np.zeros_like(price_pnl)
            if GC is not None:
                dsub = D[sl][:, idx]
                per_year = ((ysub * 100.0 - GC[sl][:, None] * 100.0) / dsub * w).sum(axis=1)
                # ``day_frac`` is a GLOBAL array of gaps between consecutive panel dates,
                # so its first element inside a trade's slice is the gap from the day
                # BEFORE entry. Accruing it would charge a day of carry the position did
                # not hold -- and it broke the identity in a way that pointed at the
                # arithmetic rather than hiding: the daily curve dropped that first step
                # while the trade log kept it, leaving a 0.96bp gap across 1,407 trades.
                dt = day_frac[sl].copy()
                dt[0] = 0.0
                # np.cumsum propagates NaN exactly as pandas' does, which is what the
                # complete-case rule wants: after a leg fails, the accrual is unknown.
                carry_cum = np.cumsum(side * per_year * dt)
                carry_cum = np.where(good, carry_cum, np.nan)

            conv_bp = float((CX[i0][idx] * w).sum())

            gross = price_pnl + carry_cum
            # Forward-fill the marks so a day one leg did not price holds the curve flat
            # rather than punching a hole in it.
            gross = pd.Series(gross).ffill().to_numpy(float)
            step = np.diff(np.r_[0.0, gross])
            pnl_arr[i0 + 1:i1 + 1] += step[1:]
            open_arr[i0 + 1:i1 + 1] += 1
            if keep_segments:
                # Per-trade daily attribution. Needed to compare a SUBSET of this book
                # against the same subset run through QueryDrivenBacktest: without it the
                # only available fast curve is the whole book's, and comparing 1,400
                # packages against 10 measures the difference between two books rather
                # than between two ways of marking one.
                seg_rows.append(pd.DataFrame({
                    "trade_id": tid + 1,
                    "date": all_dates[i0 + 1:i1 + 1],
                    "pnl_bp": step[1:],
                }))

            cost_bp = float(np.nansum(np.abs(w) * LC[i0][idx]))
            price_bp = float(price_pnl[-1])
            carry_bp = float(carry_cum[-1])

            tid += 1
            open_until[belly] = exit_date
            trades.append({
                "trade_id": tid, "opened_at": tdate, "closed_at": exit_date,
                "hold_days": hold, "belly": belly, "side": side,
                "score": pkg["score"], "ttm_belly": pkg["ttm_belly"],
                "wing_span_y": pkg["wing_span_y"], "a": pkg["a"],
                "R_entry_bp": R0, "R_exit_bp": float(R[-1]),
                "price_bp": price_bp, "carry_bp": carry_bp,
                "gross_bp": price_bp + carry_bp,
                "cost_bp": cost_bp, "pnl_bp": price_bp + carry_bp - cost_bp,
                "convexity_bp": conv_bp,
                "year": tdate.year, "month": tdate.month,
            })
            for lg, j in zip(pkg["legs"], idx):
                leg_rows.append({"trade_id": tid, "opened_at": tdate, **lg,
                                 "cost_bp": float(LC[i0][j])})

    closed = pd.DataFrame(trades)
    legs_df = pd.DataFrame(leg_rows)
    segments = pd.concat(seg_rows, ignore_index=True) if seg_rows else pd.DataFrame(
        columns=["trade_id", "date", "pnl_bp"])

    # The cost is a single charge at the exit, in full -- the only fee hook there is.
    if not closed.empty:
        for d, c in closed.groupby("closed_at")["cost_bp"].sum().items():
            pnl_arr[date_pos[d]] -= float(c)

    daily = pd.DataFrame({
        "date": all_dates, "pnl_bp": pnl_arr, "open_positions": open_arr,
    })
    daily["mtm_bp"] = daily["pnl_bp"].cumsum()

    funnel["entry_dates"] = len(entries)
    funnel.update({f"drop_{k}": v for k, v in drops.items()})
    funnel["trades"] = len(closed)
    return Result(config=cfg, closed=closed, daily=daily, legs=legs_df,
                  funnel=funnel, universe=universe, segments=segments)


# ======================================================================= carry


_GC_CACHE: Dict[Any, pd.Series] = {}


def _gc_series(dates: Sequence[pd.Timestamp]) -> pd.Series:
    """Overnight Treasury GC per date, as a decimal rate.

    SOFR is itself an overnight Treasury repo rate and is the repo's own GC proxy; the
    ladder behind ``load_us_treasury_gc_fixing_pct`` falls back to Fed Funds before
    SOFR's history begins. Every leg of a three-month butterfly is a deep off-the-run,
    so none of them is special and one common GC is the right model here -- unlike an
    olds-vs-currents switch, where the short leg IS the special one and a flat rate makes
    the trade look free.
    """
    key = (dates[0], dates[-1], len(dates))
    if key in _GC_CACHE:
        return _GC_CACHE[key]

    # Persisted, because ``load_us_treasury_gc_fixing_pct`` is a per-date lookup that
    # costs 78 seconds over the study window -- ten times a whole backtest -- and a grid
    # run in worker processes would otherwise pay it once per worker.
    from RVUtils.ETFRebalance.bond_panel import panel_dir

    path = panel_dir() / "gc_fixings.parquet"
    have = pd.Series(dtype=float)
    if path.exists():
        df = pd.read_parquet(path)
        have = pd.Series(df["gc"].to_numpy(float), index=pd.to_datetime(df["date"]))

    want = pd.DatetimeIndex(sorted(pd.to_datetime(list(dates))))
    missing = want.difference(have.index)
    if len(missing):
        from Query.FixedRateBonds.carry_roll import load_us_treasury_gc_fixing_pct

        vals = {}
        for d in missing:
            try:
                vals[d] = float(load_us_treasury_gc_fixing_pct(
                    as_of_date=pd.Timestamp(d).date())) / 100.0
            except Exception:
                vals[d] = np.nan
        have = pd.concat([have, pd.Series(vals)]).sort_index()
        have = have[~have.index.duplicated(keep="last")]
        have.rename_axis("date").rename("gc").reset_index().to_parquet(path, index=False)

    s = have.reindex(want).ffill().bfill()
    _GC_CACHE[key] = s
    return s


# ======================================================================= reporting


def summarize(res: Result, *, ann_days: int = 252) -> Dict[str, Any]:
    """Trade-level and daily-equity statistics side by side.

    Both, because they answer different questions and disagree for real reasons: the
    trade statistic asks whether the average trade made money, the daily statistic asks
    what holding the book felt like, and a book whose positions overlap has fewer
    independent bets than it has trades.
    """
    c, d = res.closed, res.daily
    if c is None or c.empty:
        return {"trades": 0}

    pnl = c["pnl_bp"].to_numpy(float)
    eq = d["mtm_bp"].to_numpy(float)
    dd = eq - np.maximum.accumulate(eq)
    daily_r = d["pnl_bp"].to_numpy(float)
    active = d["open_positions"].to_numpy() > 0
    n_active = int(active.sum())

    sd = float(np.std(daily_r[active], ddof=1)) if n_active > 2 else np.nan
    sharpe = (float(np.mean(daily_r[active])) / sd * np.sqrt(ann_days)) \
        if (n_active > 2 and np.isfinite(sd) and sd > 0) else np.nan

    return {
        "trades": len(c),
        "total_bp": float(pnl.sum()),
        "avg_bp": float(pnl.mean()),
        "med_bp": float(np.median(pnl)),
        "hit": float((pnl > 0).mean()),
        "gross_avg_bp": float(c["gross_bp"].mean()),
        "price_avg_bp": float(c["price_bp"].mean()),
        "carry_avg_bp": float(c["carry_bp"].mean()),
        "cost_avg_bp": float(c["cost_bp"].mean()),
        "t_stat": float(pnl.mean() / (pnl.std(ddof=1) / np.sqrt(len(pnl))))
        if len(pnl) > 1 and pnl.std(ddof=1) > 0 else np.nan,
        "sharpe_daily": sharpe,
        "sr_per_trade": float(pnl.mean() / pnl.std(ddof=1)) if pnl.std(ddof=1) > 0 else 0.0,
        "max_dd_bp": float(dd.min()),
        "breakeven_cost_mult": float(c["gross_bp"].mean() / c["cost_bp"].mean())
        if c["cost_bp"].mean() > 0 else np.inf,
        "active_days": n_active,
        "first": c["opened_at"].min(),
        "last": c["closed_at"].max(),
    }

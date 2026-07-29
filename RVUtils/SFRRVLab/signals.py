"""Premium-native signal panels shared across the SR3 RV frameworks.

Every panel here is built from LISTED settle premiums and listed deltas. Where
a framework's "fair value" would be pinned by put-call parity, the pinned part
is stated and only the free part is turned into a signal:

* **Risk reversals / wings** — the level of a wing pair is free (skew is not
  pinned by the forward); its history is the signal.
* **Digital calendars** — ``sum_K [P_back(>=K) - P_front(>=K)] dK`` is exactly
  the futures calendar spread, so the *level* of the digital-calendar profile is
  pinned by the linear market. Only its **shape across strikes** is free. The
  tradeable object is therefore the strike-butterfly of digital calendars, which
  is invariant to that constraint.
* **Straddles / vol** — the ATM straddle premium is a pure variance claim; the
  free part vs the futures market is implied-minus-realized.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.SFRRVLab.panels import pick_listed_strike, vertical_digital
from RVUtils.SFRRVLab.structures import (
    DOLLARS_PER_BP,
    Leg,
    MarkBook,
    Structure,
    mark_structure,
)

__all__ = [
    "risk_reversal_panel", "pair_rr_basis", "digital_calendar_panel",
    "vol_smile_panel", "wing_panel", "delta_hedged_pnl", "zscore_by_key",
    "quarterly_sort_key", "adjacent_pairs", "contract_pairs", "digital_legs",
]

_IMM_ORDER = {"H": 0, "M": 1, "U": 2, "Z": 3}


def quarterly_sort_key(symbol: str) -> Tuple[int, int]:
    """Chronological key for SFR-style quarterly codes (SFRU26 -> (26, 2))."""
    code, year = symbol[-3], symbol[-2:]
    if code in _IMM_ORDER and year.isdigit():
        return (int(year), _IMM_ORDER[code])
    return (9999, 0)


def adjacent_pairs(symbols: Sequence[str]) -> List[Tuple[str, str]]:
    s = sorted(set(symbols), key=quarterly_sort_key)
    return [(s[i], s[i + 1]) for i in range(len(s) - 1)]


def contract_pairs(symbols: Sequence[str],
                   gaps: Sequence[int] = (1,)) -> List[Tuple[str, str]]:
    """Chronologically ordered pairs at the given quarterly gaps.

    ``gaps=(1, 2)`` gives adjacent pairs plus 6-month pairs — a wider
    cross-section for the same panel, at the cost of overlapping legs between
    keys (the daily P&L is then a portfolio, and correlated trades are noted in
    the notebooks rather than assumed away).
    """
    s = sorted(set(symbols), key=quarterly_sort_key)
    out: List[Tuple[str, str]] = []
    for g in gaps:
        out.extend((s[i], s[i + g]) for i in range(len(s) - g))
    return out


# ---------------------------------------------------------------------------
def risk_reversal_panel(
    quotes: pd.DataFrame,
    contracts: pd.DataFrame,
    *,
    offset: float = 0.375,
    tol: float = 0.13,
    min_oi: float = 0.0,
) -> pd.DataFrame:
    """Per (as_of, symbol): the listed hike/cut wing pair at +/- ``offset`` in rate.

    The hike wing is a **put on price** at ``forward + offset`` (a payer); the
    cut wing is a **call on price** at ``forward - offset`` (a receiver).
    ``rr_bp = hk_prem - ct_prem`` — positive means the market pays up for hikes.
    """
    fwd = contracts.set_index(["as_of", "symbol"])["forward_rate"]
    rows = []
    for (ts, sym), g in quotes.groupby(["as_of", "symbol"], sort=False):
        f = fwd.get((ts, sym))
        if f is None or not np.isfinite(f):
            continue
        hk = pick_listed_strike(g, "P", f + offset, tol=tol, min_oi=min_oi)
        ct = pick_listed_strike(g, "C", f - offset, tol=tol, min_oi=min_oi)
        if hk is None or ct is None:
            continue
        rows.append({
            "as_of": ts, "symbol": sym, "forward_rate": float(f),
            "hk_K": float(hk["strike_price"]), "hk_prem": float(hk["premium_bp"]),
            "ct_K": float(ct["strike_price"]), "ct_prem": float(ct["premium_bp"]),
            "rr_bp": float(hk["premium_bp"] - ct["premium_bp"]),
            "wing_sum_bp": float(hk["premium_bp"] + ct["premium_bp"]),
            "oi_min": float(min(hk.get("oi", 0.0), ct.get("oi", 0.0))),
        })
    return pd.DataFrame(rows)


def pair_rr_basis(rr: pd.DataFrame, pairs: Optional[Sequence[Tuple[str, str]]] = None,
                  *, quality: Optional[pd.DataFrame] = None,
                  gaps: Sequence[int] = (1,)) -> pd.DataFrame:
    """Back-minus-front risk-reversal spread per pair (premium-native).

    ``gate`` is the leg-level gate — the wings were already OI-screened when the
    strikes were picked, so a pair-date with both wings listed and traded is
    tradeable. ``gate_bl`` carries the stricter Breeden-Litzenberger surface rule
    (``|forward residual| <= 2.5bp`` and mass <= 1.02) separately, because that
    rule mostly rejects days when the *listed chain is too narrow for BL to
    integrate to one* — a fit-domain problem, not evidence that the two wings
    being traded are stale. Notebooks report both.
    """
    if rr.empty:
        return pd.DataFrame()
    if pairs is None:
        pairs = contract_pairs(rr["symbol"].unique(), gaps=gaps)
    idx = rr.set_index(["as_of", "symbol"]).sort_index()
    gate = (quality.set_index(["as_of", "symbol"])["gate"]
            if quality is not None else None)
    out = []
    for front, back in pairs:
        try:
            f = idx.xs(front, level="symbol")
            b = idx.xs(back, level="symbol")
        except KeyError:
            continue
        j = f.join(b, how="inner", lsuffix="_f", rsuffix="_b")
        if j.empty:
            continue
        d = pd.DataFrame(index=j.index)
        d["key"] = f"{front}-{back}"
        d["front"], d["back"] = front, back
        d["signal"] = j["rr_bp_b"] - j["rr_bp_f"]
        for c in ("hk_K_f", "ct_K_f", "hk_K_b", "ct_K_b",
                  "hk_prem_f", "ct_prem_f", "hk_prem_b", "ct_prem_b"):
            d[c] = j[c]
        d["gate"] = True                      # leg-level: strikes were OI-screened
        if gate is not None:
            gf = gate.xs(front, level="symbol").reindex(j.index).fillna(False)
            gb = gate.xs(back, level="symbol").reindex(j.index).fillna(False)
            d["gate_bl"] = (gf & gb).to_numpy()
        else:
            d["gate_bl"] = True
        out.append(d.reset_index())
    if not out:
        return pd.DataFrame()
    return pd.concat(out, ignore_index=True).sort_values(["key", "as_of"])


# ---------------------------------------------------------------------------
def digital_calendar_panel(
    quotes: pd.DataFrame,
    contracts: pd.DataFrame,
    *,
    offsets: Sequence[float] = (-0.25, 0.0, 0.25),
    pairs: Optional[Sequence[Tuple[str, str]]] = None,
    tol: float = 0.02,
    min_oi: float = 0.0,
    anchor: str = "front",
) -> pd.DataFrame:
    """Digital calendars at a common RATE strike across adjacent expiries.

    For each pair and each ``offset`` (percent, relative to the ``anchor``
    contract's forward) the same absolute rate strike ``K`` is priced as a
    listed vertical on both contracts. ``cal`` is
    ``P_back(>=K) - P_front(>=K)`` — a tradeable calendar of listed verticals.

    The ``fly`` column is the strike-butterfly of ``cal`` across the three
    offsets, which is the part of the profile NOT pinned by the futures
    calendar spread (see module docstring). It is only produced when exactly
    three offsets are supplied and all three price.
    """
    fwd = contracts.set_index(["as_of", "symbol"])["forward_rate"]
    fwd_px = contracts.set_index(["as_of", "symbol"])["forward_price"]
    if pairs is None:
        pairs = adjacent_pairs(quotes["symbol"].unique())
    by_day = {k: v for k, v in quotes.groupby(["as_of", "symbol"], sort=False)}
    rows = []
    for front, back in pairs:
        dates = sorted({ts for (ts, s) in by_day if s == front}
                       & {ts for (ts, s) in by_day if s == back})
        for ts in dates:
            gf, gb = by_day[(ts, front)], by_day[(ts, back)]
            if min_oi > 0:
                gf, gb = gf[gf["oi"] >= min_oi], gb[gb["oi"] >= min_oi]
            f_anchor = fwd.get((ts, front if anchor == "front" else back))
            if f_anchor is None or not np.isfinite(f_anchor):
                continue
            rec: Dict[str, float] = {"as_of": ts, "key": f"{front}-{back}",
                                     "front": front, "back": back,
                                     "anchor_rate": float(f_anchor)}
            ok = True
            fp_f = float(fwd_px.get((ts, front), np.nan))
            fp_b = float(fwd_px.get((ts, back), np.nan))
            for o in offsets:
                k = float(f_anchor) + float(o)
                df_ = vertical_digital(gf, k, tol=tol, forward_price=fp_f)
                db_ = vertical_digital(gb, k, tol=tol, forward_price=fp_b)
                if df_ is None or db_ is None:
                    ok = False
                    break
                tag = f"{o:+.3f}"
                rec[f"K{tag}"] = k
                rec[f"pf{tag}"] = df_["prob"]
                rec[f"pb{tag}"] = db_["prob"]
                rec[f"cal{tag}"] = db_["prob"] - df_["prob"]
                for side, dd in (("f", df_), ("b", db_)):
                    rec[f"{side}_lo{tag}"] = dd["k_lo"]
                    rec[f"{side}_hi{tag}"] = dd["k_hi"]
                    rec[f"{side}_w{tag}"] = dd["width_bp"]
                    rec[f"{side}_r{tag}"] = dd["right"]
            if not ok:
                continue
            if len(offsets) == 3:
                a, b_, c = [f"cal{o:+.3f}" for o in offsets]
                rec["fly"] = rec[a] - 2.0 * rec[b_] + rec[c]
                rec["cal_atm"] = rec[b_]
            rows.append(rec)
    return pd.DataFrame(rows)


def digital_legs(symbol: str, k_lo: float, k_hi: float, right: str,
                 weight: float = 1.0) -> Tuple[Leg, ...]:
    """Listed vertical scaled to ONE unit of ``P(rate >= K)``.

    The scale is ``1 / width`` in price points, so a 6.25bp vertical trades 16
    lots a side and 25bp trades 4 — always whole lots on the CME ladder — and
    the package marks at ``100 x prob`` bp. The call-side digital is the
    complement of its vertical, so its legs carry the opposite sign; the
    constant that completes the complement is time-invariant and therefore drops
    out of every P&L, which is a change in the mark.
    """
    w = float(k_hi) - float(k_lo)
    if w <= 1e-9:
        raise ValueError(f"degenerate vertical width for {symbol}: {k_lo}/{k_hi}")
    s = weight / w
    if right == "P":
        return (Leg("option", symbol, s, "P", float(k_hi)),
                Leg("option", symbol, -s, "P", float(k_lo)))
    return (Leg("option", symbol, -s, "C", float(k_lo)),
            Leg("option", symbol, s, "C", float(k_hi)))


# ---------------------------------------------------------------------------
def vol_smile_panel(
    quotes: pd.DataFrame,
    contracts: pd.DataFrame,
    *,
    offset: float = 0.25,
    tol: float = 0.13,
    min_oi: float = 0.0,
) -> pd.DataFrame:
    """ATM / wing listed normal vols per (as_of, symbol) plus RR and FLY in vol space."""
    fwd = contracts.set_index(["as_of", "symbol"])["forward_rate"]
    rows = []
    for (ts, sym), g in quotes.groupby(["as_of", "symbol"], sort=False):
        f = fwd.get((ts, sym))
        if f is None or not np.isfinite(f):
            continue
        atm_c = pick_listed_strike(g, "C", f, tol=tol, min_oi=min_oi)
        atm_p = pick_listed_strike(g, "P", f, tol=tol, min_oi=min_oi)
        hk = pick_listed_strike(g, "P", f + offset, tol=tol, min_oi=min_oi)
        ct = pick_listed_strike(g, "C", f - offset, tol=tol, min_oi=min_oi)
        if atm_c is None or atm_p is None or hk is None or ct is None:
            continue
        atm_iv = float(np.nanmean([atm_c["iv_bp"], atm_p["iv_bp"]]))
        rows.append({
            "as_of": ts, "symbol": sym, "forward_rate": float(f),
            "atm_iv_bp": atm_iv,
            "hk_iv_bp": float(hk["iv_bp"]), "ct_iv_bp": float(ct["iv_bp"]),
            "rr_iv_bp": float(hk["iv_bp"] - ct["iv_bp"]),
            "fly_iv_bp": float(0.5 * (hk["iv_bp"] + ct["iv_bp"]) - atm_iv),
        })
    return pd.DataFrame(rows)


def wing_panel(
    quotes: pd.DataFrame, contracts: pd.DataFrame, *,
    offsets: Sequence[float] = (0.25, 0.375, 0.5), tol: float = 0.13,
    min_oi: float = 0.0,
) -> pd.DataFrame:
    """Single-wing listed premiums at several rate offsets, both sides."""
    fwd = contracts.set_index(["as_of", "symbol"])["forward_rate"]
    rows = []
    for (ts, sym), g in quotes.groupby(["as_of", "symbol"], sort=False):
        f = fwd.get((ts, sym))
        if f is None or not np.isfinite(f):
            continue
        rec = {"as_of": ts, "symbol": sym, "forward_rate": float(f)}
        for o in offsets:
            hk = pick_listed_strike(g, "P", f + o, tol=tol, min_oi=min_oi)
            ct = pick_listed_strike(g, "C", f - o, tol=tol, min_oi=min_oi)
            if hk is not None:
                rec[f"hk{o:g}_K"] = float(hk["strike_price"])
                rec[f"hk{o:g}_bp"] = float(hk["premium_bp"])
            if ct is not None:
                rec[f"ct{o:g}_K"] = float(ct["strike_price"])
                rec[f"ct{o:g}_bp"] = float(ct["premium_bp"])
        rows.append(rec)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
def delta_hedged_pnl(
    book: MarkBook,
    option_legs: Sequence[Leg],
    dates: Sequence[pd.Timestamp],
    *,
    hedge_symbol: str,
    rehedge_band: float = 0.0,
    future_cost_bp: float = 0.25,
) -> pd.DataFrame:
    """Daily P&L of an option package delta-hedged on futures settles.

    The hedge held over ``[t, t+1]`` is set from the delta observed at ``t``
    (never at ``t+1``), so the gamma P&L is earned honestly. ``rehedge_band`` is
    the absolute delta drift tolerated before re-hedging; every actual re-hedge
    is charged ``future_cost_bp`` on the traded delta.

    Returns a frame indexed by date with ``opt_bp`` (package premium), ``d_opt``,
    ``d_hedge``, ``hedge_cost_bp`` and ``pnl_bp`` (= d_opt + d_hedge - cost).
    """
    idx = pd.DatetimeIndex(dates)
    st = Structure(tuple(option_legs), label="dh")
    opt, _ = mark_structure(book, st, idx)
    fut = book.series(Leg("future", hedge_symbol))
    if fut is None:
        raise ValueError(f"no futures marks for {hedge_symbol}")
    fut = fut.reindex(idx).ffill()

    deltas = []
    for leg in option_legs:
        s = book.delta_series(leg)
        d = (s.reindex(idx).ffill() if s is not None
             else pd.Series(0.0, index=idx))
        deltas.append(leg.weight * d.fillna(0.0).to_numpy())
    net_delta = np.sum(deltas, axis=0)

    hedge = np.zeros(len(idx))
    cost = np.zeros(len(idx))
    cur = 0.0
    for t in range(len(idx)):
        target = -net_delta[t]
        if t == 0 or abs(target - cur) > rehedge_band:
            cost[t] = abs(target - cur) * future_cost_bp
            cur = target
        hedge[t] = cur

    f = fut.to_numpy(dtype=float)
    d_opt = np.diff(opt, prepend=opt[0])
    d_hedge = np.zeros(len(idx))
    d_hedge[1:] = hedge[:-1] * np.diff(f)
    out = pd.DataFrame({
        "opt_bp": opt, "fut_bp": f, "net_delta": net_delta, "hedge": hedge,
        "d_opt": d_opt, "d_hedge": d_hedge, "hedge_cost_bp": cost,
    }, index=idx)
    out["pnl_bp"] = out["d_opt"] + out["d_hedge"] - out["hedge_cost_bp"]
    out.iloc[0, out.columns.get_loc("pnl_bp")] = -cost[0]
    out.iloc[0, out.columns.get_loc("d_opt")] = 0.0
    return out


# ---------------------------------------------------------------------------
def zscore_by_key(
    df: pd.DataFrame, col: str = "signal", *, ma: int = 5, window: int = 120,
    min_periods: int = 40, key: str = "key",
) -> pd.DataFrame:
    """Add ``{col}_z`` (rolling, per key) using the engine's exact convention."""
    out = df.sort_values([key, "as_of"]).reset_index(drop=True).copy()
    g = out.groupby(key)[col]
    s = g.transform(lambda x: x.rolling(ma).mean())
    mu = s.groupby(out[key]).transform(
        lambda x: x.rolling(window, min_periods=min_periods).mean())
    sd = s.groupby(out[key]).transform(
        lambda x: x.rolling(window, min_periods=min_periods).std(ddof=0))
    out[f"{col}_z"] = (s - mu) / sd.where(sd > 1e-12)
    return out

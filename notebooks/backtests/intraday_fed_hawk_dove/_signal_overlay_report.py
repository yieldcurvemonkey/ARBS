r"""Does conditioning the Fed speaker book on the macro state pay?

    conda run -n stir python notebooks/backtests/intraday_fed_hawk_dove/_signal_overlay_report.py

Writes ``_signal_overlay_results.pkl`` beside itself. The notebook reads that
pickle; the expensive part is a plain process that can be watched and killed.

The design decision that makes this cheap and honest
----------------------------------------------------
``mode="flip"`` and ``mode="size"`` are **book-preserving**: the same events, the
same entries, the same exits, the same ``d_rate_bp``. Only the side or the size
moves. ``_probe20_signal_knob.py`` proves that against the engine, route 4.

So the whole flip/size grid -- every lead, every threshold, both readings, both
modes -- can be computed from ONE baseline run per (window, instrument), by
negating the rows the rule selects. And so can its null: rotate the weekly state,
re-select, re-negate. Thousands of rotations cost seconds instead of thousands of
backtests, which is what makes an exact rotation null affordable here at all.

It also makes the comparison **paired**. The conditioned book and the baseline
trade the same events, so their difference is not confounded by the
one-position-at-a-time rule choosing differently, by bar coverage, or by the
sample. ``project_fomc_nonvoter_fade`` measured what that confound is worth: the
combined book there was not the sum of its parts because 52 voter trades worth
+41.5bp were displaced by non-voter positions holding the slot.

``mode="gate"`` is NOT book-preserving -- it removes events before the
one-position rule, so a later event can claim a slot a removed one would have
blocked. Those cells are run through the real engine, and they are compared only
against a baseline carrying the same date filters.

The null, and why it is the rotated STATE
-----------------------------------------
An event-level sign-flip or a random partition of the events treats every trade
as independent. The macro state does not move that way: it holds a sign for
months, so a "random partition" of the same size is a far weaker competitor than
a rotation of the real state, which keeps the state's persistence, its marginals
and its run lengths and destroys only its alignment with the calendar.

``project_fomc_nonvoter_fade`` is the cautionary case: flipping 155 non-voter
trades beat 99.9% of random 155-of-504 partitions -- and demeaning those rows so
their drift was exactly zero still rejected at p ~ 0.02, because the p-value was
carried by the rows that were NOT flipped. A rotation null cannot be gamed that
way: every surrogate flips a subset with the same time-series structure.

Sign-flip on the trades is reported too, and is secondary, always.

Pre-registered primary cells, written before anything ran
---------------------------------------------------------
``A``  state ``data``, ``lead_w = 0``, ``threshold = 0.5``, ``when = agree``,
       ``mode = flip``, ``OUT_3``, the whole book.
       Reading: a speech that says what the data already said is anticipatable,
       so FADE it. ``lead_w = 0`` because the honest starting point is that the
       tradeable information is where the data stands now, and because 21 years
       of FedLock put any durable lead at +1 to +2 weeks -- inside the weekly
       grid's own resolution. ``0.5`` because a half-sigma is the loosest band
       that still means "the data is saying something".

``B``  state ``detach``, ``lead_w = 0``, ``threshold = 1.0``, ``when = agree``,
       ``mode = flip``, ``OUT_3``, the detach window.
       Reading: when Fedspeak has already run hawkish relative to the data, one
       more hawk is priced. ``1.0`` because a one-sigma gap is the conventional
       bar for "detached" and is what ``fed_detachment_rv`` pre-registered.
"""
from __future__ import annotations

import io
import itertools
import pickle
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
for _p in (str(REPO), str(REPO / "notebooks" / "rv"), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP  # noqa: E402

import global_hawk_dove_common as G  # noqa: E402
import hawk_dove_config as HC  # noqa: E402
import fed_signal_overlay as SIG  # noqa: E402

CACHE = HERE / "_global_cache"
OUT = HERE / "_signal_overlay_results.pkl"

#: One-way listed cost per contract, bp of rate. An SR3 outright round trip is
#: 0.50bp (``reference_sfr_fly_conventions``). The baseline books are run at
#: ZERO cost and the cost is applied analytically, so it can be swept without
#: re-running the engine.
COST_ROUND_TRIP_BP = 0.50

#: The two windows. They are never pooled: one is the notebook's live config and
#: the other is the whole raw book, and a statistic from one is not comparable
#: with a statistic from the other.
WINDOWS: Dict[str, Dict[str, Any]] = {
    "LIVE": {
        "note": "the notebook's live config: 2022+, SR3, voters only, >=10d from a meeting",
        "filters": {"start": "2022-01-01", "end": None, "voters": "voters",
                    "roles": None, "speakers_include": None, "speakers_exclude": None,
                    "timestamp_source": "all", "min_abs_bucket": 1,
                    "direction": "both", "era": "SR3", "days_to_fomc_max": None,
                    "days_to_fomc_min": 10, "weekdays": None},
    },
    "ALL": {
        "note": "the whole raw FED book, 2019-2026, every speaker, both contract roots",
        "filters": {"start": None, "end": None, "voters": "all", "roles": None,
                    "speakers_include": None, "speakers_exclude": None,
                    "timestamp_source": "all", "min_abs_bucket": 1,
                    "direction": "both", "era": "all", "days_to_fomc_max": None,
                    "days_to_fomc_min": None, "weekdays": None},
    },
}

INSTRUMENTS: Dict[str, Dict[str, Any]] = {
    "OUT_2": {"kind": "outright", "rank": 2},
    "OUT_3": {"kind": "outright", "rank": 3},
    "OUT_4": {"kind": "outright", "rank": 4},
}

LEADS: Tuple[int, ...] = (0, 2, 5, 11)
THRESHOLDS: Tuple[float, ...] = (0.0, 0.5, 1.0)
WHENS: Tuple[str, ...] = ("agree", "disagree")

BASE_TIMING = {"entry_offset_min": -60, "exit_offset_min": 240,
               "max_staleness_min": 45, "retime_synthetic": False}


def _p(*a):
    print(*a, flush=True)


# ==========================================================================
# baselines
# ==========================================================================
def baseline(window: str, instrument: str, raw, mdp) -> "HC.Result":
    """The unconditioned book, at ZERO cost.

    Cost is applied analytically downstream so that a cost sweep does not need
    the engine, and so that the flip's cost accounting is explicit: flipping
    negates the GROSS P&L and leaves the round trip payable either way, i.e.
    ``flipped_net = -gross - cost``, never ``-net``.
    """
    cfg = {"name": f"{window}/{instrument}/baseline", "bank": "FED",
           "instrument": INSTRUMENTS[instrument], "timing": dict(BASE_TIMING),
           "filters": dict(WINDOWS[window]["filters"]),
           "flip": "none", "sizing": "equal", "cost_bp": 0.0,
           "signal": {"mode": "off"}}
    return HC.run_config(cfg, raw, mdp)


def attach_state(closed: pd.DataFrame, state: pd.Series,
                 sig: Dict[str, Any]) -> pd.DataFrame:
    """Per-trade state, joined on the day the position OPENED.

    Uses ``opened_at`` -- the RETIMED entry, which is what the trade actually
    did -- rather than the raw ``entry_ts`` the config's own join reads. The two
    can differ by the difference between the raw builder's -45 minute offset and
    the config's -60, which is why :func:`tie_out_state` cross-checks this
    against the column the engine attached instead of assuming they agree.
    """
    out = closed.copy()
    idx = state.index.values
    days = pd.DatetimeIndex(pd.to_datetime(out["opened_at"], utc=True)
                            ).tz_localize(None).normalize().values
    pos = np.searchsorted(idx, days, side="left") - 1
    vals = np.where(pos >= 0, state.to_numpy(float)[np.clip(pos, 0, len(idx) - 1)],
                    np.nan)
    vals = np.where(pos >= 0, vals, np.nan)
    out["state_value_calc"] = vals
    out["state_week_calc"] = np.where(
        pos >= 0, pd.DatetimeIndex(idx[np.clip(pos, 0, len(idx) - 1)]).astype("datetime64[ns]"),
        np.datetime64("NaT"))
    thr = float(sig.get("threshold", 0.0))
    sgn = np.where(np.isfinite(vals) & (np.abs(vals) >= thr) & (vals != 0),
                   np.sign(vals), 0).astype(int)
    out["state_sign_calc"] = sgn
    return out


def tie_out_state(closed: pd.DataFrame, state: pd.Series,
                  sig: Dict[str, Any]) -> Dict[str, Any]:
    """The analytic join must reproduce the engine's own, on the same events.

    Verifying the checker. Everything downstream is computed from the analytic
    join, so if it disagrees with what ``hawk_dove_config`` attached, every
    number in this report describes a different rule than the one the engine
    would trade.
    """
    if "state_value" not in closed.columns:
        return {"checked": 0, "note": "engine column absent (signal mode off)"}
    a = attach_state(closed, state, sig)
    both = a[["state_value", "state_value_calc"]].dropna()
    if both.empty:
        return {"checked": 0, "note": "no overlap"}
    worst = float((both["state_value"] - both["state_value_calc"]).abs().max())
    assert worst < 1e-12, (
        f"the analytic state join disagrees with the engine's by {worst:.3e} -- "
        f"every number computed from it describes a different rule")
    return {"checked": int(len(both)), "worst_abs_diff": worst}


# ==========================================================================
# the conditioned book, computed from the baseline frame
# ==========================================================================
def selection(bucket: np.ndarray, state_sign: np.ndarray, when: str) -> np.ndarray:
    """Which trades the rule acts on. ``state_sign == 0`` is never selected."""
    live = state_sign != 0
    agrees = (bucket > 0) == (state_sign > 0)
    return live & (agrees if when == "agree" else ~agrees)


def conditioned_pnl(gross: np.ndarray, sel: np.ndarray, cost_bp: float) -> np.ndarray:
    """Flip the selected rows. The round trip is payable either way round.

    ``-(g) - cost`` and not ``-(g - cost)``: taking the second would refund the
    cost on every faded trade and quietly pay the book to change its mind.
    """
    g = np.where(sel, -gross, gross)
    return g - cost_bp


def score(pnl: np.ndarray, opened: pd.Series) -> Dict[str, float]:
    """Per-trade statistics plus a Sharpe annualised by the book's own frequency."""
    p = np.asarray(pnl, float)
    if p.size < 2:
        return {"trades": int(p.size), "total_bp": float(p.sum()) if p.size else np.nan,
                "avg_bp": np.nan, "sharpe_ann": np.nan, "t_stat": np.nan,
                "hit": np.nan, "max_dd_bp": np.nan}
    sd = float(p.std(ddof=1))
    span_y = max((pd.Timestamp(opened.max()) - pd.Timestamp(opened.min())).days / 365.25,
                 1e-9)
    per_year = len(p) / span_y
    eq = np.cumsum(p)
    return {"trades": int(p.size), "total_bp": float(p.sum()),
            "avg_bp": float(p.mean()),
            "sharpe_ann": float(p.mean() / sd * np.sqrt(per_year)) if sd > 0 else np.nan,
            "t_stat": float(p.mean() / (sd / np.sqrt(len(p)))) if sd > 0 else np.nan,
            "hit": float((p > 0).mean()),
            "trades_per_year": float(per_year),
            "max_dd_bp": float((eq - np.maximum.accumulate(eq)).min())}


def _state_sign_on(state: pd.Series, days: np.ndarray, thr: float) -> np.ndarray:
    idx = state.index.values
    pos = np.searchsorted(idx, days, side="left") - 1
    v = np.where(pos >= 0, state.to_numpy(float)[np.clip(pos, 0, len(idx) - 1)], np.nan)
    return np.where(np.isfinite(v) & (np.abs(v) >= thr) & (v != 0),
                    np.sign(v), 0).astype(int)


# ==========================================================================
# the null
# ==========================================================================
def rotation_offsets(n: int, max_lead: int) -> np.ndarray:
    """Rotations that cannot reproduce the true alignment.

    The holding period is intraday, so it contributes no weeks; the widest
    alignment searched is the largest lead. ``min_offset = 2*max_lead + 1``,
    the same arithmetic ``reference_rotation_null_self_match`` fixes.
    """
    m = 2 * int(max_lead) + 1
    if n <= 2 * m:
        return np.array([], dtype=int)
    return np.arange(m, n - m + 1, dtype=int)


def rotation_null(frame: pd.DataFrame, states: Dict[int, pd.Series], *,
                  leads: Sequence[int], thresholds: Sequence[float],
                  whens: Sequence[str], cost_bp: float, state_kind: str,
                  draws: int, rng: np.random.Generator) -> Dict[str, Any]:
    """Rotate the weekly state and re-score the ENTIRE grid, every time.

    The searched maximum is what the observation is, so it is what every
    surrogate must be scored on. Scoring the null on a single cell while
    reporting the grid's best would compare a maximum against a draw.
    """
    gross = frame["pnl_bp_gross"].to_numpy(float)
    bucket = frame["bucket"].to_numpy(int)
    opened = pd.to_datetime(frame["opened_at"], utc=True)
    days = pd.DatetimeIndex(opened).tz_localize(None).normalize().values

    n = min(len(s) for s in states.values())
    offs = rotation_offsets(n, max(leads))
    if offs.size == 0:
        return {"n_offsets": 0, "note": "sample too short for a legal rotation"}
    exhaustive = offs.size <= draws
    if not exhaustive:
        offs = np.sort(rng.choice(offs, size=draws, replace=False))

    maxima = np.empty(offs.size)
    for i, o in enumerate(offs):
        best = -np.inf
        for lead in leads:
            st = states[int(lead)]
            rot = pd.Series(np.roll(st.to_numpy(float), int(o)), index=st.index)
            for thr in thresholds:
                sgn = _state_sign_on(rot, days, float(thr))
                for when in whens:
                    sel = selection(bucket, sgn, when)
                    pnl = conditioned_pnl(gross, sel, cost_bp)
                    sd = pnl.std(ddof=1)
                    if sd > 0:
                        best = max(best, float(pnl.mean() / sd))
        maxima[i] = best
    m = maxima[np.isfinite(maxima)]
    return {"n_offsets": int(offs.size), "stats": m,
            "distinct": int(rotation_offsets(n, max(leads)).size),
            "exhaustive": bool(exhaustive),
            "min_offset": int(2 * max(leads) + 1),
            "q50": float(np.quantile(m, 0.5)) if m.size else np.nan,
            "q95": float(np.quantile(m, 0.95)) if m.size else np.nan,
            "p_floor": 1.0 / (m.size + 1) if m.size else np.nan}


def rotation_p(observed: float, null: Dict[str, Any]) -> float:
    st = np.asarray(null.get("stats", []), float)
    if st.size == 0 or not np.isfinite(observed):
        return np.nan
    return float((1 + np.sum(st >= observed)) / (st.size + 1))


def sign_flip_p(pnl: np.ndarray, *, draws: int = 20000,
                rng: Optional[np.random.Generator] = None) -> float:
    """Secondary. Treats every trade as independent, which the state is not."""
    p = np.asarray(pnl, float)
    p = p[np.isfinite(p)]
    if p.size < 8:
        return np.nan
    rng = rng or np.random.default_rng(0)
    obs = abs(float(p.mean() / p.std(ddof=1))) if p.std(ddof=1) > 0 else np.nan
    sims = rng.choice([-1.0, 1.0], size=(draws, p.size)) * p
    mu, sd = sims.mean(axis=1), sims.std(axis=1, ddof=1)
    stat = np.abs(np.where(sd > 0, mu / sd, np.nan))
    ok = np.isfinite(stat)
    return float((1 + np.sum(stat[ok] >= obs)) / (1 + ok.sum()))


# ==========================================================================
# one arm
# ==========================================================================
def run_arm(*, label: str, state_kind: str, window: str, raw, mdp,
            instruments: Sequence[str] = tuple(INSTRUMENTS),
            leads: Sequence[int] = LEADS,
            thresholds: Sequence[float] = THRESHOLDS,
            whens: Sequence[str] = WHENS,
            cost_bp: float = COST_ROUND_TRIP_BP,
            draws: int = 4000, seed: int = 20260824,
            with_gate: bool = True) -> Dict[str, Any]:
    out: Dict[str, Any] = {"label": label, "state": state_kind, "window": window,
                           "window_note": WINDOWS[window]["note"],
                           "cost_bp": cost_bp}
    rng = np.random.default_rng(seed)

    # ---- the states, one per lead ------------------------------------
    states: Dict[int, pd.Series] = {}
    prov = {}
    for lead in leads:
        sig = SIG.normalise({"mode": "flip", "state": state_kind, "lead_w": int(lead)})
        st, pv = SIG.build_state(sig)
        states[int(lead)] = st
        prov[int(lead)] = pv
    out["state_provenance"] = prov

    # ---- the common window: every cell must see the same events -------
    # A state that starts in 2023 turns "condition on the data" into "trade only
    # the SR3 era". The baseline is therefore restricted to the events EVERY
    # lead can price, and the restriction is reported.
    first_usable = max(pd.Timestamp(s.dropna().index.min()) for s in states.values())
    out["first_usable_week"] = first_usable

    per_inst = {}
    for inst in instruments:
        base = baseline(window, inst, raw, mdp)
        cl = base.closed
        if cl.empty:
            per_inst[inst] = {"error": "empty baseline book"}
            continue
        opened = pd.to_datetime(cl["opened_at"], utc=True).dt.tz_localize(None)
        keep = opened.dt.normalize() > first_usable
        cl = cl.loc[keep].reset_index(drop=True)
        if len(cl) < 20:
            per_inst[inst] = {"error": f"only {len(cl)} trades after the state starts"}
            continue

        # ONE grid builder for both kinds. ``SIG.build_state`` already applies
        # the lead -- as a shift for ``data``, inside the construction for
        # ``detach`` -- so ``states[lead]`` is the right series either way and
        # this code never has to know which.
        league, sels, keys = _grid_multi_state(
            cl, states, leads=leads, thresholds=thresholds, whens=whens,
            cost_bp=cost_bp, state_kind=state_kind)

        gross = cl["pnl_bp_gross"].to_numpy(float)
        base_pnl = gross - cost_bp
        base_score = score(base_pnl, pd.to_datetime(cl["opened_at"], utc=True))
        best_i = int(league["sharpe_ann"].idxmax()) if league["sharpe_ann"].notna().any() else -1

        # the searched maximum, on the same per-trade Sharpe the null scores
        per_trade_sr = []
        for j in range(len(keys)):
            p = conditioned_pnl(gross, sels[j], cost_bp)
            sd = p.std(ddof=1)
            per_trade_sr.append(float(p.mean() / sd) if sd > 0 else np.nan)
        per_trade_sr = np.asarray(per_trade_sr, float)
        observed = float(np.nanmax(per_trade_sr)) if np.isfinite(per_trade_sr).any() else np.nan

        null = rotation_null(cl, states, leads=leads, thresholds=thresholds,
                             whens=whens, cost_bp=cost_bp, state_kind=state_kind,
                             draws=draws, rng=rng)
        p_rot = rotation_p(observed, null)

        per_inst[inst] = {
            "n_trades": int(len(cl)),
            "first": str(pd.Timestamp(cl["opened_at"].min()).date()),
            "last": str(pd.Timestamp(cl["opened_at"].max()).date()),
            "baseline": base_score,
            "baseline_sign_flip_p": sign_flip_p(base_pnl, rng=np.random.default_rng(seed + 1)),
            "league": league,
            "best_cell": league.iloc[best_i].to_dict() if best_i >= 0 else None,
            "observed_max_sharpe_per_trade": observed,
            "rotation_null": {k: v for k, v in null.items() if k != "stats"},
            "p_rotation": p_rot,
            "null_percentile": (float((np.asarray(null.get("stats", []), float) < observed).mean())
                                if np.size(null.get("stats", [])) and np.isfinite(observed) else np.nan),
            "tie_out": _tie_out(cl, states, raw, mdp, window, inst, state_kind),
            "closed": cl,
        }
        _p(f"    {inst}: {len(cl)} trades {per_inst[inst]['first']}..{per_inst[inst]['last']}  "
           f"baseline {base_score['total_bp']:+.1f}bp SR {base_score['sharpe_ann']:.2f}  |  "
           f"best cell SR/trade {observed:.4f} vs null q50 {null.get('q50', float('nan')):.4f} "
           f"q95 {null.get('q95', float('nan')):.4f}  p_rot {p_rot:.4f}")

    out["instruments"] = per_inst

    # ---- the gate cells, which need the real engine -------------------
    if with_gate:
        out["gate"] = _run_gate_cells(window, state_kind, raw, mdp,
                                      leads=leads, thresholds=thresholds,
                                      whens=whens, first_usable=first_usable,
                                      cost_bp=cost_bp)
    return out


def _tie_out(cl, states, raw, mdp, window, inst, state_kind) -> Dict[str, Any]:
    """Run ONE conditioned config through the real engine and require this
    module's analytic flip to reproduce it exactly.

    Everything in this report is computed by negating rows of a baseline frame.
    If that shortcut ever disagrees with what ``hawk_dove_config`` would
    actually trade, every number here describes a different rule -- and it would
    look completely normal. So the shortcut is checked against the engine, once
    per instrument, on a cell chosen before the results are seen.
    """
    lead, thr, when = 0, 0.5, "agree"
    cfg = {"name": "tieout", "bank": "FED", "instrument": INSTRUMENTS[inst],
           "timing": dict(BASE_TIMING), "filters": dict(WINDOWS[window]["filters"]),
           "flip": "none", "sizing": "equal", "cost_bp": 0.0,
           "signal": {"mode": "flip", "state": state_kind, "lead_w": lead,
                      "threshold": thr, "when": when}}
    try:
        eng = HC.run_config(cfg, raw, mdp).closed
    except RuntimeError as e:
        return {"checked": 0, "note": str(e)[:70]}
    eng = eng.set_index("tag")
    common = [t for t in cl["tag"] if t in eng.index]
    if len(common) < 20:
        return {"checked": len(common), "note": "too few shared trades"}
    sub = cl.set_index("tag").loc[common]
    days = pd.DatetimeIndex(pd.to_datetime(sub["opened_at"], utc=True)
                            ).tz_localize(None).normalize().values
    sgn = _state_sign_on(states[lead], days, thr)
    sel = selection(sub["bucket"].to_numpy(int), sgn, when)
    mine = conditioned_pnl(sub["pnl_bp_gross"].to_numpy(float), sel, 0.0)
    theirs = eng.loc[common, "pnl_bp"].to_numpy(float)
    worst = float(np.abs(mine - theirs).max())
    assert worst < 1e-9, (
        f"the analytic flip disagrees with the engine by {worst:.3e}bp on "
        f"{inst}/{window}/{state_kind} -- every number in this report describes "
        f"a different rule than the one the engine would trade")
    return {"checked": int(len(common)), "worst_abs_diff_bp": worst,
            "cell": f"L{lead}/thr{thr}/{when}",
            "n_flipped_engine": int((eng.loc[common, "signal_flip"] < 0).sum()),
            "n_flipped_here": int(sel.sum())}


def _grid_multi_state(frame: pd.DataFrame, states: Dict[int, pd.Series], *,
                      leads, thresholds, whens, cost_bp, state_kind):
    """The grid when each lead is its OWN series (the ``detach`` construction)."""
    gross = frame["pnl_bp_gross"].to_numpy(float)
    bucket = frame["bucket"].to_numpy(int)
    opened = pd.to_datetime(frame["opened_at"], utc=True)
    days = pd.DatetimeIndex(opened).tz_localize(None).normalize().values
    base = score(gross - cost_bp, opened)
    keys, rows, sels = [], [], []
    for lead, thr, when in itertools.product(leads, thresholds, whens):
        sgn = _state_sign_on(states[int(lead)], days, float(thr))
        sel = selection(bucket, sgn, when)
        pnl = conditioned_pnl(gross, sel, cost_bp)
        s = score(pnl, opened)
        rows.append({"state": state_kind, "lead_w": int(lead), "threshold": float(thr),
                     "when": when, "n_selected": int(sel.sum()),
                     "share_selected": float(sel.mean()), **s,
                     "baseline_total_bp": base["total_bp"],
                     "baseline_sharpe_ann": base["sharpe_ann"],
                     "delta_total_bp": s["total_bp"] - base["total_bp"],
                     "delta_sharpe": s["sharpe_ann"] - base["sharpe_ann"]})
        keys.append((state_kind, int(lead), float(thr), when))
        sels.append(sel)
    return pd.DataFrame(rows), np.vstack(sels), keys


def _run_gate_cells(window: str, state_kind: str, raw, mdp, *, leads, thresholds,
                    whens, first_usable, cost_bp) -> pd.DataFrame:
    """``mode='gate'`` through the real engine, against a same-window baseline.

    A gate removes events BEFORE the one-position-at-a-time rule, so the gated
    book is not a subset of the ungated one's trades: a later event can claim a
    slot a removed one would have blocked. That is why every gated cell is
    compared against a baseline carrying the SAME date filters, and never
    against the headline book.
    """
    start = str((pd.Timestamp(first_usable) + pd.Timedelta(days=1)).date())
    filt = {**WINDOWS[window]["filters"], "start": start}
    rows = []
    base_cfg = {"name": "gate-baseline", "bank": "FED",
                "instrument": INSTRUMENTS["OUT_3"], "timing": dict(BASE_TIMING),
                "filters": dict(filt), "flip": "none", "sizing": "equal",
                "cost_bp": cost_bp, "signal": {"mode": "off"}}
    b = HC.run_config(base_cfg, raw, mdp)
    bs = b.summary
    rows.append({"cell": "BASELINE (same window)", "state": state_kind,
                 "lead_w": None, "threshold": None, "when": None,
                 "trades": bs.get("trades"), "total_bp": bs.get("total"),
                 "avg_bp": bs.get("avg"), "sharpe_ann": bs.get("sharpe"),
                 "t_stat": bs.get("t_stat"), "max_dd": bs.get("max_dd")})
    for lead, thr, when in itertools.product(leads, thresholds, whens):
        cfg = {**base_cfg, "name": f"gate/{state_kind}/L{lead}/thr{thr}/{when}",
               "signal": {"mode": "gate", "state": state_kind, "lead_w": int(lead),
                          "threshold": float(thr), "when": when}}
        try:
            r = HC.run_config(cfg, raw, mdp)
        except RuntimeError as e:
            rows.append({"cell": cfg["name"], "state": state_kind, "lead_w": lead,
                         "threshold": thr, "when": when, "trades": 0,
                         "note": str(e)[:70]})
            continue
        s = r.summary
        rows.append({"cell": cfg["name"], "state": state_kind, "lead_w": int(lead),
                     "threshold": float(thr), "when": when,
                     "trades": s.get("trades"), "total_bp": s.get("total"),
                     "avg_bp": s.get("avg"), "sharpe_ann": s.get("sharpe"),
                     "t_stat": s.get("t_stat"), "max_dd": s.get("max_dd"),
                     "dropped_no_state": r.funnel["filter_drops"].get("no_macro_state", 0),
                     "dropped_stand_aside": r.funnel["filter_drops"].get(
                         "macro_state_says_stand_aside", 0)})
    return pd.DataFrame(rows)


# ==========================================================================
# the pre-registered cells
# ==========================================================================
PRIMARIES = {
    "A": {"state": "data", "lead_w": 0, "threshold": 0.5, "when": "agree",
          "window": "ALL", "instrument": "OUT_3",
          "reading": "fade the speech that says what the data already said"},
    "B": {"state": "detach", "lead_w": 0, "threshold": 1.0, "when": "agree",
          "window": "LIVE", "instrument": "OUT_3",
          "reading": "when Fedspeak has run hawkish vs the data, one more hawk is priced"},
}


def primary_row(res: Dict[str, Any], spec: Dict[str, Any]) -> pd.Series:
    inst = res["instruments"].get(spec["instrument"], {})
    if "league" not in inst:
        return pd.Series({"cell": spec, "error": inst.get("error", "not run")})
    lg = inst["league"]
    m = ((lg["lead_w"] == spec["lead_w"]) & (lg["threshold"] == spec["threshold"])
         & (lg["when"] == spec["when"]))
    if not m.any():
        return pd.Series({"cell": spec, "error": "cell not in league"})
    r = lg.loc[m].iloc[0]
    return pd.Series({
        "arm": res["label"], "reading": spec["reading"],
        "window": res["window"], "instrument": spec["instrument"],
        "trades": r["trades"], "selected": r["n_selected"],
        "share_selected": r["share_selected"],
        "baseline_total_bp": r["baseline_total_bp"],
        "conditioned_total_bp": r["total_bp"],
        "delta_total_bp": r["delta_total_bp"],
        "baseline_sharpe": r["baseline_sharpe_ann"],
        "conditioned_sharpe": r["sharpe_ann"],
        "delta_sharpe": r["delta_sharpe"],
        "t_stat": r["t_stat"],
        "p_rotation_of_the_SEARCH": inst["p_rotation"],
    })


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--draws", type=int, default=4000)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)
    draws = 50 if args.quick else args.draws

    G.load_bar_cache(CACHE / "bars.pkl")
    with open(CACHE / "events_manual_raw.pkl", "rb") as f:
        raw = pickle.load(f)["FED"]["events"]
    mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
    _p(f"raw events {len(raw)}   bar cache {len(G._BAR_CACHE):,}\n")

    arms = [
        ("A-data-ALL", "data", "ALL"),
        ("A-data-LIVE", "data", "LIVE"),
        ("B-detach-LIVE", "detach", "LIVE"),
        ("B-detach-ALL", "detach", "ALL"),
    ]
    results = {}
    t0 = time.time()
    for label, kind, win in arms:
        _p("=" * 78)
        _p(f"{label}: state={kind}  window={win}  -- {WINDOWS[win]['note']}")
        _p("=" * 78)
        try:
            results[label] = run_arm(label=label, state_kind=kind, window=win,
                                     raw=raw, mdp=mdp, draws=draws,
                                     with_gate=not args.quick)
        except Exception as exc:  # noqa: BLE001
            _p(f"  FAILED: {type(exc).__name__}: {exc}")
            results[label] = {"label": label, "error": f"{type(exc).__name__}: {exc}"}
        _p("")

    with open(args.out, "wb") as f:
        pickle.dump(results, f)
    _p(f"wrote {args.out}  ({time.time() - t0:.1f}s)")

    _p("\n" + "=" * 78)
    _p("PRE-REGISTERED PRIMARY CELLS")
    _p("=" * 78)
    rows = []
    for key, spec in PRIMARIES.items():
        for label, res in results.items():
            if res.get("state") == spec["state"] and res.get("window") == spec["window"]:
                rows.append(primary_row(res, spec).rename(f"{key}: {label}"))
    if rows:
        _p(pd.DataFrame(rows).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

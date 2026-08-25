r"""The grid, the nulls and the deflation for :mod:`fed_expected_sentiment`.

The scoring primitives are imported from ``fed_detachment_grid`` rather than
forked. That module's ``run_cell`` / ``best_of_both`` / ``book_sharpe`` /
``episode_stats`` / ``rotation_null`` / ``family_test`` / ``deflate`` were built
and then adversarially reviewed for the detachment study, and six defects were
found and fixed in them -- four of which flattered the null. Re-implementing
them here would re-introduce those six by hand. What IS written here is only the
part that genuinely differs: this study's signal bank, whose signals depend on
the holding period as well as on the lead, and a league table with this study's
own column meanings.

The one place the reuse is not free is the cell key. ``fed_detachment_grid``
keys a cell as ``(construction, k, threshold, horizon, structure)`` and looks
the signal up by ``(construction, k)``. Here the signal depends on ``horizon``
too -- ``ExpectConfig.lags()`` turns ``(lead, horizon)`` into the two lags -- so
the bank is keyed by ``(reading, lead, horizon)`` and this module builds
``key_row`` itself. ``GR.grid_statistic`` and ``GR.rotation_null`` only ever
index ``key_row[j]`` and unpack ``thr, h, struct``, so they work on this study's
keys unchanged; ``GR.run_grid``, which builds ``key_row`` from a two-part key,
does not, and is replaced by :func:`run_grid` below.

A ``DetachConfig`` still appears, as :func:`cost_carrier`. It is used ONLY to
carry ``cost_bp_one_way``, ``entry_lag_sessions`` and ``rotation_draws`` into
the borrowed functions. Its ``sign`` field is never read here -- this study's
direction lives in ``ExpectConfig.direction`` and, inside the grid, is searched
by ``best_of_both``. Two studies sharing a knob name with opposite meanings is
this desk's most repeated defect class, so the carrier is built in one function
and never passed around as if it were the study's config.

What is searched, and what that costs
-------------------------------------
The grid searches ``reading x lead x threshold x horizon x structure``, and
every cell is scored at BOTH directions inside ``best_of_both`` -- so the trial
count fed to the deflation is twice the cell count. The lead axis is four values
each of which somebody has defended (see :mod:`fed_expected_sentiment`), not a
sweep; that is an argument about interpretation, not about arithmetic, and the
deflation charges for all four regardless.

Three samples are run and they are NEVER compared to each other in one league:

``SR3``    2018-05 onwards, the futures structures. This is the tradeable book.
``OIS21``  2005 onwards, a 2y SOFR OIS priced off the CurveStore discount
           factors. It is the only instrument that exists over the long sample,
           and it is a MID -- a par rate implied by a vendor's fitted curve, not
           an executable price. It is also the clean re-run of the "does it
           reach the price" sections that ``fed_sentiment_lead`` and
           ``fedlock_sentiment_lead`` computed on the poisoned
           ``RATES.OIS.USD_SOFR.PAR.2Y`` tag and recorded as "not re-run".
``JPM``    the ~121 weeks on which the point-in-time Fed sentiment index exists,
           which is the only sample where the ``fit`` reading can run at all.

Comparing a Sharpe from one to a Sharpe from another compares instruments AND
samples at once. ``project_global_cb_hawk_dove`` measured that the leg mix alone
spanned a wider Sharpe range than the whole structure ranking it was trying to
read.
"""
from __future__ import annotations

import dataclasses
import itertools
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

import fed_detachment_data as D  # noqa: E402
import fed_detachment_grid as GR  # noqa: E402
import fed_detachment_prices as PX  # noqa: E402
import fed_expected_sentiment as E  # noqa: E402
import fed_sentiment_lead_data as L  # noqa: E402

#: ``(reading, lead, threshold, horizon, structure)`` -- the same 5-tuple shape
#: the borrowed ``grid_statistic`` unpacks.
CellKey = Tuple[str, int, float, int, str]

#: The futures structures. ``ois2y`` is excluded here and run as its own sample.
SR3_STRUCTURES: Tuple[str, ...] = ("out1", "out2", "out3", "out4",
                                   "spr1x3", "spr2x4", "pack1")


def cost_carrier(cfg: E.ExpectConfig) -> D.DetachConfig:
    """A ``DetachConfig`` carrying only cost, fill lag and draw count.

    Built here, in one place, so no caller is ever tempted to read
    ``.sign`` off it -- that field means FADE=+1 in the detachment study and
    would mean the opposite here.
    """
    return D.DetachConfig(cost_bp_one_way=cfg.cost_bp_one_way,
                          entry_lag_sessions=cfg.entry_lag_sessions,
                          rotation_draws=cfg.rotation_draws,
                          seed=cfg.seed)


# ==========================================================================
# banks
# ==========================================================================
def build_signal_bank(zc: pd.Series, cfg: E.ExpectConfig, *,
                      readings: Sequence[str], leads: Sequence[int],
                      horizons: Sequence[int],
                      zs: Optional[pd.Series] = None
                      ) -> Dict[Tuple[str, int, int], pd.Series]:
    """``(reading, lead, horizon) -> weekly signal``.

    The horizon is part of the key because it is part of the signal: the lag
    window is derived from ``(lead, horizon)`` together. Two cells that differ
    only in horizon therefore read DIFFERENT signals, which is the correct
    behaviour and the reason ``GR.run_grid`` cannot be used as-is.
    """
    out: Dict[Tuple[str, int, int], pd.Series] = {}
    for r in readings:
        for lw in leads:
            for h in horizons:
                sub = dataclasses.replace(cfg, reading=r, lead_w=int(lw),
                                          horizon_w=int(h))
                out[(r, int(lw), int(h))] = E.build_signal(zc, sub, zs)
    return out


def common_support(bank: Dict[Tuple[str, int, int], pd.Series]) -> pd.DatetimeIndex:
    """Weeks on which EVERY signal in the bank is defined.

    One support for the whole grid, so a difference between two cells is a
    difference in the rule and not a difference in the sample. It also makes the
    rotation well defined: rotating a series with a ragged NaN prefix gives each
    surrogate a different effective length.
    """
    idx: Optional[pd.Index] = None
    for s in bank.values():
        f = s.dropna().index
        idx = f if idx is None else idx.intersection(f)
    return pd.DatetimeIndex(sorted(idx)) if idx is not None else pd.DatetimeIndex([])


def cell_keys(*, readings: Sequence[str], leads: Sequence[int],
              thresholds: Sequence[float], horizons: Sequence[int],
              structures: Sequence[str]) -> List[CellKey]:
    return [tuple(x) for x in itertools.product(readings, leads, thresholds,
                                                horizons, structures)]


def key_rows(keys: Sequence[CellKey],
             bank: Dict[Tuple[str, int, int], pd.Series]) -> Tuple[List[int], List]:
    """``(row index per cell, the bank keys in row order)``."""
    sig_keys = sorted(bank)
    row_of = {sk: i for i, sk in enumerate(sig_keys)}
    rows = [row_of[(r, int(lw), int(h))] for (r, lw, _t, h, _s) in keys]
    return rows, sig_keys


def dmatrix(bank: Dict[Tuple[str, int, int], pd.Series], sig_keys: Sequence,
            weeks: pd.DatetimeIndex) -> np.ndarray:
    return np.vstack([bank[sk].reindex(weeks).to_numpy(float) for sk in sig_keys])


# ==========================================================================
# the grid
# ==========================================================================
def run_grid(bank: Dict[Tuple[str, int, int], pd.Series],
             return_bank: Dict[Tuple[str, int], np.ndarray],
             weeks: pd.DatetimeIndex, cfg: E.ExpectConfig, *,
             keys: Sequence[CellKey], min_trades: int = 8
             ) -> Tuple[pd.DataFrame, np.ndarray, np.ndarray, List[CellKey],
                        List[int], np.ndarray]:
    """``(league, dmat, streams, keys, key_row, streams_both)``.

    The body is ``GR.run_grid``'s, with two changes: ``key_row`` comes from the
    three-part bank key, and the league's ``sign`` column is written in THIS
    study's vocabulary -- ``follow`` means trade with the data, which is
    ``ExpectConfig.direction = +1``.

    Mapping the borrowed sign: ``best_of_both`` returns ``+1`` for the reading
    it calls "fade", which is ``side = +sign(signal)`` = LONG the future when
    the signal is positive. In this study a positive signal means hot data, and
    going LONG the future on hot data is FADING the data. So ``+1`` is fade
    here too, and ``direction = +1`` (follow) corresponds to the borrowed
    ``-1``. That correspondence is asserted in
    ``tests/test_fed_expected_sentiment.py``, not left to this paragraph.
    """
    keys = list(keys)
    key_row, sig_keys = key_rows(keys, bank)
    dmat = dmatrix(bank, sig_keys, weeks)
    carrier = cost_carrier(cfg)

    rows: List[dict] = []
    streams = np.zeros((len(keys), len(weeks)))
    streams_both = np.zeros((2 * len(keys), len(weeks)))
    for j, (reading, lw, thr, h, struct) in enumerate(keys):
        r = return_bank.get((struct, int(h)))
        if r is None:
            rows.append({"construction": reading, "lead_k": int(lw),
                         "threshold": float(thr), "horizon_w": int(h),
                         "structure": struct, "sign": "n/a", "trades": 0,
                         "sharpe": np.nan})
            continue
        cost = 2.0 * cfg.cost_bp_one_way * E.STRUCTURES[struct][2] / E.STRUCTURES[struct][3]
        idx0, p0 = GR.run_cell(dmat[key_row[j]], r, threshold=float(thr),
                               horizon=int(h), sign=1, cost_bp=cost)
        if len(idx0) >= min_trades:
            # A cell too thin to be selectable is not a trial. Counting it
            # inflates the trial count and with it the SR0 bar a winner must
            # clear -- which, on a NULL result, makes the null look better
            # established than it is.
            streams_both[j, idx0] = p0
            streams_both[len(keys) + j, idx0] = -(p0 + cost) - cost
        sr, sgn, idx, p = GR.best_of_both(dmat[key_row[j]], r, threshold=float(thr),
                                          horizon=int(h), cost_bp=cost,
                                          n_weeks=len(weeks), min_trades=min_trades)
        streams[j, idx] = p
        sides = (float(sgn) * np.sign(dmat[key_row[j]][idx])) if len(idx) else np.array([])
        ep = GR.episode_stats(idx, sides, p)
        sd_t = float(p.std(ddof=1)) if len(p) > 1 else np.nan
        near, far = dataclasses.replace(cfg, reading=reading, lead_w=int(lw),
                                        horizon_w=int(h)).lags()
        rows.append({
            "construction": reading, "lead_k": int(lw), "threshold": float(thr),
            "horizon_w": int(h), "structure": struct,
            "lag_near_w": int(near), "lag_far_w": int(far),
            # `fade` = long the future on hot data; `follow` = pay on hot data.
            "sign": "fade" if sgn > 0 else "follow",
            "direction": -1 if sgn > 0 else 1,
            "trades": int(len(p)),
            "avg_bp": float(p.mean()) if len(p) else np.nan,
            "gross_avg_bp": float(p.mean() + cost) if len(p) else np.nan,
            "cost_bp": cost,
            "hit": float((p > 0).mean()) if len(p) else np.nan,
            "sharpe": sr,
            "sharpe_ann": sr * np.sqrt(52.0) if np.isfinite(sr) else np.nan,
            "sharpe_per_trade": GR._sharpe(p, min_trades),
            "t_stat": (float(p.mean() / (sd_t / np.sqrt(len(p))))
                       if len(p) > 1 and sd_t and sd_t > 0 else np.nan),
            "total_bp": float(p.sum()) if len(p) else np.nan,
            **ep,
        })
    del carrier
    return pd.DataFrame(rows), dmat, streams, keys, key_row, streams_both


# ==========================================================================
# one sample, end to end
# ==========================================================================
def run_sample(*, label: str, structures: Sequence[str],
               readings: Sequence[str] = ("level", "chg"),
               leads: Sequence[int] = E.LEADS_W,
               thresholds: Sequence[float] = E.THRESHOLDS,
               horizons: Sequence[int] = E.HORIZONS_W,
               cfg: Optional[E.ExpectConfig] = None,
               start: Optional[str] = None, end: Optional[str] = None,
               rotation_draws: Optional[int] = None,
               min_trades: int = 8,
               show_progress: bool = False,
               with_family: bool = True,
               with_deflation: bool = True) -> Dict[str, object]:
    """Load, gate, build both books, search the grid, then test the search.

    Order matters and is deliberate: the gates run BEFORE anything is scored,
    the pre-registered primary cell is priced and reported BEFORE the grid, and
    the grid's winner is only ever quoted alongside the rotation p-value that
    prices the search that found it.

    **One residual look-ahead lives in the borrowed grid and is not removable
    here.** ``GR.run_cell`` skips a week whose FORWARD return is not finite --
    ``ret = r[i]; if not np.isfinite(ret): i += 1; continue`` -- so whether a
    trade is taken depends on whether its exit settle will exist, which is not
    knowable at entry. The detachment study frames this as a schedule choice
    (skip by one week rather than consume a holding period, so a data gap does
    not silently move the trade calendar) and it is inherited unchanged rather
    than forked. It affects only weeks the panel cannot price -- 1 of 433 on the
    SR3 sample, 2 of 1122 on the OIS one, per the coverage gate -- and the
    module's own :func:`E.schedule_trades`, which prices the pre-registered
    cell, does NOT condition on the forward return.

    It is measured rather than waved at. ``_probe_expect_exit_holes.py`` splits
    every hole in the return bank into the side knowable at entry and the side
    that is not: on the SR3 sample there are **28 unknowable holes each on out1,
    spr1x3 and pack1** and **none on out2, out3, out4 or spr2x4**, because only
    the rank-1 contract has gaps in the settle panel. The full grid's winner
    lands in the affected set, so :func:`run_sample` also scores the grid
    restricted to the clean structures and reports both -- see
    ``out["clean_structures"]``.
    """
    cfg = cfg or E.PRIMARY
    out: Dict[str, object] = {"label": label, "config": cfg}

    # ---- inputs -------------------------------------------------------
    zc, cprov = E.load_composite()
    out["composite_provenance"] = cprov
    zs = None
    if "fit" in readings:
        zs, sprov = E.load_sentiment(cfg)
        out["sentiment_provenance"] = sprov

    rate = None
    if any(s in E.NON_FUTURES for s in structures):
        rate = PX.curve_store_par_rate(2)
        out["rate_gate"] = PX.gate_rate_sanity(rate, name="USD_SOFR_PAR_2Y")

    # ---- price panel --------------------------------------------------
    span_start = pd.Timestamp(start) if start else pd.Timestamp("2018-05-07")
    span_end = pd.Timestamp(end) if end else pd.Timestamp(zc.dropna().index.max())
    PX.seed_local_cache()
    max_rank = max(max(E.STRUCTURES[s][0]) for s in structures if s not in E.NON_FUTURES) \
        if any(s not in E.NON_FUTURES for s in structures) else 1
    syms = PX.sr3_universe(span_start.date(), span_end.date(), max_rank=max_rank)
    panel = PX.settle_panel(syms)
    sessions = np.asarray(pd.DatetimeIndex(panel.index).values, dtype="datetime64[ns]")
    # A non-futures structure trades on the RATE's sessions, not SR3's. Using
    # the SR3 panel for both silently truncated the 21-year OIS sample to the
    # 8 years SR3 has existed: measured, the OIS primary ran 109 trades from
    # 2018-05 while its own grid ran 1,122 weeks from 2005.
    rate_sessions = (np.asarray(pd.DatetimeIndex(rate.dropna().index).values,
                                dtype="datetime64[ns]") if rate is not None else None)

    # ---- banks --------------------------------------------------------
    bank = build_signal_bank(zc, cfg, readings=readings, leads=leads,
                             horizons=horizons, zs=zs)
    support = common_support(bank)
    support = support[(support >= span_start) & (support <= span_end)]
    out["support"] = support
    if len(support) < 40:
        raise RuntimeError(
            f"{label}: only {len(support)} weeks of common support "
            f"({support.min() if len(support) else '-'} .. "
            f"{support.max() if len(support) else '-'}) -- too short to score")

    return_bank, rb_diag = GR.build_return_bank(
        panel, support, cost_carrier(cfg), horizons=horizons,
        structures=structures, entry_lag_sessions=cfg.entry_lag_sessions,
        rate=rate)
    out["return_bank_diag"] = rb_diag
    out["coverage_gate"] = _gate_return_bank_coverage(return_bank, structures, support)

    # ---- gates --------------------------------------------------------
    probes = list(support[:: max(1, len(support) // 12)][:12])
    gates = []
    for r in readings:
        sub = dataclasses.replace(cfg, reading=r)
        gates.append(E.gate_trailing_signal(zc, sub, probe_dates=probes, zs=zs)
                     .assign(reading=r))
    out["gate_trailing"] = pd.concat(gates, ignore_index=True) if gates else pd.DataFrame()
    out["gate_fill"] = E.gate_fill_is_next_session(
        rate_sessions if (rate_sessions is not None and
                          all(st in E.NON_FUTURES for st in structures)) else sessions,
        cfg, probe_weeks=probes)

    # ---- the roll placebo, run BEFORE the books ------------------------
    if any(s not in E.NON_FUTURES for s in structures):
        out["roll_placebo"] = E.roll_placebo(panel, support, sessions, rank=3)

    # ---- the pre-registered primary cell -------------------------------
    prim = cfg if cfg.structure in structures else dataclasses.replace(
        cfg, structure=structures[0])
    prim_sessions = (rate_sessions if prim.structure in E.NON_FUTURES
                     and rate_sessions is not None else sessions)
    s_prim = E.build_signal(zc, prim, zs).reindex(support).dropna()
    trades = E.schedule_trades(s_prim, prim, prim_sessions)
    bookA, reasonsA = E.price_trades(trades, panel, prim, rate=rate)
    bookB, reasonsB = E.weekly_book(s_prim, panel, prim, prim_sessions, rate=rate)
    out["primary"] = {
        "config": prim,
        "signal": s_prim,
        "discrete_book": bookA,
        "discrete_reasons": reasonsA,
        "discrete_score": E.score_trades(bookA, weeks_per_trade=float(prim.horizon_w)),
        "weekly_book": bookB,
        "weekly_reasons": reasonsB,
        "weekly_score": E.score_weekly(bookB),
        "roll_gate_discrete": E.gate_no_roll_jump(bookA, name="discrete", panel=panel),
        "roll_gate_weekly": E.gate_no_roll_jump(bookB, name="weekly", panel=panel),
    }
    if len(bookA):
        out["primary"]["sign_flip"] = GR.sign_flip_pvalue(
            bookA["pnl_bp"].to_numpy(float), rng=cfg.rng(7))
        out["primary"]["episodes"] = E.episodes(bookA)

        # The pre-registered cell needs the SAME null the grid gets, not just the
        # sign-flip. A sign-flip treats every trade as independent, and this
        # signal holds a sign for months -- the primary book lives in a few dozen
        # episodes, not a hundred. Rotating the signal keeps that persistence and
        # destroys only the alignment. No search is involved here, so the
        # statistic is the cell's own per-trade Sharpe rather than a maximum.
        def _score_primary(rot):
            tr = E.schedule_trades(rot, prim, prim_sessions)
            bk, _ = E.price_trades(tr, panel, prim, rate=rate)
            if bk.empty or len(bk) < 8:
                return float("nan")
            pl = bk["pnl_bp"].to_numpy(float)
            sd = pl.std(ddof=1)
            return float(pl.mean() / sd) if sd > 0 else float("nan")

        near, far = prim.lags()
        pn = E.rotation_null(s_prim, _score_primary, max_lag=int(far),
                             max_h=int(prim.horizon_w),
                             draws=int(rotation_draws or cfg.rotation_draws),
                             rng=cfg.rng(21))
        obs_prim = _score_primary(s_prim)
        out["primary"]["rotation_null"] = {k: v for k, v in pn.items()
                                           if k != "stats"}
        out["primary"]["observed_sharpe_per_trade"] = obs_prim
        out["primary"]["p_rotation"] = E.rotation_pvalue(obs_prim, pn)
        _st = pn.get("stats")
        out["primary"]["null_median"] = (float(np.median(_st))
                                         if _st is not None and len(_st) else float("nan"))
    if len(bookB):
        out["primary"]["weekly_sign_flip"] = GR.sign_flip_pvalue(
            bookB.loc[bookB["side"] != 0, "pnl_bp"].to_numpy(float), rng=cfg.rng(8))

    # ---- the grid ------------------------------------------------------
    keys = cell_keys(readings=readings, leads=leads, thresholds=thresholds,
                     horizons=horizons, structures=structures)
    league, dmat, streams, keys, key_row, streams_both = run_grid(
        bank, return_bank, support, cfg, keys=keys, min_trades=min_trades)
    out["league"] = league
    out["n_cells"] = len(keys)
    scored = int(league["sharpe"].notna().sum())
    out["n_scored"] = scored
    # ``2 * n_cells`` is the size of the trial SET the grid enumerates. It is NOT
    # what the deflation charges for: a cell too thin to be selectable was never
    # a trial, and ``run_grid`` leaves those rows at zero in ``streams_both`` so
    # ``deflate`` drops them. Both numbers are reported, because quoting only the
    # first overstates the search on a null result -- it raises the SR0 bar the
    # winner has to clear and so makes the null look better established.
    out["n_trials_enumerated"] = 2 * len(keys)
    out["n_trials_scoreable"] = 2 * scored
    out["n_trials"] = 2 * len(keys)

    obs, best_i, per_cell = GR.grid_statistic(dmat, keys, key_row, return_bank,
                                              cost_carrier(cfg),
                                              min_trades=min_trades)
    out["best_sharpe"] = obs
    out["best_cell"] = league.iloc[best_i].to_dict() if best_i >= 0 else None

    # ---- the null that prices the search --------------------------------
    max_lag = max(dataclasses.replace(cfg, reading=r, lead_w=int(lw), horizon_w=int(h))
                  .lags()[1] for r in readings for lw in leads for h in horizons)
    null = GR.rotation_null(dmat, keys, key_row, return_bank, cost_carrier(cfg),
                            max_k=int(max_lag), max_h=int(max(horizons)),
                            min_trades=min_trades,
                            draws=int(rotation_draws or cfg.rotation_draws),
                            rng=cfg.rng(11), show_progress=show_progress)
    out["rotation_null"] = {k: v for k, v in null.items() if k != "cell_sharpes"}
    out["p_rotation"] = GR.rotation_pvalue(obs, null)

    if with_family and null.get("cell_sharpes") is not None:
        try:
            out["family"] = GR.family_test(per_cell, null, league)
        except Exception as exc:  # noqa: BLE001
            out["family"] = {"error": f"{type(exc).__name__}: {exc}"}
    if with_deflation:
        try:
            out["deflation"] = GR.deflate(streams_both, league, seed=cfg.seed)
        except Exception as exc:  # noqa: BLE001
            out["deflation"] = {"error": f"{type(exc).__name__}: {exc}"}

    # ---- robustness: the grid with the forward-look exposure removed ----
    # The borrowed run_cell decides whether to open by reading the forward
    # return, which is not knowable at entry wherever the exit settle is
    # missing. That lands only on structures containing rank 1. Re-score the
    # grid over the structures with NO such hole and report it beside the
    # headline -- because on this sample the headline's winner is in the
    # affected set, and a reader has to be able to see whether that mattered.
    clean = _structures_without_exit_holes(return_bank, structures, support,
                                           horizons, panel, sessions, cfg,
                                           rate=rate)
    out["clean_structures"] = {"clean": clean,
                               "affected": [s for s in structures if s not in clean]}
    if clean and len(clean) < len(structures):
        ck = cell_keys(readings=readings, leads=leads, thresholds=thresholds,
                       horizons=horizons, structures=clean)
        ckr, _ = key_rows(ck, bank)
        c_obs, c_best, _c = GR.grid_statistic(dmat, ck, ckr, return_bank,
                                              cost_carrier(cfg),
                                              min_trades=min_trades)
        c_null = GR.rotation_null(dmat, ck, ckr, return_bank, cost_carrier(cfg),
                                  max_k=int(max_lag), max_h=int(max(horizons)),
                                  min_trades=min_trades,
                                  draws=int(rotation_draws or cfg.rotation_draws),
                                  rng=cfg.rng(31))
        out["clean_structures"].update({
            "cells": len(ck), "best_sharpe": c_obs,
            "best_cell": (f"{ck[c_best][0]}/L{ck[c_best][1]}/thr{ck[c_best][2]}"
                          f"/h{ck[c_best][3]}/{ck[c_best][4]}") if c_best >= 0 else None,
            "null_median": c_null.get("q50"), "null_q95": c_null.get("q95"),
            "p_rotation": GR.rotation_pvalue(c_obs, c_null),
            "rotations": c_null.get("draws_used"),
            "still_below_null_median": bool(np.isfinite(c_obs)
                                            and c_obs < c_null.get("q50", np.inf)),
        })

    # ---- the honest comparison: the winner against its own null ---------
    out["null_summary"] = {
        "median": null.get("q50"), "q95": null.get("q95"),
        "p_floor": null.get("p_floor"), "draws": null.get("draws_used"),
        "min_offset": null.get("min_offset"),
        "exhaustive": null.get("exhaustive"),
        "observed_percentile": (
            float((np.asarray(null["max_abs_sharpe"], float) < obs).mean())
            if np.size(null.get("max_abs_sharpe", [])) and np.isfinite(obs) else np.nan),
    }
    return out


def _structures_without_exit_holes(return_bank: Dict, structures: Sequence[str],
                                   support: pd.DatetimeIndex,
                                   horizons: Sequence[int], panel: pd.DataFrame,
                                   sessions: np.ndarray, cfg: E.ExpectConfig,
                                   *, rate: Optional[pd.Series] = None
                                   ) -> List[str]:
    """Structures whose return bank has no hole that is UNKNOWABLE at entry.

    A hole is knowable at entry when the ENTRY settle is the missing one -- a
    trader would simply not have a price to deal on. It is not knowable when the
    entry settle exists and the EXIT settle does not, because that is a fact
    about a session ``h`` weeks in the future. Only the second kind makes the
    borrowed ``run_cell``'s skip forward-looking.

    The expiry guard is deliberately not counted: it is a calendar fact, known
    the moment the contract is chosen.
    """
    def _fill(on, lag):
        cur = pd.Timestamp(on)
        for _ in range(int(lag)):
            i = int(np.searchsorted(sessions, np.datetime64(cur), side="right"))
            if i >= len(sessions):
                return None
            cur = pd.Timestamp(sessions[i])
        return cur

    clean = []
    for name in structures:
        if name in E.NON_FUTURES:
            clean.append(name)     # a rate series has no contract to be missing
            continue
        ranks, weights, _n, _s = E.STRUCTURES[name]
        bad = 0
        for h in horizons:
            arr = return_bank.get((name, int(h)))
            if arr is None:
                continue
            for i in range(len(support) - int(h)):
                if np.isfinite(arr[i]):
                    continue
                e = _fill(support[i], cfg.entry_lag_sessions)
                x = _fill(support[i + int(h)], cfg.entry_lag_sessions)
                if e is None or x is None:
                    continue
                sy = [PX.rank_symbol(e.date(), r) for r in ranks]
                exp = min(pd.Timestamp(PX.contract_window(t).end) for t in sy)
                if exp <= x:
                    continue
                if (D.structure_price(panel, sy, weights, e) is not None
                        and D.structure_price(panel, sy, weights, x) is None):
                    bad += 1
        if bad == 0:
            clean.append(name)
    return clean


def _gate_return_bank_coverage(return_bank: Dict, structures: Sequence[str],
                               support: pd.DatetimeIndex,
                               *, min_share: float = 0.5) -> pd.DataFrame:
    """G-P3 -- every structure the grid searches must be priceable.

    ``settle_panel`` returns only the contracts whose parquet exists, so a cold
    cache makes every futures structure all-NaN, every cell NaN, and the run
    still prints a complete grid with a p-value computed from whichever
    instrument happened to be readable. Nothing in the output would say so.
    """
    rows = []
    for s in structures:
        priced = [int(np.isfinite(a).sum()) for (name, _h), a in return_bank.items()
                  if name == s]
        best = max(priced) if priced else 0
        rows.append({"structure": s, "weeks": len(support), "best_priced": best,
                     "share": best / max(len(support), 1)})
    out = pd.DataFrame(rows)
    bad = out[out["share"] < min_share]
    assert bad.empty, (
        f"G-P3 FAILED: {sorted(bad['structure'])} price fewer than {min_share:.0%} "
        f"of the {len(support)} weeks in the support. Seed the SR3 settle cache "
        f"with fed_detachment_refresh_settles.py.")
    return out


# ==========================================================================
# reporting
# ==========================================================================
def headline(res: Dict[str, object]) -> pd.Series:
    """One row that says whether the sample is alive or dead."""
    prim = res.get("primary", {})
    ds = prim.get("discrete_score", {})
    ws = prim.get("weekly_score", {})
    null = res.get("null_summary", {})
    best = res.get("best_cell") or {}
    return pd.Series({
        "sample": res.get("label"),
        "weeks": len(res.get("support", [])),
        "first": str(pd.Timestamp(res["support"][0]).date()) if len(res.get("support", [])) else None,
        "last": str(pd.Timestamp(res["support"][-1]).date()) if len(res.get("support", [])) else None,
        "PRIMARY trades": ds.get("trades"),
        "PRIMARY avg_bp": ds.get("avg_bp"),
        "PRIMARY sharpe_ann": ds.get("sharpe_ann"),
        "PRIMARY t": ds.get("t_stat"),
        "PRIMARY sign_flip_p": (prim.get("sign_flip") or {}).get("p"),
        "PRIMARY p_rot": prim.get("p_rotation"),
        "PRIMARY null_med": prim.get("null_median"),
        "WEEKLY total_bp": ws.get("total_bp"),
        "WEEKLY sharpe_ann": ws.get("sharpe_ann"),
        "WEEKLY weeks_in_mkt": ws.get("weeks_in_market"),
        "cells": res.get("n_cells"),
        "trials": res.get("n_trials_enumerated", res.get("n_trials")),
        "trials scoreable": res.get("n_trials_scoreable"),
        "best cell": (f"{best.get('construction')}/L{best.get('lead_k')}/"
                      f"thr{best.get('threshold')}/h{best.get('horizon_w')}/"
                      f"{best.get('structure')}/{best.get('sign')}") if best else None,
        "best sharpe_wk": res.get("best_sharpe"),
        "null median": null.get("median"),
        "null q95": null.get("q95"),
        "p_rotation": res.get("p_rotation"),
        "p_floor": null.get("p_floor"),
        "clean-only p_rot": (res.get("clean_structures") or {}).get("p_rotation"),
        "DSR": (res.get("deflation") or {}).get("dsr"),
        "RW rejected": (res.get("family") or {}).get("n_rejected"),
    })


def league_summary(league: pd.DataFrame, by: str) -> pd.DataFrame:
    """Median and best weekly Sharpe within each level of one axis.

    The MEDIAN is the durable number. A best-of is the maximum of however many
    cells that level happens to contain, so ranking axes by their best rewards
    the axis with the most cells.
    """
    g = league.dropna(subset=["sharpe"]).groupby(by)
    return pd.DataFrame({
        "cells": g.size(),
        "median_sharpe_wk": g["sharpe"].median(),
        "best_sharpe_wk": g["sharpe"].max(),
        "median_avg_bp": g["avg_bp"].median(),
        "follow_share": g["sign"].apply(lambda s: float((s == "follow").mean())),
    }).sort_values("median_sharpe_wk", ascending=False)

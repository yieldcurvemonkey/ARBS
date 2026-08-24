r"""The grid, the nulls that pay for it, and the harness's own calibration.

Everything here is built so that one number -- the best Sharpe over the whole
grid, with each cell scored at BOTH trade directions -- is the statistic
under test, and so that the null is scored by exactly that same statistic.
A null scored at one cell while the reported number is a maximum over 2,048 flatters the result by precisely the value of the search.

The conservative null is a **circular rotation of the finished detachment
series against the price**, with every rotation re-scored across the entire
grid. Each surrogate therefore keeps the real signal's trend, persistence,
variance and marginal distribution exactly; only the correspondence with the
front end is destroyed.

The rotation floor
------------------
``min_offset`` must exceed **twice** the widest alignment the grid can examine,
which here is ``max lead_k + max horizon = 11 + 8 = 19``, giving 39. That is not
belt-and-braces. ``reference_rotation_null_self_match`` records what happens at
the obvious bound: a rotation of ``L+1`` still contains the true alignment
inside its own scan window, the surrogate reproduces the observed statistic
exactly, and the p-value silently stops measuring effect size and starts
measuring where the argmax sits -- a weaker r 0.093 scored p 0.0018 while a
stronger r 0.122 scored 0.0027.

The cost is resolution. With ``n`` weeks the reference set holds ``n - 78``
distinct rotations, so on the 121-week JPM sample the exact p-value cannot go
below 0.0227 however strong the signal is. That floor is reported, never
rounded past.
"""
from __future__ import annotations

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
import fed_detachment_prices as PX  # noqa: E402

CellKey = Tuple[str, int, float, int, str]  # construction, k, threshold, horizon, structure


# --------------------------------------------------------------------------
# banks
# --------------------------------------------------------------------------
def build_signal_bank(
    zc: pd.Series,
    zs: pd.Series,
    cfg: D.DetachConfig,
    *,
    constructions: Sequence[str] = D.CONSTRUCTIONS,
    ks: Sequence[int] = D.LEAD_KS,
) -> Dict[Tuple[str, int], pd.Series]:
    out: Dict[Tuple[str, int], pd.Series] = {}
    import dataclasses

    for c in constructions:
        for k in ks:
            sub = dataclasses.replace(cfg, construction=c, lead_k=int(k))
            out[(c, int(k))] = D.detachment(zc, zs, sub)
    return out


def common_support(bank: Dict[Tuple[str, int], pd.Series]) -> pd.DatetimeIndex:
    """Weeks on which EVERY construction is defined.

    One support for the whole grid, so a difference between two cells is a
    difference in the rule and not a difference in the sample -- the same
    discipline ``lag_matrix`` applies on the estimator side. It also makes the
    rotation well-defined: rotating a series with a ragged NaN prefix would give
    each surrogate a different effective length.
    """
    idx: Optional[pd.Index] = None
    for s in bank.values():
        f = s.dropna().index
        idx = f if idx is None else idx.intersection(f)
    return pd.DatetimeIndex(sorted(idx)) if idx is not None else pd.DatetimeIndex([])


def build_return_bank(
    panel: pd.DataFrame,
    weeks: pd.DatetimeIndex,
    cfg: D.DetachConfig,
    *,
    horizons: Sequence[int] = D.HORIZONS_W,
    structures: Sequence[str] = tuple(D.STRUCTURES),
    entry_lag_sessions: Optional[int] = None,
    rate: Optional[pd.Series] = None,
) -> Tuple[Dict[Tuple[str, int], np.ndarray], pd.DataFrame]:
    """``(structure, horizon) -> LONG P&L in bp of the structure's quote, per week``.

    Indexed by the signal week, not the entry session. The contract set is fixed
    at the entry session and reused at the exit session, so no element of this
    bank ever differences two contracts.

    ``rate`` supplies the non-futures structures: a daily PERCENT par rate, of
    which ``ois2y`` is the only current member. "Long" keeps the futures sign
    convention -- it profits when the rate FALLS -- so the two are directly
    comparable and a cell's sign means the same thing whichever it trades.
    """
    lag = cfg.entry_lag_sessions if entry_lag_sessions is None else int(entry_lag_sessions)
    sessions = np.asarray(pd.DatetimeIndex(panel.index).values, dtype="datetime64[ns]")
    rate_sessions = (np.asarray(pd.DatetimeIndex(rate.dropna().index).values,
                                dtype="datetime64[ns]") if rate is not None else None)

    def _fill_on(sess: np.ndarray, on: pd.Timestamp) -> Optional[pd.Timestamp]:
        if lag == 0:
            return D._snap_back(sess, on)
        t = on
        for _ in range(lag):
            t = D._next_session(sess, t)
            if t is None:
                return None
        return t

    def _fill(on: pd.Timestamp) -> Optional[pd.Timestamp]:
        return _fill_on(sessions, on)

    entry_sessions = [_fill(w) for w in weeks]
    rate_vals = rate.dropna() if rate is not None else None
    bank: Dict[Tuple[str, int], np.ndarray] = {}
    diag: List[dict] = []
    for name in structures:
        if name in D.NON_FUTURES:
            for h in horizons:
                arr = np.full(len(weeks), np.nan)
                reasons: Dict[str, int] = {}
                if rate_vals is None:
                    reasons["no rate series supplied"] = len(weeks)
                else:
                    for i, w in enumerate(weeks):
                        if i + h >= len(weeks):
                            reasons["past the end of the sample"] = reasons.get(
                                "past the end of the sample", 0) + 1
                            continue
                        e = _fill_on(rate_sessions, w)
                        x = _fill_on(rate_sessions, weeks[i + h])
                        if e is None or x is None or x <= e:
                            reasons["no session"] = reasons.get("no session", 0) + 1
                            continue
                        # PERCENT -> bp, and long profits when the rate falls
                        arr[i] = -(float(rate_vals.loc[x]) - float(rate_vals.loc[e])) * 100.0
                bank[(name, int(h))] = arr
                diag.append({"structure": name, "horizon_w": int(h),
                             "priced": int(np.isfinite(arr).sum()), "weeks": int(len(weeks)),
                             **{f"drop: {k}": v for k, v in reasons.items()}})
            continue
        ranks, weights, _n, _s = D.STRUCTURES[name]
        for h in horizons:
            arr = np.full(len(weeks), np.nan)
            reasons: Dict[str, int] = {}
            for i, w in enumerate(weeks):
                if i + h >= len(weeks):
                    reasons["past the end of the sample"] = reasons.get(
                        "past the end of the sample", 0) + 1
                    continue
                e = entry_sessions[i]
                x = _fill(weeks[i + h])
                if e is None or x is None or x <= e:
                    reasons["no session"] = reasons.get("no session", 0) + 1
                    continue
                syms = [PX.rank_symbol(pd.Timestamp(e).date(), r) for r in ranks]
                exp = min(pd.Timestamp(PX.contract_window(s).end) for s in syms)
                if exp <= x:
                    reasons["contract expires inside the hold"] = reasons.get(
                        "contract expires inside the hold", 0) + 1
                    continue
                pe = D.structure_price(panel, syms, weights, e)
                pxx = D.structure_price(panel, syms, weights, x)
                if pe is None or pxx is None:
                    reasons["no settle"] = reasons.get("no settle", 0) + 1
                    continue
                arr[i] = (pxx - pe) / PX.PX_PER_BP
            bank[(name, int(h))] = arr
            diag.append({"structure": name, "horizon_w": int(h),
                         "priced": int(np.isfinite(arr).sum()), "weeks": int(len(weeks)),
                         **{f"drop: {k}": v for k, v in reasons.items()}})
    return bank, pd.DataFrame(diag)


# --------------------------------------------------------------------------
# one cell
# --------------------------------------------------------------------------
def run_cell(
    d: np.ndarray,
    r: np.ndarray,
    *,
    threshold: float,
    horizon: int,
    sign: int,
    cost_bp: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """Non-overlapping trades. Returns ``(entry week indices, net bp per trade)``.

    The rule is a book: walk the weeks; when flat and the gate is met, take the
    trade, hold ``horizon`` weeks, go flat, resume looking. A week whose
    structure cannot be priced is skipped by ONE week rather than consuming a
    holding period, because the alternative silently changes the trade schedule
    on exactly the dates the data is worst.
    """
    n = len(d)
    idx: List[int] = []
    pnl: List[float] = []
    i = 0
    while i + horizon < n:
        v = d[i]
        if not np.isfinite(v) or abs(v) < threshold or v == 0.0:
            i += 1
            continue
        ret = r[i]
        if not np.isfinite(ret):
            i += 1
            continue
        side = float(sign) * (1.0 if v > 0 else -1.0)
        idx.append(i)
        pnl.append(side * float(ret) - cost_bp)
        i += horizon
    return np.asarray(idx, dtype=int), np.asarray(pnl, dtype=float)


def _sharpe(p: np.ndarray, min_trades: int = 8) -> float:
    """Per-TRADE Sharpe. Reported for interpretation, never used to rank."""
    if p.size < min_trades:
        return np.nan
    sd = float(p.std(ddof=1))
    if not np.isfinite(sd) or sd <= 0:
        return np.nan
    return float(p.mean() / sd)


def book_sharpe(idx: np.ndarray, pnl: np.ndarray, n_weeks: int,
                min_trades: int = 8) -> float:
    """WEEKLY Sharpe of the book: each trade's net P&L on its signal week, zero
    elsewhere.

    This is the statistic everything here ranks and tests on, and the choice
    matters. A per-trade Sharpe is blind to how often the book trades, so a cell
    that takes ten trades in three years and one that takes sixty are compared as
    if a year of the first were worth a year of the second. The weekly stream IS
    the book's return series -- flat between trades, because the rule is flat
    between trades -- so its Sharpe already carries the frequency, annualises by
    the ordinary sqrt(52), and is the per-period series a deflated Sharpe wants.

    Getting this wrong is not cosmetic: ranking on the per-trade number and
    deflating on the weekly one picks two different winners out of the same grid.
    """
    if len(idx) < min_trades or n_weeks < 3:
        return np.nan
    s = np.zeros(n_weeks)
    s[idx] = pnl
    sd = float(s.std(ddof=1))
    if not np.isfinite(sd) or sd <= 0:
        return np.nan
    return float(s.mean() / sd)


# --------------------------------------------------------------------------
# the grid
# --------------------------------------------------------------------------
def best_of_both(
    d: np.ndarray,
    r: np.ndarray,
    *,
    threshold: float,
    horizon: int,
    cost_bp: float,
    n_weeks: int,
    min_trades: int = 8,
) -> Tuple[float, int, np.ndarray, np.ndarray]:
    """Score a cell at BOTH readings and return the better one.

    ``(sharpe, sign, trade indices, net P&L)`` with ``sign`` +1 for fade and -1
    for follow.

    The reason this is not ``abs(sharpe)``: **the round trip is paid whichever
    way round the trade goes**, so the follow reading of a cell is
    ``-(p + cost) - cost`` and not ``-p``. Once a cost is charged the two
    readings are no longer mirror images, and taking ``|Sharpe|`` silently
    reports whichever *magnitude* is larger -- which, for a cell whose gross
    edge is small against its cost, is the reading the flip made WORSE. Measured
    on this grid before the fix: a spr2x4 cell with a pre-flip mean of -0.29bp
    was reported as the winner at a post-flip mean of -1.71bp, because -1.71 has
    the bigger magnitude. Both readings lose money; neither should have won
    anything.
    """
    idx, p = run_cell(d, r, threshold=threshold, horizon=horizon, sign=1, cost_bp=cost_bp)
    if len(idx) < min_trades:
        return np.nan, 1, idx, p
    sr_fade = book_sharpe(idx, p, n_weeks, min_trades)
    q = -(p + cost_bp) - cost_bp
    sr_follow = book_sharpe(idx, q, n_weeks, min_trades)
    if np.isfinite(sr_follow) and (not np.isfinite(sr_fade) or sr_follow > sr_fade):
        return sr_follow, -1, idx, q
    return sr_fade, 1, idx, p


def cell_keys(
    *,
    constructions: Sequence[str] = D.CONSTRUCTIONS,
    ks: Sequence[int] = D.LEAD_KS,
    thresholds: Sequence[float] = D.THRESHOLDS,
    horizons: Sequence[int] = D.HORIZONS_W,
    structures: Sequence[str] = tuple(D.STRUCTURES),
) -> List[CellKey]:
    return [tuple(x) for x in itertools.product(constructions, ks, thresholds,
                                                horizons, structures)]


def grid_statistic(
    dmat: np.ndarray,
    keys: Sequence[CellKey],
    key_row: Sequence[int],
    return_bank: Dict[Tuple[str, int], np.ndarray],
    cfg: D.DetachConfig,
    *,
    min_trades: int = 8,
) -> Tuple[float, int, np.ndarray]:
    """``(best Sharpe over the grid, winning cell index, every cell's Sharpe)``.

    ``dmat`` is ``(n_signals, n_weeks)`` and ``key_row`` maps each cell to its
    row. Each cell is scored at BOTH readings by :func:`best_of_both` and keeps
    the better one, so the direction is searched -- and every surrogate is
    scored by the identical search, which is what makes the null pay for not
    knowing the sign in advance.
    """
    n_weeks = dmat.shape[1]
    sharpes = np.full(len(keys), np.nan)
    for j, (constr, k, thr, h, struct) in enumerate(keys):
        r = return_bank.get((struct, int(h)))
        if r is None:
            continue
        cost = 2.0 * cfg.cost_bp_one_way * D.STRUCTURES[struct][2] / D.STRUCTURES[struct][3]
        sharpes[j], _sg, _i, _p = best_of_both(
            dmat[key_row[j]], r, threshold=float(thr), horizon=int(h),
            cost_bp=cost, n_weeks=n_weeks, min_trades=min_trades)
    if not np.isfinite(sharpes).any():
        return np.nan, -1, sharpes
    best = int(np.nanargmax(sharpes))
    return float(sharpes[best]), best, sharpes


def run_grid(
    bank: Dict[Tuple[str, int], pd.Series],
    return_bank: Dict[Tuple[str, int], np.ndarray],
    weeks: pd.DatetimeIndex,
    cfg: D.DetachConfig,
    *,
    keys: Optional[Sequence[CellKey]] = None,
    min_trades: int = 8,
) -> Tuple[pd.DataFrame, np.ndarray, np.ndarray, List[CellKey], List[int]]:
    """The league table, plus the machinery the nulls reuse.

    Returns ``(league, dmat, streams, keys, key_row, streams_both)``.
    ``streams`` is one weekly P&L row per cell at its better sign -- a trade's
    net P&L placed on its signal week, zero elsewhere -- and ``streams_both``
    carries BOTH readings of every cell, which is the trial set the deflation
    has to pay for. That representation gives every trial the same length, which
    is what ``effective_trials`` needs to estimate how correlated they are.
    """
    keys = list(keys or cell_keys())
    sig_keys = sorted(bank)
    row_of = {sk: i for i, sk in enumerate(sig_keys)}
    dmat = np.vstack([bank[sk].reindex(weeks).to_numpy(float) for sk in sig_keys])
    key_row = [row_of[(c, int(k))] for (c, k, _t, _h, _s) in keys]

    rows: List[dict] = []
    streams = np.zeros((len(keys), len(weeks)))
    # Both readings of every cell, as separate trials. The sign is a free
    # parameter -- nothing said in advance which way a detachment should be
    # traded -- so "fade" and "follow" are two experiments, not one experiment
    # and its mirror. They are not exact negatives either: the round trip is
    # paid whichever way round the trade goes, so flipping is
    # ``-(p + cost) - cost``, not ``-p``.
    streams_both = np.zeros((2 * len(keys), len(weeks)))
    for j, (constr, k, thr, h, struct) in enumerate(keys):
        r = return_bank[(struct, int(h))]
        cost = 2.0 * cfg.cost_bp_one_way * D.STRUCTURES[struct][2] / D.STRUCTURES[struct][3]
        idx0, p0 = run_cell(dmat[key_row[j]], r, threshold=float(thr), horizon=int(h),
                            sign=1, cost_bp=cost)
        if len(idx0) >= min_trades:
            # A cell thinner than ``min_trades`` scores NaN in the grid and can
            # never be selected, so it is not a trial and must not be counted as
            # one. Leaving it in inflates N and with it the SR0 the winner has to
            # clear -- which, when the result is a NULL, makes the null look
            # better established than it is. Measured on the JPM grid: 264 of
            # 2,048 cells are that thin.
            streams_both[j, idx0] = p0
            streams_both[len(keys) + j, idx0] = -(p0 + cost) - cost
        sr, sign, idx, p = best_of_both(dmat[key_row[j]], r, threshold=float(thr),
                                        horizon=int(h), cost_bp=cost,
                                        n_weeks=len(weeks), min_trades=min_trades)
        streams[j, idx] = p
        sides = (float(sign) * np.sign(dmat[key_row[j]][idx])) if len(idx) else np.array([])
        ep = episode_stats(idx, sides, p)
        sd_t = float(p.std(ddof=1)) if len(p) > 1 else np.nan
        rows.append({
            "construction": constr, "lead_k": int(k), "threshold": float(thr),
            "horizon_w": int(h), "structure": struct,
            "sign": "fade" if sign > 0 else "follow",
            "trades": int(len(p)),
            "avg_bp": float(p.mean()) if len(p) else np.nan,
            "gross_avg_bp": float(p.mean() + cost) if len(p) else np.nan,
            "cost_bp": cost,
            "hit": float((p > 0).mean()) if len(p) else np.nan,
            "sharpe": sr,
            "sharpe_ann": sr * np.sqrt(52.0) if np.isfinite(sr) else np.nan,
            "sharpe_per_trade": _sharpe(p, min_trades),
            "t_stat": (float(p.mean() / (sd_t / np.sqrt(len(p))))
                       if len(p) > 1 and sd_t and sd_t > 0 else np.nan),
            "total_bp": float(p.sum()) if len(p) else np.nan,
            **ep,
        })
    league = pd.DataFrame(rows)
    return league, dmat, streams, keys, key_row, streams_both


def episode_stats(idx: np.ndarray, sides: np.ndarray, pnl: np.ndarray,
                  gap_weeks: int = 8) -> Dict[str, float]:
    """How much of a cell's P&L lives in one disagreement.

    Two heavily smoothed series do not disagree thirty independent times in
    three years; they disagree a handful of times, for months at a stretch. A
    cell whose whole P&L comes from one such episode has an effective sample of
    one whatever its trade count says, and the trade count is the number every
    Sharpe in the league is computed from. So the episode count and the largest
    episode's share of total P&L travel with every row and are read BEFORE the
    Sharpe.
    """
    if len(idx) == 0:
        return {"episodes": 0, "top_episode_share": np.nan, "pnl_ex_top_episode": np.nan}
    ep, cur = [], 0
    prev_side, prev_i = None, None
    for i, s in zip(idx, sides):
        if prev_side is None or s != prev_side or (i - prev_i) > gap_weeks:
            cur += 1
        ep.append(cur)
        prev_side, prev_i = s, i
    ep = np.asarray(ep)
    totals = {e: float(pnl[ep == e].sum()) for e in np.unique(ep)}
    denom = float(np.abs(pnl).sum())
    top = max(totals, key=lambda e: abs(totals[e]))
    return {
        "episodes": int(len(totals)),
        "top_episode_share": abs(totals[top]) / denom if denom > 0 else np.nan,
        "pnl_ex_top_episode": float(pnl[ep != top].sum()),
    }


# --------------------------------------------------------------------------
# nulls
# --------------------------------------------------------------------------
def rotation_offsets(n: int, max_k: int, max_h: int) -> np.ndarray:
    """Every rotation that cannot reproduce a true alignment. See the module docstring."""
    min_offset = 2 * (int(max_k) + int(max_h)) + 1
    if n < 3 * min_offset:
        return np.asarray([], dtype=int)
    return np.arange(min_offset, n - min_offset, dtype=int)


def rotation_null(
    dmat: np.ndarray,
    keys: Sequence[CellKey],
    key_row: Sequence[int],
    return_bank: Dict[Tuple[str, int], np.ndarray],
    cfg: D.DetachConfig,
    *,
    max_k: Optional[int] = None,
    max_h: Optional[int] = None,
    min_trades: int = 8,
    draws: Optional[int] = None,
    rng: Optional[np.random.Generator] = None,
    show_progress: bool = False,
) -> Dict[str, object]:
    """Rotate the whole signal bank against the price; re-score the ENTIRE grid.

    Every construction is rotated by the SAME offset, so the surrogate keeps the
    relationships between constructions intact and destroys only the one thing
    under test.

    The reference set is enumerated in full whenever it fits ``draws``, which
    makes the p-value exact; when it does not, offsets are drawn WITHOUT
    replacement, because sampling a finite set with replacement lets a p-value be
    quoted finer than the set can resolve.
    """
    n = dmat.shape[1]
    max_k = max_k if max_k is not None else max(int(k) for (_c, k, _t, _h, _s) in keys)
    max_h = max_h if max_h is not None else max(int(h) for (_c, _k, _t, h, _s) in keys)
    offsets = rotation_offsets(n, max_k, max_h)
    draws = int(draws if draws is not None else cfg.rotation_draws)
    exhaustive = len(offsets) <= draws
    if not exhaustive:
        rng = rng or cfg.rng(11)
        offsets = np.sort(rng.choice(offsets, size=draws, replace=False))
    it = offsets
    if show_progress and len(offsets):
        try:
            from tqdm.auto import tqdm

            it = tqdm(offsets, desc="rotation null")
        except Exception:  # noqa: BLE001
            pass
    maxima, argmax, cells = [], [], []
    for d in it:
        stat, best, per_cell = grid_statistic(np.roll(dmat, int(d), axis=1), keys,
                                              key_row, return_bank, cfg,
                                              min_trades=min_trades)
        if np.isfinite(stat):
            maxima.append(stat)
            argmax.append(best)
            cells.append(per_cell)
    m = np.asarray(maxima, float)
    return {
        # every cell's Sharpe under every rotation. Cheap to keep and it is what
        # a Romano-Wolf stepdown needs: the family test asks how many cells
        # survive familywise control, which the maximum alone cannot answer.
        "cell_sharpes": np.vstack(cells) if cells else np.zeros((0, len(keys))),
        "max_abs_sharpe": m,
        "argmax_cell": np.asarray(argmax, int),
        "n_rotations": int(len(offsets)),
        "distinct_rotations": int(len(rotation_offsets(n, max_k, max_h))),
        "exhaustive": bool(exhaustive),
        "draws_used": int(m.size),
        "min_offset": int(2 * (max_k + max_h) + 1),
        "q50": float(np.quantile(m, 0.50)) if m.size else np.nan,
        "q95": float(np.quantile(m, 0.95)) if m.size else np.nan,
        "p_floor": 1.0 / (m.size + 1) if m.size else np.nan,
    }


def family_test(sharpes: np.ndarray, null: Dict[str, object], league: pd.DataFrame,
                *, alpha: float = 0.05) -> Dict[str, object]:
    """Romano-Wolf stepdown over the WHOLE grid, against the rotation null.

    The rotation p-value answers "is the BEST cell better than the best cell of
    a misaligned copy". This answers the strictly harder question: **how many
    cells, if any, survive familywise error control** -- against the same
    surrogates, so the two tests are consistent rather than being two different
    bars. Consistent to the point of identity: with the full family the
    stepdown's first suffix maximum IS the grid maximum, so the rank-1 adjusted
    p equals the rotation p-value exactly. That equality is the check that this
    is wired up correctly.

    **The family must not be chosen using the observed statistics.** An earlier
    version ran the stepdown over the top 400 cells by observed Sharpe. That
    shrinks every suffix maximum -- the null's competing set no longer contains
    the cells the observed data ranked low but a rotation ranks high -- so the
    adjusted p-values come out too small and familywise control over the real
    family is lost. Measured: on the FedLock SR3 sample the top-400 version
    "rejected" one cell while the grid maximum's own rotation p was 0.0845.

    A cell whose observed Sharpe is NaN was never a candidate and is dropped; a
    cell that is NaN under a particular rotation is unselectable in that
    surrogate, so it enters the null matrix as -inf rather than being excluded,
    which would otherwise make the surrogate's competing set depend on the data.
    """
    from RVUtils.StatisticalFinance.family import romano_wolf

    arr = np.asarray(null.get("cell_sharpes"), dtype=float)
    if arr.size == 0:
        return {"n_rejected": 0, "reason": "no null cell matrix"}
    obs = np.asarray(sharpes, float)
    idx = np.flatnonzero(np.isfinite(obs))
    if idx.size == 0:
        return {"n_rejected": 0, "reason": "no cell produced a finite Sharpe"}
    sub = np.nan_to_num(arr[:, idx], nan=-np.inf, posinf=-np.inf, neginf=-np.inf)
    names = [f"{r.construction}/k{r.lead_k}/thr{r.threshold}/h{r.horizon_w}/"
             f"{r.structure}/{r.sign}" for r in league.iloc[idx].itertuples()]
    res = romano_wolf(obs[idx], sub, alpha=alpha, names=names)
    return {"result": res, "n_rejected": res.n_rejected, "n_tested": int(idx.size),
            "table": res.table.head(15), "alpha": alpha, "draws": res.n_draws,
            "rank1_adjusted_p": float(res.table["p_adjusted"].iloc[0])}


def spectral_null(
    zc: pd.Series,
    zs: pd.Series,
    weeks: pd.DatetimeIndex,
    keys: Sequence[CellKey],
    return_bank: Dict[Tuple[str, int], np.ndarray],
    cfg: D.DetachConfig,
    *,
    draws: Optional[int] = None,
    rng: Optional[np.random.Generator] = None,
    min_trades: int = 8,
    show_progress: bool = False,
) -> Dict[str, object]:
    """The permissive null: phase-randomise BOTH inputs, rebuild, re-score.

    Each draw replaces the sentiment index and the surprise composite with
    series of identical power spectrum -- so identical autocorrelation -- and no
    relationship to each other or to anything else, then pushes them through
    ``detachment`` unchanged so every construction and every ``k`` is rebuilt by
    the production code.

    It is reported BESIDE the rotation null, never instead of it. It has as many
    draws as you like, so it resolves a small p-value where the rotation set
    cannot; but a phase-randomised surrogate wanders less than a near-unit-root
    sample really does, which is why the conservative one is the headline. Both
    sizes are measured by :func:`measure_harness_size` rather than assumed.
    """
    import dataclasses

    from fed_sentiment_lead_data import phase_randomise

    rng = rng or cfg.rng(13)
    draws = int(draws if draws is not None else cfg.surrogate_draws)
    # Randomise on each series' OWN finite span and reindex afterwards, which is
    # what production does: the constructions are computed on the full series and
    # ``common_support`` intersects after. Reindexing FIRST and randomising the
    # truncated series lets every warm-up and every lead k eat from inside the
    # test window -- measured on one draw, the surrogate's ``resid``/k11 row had
    # 85 finite weeks against the observed 121.
    zc_w = zc.dropna().to_numpy(float)
    zs_w = zs.dropna().to_numpy(float)
    zc_idx, zs_idx = zc.dropna().index, zs.dropna().index
    okc, oks = np.isfinite(zc_w), np.isfinite(zs_w)
    if okc.sum() < 30 or oks.sum() < 30:
        return {"max_abs_sharpe": np.array([]), "draws_used": 0, "q95": np.nan,
                "p_floor": np.nan}
    sig_keys = sorted({(c, int(k)) for (c, k, _t, _h, _s) in keys})
    row_of = {sk: i for i, sk in enumerate(sig_keys)}
    key_row = [row_of[(c, int(k))] for (c, k, _t, _h, _s) in keys]

    it = range(draws)
    if show_progress:
        try:
            from tqdm.auto import tqdm

            it = tqdm(it, desc="spectral null")
        except Exception:  # noqa: BLE001
            pass
    maxima = []
    for _ in it:
        sc = pd.Series(phase_randomise(zc_w, rng), index=zc_idx)
        ss = pd.Series(phase_randomise(zs_w, rng), index=zs_idx)
        rows = []
        for (c, k) in sig_keys:
            sub = dataclasses.replace(cfg, construction=c, lead_k=int(k))
            rows.append(D.detachment(sc, ss, sub).reindex(weeks).to_numpy(float))
        stat, _best, _ = grid_statistic(np.vstack(rows), keys, key_row, return_bank,
                                        cfg, min_trades=min_trades)
        if np.isfinite(stat):
            maxima.append(stat)
    m = np.asarray(maxima, float)
    return {"max_abs_sharpe": m, "draws_used": int(m.size),
            "q50": float(np.quantile(m, 0.50)) if m.size else np.nan,
            "q95": float(np.quantile(m, 0.95)) if m.size else np.nan,
            "p_floor": 1.0 / (m.size + 1) if m.size else np.nan}


def follow_share_null(
    dmat: np.ndarray,
    keys: Sequence[CellKey],
    key_row: Sequence[int],
    return_bank: Dict[Tuple[str, int], np.ndarray],
    cfg: D.DetachConfig,
    *,
    top: int = 100,
    max_k: Optional[int] = None,
    max_h: Optional[int] = None,
    min_trades: int = 8,
) -> Dict[str, object]:
    """Is 'follow' dominating the top of the league, or is that what noise does?

    "82 of the best 100 cells are follow" reads like a finding until you ask how
    often a MISALIGNED copy of the same signal produces a top hundred that
    lopsided. Both readings of a cell are scored, so whichever wins is the sign
    of a difference between two noisy numbers, and the winners will cluster on
    one side whenever the instruments share a directional drift over the window
    -- which SR3 did. This measures the observed share against the same rotation
    set the p-value uses, so the claim is either supported or withdrawn on
    evidence rather than eyeballed.
    """
    n_weeks = dmat.shape[1]

    def _share(mat: np.ndarray) -> float:
        srs = np.full(len(keys), np.nan)
        sgn = np.ones(len(keys))
        for j, (_c, _k, thr, h, struct) in enumerate(keys):
            r = return_bank.get((struct, int(h)))
            if r is None:
                continue
            cost = (2.0 * cfg.cost_bp_one_way * D.STRUCTURES[struct][2]
                    / D.STRUCTURES[struct][3])
            srs[j], sgn[j], _i, _p = best_of_both(
                mat[key_row[j]], r, threshold=float(thr), horizon=int(h),
                cost_bp=cost, n_weeks=n_weeks, min_trades=min_trades)
        ok = np.flatnonzero(np.isfinite(srs))
        if ok.size < top:
            return np.nan
        best = ok[np.argsort(-srs[ok])][:top]
        return float((sgn[best] < 0).mean())

    observed = _share(dmat)
    max_k = max_k if max_k is not None else max(int(k) for (_c, k, _t, _h, _s) in keys)
    max_h = max_h if max_h is not None else max(int(h) for (_c, _k, _t, h, _s) in keys)
    shares = []
    for d in rotation_offsets(n_weeks, max_k, max_h):
        v = _share(np.roll(dmat, int(d), axis=1))
        if np.isfinite(v):
            shares.append(v)
    s = np.asarray(shares, float)
    return {
        "observed_follow_share": observed,
        "null_follow_shares": s,
        "null_median": float(np.median(s)) if s.size else np.nan,
        "p_at_least_as_lopsided": (float((1 + np.sum(s >= observed)) / (1 + s.size))
                                   if s.size and np.isfinite(observed) else np.nan),
        "draws": int(s.size), "top": int(top),
    }


def rotation_pvalue(observed: float, null: Dict[str, object]) -> float:
    m = np.asarray(null["max_abs_sharpe"], float)
    if m.size == 0 or not np.isfinite(observed):
        return np.nan
    return float((1 + np.sum(m >= observed)) / (1 + m.size))


def sign_flip_pvalue(pnl: Sequence[float], *, draws: int = 20000,
                     rng: Optional[np.random.Generator] = None) -> Dict[str, float]:
    """One cell's Sharpe against a shared sign-flip null.

    Row permutation cannot test a Sharpe -- shuffling the order leaves the mean
    and the standard deviation untouched, so the statistic is invariant and the
    p-value is uniform by construction whatever the data says
    (``project_rvutils_statistical_finance``). Flipping SIGNS changes the mean
    and not the dispersion, which is the null a Sharpe actually has.
    """
    p = np.asarray(list(pnl), float)
    p = p[np.isfinite(p)]
    if p.size < 8:
        return {"observed": np.nan, "p": np.nan, "draws": 0}
    rng = rng or np.random.default_rng(0)
    obs = abs(_sharpe(p))
    flips = rng.choice([-1.0, 1.0], size=(draws, p.size))
    sims = flips * p[None, :]
    mu = sims.mean(axis=1)
    sd = sims.std(axis=1, ddof=1)
    stat = np.abs(np.where(sd > 0, mu / sd, np.nan))
    ok = np.isfinite(stat)
    return {"observed": obs, "p": float((1 + np.sum(stat[ok] >= obs)) / (1 + ok.sum())),
            "draws": int(ok.sum())}


# --------------------------------------------------------------------------
# deflation
# --------------------------------------------------------------------------
def deflate(streams_both: np.ndarray, league: pd.DataFrame, *, method: str = "bailey",
            seed: int = 0) -> Dict[str, object]:
    """DSR of the best trial, with the trial count estimated from the trials.

    Fed ``streams_both`` -- every cell in BOTH directions -- for two reasons.
    Taking the maximum over a set that has already been sign-optimised would
    make every trial's Sharpe non-negative, halving the observed cross-trial
    variance and lowering the ``SR0`` bar by exactly the amount the sign search
    is worth. And the maximum over the two-sided set is ``max |Sharpe|``, which
    is the statistic the rotation null is scored on, so the two tests answer the
    same question.

    Reported BESIDE the rotation p-value and never instead of it: with thousands
    of trials over ~120 weekly observations the correlation matrix is
    ill-conditioned -- the library logs that warning itself -- and a parametric
    deflation resting on an overfit ``rho-bar`` is weaker evidence than an exact
    permutation test with a coarse floor.
    """
    from RVUtils.StatisticalFinance.deflated_sharpe import (
        deflated_sharpe_of_best, effective_trials)

    keep = [i for i in range(streams_both.shape[0])
            if np.isfinite(streams_both[i]).all() and streams_both[i].std(ddof=1) > 0]
    if not keep:
        return {"dsr": np.nan, "reason": "no cell produced a usable stream"}
    rng = np.random.default_rng(seed)
    series = [streams_both[i] for i in keep]
    out = deflated_sharpe_of_best(series, method=method, rng=rng)
    out["n_eff_evt_mc"] = float(effective_trials(series, method="evt_mc", rng=rng))
    row = keep[int(out.get("best_index", 0))]
    n_cells = len(league)
    out["best_cell"] = league.iloc[row % n_cells].to_dict()
    out["best_direction"] = "as-scored" if row < n_cells else "flipped"
    return out


# --------------------------------------------------------------------------
# calibration -- run the harness on data whose answer is known
# --------------------------------------------------------------------------
def synthetic_bank(
    weeks: pd.DatetimeIndex,
    cfg: D.DetachConfig,
    rng: np.random.Generator,
    *,
    phi: float = 0.97,
    constructions: Sequence[str] = D.CONSTRUCTIONS,
    ks: Sequence[int] = D.LEAD_KS,
) -> Dict[Tuple[str, int], pd.Series]:
    """A signal bank with NO relationship to anything, built by the real pipeline.

    Two unrelated AR(phi) series stand in for the sentiment index and the
    surprise composite; every construction and every ``k`` is then computed by
    :func:`fed_detachment_data.detachment` unchanged. So the surrogate bank
    inherits the real bank's internal correlation structure -- which is what the
    grid's maximum is sensitive to -- while carrying no information about the
    price at all.
    """
    import dataclasses

    n = len(weeks)
    a = pd.Series(_ar1(n, phi, rng), index=weeks)
    b = pd.Series(_ar1(n, phi, rng), index=weeks)
    out = {}
    for c in constructions:
        for k in ks:
            sub = dataclasses.replace(cfg, construction=c, lead_k=int(k))
            out[(c, int(k))] = D.detachment(a, b, sub)
    return out


def _ar1(n: int, phi: float, rng: np.random.Generator, *, unit_sd: bool = True
         ) -> np.ndarray:
    """One AR(phi) path, rescaled to unit standard deviation by default.

    The rescaling matters for the calibration and is not cosmetic. An AR(0.97)
    path with unit innovations has a standard deviation near 4, while the real
    inputs are z-scores of order 1 -- and the grid's entry thresholds (0.5, 1.0,
    1.5) are ABSOLUTE. Feeding an unscaled path means the thresholds almost
    never bind, the synthetic grid takes a different number of trades from the
    real one, and the "identical pipeline" the size measurement claims to run is
    not identical. Scaling is a full-sample operation, which would be a leak in a
    trading signal but is simply how the null-data generator is parameterised.
    """
    e = rng.normal(size=n)
    x = np.empty(n)
    x[0] = e[0]
    for i in range(1, n):
        x[i] = phi * x[i - 1] + e[i]
    if unit_sd:
        sd = float(np.std(x, ddof=1))
        if sd > 0:
            x = x / sd
    return x


def measure_harness_size(
    weeks: pd.DatetimeIndex,
    return_bank: Dict[Tuple[str, int], np.ndarray],
    cfg: D.DetachConfig,
    *,
    trials: int = 40,
    seed: int = 7000,
    keys: Optional[Sequence[CellKey]] = None,
    alpha: float = 0.05,
    which: str = "rotation",
    null_draws: Optional[int] = None,
    show_progress: bool = True,
) -> Dict[str, object]:
    """How often does the whole apparatus reject when there is nothing to find?

    A checking tool that is itself wrong reports success and hides the thing it
    was built to find. So the grid, the rotation null and the p-value are run
    end to end against a signal that cannot possibly work, ``trials`` times, and
    the rejection rate at nominal ``alpha`` is the size the real p-value should
    be read against.
    """
    keys = list(keys or cell_keys())
    rejected, ps = 0, []
    it = range(trials)
    if show_progress:
        try:
            from tqdm.auto import tqdm

            it = tqdm(it, desc="harness size")
        except Exception:  # noqa: BLE001
            pass
    for i in it:
        rng = np.random.default_rng(seed + i)
        # Generate on an index extended BACKWARDS, then reindex to ``weeks``.
        # Generating on ``weeks`` itself leaves every construction's own warm-up
        # inside the test window: measured at the shipped seeds, the calibration
        # dmat was 14.9% NaN with ragged per-row prefixes of 0-36 weeks, where
        # production's is 0.0% NaN -- and ``np.roll`` then moves that dead block
        # around under every rotation, which is the ragged-prefix hazard
        # ``common_support``'s own docstring exists to prevent. So the surrogate
        # would not have been the "identical pipeline" the size claim asserts.
        ext = _extend_back(weeks, _CALIBRATION_PAD_W)
        a = pd.Series(_ar1(len(ext), 0.97, rng), index=ext)
        b = pd.Series(_ar1(len(ext), 0.97, rng), index=ext)
        bank = {k: v.reindex(weeks) for k, v in _bank_from(a, b, cfg).items()}
        if len(common_support(bank)) < len(weeks):
            continue
        sig_keys = sorted(bank)
        row_of = {sk: j for j, sk in enumerate(sig_keys)}
        dmat = np.vstack([bank[sk].to_numpy(float) for sk in sig_keys])
        key_row = [row_of[(c, int(k))] for (c, k, _t, _h, _s) in keys]
        obs, _, _ = grid_statistic(dmat, keys, key_row, return_bank, cfg)
        if which == "rotation":
            null = rotation_null(dmat, keys, key_row, return_bank, cfg,
                                 draws=null_draws, show_progress=False)
        elif which == "spectral":
            null = spectral_null(a, b, weeks, keys, return_bank, cfg,
                                 draws=null_draws or 200,
                                 rng=np.random.default_rng(seed + 50000 + i))
        else:
            raise ValueError(f"unknown null {which!r}")
        p = rotation_pvalue(obs, null)
        if np.isfinite(p):
            ps.append(p)
            rejected += p < alpha
    n = len(ps)
    lo, hi = _wilson(rejected, n)
    return {"null": which, "trials": n, "rejected": int(rejected),
            "size": rejected / n if n else np.nan,
            "wilson_lo": lo, "wilson_hi": hi, "alpha": alpha,
            "median_p": float(np.median(ps)) if ps else np.nan}


#: Weeks of synthetic history generated BEFORE the test window so every
#: construction's warm-up happens outside it. 120 comfortably covers the longest
#: chain: a 52-week rolling window, an 11-week lead and a 4-week difference.
_CALIBRATION_PAD_W = 120


def _extend_back(weeks: pd.DatetimeIndex, pad: int) -> pd.DatetimeIndex:
    """``weeks`` with ``pad`` more weekly points prepended at the same spacing."""
    step = weeks[1] - weeks[0]
    head = pd.DatetimeIndex([weeks[0] - step * (pad - i) for i in range(pad)])
    return head.append(pd.DatetimeIndex(weeks))


def _bank_from(zc: pd.Series, zs: pd.Series, cfg: D.DetachConfig
               ) -> Dict[Tuple[str, int], pd.Series]:
    import dataclasses

    out = {}
    for c in D.CONSTRUCTIONS:
        for k in D.LEAD_KS:
            sub = dataclasses.replace(cfg, construction=c, lead_k=int(k))
            out[(c, int(k))] = D.detachment(zc, zs, sub)
    return out


def measure_harness_power(
    weeks: pd.DatetimeIndex,
    return_bank: Dict[Tuple[str, int], np.ndarray],
    cfg: D.DetachConfig,
    *,
    planted_structure: str = "out3",
    planted_horizon: int = 4,
    noise: float = 1.0,
    trials: int = 20,
    seed: int = 9000,
    keys: Optional[Sequence[CellKey]] = None,
    alpha: float = 0.05,
) -> Dict[str, object]:
    """And can it FIND an edge that is really there?

    A signal is planted by construction: the detachment series is the sign of
    the forward return the planted cell would earn, buried in ``noise`` standard
    deviations of AR noise. Size without power is a test that never rejects; the
    pair is what makes a non-rejection informative.
    """
    keys = list(keys or cell_keys())
    r = return_bank[(planted_structure, int(planted_horizon))]
    detected, ps = 0, []
    for i in range(trials):
        rng = np.random.default_rng(seed + i)
        # The edge is planted in the SENTIMENT INPUT and then pushed through
        # ``build_signal_bank`` unchanged, so the sixteen constructions differ
        # from one another exactly as they do in production. An earlier version
        # planted it directly into the bank, giving sixteen IDENTICAL rows --
        # which is a grid with no internal diversity, and therefore a different
        # maximum and a different null bar from the one the real run faces.
        ext = _extend_back(weeks, _CALIBRATION_PAD_W)
        base = np.where(np.isfinite(r), np.sign(np.nan_to_num(r)), 0.0)
        # the padded prefix carries noise only; it exists so the constructions
        # warm up OUTSIDE the test window, exactly as they do in production
        padded = np.concatenate([np.zeros(len(ext) - len(weeks)), base])
        zs_planted = pd.Series(padded + noise * _ar1(len(ext), 0.5, rng), index=ext)
        zc_null = pd.Series(_ar1(len(ext), 0.97, rng), index=ext)
        bank = {k: v.reindex(weeks)
                for k, v in _bank_from(zc_null, zs_planted, cfg).items()}
        sig_keys = sorted(bank)
        row_of = {sk: j for j, sk in enumerate(sig_keys)}
        dmat = np.vstack([bank[sk].to_numpy(float) for sk in sig_keys])
        key_row = [row_of[(c, int(k))] for (c, k, _t, _h, _s) in keys]
        obs, _, _ = grid_statistic(dmat, keys, key_row, return_bank, cfg)
        null = rotation_null(dmat, keys, key_row, return_bank, cfg, show_progress=False)
        p = rotation_pvalue(obs, null)
        if np.isfinite(p):
            ps.append(p)
            detected += p < alpha
    n = len(ps)
    lo, hi = _wilson(detected, n)
    return {"trials": n, "detected": int(detected), "power": detected / n if n else np.nan,
            "wilson_lo": lo, "wilson_hi": hi, "alpha": alpha,
            "median_p": float(np.median(ps)) if ps else np.nan}


def _wilson(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    d = 1.0 + z * z / n
    centre = p + z * z / (2 * n)
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((centre - half) / d, (centre + half) / d)

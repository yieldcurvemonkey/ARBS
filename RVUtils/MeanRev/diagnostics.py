"""How big is the pond? -- move-size diagnostics that bound a strategy in advance.

The prior butterfly lab established that fading SR3 flies is *directionally*
right (fade beats momentum in 17 of 23 frameworks) and still loses money,
because the moves are barely larger than the round trip. That reframes what a
new signal has to do:

    A better signal can only help in two ways -- call the sign more often, or
    **select days on which the fly moves further**. The second is the binding
    one, and it is measurable *before* any backtest.

So every candidate signal here is scored on three numbers, at a fixed horizon:

``oracle_bp``
    ``E[|level[t+h] - level[t]|]`` over the days the signal fires. This is what
    a trader with perfect foresight of the *direction* would capture. It is an
    upper bound no amount of signal work can exceed, and it is compared against
    the round trip directly.

``selectivity``
    the same expectation divided by its unconditional counterpart. Above 1.0
    means the signal picks days with bigger moves; at 1.0 it is picking days at
    random with respect to move size, and every bp of edge then has to come out
    of the sign call alone.

``p_beat_cost``
    ``P(|move| > round trip)`` on the selected days -- the share of entries that
    could pay for themselves even with a perfect sign call.

None of this knows what a butterfly is; it takes a level panel and a boolean
mask.
"""
from __future__ import annotations

from typing import Dict, Optional, Sequence

import numpy as np
import pandas as pd

__all__ = [
    "forward_move", "move_profile", "oracle_table", "selectivity_table",
    "signal_entry_mask", "variance_decomposition",
]


def forward_move(levels: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """``level[t+h] - level[t]``, aligned on ``t``. NaN in the last ``h`` rows."""
    h = int(horizon)
    return levels.shift(-h) - levels


def signal_entry_mask(signal: pd.DataFrame, entry_z: float, *,
                      gate: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """``|signal| >= entry_z``, optionally intersected with a gate.

    This is the engine's entry condition with the position bookkeeping removed,
    so a move profile can be computed for a signal without running a backtest
    and without inheriting the backtest's overlap rules.
    """
    m = signal.abs() >= float(entry_z)
    m = m & signal.notna()
    if gate is not None:
        m = m & gate.reindex(index=m.index, columns=m.columns).fillna(False)
    return m.fillna(False)


def move_profile(levels: pd.DataFrame, mask: Optional[pd.DataFrame], *,
                 horizons: Sequence[int] = (5, 10, 21),
                 round_trip_bp: float = 2.0) -> pd.DataFrame:
    """Distribution of the forward move on the selected (date, key) cells.

    ``mask=None`` gives the unconditional profile, which is the denominator of
    :func:`selectivity_table`.
    """
    rows = []
    for h in horizons:
        g = forward_move(levels, h)
        if mask is not None:
            g = g.where(mask.reindex(index=g.index, columns=g.columns).fillna(False))
        a = g.to_numpy(dtype=float).ravel()
        a = a[np.isfinite(a)]
        if a.size == 0:
            # A signal that never fires still needs a row with every column, or
            # any table built from several signals loses the column entirely and
            # its consumers raise KeyError on the first NaN-free one.
            rows.append({
                "horizon": h, "n": 0, "mean_bp": np.nan, "sd_bp": np.nan,
                "mean_abs_bp": np.nan, "median_abs_bp": np.nan,
                "p75_abs_bp": np.nan, "p90_abs_bp": np.nan,
                "oracle_net_bp": np.nan, "p_beat_cost": np.nan})
            continue
        ab = np.abs(a)
        rows.append({
            "horizon": h, "n": int(a.size),
            "mean_bp": float(a.mean()), "sd_bp": float(a.std(ddof=1)),
            "mean_abs_bp": float(ab.mean()), "median_abs_bp": float(np.median(ab)),
            "p75_abs_bp": float(np.quantile(ab, 0.75)),
            "p90_abs_bp": float(np.quantile(ab, 0.90)),
            "oracle_net_bp": float(ab.mean() - float(round_trip_bp)),
            "p_beat_cost": float((ab > float(round_trip_bp)).mean()),
        })
    return pd.DataFrame(rows)


def oracle_table(levels: pd.DataFrame, masks: Dict[str, Optional[pd.DataFrame]], *,
                 horizons: Sequence[int] = (5, 10, 21),
                 round_trip_bp: float = 2.0) -> pd.DataFrame:
    """:func:`move_profile` for several named signals, plus the unconditional row.

    ``masks`` maps a label to an entry mask; ``None`` (or the key
    ``'unconditional'``) gives every cell. ``selectivity`` is each label's
    ``mean_abs_bp`` over the unconditional one at the same horizon.
    """
    base = move_profile(levels, None, horizons=horizons, round_trip_bp=round_trip_bp)
    ref = base.set_index("horizon")["mean_abs_bp"]
    out = [base.assign(signal="unconditional", selectivity=1.0)]
    for name, m in masks.items():
        p = move_profile(levels, m, horizons=horizons, round_trip_bp=round_trip_bp)
        p["signal"] = name
        p["selectivity"] = p["mean_abs_bp"] / p["horizon"].map(ref)
        out.append(p)
    cols = ["signal", "horizon", "n", "mean_abs_bp", "selectivity", "median_abs_bp",
            "p90_abs_bp", "oracle_net_bp", "p_beat_cost", "mean_bp", "sd_bp"]
    res = pd.concat(out, ignore_index=True)
    return res[[c for c in cols if c in res.columns]]


def selectivity_table(levels: pd.DataFrame, signals: Dict[str, pd.DataFrame], *,
                      entry_z: float = 2.0, gate: Optional[pd.DataFrame] = None,
                      horizons: Sequence[int] = (5, 10, 21),
                      round_trip_bp: float = 2.0) -> pd.DataFrame:
    """:func:`oracle_table` driven directly by signal panels and one threshold."""
    masks = {k: signal_entry_mask(v, entry_z, gate=gate) for k, v in signals.items()}
    return oracle_table(levels, masks, horizons=horizons, round_trip_bp=round_trip_bp)


def variance_decomposition(actual: pd.DataFrame, explained: pd.DataFrame, *,
                           groups: Optional[pd.Series] = None) -> pd.DataFrame:
    """How much of a level panel a model panel accounts for, per group.

    ``explained`` is the model's prediction on the same ``date x key`` grid;
    the residual is ``actual - explained``. Reports the two standard
    deviations, the ratio, ``1 - var(resid)/var(actual)`` and the correlation.
    A negative ``r2`` is not a bug -- an unbiased model can still add variance
    if it is noisy, and saying so is the point of reporting it.
    """
    a = actual.reindex(index=explained.index, columns=explained.columns)
    e = explained
    r = a - e
    g = (pd.Series("all", index=a.columns) if groups is None
         else pd.Series(groups).reindex(a.columns).fillna("all"))
    rows = []
    for name, cols in g.groupby(g):
        c = list(cols.index)
        av = a[c].to_numpy(dtype=float).ravel()
        ev = e[c].to_numpy(dtype=float).ravel()
        rv = r[c].to_numpy(dtype=float).ravel()
        ok = np.isfinite(av) & np.isfinite(ev)
        if ok.sum() < 10:
            continue
        av, ev, rv = av[ok], ev[ok], rv[ok]
        va = float(np.var(av, ddof=1))
        rows.append({
            "group": name, "n": int(ok.sum()),
            "sd_actual_bp": float(np.sqrt(va)),
            "sd_model_bp": float(np.std(ev, ddof=1)),
            "sd_resid_bp": float(np.std(rv, ddof=1)),
            "resid_share": float(np.std(rv, ddof=1) / np.sqrt(va)) if va > 0 else np.nan,
            "r2": float(1.0 - np.var(rv, ddof=1) / va) if va > 0 else np.nan,
            # a constant model has no correlation to report, not a NaN warning
            "corr": (float(np.corrcoef(av, ev)[0, 1])
                     if va > 0 and np.var(ev, ddof=1) > 0 else np.nan),
        })
    return pd.DataFrame(rows)

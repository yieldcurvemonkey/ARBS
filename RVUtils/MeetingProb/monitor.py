"""Channel decomposition and the two-digital classifier.

Channel 1 (two-sided, convergence): per-meeting probability gap between the
option-refit lattice and ZQ's ladder, reported with its bootstrap sigma.
Channel 2 (one-sided, harvest): the premium residual no independent-q vector
reproduces — coupling, >25bp mass, tails. Measured, never claimed convergeable.

The two-digital classifier, executable from two premium quotes: price the
boundary digitals either side of the modal atom from LISTED verticals and from
the ZQ tree. One side rich => a genuine per-meeting P disagreement (channel 1).
Both sides rich => overdispersion of the move count — coupling (channel 2) —
because no independent-q vector fattens both tails at once while keeping the
mean pinned.
"""
from __future__ import annotations

import dataclasses
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.MeetingProb.atoms import ContractMeetings, atom_distribution
from RVUtils.MeetingProb.pricer import digital_prob
from RVUtils.MeetingProb.refit import RefitResult

__all__ = ["boundary_digitals", "two_digital_test", "channel_row"]


def boundary_digitals(
    cm: ContractMeetings,
    forward_rate: float,
    day_quotes: pd.DataFrame,
    *,
    smear_bp: float,
    q: Optional[Sequence[float]] = None,
    tol: float = 0.10,
) -> pd.DataFrame:
    """Listed vs tree digital P(rate >= K) at every atom boundary.

    Boundaries are midpoints between adjacent atoms; the listed side prices the
    tightest vertical bracketing each boundary (via the lab's
    ``vertical_digital``), the tree side integrates the smeared atoms.
    """
    from RVUtils.SFRRVLab.panels import vertical_digital

    rates, probs = atom_distribution(cm, forward_rate, q=q)
    ks = [float(0.5 * (lo + hi)) for lo, hi in zip(rates[:-1], rates[1:])]
    # outer boundaries: half a spacing beyond the extreme atoms, so symmetric
    # tail fattening (which cancels at interior midpoints) is visible
    if len(rates) >= 2:
        half = float(np.min(np.diff(np.sort(rates)))) / 2.0
        ks = [float(rates.min() - half)] + ks + [float(rates.max() + half)]
    rows = []
    for k in ks:
        d = vertical_digital(day_quotes, k, tol=tol,
                            forward_price=100.0 - forward_rate)
        if d is None or not (-0.02 <= d["prob"] <= 1.02):
            continue
        rows.append({
            "boundary_rate": k,
            "p_listed": float(d["prob"]),
            "p_tree": digital_prob(rates, probs, k, smear_bp=smear_bp),
            "k_lo": d["k_lo"], "k_hi": d["k_hi"], "right": d["right"],
            "width_bp": d["width_bp"],
        })
    out = pd.DataFrame(rows)
    if len(out):
        out["gap"] = out["p_listed"] - out["p_tree"]
    return out


def two_digital_test(
    bd: pd.DataFrame, *, rich_pp: float = 0.03, tail_pp: float = 0.005
) -> str:
    """'channel1' | 'channel2' | 'flat' | 'thin' from the boundary-digital table.

    Two signatures, two places to look (worked out in the tests' algebra):

    * **Channel 2 (overdispersion/coupling)** lives in the OUTER tails: mass
      pushed beyond BOTH extreme atoms. At interior boundaries a symmetric
      smear nearly cancels (the atom above a boundary loses what the atom
      below gains), so the tails are where no independent-q vector can follow.
    * **Channel 1 (per-meeting reallocation)** lives at the boundaries flanking
      the tree's modal cell: shifting probability between adjacent move counts
      enriches exactly one side of the mode and cheapens the other.
    """
    if bd is None or len(bd) < 3:
        return "thin"
    b = bd.sort_values("boundary_rate").reset_index(drop=True)

    # outer tails (first and last boundary in the table)
    lo, hi = b.iloc[0], b.iloc[-1]
    tail_lo = lo["p_tree"] - lo["p_listed"]          # market mass below the low tail
    tail_hi = hi["p_listed"] - hi["p_tree"]          # market mass above the high tail
    if tail_lo > tail_pp and tail_hi > tail_pp:
        return "channel2"

    # modal cell = consecutive boundary pair with the largest tree mass between
    cell_mass = (b["p_tree"].to_numpy()[:-1] - b["p_tree"].to_numpy()[1:])
    i = int(np.argmax(cell_mass))
    b_lo, b_hi = b.iloc[i], b.iloc[i + 1]
    rich_below = b_lo["p_tree"] - b_lo["p_listed"]   # market richer below the mode
    rich_above = b_hi["p_listed"] - b_hi["p_tree"]   # market richer above the mode
    if rich_below > rich_pp and rich_above > rich_pp:
        return "channel2"
    if abs(rich_below) > rich_pp or abs(rich_above) > rich_pp:
        return "channel1"
    return "flat"


def channel_row(
    cm: ContractMeetings,
    fit: RefitResult,
    boot: Optional[Dict[str, np.ndarray]],
    bd: pd.DataFrame,
) -> Dict[str, object]:
    """One monitor row per (as_of, contract): gaps, sigmas, residual, class."""
    row: Dict[str, object] = {
        "as_of": cm.as_of, "symbol": cm.symbol,
        "n_resolved": cm.n_resolved, "n_quotes": fit.n_quotes,
        "rmse_bp": fit.rmse_bp, "smear_bp": fit.smear_bp,
        "unresolved_std_bp": float(np.sqrt(cm.unresolved_var_bp2)),
        "any_stale": cm.any_stale,
        "channel": two_digital_test(bd),
        "n_boundaries": 0 if bd is None else int(len(bd)),
        "max_abs_digital_gap": (np.nan if bd is None or not len(bd)
                                else float(bd["gap"].abs().max())),
    }
    for i, r in enumerate(cm.resolved):
        tag = r.effective.strftime("%b%y").lower()
        row[f"pgap_{tag}"] = float(fit.p_gap[i])
        row[f"q_opt_{tag}"] = float(fit.q[i])
        row[f"q_zq_{tag}"] = float(fit.q_zq[i])
        row[f"vgap_{tag}_bp2"] = float(fit.var_opt_bp2[i] - fit.var_zq_bp2[i])
        if boot is not None:
            row[f"qstd_{tag}"] = float(boot["q_std"][i])
            row[f"tstat_{tag}"] = (float(fit.p_gap[i] / boot["q_std"][i])
                                   if boot["q_std"][i] > 1e-9 else np.nan)
    return row

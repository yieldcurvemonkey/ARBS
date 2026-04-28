"""Payoff distribution metrics: central moments, asymmetry, percentiles, tails."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

import numpy as np


@dataclass(frozen=True)
class PayoffMetrics:
    mean_bp: float
    std_bp: float
    skew: float
    excess_kurtosis: float
    p_profit: float
    ev_given_profit_bp: float
    ev_given_loss_bp: float
    asymmetry_ratio: float
    percentiles_bp: Dict[str, float]
    tail_ratio: float

    def to_dict(self) -> Dict[str, float]:
        d = {
            "mean_bp": self.mean_bp,
            "std_bp": self.std_bp,
            "skew": self.skew,
            "excess_kurt": self.excess_kurtosis,
            "p_profit": self.p_profit,
            "ev_given_profit_bp": self.ev_given_profit_bp,
            "ev_given_loss_bp": self.ev_given_loss_bp,
            "asymmetry_ratio": self.asymmetry_ratio,
            "tail_ratio": self.tail_ratio,
        }
        d.update({f"pct_{k}": v for k, v in self.percentiles_bp.items()})
        return d


def _percentiles(samples: np.ndarray) -> Dict[str, float]:
    pcts = np.percentile(samples, [5, 25, 50, 75, 95])
    return {
        "p5": float(pcts[0]),
        "p25": float(pcts[1]),
        "p50": float(pcts[2]),
        "p75": float(pcts[3]),
        "p95": float(pcts[4]),
    }


def _asymmetry_components_from_samples(
    samples: np.ndarray,
) -> Tuple[float, float, float, float]:
    pos = samples[samples > 0]
    neg = samples[samples < 0]
    n = len(samples)
    p_profit = len(pos) / n if n else 0.0
    ev_pos = float(pos.mean()) if pos.size else 0.0
    ev_neg = float(neg.mean()) if neg.size else 0.0
    upper = ev_pos * (len(pos) / n if n else 0.0)
    lower = abs(ev_neg * (len(neg) / n if n else 0.0))
    asym = upper / lower if lower > 0 else float("inf")
    return p_profit, ev_pos, ev_neg, asym


def metrics_from_samples(samples: np.ndarray) -> PayoffMetrics:
    samples = np.asarray(samples, dtype=float)
    mean = float(samples.mean())
    std = float(samples.std(ddof=1))
    if std > 0:
        z = (samples - mean) / std
        skew = float((z ** 3).mean())
        excess_kurt = float((z ** 4).mean()) - 3.0
    else:
        skew = 0.0
        excess_kurt = 0.0

    p_profit, ev_pos, ev_neg, asym = _asymmetry_components_from_samples(samples)
    pcts = _percentiles(samples)
    tail = abs(pcts["p95"]) / abs(pcts["p5"]) if pcts["p5"] != 0 else float("inf")
    return PayoffMetrics(
        mean_bp=mean,
        std_bp=std,
        skew=skew,
        excess_kurtosis=excess_kurt,
        p_profit=p_profit,
        ev_given_profit_bp=ev_pos,
        ev_given_loss_bp=ev_neg,
        asymmetry_ratio=asym,
        percentiles_bp=pcts,
        tail_ratio=tail,
    )


def metrics_from_pdf(outcomes_bp: np.ndarray, probs: np.ndarray) -> PayoffMetrics:
    outcomes_bp = np.asarray(outcomes_bp, dtype=float)
    probs = np.asarray(probs, dtype=float)
    total = probs.sum()
    if total > 0:
        probs = probs / total

    mean = float((outcomes_bp * probs).sum())
    var = float(((outcomes_bp - mean) ** 2 * probs).sum())
    std = float(np.sqrt(max(var, 0.0)))
    if std > 0:
        skew = float(((outcomes_bp - mean) ** 3 * probs).sum() / (std ** 3))
        excess_kurt = float(((outcomes_bp - mean) ** 4 * probs).sum() / (std ** 4)) - 3.0
    else:
        skew = 0.0
        excess_kurt = 0.0

    pos_mask = outcomes_bp > 0
    neg_mask = outcomes_bp < 0
    p_profit = float(probs[pos_mask].sum())
    p_loss = float(probs[neg_mask].sum())
    ev_pos_num = float((outcomes_bp[pos_mask] * probs[pos_mask]).sum())
    ev_neg_num = float((outcomes_bp[neg_mask] * probs[neg_mask]).sum())
    ev_pos = ev_pos_num / max(p_profit, 1e-12) if p_profit > 0 else 0.0
    ev_neg = ev_neg_num / max(p_loss, 1e-12) if p_loss > 0 else 0.0

    upper = ev_pos_num
    lower = abs(ev_neg_num)
    asym = upper / lower if lower > 0 else float("inf")

    cdf = np.cumsum(probs)
    pct_levels = [0.05, 0.25, 0.50, 0.75, 0.95]
    pct_vals = [float(np.interp(p, cdf, outcomes_bp)) for p in pct_levels]
    pcts = dict(zip(["p5", "p25", "p50", "p75", "p95"], pct_vals))
    tail = abs(pcts["p95"]) / abs(pcts["p5"]) if pcts["p5"] != 0 else float("inf")
    return PayoffMetrics(
        mean_bp=mean,
        std_bp=std,
        skew=skew,
        excess_kurtosis=excess_kurt,
        p_profit=p_profit,
        ev_given_profit_bp=ev_pos,
        ev_given_loss_bp=ev_neg,
        asymmetry_ratio=asym,
        percentiles_bp=pcts,
        tail_ratio=tail,
    )

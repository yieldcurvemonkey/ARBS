"""View-conditional expression pricer — the alpha-overlay lens.

The RV layers established that on clean data the curve and the option surface
price the same scenarios consistently: there is no standing basis to converge.
What remains tradeable is *your* disagreement with the market. This module
encodes a subjective FOMC view as per-meeting move distributions on the 25bp
lattice (the same machinery as the FedWatch null in ``baselines`` — fed with
your probabilities instead of the curve's mantissas), prices candidate
expressions under that measure with settlement-exact day weighting, and ranks
them by expected payoff per unit of worst case — a positively-convex-payoff
screen conditioned on the view.

Payoffs are deterministic per scenario (terminal realisation); options are
priced at their intrinsic under the scenario path vs the supplied premium, so
use listed premiums (the cached smile objects) — never BL-fit mids.
"""
from __future__ import annotations

import dataclasses
import datetime
import itertools
from typing import Dict, List, Mapping, Sequence, Tuple

from RVUtils.FlyVsVol._types import ContractMarginal
from RVUtils.FlyVsVol.baselines import _window_weight

__all__ = [
    "MeetingView",
    "FuturesLeg",
    "OptionLeg",
    "Expression",
    "ExpressionResult",
    "encode_view",
    "price_expressions",
    "view_vs_market_bins",
]

Window = Tuple[datetime.date, datetime.date]


@dataclasses.dataclass(frozen=True)
class MeetingView:
    """Subjective per-meeting move distributions on the lattice."""

    meetings: Tuple[Tuple[datetime.date, Tuple[Tuple[int, float], ...]], ...]
    base_rate: float
    move_size_bp: float = 25.0
    effective_lag_days: int = 1

    def scenarios(self) -> List[Tuple[float, Dict[datetime.date, int]]]:
        """All joint outcomes as (probability, {decision_date: n_moves})."""
        dates = [d for d, _ in self.meetings]
        outcome_sets = [list(probs) for _, probs in self.meetings]
        out = []
        for combo in itertools.product(*outcome_sets):
            prob = 1.0
            moves: Dict[datetime.date, int] = {}
            for d, (n, p) in zip(dates, combo):
                prob *= p
                moves[d] = n
            if prob > 0:
                out.append((prob, moves))
        return out

    def contract_rate(self, window: Window, moves: Mapping[datetime.date, int]) -> float:
        """Day-weighted reference-quarter average rate under one scenario."""
        bump_bp = 0.0
        for d, n in moves.items():
            eff = d + datetime.timedelta(days=self.effective_lag_days)
            bump_bp += n * self.move_size_bp * _window_weight(window, eff)
        return self.base_rate + bump_bp / 100.0


def encode_view(
    meeting_probs: Mapping[datetime.date, Mapping[int, float]],
    *,
    base_rate: float,
    move_size_bp: float = 25.0,
) -> MeetingView:
    meetings = []
    for d in sorted(meeting_probs):
        probs = dict(meeting_probs[d])
        total = sum(probs.values())
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"meeting {d}: probabilities sum to {total}, not 1")
        meetings.append((d, tuple(sorted(probs.items()))))
    return MeetingView(meetings=tuple(meetings), base_rate=base_rate,
                       move_size_bp=move_size_bp)


@dataclasses.dataclass(frozen=True)
class FuturesLeg:
    """Position in RATE terms: weight +1 earns 1bp per bp of rate rise."""

    contract: str
    weight: float
    ref_window: Window
    entry_rate: float  # percent


@dataclasses.dataclass(frozen=True)
class OptionLeg:
    """European-on-terminal-rate approximation; qty +1 = long one option."""

    contract: str
    right: str  # "rate_call" pays (r-K)+ (a price put); "rate_put" pays (K-r)+
    strike_rate: float
    qty: float
    premium_bp: float
    ref_window: Window


@dataclasses.dataclass(frozen=True)
class Expression:
    label: str
    futures: Tuple[FuturesLeg, ...] = ()
    options: Tuple[OptionLeg, ...] = ()


@dataclasses.dataclass(frozen=True)
class ExpressionResult:
    label: str
    e_view_bp: float
    worst_bp: float
    best_bp: float
    ratio: float  # e_view / |worst|; inf when no losing scenario
    p_win: float
    premium_bp: float  # net premium paid (+) across option legs
    scenario_table: Tuple[Tuple[float, float], ...]  # (prob, pnl_bp)


def _scenario_pnl(expr: Expression, view: MeetingView,
                  moves: Mapping[datetime.date, int]) -> float:
    pnl = 0.0
    for leg in expr.futures:
        r = view.contract_rate(leg.ref_window, moves)
        pnl += leg.weight * (r - leg.entry_rate) * 100.0
    for leg in expr.options:
        r = view.contract_rate(leg.ref_window, moves)
        if leg.right == "rate_call":
            intrinsic = max(r - leg.strike_rate, 0.0) * 100.0
        elif leg.right == "rate_put":
            intrinsic = max(leg.strike_rate - r, 0.0) * 100.0
        else:
            raise ValueError(f"unknown right {leg.right!r}")
        pnl += leg.qty * (intrinsic - leg.premium_bp)
    return pnl


def price_expressions(
    view: MeetingView, expressions: Sequence[Expression]
) -> List[ExpressionResult]:
    """Price every expression under the view; ranked by e_view/|worst| desc."""
    scenarios = view.scenarios()
    results = []
    for expr in expressions:
        table = tuple(
            (prob, _scenario_pnl(expr, view, moves)) for prob, moves in scenarios
        )
        e = sum(p * v for p, v in table)
        worst = min(v for _, v in table)
        best = max(v for _, v in table)
        ratio = e / abs(worst) if worst < 0 else float("inf")
        results.append(ExpressionResult(
            label=expr.label,
            e_view_bp=e,
            worst_bp=worst,
            best_bp=best,
            ratio=ratio,
            p_win=sum(p for p, v in table if v > 0),
            premium_bp=sum(l.qty * l.premium_bp for l in expr.options),
            scenario_table=table,
        ))
    return sorted(results, key=lambda r: r.ratio, reverse=True)


def view_vs_market_bins(
    view: MeetingView, marginal: ContractMarginal, window: Window,
    *, bin_halfwidth: float = 0.125,
) -> Dict[float, Tuple[float, float, float]]:
    """Per terminal-rate outcome: (view prob, market RND prob, edge).

    The market probability is the RND mass within +/- ``bin_halfwidth`` of the
    scenario's day-weighted terminal rate — the price of the bin you are
    buying or selling by disagreeing.
    """
    outcomes: Dict[float, float] = {}
    for prob, moves in view.scenarios():
        r = round(view.contract_rate(window, moves), 6)
        outcomes[r] = outcomes.get(r, 0.0) + prob
    table = {}
    for r, p_view in sorted(outcomes.items()):
        p_mkt = float(
            marginal.cdf_at(r + bin_halfwidth) - marginal.cdf_at(r - bin_halfwidth)
        )
        table[r] = (p_view, p_mkt, p_view - p_mkt)
    return table

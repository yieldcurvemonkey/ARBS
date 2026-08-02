"""CME FF-vs-SR3 inter-commodity spread conventions, and the FF-anchored view.

Source: CME "STIR futures Inter-Commodity Spreads on Globex" (June 2026).
The FF vs 3M SOFR ICS (spread type "EF", e.g. ``ZQN4Q4-SR3M4``):

* legs arranged to match exposures between IMM dates — one quarterly SR3
  against the NEXT TWO Fed Funds contract months (SR3M6 vs ZQN6+ZQQ6;
  SR3Z26 vs ZQF27+ZQG27);
* 10:6 leg ratio for DV01 neutrality (10 x $25 vs 6 x $41.67 = $250/bp);
* quoted ``Spread Price = (average FF price) - SR3 price = SOFR rate - FF
  rate`` (worked example: (94.890+94.735)/2 - 94.7775 = 3.5bp).

The ICS blend gives the framework the thing mean-pinning deliberately
discards: a MARKET-priced FF-side anchor for the same reference quarter. The
mean gap between the SR3 forward and the blend is then an observable (the
listed spread), and the FF lattice can be laid down at ABSOLUTE rates
(:func:`ff_conditional_atoms`) instead of being pinned to the option forward.

The blend is the exchange's IMM-proxy, not the true quarter average: the two
full months miss the window's edges. :func:`proxy_wedge_bp` prices that
wedge off the same lattice, and :func:`compounding_wedge_bp` prices the
compounded-vs-arithmetic wedge, so the observed ICS decomposes into
basis + compounding + calendar proxy + residual.
"""
from __future__ import annotations

import calendar
import datetime
from typing import List, Sequence, Tuple

import numpy as np

from RVUtils.MeetingProb.atoms import AtomEngine, split_meetings
from RVUtils.MeetingProb.ladder import MeetingLattice

__all__ = [
    "ics_blend_contracts", "ics_spread_bp", "compounding_wedge_bp",
    "window_level_weights", "proxy_wedge_bp", "ff_conditional_atoms",
]

_MONTH_CODE = "FGHJKMNQUVXZ"


def _symbol_month(symbol: str) -> Tuple[int, int]:
    """(year, month) of an SR3-style quarterly symbol, e.g. SFRZ26 -> (2026, 12)."""
    code, yy = symbol[-3], int(symbol[-2:])
    return 2000 + yy, _MONTH_CODE.index(code) + 1


def ics_blend_contracts(symbol: str) -> Tuple[str, str]:
    """The two ZQ contracts of the CME FF-vs-SR3 ICS blend for one quarterly.

    Per the spread design, the FF leg is the next two contract months after
    the SR3 quarter month: SR3Z26 -> (ZQF27, ZQG27).
    """
    y, m = _symbol_month(symbol)
    out = []
    for k in (1, 2):
        ym, yy = m + k, y
        if ym > 12:
            ym, yy = ym - 12, yy + 1
        out.append(f"ZQ{_MONTH_CODE[ym - 1]}{yy % 100:02d}")
    return out[0], out[1]


def ics_spread_bp(sr3_price: float, ff_prices: Sequence[float]) -> float:
    """CME quoting: (average FF price) - SR3 price, in bp (= SOFR - FF rate)."""
    return (float(np.mean(ff_prices)) - sr3_price) * 100.0


def compounding_wedge_bp(avg_rate_pct: float, days: int) -> float:
    """Daily-compounded annualized rate minus the arithmetic average, act/360.

    SR3 settles on compounded SOFR; ZQ on the arithmetic EFFR average. At a
    flat rate r over D calendar days the compounded annualized rate exceeds
    the average by ~ r^2 (D-1)/720; computed exactly here (flat-path
    approximation of the true business-day compounding).
    """
    r = avg_rate_pct / 100.0
    comp = ((1.0 + r / 360.0) ** days - 1.0) * 360.0 / days
    return (comp - r) * 1e4


def window_level_weights(
    meeting_effectives: Sequence[datetime.date],
    start: datetime.date,
    end: datetime.date,
) -> np.ndarray:
    """Day weight of each policy level over ``[start, end)``.

    Level 0 rules before the first meeting; level k rules on
    ``[effective_k, effective_{k+1})``. Returns ``n_meetings + 1`` weights
    summing to 1.
    """
    total = (end - start).days
    if total <= 0:
        raise ValueError("empty window")
    effs: List[datetime.date] = sorted(meeting_effectives)
    bounds = [datetime.date.min] + effs + [datetime.date.max]
    w = np.zeros(len(effs) + 1)
    for k in range(len(effs) + 1):
        lo = max(start, bounds[k])
        hi = min(end, bounds[k + 1])
        w[k] = max(0, (hi - lo).days) / total
    return w


def proxy_wedge_bp(ladder: Sequence[MeetingLattice], symbol: str) -> float:
    """Expected (blend rate - true window-average rate) implied by one lattice.

    Both are deterministic functions of the same meeting jumps: the two blend
    months and the reference window weight the post-meeting levels
    differently. Positive means the ICS blend sits ABOVE the true quarter
    average (it overweights late-window levels when jumps are positive).
    """
    from MDP.STIRFutures._sofr_option_contracts import quarterly_reference_window

    S, E = quarterly_reference_window(symbol)
    effs = [m.effective for m in ladder]
    jumps = np.array([m.jump_bp for m in ladder])
    cum = np.concatenate([[0.0], np.cumsum(jumps)])          # level k in bp

    w_win = window_level_weights(effs, S, E)
    month_ws = []
    for c in ics_blend_contracts(symbol):
        y, m = _symbol_month(c)
        first = datetime.date(y, m, 1)
        nxt = datetime.date(y + (m == 12), m % 12 + 1, 1)
        month_ws.append(window_level_weights(effs, first, nxt))
    w_blend = 0.5 * (month_ws[0] + month_ws[1])
    return float(np.dot(w_blend - w_win, cum))


def ff_conditional_atoms(
    as_of: datetime.date,
    symbol: str,
    ladder: Sequence[MeetingLattice],
    base_rate_pct: float,
    *,
    move_size_bp: float = 25.0,
):
    """The FF-side conditional settlement distribution at ABSOLUTE rates.

    Same resolved/unresolved split as the option-side atoms, but anchored at
    the current overnight level plus the lattice's expected path — NOT
    mean-pinned to the option forward. The gap between this distribution's
    mean and the option forward is the (lattice-consistent) ICS level.

    Returns ``(rates_pct, probs, smear_bp, mean_pct, cm)`` where ``smear_bp``
    is the raw unresolved-meeting smear (no basis noise added).
    """
    cm = split_meetings(as_of, symbol, ladder, move_size_bp=move_size_bp)
    if cm is None:
        return None
    eng = AtomEngine(cm, move_size_bp=move_size_bp)
    rel, probs = eng.rates_probs(0.0)            # mean-pinned about zero

    from MDP.STIRFutures._sofr_option_contracts import quarterly_reference_window
    S, E = quarterly_reference_window(symbol)
    total = (E - S).days
    mean_shift_bp = 0.0
    for m in ladder:
        if m.effective <= as_of or m.effective >= E:
            continue
        w = 1.0 if m.effective <= S else (E - m.effective).days / total
        if w > 0.0:
            mean_shift_bp += w * m.jump_bp       # resolved AND unresolved
    mean = base_rate_pct + mean_shift_bp / 100.0
    return mean + rel, probs, float(np.sqrt(cm.unresolved_var_bp2)), mean, cm

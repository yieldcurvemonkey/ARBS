"""Convergence-trade construction for the fly-vs-vol gap G = fly - median-path fly.

G is the framework's basis object. It converges to zero mechanically: as each
leg's option expiry arrives its RND collapses onto the futures price, so
(mean - median) retires leg by leg on a known schedule. Nothing *arbitrages* G
to zero, though - it converges because uncertainty resolves, so the position
collecting the convergence carries the tail risk in the interim. The basis is
the risk premium.

Attribution: G decomposes exactly as

    tail_rent = skew_G + fit_residual
    skew_G    = -mm_front + 2*mm_belly - mm_back,   mm_i = (mean_i - median_i) bp

Expression (``convergence_package``): trade the hike-side wings in the
-1/+2/-1 pattern (or the dominant leg only), delta-hedged with futures. For
long-G (G below target): sell front/back wings, buy the belly wing. The
futures delta hedge - not an outright 500-lot fly - is the linear leg of the
trade; rehedged daily it removes first-order exposure to which meeting moves.
"""
from __future__ import annotations

import dataclasses
import datetime
from typing import Mapping, Optional, Sequence, Tuple

from RVUtils.FlyVsVol._types import FlySnapshot

__all__ = [
    "SkewAttribution",
    "WingQuote",
    "WingLeg",
    "ConvergencePackage",
    "skew_attribution",
    "convergence_package",
]


@dataclasses.dataclass(frozen=True)
class SkewAttribution:
    label: str
    mm_front_bp: float
    mm_belly_bp: float
    mm_back_bp: float
    contrib_front_bp: float
    contrib_belly_bp: float
    contrib_back_bp: float
    skew_g_bp: float
    fit_residual_bp: float
    tail_rent_bp: float
    dominant_leg: str


@dataclasses.dataclass(frozen=True)
class WingQuote:
    """One listed wing option: premium in bp of price, delta_abs in percent."""

    symbol: str
    right: str
    strike_rate: float
    premium_bp: float
    delta_abs: float


@dataclasses.dataclass(frozen=True)
class WingLeg:
    side: str  # "sell" | "buy"
    quote: WingQuote
    lots: int
    premium_bp_total: float  # lots * premium_bp, sign-agnostic (see package net)
    hedge_futures_lots: float  # signed futures (price terms) to trade for delta-flat


@dataclasses.dataclass(frozen=True)
class ConvergencePackage:
    fly_label: str
    as_of: Optional[datetime.date]
    direction: str  # "long_G" | "short_G"
    legs: Tuple[WingLeg, ...]
    attribution: SkewAttribution
    current_g_bp: float
    target_g_bp: float
    expected_reversion_bp: float
    net_premium_bp_lots: float  # + = net premium collected, in bp x lots ($25/unit)
    schedule: Tuple[Tuple[str, Optional[datetime.date], float], ...]


def skew_attribution(snapshot: FlySnapshot) -> SkewAttribution:
    """Exact decomposition of tail_rent into per-leg skew + fit residual."""
    mm = [(m.mean - m.median) * 100 for m in snapshot.legs]
    contribs = (-mm[0], 2 * mm[1], -mm[2])
    skew_g = sum(contribs)
    by_symbol = {m.symbol: c for m, c in zip(snapshot.legs, contribs)}
    return SkewAttribution(
        label=snapshot.fly.label,
        mm_front_bp=mm[0],
        mm_belly_bp=mm[1],
        mm_back_bp=mm[2],
        contrib_front_bp=contribs[0],
        contrib_belly_bp=contribs[1],
        contrib_back_bp=contribs[2],
        skew_g_bp=skew_g,
        fit_residual_bp=snapshot.fly_bp - snapshot.fly_mean_bp,
        tail_rent_bp=snapshot.tail_rent_bp,
        dominant_leg=max(by_symbol, key=lambda s: abs(by_symbol[s])),
    )


def _pick_quote(quotes: Sequence[WingQuote], target_rate: float, right: str) -> WingQuote:
    candidates = [q for q in quotes if q.right == right]
    if not candidates:
        raise ValueError(f"no {right!r}-side wing quotes supplied")
    return min(candidates, key=lambda q: abs(q.strike_rate - target_rate))


def convergence_package(
    snapshot: FlySnapshot,
    wing_quotes: Mapping[str, Sequence[WingQuote]],
    *,
    scale_lots: int = 100,
    target_g_bp: Optional[float] = None,
    target_percentile: float = 90.0,
    mode: str = "curvature",
    wing_right: str = "P",
) -> ConvergencePackage:
    """Build the delta-hedged wing package that is long (or short) the gap G.

    ``target_g_bp``: where you expect G to converge - 0.0 (terminal, default)
    or e.g. the rolling mean for a z-score reversion entry. Direction is
    inferred: target above current G -> long_G -> sell front/back hike wings,
    buy belly (short_G flips every side). ``mode``: "curvature" trades all
    three legs 1:2:1; "dominant" trades only the largest |contribution| leg.
    ``wing_right="P"`` selects price-puts (the hike-side wing). Strikes are
    chosen nearest each leg's ``target_percentile`` rate. Hedge lots assume
    ``delta_abs`` percent per lot; selling a price-put leaves positive price
    delta, hedged by selling futures (negative ``hedge_futures_lots``).
    """
    att = skew_attribution(snapshot)
    current_g = snapshot.tail_rent_bp
    target = 0.0 if target_g_bp is None else float(target_g_bp)
    long_g = target >= current_g
    direction = "long_G" if long_g else "short_G"

    # desired mm exposure per leg for long_G: (-1, +2, -1) -> sell/buy/sell hike wing
    base = {
        snapshot.legs[0].symbol: ("sell", 1),
        snapshot.legs[1].symbol: ("buy", 2),
        snapshot.legs[2].symbol: ("sell", 1),
    }
    if mode == "dominant":
        w = {s: v for s, v in base.items() if s == att.dominant_leg}
        w = {s: (side, 1) for s, (side, _) in w.items()}
    elif mode == "curvature":
        w = base
    else:
        raise ValueError(f"mode must be 'curvature' or 'dominant', got {mode!r}")

    legs = []
    net_premium = 0.0
    for m in snapshot.legs:
        if m.symbol not in w:
            continue
        side, mult = w[m.symbol]
        if not long_g:
            side = "buy" if side == "sell" else "sell"
        quote = _pick_quote(
            wing_quotes.get(m.symbol, ()), m.percentile(target_percentile), wing_right
        )
        lots = int(round(scale_lots * mult))
        # position price-delta per lot: short put -> +delta_abs/100; long put -> -.
        pos_delta = (1 if side == "sell" else -1) * lots * quote.delta_abs / 100.0
        legs.append(
            WingLeg(
                side=side,
                quote=quote,
                lots=lots,
                premium_bp_total=lots * quote.premium_bp,
                hedge_futures_lots=-pos_delta,
            )
        )
        net_premium += (1 if side == "sell" else -1) * lots * quote.premium_bp

    contrib_by_symbol = {
        snapshot.legs[0].symbol: att.contrib_front_bp,
        snapshot.legs[1].symbol: att.contrib_belly_bp,
        snapshot.legs[2].symbol: att.contrib_back_bp,
    }
    schedule = tuple(
        sorted(
            ((m.symbol, m.option_expiry, contrib_by_symbol[m.symbol]) for m in snapshot.legs),
            key=lambda t: (t[1] is None, t[1]),
        )
    )
    return ConvergencePackage(
        fly_label=snapshot.fly.label,
        as_of=snapshot.as_of,
        direction=direction,
        legs=tuple(legs),
        attribution=att,
        current_g_bp=current_g,
        target_g_bp=target,
        expected_reversion_bp=target - current_g,
        net_premium_bp_lots=net_premium,
        schedule=schedule,
    )

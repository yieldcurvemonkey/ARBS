"""Trade flag emission per spec §3.

Four trade families:
1. Vol cone (variance RV) — sell SR3 straddle when residual_ratio top-decile,
   buy when bottom-decile. Hedge first-moment via FF spread.
2. Skew — flag when SR3 RR mismatches FedWatch directional lean after
   floor adjustment. Sign + magnitude check on RND skew.
3. Tail — flag when SR3 wing tail mass is in top decile relative to its
   own history within regime. ZQ tree mechanically zero, so any large
   SR3 tail value is informative.
4. Cross-quarter — flag when residual variance term-structure inverts /
   steepens beyond what scheduled meeting density explains. Requires ≥3
   contracts in the snapshot.
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence

from RVUtils.SR3ZQDistributionScreener._types import (
    DistributionScreenerConfig,
    RegimeBucket,
    TradeFlag,
    TradeFlagKind,
)


def _decile(value: float, *, lo: float, hi: float) -> int:
    """Map ``value`` to a 1–10 decile bucket between lo and hi."""
    if not math.isfinite(value):
        return 5
    if hi <= lo:
        return 5
    pct = max(0.0, min(1.0, (value - lo) / (hi - lo)))
    return min(10, max(1, int(pct * 10) + 1))


def signal_vol_cone(
    *,
    residual_ratio: float,
    regime: RegimeBucket,
    config: DistributionScreenerConfig,
) -> Optional[TradeFlag]:
    """Spec §3.1 — variance RV.

    Stress regime: residual_ratio in top decile ⇒ sell SR3 straddle (vol rich).
    Calm regime: residual_ratio bottom decile ⇒ buy SR3 straddle (vol cheap).
    """
    if not math.isfinite(residual_ratio):
        return None

    if regime == RegimeBucket.STRESS:
        # Stress baseline: residual_ratio p25 ≈ 84, p75 ≈ 130, max ≈ 165
        # Top decile ≈ ratio > 130
        if residual_ratio >= 130.0:
            decile = _decile(residual_ratio, lo=84.0, hi=200.0)
            return TradeFlag(
                kind=TradeFlagKind.VOL_CONE,
                severity_decile=decile,
                direction="sell_vol",
                rationale=(
                    f"Stress regime, residual_ratio={residual_ratio:.1f} (p>90 within stress) "
                    "— SR3 ATM vol over-rich vs day-weighted ZQ tree + drift"
                ),
                severity_value=residual_ratio,
                severity_threshold=130.0,
            )

    if regime == RegimeBucket.CALM:
        # Calm baseline: residual_ratio p25 ≈ 28, p75 ≈ 30
        # Bottom decile ≈ ratio < 24
        if residual_ratio < 20.0:
            return TradeFlag(
                kind=TradeFlagKind.VOL_CONE,
                severity_decile=_decile(20.0 - residual_ratio, lo=0.0, hi=20.0),
                direction="buy_vol",
                rationale=(
                    f"Calm regime, residual_ratio={residual_ratio:.1f} (p<10 within calm) "
                    "— SR3 ATM vol cheap vs day-weighted ZQ tree + drift"
                ),
                severity_value=residual_ratio,
                severity_threshold=20.0,
            )

    return None


def signal_skew(
    *,
    skew: float,
    regime: RegimeBucket,
    config: DistributionScreenerConfig,
) -> Optional[TradeFlag]:
    """Spec §3.2 — skew (directional disagreement).

    Triggers when RND skew sign / magnitude is regime-extreme:
        - Calm with positive skew (typical) but skew < calm p25 ⇒ skew dovish-cheap
        - Pivot or calm with skew < -1.5 ⇒ heavily directional move priced (long-rate)

    Suppress signal in stress regime (mode count varies, floor effect dominates).
    """
    if not math.isfinite(skew):
        return None

    # Suppress in stress
    if regime == RegimeBucket.STRESS:
        return None

    # Heavy negative skew = market priced rate cut directional move
    if skew <= -1.5:
        return TradeFlag(
            kind=TradeFlagKind.SKEW,
            severity_decile=min(10, _decile(-skew, lo=1.0, hi=3.5)),
            direction="long_call_skew_take_dovish_view",
            rationale=(
                f"RND skew={skew:.2f} (heavily dovish) — market pricing rate-cut "
                "directional move; FedWatch first-moment likely confirms"
            ),
            severity_value=skew,
            severity_threshold=-1.5,
        )

    # Calm with skew below normal calm range (skew approaching neutral)
    if regime == RegimeBucket.CALM and skew < 0.0:
        return TradeFlag(
            kind=TradeFlagKind.SKEW,
            severity_decile=_decile(-skew, lo=0.0, hi=1.0),
            direction="sell_call_skew",
            rationale=(
                f"Calm regime but skew={skew:.2f} (below calm p25=+0.20) — "
                "SR3 RR has dovish lean atypical for calm; consider call-skew sale"
            ),
            severity_value=skew,
            severity_threshold=0.0,
        )

    return None


def signal_tail(
    *,
    tail_upper_50bp: float,
    tail_lower_50bp: float,
    tail_upper_100bp: float,
    tail_lower_100bp: float,
    regime: RegimeBucket,
    config: DistributionScreenerConfig,
) -> Optional[TradeFlag]:
    """Spec §3.3 — tail (surprise component).

    SR3 wing > 15% at ±50bp ⇒ tail rich, candidate sell-wing OR confirm
    stress hedge. Tail+100bp > 5% in stress = real probability of large
    move that ZQ tree mechanically zeros.
    """
    max_tail_50 = max(tail_upper_50bp, tail_lower_50bp)
    max_tail_100 = max(tail_upper_100bp, tail_lower_100bp)
    if not math.isfinite(max_tail_50):
        return None

    threshold = config.tail_upper_50bp_threshold

    if max_tail_50 >= threshold:
        # Direction: which side is heavier?
        side = "upper" if tail_upper_50bp > tail_lower_50bp else "lower"
        if regime == RegimeBucket.STRESS:
            direction = "long_tail_stress_hedge"
            rationale = (
                f"Stress regime, max(tail±50bp)={max_tail_50:.3f} (≥15%); "
                f"{side} side heavier — SR3 wings price real surprise probability "
                "ZQ tree mechanically zeros. Confirm stress hedge entry."
            )
        else:
            direction = f"sell_{side}_wing_or_size_carefully"
            rationale = (
                f"{regime.value} regime, max(tail±50bp)={max_tail_50:.3f} "
                "(>15%, regime-atypical) — SR3 wings extended without "
                "stress backdrop; consider wing sale unless catalyst inside expiry."
            )
        decile = _decile(max_tail_50, lo=threshold, hi=0.40)
        return TradeFlag(
            kind=TradeFlagKind.TAIL,
            severity_decile=decile,
            direction=direction,
            rationale=rationale,
            severity_value=max_tail_50,
            severity_threshold=threshold,
        )

    return None


def signal_cross_quarter(
    *,
    residual_ratios_by_contract: Sequence[float],
    regime: RegimeBucket,
    config: DistributionScreenerConfig,
) -> Optional[TradeFlag]:
    """Spec §3.4 — cross-quarter residual term structure.

    Need ≥3 contracts. Signal fires when residual ratios are inverted
    (front > back) by > 2× — front contract carries more relative residual
    than back, suggesting SR3 vol mispriced at the front.
    """
    if len(residual_ratios_by_contract) < config.cross_quarter_min_contracts:
        return None

    finite_ratios = [r for r in residual_ratios_by_contract if math.isfinite(r)]
    if len(finite_ratios) < 3:
        return None

    front = finite_ratios[0]
    back = finite_ratios[-1]
    if back <= 0:
        return None

    inversion = front / back

    if inversion >= 2.0:
        return TradeFlag(
            kind=TradeFlagKind.CROSS_QUARTER,
            severity_decile=_decile(inversion, lo=2.0, hi=10.0),
            direction="sell_front_vol_buy_back_vol",
            rationale=(
                f"Residual ratio inversion: front={front:.1f}, back={back:.1f} "
                f"(inversion={inversion:.1f}×) — front SR3 over-rich relative to back; "
                "calendar straddle spread expression"
            ),
            severity_value=inversion,
            severity_threshold=2.0,
        )
    if back > 0 and inversion <= 0.5:
        return TradeFlag(
            kind=TradeFlagKind.CROSS_QUARTER,
            severity_decile=_decile(1.0 / inversion, lo=2.0, hi=10.0),
            direction="buy_front_vol_sell_back_vol",
            rationale=(
                f"Residual ratio steepening: front={front:.1f}, back={back:.1f} "
                f"(steep={1.0/inversion:.1f}×) — back SR3 over-rich relative to front; "
                "calendar straddle spread expression"
            ),
            severity_value=inversion,
            severity_threshold=0.5,
        )

    return None


def compute_signals(
    *,
    residual_ratio: float,
    skew: float,
    tail_upper_50bp: float,
    tail_lower_50bp: float,
    tail_upper_100bp: float,
    tail_lower_100bp: float,
    regime: RegimeBucket,
    residual_ratios_by_contract: Sequence[float] = (),
    config: Optional[DistributionScreenerConfig] = None,
    lambda_wing: float = float("nan"),
    lambda_prior: float = float("nan"),
    lambda_z: float = float("nan"),
    hard_violation_bp2: float = 0.0,
    lambda_atom_spread: float = float("nan"),
) -> List[TradeFlag]:
    """Compute all four trade signals. Returns list of triggered flags."""
    if config is None:
        config = DistributionScreenerConfig()

    flags: List[TradeFlag] = []

    f = signal_vol_cone(
        residual_ratio=residual_ratio, regime=regime, config=config
    )
    if f is not None:
        flags.append(f)

    f = signal_skew(skew=skew, regime=regime, config=config)
    if f is not None:
        flags.append(f)

    f = signal_tail(
        tail_upper_50bp=tail_upper_50bp,
        tail_lower_50bp=tail_lower_50bp,
        tail_upper_100bp=tail_upper_100bp,
        tail_lower_100bp=tail_lower_100bp,
        regime=regime,
        config=config,
    )
    if f is not None:
        flags.append(f)

    f = signal_cross_quarter(
        residual_ratios_by_contract=residual_ratios_by_contract,
        regime=regime,
        config=config,
    )
    if f is not None:
        flags.append(f)

    # Emitted last and gated on its own diagnostics: with no lambda inputs the defaults are
    # NaN and this is a no-op, so every existing caller is unaffected.
    f = signal_lambda_dependence(
        lambda_wing=lambda_wing,
        lambda_prior=lambda_prior,
        lambda_z=lambda_z,
        hard_violation_bp2=hard_violation_bp2,
        lambda_atom_spread=lambda_atom_spread,
    )
    if f is not None:
        flags.append(f)

    return flags


def signal_lambda_dependence(
    *,
    lambda_wing: float,
    lambda_prior: float,
    lambda_z: float,
    hard_violation_bp2: float = 0.0,
    lambda_atom_spread: float = float("nan"),
    z_threshold: float = 1.0,
    atom_spread_max: float = 0.60,
) -> Optional[TradeFlag]:
    """The copula coordinate against a prior. See RVUtils.SR3ZQDistributionScreener._copula.

    Two tiers, and only two, because any payoff LINEAR in the move count is copula-free:
    there is no copula-free arbitrage between the ZQ strip and SR3 options, so lambda is an
    unobservable the market must price rather than a mispricing to converge.

    * HARD -- ``hard_violation_bp2 != 0`` means the RND's meeting-attributed variance lies
      outside ``[Var_min, Var_com]``, i.e. outside what ANY coupling of these marginals can
      produce. That is a genuine static arbitrage and it dominates everything below.
    * SOFT -- inside the interval, lambda versus the prior is a VIEW. Fires on the
      standardised ``lambda_z``, never on the raw level, because the raw level is
      mechanically confounded with time to expiry and with how many meetings are still
      unresolved.

    A wide ``lambda_atom_spread`` means the atoms disagree about lambda -- the RND has left
    the one-parameter family, so a single headline lambda is an average of things that
    contradict each other. The signal is suppressed rather than emitted with a caveat.
    """
    if math.isfinite(hard_violation_bp2) and abs(hard_violation_bp2) > 0.0:
        return TradeFlag(
            kind=TradeFlagKind.LAMBDA_ARBITRAGE,
            severity_decile=10,
            direction="buy_wings" if hard_violation_bp2 < 0 else "sell_wings",
            rationale=(
                f"RND meeting variance is {abs(hard_violation_bp2):.0f}bp^2 outside the "
                f"[min-variance, comonotone] interval: no coupling of the ZQ marginals can "
                f"produce it, so this is a static arbitrage, not a view"
            ),
            severity_value=float(hard_violation_bp2),
            severity_threshold=0.0,
        )

    if not math.isfinite(lambda_wing) or not math.isfinite(lambda_z):
        return None
    if math.isfinite(lambda_atom_spread) and lambda_atom_spread > atom_spread_max:
        return None
    if abs(lambda_z) < float(z_threshold):
        return None

    cheap = lambda_z <= -float(z_threshold)
    return TradeFlag(
        kind=TradeFlagKind.LAMBDA_DEPENDENCE,
        severity_decile=_decile(abs(lambda_z), lo=float(z_threshold), hi=3.0),
        # Low lambda = the market prices a fat middle, so the wings are the cheap side.
        direction="buy_wings" if cheap else "sell_wings",
        rationale=(
            f"lambda_wing {lambda_wing:+.3f} vs prior {lambda_prior:+.3f} "
            f"(z {lambda_z:+.2f}): the market is pricing the Fed as "
            f"{'more independent' if cheap else 'more comonotone'} than the prior"
        ),
        severity_value=float(lambda_z),
        severity_threshold=float(z_threshold) * (-1.0 if cheap else 1.0),
    )

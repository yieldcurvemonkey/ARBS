"""Hump-shaped confidence model (spec section 6e)."""
from __future__ import annotations

import dataclasses
import math

from SDRUtils.stir_flow import config


@dataclasses.dataclass
class TickStats:
    median_tick_bps: float | None
    disp_jns: float | None
    futures_tick_bps: float


@dataclasses.dataclass
class ConfidenceDecision:
    confidence: str
    p_flip: float | None = None
    use_tick_rule: bool = False
    curve_suspect_trade: bool = False


def _tick(stats: TickStats) -> float:
    if stats.median_tick_bps is not None and stats.median_tick_bps > 0:
        return stats.median_tick_bps
    return stats.futures_tick_bps


def sigma_mid(stats: TickStats) -> float:
    half = _tick(stats) / 2.0
    if stats.disp_jns is not None and stats.disp_jns > half:
        return math.sqrt(stats.disp_jns ** 2 - half ** 2)
    return stats.futures_tick_bps / 2.0


def p_flip(deviation_bps: float, sigma: float) -> float:
    if sigma <= 0:
        return 0.0
    z = abs(deviation_bps) / sigma
    return 1.0 - 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _tier(p: float) -> str:
    if p < config.P_FLIP_HIGH:
        return "HIGH"
    if p < config.P_FLIP_MEDIUM:
        return "MEDIUM"
    return "LOW"


def score_on_market(s2m_bps: float, stats: TickStats, is_block: bool) -> ConfidenceDecision:
    s = _tick(stats)
    dev = abs(s2m_bps)
    if dev > config.HUMP_OUTLIER_MULT * s:
        return ConfidenceDecision(
            confidence="MEDIUM" if is_block else "LOW",
            curve_suspect_trade=True,
        )
    if dev < config.AMBIGUOUS_FRAC * (s / 2.0):
        return ConfidenceDecision(confidence="LOW", use_tick_rule=True)
    p = p_flip(dev, sigma_mid(stats))
    return ConfidenceDecision(confidence=_tier(p), p_flip=p)


def score_off_market(charge_bps: float, stats: TickStats) -> ConfidenceDecision:
    s = _tick(stats)
    dev = abs(charge_bps)
    if dev > config.HUMP_OUTLIER_MULT * s:
        return ConfidenceDecision(confidence="LOW", curve_suspect_trade=True)
    p = p_flip(dev, sigma_mid(stats))
    return ConfidenceDecision(confidence=_tier(p), p_flip=p)


def apply_tick_rule(rate_pct, prev_rate_pct):
    if prev_rate_pct is None or rate_pct is None:
        return None
    if rate_pct > prev_rate_pct:
        return "RECEIVED"
    if rate_pct < prev_rate_pct:
        return "PAID"
    return None

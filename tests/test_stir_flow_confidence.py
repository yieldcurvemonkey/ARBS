import math
import pytest
from SDRUtils.stir_flow.confidence import (
    ConfidenceDecision, TickStats, apply_tick_rule, p_flip,
    score_off_market, score_on_market, sigma_mid,
)


def test_sigma_mid_decomposition_and_fallback():
    # DispJNS^2 = (S/2)^2 + sigma^2 -> sigma = sqrt(0.3^2 - 0.25^2)
    s = TickStats(median_tick_bps=0.5, disp_jns=0.3, futures_tick_bps=0.5)
    assert sigma_mid(s) == pytest.approx(math.sqrt(0.09 - 0.0625), rel=1e-6)
    # thin sample -> futures_tick/2
    s2 = TickStats(median_tick_bps=None, disp_jns=None, futures_tick_bps=0.5)
    assert sigma_mid(s2) == 0.25


def test_p_flip_boundaries():
    assert p_flip(0.0, 0.25) == pytest.approx(0.5)
    assert p_flip(1.0, 0.25) < 0.001
    assert 0.0 < p_flip(0.25, 0.25) < 0.5


def test_hump_outlier_capped_low_and_flagged():
    s = TickStats(0.5, 0.3, 0.5)
    d = score_on_market(3.11, s, is_block=False)   # 6x the tick
    assert d.confidence == "LOW" and d.curve_suspect_trade
    d_blk = score_on_market(3.11, s, is_block=True)
    assert d_blk.confidence == "MEDIUM" and d_blk.curve_suspect_trade


def test_ambiguous_zone_requests_tick_rule():
    s = TickStats(0.5, 0.3, 0.5)
    d = score_on_market(0.05, s, is_block=False)   # < 0.5*(S/2)=0.125
    assert d.use_tick_rule and d.confidence == "LOW"


def test_main_zone_pflip_tiers():
    s = TickStats(0.5, 0.3, 0.5)      # sigma ~ 0.166
    d = score_on_market(0.18, s, is_block=False)   # z~1.08 -> P~0.14 -> MEDIUM
    assert d.confidence == "MEDIUM" and not d.use_tick_rule
    d_hi = score_on_market(0.45, s, is_block=False)  # z~2.7 -> P<0.05 -> HIGH
    assert d_hi.confidence == "HIGH"


def test_off_market_textbook_print_not_punished():
    # POC correction: 0.18bp charge vs 0.5bp FF tick was wrongly LOW before
    s = TickStats(0.5, 0.3, 0.5)
    d = score_off_market(0.18, s)
    assert d.confidence == "MEDIUM"


def test_off_market_outlier_charge_flagged():
    s = TickStats(0.5, 0.3, 0.5)
    d = score_off_market(3.0, s)      # > 3*S
    assert d.confidence == "LOW" and d.curve_suspect_trade


def test_apply_tick_rule():
    assert apply_tick_rule(3.715, 3.713) == "RECEIVED"
    assert apply_tick_rule(3.713, 3.715) == "PAID"
    assert apply_tick_rule(3.713, 3.713) is None
    assert apply_tick_rule(3.713, None) is None

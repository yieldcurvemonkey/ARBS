import datetime
import numpy as np

from RVUtils.ImpliedDistribution import RNDInput
from RVUtils.ImpliedDistribution._breeden_litzenberger import extract_rnd_breeden_litzenberger


def _ill_conditioned_input_with_concave_calls() -> RNDInput:
    """Calls that violate convexity → spline 2nd derivative goes negative."""
    strikes = np.linspace(95.0, 98.0, 7)
    # Concave premium curve violates no-arbitrage; spline d²C/dK² < 0 in interior.
    premiums = np.array([0.1, 0.2, 0.5, 1.5, 0.5, 0.2, 0.1])
    return RNDInput(
        symbol="SYNTH", as_of=datetime.date(2026, 4, 28),
        forward_price=96.5, forward_rate=3.5, time_to_expiry=0.5,
        expiry_date=datetime.date(2026, 12, 14), discount_factor=1.0,
        strikes_price=strikes, call_premiums=premiums,
        strike_source="test_concave",
    )


def test_extract_emits_warning_when_negative_density_clipped():
    result = extract_rnd_breeden_litzenberger(_ill_conditioned_input_with_concave_calls())
    matching = [w for w in result.warnings if "negative density" in w.lower()]
    assert len(matching) >= 1, f"expected negative-density warning, got: {result.warnings}"


def test_extract_negative_density_warning_includes_percentage():
    """Warning text should include the percentage of mass clipped."""
    result = extract_rnd_breeden_litzenberger(_ill_conditioned_input_with_concave_calls())
    matching = [w for w in result.warnings if "negative density" in w.lower()]
    assert len(matching) == 1
    assert "%" in matching[0]


def test_rate_floor_truncation_produces_warning():
    # Forward near 0% with wide vol → density tail extends below 0%
    strikes = np.linspace(99.0, 101.0, 21)  # rates: -1% to 1%
    fwd_rate = 0.10  # 10 bp
    fwd_price = 100 - fwd_rate
    # Wide bell-shaped premium curve so tail leaks below price=100 (rate<0)
    sigma = 1.0
    premiums = np.maximum(fwd_price - strikes, 0.0) + sigma * np.exp(-((strikes - fwd_price) ** 2) / 2.0)
    rnd_input = RNDInput(
        symbol="LOWRATE", as_of=datetime.date(2026, 4, 28),
        forward_price=fwd_price, forward_rate=fwd_rate, time_to_expiry=0.5,
        expiry_date=datetime.date(2026, 12, 14), discount_factor=1.0,
        strikes_price=strikes, call_premiums=premiums,
        strike_source="test_lowrate",
    )
    result = extract_rnd_breeden_litzenberger(rnd_input, rate_floor=0.0)
    matching = [w for w in result.warnings if "floor" in w.lower()]
    assert len(matching) >= 1, f"expected rate-floor warning, got: {result.warnings}"

import datetime
import numpy as np
from unittest.mock import patch

from RVUtils.ImpliedDistribution import RNDInput, FedScenarioConfig
from RVUtils.ImpliedDistribution._gaussian_mixture import extract_gaussian_mixture


def _input() -> RNDInput:
    strikes = np.linspace(95.0, 98.0, 13)
    fwd = 96.5
    premiums = np.maximum(fwd - strikes, 0.0) + 0.3 * np.exp(-((strikes - fwd) ** 2) / 0.5)
    return RNDInput(
        symbol="SFRZ26", as_of=datetime.date(2026, 4, 28),
        forward_price=fwd, forward_rate=100 - fwd, time_to_expiry=0.5,
        expiry_date=datetime.date(2026, 12, 14), discount_factor=1.0,
        strikes_price=strikes, call_premiums=premiums, strike_source="test",
    )


def test_gm_non_convergence_emits_warning():
    cfg = FedScenarioConfig.default_sofr_scenarios(current_rate=3.5)
    import scipy.optimize as _scipy_optimize
    real_minimize = _scipy_optimize.minimize

    def fake_minimize(*args, **kwargs):
        # Run the real optimizer once, then mark success=False on result
        result = real_minimize(*args, **kwargs)
        result.success = False
        result.message = "test forced failure"
        return result

    with patch("RVUtils.ImpliedDistribution._gaussian_mixture.minimize", side_effect=fake_minimize):
        gm = extract_gaussian_mixture(_input(), cfg.scenarios)

    assert any("converge" in w.lower() or "fail" in w.lower() for w in gm.warnings), \
        f"expected non-convergence warning, got: {gm.warnings}"


def test_gm_success_no_convergence_warning():
    cfg = FedScenarioConfig.default_sofr_scenarios(current_rate=3.5)
    gm = extract_gaussian_mixture(_input(), cfg.scenarios)
    if gm.optimization_success:
        non_conv = [w for w in gm.warnings if "converge" in w.lower()]
        assert len(non_conv) == 0

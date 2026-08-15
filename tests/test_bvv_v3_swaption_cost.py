"""V3's swaption round-trip cost was charged at one ten-thousandth of its intended size.

The pre-registration required "a separate swaption round-trip cost in normal-bp of vol -- an RV
trade costed on one leg only flatters itself". `v3.py` charged

    cost_mult * |ratio| * ann * (swaption_cost_vol_bp / 1e4) * sqrt(T / 2pi)

but this module is bp-native BY DECLARATION -- `atmf_normal_gamma`'s own docstring says so -- and
`swaption_annuity` is "$ per bp on $1mm notional" (`v3_panel.py:249`). So the `/1e4` divides by
10,000 a second time. Measured against the module's own `normal_receiver_price`, the ATM Bachelier
value is exactly `ann * vol_bp * sqrt(T/2pi)` at ratio 1.00000000, which is the vega the cost is
supposed to be expressed in.

Effect on the published V3 grid, at `swaption_cost_vol_bp = 0.25`:

    root   as charged   should have been   vs the basis leg's own fees
    UB       $0.63          $6,332          1.4% of $468,750
    ZB       $2.39         $23,948          2.3% of $1,062,500
    ZN       $2.22         $22,203          1.5% of $1,531,250

The verdict cannot flip -- the correction is strictly negative-going and the grid already had 0 of
198 profitable cells with best Sharpe -0.230 against E[max | null] 0.638 -- but the published
"agrees to within $2.40 on $1.5m" is now an artifact of the same defect, because the QDB comparison
folded in the swaption's marks and never charged its cost.
"""

from __future__ import annotations

import math

import pytest

from RVUtils.BasisVsVol.v3 import normal_receiver_price


def _cost(ann_usd_per_bp: float, cost_vol_bp: float, t_years: float, ratio: float = 1.0, mult: float = 1.0) -> float:
    """The charge as v3.py now computes it."""
    return mult * abs(ratio) * ann_usd_per_bp * cost_vol_bp * math.sqrt(max(t_years, 0.0) / (2.0 * math.pi))


def test_the_charge_is_the_modules_own_atm_price_at_the_cost_vol():
    """CALIBRATION and the whole argument in one assertion.

    If the cost is "a round trip in normal bp of vol", it must equal what this module's pricer says
    an ATM option is worth at that many bp of vol. That fixes the units with no appeal to
    convention.
    """
    ann, t = 1673.05, 0.1
    for cost_vol_bp in (0.25, 1.0, 5.0):
        atm_value = normal_receiver_price(300.0, 300.0, cost_vol_bp, t, ann)
        assert _cost(ann, cost_vol_bp, t) == pytest.approx(atm_value, rel=1e-12)


def test_the_old_form_was_ten_thousand_times_too_small():
    ann, t, cost_vol_bp = 1673.05, 0.1, 0.25
    old = 1.0 * ann * (cost_vol_bp / 1e4) * math.sqrt(t / (2.0 * math.pi))
    assert _cost(ann, cost_vol_bp, t) == pytest.approx(old * 1e4, rel=1e-12)
    assert old == pytest.approx(0.005277, abs=1e-6)
    assert _cost(ann, cost_vol_bp, t) == pytest.approx(52.766586, abs=1e-5)


def test_v3_charges_the_bp_native_cost():
    """Pin the source, so the `/1e4` cannot come back as a 'unit fix'."""
    import inspect

    from RVUtils.BasisVsVol import v3

    src = inspect.getsource(v3)
    assert "cfg.swaption_cost_vol_bp / 1e4" not in src
    assert src.count("cfg.swaption_cost_vol_bp * math.sqrt(") == 2, "entry and unwind must both charge it"


def test_the_cost_scales_with_notional_and_expiry():
    """Sanity: a bigger matched notional and a longer option cost more, monotonically."""
    ann, t = 1673.05, 0.1
    assert _cost(ann, 0.25, t, ratio=2.0) == pytest.approx(2.0 * _cost(ann, 0.25, t, ratio=1.0))
    assert _cost(ann, 0.25, 0.4) > _cost(ann, 0.25, 0.1)
    assert _cost(ann, 0.25, 0.0) == 0.0

# tests/test_opa_sign_solver.py
"""Tests for OPA sign solver — brute-force + constrained + greedy."""
import pytest

from SDRUtils.packages.opa_sign_solver import (
    solve_opa_signs,
    confidence_tier,
)


class TestConfidenceTier:
    def test_exact(self):
        assert confidence_tier(50.0) == "EXACT"

    def test_tight(self):
        assert confidence_tier(500.0) == "TIGHT"

    def test_loose(self):
        assert confidence_tier(10000.0) == "LOOSE"

    def test_unresolved(self):
        assert confidence_tier(100000.0) == "UNRESOLVED"

    def test_boundary_exact(self):
        assert confidence_tier(99.99) == "EXACT"
        assert confidence_tier(100.01) == "TIGHT"


class TestSolveOpaSigns:
    def test_two_legs_exact_match(self):
        """Two legs whose diff equals PTP exactly."""
        result = solve_opa_signs([600.0, 500.0], ptp_value=100.0)
        assert result["residual"] < 1.0
        assert result["confidence"] == "EXACT"
        assert len(result["signs"]) == 2
        net = sum(s * v for s, v in zip(result["signs"], [600.0, 500.0]))
        assert abs(abs(net) - 100.0) < 1.0

    def test_twelve_leg_fly_case(self):
        """Real-world 12-leg fly OPA values from the June 25 trade."""
        opas = [
            13267.67310, 677255.44976, 314119.12370,
            23741.62083, 1227520.75738, 563983.19706,
            583940.98780, 46229.79335, 35390.43816,
            326319.60400, 25505.69450, 19963.57680,
        ]
        result = solve_opa_signs(opas, ptp_value=88100.0)
        assert result["residual"] < 300  # known: ~216
        assert result["confidence"] == "TIGHT"

    def test_eight_leg_mac_ladder(self):
        """Real-world 8-leg MAC ladder from July 1."""
        opas = [
            78379.0, 222414.96410, 658253.55059,
            847927.27494, 77767.0, 329324.49648,
            74086.48145, 75285.14512,
        ]
        result = solve_opa_signs(opas, ptp_value=1537032.0)
        assert result["residual"] < 15000  # known: ~11K
        assert result["confidence"] == "LOOSE"

    def test_constrained_solve(self):
        """Legs in the same rate/tenor group must share signs."""
        opas = [100.0, 200.0, 100.0, 200.0]
        groups = [0, 1, 0, 1]  # legs 0,2 same group; legs 1,3 same group
        result = solve_opa_signs(opas, ptp_value=200.0, rate_tenor_groups=groups)
        assert result["constrained_signs"] is not None
        assert result["constrained_signs"][0] == result["constrained_signs"][2]
        assert result["constrained_signs"][1] == result["constrained_signs"][3]

    def test_empty_opas(self):
        result = solve_opa_signs([], ptp_value=100.0)
        assert result["signs"] == []
        assert result["confidence"] == "UNRESOLVED"

    def test_single_leg(self):
        result = solve_opa_signs([100.0], ptp_value=100.0)
        assert result["residual"] < 1.0
        assert result["signs"] == [1]

    def test_greedy_fallback_large_n(self):
        """N=26 should use greedy fallback without timeout."""
        import random
        random.seed(42)
        opas = [random.uniform(1000, 100000) for _ in range(26)]
        ptp = sum(opas) * 0.1
        result = solve_opa_signs(opas, ptp_value=ptp)
        assert result["signs"] is not None
        assert len(result["signs"]) == 26

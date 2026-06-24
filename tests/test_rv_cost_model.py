"""Tests for cost model (spec H)."""
import numpy as np
import pytest

from RVUtils.cost_model import transaction_cost_bps, structure_cost_bps


class TestTransactionCostBps:
    def test_spot_short_tenor(self):
        cost = transaction_cost_bps(tenor=2.0)
        expected = 0.25 + 0.05 * min(2.0, 30) + 0.04 * min(0.0, 10)
        assert cost == pytest.approx(expected)

    def test_long_tenor_caps_at_30(self):
        c30 = transaction_cost_bps(tenor=30.0)
        c50 = transaction_cost_bps(tenor=50.0)
        assert c30 == c50

    def test_forward_start_adds_cost(self):
        spot = transaction_cost_bps(tenor=10.0, fwd_start=0.0)
        fwd = transaction_cost_bps(tenor=10.0, fwd_start=5.0)
        assert fwd > spot


class TestStructureCostBps:
    def test_butterfly_cost(self):
        legs = [2.0, 5.0, 10.0]
        weights = [-0.5, 1.0, -0.5]
        cost = structure_cost_bps(legs, weights)
        expected = sum(abs(w) * transaction_cost_bps(t) for t, w in zip(legs, weights))
        assert cost == pytest.approx(expected)

    def test_zero_weight_leg_free(self):
        cost = structure_cost_bps([5.0, 10.0], [0.0, 1.0])
        assert cost == pytest.approx(transaction_cost_bps(10.0))

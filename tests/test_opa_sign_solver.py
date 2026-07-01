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

    def test_solve_all_handles_raw_string_columns(self):
        """Live-path regression: OPA / PTP arrive as raw DTCC strings with
        thousands separators at detection time."""
        import pandas as pd

        from SDRUtils.packages.opa_sign_solver import solve_all_opa_signs

        df = pd.DataFrame({
            "trade_id": ["A", "B"],
            "ptp_group_id": ["G", "G"],
            "other_payment_amount": ["1,600", "1,500"],
            "package_transaction_price": ["88,100", "88,100"],
            "package_transaction_price_notation": [1.0, 1.0],
            "fixed_rate": [0.04, 0.04],
            "tenor_years": [2.0, 10.0],
            "estimated_pv01": [1000.0, 1000.0],
        })
        out = solve_all_opa_signs(df)
        # net = ±3,100 best vs PTP 88,100 -> residual 85,000 -> UNRESOLVED,
        # but the parse must produce real numbers, not NaN->0 everywhere.
        assert out["opa_signed_amount"].abs().sum() == 3100.0
        assert out["opa_ptp_residual"].iloc[0] == 85000.0

    def test_non_monetary_ptp_notation_is_unresolved(self):
        """Price-notation PTPs (notation != 1) must not produce fake
        EXACT tieouts — the dollar solve is meaningless there."""
        import pandas as pd

        from SDRUtils.packages.opa_sign_solver import solve_all_opa_signs

        df = pd.DataFrame({
            "trade_id": ["A", "B"],
            "ptp_group_id": ["G", "G"],
            "other_payment_amount": [None, None],
            "package_transaction_price": ["9.9999999999", "9.9999999999"],
            "package_transaction_price_notation": [3.0, 3.0],
            "fixed_rate": [0.04, 0.04],
            "tenor_years": [2.0, 10.0],
            "estimated_pv01": [1000.0, 1000.0],
        })
        out = solve_all_opa_signs(df)
        assert (out["opa_sign_confidence"] == "UNRESOLVED").all()
        assert out["opa_sign"].isna().all()

    def test_vectorized_brute_matches_reference(self):
        """Audit-added: chunked-numpy brute force must be exact — compare
        residual/net against a naive python enumeration on random inputs."""
        import random

        from SDRUtils.packages.opa_sign_solver import _solve_brute

        def _reference(opa, ptp):
            best = (float("inf"), float("inf"), 0, 0.0)
            for mask in range(1 << len(opa)):
                net = sum(v if (mask >> i) & 1 else -v for i, v in enumerate(opa))
                residual = min(abs(net - ptp), abs(net + ptp))
                direct = abs(net - ptp)
                if residual < best[0] - 1e-9 or (
                    abs(residual - best[0]) <= 1e-9 and direct < best[1]
                ):
                    best = (residual, direct, mask, net)
            return best

        random.seed(7)
        for n in (1, 2, 5, 9, 12):
            opas = [random.uniform(100, 1_000_000) for _ in range(n)]
            ptp = random.uniform(1_000, 500_000)
            signs, net, residual = _solve_brute(opas, ptp)
            ref_residual, _, _, ref_net = _reference(opas, ptp)
            assert abs(residual - ref_residual) < 1e-6
            assert abs(net - ref_net) < 1e-6
            assert abs(sum(s * v for s, v in zip(signs, opas)) - net) < 1e-6

    def test_mitm_matches_full_sweep(self):
        """Audit-added: for N>16 the solver uses meet-in-the-middle; it must
        agree exactly with a full vectorized 2^N sweep, including the
        complement-direction tiebreak (prefer net closer to +PTP)."""
        import numpy as np

        from SDRUtils.packages.opa_sign_solver import _select_best, _solve_brute

        def full_sweep(opa, ptp):
            n = len(opa)
            arr = np.asarray(opa, dtype=np.float64)
            masks = np.arange(1 << n, dtype=np.uint32)
            plus = np.zeros(masks.shape[0], dtype=np.float64)
            for i in range(n):
                plus += arr[i] * ((masks >> np.uint32(i)) & np.uint32(1))
            nets = 2.0 * plus - float(arr.sum())
            direct = np.abs(nets - ptp)
            residual = np.minimum(direct, np.abs(nets + ptp))
            tol = 1e-9 + 1e-13 * (float(np.abs(arr).sum()) + abs(ptp))
            return _select_best(residual, direct, masks, nets, tol)

        rng = np.random.default_rng(11)
        for _ in range(30):
            n = int(rng.integers(17, 21))
            opas = rng.uniform(1e2, 1e6, n).tolist()
            ptp = float(rng.uniform(1e3, 5e5))
            signs, net, residual = _solve_brute(opas, ptp)
            ref_res, _, _, ref_net = full_sweep(opas, ptp)
            assert abs(residual - ref_res) < 1e-6
            assert abs(net - ref_net) < 1e-6

    def test_brute_force_n20_fast(self):
        """Audit-added: N=20 exact solve must complete well under a second
        (pure-python loop took ~1.7s; vectorized target < 0.5s)."""
        import time

        import numpy as np

        rng = np.random.default_rng(0)
        opas = rng.uniform(1e3, 1e6, 20).tolist()
        t0 = time.perf_counter()
        result = solve_opa_signs(opas, ptp_value=88_100.0)
        elapsed = time.perf_counter() - t0
        assert len(result["signs"]) == 20
        assert elapsed < 1.0, f"N=20 brute force took {elapsed:.2f}s"

    def test_dealer_spread_bps_is_true_basis_points(self):
        """residual($) / total_dv01($/bp) is already bp — no ×100.
        Audit finding: shipped value was bp×100 (a % of DV01)."""
        import pandas as pd

        from SDRUtils.packages.opa_sign_solver import solve_all_opa_signs

        df = pd.DataFrame({
            "trade_id": ["A", "B"],
            "ptp_group_id": ["G", "G"],
            "other_payment_amount": [600.0, 500.0],
            "package_transaction_price": [90.0, 90.0],
            "package_transaction_price_notation": [1.0, 1.0],
            "fixed_rate": [0.04, 0.04],
            "tenor_years": [2.0, 10.0],
            "estimated_pv01": [40.0, 60.0],
        })
        out = solve_all_opa_signs(df)
        # best net = ±100, residual = 10; total_dv01 = 100 → 0.1 bp
        assert abs(out["dealer_spread_bps"].iloc[0] - 0.1) < 1e-9

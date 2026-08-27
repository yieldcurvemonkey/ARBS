"""Tests for RVUtils.CvxSuite.gates — all pure logic, no store required.

Includes the two synthetic constructions the DESIGN demands: a PLANTED RANK
ROTATION that the eigenvector gate must catch (and that sign-only
``align_eigenvectors`` provably cannot fix), and a PLANTED CORRELATED CLOUD
with an exactly-known Pearson correlation that the H-S diagnostic must flag.
Every planted answer carries a negative control.
"""

from __future__ import annotations

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")  # before any repo import

import math

import numpy as np
import pandas as pd
import pytest

from RVUtils.CvxSuite import gates

# The real quoted axes (MDP/CitiVelocityExcel/vol/cube_data.py:136-153) —
# note: NO 25Y on the expiry axis.
CITI_EXPIRIES = ["1M", "2M", "3M", "6M", "9M", "1Y", "18M", "2Y", "3Y", "4Y",
                 "5Y", "7Y", "10Y", "12Y", "15Y", "20Y", "30Y"]
CITI_TENORS = ["1Y", "2Y", "3Y", "4Y", "5Y", "7Y", "10Y", "12Y", "15Y",
               "20Y", "30Y"]


# ---------------------------------------------------------------------------
# degeneracy_gate
# ---------------------------------------------------------------------------
class TestDegeneracyGate:
    def test_scalar_pass_fail_boundary(self):
        """0.25 bp/day floor, inclusive (the CurveFlyScreener VOL_FLOOR).

        MUTATION: flip >= to <= — 0.30 True / 0.20 False both fail.
        MUTATION: exclusive boundary — the 0.25 case fails.
        """
        assert gates.degeneracy_gate(0.30) is True
        assert gates.degeneracy_gate(0.20) is False
        assert gates.degeneracy_gate(0.25) is True     # inclusive
        assert gates.degeneracy_gate(0.2499999) is False

    def test_nan_fails_closed(self):
        """MUTATION: NaN comparing as pass (e.g. ``not (v < floor)``) — this
        assert catches it; an unmeasured vol is not a tradeable one."""
        assert gates.degeneracy_gate(float("nan")) is False

    def test_series_elementwise(self):
        s = pd.Series([0.3, 0.2, np.nan, 0.25],
                      index=["a", "b", "c", "d"])
        out = gates.degeneracy_gate(s)
        assert isinstance(out, pd.Series)
        assert out.dtype == bool
        assert out.tolist() == [True, False, False, True]

    def test_custom_floor(self):
        assert gates.degeneracy_gate(0.4, floor=0.5) is False
        assert gates.degeneracy_gate(0.6, floor=0.5) is True


# ---------------------------------------------------------------------------
# support_gate
# ---------------------------------------------------------------------------
class TestSupportGate:
    def test_interior_non_node_passes_25y(self):
        """25y expiry is NOT a quoted node yet sits inside 1M..30Y: PASS.

        This is the KINK_GRID 25y5y case (clamped interior interpolation).
        MUTATION: node-membership check instead of envelope check — 25.0 is
        not in the axis and this assert fails.
        """
        assert gates.support_gate(25.0, 5.0, expiries=CITI_EXPIRIES,
                                  tenors=CITI_TENORS) is True

    def test_beyond_envelope_fails_40y(self):
        """The KINK_GRID 40y10y point: expiry 40 > 30Y max — FAIL by design
        (the screen must expect sigma_impl NaN there).

        MUTATION: clamping instead of failing — this assert catches it.
        """
        assert gates.support_gate(40.0, 10.0, expiries=CITI_EXPIRIES,
                                  tenors=CITI_TENORS) is False

    def test_boundaries_inclusive(self):
        assert gates.support_gate(30.0, 30.0, expiries=CITI_EXPIRIES,
                                  tenors=CITI_TENORS) is True
        assert gates.support_gate(1.0 / 12.0, 1.0, expiries=CITI_EXPIRIES,
                                  tenors=CITI_TENORS) is True

    def test_below_envelope_fails(self):
        assert gates.support_gate(5.0, 0.5, expiries=CITI_EXPIRIES,
                                  tenors=CITI_TENORS) is False   # tail < 1Y
        assert gates.support_gate(0.05, 5.0, expiries=CITI_EXPIRIES,
                                  tenors=CITI_TENORS) is False   # expiry < 1M

    def test_numeric_axes_accepted(self):
        assert gates.support_gate(3.5, 7.5, expiries=[1.0, 2.0, 5.0],
                                  tenors=(5.0, 10.0)) is True
        assert gates.support_gate(6.0, 7.5, expiries=[1.0, 2.0, 5.0],
                                  tenors=(5.0, 10.0)) is False

    def test_nan_coordinates_fail_closed(self):
        assert gates.support_gate(float("nan"), 5.0, expiries=CITI_EXPIRIES,
                                  tenors=CITI_TENORS) is False
        assert gates.support_gate(5.0, float("nan"), expiries=CITI_EXPIRIES,
                                  tenors=CITI_TENORS) is False
        assert gates.support_gate(None, 5.0, expiries=CITI_EXPIRIES,
                                  tenors=CITI_TENORS) is False

    def test_empty_axis_raises(self):
        with pytest.raises(ValueError):
            gates.support_gate(5.0, 5.0, expiries=[], tenors=CITI_TENORS)
        with pytest.raises(ValueError):
            gates.support_gate(5.0, 5.0, expiries=CITI_EXPIRIES, tenors=[])

    def test_unparseable_axis_element_raises(self):
        """A corrupt axis must not quietly shrink the envelope."""
        with pytest.raises(ValueError):
            gates.support_gate(5.0, 5.0, expiries=["1Y", "ATM"],
                               tenors=CITI_TENORS)


# ---------------------------------------------------------------------------
# compose_price_gate
# ---------------------------------------------------------------------------
class TestComposePriceGate:
    def test_within_and_beyond_tolerance(self):
        """3.0 bp two-vintage tolerance, inclusive.

        MUTATION: flip the comparison — 2.9 True / 3.1 False both fail.
        """
        assert gates.compose_price_gate(100.0, 102.9) is True
        assert gates.compose_price_gate(100.0, 103.1) is False
        assert gates.compose_price_gate(100.0, 103.0) is True   # inclusive

    def test_absolute_gap_both_directions(self):
        """MUTATION: drop the abs() — (96.5, 100) has c-p = -3.5 <= 3 and
        would PASS without abs; this assert catches it."""
        assert gates.compose_price_gate(96.5, 100.0) is False
        assert gates.compose_price_gate(103.5, 100.0) is False

    def test_nan_fails_closed(self):
        """A missing vintage is worse than a disagreeing one."""
        assert gates.compose_price_gate(float("nan"), 100.0) is False
        assert gates.compose_price_gate(100.0, float("nan")) is False
        assert gates.compose_price_gate(float("nan"), float("nan")) is False

    def test_custom_tolerance(self):
        assert gates.compose_price_gate(100.0, 100.4, tol_bp=0.5) is True
        assert gates.compose_price_gate(100.0, 100.6, tol_bp=0.5) is False


# ---------------------------------------------------------------------------
# eigenvector_gap_gate
# ---------------------------------------------------------------------------
class TestEigenvectorGapGate:
    def test_planted_rank_rotation_caught_and_sign_repair_cannot_fix_it(self):
        """PC2<->PC3 rank swap: per-slot |cos| collapses to 0 — gate FAILS.

        This is the dangerous case from ``_match_pcs``'s docstring ("call
        curvature 'slope' and hedge the wrong factor with the right
        arithmetic"). Sign-only ``pca_rv.align_eigenvectors`` provably cannot
        repair it: after alignment the per-slot cos is still 0 and the gate
        still fails — which is exactly why this gate exists.

        MUTATION: gate on sign instead of magnitude — cos=0 is not negative
        and the fail asserts catch it. MUTATION: overall pass as any()
        instead of all() — PC1 passes here so the overall-fail assert
        catches it.
        """
        V_prev = np.eye(4)[:, :3]
        V_new = V_prev[:, [0, 2, 1]]        # PC2 and PC3 swap rank
        cos = {f"PC{j + 1}": float(V_new[:, j] @ V_prev[:, j]) for j in range(3)}
        assert cos == {"PC1": 1.0, "PC2": 0.0, "PC3": 0.0}
        out = gates.eigenvector_gap_gate(cos)
        assert out["pass"] is False
        assert out["per_pc"] == {"PC1": True, "PC2": False, "PC3": False}
        assert out["worst_cos"] == 0.0
        assert out["worst_pc"] in ("PC2", "PC3")

        from RVUtils.pca_rv import align_eigenvectors
        V_fixed = align_eigenvectors(V_new, V_prev)
        cos_fixed = {f"PC{j + 1}": float(V_fixed[:, j] @ V_prev[:, j])
                     for j in range(3)}
        assert gates.eigenvector_gap_gate(cos_fixed)["pass"] is False

    def test_planted_angle_rotation_quantitative(self):
        """A rotation by theta in the PC2/PC3 plane plants |cos| = cos(theta).

        60 degrees -> 0.5 < 0.90: FAIL. 10 degrees -> 0.98481 >= 0.90: PASS.
        MUTATION: threshold applied to cos^2 or to the angle — the 10-degree
        pass / 60-degree fail pair catches it.
        """
        e = np.eye(4)
        for theta_deg, should_pass in ((60.0, False), (10.0, True)):
            th = math.radians(theta_deg)
            v2_new = math.cos(th) * e[:, 1] + math.sin(th) * e[:, 2]
            cos = {"PC1": 1.0, "PC2": float(v2_new @ e[:, 1])}
            assert cos["PC2"] == pytest.approx(math.cos(th), abs=1e-15)
            out = gates.eigenvector_gap_gate(cos)
            assert out["pass"] is should_pass
            assert out["per_pc"]["PC2"] is should_pass

    def test_sign_flip_is_benign(self):
        """|cos| semantics: -0.98 is a sign flip, not a rotation — PASS.

        MUTATION: drop the abs() — -0.98 < 0.90 and this assert fails.
        """
        out = gates.eigenvector_gap_gate({"PC1": -0.98, "PC2": 0.97})
        assert out["pass"] is True
        assert out["per_pc"]["PC1"] is True
        assert out["worst_cos"] == pytest.approx(0.97)

    def test_boundary_inclusive_and_all_pass(self):
        out = gates.eigenvector_gap_gate({"PC1": 0.999, "PC2": 0.90})
        assert out["pass"] is True
        assert out["worst_pc"] == "PC2"
        assert out["worst_cos"] == pytest.approx(0.90)
        assert out["min_cos"] == pytest.approx(0.90)

    def test_nan_fails_that_pc_and_ranks_worst(self):
        """First-refit month (no previous vintage): NaN is not continuity."""
        out = gates.eigenvector_gap_gate({"PC1": 0.99, "PC2": float("nan")})
        assert out["per_pc"] == {"PC1": True, "PC2": False}
        assert out["pass"] is False
        assert out["worst_pc"] == "PC2"
        assert np.isnan(out["worst_cos"])

    def test_empty_mapping_raises(self):
        """A vacuous all() over zero PCs must not read as a pass."""
        with pytest.raises(ValueError):
            gates.eigenvector_gap_gate({})

    def test_custom_threshold(self):
        assert gates.eigenvector_gap_gate({"PC1": 0.6}, min_cos=0.5)["pass"] is True
        assert gates.eigenvector_gap_gate({"PC1": 0.6}, min_cos=0.7)["pass"] is False


# ---------------------------------------------------------------------------
# cloud_diagnostic
# ---------------------------------------------------------------------------
def _levels_with_planted_corr(r: float, n: int = 124):
    """Two level series whose CHANGES have sample Pearson corr exactly r.

    x = tile(+1,-1) and z = tile(+1,+1,-1,-1) over n (n % 4 == 0) have zero
    means, equal norms and exact orthogonality, so y = r*x + sqrt(1-r^2)*z
    has corr(x, y) == r to machine precision.
    """
    assert n % 4 == 0
    x = np.tile([1.0, -1.0], n // 2)
    z = np.tile([1.0, 1.0, -1.0, -1.0], n // 4)
    y = r * x + math.sqrt(1.0 - r * r) * z
    idx = pd.bdate_range("2024-01-01", periods=n + 1)
    pc1 = pd.Series(np.concatenate([[0.0], np.cumsum(x)]), index=idx)
    struct = pd.Series(np.concatenate([[0.0], np.cumsum(y)]), index=idx)
    return struct, pc1


class TestCloudDiagnostic:
    def test_planted_correlated_cloud_is_flagged(self):
        """r = 0.6 planted exactly: corr == 0.6, |corr| > 0.45 -> FAIL.

        MUTATION: threshold flip, or corr computed on LEVELS instead of
        changes (level corr of two random walks with these diffs is far from
        0.6) — the exact-corr assert catches both.
        """
        struct, pc1 = _levels_with_planted_corr(0.6)
        out = gates.cloud_diagnostic(struct, pc1)
        assert out["corr"] == pytest.approx(0.6, abs=1e-12)
        assert out["pass"] is False
        assert out["n"] == 124

    def test_negative_correlation_also_flagged(self):
        """MUTATION: drop the abs() on corr — r = -0.6 would pass."""
        struct, pc1 = _levels_with_planted_corr(-0.6)
        out = gates.cloud_diagnostic(struct, pc1)
        assert out["corr"] == pytest.approx(-0.6, abs=1e-12)
        assert out["pass"] is False

    def test_clean_candidate_passes(self):
        struct, pc1 = _levels_with_planted_corr(0.3)
        out = gates.cloud_diagnostic(struct, pc1)
        assert out["corr"] == pytest.approx(0.3, abs=1e-12)
        assert out["pass"] is True

    def test_boundary_inclusive(self):
        struct, pc1 = _levels_with_planted_corr(0.45)
        out = gates.cloud_diagnostic(struct, pc1)
        assert out["pass"] is True

    def test_trailing_window_not_full_sample(self):
        """Correlation lives ONLY in the first half; the trailing window is
        exactly orthogonal -> corr == 0.0, PASS.

        Full-sample corr here is exactly 0.5 (> 0.45), so
        MUTATION: corr over head()/the full sample — pass flips to False and
        the exact-0 assert fails. This pins the PRE-ENTRY trailing semantics
        of the H-S device.
        """
        n = 124
        x = np.tile([1.0, -1.0], n)                     # 248 changes
        z = np.tile([1.0, 1.0, -1.0, -1.0], n // 4)     # 124 changes
        y = np.concatenate([x[:n], z])                   # corr 1 then corr 0
        idx = pd.bdate_range("2024-01-01", periods=2 * n + 1)
        pc1 = pd.Series(np.concatenate([[0.0], np.cumsum(x)]), index=idx)
        struct = pd.Series(np.concatenate([[0.0], np.cumsum(y)]), index=idx)
        out = gates.cloud_diagnostic(struct, pc1, window=n)
        assert out["corr"] == pytest.approx(0.0, abs=1e-12)
        assert out["pass"] is True
        assert out["n"] == n
        # the control: the full sample IS correlated (0.5) — a full-sample
        # implementation could not return 0.0 here
        full = float(pd.Series(y).corr(pd.Series(x)))
        assert full == pytest.approx(0.5, abs=1e-12)

    def test_min_n_fails_closed(self):
        """Too few paired changes: unmeasurable is not clean.

        MUTATION: drop the min_n floor — 10 orthogonal changes give corr 0
        and the gate would pass on noise.
        """
        struct, pc1 = _levels_with_planted_corr(0.0, n=12)
        out = gates.cloud_diagnostic(struct, pc1)       # min_n defaults to 63
        assert out["n"] == 12
        assert out["pass"] is False

    def test_constant_structure_fails_closed(self):
        idx = pd.bdate_range("2024-01-01", periods=200)
        struct = pd.Series(5.0, index=idx)
        pc1 = pd.Series(np.cumsum(np.tile([1.0, -1.0], 100)), index=idx)
        out = gates.cloud_diagnostic(struct, pc1)
        assert not np.isfinite(out["corr"])
        assert out["pass"] is False

    def test_alignment_on_common_index(self):
        """Series on partially overlapping indexes pair on the intersection."""
        struct, pc1 = _levels_with_planted_corr(0.6)
        out = gates.cloud_diagnostic(struct.iloc[10:], pc1.iloc[:-5])
        # 125 stamps total; struct[10:] has valid diffs at stamps 11..124,
        # pc1[:-5] at stamps 1..119 -> paired diffs at stamps 11..119 = 109
        assert out["n"] == 109
        assert out["pass"] is False

    def test_return_shape(self):
        struct, pc1 = _levels_with_planted_corr(0.3)
        out = gates.cloud_diagnostic(struct, pc1, window=100, max_abs_corr=0.4)
        assert set(out) == {"corr", "pass", "n", "window", "max_abs_corr"}
        assert out["window"] == 100
        assert out["max_abs_corr"] == pytest.approx(0.4)

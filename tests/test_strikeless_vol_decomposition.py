# tests/test_strikeless_vol_decomposition.py
"""Task 24: the exact decomposition and spot-fly replication.

Every assertion here is derived by hand or through an independent path,
never from the implementation's own output:

* ``duration_weights`` expectations are hand algebra on
  ``f(a,b) = (b*s_b - a*s_a)/(b-a)`` (worked in each docstring);
* the partition-of-unity check compares the tent ladder's SUM against a
  parallel DV01 computed in this file with ``rl.Curve.shift`` directly --
  rateslib's own bump, not this module's;
* the zero-discount limit compares the solved weights against the toy
  formula, which is exact at DF == 1 by construction (annuity == length);
* the repricing check bumps the curve and reprices package and portfolio
  through plain ``.npv()`` calls -- no ladder algebra in the assertion path;
* two mutation tests feed deliberately-broken variants (a sign-flipped copy
  of the tent kernel; a belly-sign-flipped toy) through the SAME assertion
  helpers the named tests use, and assert the helpers catch them.

All curves are synthetic rateslib fixtures; nothing here touches data.
"""
import numpy as np
import pandas as pd
import pytest
import rateslib as rl

from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve
from RVUtils.StrikelessVol import decomposition as dc
from RVUtils.StrikelessVol.conventions import FLATTENER
from RVUtils.StrikelessVol.costs import CostSchedule
from RVUtils.StrikelessVol.greeks import build_leg, build_package, package_npv
from RVUtils.StrikelessVol.universe import ForwardLeg, ForwardPair

REF = rl.dt(2026, 8, 3)

#: The package sizing every solve below uses; the toy's dollar weights are
#: this times the coefficients.
D = 100_000.0


def _make_curve(rate: float, curve_id: str) -> RLIRSwapCurve:
    """Flat curve at ``rate``, act360/nyc -- the greeks-test fixture idiom.

    41 annual nodes: the longest instrument priced here is a spot 30Y
    (matures ~2056), well inside the 2066 final node. ``rate=0.0`` gives
    DF == 1.0 at every node -- the zero-discounting limit, where the
    flat-annuity toy formula is exact (annuity == length up to day-count
    granularity).
    """
    nodes = {REF: 1.0}
    nodes.update({rl.dt(2026 + y, 8, 3): 1.0 / ((1.0 + rate) ** y) for y in range(1, 41)})
    handle = rl.Curve(nodes=nodes, convention="act360", calendar="nyc", id=curve_id)
    return RLIRSwapCurve(
        rl_curve_id="USD-OIS",
        rl_curve_handle=handle,
        fixings=rl.NoInput(0),
        meta_data={"reference_curve_name": "USD-OIS"},
    )


@pytest.fixture(scope="module")
def curve4():
    return _make_curve(0.04, "flat4")


@pytest.fixture(scope="module")
def curve0():
    """DF == 1.0 everywhere: the zero-discounting limit."""
    return _make_curve(0.0, "flat0")


@pytest.fixture(scope="module")
def pair():
    return ForwardPair("USD", "USD-OIS", ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y"))


@pytest.fixture(scope="module")
def solved0(pair, curve0):
    """The square 10-20-30 solve on the zero curve, computed once."""
    return dc.ladder_replication(pair, curve0, buckets=("10Y", "20Y", "30Y"))


@pytest.fixture(scope="module")
def solved4(pair, curve4):
    """The square 10-20-30 solve on the 4% curve, computed once."""
    return dc.ladder_replication(pair, curve4, buckets=("10Y", "20Y", "30Y"))


# ---------------------------------------------------------------------------
# duration_weights: hand algebra


def test_duration_weights_10y10y_20y10y_is_1_4_3():
    """f(10,20) = (20*s20 - 10*s10)/10 = 2*s20 - s10;
    f(20,30) = (30*s30 - 20*s20)/10 = 3*s30 - 2*s20;
    spread = f(20,30) - f(10,20) = s10 - 4*s20 + 3*s30. By hand."""
    p = ForwardPair("USD", "USD-OIS", ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y"))
    assert dc.duration_weights(p) == pytest.approx({"10Y": 1.0, "20Y": -4.0, "30Y": 3.0})


def test_duration_weights_15y5y_20y10y_by_hand():
    """f(15,20) = (20*s20 - 15*s15)/5 = 4*s20 - 3*s15;
    f(20,30) = 3*s30 - 2*s20;
    spread = 3*s30 - 2*s20 - 4*s20 + 3*s15 = 3*s15 - 6*s20 + 3*s30."""
    p = ForwardPair("USD", "USD-OIS", ForwardLeg("15Y", "5Y"), ForwardLeg("20Y", "10Y"))
    assert dc.duration_weights(p) == pytest.approx({"15Y": 3.0, "20Y": -6.0, "30Y": 3.0})


def test_duration_weights_5y10y_15y10y_by_hand():
    """f(5,15) = (15*s15 - 5*s5)/10 = 1.5*s15 - 0.5*s5;
    f(15,25) = (25*s25 - 15*s15)/10 = 2.5*s25 - 1.5*s15;
    spread = 0.5*s5 - 3*s15 + 2.5*s25."""
    p = ForwardPair("USD", "USD-OIS", ForwardLeg("5Y", "10Y"), ForwardLeg("15Y", "10Y"))
    assert dc.duration_weights(p) == pytest.approx({"5Y": 0.5, "15Y": -3.0, "25Y": 2.5})


def test_duration_weights_refuses_sub_annual_labels():
    p = ForwardPair("USD", "USD-OIS", ForwardLeg("6M", "10Y"), ForwardLeg("20Y", "10Y"))
    with pytest.raises(ValueError, match="whole-year"):
        dc.duration_weights(p)


# ---------------------------------------------------------------------------
# The tent ladder: partition of unity, checked against rl.Curve.shift


def _assert_ladder_sums_to_parallel(ladder: pd.Series, parallel_dv01: float) -> None:
    """THE partition-of-unity checker. The tents sum to 1 everywhere, so the
    bucket ladder must sum to the parallel DV01 -- computed by the CALLER with
    ``rl.Curve.shift``, rateslib's own bump, so the two sides of this
    assertion share no bump code. Shared by the named test and the
    mutation test below; rel 5e-4 against a measured 1.07e-4 discrepancy
    (second-order truncation + pillar-vs-node granularity)."""
    assert float(ladder.sum()) == pytest.approx(parallel_dv01, rel=5e-4)


def _parallel_dv01_via_rl_shift(curve, swap) -> float:
    """Independent parallel DV01: rl.Curve.shift, central difference."""
    handle = curve.handle()
    up = swap.npv(curves=handle.shift(1.0)).real
    dn = swap.npv(curves=handle.shift(-1.0)).real
    return float((up - dn) / 2.0)


def test_leg_ladder_is_a_partition_of_unity(curve4):
    """Per LEG, not per package: the package's parallel DV01 is ~0 by
    construction, so its check would compare two near-zeros. A leg sized to
    $100k is the non-degenerate case -- and this doubles as the
    bump-convention verifier: if the tent's time measure diverged from
    ``rl.shift``'s (days x daily DCF), the sum would miss by ~365/360."""
    leg = build_leg(curve4, ForwardLeg("10Y", "10Y"), dv01_usd=D, direction=+1)
    ladder = dc.swap_bucket_ladder(curve4, leg, buckets=dc.DEFAULT_BUCKETS)
    _assert_ladder_sums_to_parallel(ladder, _parallel_dv01_via_rl_shift(curve4, leg))


def test_front_buckets_carry_no_risk_for_a_10y_plus_package(curve4, pair):
    """The 2Y tent's support ends at the 5Y pillar and the 5Y tent's at the
    7Y pillar; the package's first sensitive date is ~10y out, so both bucket
    entries are structurally EXACT zeros -- every bumped node the package can
    see is unmoved. (7Y is NOT asserted zero: its tent reaches to the 10Y
    pillar, and the forward leg's effective date sits a couple of days inside
    it -- measured -$216 on this fixture, real granularity, not a bug.)"""
    pkg = build_package(curve4, pair, package_dv01_usd=D, sign=FLATTENER)
    ladder = dc.package_bucket_ladder(curve4, pkg, buckets=dc.DEFAULT_BUCKETS)
    assert ladder["2Y"] == pytest.approx(0.0, abs=1e-2)
    assert ladder["5Y"] == pytest.approx(0.0, abs=1e-2)


def test_buckets_must_be_strictly_increasing(curve4):
    with pytest.raises(ValueError, match="strictly increasing"):
        dc.bucket_pillar_dates(curve4, ("10Y", "5Y", "30Y"))


# ---------------------------------------------------------------------------
# (i) The 1:4:3 zero-discounting limit


def _assert_solved_matches_toy(solved: pd.Series, toy: dict, rel: float) -> None:
    """THE zero-limit checker: solved payer-DV01 dollars against the toy's
    ``-coef * D`` (payer-positive convention: the flattener RECEIVES the
    positive-coefficient tenors, so its solved payer weight is negative
    there). Signs asserted separately from magnitudes -- a global sign flip
    preserves every ratio. Shared by the named test and the mutation test."""
    assert set(solved.index) == set(toy)
    for tenor, coef in toy.items():
        expect = -coef * D
        got = float(solved[tenor])
        assert got * expect > 0, f"{tenor}: sign of {got} vs toy {expect}"
        assert got == pytest.approx(expect, rel=rel), f"{tenor}"


def test_solved_weights_are_1_4_3_in_the_zero_discount_limit(solved0, pair):
    """At DF == 1 the annuity IS the length (up to day-count granularity), so
    the flat-annuity toy is exact and the ladder solve must recover it:
    {10Y: -1, 20Y: +4, 30Y: -3} x $100k in payer-DV01 space. Measured
    deviations on this fixture: 2.6e-4 / 1.5e-4 / 2.8e-4 (schedule dates are
    modified-following ACT dates, not exact year multiples); rel 1e-3 bounds
    them with ~4x headroom. If this fails, the toy or the solve is wrong --
    the plan calls that a finding, not a tolerance problem."""
    _assert_solved_matches_toy(solved0, dc.duration_weights(pair), rel=1e-3)


def test_the_exact_solve_leaves_no_ladder_residual(solved0, solved4):
    """A square structure spanning the buckets must reproduce the ladder to
    numerical zero -- measured ~1.3e-10 on both fixtures; $0.01 is 8 orders
    of headroom while still catching any genuine misfit."""
    assert solved0.attrs["residual_norm"] < 1e-2
    assert solved4.attrs["residual_norm"] < 1e-2


def test_discounting_tilts_the_weights_materially_off_the_toy(solved4, pair):
    """The plan's warning made quantitative: at a flat 4% the solved weights
    sit 48-56% away from the toy's dollars (measured -148,001 / +615,212 /
    -467,211 against -100,000 / +400,000 / -300,000), and the SHAPE tilts
    too: |w20/w10| = 4.157 against the toy's 4. Floors at 0.30 and 0.05
    leave real headroom; if a change makes 4% look like the toy again,
    the discounting has been flattened out of the solve."""
    toy = dc.duration_weights(pair)
    for tenor, coef in toy.items():
        rel_dev = abs(float(solved4[tenor]) - (-coef * D)) / abs(coef * D)
        assert rel_dev > 0.30, f"{tenor}: rel dev {rel_dev:.3f}"
    assert abs(float(solved4["20Y"]) / float(solved4["10Y"])) - 4.0 > 0.05


# ---------------------------------------------------------------------------
# (ii) The solved weights reprice the package


def test_replication_reprices_the_package_under_bucket_bumps(curve4, pair, solved4):
    """The assertion path is plain repricing: rebuild the portfolio from
    ``attrs['notionals']``, tent-bump the curve +/-25bp at every bucket, and
    compare package and portfolio NPV changes through ``.npv()`` alone. The
    solve was done at h=1bp, the check runs at 25bp, so agreement is a
    statement about the replication, not an echo of the solve's own
    arithmetic. Measured worst gap: 0.005% of a $7.6m reprice (second-order
    convexity mismatch); the bound is 0.02% with a $5 floor for near-zero
    moves."""
    buckets = ("10Y", "20Y", "30Y")
    pillars = dc.bucket_pillar_dates(curve4, buckets)
    pkg = build_package(curve4, pair, package_dv01_usd=D, sign=FLATTENER)
    portfolio = [
        curve4.build_irswap(fwd="0D", tenor=lab, notional=n)
        for lab, n in solved4.attrs["notionals"].items()
    ]
    handle = curve4.handle()
    base_pkg = package_npv(handle, pkg)
    base_rep = sum(float(s.npv(curves=handle).real) for s in portfolio)
    for i in range(len(buckets)):
        for h in (25.0, -25.0):
            bumped = dc.tent_shifted_handle(handle, pillars, i, h)
            d_pkg = package_npv(bumped, pkg) - base_pkg
            d_rep = sum(float(s.npv(curves=bumped).real) for s in portfolio) - base_rep
            assert abs(d_pkg - d_rep) < max(2e-4 * abs(d_pkg), 5.0), (
                f"bucket {buckets[i]} h={h}: pkg {d_pkg:.1f} rep {d_rep:.1f}"
            )


# ---------------------------------------------------------------------------
# replication_basis: the daily panel


def test_basis_is_exactly_zero_when_nothing_moves(curve4, pair):
    """Two panel dates served by the SAME curve: every reprice is on the
    curve the instruments were struck on, so package and replication P&L are
    both identically zero and so is the basis. Anything nonzero here is
    bookkeeping, not markets."""
    panel = dc.replication_basis(
        pair,
        {pd.Timestamp("2026-08-03"): curve4, pd.Timestamp("2026-08-04"): curve4},
        structure=dc.EXACT_10_20_30,
    )
    assert list(panel.index) == [pd.Timestamp("2026-08-04")]
    assert panel["package_pnl_usd"].iloc[0] == pytest.approx(0.0, abs=1e-6)
    assert panel["replication_pnl_usd"].iloc[0] == pytest.approx(0.0, abs=1e-6)
    assert panel["basis_usd"].iloc[0] == pytest.approx(0.0, abs=1e-6)


def test_exact_replication_tracks_a_parallel_reprice(curve4, pair):
    """4.00% -> 4.05% flat: a ~5bp move. Measured on this fixture: package
    P&L +$2,383 (the package is DV01-neutral but the move is not exactly
    parallel in its shift measure, plus convexity), replication within $44 --
    1.8% of the package move and 0.00044bp/dv01. Bounds: |basis| < $100
    absolute and < 5% of the package's own P&L, both several times the
    measured values; the panel's shape and audit columns are pinned too."""
    c2 = _make_curve(0.0405, "flat405")
    panel = dc.replication_basis(
        pair,
        {pd.Timestamp("2026-08-03"): curve4, pd.Timestamp("2026-08-04"): c2},
        structure=dc.EXACT_10_20_30,
    )
    row = panel.iloc[0]
    assert abs(row["package_pnl_usd"]) > 1_000.0  # the move really repriced
    assert abs(row["basis_usd"]) < 100.0
    assert abs(row["basis_usd"]) < 0.05 * abs(row["package_pnl_usd"])
    assert row["basis_usd"] == pytest.approx(
        row["package_pnl_usd"] - row["replication_pnl_usd"], abs=1e-9
    )
    assert row["basis_bp"] == pytest.approx(row["basis_usd"] / D, abs=1e-12)
    assert {"w_10Y", "w_20Y", "w_30Y"} <= set(panel.columns)
    assert panel.attrs["structure"] == ("10Y", "20Y", "30Y")
    assert panel.attrs["dates_in"] == 1
    assert panel.attrs["n_dropped"] == 0


def test_one_bad_date_is_dropped_and_recorded_but_all_bad_raises(curve4, pair):
    """The greeks_panel idiom: a per-date failure is dropped into attrs, a
    100% failure rate raises with the first error as __cause__."""
    c2 = _make_curve(0.0405, "flat405b")
    good_then_bad = {
        pd.Timestamp("2026-08-03"): curve4,
        pd.Timestamp("2026-08-04"): c2,
        pd.Timestamp("2026-08-05"): "not a curve",
    }
    panel = dc.replication_basis(pair, good_then_bad, structure=dc.EXACT_10_20_30)
    assert len(panel) == 1
    assert panel.attrs["n_dropped"] == 1
    assert pd.Timestamp("2026-08-05") in panel.attrs["dropped"]

    with pytest.raises(ValueError, match="systematic"):
        dc.replication_basis(
            pair,
            {pd.Timestamp("2026-08-03"): "junk", pd.Timestamp("2026-08-04"): "junk"},
            structure=dc.EXACT_10_20_30,
        )


def test_structure_presets_and_leg_normalisation():
    """Hand expectations: a bare string is a spot leg; a tuple is a forward
    leg; the 1y-forward 2-7-30 preset's far wing ends at 31y (the collision-1
    point: beyond the GS 30y curve, inside the Citi 50y one) while 2-7-29's
    ends at 30y."""
    legs = dc.structure_legs(dc.PROXY_1YFWD_2_7_30)
    assert [(l.fwd, l.tail) for l in legs] == [("1Y", "2Y"), ("1Y", "7Y"), ("1Y", "30Y")]
    assert legs[-1].end_years == pytest.approx(31.0)
    legs29 = dc.structure_legs(dc.PROXY_1YFWD_2_7_29)
    assert legs29[-1].end_years == pytest.approx(30.0)
    spot = dc.structure_legs(("10Y",))
    assert (spot[0].fwd, spot[0].tail) == ("0D", "10Y")
    with pytest.raises(ValueError, match="empty"):
        dc.structure_legs(())


# ---------------------------------------------------------------------------
# The PCA metric: consumed from rl_swap_risk_ladder_utils, refusal inherited


class _FakePCA:
    """Minimal stand-in for CurvePCAModel: orthonormal loadings (identity),
    which is exactly the case where uniform weights make G == I and the
    refusal in ``_refuse_degenerate_pca_metric`` must fire."""

    def __init__(self, k: int):
        self.columns = [f"b{i}" for i in range(k)]
        self.loadings = pd.DataFrame(
            np.eye(k), index=self.columns, columns=[f"PC{i + 1}" for i in range(k)]
        )


def test_pca_metric_inherits_the_uniform_weight_refusal():
    """pca_weights=None (and explicit all-ones) must raise -- the sv-PR
    behaviour change in _build_pca_metric_matrix, reaching this module
    through the pass-through rather than being re-implemented here."""
    model = _FakePCA(3)
    with pytest.raises(ValueError, match="identity"):
        dc.pca_metric(model, None)
    with pytest.raises(ValueError, match="identity"):
        dc.pca_metric(model, [1.0, 1.0, 1.0])


def test_pca_metric_matrix_is_l_diag_w_lt_by_hand():
    """With identity loadings, G = L diag(w) L^T = diag(w) -- hand
    arithmetic. The buckets length guard is checked on both sides."""
    model = _FakePCA(3)
    G = dc.pca_metric(model, [1.0, 1.0, 0.0], buckets=("10Y", "20Y", "30Y"))
    assert np.allclose(G, np.diag([1.0, 1.0, 0.0]))
    with pytest.raises(ValueError, match="ladder buckets"):
        dc.pca_metric(model, [1.0, 1.0, 0.0], buckets=("10Y", "20Y"))


def test_identity_metric_equals_plain_least_squares(pair, curve4):
    """The G-path's normal equations must coincide with numpy's lstsq when
    G == I (an identity PASSED AS A MATRIX -- pca_metric would refuse to
    build it, but the solver must still handle it correctly). Run on the
    overdetermined case (6 buckets, 3 spot instruments), where the two code
    paths do genuinely different arithmetic."""
    plain = dc.ladder_replication(pair, curve4, structure=dc.EXACT_10_20_30)
    with_g = dc.ladder_replication(
        pair, curve4, structure=dc.EXACT_10_20_30, metric=np.eye(len(dc.DEFAULT_BUCKETS))
    )
    pd.testing.assert_series_equal(plain, with_g, rtol=1e-9)


# ---------------------------------------------------------------------------
# Per-leg initiation cost (collision 3)


def test_initiate_cost_is_charged_per_leg_not_per_package():
    """Hand arithmetic: initiate_bp=0.5, weights +$40k and -$80k of DV01.
    Per leg: 0.5*40,000 + 0.5*80,000 = $60,000. Charged on the NET package
    DV01 (|40k - 80k| = 40k) it would be $20,000 -- the mispricing collision
    3 exists to forbid. Both numbers asserted so the distinction is pinned,
    not narrated."""
    sched = CostSchedule(initiate_bp=0.5, hedge_bp=0.0, roll_bp=0.0, multiplier=1.0)
    weights = {"10Y": 40_000.0, "20Y": -80_000.0}
    assert dc.initiate_cost_usd(weights, sched) == pytest.approx(60_000.0)
    net = abs(sum(weights.values()))
    assert sched.cost_usd("initiate", net) == pytest.approx(20_000.0)
    assert dc.initiate_cost_usd(weights, sched) != pytest.approx(
        sched.cost_usd("initiate", net)
    )


# ---------------------------------------------------------------------------
# Mutation checks: the checkers must catch the broken variants


def _mutant_tent_shifted_handle(handle, pillar_dates, i, h_bp):
    """A copy of ``decomposition.tent_shifted_handle`` with ONE defect: the
    bump exponent's sign is flipped (``+n*phi`` for ``-n*phi``), so a
    positive shift LOWERS zero rates. Everything else is verbatim."""
    from RVUtils.StrikelessVol.greeks import daily_dcf

    d = daily_dcf(handle)
    base = 1.0 + d * float(h_bp) / 10_000.0
    initial = handle.nodes.initial
    p_days = [(pd.Timestamp(p).to_pydatetime() - pd.Timestamp(initial).to_pydatetime()).days
              for p in pillar_dates]
    out = handle.copy()
    for node_date, df in handle.nodes.nodes.items():
        n = (pd.Timestamp(node_date).to_pydatetime() - pd.Timestamp(initial).to_pydatetime()).days
        if n <= 0:
            continue
        phi = dc._phi(n, i, p_days)
        if phi == 0.0:
            continue
        out.update_node(node_date, float(df) * base ** (+n * phi))  # <-- the defect
    return out


def test_mutant_tent_kernel_is_caught_by_the_partition_check(curve4):
    """Feed the sign-flipped kernel through the SAME central-difference loop
    shape and the SAME checker the named partition test uses. The mutant's
    ladder is the NEGATIVE of the true one (asserted first, so the failure
    below is attributable to the flipped sign, not to a botched copy), and
    ``_assert_ladder_sums_to_parallel`` must reject it."""
    leg = build_leg(curve4, ForwardLeg("10Y", "10Y"), dv01_usd=D, direction=+1)
    buckets = dc.DEFAULT_BUCKETS
    pillars = dc.bucket_pillar_dates(curve4, buckets)
    handle = curve4.handle()
    vals = {}
    for i, b in enumerate(buckets):
        up = float(leg.npv(curves=_mutant_tent_shifted_handle(handle, pillars, i, +1.0)).real)
        dn = float(leg.npv(curves=_mutant_tent_shifted_handle(handle, pillars, i, -1.0)).real)
        vals[b] = (up - dn) / 2.0
    mutant_ladder = pd.Series(vals)

    true_ladder = dc.swap_bucket_ladder(curve4, leg, buckets=buckets)
    assert float(mutant_ladder.sum()) == pytest.approx(-float(true_ladder.sum()), rel=1e-6)

    with pytest.raises(AssertionError):
        _assert_ladder_sums_to_parallel(
            mutant_ladder, _parallel_dv01_via_rl_shift(curve4, leg)
        )


def test_mutant_toy_weights_are_caught_by_the_zero_limit_check(solved0, pair):
    """The classic transcription error -- ``+4*s20`` for ``-4*s20`` in the
    belly -- fed through the SAME checker the zero-limit test uses. The
    mutant differs from the real toy at exactly the belly (asserted first),
    and ``_assert_solved_matches_toy`` must reject it on the sign leg of its
    check."""
    toy = dc.duration_weights(pair)
    mutant = dict(toy)
    mutant["20Y"] = -mutant["20Y"]  # <-- the defect
    assert {k: v for k, v in mutant.items() if k != "20Y"} == {
        k: v for k, v in toy.items() if k != "20Y"
    }
    with pytest.raises(AssertionError):
        _assert_solved_matches_toy(solved0, mutant, rel=1e-3)

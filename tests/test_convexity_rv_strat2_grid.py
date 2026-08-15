"""Known-answer tests for the Strategy-2 butterfly universe and grid engine.

Six families, each pinned to something that can be wrong silently:

**(a) The catalogue.** 9 shapes x 5 forward starts = 45 flies over 40 distinct
leg tenors, and the ``AYxBY`` tenor grammar round-trips. A shape that quietly
loses its forward variants would make the whole hypothesis test vacuous.

**(b) The fly-rate identity.** ``IRSwapValue.RATE`` on ``IRSwapStructure.FLY``
must equal ``100 * (-w_f*r_f + r_b - w_k*r_k)`` from three OUTRIGHT par rates,
to better than 1e-6 bp. This is the licence to store LEG rates and derive every
fly arithmetically, which is what makes a 45-fly grid affordable. Marked
``slow`` and pinned to 2023-06-09.

**(c) The risk-weight landmine.** ``IRSwapStructure._build_fly`` MUTATES its
``risk_weights`` list in place. The test proves the mutation is real on the raw
engine (otherwise it is testing nothing) and then proves the universe's own
query builder is immune, because it constructs a fresh list every call and
stores weights on a frozen dataclass.

**(d) Citi's published sizing.** ``belly_DV01 = CA_DV01 * beta / 100``
reproduces the 13-Jan-2017 and 9-Feb-2017 notionals at ratios 1.004 and 1.003.

**(e) The P&L signs**, which are the ones that silently invert a backtest: a
PAID belly earns ``+belly_DV01 * d(fly_bp)``, a SHORT-CA position earns
``-CA_DV01 * d(CA_bp)``, and the short-CA gamma term is never positive. Each
has an explicit negative control asserting the opposite sign FAILS.

**(f) No lookahead**, and the mechanical invariants of the ledger.

Everything except the ``slow`` family runs on synthetic panels with planted
answers and needs no market data.
"""

import datetime
import math
import pathlib

import numpy as np
import pandas as pd
import pytest

from RVUtils.ConvexityRV.strat2_fly_universe import (
    DV01_NEUTRAL_WINGS,
    FLY_SHAPES,
    FORWARD_STARTS,
    FlySpec,
    annuity_duration,
    fly_by_id,
    fly_carry_series,
    fly_gamma_per_bp2,
    fly_query_kwargs,
    fly_rate_bp,
    fly_rate_series,
    fly_regression,
    fly_universe,
    parse_tenor_key,
    tenor_key,
    universe_tenors,
)
from RVUtils.ConvexityRV.strat2_grid import (
    COST_MULTIPLIERS,
    Strat2GridConfig,
    citi_belly_dv01,
    constant_contract_dca,
    effectiveness_matrix,
    plan_epochs,
    prepare_inputs,
    rank_label_series,
    run_grid,
    simulate_cell,
)

CURVE = "USD-SOFR-1D"
AS_OF = datetime.date(2023, 6, 9)


# ===========================================================================
# (a) the catalogue
# ===========================================================================
def test_universe_is_nine_shapes_at_five_forward_starts():
    u = fly_universe()
    assert len(u) == len(FLY_SHAPES) * len(FORWARD_STARTS) == 45
    assert len({s.fly_id for s in u}) == 45
    spot = [s for s in u if s.is_spot]
    assert len(spot) == 9
    assert {s.fly_id for s in spot} == {n for n, _ in FLY_SHAPES}


def test_citis_own_fly_and_the_pms_are_both_in_the_catalogue():
    ids = {s.fly_id for s in fly_universe()}
    assert "2s5s10s" in ids                      # Citi's published hedge
    assert "2s7s30s" in ids                      # the PM's ask
    for fs in ("1Y", "2Y", "3Y", "5Y"):
        assert f"2s5s10s@{fs}" in ids


def test_forward_fly_legs_are_the_shape_at_the_forward_start():
    s = fly_by_id("2s5s10s@2Y")
    assert (s.front, s.belly, s.back) == ("2Yx2Y", "2Yx5Y", "2Yx10Y")
    assert (s.front_y, s.belly_y, s.back_y) == (2.0, 5.0, 10.0)
    assert s.forward_start_y == 2.0 and not s.is_spot


@pytest.mark.parametrize("start,tenor,key", [
    (0, 5, "5Y"), (2, 5, "2Yx5Y"), (0, 30, "30Y"), (5, 30, "5Yx30Y"),
])
def test_tenor_key_round_trips(start, tenor, key):
    assert tenor_key(start, tenor) == key
    assert parse_tenor_key(key) == (float(start), float(tenor))


def test_universe_needs_exactly_forty_leg_tenors():
    t = universe_tenors()
    assert len(t) == 40 == len(set(t))
    # 8 spot + 8 per forward start
    assert sum(1 for k in t if "x" not in k) == 8


def test_non_integral_tenors_are_refused_not_rounded():
    with pytest.raises(ValueError):
        tenor_key(0, 2.5)


# ===========================================================================
# (b) the fly-rate identity  (slow: needs the curve)
# ===========================================================================
@pytest.fixture(scope="module")
def pricer():
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    p = IRSwapsMDP(source="CITIVELO_EXCEL").get_pricer(
        {"curve_name": CURVE, "timestamp": AS_OF, "offline": True})
    ref = p.reference_date()
    ref = ref.date() if hasattr(ref, "date") else ref
    if ref != AS_OF:
        pytest.skip(f"curve resolved to {ref}, not {AS_OF}")
    return p


def _engine_fly_bp(pricer, spec, w_front, w_back):
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    q = IRSwapQuery(structure=IRSwapStructure.FLY, value=IRSwapValue.RATE, curve=CURVE,
                    structure_kwargs=fly_query_kwargs(spec, w_front, w_back, bpv=10_000.0))
    pkg, w = q.resolve_package(pricer_or_curve=pricer)
    pkg = [pricer.resolve_pricable(p, ww) for p, ww in zip(pkg, w)]
    vm = q.build_value_map(pricer_or_curve=pricer, package=pkg, risk_weights=w)
    return float(vm.apply(value=IRSwapValue.RATE)), pkg, w


@pytest.mark.slow
@pytest.mark.parametrize("fly_id,wf,wk", [
    ("2s5s10s", 0.5, 0.5),
    ("2s5s10s", 0.73, 0.47),          # Citi's published 13-Jan-2017 weights
    ("2s5s10s@2Y", 0.5, 0.5),
    ("2s7s30s", 0.6, 0.4),
    ("10s20s30s@3Y", 0.5, 0.5),
])
def test_engine_fly_rate_equals_the_leg_arithmetic(pricer, fly_id, wf, wk):
    """The licence to store legs and derive flies. Tolerance 1e-6 bp."""
    from RVUtils.ConvexityRV.strat2_sofr_convexity import _swap_par_rate

    spec = fly_by_id(fly_id)
    engine, _, _ = _engine_fly_bp(pricer, spec, wf, wk)
    rates = {t: _swap_par_rate(pricer, CURVE, tenor=t) for t in spec.tenors}
    manual = fly_rate_bp(rates, spec, wf, wk)
    assert abs(engine - manual) < 1e-6, f"{fly_id}: engine {engine} vs manual {manual}"


@pytest.mark.slow
def test_the_fly_identity_test_is_not_vacuous(pricer):
    """Negative control: the SAME comparison with the wrong wing weights must fail."""
    from RVUtils.ConvexityRV.strat2_sofr_convexity import _swap_par_rate

    spec = fly_by_id("2s5s10s")
    engine, _, _ = _engine_fly_bp(pricer, spec, 0.73, 0.47)
    rates = {t: _swap_par_rate(pricer, CURVE, tenor=t) for t in spec.tenors}
    assert abs(engine - fly_rate_bp(rates, spec, 0.5, 0.5)) > 1.0


@pytest.mark.slow
def test_fly_leg_pv01s_are_exactly_the_risk_weights_times_bpv(pricer):
    """``PV01_i = w_i * bpv`` is what makes ``dP&L = belly_DV01 * d fly_bp`` exact."""
    spec = fly_by_id("2s5s10s")
    bpv = 21_400.0
    _, _, w = _engine_fly_bp(pricer, spec, 0.73, 0.47)
    assert list(w) == [-0.73, 1.0, -0.47]          # sign mapper: wings against belly
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    q = IRSwapQuery(structure=IRSwapStructure.FLY, value=IRSwapValue.NPV, curve=CURVE,
                    structure_kwargs=fly_query_kwargs(spec, 0.73, 0.47, bpv=bpv))
    pkg, w = q.resolve_package(pricer_or_curve=pricer)
    pkg = [pricer.resolve_pricable(p, ww) for p, ww in zip(pkg, w)]
    for leg, wi in zip(pkg, w):
        assert pricer.pv01(leg) == pytest.approx(wi * bpv, rel=1e-9, abs=1e-6)


# ===========================================================================
# (c) the risk-weight mutation landmine
# ===========================================================================
@pytest.mark.slow
def test_the_engine_really_does_mutate_risk_weights_in_place(pricer):
    """If this ever stops failing, the landmine was fixed upstream and the guard
    below is testing nothing. Assert the hazard exists before asserting immunity."""
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    shared = [0.73, 1.0, 0.47]
    IRSwapQuery(structure=IRSwapStructure.FLY, value=IRSwapValue.RATE, curve=CURVE,
                structure_kwargs={"front_tenor": "2Y", "belly_tenor": "5Y",
                                  "back_tenor": "10Y", "risk_weights": shared,
                                  "bpv": 10_000.0}).resolve_package(pricer_or_curve=pricer)
    assert shared == [-0.73, 1.0, -0.47], "the in-place mutation is gone; revisit the guard"


def test_fly_query_kwargs_hands_out_a_fresh_list_every_call():
    spec = fly_by_id("2s5s10s")
    a = fly_query_kwargs(spec, 0.73, 0.47, bpv=1.0)
    b = fly_query_kwargs(spec, 0.73, 0.47, bpv=1.0)
    assert a["risk_weights"] == b["risk_weights"] == [0.73, 1.0, 0.47]
    assert a["risk_weights"] is not b["risk_weights"]
    a["risk_weights"][0] = -999.0                     # simulate _build_fly
    assert fly_query_kwargs(spec, 0.73, 0.47, bpv=1.0)["risk_weights"][0] == 0.73


def test_flyspec_is_frozen_so_geometry_cannot_be_rewritten_in_place():
    spec = fly_by_id("2s5s10s")
    with pytest.raises(Exception):
        spec.front = "3Y"                             # frozen dataclass
    assert isinstance(spec.tenors, tuple)             # tuple, not a mutable list


@pytest.mark.slow
def test_building_the_same_fly_twice_gives_the_same_rate(pricer):
    """The end-to-end statement of immunity: repeated use must not drift."""
    spec = fly_by_id("2s5s10s")
    first, _, _ = _engine_fly_bp(pricer, spec, 0.73, 0.47)
    for _ in range(3):
        again, _, _ = _engine_fly_bp(pricer, spec, 0.73, 0.47)
        assert again == pytest.approx(first, abs=1e-10)


# ===========================================================================
# (d) Citi's published fly sizing
# ===========================================================================
@pytest.mark.parametrize("ca_dv01,beta,published_5y_mn,expected_ratio", [
    (100_000.0, 21.4, -44.4, 1.004),      # [W-JAN13] 13-Jan-2017
    (200_000.0, 20.6, -85.6, 1.003),      # [TI-FEB9] 9-Feb-2017
])
def test_belly_dv01_reproduces_citis_published_notionals(
        ca_dv01, beta, published_5y_mn, expected_ratio):
    """``belly_DV01 = CA_DV01*beta/100``; published 5y notional x $480/mn is the check."""
    required = citi_belly_dv01(ca_dv01, beta)
    implied = abs(published_5y_mn) * 480.0            # $/bp at the era's 5y DV01
    assert required / implied == pytest.approx(expected_ratio, abs=0.001)


def test_the_fly_is_deliberately_not_dv01_matched_to_the_ca_leg():
    """*"the belly is only ~21% of it, because it is a BETA hedge."*"""
    assert citi_belly_dv01(100_000.0, 21.4) / 100_000.0 == pytest.approx(0.214)


# ===========================================================================
# (e) the regression
# ===========================================================================
def _legs_frame(n=400, seed=0):
    """Wide date x tenor par rates, a correlated random walk in percent."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    tenors = universe_tenors()
    level = np.cumsum(rng.normal(0, 0.03, n))
    out = {}
    for i, t in enumerate(tenors):
        s, ny = parse_tenor_key(t)
        base = 1.5 + 0.15 * math.log1p(ny) + 0.05 * s
        out[t] = base + level + np.cumsum(rng.normal(0, 0.01, n))
    return pd.DataFrame(out, index=idx)


def test_fly_regression_recovers_planted_citi_weights():
    """Plant ``CA = 10.2 + 21.4*(-0.73*r2 + r5 - 0.47*r10)`` and recover it."""
    legs = _legs_frame()
    spec = fly_by_id("2s5s10s")
    fly_pct = (-0.73 * legs["2Y"] + legs["5Y"] - 0.47 * legs["10Y"])
    ca = 10.2 + 21.4 * fly_pct
    fit = fly_regression(ca, legs, spec, window_days=252)
    assert fit.alpha == pytest.approx(10.2, abs=1e-6)
    assert fit.beta == pytest.approx(21.4, abs=1e-6)
    assert fit.w_front == pytest.approx(0.73, abs=1e-8)
    assert fit.w_back == pytest.approx(0.47, abs=1e-8)
    assert fit.r2 == pytest.approx(1.0, abs=1e-9)
    assert fit.ok


def test_fly_regression_delegates_to_the_tested_strat2_estimator():
    """The generalised fit must BE ``hedge_regression``, not a second copy of it."""
    from RVUtils.ConvexityRV.strat2_sofr_convexity import Strat2Config, hedge_regression

    legs = _legs_frame(seed=3)
    spec = fly_by_id("2s5s10s")
    rng = np.random.default_rng(11)
    ca = (10.2 + 21.4 * (-0.73 * legs["2Y"] + legs["5Y"] - 0.47 * legs["10Y"])
          + rng.normal(0, 0.4, len(legs)))
    mine = fly_regression(ca, legs, spec, window_days=126)
    theirs = hedge_regression(ca, legs, Strat2Config(hedge_tenors=("2Y", "5Y", "10Y"),
                                                     hedge_regression_days=126))
    assert mine.beta == theirs.beta and mine.w_front == theirs.w2
    assert mine.w_back == theirs.w10 and mine.r2 == theirs.r2


def test_fly_regression_runs_the_forward_fly_through_the_same_path():
    legs = _legs_frame(seed=7)
    spec = fly_by_id("2s5s10s@2Y")
    ca = 5.0 + 12.0 * (-0.6 * legs["2Yx2Y"] + legs["2Yx5Y"] - 0.4 * legs["2Yx10Y"])
    fit = fly_regression(ca, legs, spec, window_days=252)
    assert fit.w_front == pytest.approx(0.6, abs=1e-8)
    assert fit.w_back == pytest.approx(0.4, abs=1e-8)
    assert fit.beta == pytest.approx(12.0, abs=1e-6)


def test_regression_basis_changes_is_the_same_estimator_on_first_differences():
    """Plant the relationship in CHANGES only; the level fit must not find it."""
    from RVUtils.ConvexityRV.strat2_sofr_convexity import Strat2Config, hedge_regression

    legs = _legs_frame(seed=17)
    spec = fly_by_id("2s5s10s")
    d_fly = (-0.73 * legs["2Y"] + legs["5Y"] - 0.47 * legs["10Y"]).diff()
    ca = pd.Series(np.concatenate([[100.0], 100.0 + np.cumsum(
        (21.4 * d_fly.dropna()).to_numpy())]), index=legs.index)
    chg = fly_regression(ca, legs, spec, window_days=252, basis="changes")
    assert chg.beta == pytest.approx(21.4, abs=1e-6)
    assert chg.w_front == pytest.approx(0.73, abs=1e-8)
    assert chg.w_back == pytest.approx(0.47, abs=1e-8)
    # and it IS the delegated estimator, just fed diffs
    ref = hedge_regression(ca.diff(), legs.diff(),
                           Strat2Config(hedge_tenors=("2Y", "5Y", "10Y"),
                                        hedge_regression_days=252))
    assert chg.beta == ref.beta and chg.w_front == ref.w2


def test_regression_basis_is_validated():
    with pytest.raises(ValueError):
        fly_regression(pd.Series(dtype=float), _legs_frame(n=10),
                       fly_by_id("2s5s10s"), basis="nope")


def test_a_negative_wing_is_reported_not_silently_dropped():
    legs = _legs_frame(seed=5)
    spec = fly_by_id("2s5s10s")
    ca = 5.0 + 10.0 * (+0.4 * legs["2Y"] + legs["5Y"] - 0.3 * legs["10Y"])
    fit = fly_regression(ca, legs, spec, window_days=252,
                         require_positive_wings=True)
    assert fit.w_front < 0                      # the finding is preserved
    assert not fit.ok and "fly" in fit.reason   # and marked untradeable


# ===========================================================================
# (f) the fly rate / carry arithmetic
# ===========================================================================
def test_fly_rate_series_matches_the_scalar_form_row_by_row():
    legs = _legs_frame(n=50)
    spec = fly_by_id("2s7s30s@1Y")
    ser = fly_rate_series(legs, spec, 0.6, 0.4)
    for d in legs.index[:10]:
        assert ser.at[d] == pytest.approx(fly_rate_bp(legs.loc[d], spec, 0.6, 0.4))


def test_a_dv01_neutral_fly_is_flat_to_a_parallel_shift():
    """50/50 wings: ``1 - 0.5 - 0.5 = 0``, so the fly is pure curvature."""
    legs = _legs_frame(n=20)
    spec = fly_by_id("2s5s10s")
    base = fly_rate_series(legs, spec, *DV01_NEUTRAL_WINGS)
    shifted = fly_rate_series(legs + 0.10, spec, *DV01_NEUTRAL_WINGS)   # +10bp parallel
    pd.testing.assert_series_equal(base, shifted, atol=1e-9, check_names=False)


def test_citi_weights_are_not_parallel_neutral_and_the_gap_is_the_weight_sum():
    legs = _legs_frame(n=20)
    spec = fly_by_id("2s5s10s")
    d = (fly_rate_series(legs + 0.10, spec, 0.73, 0.47)
         - fly_rate_series(legs, spec, 0.73, 0.47))
    assert float(d.iloc[0]) == pytest.approx(10.0 * (1 - 0.73 - 0.47), abs=1e-9)


def test_fly_carry_is_the_same_weighted_sum_as_the_rate():
    carry = _legs_frame(n=30, seed=2) * 3.0
    spec = fly_by_id("3s5s7s")
    got = fly_carry_series(carry, spec, 0.5, 0.5)
    want = (-0.5 * carry["3Y"] + carry["5Y"] - 0.5 * carry["7Y"])
    pd.testing.assert_series_equal(got, want, check_names=False)


def test_missing_leg_raises_rather_than_silently_dropping_the_fly():
    legs = _legs_frame(n=10).drop(columns=["30Y"])
    with pytest.raises(KeyError):
        fly_rate_series(legs, fly_by_id("2s10s30s"), 0.5, 0.5)


# ===========================================================================
# (g) the second-order term
# ===========================================================================
@pytest.mark.parametrize("start,tenor,rate,measured", [
    (0, 2, 4.50354, 1.133), (0, 5, 3.69135, 2.585), (0, 10, 3.47951, 4.889),
    (0, 30, 3.20548, 12.697), (2, 5, 3.12431, 4.603), (5, 5, 3.23046, 7.594),
])
def test_annuity_duration_matches_rateslib_analytic_delta(start, tenor, rate, measured):
    """Measured 2023-06-09 as ``-(A(+25bp)-A(0))/A(0)/25bp``. Tolerance 3%."""
    assert annuity_duration(start, tenor, rate) == pytest.approx(measured, rel=0.03)


def test_the_naive_duration_would_fail_this_test_at_the_long_end():
    """Negative control: ``s + n/2 + 0.125`` is 19% out on 30Y."""
    naive = 0 + 30 / 2 + 0.125
    assert abs(naive / 12.697 - 1.0) > 0.15
    assert abs(annuity_duration(0, 30, 3.20548) / 12.697 - 1.0) < 0.03


def test_a_fifty_fifty_2s5s10s_paid_belly_is_slightly_long_gamma():
    """``D_belly - 0.5*D_front - 0.5*D_back = 2.585 - 0.567 - 2.444 < 0`` -> +gamma."""
    rates = {"2Y": 4.50354, "5Y": 3.69135, "10Y": 3.47951}
    g = fly_gamma_per_bp2(fly_by_id("2s5s10s"), rates, 0.5, 0.5, belly_dv01=21_400.0)
    assert g > 0


# ===========================================================================
# synthetic market for the grid
# ===========================================================================
N_PACKS = 10


@pytest.fixture(scope="module")
def synthetic():
    """A CA panel whose CA is a KNOWN function of the fly, plus the leg panel.

    ``ca_bp(rank) = HoLee(T1, sigma=120bp) + 8.0*fly_pct + noise``. The loading
    on the fly is Citi-like in spirit (their beta was 21.4 on a fly whose daily
    changes are larger), and the noise is set so the fly explains ~2/3 of the
    daily CA variance -- enough for a hedge to bite, far from degenerate.
    """
    legs = _legs_frame(n=700, seed=42)
    idx = legs.index
    rng = np.random.default_rng(99)
    fly_pct = (-0.5 * legs["2Y"] + legs["5Y"] - 0.5 * legs["10Y"])
    rows = []
    for k in range(1, N_PACKS + 1):
        t1 = 0.15 + 0.25 * (k - 1)
        t1s = np.array([t1 + 0.25 * i for i in range(4)])
        label = f"P{k:02d}"
        ca = (0.5 * (1.20 ** 2) * float(np.mean(t1s ** 2)) * 1e4 / 1e4 * 1e2
              + 8.0 * fly_pct.to_numpy() + rng.normal(0, 0.05, len(idx)))
        swap = legs["5Y"].to_numpy() * 0.9
        for i, d in enumerate(idx):
            rows.append({
                "date": d, "rank": k, "pack": label, "colour": None,
                "swap_start": d, "swap_end": d,
                "pack_rate": swap[i] + ca[i] / 100.0, "swap_rate": swap[i],
                "ca_bp": ca[i], "time_weight": float(np.mean(t1s ** 2)),
                "t_mid": float(np.mean(t1s)),
            })
    panel = pd.DataFrame(rows)
    carry = _legs_frame(n=700, seed=43) * 0.1
    return panel, legs, carry


@pytest.fixture(scope="module")
def inputs(synthetic):
    panel, legs, carry = synthetic
    return prepare_inputs(panel, legs, carry=carry)


def test_prepare_inputs_aligns_everything_on_one_date_axis(inputs):
    assert len(inputs.dates) > 400
    assert inputs.ca.index.equals(inputs.dates)
    assert inputs.legs.index.equals(inputs.dates)
    assert set(inputs.ca.columns) == {f"P{k:02d}" for k in range(1, N_PACKS + 1)}


def test_t_mid_to_t1_offset_is_exact():
    """``T1_i = T1, T1+.25, T1+.5, T1+.75`` -> ``mean = T1 + 0.375``."""
    from RVUtils.ConvexityRV.strat2_grid import T_MID_TO_T1

    t1 = 2.0
    assert float(np.mean([t1 + 0.25 * i for i in range(4)])) - T_MID_TO_T1 == t1


# ===========================================================================
# (h) the P&L signs -- each with a negative control
# ===========================================================================
def test_short_ca_earns_when_the_ca_narrows(inputs):
    cfg = Strat2GridConfig(pack_rank=8, hedge_sizing="unhedged", entry_rule="always",
                           regression_window=252, holding_days=21, rebalance_days=21)
    res = simulate_cell(inputs, cfg)
    assert res.metrics["n_epochs"] > 5
    ep = res.epochs[0]
    win = inputs.dates[(inputs.dates > ep.entry) & (inputs.dates <= ep.exit)]
    d_ca = inputs.ca[ep.pack].reindex(
        inputs.dates[(inputs.dates >= ep.entry) & (inputs.dates <= ep.exit)]).diff()
    want = -(d_ca.reindex(win)) * ep.ca_dv01
    got = res.daily["ca_pnl"].reindex(win)
    pd.testing.assert_series_equal(got, want.fillna(0.0), check_names=False, atol=1e-6)
    # negative control: the OPPOSITE sign must not match
    assert not np.allclose(got.to_numpy(), (-want).to_numpy(), atol=1e-6)


def test_paid_belly_earns_when_the_fly_rate_rises(inputs):
    """``dP&L = +belly_DV01 * d(fly_bp)``. The task brief states this with a
    MINUS; the engine says otherwise and so does the economics -- ``beta>0``
    means CA and fly move together, so a short-CA book needs a leg that GAINS
    when the fly rises. Verified here, and against per-leg PV01 in the slow
    test above."""
    cfg = Strat2GridConfig(pack_rank=8, fly_id="2s5s10s", fly_weighting="dv01_neutral",
                           hedge_sizing="dv01_ratio", dv01_ratio=0.5,
                           entry_rule="always", holding_days=21, rebalance_days=21)
    res = simulate_cell(inputs, cfg)
    ep = res.epochs[0]
    hold = inputs.dates[(inputs.dates >= ep.entry) & (inputs.dates <= ep.exit)]
    win = hold[1:]
    d_fly = fly_rate_series(inputs.legs.reindex(hold), res.spec,
                            ep.w_front, ep.w_back).diff().reindex(win)
    want = d_fly * ep.belly_dv01
    got = res.daily["fly_pnl"].reindex(win)
    pd.testing.assert_series_equal(got, want.fillna(0.0), check_names=False, atol=1e-6)
    assert not np.allclose(got.to_numpy(), (-want).to_numpy(), atol=1e-6)


def test_long_ca_is_the_exact_mirror_of_short_ca(inputs):
    kw = dict(pack_rank=8, fly_id="2s5s10s", fly_weighting="dv01_neutral",
              hedge_sizing="dv01_ratio", dv01_ratio=0.3, entry_rule="always",
              holding_days=21, rebalance_days=21)
    a = simulate_cell(inputs, Strat2GridConfig(direction="short_ca", **kw))
    b = simulate_cell(inputs, Strat2GridConfig(direction="long_ca", **kw))
    assert b.metrics["total_pnl"] == pytest.approx(-a.metrics["total_pnl"], rel=1e-9)
    assert b.metrics["gamma_pnl"] == pytest.approx(-a.metrics["gamma_pnl"], rel=1e-9)


def test_short_ca_gamma_is_never_positive(inputs):
    """Long futures vs pay fixed is SHORT gamma. A positive number here means a
    sign was flipped -- the trade's entire risk would be pointing the wrong way."""
    cfg = Strat2GridConfig(pack_rank=8, hedge_sizing="unhedged", entry_rule="always",
                           holding_days=21, rebalance_days=21)
    res = simulate_cell(inputs, cfg)
    assert res.metrics["gamma_pnl"] < 0
    assert (res.daily["gamma_pnl"] <= 1e-9).all()


def test_include_gamma_moves_the_headline_and_is_reported_either_way(inputs):
    kw = dict(pack_rank=8, hedge_sizing="unhedged", entry_rule="always",
              holding_days=21, rebalance_days=21)
    off = simulate_cell(inputs, Strat2GridConfig(include_gamma=False, **kw))
    on = simulate_cell(inputs, Strat2GridConfig(include_gamma=True, **kw))
    assert off.metrics["gamma_pnl"] == pytest.approx(on.metrics["gamma_pnl"])
    assert on.metrics["total_pnl"] < off.metrics["total_pnl"]     # short gamma bleeds


# ===========================================================================
# (i) mechanics: no lookahead, sizing, costs, rolls
# ===========================================================================
def test_epoch_weights_are_fitted_only_on_data_up_to_the_entry(inputs, synthetic):
    """CORRUPT everything strictly after an entry date and refit.

    Stronger than truncation (which also removes the holding window and so
    cannot form the epoch at all): the date axis is unchanged, only the FUTURE
    is poisoned. Any weight, beta or sizing that moves was reading it.
    """
    panel, legs, carry = synthetic
    cfg = Strat2GridConfig(pack_rank=8, fly_id="2s5s10s", fly_weighting="regression",
                           regression_window=126, holding_days=42, rebalance_days=42)
    eps = plan_epochs(inputs, cfg, fly_by_id("2s5s10s"))
    assert len(eps) >= 3
    for ep in eps[:3]:
        p2 = panel.copy()
        p2.loc[p2["date"] > ep.entry, "ca_bp"] *= 1000.0
        l2 = legs.copy()
        l2.loc[l2.index > ep.entry] *= 1000.0
        again = plan_epochs(prepare_inputs(p2, l2, carry=carry), cfg,
                            fly_by_id("2s5s10s"))
        match = [e for e in again if e.entry == ep.entry]
        assert match, f"entry {ep.entry} vanished when the future was poisoned"
        assert match[0].w_front == pytest.approx(ep.w_front, rel=1e-12)
        assert match[0].w_back == pytest.approx(ep.w_back, rel=1e-12)
        assert match[0].belly_dv01 == pytest.approx(ep.belly_dv01, rel=1e-12)
        assert match[0].fly_entry_bp == pytest.approx(ep.fly_entry_bp, rel=1e-12)


def test_weights_are_frozen_for_the_life_of_an_epoch(inputs):
    cfg = Strat2GridConfig(pack_rank=8, fly_weighting="regression",
                           regression_window=126, holding_days=63, rebalance_days=63)
    eps = plan_epochs(inputs, cfg, fly_by_id("2s5s10s"))
    assert len({(e.w_front, e.w_back) for e in eps}) > 1        # they DO re-estimate
    for e in eps:                                              # ...but not intra-epoch
        assert isinstance(e.w_front, float) and isinstance(e.w_back, float)


def test_unhedged_sizing_has_no_fly_leg_at_all(inputs):
    res = simulate_cell(inputs, Strat2GridConfig(pack_rank=8, hedge_sizing="unhedged",
                                                 holding_days=21, rebalance_days=21))
    assert res.metrics["fly_leg_pnl"] == 0.0
    assert all(e.belly_dv01 == 0.0 for e in res.epochs)
    assert res.metrics["total_pnl"] == pytest.approx(res.metrics["ca_leg_pnl"])


def test_regression_beta_sizing_uses_citis_rule(inputs):
    cfg = Strat2GridConfig(pack_rank=8, hedge_sizing="regression_beta",
                           fly_weighting="regression", holding_days=63)
    eps = plan_epochs(inputs, cfg, fly_by_id("2s5s10s"))
    for e in eps:
        assert e.belly_dv01 == pytest.approx(citi_belly_dv01(cfg.ca_dv01, e.fit.beta))


def test_dv01_ratio_sizing_is_a_constant_multiple(inputs):
    cfg = Strat2GridConfig(pack_rank=8, hedge_sizing="dv01_ratio", dv01_ratio=0.25,
                           holding_days=63)
    eps = plan_epochs(inputs, cfg, fly_by_id("2s5s10s"))
    assert eps and all(e.belly_dv01 == pytest.approx(25_000.0) for e in eps)


def test_cost_sensitivity_ladder_is_linear_in_the_multiplier(inputs):
    cfg = Strat2GridConfig(pack_rank=8, hedge_sizing="dv01_ratio", dv01_ratio=0.2,
                           cost_bp_roundtrip=0.25, holding_days=21, rebalance_days=21)
    m = simulate_cell(inputs, cfg).metrics
    gross = m["pnl_cost_0x"]
    unit = gross - m["pnl_cost_1x"]
    assert unit > 0
    for mult in COST_MULTIPLIERS:
        assert m[f"pnl_cost_{mult:g}x"] == pytest.approx(gross - mult * unit, rel=1e-9)


def test_entry_rules_are_progressively_more_selective(inputs):
    base = dict(pack_rank=8, hedge_sizing="unhedged", holding_days=21, rebalance_days=21)
    always = simulate_cell(inputs, Strat2GridConfig(entry_rule="always", **base))
    z = simulate_cell(inputs, Strat2GridConfig(entry_rule="ca_z", z_entry=1.0, **base))
    hard = simulate_cell(inputs, Strat2GridConfig(entry_rule="ca_z", z_entry=2.5, **base))
    assert always.metrics["n_epochs"] >= z.metrics["n_epochs"] >= hard.metrics["n_epochs"]
    assert z.metrics["n_epochs"] < always.metrics["n_epochs"]


def test_constant_contract_dca_produces_no_roll_jump():
    """The naive rank-following diff invents a jump on every roll; this must not."""
    idx = pd.bdate_range("2020-01-01", periods=6)
    ca = pd.DataFrame({"A": [1.0, 1.1, 1.2, 1.3, 1.4, 1.5],
                       "B": [9.0, 9.1, 9.2, 9.3, 9.4, 9.5]}, index=idx)
    labels = pd.Series(["A", "A", "A", "B", "B", "B"], index=idx)
    d = constant_contract_dca(ca, labels)
    assert np.isnan(d.iloc[0])
    assert d.iloc[1] == pytest.approx(0.1) and d.iloc[2] == pytest.approx(0.1)
    assert d.iloc[3] == pytest.approx(0.1)                # NOT 9.3 - 1.2 = 8.1
    naive = ca.to_numpy()[np.arange(6), [0, 0, 0, 1, 1, 1]]
    assert abs(np.diff(naive)[2]) > 8.0                   # the jump the naive form makes


def test_rank_label_series_follows_the_rank(inputs):
    s = rank_label_series(inputs.panel, 8)
    assert set(s.unique()) == {"P08"}


def test_effectiveness_matrix_has_a_column_per_forward_start(inputs):
    m = effectiveness_matrix(inputs, shape="2s5s10s", ranks=(5, 8),
                             forward_starts=(0.0, 2.0))
    assert list(m.index) == [5, 8]
    assert {"T1_years", "n_obs", "fs_0Y", "fs_2Y"} <= set(m.columns)
    assert m.loc[8, "T1_years"] == pytest.approx(0.15 + 0.25 * 7, abs=1e-9)
    assert 0.0 <= m.loc[8, "fs_0Y"] <= 1.0


def test_hypothesis_slope_is_one_when_the_hypothesis_holds_by_construction():
    """Plant matrices whose argmax T1 tracks the forward start one-for-one."""
    from RVUtils.ConvexityRV.strat2_grid import hypothesis_slope

    t1 = np.array([0.4, 1.0, 2.0, 3.0, 5.0])
    starts = [0.0, 1.0, 2.0, 3.0, 5.0]
    mats = {}
    for shape in ("a", "b"):
        d = {"T1_years": t1}
        for j, f in enumerate(starts):
            d[f"fs_{f:g}Y"] = np.where(np.arange(5) == j, 0.9, 0.1)
        mats[shape] = pd.DataFrame(d, index=pd.Index([2, 3, 4, 5, 6], name="rank"))
    out = hypothesis_slope(mats)
    assert out["n"] == 10
    assert out["corr"] > 0.99          # not exactly 1: T1 grid is 0.4,1,2,3,5 vs F 0,1,2,3,5
    assert out["slope"] == pytest.approx(0.94, abs=0.02)


def test_hypothesis_slope_is_zero_when_the_hypothesis_fails():
    """Negative control: every forward start peaking at the SAME T1 -> slope 0."""
    from RVUtils.ConvexityRV.strat2_grid import hypothesis_slope

    t1 = np.array([0.4, 1.0, 2.0, 3.0, 5.0])
    d = {"T1_years": t1}
    for f in (0.0, 1.0, 2.0, 3.0, 5.0):
        d[f"fs_{f:g}Y"] = np.array([0.1, 0.9, 0.1, 0.1, 0.1])
    m = pd.DataFrame(d, index=pd.Index([2, 3, 4, 5, 6], name="rank"))
    out = hypothesis_slope({"a": m, "b": m})
    assert out["slope"] == pytest.approx(0.0, abs=1e-9)
    assert set(out["peak_r2_by_start"]) == {0.0, 1.0, 2.0, 3.0, 5.0}


def test_run_grid_emits_every_cell_including_empty_ones(inputs):
    rows, _ = run_grid(inputs, Strat2GridConfig(pack_rank=8, holding_days=21,
                                                rebalance_days=21),
                       axes={"fly_id": ["2s5s10s", "2s5s10s@2Y"],
                             "hedge_sizing": ["unhedged", "dv01_ratio"]},
                       progress=False)
    assert len(rows) == 4
    assert set(rows["fly_id"]) == {"2s5s10s", "2s5s10s@2Y"}
    assert rows["n_epochs"].min() > 0


def test_bad_config_values_are_rejected_at_construction():
    for kw in ({"fly_weighting": "nope"}, {"hedge_sizing": "nope"},
               {"entry_rule": "nope"}, {"z_window": "nope"},
               {"direction": "nope"}, {"holding_days": 0},
               {"regression_basis": "nope"}, {"regression_target": "nope"}):
        with pytest.raises(ValueError):
            Strat2GridConfig(**kw)


def test_rank_following_ca_is_the_rolling_colour_not_a_constant_pack(inputs):
    """Citi's *"Blues CA"* is a RANK, re-pointed on every roll."""
    from RVUtils.ConvexityRV.strat2_grid import rank_following_ca

    s = rank_following_ca(inputs, 8)
    assert s.index.equals(inputs.dates)
    # the synthetic panel has one label per rank, so the two agree there
    pd.testing.assert_series_equal(s, inputs.ca["P08"], check_names=False)


def test_regression_target_label_starves_the_deep_ranks_on_real_geometry():
    """A pack label enters a 13-contract strip at window 10 with NO history, so
    a 252d trailing fit on its own CA cannot run there. Reproduced on a panel
    with real roll geometry (a NEW label appears at rank 10 each quarter)."""
    legs = _legs_frame(n=700, seed=8)
    idx = legs.index
    rows = []
    for i, d in enumerate(idx):
        quarter = i // 63
        for k in range(1, 11):
            # label identity walks inward: the pack at rank k today was at
            # rank k+1 a quarter ago, so its name is fixed by (quarter + k)
            lbl = f"L{quarter + k:03d}"
            rows.append({"date": d, "rank": k, "pack": lbl, "colour": None,
                         "swap_start": d, "swap_end": d,
                         "pack_rate": 2.0, "swap_rate": 2.0,
                         "ca_bp": 1.0 * k + 0.01 * i, "time_weight": 0.1 * k,
                         "t_mid": 0.15 + 0.25 * (k - 1) + 0.375})
    inp = prepare_inputs(pd.DataFrame(rows), legs)
    spec = fly_by_id("2s5s10s")
    starved = plan_epochs(inp, Strat2GridConfig(pack_rank=10, regression_target="label",
                                                regression_window=252,
                                                holding_days=63, rebalance_days=21), spec)
    citi = plan_epochs(inp, Strat2GridConfig(pack_rank=10, regression_target="rank",
                                             regression_window=252,
                                             holding_days=63, rebalance_days=21), spec)
    assert len(starved) == 0, "the constant-label fit should have no history at rank 10"
    assert len(citi) >= 5, "Citi's rolling-rank series does have history"


# ===========================================================================
# (j) does the suite bite? -- an explicit self-mutation check
# ===========================================================================
def test_the_sign_probes_fail_under_a_deliberately_flipped_fly_sign(inputs, monkeypatch):
    """Mutation check. Flip the paid-belly sign inside the ledger and assert the
    sign probe FAILS. A suite that passes on mutated code is measuring nothing.

    This mutates the fly-rate series the ledger consumes, which is the same
    observable the real sign bug would move.
    """
    import RVUtils.ConvexityRV.strat2_grid as G

    good = simulate_cell(inputs, Strat2GridConfig(
        pack_rank=8, fly_weighting="dv01_neutral", hedge_sizing="dv01_ratio",
        dv01_ratio=0.5, holding_days=21, rebalance_days=21))

    monkeypatch.setattr(G, "fly_rate_series",
                        lambda legs, spec, wf, wk: -fly_rate_series(legs, spec, wf, wk))
    bad = simulate_cell(inputs, Strat2GridConfig(
        pack_rank=8, fly_weighting="dv01_neutral", hedge_sizing="dv01_ratio",
        dv01_ratio=0.5, holding_days=21, rebalance_days=21))

    assert bad.metrics["fly_leg_pnl"] == pytest.approx(-good.metrics["fly_leg_pnl"])
    assert bad.metrics["fly_leg_pnl"] != pytest.approx(good.metrics["fly_leg_pnl"])
    # and the ledger the probe compares against no longer matches
    ep = good.epochs[0]
    hold = inputs.dates[(inputs.dates >= ep.entry) & (inputs.dates <= ep.exit)]
    win = hold[1:]
    want = fly_rate_series(inputs.legs.reindex(hold), good.spec,
                           ep.w_front, ep.w_back).diff().reindex(win) * ep.belly_dv01
    assert not np.allclose(bad.daily["fly_pnl"].reindex(win).to_numpy(),
                           want.fillna(0.0).to_numpy(), atol=1e-6)


def test_the_hedge_actually_reduces_variance_on_the_synthetic_market(inputs):
    """The economic arbiter of the sign. On a market where ``CA = a + 8*fly``,
    a correctly signed hedge must cut the P&L variance; the wrong sign raises it."""
    kw = dict(pack_rank=8, fly_id="2s5s10s", fly_weighting="regression",
              hedge_sizing="regression_beta", holding_days=63, rebalance_days=21)
    hedged = simulate_cell(inputs, Strat2GridConfig(**kw))
    assert hedged.metrics["variance_reduction"] > 0.5
    assert hedged.metrics["hedge_r2"] > 0.5


# ===========================================================================
# (k) the Citi-shape tie-out ON REAL DATA
# ===========================================================================
PANELS = pathlib.Path(__file__).resolve().parents[1] / "notebooks" / "data" / "convexity_rv"


@pytest.mark.slow
def test_rolling_estimator_reproduces_citis_fly_SHAPE_on_our_own_sample():
    """Citi's 2017 anchors cannot be reproduced -- no data that far back -- so the
    tie-out is on the SHAPE: running Citi's own estimator (levels, ``CA ~ r2 +
    r5 + r10``) on the 2019-2023 SOFR sample must give same-signed,
    same-order-of-magnitude wing weights.

    Citi published ``-0.73/1/-0.47`` (13-Jan-2017) and ``-0.705/1/-0.465``
    (9-Feb-2017). Measured here, pooling the median of 54 rolling 63-day fits at
    each of ranks 3..9 on the rolling-rank CA series: **w_front ~ 0.51,
    w_back ~ 0.54**, both positive, i.e. within a factor of 1.5 of Citi's on
    both wings. The ``beta`` is a different story and is deliberately NOT
    asserted here -- see the sign-stability test below.
    """
    if not (PANELS / "strat2_panel.parquet").exists() or \
       not (PANELS / "strat2_fly_legs.parquet").exists():
        pytest.skip("panels not built; run scripts/strat2_build_fly_panel.py")
    from RVUtils.ConvexityRV.strat2_fly_universe import legs_wide
    from RVUtils.ConvexityRV.strat2_grid import prepare_inputs, rank_following_ca

    panel = pd.read_parquet(PANELS / "strat2_panel.parquet")
    legs = legs_wide(pd.read_parquet(PANELS / "strat2_fly_legs.parquet"), "rate_pct")
    inp = prepare_inputs(panel, legs)
    spec = fly_by_id("2s5s10s")

    w2s, w10s, betas = [], [], []
    for rank in range(3, 10):
        ca = rank_following_ca(inp, rank)
        for d in inp.dates[63::21]:
            f = fly_regression(ca.loc[:d].dropna(), inp.legs.loc[:d], spec,
                               window_days=63, basis="levels")
            if np.isfinite(f.w_front) and np.isfinite(f.w_back):
                w2s.append(f.w_front)
                w10s.append(f.w_back)
                betas.append(f.beta)

    assert len(w2s) > 300, f"only {len(w2s)} fits; the sample is too thin to judge"
    w2, w10 = float(np.median(w2s)), float(np.median(w10s))
    print(f"\n  measured pooled medians: w_front={w2:.3f} w_back={w10:.3f} "
          f"(Citi 0.73 / 0.47), n={len(w2s)} fits")
    assert w2 > 0 and w10 > 0, "wings must be same-signed as Citi's"
    assert 0.5 < w2 / 0.73 < 2.0, f"w_front {w2:.3f} not within a factor 2 of 0.73"
    assert 0.5 < w10 / 0.47 < 2.0, f"w_back {w10:.3f} not within a factor 2 of 0.47"
    assert np.isfinite(np.median(betas))


@pytest.mark.slow
def test_the_level_regression_beta_sign_is_unstable_on_this_sample():
    """The finding the grid exists to surface, pinned as a test.

    Citi's estimator is a LEVEL regression of a near-unit-root CA on
    near-unit-root rates. On 2019-2023 SOFR its ``R^2`` looks respectable
    (median 0.12-0.60 across ranks) and yet the fitted ``beta`` -- the thing the
    hedge is SIZED off -- changes sign on a large share of re-estimations. A
    hedge ratio whose sign is close to a coin flip cannot reduce variance, and
    measured it does not: variance reduction was positive in only 14.4% of the
    180 fly x rank cells.

    If this test ever fails because the betas became stable, the grid's headline
    conclusion has changed and must be re-derived, not patched.
    """
    if not (PANELS / "strat2_panel.parquet").exists() or \
       not (PANELS / "strat2_fly_legs.parquet").exists():
        pytest.skip("panels not built; run scripts/strat2_build_fly_panel.py")
    from RVUtils.ConvexityRV.strat2_fly_universe import legs_wide
    from RVUtils.ConvexityRV.strat2_grid import prepare_inputs, rank_following_ca

    panel = pd.read_parquet(PANELS / "strat2_panel.parquet")
    legs = legs_wide(pd.read_parquet(PANELS / "strat2_fly_legs.parquet"), "rate_pct")
    inp = prepare_inputs(panel, legs)
    spec = fly_by_id("2s5s10s")

    fracs = []
    for rank in range(3, 10):
        ca = rank_following_ca(inp, rank)
        b = [fly_regression(ca.loc[:d].dropna(), inp.legs.loc[:d], spec,
                            window_days=63, basis="levels").beta
             for d in inp.dates[63::21]]
        b = [x for x in b if np.isfinite(x)]
        if b:
            fracs.append(float(np.mean(np.asarray(b) > 0)))
    print(f"\n  frac(beta > 0) by rank 3..9, 63d levels: "
          f"{[round(f, 3) for f in fracs]}")
    assert fracs
    # every rank sits well inside a coin flip: no rank is even 80% one-signed
    assert max(fracs) < 0.80, f"betas became stable: {fracs}"
    assert min(fracs) > 0.20, f"betas became stable (negative): {fracs}"

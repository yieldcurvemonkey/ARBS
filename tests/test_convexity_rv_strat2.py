"""Known-answer tests for Citi's SOFR pack convexity screen (strategy 2).

Four families, matching the four tie-outs the strategy is graded on:

**(a) The 2023-06-09 pack table.** Citi restated the ED screen for SOFR in
*Rates Vol Lab - Forward steepener and vol divergence*, 12-Jun-2023, Figure 58
(close 6/9/23), and printed 13 rolling 1y packs. The tests here reproduce the
pack labels, the matched swap's start and end dates, and -- against live market
data -- the CA correlation. The **level** is deliberately not asserted: Citi's
swap leg is CME-cleared and ``USD-SOFR-1D`` is not, so a several-bp offset is
expected and only the shape is comparable.

**(b) The 3m roll identity.** ``Roll(p) = CA(p) - CA(p one contract nearer)``.
Citi's own printed columns satisfy it on 12/12 consecutive row pairs, and a
shuffled negative control must FAIL -- otherwise the test is vacuous and would
pass on any monotone column.

**(c) The DV01 identities.** ``1000 packs x 4 x $25 = $100,000/bp`` and
``belly_DV01 = CA_DV01 * beta / 100``, both checked against Citi's published
notionals.

**(d) Sign conventions**, which are the ones that silently invert a whole
backtest: FLY ``bpv > 0`` = pay the belly, futures ``contracts > 0`` = long the
future = short the rate.

Tests that need the market-data cache are marked ``slow`` and pinned to the
single date 2023-06-09, which is the tie-out date. Everything else is pure
arithmetic on the published numbers and runs in the fast gate.
"""

import datetime
import math

import numpy as np
import pandas as pd
import pytest

from RVUtils.ConvexityRV.holee import implied_vol_from_ca_bp, pack_time_weight
from RVUtils.ConvexityRV.packs import DV01_PER_CONTRACT, imm_date
from RVUtils.ConvexityRV.strat2_sofr_convexity import (
    HedgeFit,
    RANK_METRICS,
    Strat2Config,
    ca_snapshot,
    daily_screen,
    fit_sigma_model,
    futures_symbol,
    hedge_regression,
    hedge_sizing,
    pack_windows,
    rank_flags,
    select_pack,
)

CURVE = "USD-SOFR-1D"

# ---------------------------------------------------------------------------
# Citi, Rates Vol Lab 12-Jun-2023, Figure 58, close 6/9/2023.
# pack | CA | 1WkChg | 3mZ | 1YZ | Model | VsModel | 3mZ | 1YZ | Roll | IV | RV
# ---------------------------------------------------------------------------
CITI_SOFR = pd.DataFrame(
    [
        ("M4-H5", 4.03, 1.23, 2.94, 1.09, 0.88, 199.5, 229.7),
        ("U4-M5", 4.41, 0.98, 3.79, 0.62, 0.38, 178.1, 201.4),
        ("Z4-U5", 5.16, 0.71, 4.66, 0.49, 0.74, 167.7, 180.3),
        ("H5-Z5", 6.10, 0.29, 5.53, 0.58, 0.95, 161.6, 166.3),
        ("M5-H6", 8.24, -0.40, 6.36, 1.88, 2.14, 168.5, 156.4),
        ("U5-M6", 9.77, -1.22, 7.16, 2.60, 1.52, 166.3, 148.8),
        ("Z5-U6", 11.70, -1.89, 8.02, 3.67, 1.93, 166.5, 142.2),
        ("H6-Z6", 13.70, -2.37, 8.96, 4.74, 2.00, 166.0, 136.1),
        ("M6-H7", 15.40, -3.08, 9.98, 5.42, 1.70, 163.1, 130.9),
        ("U6-M7", 16.84, -2.97, 11.10, 5.74, 1.44, 159.0, 126.2),
        ("Z6-U7", 18.27, -2.72, 12.23, 6.04, 1.43, 155.1, 121.9),
        ("H7-Z7", 20.08, -2.33, 13.37, 6.71, 1.81, 152.8, 118.0),
        ("M7-H8", 22.29, -1.78, 14.50, 7.79, 2.21, 151.9, 113.8),
    ],
    columns=["pack", "ca", "chg1w", "model", "vs_model", "roll", "iv", "rv"],
).set_index("pack")

AS_OF = datetime.date(2023, 6, 9)
CITI_CFG = Strat2Config(n_contracts=20, rank_start=5, n_packs=13)


# ===========================================================================
# (a) the pack table -- labels and matched swap dates, no market data needed
# ===========================================================================
def test_pack_labels_reproduce_citis_thirteen_rows():
    """Windows 5..17 as of 6/9/23 are exactly Citi's 13 printed packs."""
    specs = {s.rank: s for s in pack_windows(AS_OF, CITI_CFG)}
    labels = [specs[r].label for r in range(5, 18)]
    assert labels == list(CITI_SOFR.index)


def test_pack_colours_land_where_citi_says_they_do():
    """*"Whites M3-H4, Reds M4-H5, Greens M5-H6, Blues M6-H7, Golds M7-H8."*"""
    by_label = {s.label: s.colour for s in pack_windows(AS_OF, CITI_CFG)}
    assert by_label["M3-H4"] == "Whites"
    assert by_label["M4-H5"] == "Reds"
    assert by_label["M5-H6"] == "Greens"
    assert by_label["M6-H7"] == "Blues"
    assert by_label["M7-H8"] == "Golds"


@pytest.mark.parametrize(
    "label,start,end",
    [
        # both pinned in the task's tie-out spec
        ("M4-H5", datetime.date(2024, 6, 19), datetime.date(2025, 6, 18)),
        ("M6-H7", datetime.date(2026, 6, 17), datetime.date(2027, 6, 16)),
    ],
)
def test_matched_swap_dates(label, start, end):
    """Start = IMM of the pack's first contract; end = IMM 12 months later."""
    spec = next(s for s in pack_windows(AS_OF, CITI_CFG) if s.label == label)
    assert (spec.swap_start, spec.swap_end) == (start, end)


def test_citis_own_ed_trade_dates_are_reproduced():
    """*"a matched-maturity (3/18/20-3/17/21) CME swap"* for the H0-Z0 pack.

    The ED trade is the one date pair Citi printed in full, so it pins the
    convention independently of the SOFR table.
    """
    assert imm_date(2020, 3) == datetime.date(2020, 3, 18)
    assert imm_date(2021, 3) == datetime.date(2021, 3, 17)


def test_futures_symbols_are_cme_codes():
    spec = next(s for s in pack_windows(AS_OF, CITI_CFG) if s.label == "M6-H7")
    assert spec.symbols == ("SR3M26", "SR3U26", "SR3Z26", "SR3H27")
    assert futures_symbol(2024, 6) == "SR3M24"


def test_rank_start_one_is_rejected():
    """The 3m roll needs the window one contract nearer, so rank 1 cannot rank."""
    with pytest.raises(ValueError):
        Strat2Config(rank_start=1)


def test_universe_must_cover_the_ranked_packs():
    with pytest.raises(ValueError):
        Strat2Config(n_contracts=13, rank_start=5, n_packs=13)


# ===========================================================================
# (b) the 3m roll identity, with a negative control
# ===========================================================================
def test_roll_identity_holds_on_citis_own_table():
    """``Roll(p) = CA(p) - CA(p one nearer)`` on 12/12 consecutive pairs."""
    implied = CITI_SOFR["ca"].diff().dropna()
    printed = CITI_SOFR["roll"].iloc[1:]
    assert len(implied) == 12
    np.testing.assert_allclose(implied.to_numpy(), printed.to_numpy(), atol=0.011)


def test_roll_identity_negative_control_fails():
    """Reversing the roll column must break the identity on almost every row.

    Without this the identity test would pass on any monotone CA column and
    would be measuring nothing.
    """
    implied = CITI_SOFR["ca"].diff().dropna().to_numpy()
    shuffled = CITI_SOFR["roll"].iloc[1:].to_numpy()[::-1]
    mismatches = int((np.abs(implied - shuffled) > 0.011).sum())
    assert mismatches >= 11, f"only {mismatches}/12 mismatched -- control is vacuous"


def test_ca_minus_model_equals_vs_model_on_citis_table():
    """13/13 exact -- pins the SOFR table's extra Model column assignment."""
    np.testing.assert_allclose(
        (CITI_SOFR["ca"] - CITI_SOFR["model"]).to_numpy(),
        CITI_SOFR["vs_model"].to_numpy(), atol=0.011)


# ===========================================================================
# (c) DV01 identities
# ===========================================================================
def test_pack_dv01_identity():
    """*"buy 1000 of H0-Z0 packs ... and pay $1bn"* -> $100,000/bp both sides."""
    assert DV01_PER_CONTRACT == 25.0
    assert 1000 * 4 * DV01_PER_CONTRACT == 100_000.0
    assert 2000 * 4 * DV01_PER_CONTRACT == 200_000.0


def test_contracts_per_leg_from_ca_dv01():
    cfg = Strat2Config(ca_dv01=100_000.0)
    assert round(cfg.ca_dv01 / (4.0 * DV01_PER_CONTRACT)) == 1000
    cfg2 = Strat2Config(ca_dv01=200_000.0)
    assert round(cfg2.ca_dv01 / (4.0 * DV01_PER_CONTRACT)) == 2000


@pytest.mark.parametrize(
    "ca_dv01,beta,w2,w10,published_5y_notional",
    [
        (100_000.0, 21.4, 0.73, 0.46, -44.4e6),   # 13-Jan-2017
        (200_000.0, 20.6, 0.705, 0.465, -85.6e6),  # 09-Feb-2017
    ],
)
def test_belly_dv01_reproduces_citis_published_notionals(
        ca_dv01, beta, w2, w10, published_5y_notional):
    """``belly_DV01 = CA_DV01 * beta/100``, cross-checked at $480/$1mn 5y DV01."""
    fit = HedgeFit(alpha=0.0, b2=-beta * w2, b5=beta, b10=-beta * w10, beta=beta,
                   w2=w2, w10=w10, r2=1.0, n_obs=252, ok=True)
    sizing = hedge_sizing(fit, ca_dv01)
    assert sizing["belly_dv01"] == pytest.approx(ca_dv01 * beta / 100.0)
    implied = abs(published_5y_notional) * 480.0 / 1e6
    assert sizing["belly_dv01"] / implied == pytest.approx(1.0, abs=0.01)
    assert sizing["wing_2y_dv01"] == pytest.approx(w2 * sizing["belly_dv01"])
    assert sizing["wing_10y_dv01"] == pytest.approx(w10 * sizing["belly_dv01"])


def test_ca_leg_3m_carry_is_the_roll_column_times_dv01():
    """*"$130k from the short CA trade"* = 1.30bp of roll on $100k/bp."""
    assert 1.30 * 100_000.0 == pytest.approx(130_000.0)


def test_hedge_regression_recovers_citis_chart_annotation():
    """``10.2 + 21.4*(-0.73*2y + 5y - 0.47*10y)`` must come back out of a fit.

    A synthetic history is generated FROM Citi's published equation and the
    regression must recover alpha, beta and both wing weights. This checks the
    ``beta = b5, w2 = -b2/beta, w10 = -b10/beta`` algebra, which is where a sign
    slip would flip the hedge into a doubling-up.
    """
    rng = np.random.default_rng(17)
    n = 300
    idx = pd.bdate_range("2016-01-04", periods=n)
    r2 = pd.Series(1.2 + 0.4 * rng.standard_normal(n).cumsum() / math.sqrt(n), index=idx)
    r5 = pd.Series(1.9 + 0.5 * rng.standard_normal(n).cumsum() / math.sqrt(n), index=idx)
    r10 = pd.Series(2.4 + 0.5 * rng.standard_normal(n).cumsum() / math.sqrt(n), index=idx)
    ca = 10.2 + 21.4 * (-0.73 * r2 + r5 - 0.47 * r10)
    rates = pd.DataFrame({"2Y": r2, "5Y": r5, "10Y": r10})
    fit = hedge_regression(ca, rates, Strat2Config(hedge_regression_days=n))
    assert fit.ok
    assert fit.alpha == pytest.approx(10.2, abs=1e-6)
    assert fit.beta == pytest.approx(21.4, abs=1e-6)
    assert fit.w2 == pytest.approx(0.73, abs=1e-6)
    assert fit.w10 == pytest.approx(0.47, abs=1e-6)
    assert fit.r2 == pytest.approx(1.0, abs=1e-9)
    assert fit.fitted_fly_bp(float(r2.iloc[-1]), float(r5.iloc[-1]),
                             float(r10.iloc[-1])) == pytest.approx(float(ca.iloc[-1]))


def test_hedge_is_skipped_when_beta_is_degenerate():
    """A near-zero beta makes ``w2 = -b2/beta`` explode; skip, do not scale."""
    rng = np.random.default_rng(3)
    n = 300
    idx = pd.bdate_range("2016-01-04", periods=n)
    rates = pd.DataFrame({t: 1.0 + 0.1 * rng.standard_normal(n).cumsum() / math.sqrt(n)
                          for t in ("2Y", "5Y", "10Y")}, index=idx)
    ca = pd.Series(rng.standard_normal(n) * 1e-6, index=idx)   # no relationship
    fit = hedge_regression(ca, rates, Strat2Config(hedge_regression_days=n))
    assert not fit.ok and "beta" in fit.reason


# ===========================================================================
# The Ho-Lee model and the sigma fit
# ===========================================================================
def test_sqrt_time_weight_pseudo_t1_is_exact():
    """``pack_time_weight([sqrt(M)]) == M`` -- the shortcut the screen uses."""
    for m in (0.5, 1.0, 4.3, 19.4):
        assert pack_time_weight([math.sqrt(m)], convention="citi") == pytest.approx(m)


def test_fit_recovers_a_planted_variance_term_structure():
    """Plant ``v(T) = c0 + c1 T + c2 T^2``, price the CAs, fit them back."""
    t = np.linspace(1.3, 4.4, 13)
    m = t ** 2 + 0.02                                # M = mean(T1^2), close to T^2
    c = np.array([30000.0, -4000.0, 300.0])          # bp^2
    v = c[0] + c[1] * t + c[2] * t ** 2
    ca = 0.5 * m / 1e4 * v
    sigma, ca_model, coeffs = fit_sigma_model(ca, m, t, degree=2)
    np.testing.assert_allclose(coeffs, c, rtol=1e-6)
    np.testing.assert_allclose(sigma, np.sqrt(v), rtol=1e-8)
    np.testing.assert_allclose(ca_model, ca, rtol=1e-8)


def test_fit_on_citis_own_ca_column_reproduces_the_shape_of_citis_model():
    """The fitted model tracks Citi's cap-vol model in SHAPE but not in level.

    This is the documented limitation of ``sigma_model_mode="fit"`` stated as a
    test: the residual-centred fit correlates with Citi's externally-calibrated
    model column at >0.99, but sits systematically above it, because Citi's
    ``Vs Model`` carries a level the cross-sectional fit absorbs by
    construction. If this ever started reproducing the LEVEL too, the fit would
    have stopped being what the docstring says it is.
    """
    specs = {s.label: s for s in pack_windows(AS_OF, CITI_CFG)}
    m = np.array([specs[p].time_weight for p in CITI_SOFR.index])
    t = np.array([specs[p].t_mid for p in CITI_SOFR.index])
    _, ca_model, _ = fit_sigma_model(CITI_SOFR["ca"].to_numpy(), m, t, degree=2)
    corr = float(np.corrcoef(ca_model, CITI_SOFR["model"].to_numpy())[0, 1])
    assert corr > 0.99, f"shape lost: corr {corr:.4f}"
    assert ca_model.mean() > CITI_SOFR["model"].mean(), "the level gap is expected"


def test_implied_vol_from_citis_ca_reproduces_citis_implied_vol_column():
    """13/13 rows, median ratio ~0.997 -- the external known answer."""
    specs = {s.label: s for s in pack_windows(AS_OF, CITI_CFG)}
    ratios = []
    for p, row in CITI_SOFR.iterrows():
        w = specs[p].time_weight
        iv = implied_vol_from_ca_bp(float(row["ca"]), [math.sqrt(w)], convention="citi")
        ratios.append(iv / float(row["iv"]))
    ratios = np.array(ratios)
    assert len(ratios) == 13
    assert np.median(ratios) == pytest.approx(0.9973, abs=0.002)
    assert ratios.min() > 0.99 and ratios.max() < 1.0


# ===========================================================================
# The ranking
# ===========================================================================
def _toy_screen() -> pd.DataFrame:
    packs = [f"P{i}" for i in range(6)]
    d = pd.DataFrame(index=pd.Index(packs, name="pack"))
    d["pack"] = packs
    # P5 tops five metrics, P4 tops three -> P5 must be selected
    d["ca_bp"] = [1, 2, 3, 4, 5, 6]
    d["ca_z3m"] = [1, 2, 3, 4, 5, 6]
    d["ca_z1y"] = [1, 2, 3, 4, 5, 6]
    d["vs_model_bp"] = [6, 5, 4, 3, 2, 1]
    d["vs_model_z3m"] = [6, 5, 4, 3, 2, 1]
    d["vs_model_z1y"] = [1, 2, 3, 4, 6, 5]
    d["roll_3m_bp"] = [1, 2, 3, 4, 5, 6]
    d["implied_over_realized"] = [1, 2, 3, 4, 5, 6]
    return d


def test_rank_flags_marks_three_per_metric():
    cfg = Strat2Config()
    flags = rank_flags(_toy_screen(), cfg)
    for m in RANK_METRICS:
        assert int(flags[m].sum()) == 3, m


def test_selection_is_the_pack_flagged_by_the_most_metrics():
    cfg = Strat2Config()
    pick, flags = select_pack(_toy_screen(), cfg)
    assert pick == "P5"
    assert int(flags.loc["P5", "n_flags"]) >= int(flags.loc["P4", "n_flags"])


def test_metrics_with_no_finite_values_do_not_vote():
    cfg = Strat2Config()
    s = _toy_screen()
    s["vs_model_z1y"] = np.nan
    flags = rank_flags(s, cfg)
    assert int(flags["vs_model_z1y"].sum()) == 0
    assert int(flags["ca_bp"].sum()) == 3


def test_min_metrics_flagged_can_hold_the_book_flat():
    cfg = Strat2Config(min_metrics_flagged=99)
    pick, _ = select_pack(_toy_screen(), cfg)
    assert pick is None


def test_ranking_direction_is_high_is_short_convexity():
    """Every metric points the same way: higher = better short-convexity sale.

    Flipping the sign of a metric must move the flag to the other end of the
    cross-section; if it did not, the metric would not be participating.
    """
    cfg = Strat2Config()
    s = _toy_screen()
    assert rank_flags(s, cfg).at["P5", "ca_bp"]
    s2 = s.copy()
    s2["ca_bp"] = -s2["ca_bp"]
    assert not rank_flags(s2, cfg).at["P5", "ca_bp"]
    assert rank_flags(s2, cfg).at["P0", "ca_bp"]


# ===========================================================================
# (a) + (d) live: the market-data tie-out and the sign probes
# ===========================================================================
@pytest.mark.slow
def test_live_ca_snapshot_reproduces_citis_shape():
    """Correlation > 0.95 against Citi's 13 rows on 2023-06-09.

    The LEVEL is not asserted. Citi prices the swap leg CME-cleared and
    ``USD-SOFR-1D`` does not, and the measured offset is about -3.9bp. What is
    asserted is the shape, the row set and the swap dates -- the things a
    clearing basis cannot explain away.
    """
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP

    cfg = CITI_CFG
    fut = STIRFutureMDP(source=cfg.futures_source)
    swp = IRSwapsMDP(source=cfg.swap_source)
    syms = sorted({s for sp in pack_windows(AS_OF, cfg) for s in sp.symbols})
    snap = fut.get_data({"symbols": syms, "timestamp": AS_OF})
    prices = {s: float(v[0].price()) for s, v in snap.items() if v}
    pricer = swp.get_pricer({"curve_name": cfg.curve, "timestamp": AS_OF, "offline": True})
    got = ca_snapshot(AS_OF, cfg, futures_prices=prices, swap_pricer=pricer).set_index("pack")

    common = [p for p in CITI_SOFR.index if p in got.index]
    assert common == list(CITI_SOFR.index), "row set differs from Citi's"
    corr = float(got.loc[common, "ca_bp"].corr(CITI_SOFR["ca"]))
    assert corr > 0.95, f"CA correlation vs Citi is only {corr:.4f}"
    offset = float((got.loc[common, "ca_bp"] - CITI_SOFR["ca"]).median())
    assert -8.0 < offset < 0.0, f"unexpected level offset {offset:.2f}bp"
    # the basis knob must move the level and nothing else
    shifted = ca_snapshot(AS_OF, Strat2Config(**{**cfg.__dict__, "ca_basis_bp": 4.0}),
                          futures_prices=prices, swap_pricer=pricer).set_index("pack")
    np.testing.assert_allclose(shifted.loc[common, "ca_bp"].to_numpy(),
                               got.loc[common, "ca_bp"].to_numpy() + 4.0, atol=1e-9)


@pytest.mark.slow
def test_roll_identity_holds_on_our_own_computed_screen():
    """The identity is a construction in ``daily_screen``; prove it anyway."""
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP

    cfg = CITI_CFG
    fut = STIRFutureMDP(source=cfg.futures_source)
    swp = IRSwapsMDP(source=cfg.swap_source)
    syms = sorted({s for sp in pack_windows(AS_OF, cfg) for s in sp.symbols})
    snap = fut.get_data({"symbols": syms, "timestamp": AS_OF})
    prices = {s: float(v[0].price()) for s, v in snap.items() if v}
    pricer = swp.get_pricer({"curve_name": cfg.curve, "timestamp": AS_OF, "offline": True})
    panel = ca_snapshot(AS_OF, cfg, futures_prices=prices, swap_pricer=pricer)
    screen = daily_screen(AS_OF, panel, cfg)
    by_rank = panel.set_index("rank")["ca_bp"]
    for _, r in screen.iterrows():
        expect = float(by_rank.loc[r["rank"]] - by_rank.loc[r["rank"] - 1])
        assert float(r["roll_3m_bp"]) == pytest.approx(expect, abs=1e-9)
    # negative control: the roll is NOT the difference to the next FURTHER pack
    wrong = [float(by_rank.loc[r["rank"] + 1] - by_rank.loc[r["rank"]])
             for _, r in screen.iterrows() if (r["rank"] + 1) in by_rank.index]
    got = screen["roll_3m_bp"].to_numpy()[:len(wrong)]
    assert int((np.abs(got - np.array(wrong)) > 0.011).sum()) >= len(wrong) - 1


@pytest.mark.slow
def test_outright_bpv_sign_is_payer():
    """``bpv > 0`` must gain in a selloff, and +/- must mirror exactly.

    The 2022-09 CPI week moved 5y rates about 23bp. A regressed
    ``resolve_pricable`` would silently invert every P&L in the strategy.
    """
    from BT.data_handler import TimeGrid
    from BT.query_actions import AddQueryAction, UnwindPositionsAction
    from BT.query_engine import QueryDrivenBacktest
    from BT.query_strategy import QueryStrategy
    from BT.triggers import DateTrigger, DateTriggerRequirements
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    dates = [datetime.date(2022, 9, 12), datetime.date(2022, 9, 13),
             datetime.date(2022, 9, 14), datetime.date(2022, 9, 15)]

    def run(bpv):
        mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
        q = IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV,
                        tenor="5Y", curve=CURVE, structure_kwargs={"bpv": bpv},
                        tags=("probe",))
        strat = QueryStrategy(name=f"p{bpv:+.0f}", triggers=[
            DateTrigger(DateTriggerRequirements(dates=[dates[0]]),
                        actions=[AddQueryAction(query=q, meta={"tags": ["probe"]})]),
            DateTrigger(DateTriggerRequirements(dates=[dates[-1]]),
                        actions=[UnwindPositionsAction(match_tag="probe", fee=0.0)]),
        ])
        bt = QueryDrivenBacktest(time_grid=TimeGrid([pd.Timestamp(d) for d in dates]),
                                 strategy=strat, mdp=mdp, show_progress=False)
        bt.run()
        eq = pd.Series(bt.mtm_history)
        assert len(eq) == len(dates), "engine swallowed a step"
        return float(eq.iloc[-1])

    plus, minus = run(+100_000.0), run(-100_000.0)
    assert plus > 0, "payer must gain in the 2022-09 selloff"
    assert abs(plus + minus) < 1e-6 * abs(plus), "buy/sell must mirror"


@pytest.mark.slow
def test_fly_bpv_positive_pays_the_belly():
    """``risk_weights=[w2, 1, w10]`` + ``bpv>0`` resolves to ``[-w2, +1, -w10]``.

    That is pay-belly / receive-wings, which is Citi's *"pay the belly of the
    2s5s10s swap fly"*. The resolved notionals are also checked against the
    published shape -- 2y and 10y opposite in sign to the 5y.
    """
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
    pricer = mdp.get_pricer({"curve_name": CURVE, "timestamp": AS_OF, "offline": True})
    q = IRSwapQuery(structure=IRSwapStructure.FLY, value=IRSwapValue.PV01, curve=CURVE,
                    structure_kwargs={"front_tenor": "2Y", "belly_tenor": "5Y",
                                      "back_tenor": "10Y",
                                      "risk_weights": [0.73, 1.0, 0.47],
                                      "bpv": 21_400.0})
    package, weights = q.resolve_package(pricer_or_curve=pricer)
    assert weights == [-0.73, 1.0, -0.47]
    resolved = [pricer.resolve_pricable(p, w) for p, w in zip(package, weights)]
    notionals = [float(pricer.notional(p)) for p in resolved]
    assert notionals[1] > 0 > notionals[0] and notionals[2] < 0, notionals
    assert abs(notionals[1]) / 1e6 == pytest.approx(44.4, rel=0.25)


@pytest.mark.slow
def test_fly_risk_weights_list_is_mutated_in_place_by_the_builder():
    """A landmine, pinned: reusing one list across queries corrupts the second.

    ``IRSwapStructure._build_fly`` rewrites ``risk_weights`` through
    ``math.copysign``. ``build_trade_queries`` therefore constructs a fresh list
    per query; this test is what stops that from being quietly "simplified".
    """
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
    pricer = mdp.get_pricer({"curve_name": CURVE, "timestamp": AS_OF, "offline": True})
    shared = [0.73, 1.0, 0.47]
    q = IRSwapQuery(structure=IRSwapStructure.FLY, value=IRSwapValue.PV01, curve=CURVE,
                    structure_kwargs={"front_tenor": "2Y", "belly_tenor": "5Y",
                                      "back_tenor": "10Y", "risk_weights": shared,
                                      "bpv": 21_400.0})
    q.resolve_package(pricer_or_curve=pricer)
    assert shared == [-0.73, 1.0, -0.47], "the in-place mutation stopped happening"


@pytest.mark.slow
def test_long_futures_is_short_the_rate_through_the_engine():
    """100 contracts of SR3M25 over a +4.50bp move must mark -$11,250.

    ``-4.50 * $25 * 100``. This is the leg the strategy's convexity comes from,
    and it is the leg most likely to be silently mis-signed, so it is measured
    end-to-end through ``QueryDrivenBacktest`` rather than asserted from the
    handler's source.
    """
    from BT.data_handler import TimeGrid
    from BT.query_actions import AddQueryAction, UnwindPositionsAction
    from BT.query_engine import QueryDrivenBacktest
    from BT.query_strategy import QueryStrategy
    from BT.triggers import DateTrigger, DateTriggerRequirements
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
    from Query.STIRFutures.STIRFutureQuery import STIRFutureQuery
    from Query.STIRFutures.STIRFutureStructure import STIRFutureStructure
    from Query.STIRFutures.STIRFutureValue import STIRFutureValue

    d0, d1 = datetime.date(2023, 6, 9), datetime.date(2023, 6, 15)
    fut = STIRFutureMDP(source="BARCHART_STIRF-RL")
    swp = IRSwapsMDP(source="CITIVELO_EXCEL")
    p0 = float(fut.get_data({"symbols": ["SR3M25"], "timestamp": d0})["SR3M25"][0].price())
    p1 = float(fut.get_data({"symbols": ["SR3M25"], "timestamp": d1})["SR3M25"][0].price())
    expected = (p1 - p0) * 100.0 * DV01_PER_CONTRACT * 100

    q = STIRFutureQuery(structure=STIRFutureStructure.OUTRIGHT,
                        value=STIRFutureValue.PRICE, symbol="SR3M25",
                        structure_kwargs={"contracts": 100}, tags=("f",))
    dates = [x.date() for x in pd.bdate_range(d0, d1)]
    strat = QueryStrategy(name="fut", triggers=[
        DateTrigger(DateTriggerRequirements(dates=[dates[0]]),
                    actions=[AddQueryAction(query=q, meta={"tags": ["f"]})]),
        DateTrigger(DateTriggerRequirements(dates=[dates[-1]]),
                    actions=[UnwindPositionsAction(match_tag="f", fee=0.0)]),
    ])
    strat.mdps = {"STIRFUTURE": fut, "IRS": swp}
    strat.default_mdp = swp
    bt = QueryDrivenBacktest(time_grid=TimeGrid([pd.Timestamp(d) for d in dates]),
                             strategy=strat, mdp=swp, show_progress=False)
    bt.run()
    eq = pd.Series(bt.mtm_history)
    assert len(eq) == len(dates), "engine swallowed a step"
    assert float(eq.iloc[-1]) == pytest.approx(expected, abs=1.0)
    assert p1 < p0 and float(eq.iloc[-1]) < 0, "price fell, a long must lose"


def test_hedge_enabled_is_the_default_for_run_backtest():
    """The config knob must actually drive the runner, not sit there unread.

    ``run_backtest(hedged=None)`` reads ``cfg.hedge_enabled``; an explicit
    ``hedged=`` overrides it. Checked on the signature and on
    ``build_trade_queries``, which is where the fly leg is added or not.
    """
    import inspect

    from RVUtils.ConvexityRV.strat2_sofr_convexity import (
        TradeSpec, build_trade_queries, run_backtest)

    assert inspect.signature(run_backtest).parameters["hedged"].default is None

    fit = HedgeFit(0.0, -15.6, 21.4, -10.1, 21.4, 0.73, 0.47, 0.9, 252, True)
    spec = TradeSpec(
        entry=datetime.date(2023, 1, 3), exit=datetime.date(2023, 4, 3),
        pack="M4-H5", rank=5,
        symbols=("SR3M24", "SR3U24", "SR3Z24", "SR3H25"),
        swap_start=datetime.date(2024, 6, 19), swap_end=datetime.date(2025, 6, 18),
        contracts_per_leg=1000, ca_dv01=100_000.0, n_flags=6, ca_entry_bp=4.0,
        hedge=fit, hedge_dv01=hedge_sizing(fit, 100_000.0), tag="t")
    cfg = Strat2Config()
    assert len(build_trade_queries(spec, cfg, hedged=False)) == 5   # 4 futures + swap
    assert len(build_trade_queries(spec, cfg, hedged=True)) == 6    # + the fly


def test_a_skipped_hedge_adds_no_fly_leg():
    """An inexpressible regression must drop the leg, not clip it into one."""
    from RVUtils.ConvexityRV.strat2_sofr_convexity import TradeSpec, build_trade_queries

    bad = HedgeFit(0.0, 5.0, 21.4, -10.1, 21.4, -0.23, 0.47, 0.4, 252, False,
                   "wing weight not expressible as a fly")
    spec = TradeSpec(
        entry=datetime.date(2023, 1, 3), exit=datetime.date(2023, 4, 3),
        pack="M4-H5", rank=5,
        symbols=("SR3M24", "SR3U24", "SR3Z24", "SR3H25"),
        swap_start=datetime.date(2024, 6, 19), swap_end=datetime.date(2025, 6, 18),
        contracts_per_leg=1000, ca_dv01=100_000.0, n_flags=6, ca_entry_bp=4.0,
        hedge=bad, hedge_dv01=None, tag="t")
    assert len(build_trade_queries(spec, Strat2Config(), hedged=True)) == 5

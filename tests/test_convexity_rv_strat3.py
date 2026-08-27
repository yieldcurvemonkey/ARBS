"""Strategy 3 — delta-hedged long-dated forward flatteners.

Three layers of check, in increasing order of what they can catch:

1. **Closed-form**, on a synthetic ``PricingContext`` with a known quadratic
   PV. Pins the engine's mechanics — resize target, ``beta``, ``resize_mode``,
   the residual delta a rally builds — with no market data anywhere near it.
2. **Synthetic rateslib curve**. Pins the package algebra (DV01 neutrality,
   convex payoff profile, ``Gamma = dM/1e4``) against real repricing on a
   deliberately inverted long end.
3. **The Citi Figure-7 known answer**, on the banked Citi Velocity curve for
   the close of 2019-05-08. This is an EXTERNAL known answer — eight published
   curve levels, carries, breakevens and realized vols from a note this repo
   did not produce — and it is what would catch a plausible-looking but wrong
   convention that layers 1 and 2 cannot see. Skipped, not failed, when the
   local curve store cannot serve that date offline.
"""
import datetime as dt

import numpy as np
import pandas as pd
import pytest
import rateslib as rl

import RVUtils.ConvexityRV.strat3_strikeless_vol as S3
from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve
from RVUtils.ConvexityRV.curve_ops import payoff_profile
from RVUtils.StrikelessVol.costs import FREE, CostSchedule
from RVUtils.StrikelessVol.greeks import build_package, package_dv01, package_gamma
from RVUtils.StrikelessVol.replication import ReplicationConfig, simulate

BASE_DV01 = 100_000.0
REF = rl.dt(2019, 5, 8)


# ---------------------------------------------------------------------------
# 1. Closed-form engine mechanics
# ---------------------------------------------------------------------------


class SyntheticCtx:
    """A closed-form world: quadratic PV in the long rate, linear time decay.

    Identical in shape to ``tests/test_strikeless_vol_replication.SyntheticCtx``
    so the equivalence test below compares the two engines on exactly the world
    the incumbent's own tests use. ``dv01`` drifts with the rate, which is what
    makes the resize rule bite — that drift IS the gamma being scalped, so a
    synthetic world without it would prove nothing.
    """

    def __init__(self, path_bp, *, theta_per_day=-500.0, gamma=40.0):
        self.dates = pd.date_range("2026-01-01", periods=len(path_bp), freq="B")
        self.path = dict(zip(self.dates, np.asarray(path_bp, dtype=float)))
        self.day_index = {d: i for i, d in enumerate(self.dates)}
        self.theta_per_day = theta_per_day
        self.k = gamma / 1e4

    def rate(self, date, leg):
        base = 0.04 if leg == "long" else 0.045
        return base + self.path[date] * 1e-4

    def dv01(self, date, leg):
        return 1.0 + self.k * self.path[date] if leg == "long" else 1.0

    def theta(self, date, notional_long, notional_short):
        return self.theta_per_day * (notional_long / BASE_DV01)

    def pv(self, date, notional_long, notional_short):
        dr = self.path[date]
        i = self.day_index[date]
        return (notional_long * (dr + 0.5 * self.k * dr * dr) - notional_short * dr
                + self.theta_per_day * i * (notional_long / BASE_DV01))


@pytest.fixture(scope="module")
def sawtooth():
    """+/-30bp round trips: enough to fire a 25bp trigger in both directions."""
    leg = list(np.linspace(0, 30, 16)) + list(np.linspace(30, -30, 31)) + list(np.linspace(-30, 0, 16))
    return SyntheticCtx(leg * 2)


def _cfg(**kw) -> S3.Strat3Config:
    return S3.Strat3Config(short_leg="10Yx10Y", long_leg="20Yx10Y",
                           package_dv01_usd=BASE_DV01, **kw)


def test_engine_matches_strikeless_vol_simulate(sawtooth):
    """At beta=1, resize_mode='neutral' the new engine IS the incumbent.

    ``simulate_strat3`` adds two knobs to ``replication.simulate``; the point of
    adding them in a new function rather than editing the old one is that the
    ``sv_*`` scripts and their pinned tests depend on the old one's exact
    behaviour. This is the check that the addition changed nothing else.
    """
    ref = simulate(sawtooth, sawtooth.dates,
                   ReplicationConfig(trigger_bp=25.0, roll_months=1200,
                                     package_dv01_usd=BASE_DV01), FREE)
    mine = S3.simulate_strat3(sawtooth, sawtooth.dates, _cfg(hedge_threshold_bp=25.0), FREE)
    cols = ["carry", "harvest", "mtm", "cross", "cost", "total",
            "long_notional", "short_notional", "n_hedges"]
    for c in cols:
        assert np.allclose(ref[c].to_numpy(), mine[c].to_numpy(), atol=1e-9, rtol=0), c
    assert mine["n_hedges"].sum() > 0, "a sawtooth that never hedges tests nothing"


def test_beta_scales_the_target_notional(sawtooth):
    """Doc B: "scaling the DV01-neutral notional up by 1.025"."""
    neutral = S3.simulate_strat3(sawtooth, sawtooth.dates, _cfg(hedge_threshold_bp=25.0), FREE)
    tilted = S3.simulate_strat3(sawtooth, sawtooth.dates,
                                _cfg(hedge_threshold_bp=25.0, beta=1.025), FREE)
    ratio = tilted["long_notional"] / neutral["long_notional"]
    assert np.allclose(ratio.to_numpy(), 1.025, atol=1e-12)
    # ... and the tilt is exactly the 2.5% of residual delta it claims to be
    assert np.isclose(tilted["package_dv01_usd"].iloc[0], -0.025 * BASE_DV01, rtol=1e-9)
    assert np.isclose(neutral["package_dv01_usd"].iloc[0], 0.0, atol=1e-6)


def test_always_decrease_never_grows_the_long_leg(sawtooth):
    """The PM's self-liquidating variant: "always decrease ... the delta
    hedging eventually is also an exit if you feel like it"."""
    led = S3.simulate_strat3(sawtooth, sawtooth.dates,
                             _cfg(hedge_threshold_bp=25.0, resize_mode="always_decrease"), FREE)
    steps = led["long_notional"].abs().diff().dropna()
    assert (steps <= 1e-9).all(), "always_decrease grew the long leg"
    assert led["long_notional"].abs().iloc[-1] < led["long_notional"].abs().iloc[0], \
        "always_decrease never shrank anything on a path that round-trips 60bp"


def test_hedging_a_round_trip_harvests_positive_gamma(sawtooth):
    """The whole thesis, in one number: resizing on a round trip books money."""
    hedged = S3.simulate_strat3(sawtooth, sawtooth.dates, _cfg(hedge_threshold_bp=25.0), FREE)
    never = S3.simulate_strat3(sawtooth, sawtooth.dates, _cfg(hedge_threshold_bp=1e6), FREE)
    assert hedged["harvest"].sum() > 0
    assert never["harvest"].sum() == pytest.approx(0.0, abs=1e-9)


def test_resize_mode_is_validated(sawtooth):
    with pytest.raises(ValueError, match="resize_mode"):
        S3.simulate_strat3(sawtooth, sawtooth.dates, _cfg(resize_mode="whatever"), FREE)


def test_tighter_thresholds_hedge_more_often(sawtooth):
    counts = {t: int(S3.simulate_strat3(sawtooth, sawtooth.dates,
                                        _cfg(hedge_threshold_bp=t), FREE)["n_hedges"].sum())
              for t in (10.0, 25.0, 40.0)}
    assert counts[10.0] > counts[25.0] > counts[40.0], counts


# ---------------------------------------------------------------------------
# 2. Package algebra on a synthetic rateslib curve
# ---------------------------------------------------------------------------


def _inverted_curve():
    """A long end that inverts beyond 20y — the shape the trade exists for.

    Zero rates rise to 20y then fall away, so the ultra-long forward curve is
    inverted (Doc A Figure 1) and a flattener rolls negatively, exactly as the
    note describes. USD-OIS is act360 on both the curve and ``usd_irs``'s legs,
    which is the production pairing.
    """
    nodes = {REF: 1.0}
    df = 1.0
    for y in range(1, 56):
        z = 0.025 + 0.012 * min(y, 20) / 20.0 - 0.004 * max(y - 20, 0) / 35.0
        nodes[rl.dt(2019 + y, 5, 8)] = float(np.exp(-z * y))
    handle = rl.Curve(nodes=nodes, convention="act360", calendar="nyc", id="inv")
    return RLIRSwapCurve(rl_curve_id="USD-OIS", rl_curve_handle=handle,
                         fixings=rl.NoInput(0),
                         meta_data={"reference_curve_name": "USD-OIS"})


@pytest.fixture(scope="module")
def inv_curve():
    return _inverted_curve()


@pytest.mark.parametrize("short,long", S3.PAIRS_15)
def test_package_is_dv01_neutral_at_inception(inv_curve, short, long):
    """Tie-out (b). The measure is a repriced central difference, not the
    analytic annuity: sizing on one and checking on the other is how a
    directional residual gets into a package that claims to have none."""
    pair = S3.forward_pair(short, long, curve_name="USD-OIS")
    pkg = build_package(inv_curve, pair, package_dv01_usd=BASE_DV01, sign=+1)
    assert abs(package_dv01(inv_curve, pkg)) < 1e-4 * BASE_DV01


@pytest.mark.parametrize("short,long", S3.PAIRS_15)
def test_flattener_gamma_matches_the_delta_m_reconstruction(inv_curve, short, long):
    """Tie-out (c), first half: the flattener is long convexity, and the
    magnitude is the spec's ``Gamma = dM/10000`` bp per bp^2 per unit DV01.

    Citi never publishes a gamma; the spec inverts one from the published
    carry/breakeven pairs. This checks that reconstruction against a direct
    second-difference reprice — a genuinely independent route to the same
    number, which is what makes the reconstruction usable.
    """
    pair = S3.forward_pair(short, long, curve_name="USD-OIS")
    pkg = build_package(inv_curve, pair, package_dv01_usd=BASE_DV01, sign=+1)
    measured = package_gamma(inv_curve, pkg, h_bp=25.0)
    theory = 2.0 * (S3.delta_m_years(short, long) / 1e4) * BASE_DV01
    assert measured > 0, "a flattener must be positively convex"
    assert measured == pytest.approx(theory, rel=0.10)


def _pkg_dv01_on(handle, pkg, h_bp: float = 1.0) -> float:
    """Dollars per bp of a package on an ARBITRARY handle, positive = gains
    when rates rise. Independent of everything under test."""
    def npv(hh):
        return float(pkg.short.npv(curves=hh).real + pkg.long.npv(curves=hh).real)

    return (npv(handle.shift(h_bp)) - npv(handle.shift(-h_bp))) / (2.0 * h_bp)


@pytest.mark.parametrize("move_bp,expect_sign", [(-100.0, -1.0), (+100.0, +1.0)])
def test_unhedged_package_builds_delta_after_a_big_move(inv_curve, move_bp, expect_sign):
    """Tie-out (e), the economics. No resize happens, so what is left is gamma.

    A rally makes the RECEIVED longer leg's DV01 grow faster than the paid
    shorter leg's, so the package goes net-received — long duration, gaining if
    rates keep falling. In the "positive = gains when rates rise" convention a
    rallied flattener must therefore show a NEGATIVE residual delta, and a
    sold-off one a positive residual. That asymmetry is the entire strategy:
    the resize sells the delta the rally built and buys back the delta the
    selloff destroyed, always at a profit versus entry.
    """
    pair = S3.forward_pair("10Yx10Y", "20Yx10Y", curve_name="USD-OIS")
    pkg = build_package(inv_curve, pair, package_dv01_usd=BASE_DV01, sign=+1)
    handle = inv_curve.handle()
    assert abs(_pkg_dv01_on(handle, pkg)) < 1e-4 * BASE_DV01
    residual = _pkg_dv01_on(handle.shift(move_bp), pkg)
    assert abs(residual) > 0.005 * BASE_DV01, \
        f"a {move_bp:+g}bp move left only {residual:+,.0f} of delta"
    assert np.sign(residual) == expect_sign, f"{move_bp:+g}bp -> {residual:+,.0f}"


def test_flattener_payoff_profile_is_convex(inv_curve):
    """Tie-out (c), second half: the SHIFT profile, via ``curve_ops``.

    ``payoff_profile`` is used with ``horizon_date=None`` on purpose. Its ageing
    path uses ``rl.Curve.translate``, which returns exactly zero carry for a
    par-struck, not-yet-started forward package — measured on real curves at
    both a 1-day and a 1-year horizon, and pinned upstream by
    ``test_translate_yields_no_carry_for_a_par_struck_forward_package``. The
    shift-only profile is unaffected and is what the convexity claim needs.
    """
    pair = S3.forward_pair("10Yx10Y", "20Yx10Y", curve_name="USD-OIS")
    pkg = build_package(inv_curve, pair, package_dv01_usd=BASE_DV01, sign=+1)
    shifts = np.array([-250, -200, -150, -100, -50, -25, 0, 25, 50, 100, 150, 200, 250], float)
    handle = inv_curve.handle()
    base = float(pkg.short.npv(curves=handle).real + pkg.long.npv(curves=handle).real)
    prof = np.array([float(pkg.short.npv(curves=handle.shift(s)).real
                           + pkg.long.npv(curves=handle.shift(s)).real) - base
                     for s in shifts])
    assert (np.diff(prof, 2) > 0).all(), f"payoff is not convex: {prof}"
    assert prof[shifts == 0][0] == pytest.approx(0.0, abs=1.0)
    assert prof[0] > 0 and prof[-1] > 0, "both wings of a long-gamma profile pay"


def test_payoff_profile_kernel_agrees_with_direct_repricing(inv_curve):
    """``curve_ops.payoff_profile`` and a hand-rolled shift loop must agree —
    the shared regression table was produced with the former."""
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    q = IRSwapQuery(structure=IRSwapStructure.CURVE, value=IRSwapValue.NPV, curve="USD-OIS",
                    structure_kwargs={"front_tenor": "10Yx10Y", "back_tenor": "20Yx10Y",
                                      "bpv": -BASE_DV01})
    pkg, w = q.resolve_package(pricer_or_curve=inv_curve)
    pkg = [inv_curve.resolve_pricable(p, rw) for p, rw in zip(pkg, w)]
    shifts = [-100, -50, -25, 0, 25, 50, 100]
    prof = payoff_profile(inv_curve, pkg, shifts, horizon_date=None)
    assert (np.diff(prof, 2) > 0).all(), f"CURVE-query flattener is not convex: {prof}"
    assert prof[shifts.index(0)] == pytest.approx(0.0, abs=1.0)


def test_translate_gives_no_carry_so_the_exact_breakeven_uses_roll(inv_curve):
    """Why ``be_daily_exact`` is not built on ``payoff_profile(horizon_date=...)``.

    Recorded as a test rather than a comment because the brief names that
    function, and a reader who does not know this will get a breakeven of zero
    and no error.
    """
    pair = S3.forward_pair("10Yx10Y", "20Yx10Y", curve_name="USD-OIS")
    pkg = build_package(inv_curve, pair, package_dv01_usd=BASE_DV01, sign=+1)
    handle = inv_curve.handle()

    def npv(h):
        return float(pkg.short.npv(curves=h).real + pkg.long.npv(curves=h).real)

    base = npv(handle)
    horizon = (pd.Timestamp(REF) + pd.DateOffset(years=1)).to_pydatetime()
    assert npv(handle.translate(horizon)) - base == pytest.approx(0.0, abs=1.0)
    assert abs(npv(handle.roll(horizon)) - base) > 1_000.0


def test_screen_frame_on_a_synthetic_inverted_curve(inv_curve):
    scr = S3.screen_frame(inv_curve, S3.PAIRS_15, asof=dt.date(2019, 5, 8),
                          curve_name="USD-OIS").set_index("pair")
    assert len(scr) == len(S3.PAIRS_15)
    assert scr["package_dv01_usd"].abs().max() < 1e-4 * BASE_DV01     # tie-out (b)
    assert (scr["gamma_usd_bp2"] > 0).all()                            # long convexity
    assert (scr["gamma_ratio"].between(0.9, 1.1)).all()                # dM/1e4 holds
    assert (scr["level_bp"] < 0).all(), "the fixture's long end is inverted by design"
    neg = scr["carry_1y_bp"] < 0
    assert (scr.loc[~neg, "be_daily_analytic"] == 0).all(), \
        "breakeven must be exactly zero where carry is non-negative"
    assert (scr.loc[neg, "be_daily_analytic"] > 0).all()
    ratio = scr.loc[neg, "be_daily_exact"] / scr.loc[neg, "be_daily_analytic"]
    assert ratio.between(0.95, 1.05).all(), ratio.to_dict()


# ---------------------------------------------------------------------------
# 3. Pure helpers
# ---------------------------------------------------------------------------


def test_parse_and_delta_m():
    assert S3.parse_fwd("20Yx10Y") == (20.0, 10.0)
    assert S3.delta_m_years("10Yx10Y", "20Yx10Y") == 10.0
    assert S3.delta_m_years("15Yx5Y", "20Yx10Y") == 7.5
    assert S3.delta_m_years("10Yx10Y", "25Yx10Y") == 15.0
    assert S3.delta_m_years("20Yx5Y", "25Yx5Y") == 5.0


def test_the_universe_is_the_published_fifteen():
    assert len(S3.PAIRS_15) == 15
    assert len(set(S3.PAIRS_15)) == 15
    assert S3.leg_labels() == ["10Yx10Y", "15Yx15Y", "20Yx5Y", "20Yx10Y", "20Yx15Y",
                               "25Yx5Y", "25Yx10Y", "15Yx5Y", "15Yx10Y"]
    # every pair's long leg must genuinely be the longer-dated one, or the
    # convexity sign of the whole study is inverted
    for s, l in S3.PAIRS_15:
        assert S3.delta_m_years(s, l) > 0, (s, l)


def test_fig9_cost_tiers():
    tight = S3.cost_schedule_for("10Yx10Y", "20Yx10Y")
    wide = S3.cost_schedule_for("10Yx10Y", "25Yx10Y")
    unpublished = S3.cost_schedule_for("15Yx10Y", "25Yx10Y")
    assert (tight.initiate_bp, tight.hedge_bp, tight.roll_bp) == (0.75, 0.30, 0.30)
    assert (wide.initiate_bp, wide.hedge_bp, wide.roll_bp) == (1.00, 0.40, 0.40)
    assert (unpublished.initiate_bp, unpublished.hedge_bp) == S3.DEFAULT_COST_BP
    # Doc A l.155: "We assume the same bid/offer for the roll as for delta-hedging."
    for pair in S3.PAIRS_15:
        s = S3.cost_schedule_for(*pair)
        assert s.roll_bp == s.hedge_bp
    # 0.75bp on a $100k/bp package is $75,000 per initiation
    assert tight.cost_usd("initiate", 100_000.0) == pytest.approx(75_000.0)


def test_citi_fig4_sharpe_is_the_published_annualisation():
    """Sharpe = avg daily / daily vol * sqrt(252), exact to 2dp on all eight
    columns. Pins the convention ``book_stats`` reports in."""
    for pair, sharpe in S3.CITI_FIG4_SHARPE.items():
        mu_k, sd_k = S3.CITI_FIG4_DAILY_K[pair]
        assert round(mu_k / sd_k * np.sqrt(252.0), 2) == sharpe, pair


def test_roll_segments_share_their_boundary_date():
    days = list(pd.bdate_range("2019-01-01", "2023-12-29"))
    segs = S3.roll_segments(days, 12)
    assert segs[0][0] == 0 and segs[-1][1] == len(days) - 1
    for (a, b), (c, d) in zip(segs, segs[1:]):
        assert b == c, "the roll date must belong to both segments"
    for (i, j) in segs[:-1]:
        assert (days[j] - days[i]).days >= 360


def test_stitch_relabels_later_openings_as_rolls(sawtooth):
    dates = list(sawtooth.dates)
    a = S3.simulate_strat3(sawtooth, dates[:40], _cfg(), FREE)
    b = S3.simulate_strat3(sawtooth, dates[39:], _cfg(), FREE)
    out = S3.stitch_segments([a, b])
    assert out.index.is_monotonic_increasing and not out.index.duplicated().any()
    assert out["initiate_dv01_usd"].sum() == pytest.approx(BASE_DV01)
    assert out["roll_dv01_usd"].sum() == pytest.approx(BASE_DV01)
    assert out["n_rolls"].sum() == 1
    # the shared boundary date earns both segments' flows exactly once
    assert len(out) == len(dates)


def test_book_stats_sharpe_and_carry_split(sawtooth):
    led = S3.simulate_strat3(sawtooth, sawtooth.dates, _cfg(hedge_threshold_bp=25.0), FREE)
    st = S3.book_stats(led, package_dv01_usd=BASE_DV01)
    net = st["net_daily"]
    assert st["sharpe"] == pytest.approx(net.mean() / net.std(ddof=1) * np.sqrt(252.0))
    assert st["total_net_usd"] == pytest.approx(led["total"].sum())
    # the buckets partition gross exactly -- that is what lets a grid cell
    # report "long vol AND paid to hold it" rather than one blended number
    assert (st["carry_usd"] + st["harvest_usd"] + st["mtm_usd"]) == pytest.approx(
        st["total_gross_usd"], abs=1e-6 * max(abs(st["total_gross_usd"]), 1.0))
    assert st["carry_usd"] < 0, "the synthetic world has negative theta by construction"
    assert st["harvest_usd"] > 0


def test_entry_state_is_lagged_and_gates(sawtooth):
    idx = pd.bdate_range("2020-01-01", periods=10)
    scr = pd.DataFrame({"zs_3y": [0, 0, 3, 3, 3, 0, 0, 0, 0, 0],
                        "be_over_rv": 0.1, "carry_1y_bp": -1.0}, index=idx)
    cfg = _cfg(entry_rule="z", z_window="3y", z_min=1.0)
    st = S3.entry_state(scr, cfg, idx)
    assert st.iloc[0] == 0 and st.iloc[2] == 0, "state must be LAG-1"
    assert list(st.to_numpy()) == [0, 0, 0, 1, 1, 1, 0, 0, 0, 0]
    assert (S3.entry_state(scr, _cfg(entry_rule="always"), idx) == 1).all()
    assert (S3.entry_state(scr, _cfg(entry_rule="carry", carry_min_bp=0.0), idx) == 0).all()


def test_config_round_trips():
    cfg = S3.Strat3Config()
    assert cfg.pair == ("15Yx5Y", "20Yx10Y")
    assert cfg.pair_name == "15Yx5Y/20Yx10Y"
    assert cfg.with_(beta=1.025).beta == 1.025 and cfg.beta == 1.0
    assert cfg.to_dict()["start"] == "2019-01-01"


# ---------------------------------------------------------------------------
# 4. The external known answer — Citi Figure 7, close of 2019-05-08
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def citi_2019_05_08():
    try:
        from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

        mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
        return mdp.get_pricer({"curve_name": "USD-SOFR-1D",
                               "timestamp": dt.date(2019, 5, 8), "offline": True})
    except Exception as exc:  # noqa: BLE001 - a cold cache is not a test failure
        pytest.skip(f"local Citi curve store cannot serve 2019-05-08 offline: {exc!r}")


def test_citi_figure_7_levels_and_carry(citi_2019_05_08):
    """The external tie-out. Levels within 1.5bp, carry within 1bp.

    The residual is a curve-construction difference, not a convention error:
    every level is uniformly ~0.8bp more negative than Citi's and every carry
    uniformly ~0.4bp less negative, on a SOFR curve this repo rebuilds from
    banked par rates while Citi quoted its own. What matters is that the RANK
    ORDER is exact — which pair is the cheapest convexity is the decision the
    screen exists to make, and it is reproduced.
    """
    pairs = list(S3.CITI_FIG7_SCREEN)
    scr = S3.screen_frame(citi_2019_05_08, pairs, asof=dt.date(2019, 5, 8)).set_index("pair")
    d_lvl, d_carry = {}, {}
    for (s, l), pub in S3.CITI_FIG7_SCREEN.items():
        row = scr.loc[f"{s}/{l}"]
        d_lvl[f"{s}/{l}"] = row["level_bp"] - pub[0]
        d_carry[f"{s}/{l}"] = row["carry_1y_bp"] - pub[3]
    assert max(abs(v) for v in d_lvl.values()) < 1.5, d_lvl
    assert max(abs(v) for v in d_carry.values()) < 1.0, d_carry

    pub_carry = np.array([S3.CITI_FIG7_SCREEN[p][3] for p in pairs])
    ours = np.array([scr.loc[f"{s}/{l}", "carry_1y_bp"] for s, l in pairs])
    assert np.corrcoef(ours, pub_carry)[0, 1] > 0.95
    from scipy.stats import spearmanr

    # MEASURED, not aspirational: rho = 0.976, one adjacent transposition
    # (10y10y/20y15y and 10y10y/25y10y swap places; our carries differ by
    # 0.002bp, Citi's by 0.05bp, so the pair is a coin flip on either curve).
    # Every other rank is identical, including all three of the trades the note
    # actually recommends.
    assert spearmanr(ours, pub_carry).statistic > 0.95, \
        "the carry RANKING is the screen's actual output and must survive"


def test_citi_figure_7_dv01_neutrality_and_gamma(citi_2019_05_08):
    """Tie-outs (b) and (c) on the real curve, at the published date."""
    scr = S3.screen_frame(citi_2019_05_08, S3.PAIRS_15, asof=dt.date(2019, 5, 8))
    assert scr["package_dv01_usd"].abs().max() < 1e-6 * BASE_DV01
    assert (scr["gamma_usd_bp2"] > 0).all()
    assert scr["gamma_ratio"].between(0.95, 1.05).all(), scr["gamma_ratio"].describe()
    neg = scr["carry_1y_bp"] < 0
    ratio = scr.loc[neg, "be_daily_exact"] / scr.loc[neg, "be_daily_analytic"]
    assert ratio.between(0.98, 1.02).all(), \
        f"analytic and repriced breakevens disagree by more than 2%: {ratio.describe()}"


def test_both_carry_paths_tie_out_to_citi(citi_2019_05_08):
    """Two independent carry paths, one published answer.

    HISTORY: this test used to assert the opposite — that
    ``CARRY_AND_ROLL_BPS_RUNNING`` correlated -0.136 against the repriced
    roll's +0.991, and that the repriced roll was therefore the only usable
    field. Two defects produced that number and both are fixed: the query value
    aged a forward-starting leg by shortening its TAIL instead of bringing its
    START nearer (``Query.IRSwaps._carry_roll``), and ``_query_carry_1y`` asked
    for the opposite trade direction (``bpv < 0``). Measured 2026-08-27 the two
    paths agree: +0.991 / MAE 0.338 bp (query) against +0.991 / 0.354
    (repriced).

    MUTATION: restore either defect and the agreement bound below fails —
    the tail-ageing rule alone moves the query MAE to 1.578 bp.
    """
    pairs = list(S3.CITI_FIG7_SCREEN)
    scr = S3.screen_frame(citi_2019_05_08, pairs, asof=dt.date(2019, 5, 8),
                          include_query_carry=True).set_index("pair")
    pub = np.array([S3.CITI_FIG7_SCREEN[p][3] for p in pairs])
    repriced = np.array([scr.loc[f"{s}/{l}", "carry_1y_bp"] for s, l in pairs])
    queried = np.array([scr.loc[f"{s}/{l}", "carry_query_bp"] for s, l in pairs])
    assert np.corrcoef(repriced, pub)[0, 1] > 0.95
    assert np.corrcoef(queried, pub)[0, 1] > 0.95
    # both within the published table's own 2dp granularity plus the leg gap
    assert np.abs(repriced - pub).mean() < 0.60
    assert np.abs(queried - pub).mean() < 0.60
    # and within half a bp of EACH OTHER, pairwise
    assert np.max(np.abs(repriced - queried)) < 0.50


def _covid_ctx(start, end):
    try:
        from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
        from RVUtils.StrikelessVol.citivelo import stored_dates
        from RVUtils.StrikelessVol.replication import CurvePricer

        days = stored_dates("USD", start, end)
        cm = IRSwapsMDP(source="CITIVELO_EXCEL").bulk_get_data(
            {"curve_name": "USD-SOFR-1D", "timestamps": days, "offline": True})
        cm = {pd.Timestamp(k): v for k, v in cm.items() if v is not None and k != "live"}
        assert len(cm) > 8
        return CurvePricer(cm, S3.forward_pair("10Yx10Y", "20Yx10Y"),
                           package_dv01_usd=BASE_DV01)
    except Exception as exc:  # noqa: BLE001 - a cold cache is not a test failure
        pytest.skip(f"store cannot serve {start}..{end} offline: {exc!r}")


def test_engine_residual_delta_sign_across_the_2020_rally():
    """Tie-out (e) through the engine itself, on the real Covid rally.

    2020-02-19 -> 2020-03-09: the largest clean one-way rally in the sample.
    Held unhedged, the flattener's package delta must go NEGATIVE — the
    RECEIVED longer leg's DV01 grows faster than the paid shorter leg's, so the
    package becomes net-received and gains if rates fall further. Running the
    25bp trigger must take that delta back out. Nothing synthetic: this is
    exactly the mechanic the PM described ("recalc the delta on the trades you
    do every 25 bp and then resize the notionals back to be dv01 neutral").
    """
    ctx = _covid_ctx(dt.date(2020, 2, 19), dt.date(2020, 3, 9))
    days = ctx.dates()
    move_bp = (ctx.rate(days[-1], "long") - ctx.rate(days[0], "long")) * 1e4
    assert move_bp < -40.0, f"expected a big rally, got {move_bp:+.1f}bp"

    naked = S3.simulate_strat3(ctx, days, _cfg(hedge_threshold_bp=1e6), FREE)
    assert naked["n_hedges"].sum() == 0
    assert abs(naked["package_dv01_usd"].iloc[0]) < 1e-6 * BASE_DV01     # (b)
    residual = naked["package_dv01_usd"].iloc[-1]
    assert residual < -0.005 * BASE_DV01, (
        f"a {move_bp:+.0f}bp rally left residual delta {residual:+,.0f}; a "
        f"received longer leg gaining DV01 must leave a NEGATIVE package delta")

    hedged = S3.simulate_strat3(ctx, days, _cfg(hedge_threshold_bp=25.0), FREE)
    assert hedged["n_hedges"].sum() >= 1
    assert abs(hedged["package_dv01_usd"].iloc[-1]) < 0.25 * abs(residual)


def test_delta_hedging_harvests_a_real_round_trip_and_pays_for_a_trend():
    """The strategy's whole claim, measured on 2020's round trip.

    The 20y10y rate started 2020 at ~180bp, collapsed to ~31bp in March and
    finished at ~136bp. Over that path, held at $100k DV01 and hedged at 25bp,
    the resizes book roughly +$1.0mn of harvest against +$0.1mn for the same
    package left unhedged — the hedge, not the direction, is where the money is
    ("Everytime you will be 'taking profit'").

    The one-way leg of that path does the OPPOSITE, and it is worth pinning
    rather than hiding: over 2020-02-19..2020-03-09 alone, hedging a monotone
    rally sells delta the market then keeps rewarding, so ``harvest`` is
    negative there. Long gamma pays for round trips, not for trends. A test
    that asserted "resizes always book money" would be asserting something
    false about the strategy.
    """
    ctx = _covid_ctx(dt.date(2020, 1, 2), dt.date(2020, 12, 31))
    days = ctx.dates()
    hedged = S3.simulate_strat3(ctx, days, _cfg(hedge_threshold_bp=25.0), FREE)
    naked = S3.simulate_strat3(ctx, days, _cfg(hedge_threshold_bp=1e6), FREE)
    assert hedged["harvest"].sum() > 0.5e6
    assert hedged["total"].sum() > 5.0 * naked["total"].sum()
    assert naked["harvest"].sum() == pytest.approx(0.0, abs=1e-9)
    assert hedged["carry"].sum() < 0, "a flattener on an inverted long end bleeds"

    trend_ctx = _covid_ctx(dt.date(2020, 2, 19), dt.date(2020, 3, 9))
    trend = S3.simulate_strat3(trend_ctx, trend_ctx.dates(),
                               _cfg(hedge_threshold_bp=25.0), FREE)
    assert trend["harvest"].sum() < 0


def test_the_shared_regression_payoff_table(citi_2019_05_08):
    """The committed 2022-09-13 payoff profile, to the published decimal.

    Different date from the rest of this block, so it builds its own curve; it
    is the regression check the shared brief supplies for ``payoff_profile``
    and the CURVE-query package, and it is what would catch a change in the
    query layer's risk-weight resolution.
    """
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    try:
        p = IRSwapsMDP(source="CITIVELO_EXCEL").get_pricer(
            {"curve_name": "USD-SOFR-1D", "timestamp": dt.date(2022, 9, 13), "offline": True})
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"store cannot serve 2022-09-13 offline: {exc!r}")

    expected = {
        ("20Yx5Y", "25Yx5Y"): [60.0, 33.7, 16.5, 6.4, 1.3, 0.3, 0.0, 0.4, 1.2, 4.2, 8.2, 12.8, 17.5],
        ("30Y", "50Y"): [137.9, 82.1, 44.7, 20.9, 6.9, 2.7, 0.0, -1.4, -1.8, -0.1, 3.9, 9.5, 15.9],
        ("10Yx10Y", "20Yx10Y"): [104.9, 60.0, 29.9, 11.6, 2.3, 0.4, 0.0, 0.9, 2.9, 9.5, 18.7, 29.7, 41.7],
    }
    shifts = [-250, -200, -150, -100, -50, -25, 0, 25, 50, 100, 150, 200, 250]
    for (front, back), want in expected.items():
        q = IRSwapQuery(structure=IRSwapStructure.CURVE, value=IRSwapValue.NPV,
                        curve="USD-SOFR-1D",
                        structure_kwargs={"front_tenor": front, "back_tenor": back,
                                          "bpv": -BASE_DV01})
        pkg, w = q.resolve_package(pricer_or_curve=p)
        pkg = [p.resolve_pricable(x, rw) for x, rw in zip(pkg, w)]
        got = payoff_profile(p, pkg, shifts, horizon_date=None) / BASE_DV01
        assert np.allclose(np.round(got, 1), want, atol=0.05), \
            f"{front}/{back}: {np.round(got, 1).tolist()} != {want}"

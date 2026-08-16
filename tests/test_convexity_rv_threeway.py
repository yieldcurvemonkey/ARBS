"""Known-answer tests for the THREE-WAY study (curve vs swaption vs listed).

Three tiers, so the fast gate stays fast:

* **Hand-computed / synthetic** (no I/O). A tiny panel whose three vols are
  chosen so the cheapest source, the ranking, every gate and the resulting
  cohort P&L are known on paper before the code runs.
* **Algebraic identities** (no I/O). The ``both`` == ``cheapest`` identity is
  swept across a grid of configurations, and the linearity identity that the
  whole gate-book derivation rests on is pinned in both directions.
* **Data-backed** (``@pytest.mark.slow``, skipped when the parquet is absent).
  The two tie-outs that make the study trustworthy: recomputed signals must
  equal the stored strategy-1-listed signals row-for-row on the intersection,
  and replaying the stored direction through :func:`apply_gate` must reproduce
  the stored cohort P&L to machine precision.

**Verifying the checker itself.** A test that passes against mutated code is a
test that does not test, so ten plausible wrong implementations were planted in
``strat1_threeway.py`` and the suite re-run against each. **Measured log:**

=================================================  ========  =====================
mutation                                           result    caught by
=================================================  ========  =====================
drop the ``direction *`` in ``unit_cohort_table``  CAUGHT    replays_stored_direction
charge the round-trip cost once, not twice         CAUGHT    replays_stored_direction
``abs()`` the gated gross P&L                      CAUGHT    flip_negates_pnl
charge cost on UNTRADED cohorts                    CAUGHT    standing_aside_costs_nothing
multiple-testing correction with the wrong sign    CAUGHT    expected_max_sharpe_rises
drop the gate lag (look-ahead)                     CAUGHT    lag_shifts_the_gate
``both`` computed as an OR, not an AND             CAUGHT    both_equals_cheapest
scale the curve vol before comparing (unit error)  CAUGHT    no_time_to_expiry_scaling
basis as listed - swaption (sign flip)             CAUGHT    basis_sign_is_swaption_minus
rank NaN as cheapest instead of last               **INERT** -- see below
=================================================  ========  =====================

Nine of ten were caught. The tenth is reported honestly rather than papered
over: the NaN fill in the ranking is **provably unreachable in the output**,
because a NaN can only occur where ``usable`` is False and every rank and label
is masked there. Flipping it changes no value the module returns, so it is a
semantically inert mutation, not an escaped bug.
``test_unusable_rows_carry_no_ranking`` pins the invariant that makes it inert,
so if a future change relaxes ``usable`` the mutation becomes live and catchable.
"""

from __future__ import annotations

import math
import pathlib

import numpy as np
import pandas as pd
import pytest

from RVUtils.ConvexityRV import strat1_threeway as tw

DATA = pathlib.Path(__file__).resolve().parents[1] / "notebooks" / "data" / "convexity_rv"
PANEL = DATA / "strat1_listed_signal_panel.parquet"


# --------------------------------------------------------------------- fixtures


def _synthetic_panel() -> pd.DataFrame:
    """Six dates x one structure, with every ranking case planted by hand.

    Columns follow the strategy-1-listed panel exactly, so the same
    ``threeway_frame`` call serves both. Rows, as (curve, swaption, listed) in
    bp/day, and the answer each is planted to produce:

    ======  =====  ========  ======  ==================================
    date    curve  swaption  listed  planted answer
    ======  =====  ========  ======  ==================================
    d0        4.0       6.0     7.0  curve cheapest; both signals CHEAP
    d1        9.0       6.0     7.0  curve richest;  both signals RICH
    d2        6.5       6.0     7.0  MIXED: rich vs swaption, cheap vs
                                     listed -> ``both`` stands aside
    d3        0.0       6.0     7.0  ``always_cheap`` sentinel
    d4        inf       6.0     7.0  ``never_cheap`` sentinel
    d5        5.0       NaN     7.0  swaption missing -> unusable
    ======  =====  ========  ======  ==================================
    """
    dates = pd.to_datetime(["2025-01-06", "2025-01-07", "2025-01-08",
                            "2025-01-09", "2025-01-10", "2025-01-13"])
    curve = [4.0, 9.0, 6.5, 0.0, np.inf, 5.0]
    swpn = [6.0, 6.0, 6.0, 6.0, 6.0, np.nan]
    listed = [7.0, 7.0, 7.0, 7.0, 7.0, 7.0]
    return pd.DataFrame({
        "date": dates,
        "structure": ["1Yx2Y/2Yx2Y"] * 6,
        "breakeven_vol_bp_day": curve,
        "otc_atmf_bp_day": swpn,
        "listed_atm_bp_day": listed,
        "breakeven_status": ["root", "root", "root", "always_cheap",
                             "never_cheap", "root"],
    })


def _cfg(**kw):
    base = dict(structures=(("1Yx2Y/2Yx2Y", "1Yx2Y", "2Yx2Y"),),
                start=pd.Timestamp("2024-01-01").date(),
                end=pd.Timestamp("2027-01-01").date())
    base.update(kw)
    return tw.Strat1ThreeWayConfig(**base)


@pytest.fixture
def three() -> pd.DataFrame:
    return tw.threeway_frame(_synthetic_panel(), _cfg())


# -------------------------------------------------------------- the three vols


def test_ranking_is_planted_row_by_row(three):
    """The cheapest source on each planted date, worked out on paper above."""
    got = three.reset_index()["cheapest_source"].tolist()
    assert got[0] == "curve"        # 4.0 < 6.0 < 7.0
    assert got[1] == "swaption"     # 6.0 < 7.0 < 9.0
    assert got[2] == "swaption"     # 6.0 < 6.5 < 7.0
    assert got[3] == "curve"        # always_cheap sentinel: 0.0
    assert got[4] == "swaption"     # never_cheap sentinel: +inf
    assert got[5] is None           # unusable -- swaption missing

    rich = three.reset_index()["richest_source"].tolist()
    assert rich[0] == "listed" and rich[1] == "curve" and rich[4] == "curve"


def test_usable_is_the_three_way_intersection(three):
    """A missing benchmark makes the row unusable, and the row is KEPT.

    Dropping it would make the intersection invisible; the honest behaviour is
    to carry it with ``usable=False`` so ``intersection_report`` can count it.
    """
    u = three["usable"].to_numpy(bool)
    assert u.tolist() == [True, True, True, True, True, False]
    rep = tw.intersection_report(three)
    assert rep["n_rows"] == 6
    assert rep["rows_all_three"] == 5
    assert rep["rows_swaption_ok"] == 5 and rep["rows_listed_ok"] == 6


def test_sentinels_are_ranked_not_dropped(three):
    """``always_cheap`` (0) and ``never_cheap`` (+inf) are real states.

    ``breakeven_vol`` deliberately encodes them as 0 and +inf rather than NaN,
    and a rank test that filtered on ``isfinite`` would silently delete the
    ``never_cheap`` row -- i.e. exactly the days the curve is most expensive.
    """
    r = three.reset_index()
    assert r.loc[3, "rank_curve"] == 1.0          # 0.0 is cheapest of the three
    assert r.loc[4, "rank_curve"] == 3.0          # +inf is richest
    assert bool(r.loc[4, "usable"])               # and it is USABLE, not dropped


def test_unusable_rows_carry_no_ranking(three):
    """The invariant that makes the NaN-fill mutation inert -- see the module log.

    No usable row may contain a non-finite benchmark, and every unusable row
    must carry NaN ranks and a ``None`` label. Together those make the choice of
    NaN fill in the ranking unobservable. If this test ever fails, the fill
    direction has become live and must be re-checked.
    """
    u = three["usable"].to_numpy(bool)
    for col in ("swaption_bp_day", "listed_bp_day"):
        assert np.isfinite(three.loc[u, col].to_numpy(float)).all()
    assert not np.isnan(three.loc[u, "curve_bp_day"].to_numpy(float)).any()
    for name in tw.SOURCES:
        assert three.loc[~u, f"rank_{name}"].isna().all()
    assert all(v is None for v in three.loc[~u, "cheapest_source"])


def test_basis_sign_is_swaption_minus_listed(three):
    """Positive basis = the OTC market prices MORE vol than the exchange."""
    b = three["basis_bp_day"].to_numpy(float)
    assert b[0] == pytest.approx(6.0 - 7.0)
    assert np.isnan(b[5])


# ------------------------------------------------------------------ the gates


def test_gates_are_planted_row_by_row(three):
    """Each gate on each planted date."""
    r = three.reset_index()
    assert r["signal_swaption"].tolist() == [1.0, -1.0, -1.0, 1.0, -1.0, 0.0]
    assert r["signal_listed"].tolist() == [1.0, -1.0, 1.0, 1.0, -1.0, 0.0]
    # MIXED row (index 2): swaption says rich, listed says cheap
    assert r.loc[2, "gate_both"] == 0.0
    assert r.loc[2, "gate_either"] == 1.0          # at least one says cheap
    assert r.loc[2, "gate_swaption_only"] == -1.0
    assert r.loc[2, "gate_listed_only"] == 1.0
    # unusable row gates flat under every mode
    assert all(r.loc[5, f"gate_{m}"] == 0.0 for m in tw.GATE_MODES)


@pytest.mark.parametrize("threshold", [0.0, 0.25, 1.5])
@pytest.mark.parametrize("trade_when_rich", [True, False])
@pytest.mark.parametrize("require_all_three", [True, False])
def test_both_equals_cheapest_for_every_configuration(threshold, trade_when_rich,
                                                      require_all_three):
    """``both`` and ``cheapest`` are the SAME gate -- for every knob setting.

    "the curve beats both benchmarks" and "the curve is the cheapest of the
    three" are the same proposition. The two are computed by different
    expressions (an AND over signals versus a min/max comparison), so this
    compares two code paths, not one against itself.

    A randomised sweep is added to the planted rows because the planted set is
    small enough that an implementation could pass it by luck.
    """
    cfg = _cfg(entry_threshold_bp_per_day=threshold,
               trade_when_rich=trade_when_rich,
               require_all_three=require_all_three)
    assert tw.assert_both_equals_cheapest(tw.threeway_frame(_synthetic_panel(), cfg))["identical"]

    rng = np.random.default_rng(20260815)
    n = 4000
    p = pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=n, freq="D"),
        "structure": ["1Yx2Y/2Yx2Y"] * n,
        "breakeven_vol_bp_day": rng.uniform(0.0, 12.0, n),
        "otc_atmf_bp_day": rng.uniform(4.0, 9.0, n),
        "listed_atm_bp_day": rng.uniform(4.0, 9.0, n),
    })
    res = tw.assert_both_equals_cheapest(tw.threeway_frame(p, cfg))
    assert res["identical"], f"{res['n_differ']} rows differ at {res['first_difference']}"


def test_either_is_strictly_more_permissive_than_both(three):
    """``either`` must differ from ``both`` on the mixed row, or it is redundant.

    If this ever passes trivially (no mixed rows) the synthetic panel has lost
    its planted disagreement and the rest of the gate tests are vacuous.
    """
    r = three.reset_index()
    mixed = r["signal_swaption"] != r["signal_listed"]
    assert mixed.sum() >= 1, "planted panel no longer contains a disagreement"
    assert (r.loc[mixed, "gate_both"] == 0.0).all()
    assert (r.loc[mixed, "gate_either"] != 0.0).any()


def test_signal_uses_no_time_to_expiry_scaling():
    """MUTATION CHECK: a ``sqrt(tte)`` in the bp/day comparison must break this.

    All three sources are already annual-vol/sqrt(252). Multiplying any of them
    by ``sqrt(tte)`` again turns a vol into a terminal standard deviation -- the
    single most likely unit error in this study. Here the curve sits 2 bp/day
    below both benchmarks; no horizon appears anywhere, so scaling either side
    by sqrt(1.0) must be a no-op and by anything else must flip a verdict.
    """
    p = _synthetic_panel().iloc[:1].copy()
    for hy in (0.25, 1.0, 4.0):
        got = tw.threeway_frame(p, _cfg(horizon_years=hy))
        assert got["signal_swaption"].iloc[0] == 1.0
        assert got["curve_bp_day"].iloc[0] == pytest.approx(4.0)


def test_no_trade_band_widens_the_flat_zone():
    """A positive threshold must create rows that stand aside, not shift them."""
    p = _synthetic_panel()
    tight = tw.threeway_frame(p, _cfg(entry_threshold_bp_per_day=0.0))
    wide = tw.threeway_frame(p, _cfg(entry_threshold_bp_per_day=3.0))
    assert (tight["gate_swaption_only"] == 0.0).sum() < (wide["gate_swaption_only"] == 0.0).sum()


def test_structures_outside_the_config_are_dropped():
    """A long-end row must never reach a table that says "listed".

    Sector matching is the load-bearing honesty requirement of this study: an
    SFR option and a 30-year flattener are not the same risk. The frame refuses
    to carry a structure the config does not name.
    """
    p = pd.concat([_synthetic_panel(), _synthetic_panel().assign(structure="30Y/50Y")])
    got = tw.threeway_frame(p, _cfg())
    assert set(got.index.get_level_values("structure")) == {"1Yx2Y/2Yx2Y"}


# ------------------------------------------------------- gate -> cohort P&L


def _synthetic_cohorts() -> pd.DataFrame:
    """Four cohorts with hand-chosen stored P&L and mixed stored directions.

    Stored P&L is what the engine would have logged for the direction actually
    traded, so the pure-flattener ("unit") P&L is ``direction * gross``:

    ====  =========  =====  ==========
    tag   direction  gross  unit_gross
    ====  =========  =====  ==========
    c0         +1.0   +6.0        +6.0
    c1         -1.0   +4.0        -4.0
    c2         +1.0  -10.0       -10.0
    c3         -1.0   -2.0        +2.0
    ====  =========  =====  ==========
    """
    entries = pd.to_datetime(["2025-01-06", "2025-01-07", "2025-01-08", "2025-01-09"])
    return pd.DataFrame({
        "tag": [f"c{i}" for i in range(4)],
        "structure": ["1Yx2Y/2Yx2Y"] * 4,
        "entry": entries,
        "exit": entries + pd.DateOffset(years=1),
        "direction": [1.0, -1.0, 1.0, -1.0],
        "live_at_end": [False] * 4,
        "closed": [True] * 4,
        "gross_pnl_bp": [6.0, 4.0, -10.0, -2.0],
        "net_pnl_bp": [5.0, 3.0, -11.0, -3.0],     # gross - 2 * 0.5 bp
    })


def test_unit_cohort_table_is_the_flattener_pnl():
    """``unit_gross_bp = direction * gross`` -- the planted column above."""
    u = tw.unit_cohort_table(_synthetic_cohorts(), cfg=_cfg())
    assert u["unit_gross_bp"].tolist() == [6.0, -4.0, -10.0, 2.0]


def test_unit_cohort_table_rejects_non_unit_directions():
    """A stored direction of +2 would silently double every derived P&L."""
    bad = _synthetic_cohorts()
    bad.loc[0, "direction"] = 2.0
    with pytest.raises(ValueError, match="direction"):
        tw.unit_cohort_table(bad, cfg=_cfg())


def test_apply_gate_replays_stored_direction_exactly():
    """MUTATION CHECK: the known-answer property the whole study rests on.

    Feeding the stored direction back through ``apply_gate`` must reproduce the
    stored ``net_pnl_bp``. Fails if ``unit_cohort_table`` drops the
    ``direction *``, or if the round-trip cost is charged once (0.5) instead of
    twice (1.0), or if the cost sign is flipped.
    """
    coh = _synthetic_cohorts()
    # stored direction as a daily series on the entry grid, un-lagged
    sig = pd.Series(coh["direction"].to_numpy(float), index=coh["entry"])
    got = tw.apply_gate(coh, sig, cfg=_cfg(), lag_days=0)
    assert got["gate_direction"].tolist() == coh["direction"].tolist()
    np.testing.assert_allclose(got["gate_net_bp"].to_numpy(float),
                               coh["net_pnl_bp"].to_numpy(float), atol=1e-12)


def test_gate_direction_flip_negates_pnl():
    """MUTATION CHECK: flipping every gate must negate every GROSS P&L.

    This is the linearity identity that lets five gate modes be scored off one
    engine run. Fails if ``apply_gate`` ever takes an ``abs()``, or drops the
    sign, or treats the cost as sign-dependent (it is not -- you pay to get out
    either way, so NET is not simply negated and that asymmetry is checked too).
    """
    coh = _synthetic_cohorts()
    idx = coh["entry"]
    up = tw.apply_gate(coh, pd.Series(1.0, index=idx), cfg=_cfg(), lag_days=0)
    dn = tw.apply_gate(coh, pd.Series(-1.0, index=idx), cfg=_cfg(), lag_days=0)
    np.testing.assert_allclose(up["gate_gross_bp"].to_numpy(float),
                               -dn["gate_gross_bp"].to_numpy(float), atol=1e-12)
    # cost is paid in both directions, so net is NOT the negation
    np.testing.assert_allclose(up["gate_net_bp"].to_numpy(float)
                               + dn["gate_net_bp"].to_numpy(float),
                               np.full(4, -2.0 * 2 * 0.5), atol=1e-12)


def test_standing_aside_costs_nothing():
    """MUTATION CHECK: a zero gate must produce zero P&L and zero cost.

    Fails if the cost is charged unconditionally, which would make the gates
    that trade less look worse for a reason that has nothing to do with the
    signal -- exactly the bias this study is trying to measure.
    """
    coh = _synthetic_cohorts()
    got = tw.apply_gate(coh, pd.Series(0.0, index=coh["entry"]), cfg=_cfg(), lag_days=0)
    assert not got["traded"].any()
    assert (got["gate_cost_bp"] == 0.0).all()
    assert (got["gate_gross_bp"] == 0.0).all()
    assert got["gate_net_bp"].isna().all()


def test_missing_gate_dates_stand_aside():
    """A cohort whose entry has no gate value must not trade on a guess."""
    coh = _synthetic_cohorts()
    sig = pd.Series([1.0, np.nan], index=coh["entry"].iloc[:2])
    got = tw.apply_gate(coh, sig, cfg=_cfg(), lag_days=0)
    assert got["traded"].tolist() == [True, False, False, False]


def test_lag_shifts_the_gate_by_one_grid_day():
    """The gate must be lagged, or the cohort trades on its own close.

    The stored runs used ``shift(1)``; a gate book built without it would not be
    comparable to them and would be look-ahead besides.
    """
    coh = _synthetic_cohorts()
    grid = pd.date_range("2025-01-06", periods=4, freq="D")
    sig = pd.Series([1.0, -1.0, -1.0, -1.0], index=grid)
    lagged = tw.apply_gate(coh, sig, cfg=_cfg(), lag_days=1)
    # entry d0 has no prior day -> flat; entry d1 sees d0's +1
    assert lagged["gate_direction"].tolist()[:2] == [0.0, 1.0]
    unlagged = tw.apply_gate(coh, sig, cfg=_cfg(), lag_days=0)
    assert unlagged["gate_direction"].tolist()[:2] == [1.0, -1.0]


# -------------------------------------------------------- sample-size arithmetic


def test_effective_independent_n_counts_windows_not_cohorts():
    """50 weekly cohorts over 2 years of 1-year holds are ~2 observations."""
    entries = pd.date_range("2024-07-01", periods=50, freq="W")
    exits = entries + pd.DateOffset(years=1)
    n = tw.effective_independent_n(entries, exits, horizon_years=1.0)
    assert 1.9 < n < 2.2, n
    assert n < 50


def test_expected_max_sharpe_rises_with_trials():
    """MUTATION CHECK: more gates tried => a HIGHER bar, never a lower one.

    Fails if the multiple-testing correction is applied with the wrong sign,
    which is the way this statistic is usually got backwards.
    """
    vals = [tw.expected_max_sharpe_under_null(n, 54) for n in (2, 4, 8, 16)]
    assert all(b > a for a, b in zip(vals, vals[1:])), vals
    assert tw.expected_max_sharpe_under_null(1, 54) == 0.0
    # fewer observations => a noisier max => a higher bar
    assert tw.expected_max_sharpe_under_null(4, 2) > tw.expected_max_sharpe_under_null(4, 54)


def test_expected_max_sharpe_matches_hand_value():
    """Hand-computed from Bailey & Lopez de Prado's closed form, N=4, n=100.

    ``g = 0.5772156649``; ``Z(1 - 1/4) = Z(0.75) = 0.6744897502``;
    ``Z(1 - 1/(4e)) = Z(0.9080301397) = 1.3296656``; so
    ``E[max] = (0.4227843351*0.6744897502 + 0.5772156649*1.3296656)/10``.
    """
    from scipy.stats import norm

    g = 0.5772156649015329
    want = ((1 - g) * float(norm.ppf(0.75))
            + g * float(norm.ppf(1 - 1 / (4 * math.e)))) / math.sqrt(100)
    assert tw.expected_max_sharpe_under_null(4, 100) == pytest.approx(want, rel=1e-12)


def test_deflated_sharpe_is_a_probability_and_moves_the_right_way():
    """DSR in (0,1); rises with the observed Sharpe, falls with the benchmark."""
    a = tw.deflated_sharpe_ratio(0.30, 100)
    b = tw.deflated_sharpe_ratio(0.10, 100)
    assert 0.0 < b < a < 1.0
    assert tw.deflated_sharpe_ratio(0.30, 100, sr_benchmark=0.25) < a
    # a Sharpe exactly at the benchmark is a coin flip
    assert tw.deflated_sharpe_ratio(0.2, 100, sr_benchmark=0.2) == pytest.approx(0.5)


# ------------------------------------------------------------------- reporting


def test_agreement_table_counts_the_planted_disagreement(three):
    """One mixed row of five usable ones -> 20% disagreement, pooled row present."""
    t = tw.agreement_table(three)
    row = t[t["structure"] == "1Yx2Y/2Yx2Y"].iloc[0]
    assert row["n_days"] == 5
    assert row["n_disagree"] == 1
    assert row["frac_disagree"] == pytest.approx(0.2)
    assert row["frac_swaption_rich_listed_cheap"] == pytest.approx(0.2)
    assert "POOLED" in set(t["structure"])


def test_rank_table_fractions_sum_to_one(three):
    t = tw.rank_table(three)
    for _, r in t.iterrows():
        s = sum(r[f"frac_cheapest_{n}"] for n in tw.SOURCES)
        assert s == pytest.approx(1.0)


def test_basis_frame_is_one_row_per_date():
    """The benchmark columns are identical across structures on a given date."""
    p = pd.concat([_synthetic_panel(),
                   _synthetic_panel().assign(structure="2Yx2Y/3Yx2Y")])
    b = tw.basis_frame(p, _cfg())
    assert len(b) == 6
    assert b["basis_bp_day"].iloc[0] == pytest.approx(-1.0)


# ------------------------------------------------------------------ data-backed


@pytest.mark.slow
@pytest.mark.skipif(not PANEL.exists(), reason="strategy-1-listed panel not built")
def test_recomputed_signals_match_the_stored_panel():
    """TIE-OUT: this module's signals must equal strategy-1-listed's, row for row.

    ``threeway_frame`` recomputes the curve-vs-benchmark signals from the bp/day
    columns instead of copying ``signal_otc`` / ``signal_listed``, so that it
    works on any frame carrying three vols. That freedom is only safe if the two
    agree on the real panel -- including on the ``always_cheap`` (0) and
    ``never_cheap`` (+inf) sentinel rows, which is where a naive numeric
    comparison would diverge from ``signal_from_breakeven``'s status switch.

    Restricted to the three-way intersection: off it, this module deliberately
    gates flat where the stored panel did not, because a gate comparison across
    different coverage measures coverage rather than information.
    """
    panel = pd.read_parquet(PANEL)
    got = tw.threeway_frame(panel, tw.Strat1ThreeWayConfig())
    u = got["usable"].to_numpy(bool)
    assert u.sum() > 2000
    np.testing.assert_array_equal(got.loc[u, "signal_swaption"].to_numpy(float),
                                  got.loc[u, "src_signal_otc"].to_numpy(float))
    np.testing.assert_array_equal(got.loc[u, "signal_listed"].to_numpy(float),
                                  got.loc[u, "src_signal_listed"].to_numpy(float))


@pytest.mark.slow
@pytest.mark.skipif(not PANEL.exists(), reason="strategy-1-listed panel not built")
@pytest.mark.parametrize("label", ["1Yx2Y/2Yx2Y", "2Yx2Y/3Yx2Y", "1Yx3Y/2Yx3Y",
                                   "2Yx3Y/3Yx3Y", "1Yx2Y/3Yx2Y"])
def test_apply_gate_reproduces_the_stored_backtest(label):
    """TIE-OUT: the derived books must reproduce the engine's own cohort P&L.

    Every gate-mode number in this study is derived arithmetically from ONE
    stored engine run per structure. If replaying the stored gate through that
    arithmetic did not return the stored answer, none of the derived numbers
    would mean anything -- so this is checked on all five structures, not one.
    """
    coh_path = DATA / f"strat1_listed_cohorts_{label.replace('/', '-')}.parquet"
    if not coh_path.exists():
        pytest.skip(f"no stored cohort table for {label}")
    panel = pd.read_parquet(coh_path.parent / "strat1_listed_signal_panel.parquet")
    panel["date"] = pd.to_datetime(panel["date"])
    stored_sig = (panel[panel["structure"] == label]
                  .set_index("date").sort_index()["signal_listed"])

    coh = pd.read_parquet(coh_path)
    got = tw.apply_gate(coh, stored_sig, cfg=tw.Strat1ThreeWayConfig())

    np.testing.assert_array_equal(got["gate_direction"].to_numpy(float),
                                  got["direction"].to_numpy(float))
    closed = got[got["gate_closed"].to_numpy(bool)]
    assert len(closed) > 40
    np.testing.assert_allclose(closed["gate_net_bp"].to_numpy(float),
                               closed["net_pnl_bp"].to_numpy(float), atol=1e-9)

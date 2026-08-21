"""Unit tests for the ETF-rebalance study.

Each test here corresponds to a defect that was actually hit while building this, not to
a line of code that wanted covering. The comments name the failure so a future change
that reintroduces it fails with an explanation rather than a red dot.
"""

from __future__ import annotations

import datetime
import hashlib

import numpy as np
import pandas as pd
import pytest

from MDP.ETFHoldings.providers import ishares
from MDP.ETFHoldings.universe import ETFSpec, spec, tickers_above
from RVUtils.ETFRebalance import costs as CO
from RVUtils.ETFRebalance import curve as CV
from RVUtils.ETFRebalance import engine as EN
from RVUtils.ETFRebalance import holdings_panel as HP
from RVUtils.ETFRebalance import signals as SIG

# --------------------------------------------------------------------------- fixtures

HEADER = (
    "Name,Sector,Asset Class,Market Value,Weight (%),Notional Value,Par Value,CUSIP,ISIN,"
    "SEDOL,Price,Location,Exchange,Currency,Duration,YTM (%),FX Rate,Maturity,Coupon (%),"
    "Mod. Duration,Yield to Call (%),Yield to Worst (%),Real Duration,Real YTM (%),"
    "Market Currency,Accrual Date,Effective Date\n"
)


def _doc(as_of: str, shares: str = "565,000,000.00", rows: str = "") -> str:
    return (
        "iShares 20+ Year Treasury Bond ETF\n"
        f'Fund Holdings as of,"{as_of}"\n'
        'Inception Date,"Jul 22, 2002"\n'
        f'Shares Outstanding,"{shares}"\n'
        "\n" + HEADER + rows
    )


BOND_ROW = (
    '"TREASURY BOND","Treasuries","Fixed Income","2,119,419,144.95","4.52",'
    '"2,119,419,144.95","2,243,213,900.00","912810UK2","US912810UK24","BPJK9V9","93.24",'
    '"United States","-","USD","14.57","5.21","1.00","May 15, 2055","4.75","14.91","-",'
    '"5.21","14.91","5.21","USD","May 15, 2025","May 15, 2025"\n'
)

CASH_ROW = (
    '"USD CASH","Cash","Cash and/or Derivatives","1,000.00","0.00","1,000.00","1,000.00",'
    '"-","-","-","1.00","United States","-","USD","-","-","1.00","-","-","-","-","-","-",'
    '"-","USD","-","-"\n'
)


# --------------------------------------------------------------------------- provider


def test_parse_reads_the_documents_own_date_not_the_requested_one():
    """The endpoint answers 200 for market holidays and re-serves a neighbouring file.

    Keying a row on the date REQUESTED rather than the date the document claims writes a
    duplicate observation and makes ``diff()`` book one real day of rebalancing as two
    half-days. The parser must report the document's own stamp.
    """
    hf = ishares.parse(_doc("Aug 19, 2026", rows=BOND_ROW), ticker="TLT",
                       requested=datetime.date(2026, 8, 20))
    assert hf is not None
    assert hf.as_of == datetime.date(2026, 8, 19)
    assert hf.requested == datetime.date(2026, 8, 20)


def test_parse_drops_the_cash_line_but_keeps_bonds():
    hf = ishares.parse(_doc("Aug 19, 2026", rows=BOND_ROW + CASH_ROW), ticker="TLT",
                       requested=datetime.date(2026, 8, 19))
    assert len(hf.frame) == 2                      # parse keeps both; the panel filters
    assert set(hf.frame["Asset Class"]) == {"Fixed Income", "Cash and/or Derivatives"}


def test_parse_numbers_survive_thousands_separators():
    hf = ishares.parse(_doc("Aug 19, 2026", rows=BOND_ROW), ticker="TLT",
                       requested=datetime.date(2026, 8, 19))
    row = hf.frame.iloc[0]
    assert row["Par Value"] == pytest.approx(2_243_213_900.00)
    assert row["Mod. Duration"] == pytest.approx(14.91)
    assert hf.shares_outstanding == pytest.approx(565_000_000.0)


def test_parse_returns_none_for_a_non_holdings_body():
    """A 200 that is not a holdings document is the ONLY genuine "no file for this date"."""
    assert ishares.parse("<HTML><HEAD><TITLE>Access Denied</TITLE></HEAD></HTML>",
                         ticker="TLT", requested=datetime.date(2019, 1, 3)) is None


def test_content_hash_distinguishes_a_reserved_document():
    a = ishares.parse(_doc("Jun 18, 2026", rows=BOND_ROW), ticker="TLT",
                      requested=datetime.date(2026, 6, 18))
    b = ishares.parse(_doc("Jun 18, 2026", rows=BOND_ROW), ticker="TLT",
                      requested=datetime.date(2026, 6, 19))
    assert a.content_sha1 == b.content_sha1        # same bytes -> detectable as a re-serve


def test_a_refusal_is_an_exception_not_absence():
    """403 recorded as "no file" is how a run wrote 2,515 fabricated absences and exited 0."""
    class _Resp:
        status_code = 403
        headers: dict = {}
        text = "Access Denied"

    class _Sess:
        def get(self, *a, **k):
            return _Resp()

    with pytest.raises(ishares.Blocked):
        ishares.fetch("239454", datetime.date(2019, 1, 3), ticker="TLT",
                      session=_Sess(), max_attempts=1)
    assert 403 in ishares.BLOCKED_STATUSES


# --------------------------------------------------------------------------- universe


def test_registry_refuses_a_fund_it_has_no_band_for():
    with pytest.raises(KeyError, match="deletion boundary"):
        spec("NOTAFUND")


def test_tickers_above_is_sorted_by_size_and_excludes_strips():
    got = tickers_above(1e9)
    assert "TLT" in got and "GOVZ" not in got      # GOVZ is STRIPS and below the cut
    assert got[0] == "TLT" or spec(got[0]).aum_usd >= spec("TLT").aum_usd


# --------------------------------------------------------------------------- ladder


def test_bucket_zero_is_always_the_deletion_bucket():
    """The whole point of a constant-maturity ladder: bucket 0 keeps its meaning."""
    sp = spec("TLT")
    ttm = pd.Series([20.05, 20.30, 24.00, 29.90])
    b = HP.bucket_index(ttm, sp, width_y=0.25)
    assert b.iloc[0] == 0                          # 20.00-20.25 -> about to be dropped
    assert b.iloc[1] == 1
    assert b.iloc[3] > b.iloc[2]


def test_bucket_index_saturates_above_the_band():
    sp = ETFSpec("X", "i", "0", "x", 1e9, (20.0, 30.0))
    b = HP.bucket_index(pd.Series([35.0]), sp, width_y=0.25)
    assert b.iloc[0] == np.floor((30.0 - 20.0) / 0.25)


# --------------------------------------------------------------------------- signals


def test_cross_sectional_z_survives_a_sparse_signal():
    """A signal that is zero for most of the cross-section has MAD exactly 0.

    A pure MAD z-score is then NaN on every date, which is how ``deletion`` produced a
    usable cross-section on 0 of 2,528 dates and was silently dropped as "too few finite
    values". The scale must fall back rather than the signal disappearing.
    """
    dates = pd.Series([pd.Timestamp("2026-01-02")] * 20)
    s = pd.Series([0.0] * 18 + [-1.0, -0.5])
    z = SIG.cross_sectional_z(s, dates, robust=True)
    assert z.notna().all()
    assert z.iloc[18] < z.iloc[0]                  # the flagged bonds rank below the rest


def test_cross_sectional_z_is_nan_only_when_there_is_no_variation_at_all():
    dates = pd.Series([pd.Timestamp("2026-01-02")] * 5)
    z = SIG.cross_sectional_z(pd.Series([1.0] * 5), dates)
    assert z.isna().all()


def test_month_end_is_declared_timing_only():
    """It is constant across the cross-section, so ranking bonds on it is meaningless."""
    assert "month_end" in SIG.TIMING_ONLY
    assert SIG.TIMING_ONLY.isdisjoint(SIG.HOLDINGS_BASED)


def test_calendar_signals_need_no_holdings_columns():
    """The null must be computable with no fund book at all, or it is not a null."""
    df = pd.DataFrame({
        "date": pd.to_datetime(["2026-01-02"] * 3),
        "ttm": [20.05, 22.0, 25.0],
        "issue_date": pd.to_datetime(["2025-11-15"] * 3),
    })
    d = SIG.sig_deletion(df, band_low=20.0, horizon_m=3)
    a = SIG.sig_addition(df, horizon_m=3)
    assert d.notna().all() and a.notna().all()
    assert d.iloc[0] < d.iloc[2]                   # the crossing bond scores most negative


def test_combine_standardises_before_weighting():
    """Without it a 50/50 blend of a 1e-3 signal and a 1e-1 one is really 99/1."""
    n = 60
    df = pd.DataFrame({
        "date": pd.to_datetime(["2026-01-02"] * n),
        "cusip": [f"C{i:03d}" for i in range(n)],
        "ttm": np.linspace(20, 30, n),
        "w_f": np.linspace(0, 1e-3, n),
        "w_i": np.full(n, 5e-4),
        "active_w": np.linspace(-1e-3, 1e-3, n),
        "ownership": np.linspace(0.0, 0.2, n),
        "free_float": np.full(n, 2e10),
        "resid_bp": np.linspace(-1, 1, n),
        "held": True,
    })
    out = SIG.combine(df, {"active_w": 1.0, "ownership": 1.0}, z_mode="cross_section")
    za, zo = out["z_active_w"], out["z_ownership"]
    # Both components must contribute on the same scale after standardisation.
    assert abs(za.std() - zo.std()) < 0.35 * max(za.std(), zo.std())


# --------------------------------------------------------------------------- structure


def test_fly_weights_are_neutral_to_level_and_slope():
    """Wings deliberately ASYMMETRIC.

    A symmetric fixture (24.00 / 24.25 / 24.50) makes ``a`` exactly 0.5, so hard-coding
    ``a = 0.5`` -- the obvious way to break slope neutrality -- passes the test unchanged.
    Verified by mutation: with symmetric wings the mutant survived. The maturity gaps
    here are 0.20 and 0.45, which no fixed constant can satisfy.
    """
    ttm = [24.00, 24.20, 24.65]
    day = pd.DataFrame({
        "cusip": ["F", "B", "K"], "ttm": ttm, "ytm": [4.0, 4.1, 4.2],
        "mod_dur": [14.0, 14.1, 14.2], "score": [0.0, 5.0, 0.0],
    })
    cfg = EN.merge_config({"structure": {"n_positions": 1, "both_sides": False,
                                         "wing_gap_min_y": 0.1, "wing_gap_max_y": 0.8}})
    pkgs = EN.build_flies(day, cfg)
    assert len(pkgs) == 1
    w = np.array([lg["w"] for lg in pkgs[0]["legs"]])
    t = np.array(ttm)
    assert w.sum() == pytest.approx(0.0, abs=1e-12)          # DV01 neutral
    assert float(w @ t) == pytest.approx(0.0, abs=1e-12)     # slope neutral
    assert pkgs[0]["legs"][1]["role"] == "belly"
    assert pkgs[0]["legs"][1]["w"] == pytest.approx(1.0)
    assert abs(w[0] + 0.5) > 1e-6                            # a != 0.5, so the test bites


def test_fly_is_refused_when_a_wing_is_out_of_reach():
    day = pd.DataFrame({
        "cusip": ["B", "K"], "ttm": [24.0, 24.25], "ytm": [4.0, 4.1],
        "mod_dur": [14.0, 14.1], "score": [5.0, 0.0],
    })
    cfg = EN.merge_config({"structure": {"n_positions": 1, "both_sides": False}})
    assert EN.build_flies(day, cfg) == []


def test_no_belly_is_selected_twice_on_one_day():
    n = 12
    day = pd.DataFrame({
        "cusip": [f"C{i}" for i in range(n)],
        "ttm": np.linspace(20, 30, n),
        "ytm": np.linspace(4, 5, n),
        "mod_dur": np.linspace(13, 16, n),
        "score": np.linspace(-3, 3, n),
    })
    cfg = EN.merge_config({"structure": {"n_positions": 4, "both_sides": True}})
    pkgs = EN.build_flies(day, cfg)
    bellies = [p["belly"] for p in pkgs]
    assert len(bellies) == len(set(bellies))


# --------------------------------------------------------------------------- lag


def test_exec_lag_moves_the_trade_date_along_the_panels_own_axis():
    """A calendar offset would land on a day with no price; a panel-axis shift cannot."""
    dates = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"])
    df = pd.DataFrame({"date": list(dates) * 2,
                       "cusip": ["A"] * 3 + ["B"] * 3, "score": range(6)})
    out = HP.apply_exec_lag(df, exec_lag=1)
    got = out[out["date"] == dates[0]]["trade_date"].unique()
    assert list(got) == [dates[1]]
    # the final date has no successor, so it cannot be traded and is dropped
    assert (out["date"] == dates[-1]).sum() == 0


def test_exec_lag_zero_is_the_identity():
    dates = pd.to_datetime(["2026-01-02", "2026-01-05"])
    df = pd.DataFrame({"date": list(dates), "cusip": ["A", "A"], "score": [1, 2]})
    out = HP.apply_exec_lag(df, exec_lag=0)
    assert (out["trade_date"] == out["date"]).all()


def test_negative_exec_lag_is_refused():
    df = pd.DataFrame({"date": pd.to_datetime(["2026-01-02"]), "cusip": ["A"]})
    with pytest.raises(ValueError):
        HP.apply_exec_lag(df, exec_lag=-1)


# --------------------------------------------------------------------------- costs


def test_measured_cost_never_returns_zero_for_a_zero_quoted_spread():
    """FedInvest sometimes publishes bid == offer. A zero cost is a plausible number and
    must never be confused with an unknown one."""
    legs = pd.DataFrame({
        "date": pd.to_datetime(["2026-01-02"] * 3),
        "spread_price_bp": [0.0, np.nan, 4.0],
        "mod_dur": [14.0, 14.0, 14.0],
        "ttm": [24.0, 24.0, 24.0],
    })
    c = CO.CostModel(basis="measured").leg_round_trip_yield_bp(legs)
    assert (c > 0).all()
    assert c.iloc[2] == pytest.approx(4.0 / 14.0)


def test_sr1170_is_far_more_pessimistic_than_the_measured_basis():
    """The bound must actually bound, or calling it one is decoration."""
    legs = pd.DataFrame({
        "date": pd.to_datetime(["2023-06-15"]),
        "spread_price_bp": [8.0], "mod_dur": [14.5], "ttm": [25.0], "rank": [8],
    })
    meas = CO.CostModel(basis="measured").leg_round_trip_yield_bp(legs).iloc[0]
    sr = CO.CostModel(basis="sr1170").leg_round_trip_yield_bp(legs).iloc[0]
    assert sr > 10 * meas
    assert CO.SR1170_FULL_SAMPLE[30][6] == pytest.approx(166.98)


def test_cost_multiplier_is_linear():
    legs = pd.DataFrame({
        "date": pd.to_datetime(["2026-01-02"]), "spread_price_bp": [6.0],
        "mod_dur": [14.0], "ttm": [24.0],
    })
    a = CO.CostModel(basis="measured", multiplier=1.0).leg_round_trip_yield_bp(legs).iloc[0]
    b = CO.CostModel(basis="measured", multiplier=2.5).leg_round_trip_yield_bp(legs).iloc[0]
    assert b == pytest.approx(2.5 * a)


# --------------------------------------------------------------------------- curve


def test_residual_is_positive_for_a_cheap_bond():
    """Sign convention: resid_bp > 0 means the bond yields MORE than the curve -> cheap."""
    n = 40
    df = pd.DataFrame({
        "date": pd.to_datetime(["2026-01-02"] * n),
        "cusip": [f"C{i}" for i in range(n)],
        "ttm": np.linspace(20, 30, n),
        "cpn": np.full(n, 4.0),
    })
    df["ytm"] = 4.0 + 0.01 * (df["ttm"] - 25.0)
    df.loc[10, "ytm"] += 0.05                       # 5bp cheap
    out = CV.fit_residuals(df, deg=2, include_coupon=False, robust=True)
    assert out.loc[out["cusip"] == "C10", "resid_bp"].iloc[0] > 3.0
    assert out.loc[out["cusip"] != "C10", "resid_bp"].abs().max() < 2.0


def test_robust_fit_is_not_dragged_by_the_outlier_it_is_measuring():
    n = 40
    df = pd.DataFrame({
        "date": pd.to_datetime(["2026-01-02"] * n),
        "cusip": [f"C{i}" for i in range(n)],
        "ttm": np.linspace(20, 30, n), "cpn": np.full(n, 4.0),
    })
    df["ytm"] = 4.0 + 0.01 * (df["ttm"] - 25.0)
    df.loc[20, "ytm"] += 0.50                        # a 50bp dislocation
    rob = CV.fit_residuals(df, deg=2, include_coupon=False, robust=True)
    ols = CV.fit_residuals(df, deg=2, include_coupon=False, robust=False)
    r_rob = rob.loc[rob["cusip"] == "C20", "resid_bp"].iloc[0]
    r_ols = ols.loc[ols["cusip"] == "C20", "resid_bp"].iloc[0]
    assert r_rob > r_ols                             # OLS shrinks the thing being measured


def test_residual_quality_reports_persistence():
    dates = pd.bdate_range("2026-01-01", periods=120)
    rng = np.random.default_rng(3)
    x = np.zeros(len(dates))
    for i in range(1, len(dates)):
        x[i] = 0.95 * x[i - 1] + rng.normal(scale=0.2)
    df = pd.DataFrame({"date": dates, "cusip": "A", "resid_bp": x})
    q = CV.residual_quality(df)
    assert q.loc["A", "autocorr_1"] > 0.7


# --------------------------------------------------------------------------- config


def _synthetic_universe(n_days: int = 60, n_bonds: int = 12) -> pd.DataFrame:
    """A small gated universe with the columns the engine needs, and nothing else."""
    dates = pd.bdate_range("2024-01-02", periods=n_days)
    rng = np.random.default_rng(5)
    rows = []
    for d in dates:
        for i in range(n_bonds):
            ttm = 20.2 + 0.25 * i
            rows.append({
                "date": d, "cusip": f"C{i:03d}", "ttm": ttm,
                "ytm": 4.0 + 0.02 * (ttm - 24.0) + rng.normal(scale=0.005),
                "mod_dur": 13.0 + 0.12 * i, "convexity": 300.0 + 8.0 * i,
                "clean_price": 95.0, "spread_price_bp": 5.0, "cpn": 4.0,
                "w_f": 1.0 / n_bonds + rng.normal(scale=1e-3),
                "w_i": 1.0 / n_bonds,
                "free_float": 2e10, "ownership": 0.05, "par_per_share": 1.0,
                "held": True, "resid_bp": 0.0, "rank": 8,
                "issue_date": pd.Timestamp("2020-01-02"),
            })
    u = pd.DataFrame(rows)
    u["active_w"] = u["w_f"] - u["w_i"]
    return u


def test_daily_marks_reconcile_to_the_trade_log_exactly():
    """The equity curve and the trade log are built by different code paths.

    The curve accumulates per-day steps across open packages; the log closes per package.
    They must agree to floating point. This is the check that caught a vectorisation
    which accrued one extra day of carry at entry: the log kept that first step and the
    curve dropped it, leaving a 0.96bp gap across 1,407 trades -- small enough to look
    like rounding and large enough to be twice the whole strategy's edge.
    """
    uni = _synthetic_universe()
    cfg = EN.merge_config({
        "universe": {"start": "2024-01-01"},
        "signal": {"components": {"active_w": 1.0}},
        "timing": {"exec_lag": 1, "hold_days": 5, "entry_every": 5},
        "carry": {"enabled": False},          # no network in a unit test
    })
    res = EN.run_config(cfg, universe=uni, prepared_funnel={})
    assert len(res.closed) > 5
    assert float(res.daily["mtm_bp"].iloc[-1]) == pytest.approx(
        float(res.closed["pnl_bp"].sum()), abs=1e-9)


def test_the_charged_cost_is_a_FULL_round_trip_on_all_three_legs():
    """``net == gross - cost`` is true by construction and catches nothing.

    Verified by mutation: halving ``cost_bp`` leaves that identity intact, because
    ``pnl_bp`` is computed from the same halved number. So the cost is pinned against the
    legs independently -- the DV01-weighted sum of each leg's FULL quoted spread. This is
    the check that would have caught charging half a round trip, which on a prior book
    was $2.82m against a true $5.64m: the difference between "+$431k" and roughly -$2.4m.
    """
    uni = _synthetic_universe()
    cfg = EN.merge_config({"timing": {"hold_days": 5, "entry_every": 5},
                           "carry": {"enabled": False}})
    res = EN.run_config(cfg, universe=uni, prepared_funnel={})

    d = res.closed["pnl_bp"] - (res.closed["gross_bp"] - res.closed["cost_bp"])
    assert d.abs().max() < 1e-12
    assert (res.closed["cost_bp"] > 0).all()   # a free trade is never a real one

    # The synthetic panel quotes 5.0 price bp on every bond, so each leg's full round
    # trip is 5.0 / mod_dur yield bp and the package pays sum(|w| * that).
    dur = uni.drop_duplicates("cusip").set_index("cusip")["mod_dur"]
    for tid, lg in res.legs.groupby("trade_id"):
        expect = float((lg["w"].abs() * (5.0 / dur.loc[lg["cusip"]].to_numpy())).sum())
        got = float(res.closed.loc[res.closed.trade_id == tid, "cost_bp"].iloc[0])
        assert got == pytest.approx(expect, rel=1e-9), f"trade {tid} paid {got}, not {expect}"

    # All three legs pay, and the weights sum to twice the belly's, so the package costs
    # about twice one leg -- never one leg's worth.
    per_trade_legs = res.legs.groupby("trade_id").size()
    assert (per_trade_legs == 3).all()


def test_a_mid_hold_pricing_hole_does_not_nan_the_whole_trade():
    """One unpriced day inside a hold must not destroy the trade's carry.

    A plain ``cumsum`` propagates NaN for the rest of the trade, so a single mid-hold day
    on which one leg did not price turned that trade's ``carry_bp`` -- and hence its
    ``gross_bp``, ``pnl_bp``, and the whole configuration's ``avg_bp`` and ``t_stat`` --
    into NaN. Found in a grid peek where several configurations reported
    ``sr_per_trade = 0.0`` with a NaN t: an inert-looking result rather than a broken one.
    The position IS held across that day; only its carry is unmeasured.
    """
    uni = _synthetic_universe(n_days=40)
    hole = sorted(uni["date"].unique())[6]
    victim = sorted(uni["cusip"].unique())[3]
    uni.loc[(uni["date"] == hole) & (uni["cusip"] == victim), "ytm"] = np.nan

    # Carry must be ON -- the NaN travels through the carry accumulation, so a test with
    # carry disabled cannot see the defect. (Verified by mutation: with carry off, the
    # mutant survived.) A flat stub avoids the network lookup a real GC series needs.
    orig_gc = EN._gc_series
    EN._gc_series = lambda dates: pd.Series(0.04, index=pd.DatetimeIndex(dates))
    try:
        cfg = EN.merge_config({
            "signal": {"components": {"active_w": 1.0}},
            "timing": {"exec_lag": 1, "hold_days": 10, "entry_every": 5},
            "carry": {"enabled": True},
        })
        res = EN.run_config(cfg, universe=uni, prepared_funnel={})
    finally:
        EN._gc_series = orig_gc
    assert not res.closed.empty
    for col in ("price_bp", "carry_bp", "gross_bp", "cost_bp", "pnl_bp"):
        assert res.closed[col].notna().all(), f"{col} went NaN on a mid-hold hole"
    assert float(res.daily["mtm_bp"].iloc[-1]) == pytest.approx(
        float(res.closed["pnl_bp"].sum()), abs=1e-9)


def test_the_same_belly_is_never_open_twice():
    """A bond that stays underweight for a month must not be entered twenty times."""
    uni = _synthetic_universe(n_days=120)
    cfg = EN.merge_config({"timing": {"hold_days": 21, "entry_every": 1},
                           "carry": {"enabled": False}})
    res = EN.run_config(cfg, universe=uni, prepared_funnel={})
    for belly, g in res.closed.groupby("belly"):
        g = g.sort_values("opened_at")
        assert (g["opened_at"].to_numpy()[1:] >= g["closed_at"].to_numpy()[:-1]).all()


def test_price_basis_knob_actually_changes_the_book():
    """A knob that changes nothing is a knob that is not wired, and it reads as a pass.

    ``prepare_universe`` repriced the PANEL for ``price_basis="eod"``, but every price
    column the universe actually uses -- ytm, mod_dur, convexity -- comes from the
    HOLDINGS join, which was untouched. The two bases therefore produced books identical
    to six decimal places while the underlying series differ by a median of 1.07bp, so
    the sensitivity section compared a thing to itself and reported that the result was
    robust. This asserts the knob bites.
    """
    n = 40
    dates = pd.bdate_range("2024-01-02", periods=30)
    rows = []
    for d in dates:
        for i in range(n):
            ttm = 20.2 + 0.25 * i
            y = 4.0 + 0.02 * (ttm - 24.0)
            rows.append({
                "date": d, "cusip": f"C{i:03d}", "ttm": ttm,
                "ytm": y, "ytm_eod": y + 0.03,            # a 3bp basis difference
                "mod_dur": 13.0 + 0.05 * i, "mod_dur_eod": 13.0 + 0.05 * i,
                "convexity": 300.0, "convexity_eod": 300.0,
                "clean_price": 95.0, "eod_price": 94.8,
                "spread_price_bp": 5.0, "cpn": 4.0, "rank": 8,
                "outstanding_amt": 2e10, "soma_holdings": 0.0, "free_float": 2e10,
                "yield_gate_fail": False, "price_source": "mid",
                "issue_date": pd.Timestamp("2020-01-02"),
                "maturity_date": d + pd.Timedelta(days=int(ttm * 365.25)),
                "par": 1e8, "mv": 1e8, "dv01_per_mm": 1450.0,
                "shares_out": 1e6, "ticker": "TLT",
            })
    p = pd.DataFrame(rows)
    p["priced"] = True

    mid = EN._reprice_on_eod.__wrapped__ if hasattr(EN._reprice_on_eod, "__wrapped__") else None
    swapped = EN._reprice_on_eod(p)
    assert not np.allclose(swapped["ytm"], p["ytm"]), "_reprice_on_eod did not swap the yields"
    assert np.allclose(swapped["ytm"], p["ytm_eod"]), "_reprice_on_eod swapped the wrong column"

    # And it must refuse rather than silently no-op when the panel lacks the columns.
    with pytest.raises(KeyError, match="price_basis"):
        EN._reprice_on_eod(p.drop(columns=["ytm_eod"]))


def test_merge_config_is_shallow_one_level_down():
    cfg = EN.merge_config({"timing": {"hold_days": 42}})
    assert cfg["timing"]["hold_days"] == 42
    assert cfg["timing"]["exec_lag"] == 1             # untouched siblings survive
    assert cfg["fund"] == "TLT"


def test_default_exec_lag_is_causal():
    """The default must never be the lookahead one."""
    assert EN.DEFAULT_CONFIG["timing"]["exec_lag"] >= 1

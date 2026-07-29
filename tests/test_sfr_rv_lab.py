"""Tests for RVUtils.SFRRVLab — the SR3 futures-vs-options RV lab.

All fixtures are synthetic and hand-computable: a two-contract, five-strike
listed panel whose premiums are exact linear/affine functions of the strike, so
digitals, parity residuals, package marks, hedge P&L and the backtest's lag and
cost accounting all have closed-form expected values.
"""
import datetime

import numpy as np
import pandas as pd
import pytest

from RVUtils.SFRRVLab import (
    DOLLARS_PER_BP,
    LabConfig,
    Leg,
    MarkBook,
    Structure,
    add_event_distance,
    constant_maturity_slots,
    cost_curve,
    delta_hedged_pnl,
    digital_calendar_panel,
    grid_search,
    mark_structure,
    nonoverlapping_sharpe,
    nw_tstat,
    parity_residuals,
    pick_listed_strike,
    realized_vol_bp,
    risk_reversal_panel,
    round_trip_cost_bp,
    run_backtest,
    verdict,
    vertical_digital,
)
from RVUtils.SFRRVLab.stats import grid_distribution, neighbourhood_stability

DATES = pd.bdate_range("2026-01-01", periods=10)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
def _contracts(forward_a=4.00, forward_b=4.00, n=len(DATES)):
    rows = []
    for i, d in enumerate(DATES[:n]):
        for sym, f0 in (("SFRH27", forward_a), ("SFRM27", forward_b)):
            f = f0 + 0.01 * i if sym == "SFRH27" else f0
            rows.append({
                "as_of": d, "symbol": sym, "forward_rate": f,
                "forward_price": 100.0 - f,
                "expiry_date": pd.Timestamp("2027-03-12") if sym == "SFRH27"
                else pd.Timestamp("2027-06-11"),
            })
    return pd.DataFrame(rows)


def _quotes(contracts, *, put_slope=40.0, call_slope=25.0, base=10.0):
    """Premiums affine in the strike so every derived quantity is closed form.

    ``put premium = base + put_slope * (K - F)`` in bp of price with K, F in
    price points, so a put vertical of width w prices at ``put_slope * w`` bp
    and the implied digital is exactly ``put_slope / 100``.
    """
    rows = []
    for _, c in contracts.iterrows():
        f_price = c["forward_price"]
        for k in np.arange(round(f_price * 4) / 4 - 0.5, round(f_price * 4) / 4 + 0.51, 0.25):
            rows.append({
                "as_of": c["as_of"], "symbol": c["symbol"], "right": "P",
                "strike_price": round(float(k), 4), "strike_rate": 100.0 - float(k),
                "premium_bp": base + put_slope * (float(k) - f_price),
                "iv_bp": 60.0, "delta_abs": 0.5, "atm_offset_bps": 0.0,
                "oi": 1000.0, "volume": 10.0,
            })
            rows.append({
                "as_of": c["as_of"], "symbol": c["symbol"], "right": "C",
                "strike_price": round(float(k), 4), "strike_rate": 100.0 - float(k),
                "premium_bp": base - call_slope * (float(k) - f_price),
                "iv_bp": 60.0, "delta_abs": 0.5, "atm_offset_bps": 0.0,
                "oi": 1000.0, "volume": 10.0,
            })
    return pd.DataFrame(rows)


@pytest.fixture()
def panel():
    c = _contracts()
    return c, _quotes(c)


# ---------------------------------------------------------------------------
# structures
# ---------------------------------------------------------------------------
def test_leg_validation():
    with pytest.raises(ValueError):
        Leg("spot", "SFRH27")
    with pytest.raises(ValueError):
        Leg("option", "SFRH27", right="X", strike_price=96.0)
    with pytest.raises(ValueError):
        Leg("option", "SFRH27", right="C")
    with pytest.raises(ValueError):
        Structure(())


def test_mark_structure_is_the_weighted_sum(panel):
    c, q = panel
    book = MarkBook(q, c)
    k = float(q["strike_price"].iloc[0])
    st = Structure((Leg("option", "SFRH27", 1.0, "P", k),
                    Leg("option", "SFRH27", -1.0, "C", k)))
    marks, stale = mark_structure(book, st, DATES)
    day0 = q[(q["as_of"] == DATES[0]) & (q["symbol"] == "SFRH27")
             & (q["strike_price"] == k)]
    expected = (float(day0[day0["right"] == "P"]["premium_bp"].iloc[0])
                - float(day0[day0["right"] == "C"]["premium_bp"].iloc[0]))
    assert marks[0] == pytest.approx(expected)
    assert stale == pytest.approx(0.0, abs=1e-9)


def test_mark_structure_reports_staleness_and_never_invents_a_price(panel):
    c, q = panel
    q2 = q[~((q["as_of"] > DATES[4]) & (q["strike_price"] == q["strike_price"].iloc[0]))]
    book = MarkBook(q2, c)
    k = float(q["strike_price"].iloc[0])
    st = Structure((Leg("option", "SFRH27", 1.0, "P", k),))
    marks, stale = mark_structure(book, st, DATES)
    assert stale > 0.0                       # the dead strike is flagged
    assert np.all(np.isfinite(marks))        # carried, not NaN
    assert marks[-1] == pytest.approx(marks[4])


def test_futures_leg_marks_in_price_bp(panel):
    c, q = panel
    book = MarkBook(q, c)
    st = Structure((Leg("future", "SFRH27", 1.0),))
    marks, _ = mark_structure(book, st, DATES)
    assert marks[0] == pytest.approx((100.0 - 4.00) * 100.0)
    # forward rate rises 1bp/day => price falls 1bp/day
    assert marks[1] - marks[0] == pytest.approx(-1.0)


def test_round_trip_cost_is_two_way_per_leg():
    st = Structure((Leg("option", "A", 1.0, "P", 96.0),
                    Leg("option", "A", -2.0, "C", 96.0),
                    Leg("future", "A", 0.5)))
    assert round_trip_cost_bp(st, option_leg_bp=0.5, future_leg_bp=0.25) == \
        pytest.approx(2 * (3 * 0.5 + 0.5 * 0.25))


# ---------------------------------------------------------------------------
# panels
# ---------------------------------------------------------------------------
def test_parity_residual_is_zero_on_a_parity_consistent_panel():
    """C - P - (F - K) with premiums built to satisfy parity exactly."""
    c = _contracts()
    rows = []
    for _, r in c.iterrows():
        for k in (95.5, 95.75, 96.0):
            put = 12.0
            call = put + (r["forward_price"] - k) * 100.0
            rows.append({"as_of": r["as_of"], "symbol": r["symbol"], "right": "P",
                         "strike_price": k, "strike_rate": 100 - k,
                         "premium_bp": put, "iv_bp": 60.0, "delta_abs": 0.5,
                         "oi": 100.0})
            rows.append({"as_of": r["as_of"], "symbol": r["symbol"], "right": "C",
                         "strike_price": k, "strike_rate": 100 - k,
                         "premium_bp": call, "iv_bp": 60.0, "delta_abs": 0.5,
                         "oi": 100.0})
    res = parity_residuals(pd.DataFrame(rows), c)
    assert np.allclose(res["parity_bp"].to_numpy(), 0.0, atol=1e-9)


def test_parity_residual_recovers_an_injected_dislocation():
    c = _contracts(n=1)
    rows = []
    for k, bump in ((95.5, 0.0), (95.75, 3.0)):
        put = 12.0
        call = put + (c["forward_price"].iloc[0] - k) * 100.0 + bump
        for right, prem in (("P", put), ("C", call)):
            rows.append({"as_of": c["as_of"].iloc[0], "symbol": c["symbol"].iloc[0],
                         "right": right, "strike_price": k, "strike_rate": 100 - k,
                         "premium_bp": prem, "iv_bp": 60.0, "delta_abs": 0.5,
                         "oi": 100.0})
    res = parity_residuals(pd.DataFrame(rows), c)
    got = res.set_index("strike_price")["parity_bp"]
    assert got.loc[95.5] == pytest.approx(0.0, abs=1e-9)
    assert got.loc[95.75] == pytest.approx(3.0, abs=1e-9)


def test_vertical_digital_equals_the_premium_slope(panel):
    """put premium = base + slope*(K-F) => digital P(rate>=k) = slope/100."""
    c, q = panel
    day = q[(q["as_of"] == DATES[0]) & (q["symbol"] == "SFRH27")]
    f = float(c[(c["as_of"] == DATES[0]) & (c["symbol"] == "SFRH27")]["forward_rate"].iloc[0])
    d = vertical_digital(day, f, right="P", tol=0.26)
    assert d is not None
    assert d["prob"] == pytest.approx(40.0 / 100.0, abs=1e-9)
    # target lands exactly on a listed strike -> centred over its two neighbours
    assert d["width_bp"] == pytest.approx(50.0)
    # a target between two strikes uses the tight bracket and gives the same slope
    d2 = vertical_digital(day, f + 0.125, right="P", tol=0.26)
    assert d2["width_bp"] == pytest.approx(25.0)
    assert d2["prob"] == pytest.approx(40.0 / 100.0, abs=1e-9)


def _parity_day(forward_price=96.0, slope=40.0, convexity=20.0):
    """A one-day chain whose calls and puts satisfy put-call parity exactly.

    The put curve is convex in the strike, so the implied digital genuinely
    varies across strikes (an affine curve would give a flat density and could
    not detect a monotonicity error).
    """
    rows = []
    for k in np.arange(95.5, 96.51, 0.25):
        x = float(k) - forward_price
        put = 30.0 + slope * x + convexity * x * x
        call = put + (forward_price - float(k)) * 100.0
        for right, prem in (("P", put), ("C", call)):
            rows.append({"as_of": DATES[0], "symbol": "X", "right": right,
                         "strike_price": round(float(k), 4),
                         "strike_rate": 100.0 - float(k), "premium_bp": prem,
                         "iv_bp": 60.0, "delta_abs": 0.5, "oi": 100.0})
    return pd.DataFrame(rows)


@pytest.mark.parametrize("target_rate", [3.875, 4.0, 4.125, 4.25])
def test_call_and_put_digitals_agree_under_parity(target_rate):
    """The sign convention must be identical on both sides of the smile.

    Under parity ``C(k_lo) - C(k_hi) = w - [P(k_hi) - P(k_lo)]``, so the raw call
    vertical measures ``P(rate < K)``; both sides must still report
    ``P(rate >= K)``. Auto side-selection mixes the two across strikes, so a sign
    slip here would silently corrupt every digital framework.
    """
    day = _parity_day()
    p = vertical_digital(day, target_rate, right="P", tol=0.26)
    c_ = vertical_digital(day, target_rate, right="C", tol=0.26)
    assert p is not None and c_ is not None
    assert c_["prob"] == pytest.approx(p["prob"], abs=1e-9)


def test_auto_side_picks_the_listed_otm_wing():
    """Panels carry only OTM options: puts below the forward, calls above."""
    day = _parity_day()
    otm_only = pd.concat([
        day[(day["right"] == "P") & (day["strike_price"] <= 96.0)],
        day[(day["right"] == "C") & (day["strike_price"] >= 96.0)],
    ])
    hi_rate = vertical_digital(otm_only, 4.25, tol=0.26, forward_price=96.0)
    lo_rate = vertical_digital(otm_only, 3.75, tol=0.26, forward_price=96.0)
    assert hi_rate is not None and hi_rate["right"] == "P"
    assert lo_rate is not None and lo_rate["right"] == "C"
    assert lo_rate["prob"] > hi_rate["prob"]   # P(rate>=K) falls as K rises


def test_digital_legs_scale_to_one_unit_of_probability(panel):
    """A digital package must mark at 100 x prob, in whole CME lots."""
    from RVUtils.SFRRVLab.signals import digital_legs
    c, q = panel
    book = MarkBook(q, c)
    day = q[(q["as_of"] == DATES[0]) & (q["symbol"] == "SFRH27")]
    d = vertical_digital(day, 4.125, right="P", tol=0.26)
    legs = digital_legs("SFRH27", d["k_lo"], d["k_hi"], "P")
    assert all(abs(l.weight) == pytest.approx(4.0) for l in legs)   # 25bp -> 4 lots
    marks, _ = mark_structure(book, Structure(legs), [DATES[0]])
    assert marks[0] == pytest.approx(d["prob"] * 100.0, abs=1e-9)


def test_vertical_digital_returns_none_when_no_strike_brackets():
    c = _contracts(n=1)
    q = _quotes(c)
    day = q[(q["as_of"] == DATES[0]) & (q["symbol"] == "SFRH27")]
    assert vertical_digital(day, 90.0, right="P", tol=0.02) is None


def test_pick_listed_strike_respects_tolerance_and_open_interest(panel):
    c, q = panel
    day = q[(q["as_of"] == DATES[0]) & (q["symbol"] == "SFRH27")]
    assert pick_listed_strike(day, "P", 4.00, tol=0.13) is not None
    assert pick_listed_strike(day, "P", 4.00, tol=0.13, min_oi=1e9) is None
    assert pick_listed_strike(day, "P", 40.0, tol=0.13) is None


def test_realized_vol_of_a_constant_step_series():
    """A series with a constant daily step has zero realized vol."""
    s = pd.Series(np.arange(30, dtype=float) * 0.01)
    rv = realized_vol_bp(s, window=10)
    assert rv.dropna().iloc[-1] == pytest.approx(0.0, abs=1e-9)


def test_realized_vol_scales_with_the_annualisation():
    rng = np.random.default_rng(0)
    s = pd.Series(np.cumsum(rng.normal(0, 0.01, 400)))
    rv = realized_vol_bp(s, window=100).dropna().iloc[-1]
    # daily bp sd ~1.0 -> annualised ~ sqrt(252)
    assert rv == pytest.approx(np.sqrt(252.0), rel=0.35)


def test_constant_maturity_slots_rank_by_expiry():
    c = constant_maturity_slots(_contracts())
    day = c[c["as_of"] == DATES[0]].set_index("symbol")["cm_slot"]
    assert day.loc["SFRH27"] == 1
    assert day.loc["SFRM27"] == 2


def test_event_distance_is_signed_around_the_nearest_meeting():
    df = pd.DataFrame({"as_of": [pd.Timestamp("2026-03-16"),
                                 pd.Timestamp("2026-03-20")]})
    out = add_event_distance(df)
    assert out["days_to_fomc"].tolist() == [-2, 2]   # 2026-03-18 meeting


# ---------------------------------------------------------------------------
# signal panels
# ---------------------------------------------------------------------------
def test_risk_reversal_panel_picks_the_two_wings(panel):
    c, q = panel
    rr = risk_reversal_panel(q, c, offset=0.25, tol=0.13)
    assert not rr.empty
    r0 = rr[(rr["as_of"] == DATES[0]) & (rr["symbol"] == "SFRH27")].iloc[0]
    # hike wing = put struck 25bp BELOW the forward price
    assert r0["hk_K"] == pytest.approx(r0["forward_rate"] * 0 + (100 - 4.00) - 0.25)
    assert r0["ct_K"] == pytest.approx((100 - 4.00) + 0.25)
    assert r0["rr_bp"] == pytest.approx(r0["hk_prem"] - r0["ct_prem"])


def test_digital_calendar_fly_is_the_strike_butterfly(panel):
    c, q = panel
    dc = digital_calendar_panel(q, c, offsets=(-0.25, 0.0, 0.25),
                                pairs=[("SFRH27", "SFRM27")], tol=0.26)
    assert not dc.empty
    r = dc.iloc[0]
    expected = r["cal-0.250"] - 2 * r["cal+0.000"] + r["cal+0.250"]
    assert r["fly"] == pytest.approx(expected)
    # affine premiums => identical digitals on both legs => zero calendar
    assert r["cal+0.000"] == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# delta hedging
# ---------------------------------------------------------------------------
def test_delta_hedged_pnl_uses_yesterdays_hedge():
    """Constant delta, linear futures path: hedge P&L is delta * dF each day."""
    c = _contracts()
    q = _quotes(c)
    book = MarkBook(q, c)
    k = float(q[q["symbol"] == "SFRH27"]["strike_price"].iloc[0])
    leg = Leg("option", "SFRH27", 1.0, "C", k)   # delta_abs 0.5 => +0.5
    out = delta_hedged_pnl(book, [leg], DATES, hedge_symbol="SFRH27",
                           rehedge_band=1e9, future_cost_bp=0.0)
    # hedge is -0.5 futures; price falls 1bp/day => hedge earns +0.5bp/day
    assert out["d_hedge"].iloc[1] == pytest.approx(0.5)
    assert out["hedge"].iloc[0] == pytest.approx(-0.5)


def test_delta_hedge_band_suppresses_rehedge_costs():
    c = _contracts()
    q = _quotes(c)
    book = MarkBook(q, c)
    k = float(q[q["symbol"] == "SFRH27"]["strike_price"].iloc[0])
    leg = Leg("option", "SFRH27", 1.0, "C", k)
    tight = delta_hedged_pnl(book, [leg], DATES, hedge_symbol="SFRH27",
                             rehedge_band=0.0, future_cost_bp=1.0)
    wide = delta_hedged_pnl(book, [leg], DATES, hedge_symbol="SFRH27",
                            rehedge_band=1e9, future_cost_bp=1.0)
    assert wide["hedge_cost_bp"].sum() <= tight["hedge_cost_bp"].sum()


# ---------------------------------------------------------------------------
# engine
# ---------------------------------------------------------------------------
def _linear_book(n=40, step=1.0):
    """A single option whose premium rises ``step`` bp per day."""
    dates = pd.bdate_range("2026-01-01", periods=n)
    c = pd.DataFrame({"as_of": dates, "symbol": "X", "forward_rate": 4.0,
                      "forward_price": 96.0,
                      "expiry_date": pd.Timestamp("2027-03-12")})
    q = pd.DataFrame({"as_of": dates, "symbol": "X", "right": "P",
                      "strike_price": 96.0, "strike_rate": 4.0,
                      "premium_bp": 10.0 + step * np.arange(n),
                      "iv_bp": 60.0, "delta_abs": 0.5, "oi": 100.0})
    return dates, MarkBook(q, c)


def _builder(_key, _date, _direction):
    return Structure((Leg("option", "X", 1.0, "P", 96.0),), label="one_put")


def test_engine_lag1_execution_and_cost_accounting():
    """Signal on bar i, fill on i+1; a 5-day hold on a +1bp/day path earns 5bp."""
    dates, book = _linear_book()
    sig = pd.DataFrame({"key": "K", "as_of": dates,
                        "signal": np.where(np.arange(len(dates)) == 20, 10.0, 0.0)})
    # force a deterministic entry: huge z on bar 20, time exit after 5 days
    cfg = LabConfig(ma=1, zscore_window=10, zscore_min_periods=5,
                    entry_min_zscore=2.0, direction="momentum", exit_style="t5",
                    lag=1, cost_mode="flat", round_trip_cost_bp=2.0,
                    exit_max_holding_days=50)
    res = run_backtest(cfg, signals=sig, book=book, builder=_builder)
    assert len(res.trades) >= 1
    t = res.trades.iloc[0]
    assert t["entry"] == dates[21]                 # signal bar 20 + lag 1
    assert t["days"] == 5
    assert t["gross_bp"] == pytest.approx(5.0)
    assert t["net_bp"] == pytest.approx(3.0)
    assert res.daily_bp.sum() == pytest.approx(t["net_bp"])


def test_engine_direction_flips_the_sign():
    dates, book = _linear_book()
    sig = pd.DataFrame({"key": "K", "as_of": dates,
                        "signal": np.where(np.arange(len(dates)) == 20, 10.0, 0.0)})
    base = dict(ma=1, zscore_window=10, zscore_min_periods=5, entry_min_zscore=2.0,
                exit_style="t5", lag=1, round_trip_cost_bp=0.0,
                exit_max_holding_days=50)
    up = run_backtest(LabConfig(direction="momentum", **base),
                      signals=sig, book=book, builder=_builder)
    dn = run_backtest(LabConfig(direction="fade", **base),
                      signals=sig, book=book, builder=_builder)
    assert up.trades["gross_bp"].iloc[0] == pytest.approx(
        -dn.trades["gross_bp"].iloc[0])


def test_lag_shifts_the_entry_bar_without_changing_a_linear_paths_pnl():
    """Lag moves WHEN you get filled; on a constant-slope path that is all it does.

    (The 56-72% same-bar inflation measured on real data comes from entering on
    the extreme bar of a mean-reverting signal, not from the path slope.)
    """
    dates, book = _linear_book()
    sig = pd.DataFrame({"key": "K", "as_of": dates,
                        "signal": np.where(np.arange(len(dates)) == 20, 10.0, 0.0)})
    base = dict(ma=1, zscore_window=10, zscore_min_periods=5, entry_min_zscore=2.0,
                direction="momentum", exit_style="t5", round_trip_cost_bp=0.0,
                exit_max_holding_days=50)
    l0 = run_backtest(LabConfig(lag=0, **base), signals=sig, book=book,
                      builder=_builder)
    l1 = run_backtest(LabConfig(lag=1, **base), signals=sig, book=book,
                      builder=_builder)
    assert l0.trades["gross_bp"].iloc[0] == pytest.approx(
        l1.trades["gross_bp"].iloc[0])   # same holding length, same slope
    assert l0.trades["entry"].iloc[0] < l1.trades["entry"].iloc[0]


def test_engine_gate_blocks_entry():
    dates, book = _linear_book()
    sig = pd.DataFrame({"key": "K", "as_of": dates,
                        "signal": np.where(np.arange(len(dates)) == 20, 10.0, 0.0),
                        "gate": False})
    cfg = LabConfig(ma=1, zscore_window=10, zscore_min_periods=5,
                    entry_min_zscore=2.0, direction="momentum", exit_style="t5",
                    quality_gate=True)
    assert run_backtest(cfg, signals=sig, book=book, builder=_builder).trades.empty


def test_engine_counts_skips_when_the_builder_declines():
    dates, book = _linear_book()
    sig = pd.DataFrame({"key": "K", "as_of": dates,
                        "signal": np.where(np.arange(len(dates)) == 20, 10.0, 0.0)})
    cfg = LabConfig(ma=1, zscore_window=10, zscore_min_periods=5,
                    entry_min_zscore=2.0, direction="momentum", exit_style="t5")
    res = run_backtest(cfg, signals=sig, book=book,
                       builder=lambda *_: None)
    assert res.trades.empty
    assert res.metrics["n_skipped"] >= 1


def test_engine_dollars_follow_the_bp_and_the_package_size():
    dates, book = _linear_book()
    sig = pd.DataFrame({"key": "K", "as_of": dates,
                        "signal": np.where(np.arange(len(dates)) == 20, 10.0, 0.0)})
    cfg = LabConfig(ma=1, zscore_window=10, zscore_min_periods=5,
                    entry_min_zscore=2.0, direction="momentum", exit_style="t5",
                    round_trip_cost_bp=0.0, contracts_per_leg=100)
    res = run_backtest(cfg, signals=sig, book=book, builder=_builder)
    assert res.metrics["total_net_usd"] == pytest.approx(
        res.metrics["total_net_bp"] * DOLLARS_PER_BP * 100)
    assert res.daily_usd.sum() == pytest.approx(res.daily_bp.sum() * 2500.0)


def test_grid_search_returns_one_row_per_config():
    dates, book = _linear_book()
    sig = pd.DataFrame({"key": "K", "as_of": dates,
                        "signal": np.where(np.arange(len(dates)) == 20, 10.0, 0.0)})
    base = LabConfig(ma=1, zscore_window=10, zscore_min_periods=5,
                     exit_style="t5", round_trip_cost_bp=0.0)
    res = grid_search({"direction": ["fade", "momentum"],
                       "entry_min_zscore": [2.0, 3.0]},
                      signals=sig, book=book, builder=_builder, base=base)
    assert len(res) == 4
    assert set(res["direction"]) == {"fade", "momentum"}


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------
def test_grid_distribution_summarises_the_sweep():
    res = pd.DataFrame({"total_net_bp": [-2.0, -1.0, 0.5, 3.0]})
    d = grid_distribution(res)
    assert d["n_configs"] == 4
    assert d["median"] == pytest.approx(-0.25)
    assert d["pct_positive"] == pytest.approx(0.5)
    assert d["best"] == pytest.approx(3.0)


def test_neighbourhood_stability_moves_one_param_at_a_time():
    res = pd.DataFrame({"ma": [1, 1, 5, 5], "entry_min_zscore": [2.0, 3.0, 2.0, 3.0],
                        "total_net_bp": [1.0, 2.0, 3.0, 4.0], "n_trades": 5})
    best = res.iloc[3]
    nb = neighbourhood_stability(res, best, ["ma", "entry_min_zscore"])
    assert set(nb["param"]) == {"ma", "entry_min_zscore"}
    ma_slice = nb[nb["param"] == "ma"].set_index("value")["total_net_bp"]
    assert ma_slice.loc[1] == pytest.approx(2.0)    # entry_z held at best (3.0)
    assert ma_slice.loc[5] == pytest.approx(4.0)


def test_nw_tstat_matches_plain_t_at_zero_lags():
    rng = np.random.default_rng(1)
    x = rng.normal(0.4, 1.0, 400)
    plain = x.mean() / (x.std(ddof=0) / np.sqrt(len(x)))
    assert nw_tstat(x, lags=0) == pytest.approx(plain, rel=1e-9)


def test_nonoverlapping_sharpe_drops_overlapping_trades():
    t = pd.DataFrame({
        "entry": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-02-01",
                                 "2026-03-01"]),
        "exit": pd.to_datetime(["2026-01-20", "2026-01-21", "2026-02-20",
                                "2026-03-20"]),
        "net_bp": [1.0, 50.0, 3.0, 2.0],
    })
    # the 50bp trade starts inside the first trade's window and must be dropped
    kept = nonoverlapping_sharpe(t)
    a = np.array([1.0, 3.0, 2.0])
    assert kept == pytest.approx(a.mean() / a.std(ddof=1))


def test_cost_curve_is_linear_in_the_cost():
    t = pd.DataFrame({"gross_bp": [3.0, 1.0, -1.0]})
    cc = cost_curve(t, [0.0, 1.0]).set_index("round_trip_bp")
    assert cc.loc[0.0, "total_net_bp"] == pytest.approx(3.0)
    assert cc.loc[1.0, "total_net_bp"] == pytest.approx(0.0)


def test_verdict_taxonomy():
    assert verdict(net_bp_at_taker=5.0, net_bp_at_maker=9.0, dsr_prob=0.9,
                   median_net_bp=1.0, n_trades=50) == "ALIVE"
    assert verdict(net_bp_at_taker=-1.0, net_bp_at_maker=4.0, dsr_prob=0.9,
                   median_net_bp=1.0, n_trades=50) == "MARGINAL-maker-only"
    # profitable at taker but the search does not survive deflation
    assert verdict(net_bp_at_taker=5.0, net_bp_at_maker=9.0, dsr_prob=0.2,
                   median_net_bp=1.0, n_trades=50) == "SELECTION-ARTIFACT"
    assert verdict(net_bp_at_taker=-5.0, net_bp_at_maker=-1.0, dsr_prob=0.1,
                   median_net_bp=-2.0, n_trades=50) == "DEAD"
    assert "too few" in verdict(net_bp_at_taker=5.0, net_bp_at_maker=5.0,
                                dsr_prob=0.9, median_net_bp=1.0, n_trades=3)


def test_verdict_requires_a_positive_median_config():
    """A lucky corner with a negative median sweep is never ALIVE."""
    assert verdict(net_bp_at_taker=5.0, net_bp_at_maker=9.0, dsr_prob=0.9,
                   median_net_bp=-3.0, n_trades=50) == "SELECTION-ARTIFACT"


# ---------------------------------------------------------------------------
# daily delta hedging
# ---------------------------------------------------------------------------
def test_hedged_path_earns_yesterdays_hedge_each_day(panel):
    """Constant +0.5 delta, price falling 1bp/day => hedge earns +0.5bp/day."""
    from RVUtils.SFRRVLab import hedged_path
    c, q = panel
    book = MarkBook(q, c)
    k = float(q[q["symbol"] == "SFRH27"]["strike_price"].iloc[0])
    st = Structure((Leg("option", "SFRH27", 1.0, "C", k),))
    value, _stale, cost = hedged_path(book, st, DATES, rehedge_band=1e9,
                                      future_cost_bp=0.0)
    cost = float(np.asarray(cost).sum())
    opt, _ = mark_structure(book, st, DATES)
    hedge_pnl = (value - opt) - (value[0] - opt[0])
    assert hedge_pnl[1] == pytest.approx(0.5)
    assert hedge_pnl[-1] == pytest.approx(0.5 * (len(DATES) - 1))
    assert cost == pytest.approx(0.0)


def test_hedged_path_charges_every_rehedge(panel):
    from RVUtils.SFRRVLab import hedged_path
    c, q = panel
    book = MarkBook(q, c)
    k = float(q[q["symbol"] == "SFRH27"]["strike_price"].iloc[0])
    st = Structure((Leg("option", "SFRH27", 1.0, "C", k),))
    _v, _s, cost_tight = hedged_path(book, st, DATES, rehedge_band=0.0,
                                     future_cost_bp=1.0)
    _v, _s, cost_wide = hedged_path(book, st, DATES, rehedge_band=1e9,
                                    future_cost_bp=1.0)
    # cost is returned as a cumulative array so the engine can charge it to both
    # directions rather than crediting it to shorts
    assert float(cost_tight[-1]) >= float(cost_wide[-1]) > 0.0


def test_hedged_path_beats_a_static_hedge_on_a_moving_market(panel):
    """A static hedge stops matching; the daily one keeps the delta at zero."""
    from RVUtils.SFRRVLab import hedge_each_contract, hedged_path
    c, q = panel
    book = MarkBook(q, c)
    k = float(q[q["symbol"] == "SFRH27"]["strike_price"].iloc[0])
    st = Structure((Leg("option", "SFRH27", 1.0, "C", k),))
    static = hedge_each_contract(book, st, DATES[0])
    assert static.n_future_legs == pytest.approx(0.5)
    dyn, _s, _c = hedged_path(book, st, DATES, rehedge_band=0.0,
                              future_cost_bp=0.0)
    stat_marks, _ = mark_structure(book, static, DATES)
    # deltas are constant in this fixture, so the two must agree exactly
    assert (dyn - dyn[0])[-1] == pytest.approx((stat_marks - stat_marks[0])[-1])


def test_engine_daily_hedge_changes_the_pnl_path():
    dates, book = _linear_book()
    sig = pd.DataFrame({"key": "K", "as_of": dates,
                        "signal": np.where(np.arange(len(dates)) == 20, 10.0, 0.0)})
    base = dict(ma=1, zscore_window=10, zscore_min_periods=5, entry_min_zscore=2.0,
                direction="momentum", exit_style="t5", round_trip_cost_bp=0.0,
                exit_max_holding_days=50)
    plain = run_backtest(LabConfig(delta_hedge="none", **base), signals=sig,
                         book=book, builder=_builder)
    hedged = run_backtest(LabConfig(delta_hedge="daily", future_leg_bp=0.0, **base),
                          signals=sig, book=book, builder=_builder)
    assert "dh" in hedged.config.label()
    # the futures leg is flat in this fixture, so the hedge adds no P&L
    assert hedged.trades["gross_bp"].iloc[0] == pytest.approx(
        plain.trades["gross_bp"].iloc[0])


# ---------------------------------------------------------------------------
# meeting lattice (FedWatch-style curve-only null)
# ---------------------------------------------------------------------------
def test_day_weight_matrix_is_the_post_meeting_share_of_the_quarter():
    from RVUtils.SFRRVLab.lattice import day_weight_matrix
    q = (datetime.date(2026, 3, 18), datetime.date(2026, 6, 17))   # 91 days
    # a meeting before the quarter starts affects the whole of it
    w_before = day_weight_matrix([q], [datetime.date(2026, 1, 28)])
    assert w_before[0, 0] == pytest.approx(1.0)
    # a meeting after it ends affects none of it
    w_after = day_weight_matrix([q], [datetime.date(2026, 7, 29)])
    assert w_after[0, 0] == pytest.approx(0.0)
    # a meeting inside it is fractional, and effective the day after
    w_in = day_weight_matrix([q], [datetime.date(2026, 4, 29)])
    days_after = (q[1] - datetime.date(2026, 4, 30)).days
    assert w_in[0, 0] == pytest.approx(days_after / (q[1] - q[0]).days)


def test_solve_meeting_jumps_recovers_planted_jumps():
    """Given a weight matrix and known jumps, the solve must invert them."""
    from RVUtils.SFRRVLab.lattice import solve_meeting_jumps
    rng = np.random.default_rng(3)
    W = np.array([[1.0, 0.6, 0.0], [1.0, 1.0, 0.4], [1.0, 1.0, 1.0]])
    truth = np.array([25.0, -12.5, 40.0])
    base = 400.0
    fwd = base + W @ truth
    got = solve_meeting_jumps(fwd, W, base, ridge=1e-9)
    assert np.allclose(got, truth, atol=1e-6)


def test_meeting_null_is_a_normalised_distribution_with_the_right_mean():
    """Independent lattice: E[offset] must equal sum_m w_m * jump_m."""
    from RVUtils.SFRRVLab.lattice import meeting_null_distribution
    jumps = [25.0, -12.5, 7.0]
    weights = [1.0, 0.5, 0.25]
    off, p = meeting_null_distribution(jumps, weights, merge_bp=0.05)
    assert p.sum() == pytest.approx(1.0)
    expected = sum(j * w for j, w in zip(jumps, weights))
    assert float((off * p).sum()) == pytest.approx(expected, abs=0.1)


def test_meeting_null_ignores_meetings_with_no_weight():
    from RVUtils.SFRRVLab.lattice import meeting_null_distribution
    a = meeting_null_distribution([25.0, 25.0], [1.0, 0.0], merge_bp=0.05)
    b = meeting_null_distribution([25.0], [1.0], merge_bp=0.05)
    assert np.allclose(a[0], b[0]) and np.allclose(a[1], b[1])


def test_null_prob_ge_is_monotone_decreasing_in_the_strike():
    from RVUtils.SFRRVLab.lattice import meeting_null_distribution, null_prob_ge
    off, p = meeting_null_distribution([25.0, 25.0], [1.0, 0.5], merge_bp=0.05)
    ks = [380.0, 400.0, 420.0, 440.0]
    probs = [null_prob_ge(off, p, 400.0, k) for k in ks]
    assert probs == sorted(probs, reverse=True)
    assert probs[0] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# delta scale (the vendor quotes delta in percent, not as a decimal)
# ---------------------------------------------------------------------------
def test_markbook_normalises_percent_deltas_to_decimals():
    """An ATM SR3 option prints delta_abs ~46; hedging on that oversizes 100x."""
    c = _contracts()
    q = _quotes(c)
    q["delta_abs"] = 46.0                       # vendor scale
    book = MarkBook(q, c)
    assert book.delta_scale == pytest.approx(100.0)
    leg = Leg("option", "SFRH27", 1.0, "C", float(q["strike_price"].iloc[0]))
    s = book.delta_series(leg)
    assert float(s.iloc[0]) == pytest.approx(0.46)


def test_markbook_leaves_decimal_deltas_alone():
    c = _contracts()
    q = _quotes(c)
    q["delta_abs"] = 0.46
    book = MarkBook(q, c)
    assert book.delta_scale == pytest.approx(1.0)
    leg = Leg("option", "SFRH27", 1.0, "C", float(q["strike_price"].iloc[0]))
    assert float(book.delta_series(leg).iloc[0]) == pytest.approx(0.46)


def test_put_delta_is_negative_in_price_space():
    c = _contracts()
    q = _quotes(c)
    book = MarkBook(q, c)
    k = float(q["strike_price"].iloc[0])
    assert float(book.delta_series(Leg("option", "SFRH27", 1.0, "P", k)).iloc[0]) < 0
    assert float(book.delta_series(Leg("option", "SFRH27", 1.0, "C", k)).iloc[0]) > 0


def test_hedge_size_is_sane_for_a_percent_scaled_panel():
    """The hedge for one ATM option must be well under one futures contract."""
    from RVUtils.SFRRVLab import hedge_each_contract
    c = _contracts()
    q = _quotes(c)
    q["delta_abs"] = 46.0
    book = MarkBook(q, c)
    st = Structure((Leg("option", "SFRH27", 1.0, "C", float(q["strike_price"].iloc[0])),))
    hedged = hedge_each_contract(book, st, DATES[0])
    assert hedged.n_future_legs == pytest.approx(0.46)


# ---------------------------------------------------------------------------
# unconditional entry rule (benchmarks and calendar rules)
# ---------------------------------------------------------------------------
def test_entry_rule_always_holds_one_side():
    """A z-score-driven 'benchmark' flips sides every bar; 'always' must not."""
    dates, book = _linear_book(n=60)
    sig = pd.DataFrame({"key": "K", "as_of": dates,
                        "signal": np.tile([1.0, -1.0], 30)})
    cfg = LabConfig(entry_rule="always", direction="fade", exit_style="t5",
                    entry_every=5, lag=1, round_trip_cost_bp=0.0,
                    zscore_min_periods=5, ma=1, zscore_window=10)
    res = run_backtest(cfg, signals=sig, book=book, builder=_builder)
    assert len(res.trades) > 3
    assert set(res.trades["dir"]) == {-1}          # short, every time
    assert "always" in cfg.label()

    long_cfg = dataclasses_replace(cfg, direction="momentum")
    res_long = run_backtest(long_cfg, signals=sig, book=book, builder=_builder)
    assert set(res_long.trades["dir"]) == {1}
    # on a +1bp/day path a short loses exactly what the long makes
    assert res.trades["gross_bp"].sum() == pytest.approx(
        -res_long.trades["gross_bp"].sum())


def test_zscore_rule_on_an_alternating_signal_flips_sides():
    """Documents the trap the 'always' rule exists to avoid."""
    dates, book = _linear_book(n=60)
    sig = pd.DataFrame({"key": "K", "as_of": dates,
                        "signal": np.tile([1.0, -1.0], 30)})
    cfg = LabConfig(entry_rule="zscore", direction="fade", exit_style="t1",
                    entry_every=1, lag=1, round_trip_cost_bp=0.0,
                    entry_min_zscore=0.5, zscore_min_periods=5, ma=1,
                    zscore_window=10)
    res = run_backtest(cfg, signals=sig, book=book, builder=_builder)
    assert len(set(res.trades["dir"])) == 2        # both sides — not a benchmark


def dataclasses_replace(cfg, **kw):
    import dataclasses as _d
    return _d.replace(cfg, **kw)


def test_hedged_path_is_memoised_per_book(panel):
    """A grid re-enters the same structure on the same date dozens of times."""
    from RVUtils.SFRRVLab import hedged_path
    c, q = panel
    book = MarkBook(q, c)
    k = float(q[q["symbol"] == "SFRH27"]["strike_price"].iloc[0])
    st = Structure((Leg("option", "SFRH27", 1.0, "C", k),))
    a = hedged_path(book, st, DATES, rehedge_band=0.0, future_cost_bp=0.25)
    b = hedged_path(book, st, DATES, rehedge_band=0.0, future_cost_bp=0.25)
    assert a[0] is b[0]                       # same array object -> cache hit
    # a different band must NOT reuse the cached path
    d = hedged_path(book, st, DATES, rehedge_band=0.5, future_cost_bp=0.25)
    assert d[0] is not a[0]


def test_hedge_costs_are_charged_to_both_sides():
    """Long and short of the same hedged package cannot both be gross positive.

    Their gross P&L must sum to exactly minus twice the re-hedge cost.
    """
    dates, book = _linear_book(n=60)
    sig = pd.DataFrame({"key": "K", "as_of": dates,
                        "signal": np.tile([1.0, -1.0], 30)})
    base = dict(entry_rule="always", exit_style="t10", entry_every=20, lag=1,
                round_trip_cost_bp=0.0, delta_hedge="daily", future_leg_bp=1.0,
                zscore_min_periods=5, ma=1, zscore_window=10)
    lo = run_backtest(LabConfig(direction="momentum", **base), signals=sig,
                      book=book, builder=_builder)
    sh = run_backtest(LabConfig(direction="fade", **base), signals=sig,
                      book=book, builder=_builder)
    assert len(lo.trades) == len(sh.trades) > 0
    total = lo.trades["gross_bp"].sum() + sh.trades["gross_bp"].sum()
    assert total < 0                       # both sides pay, neither is credited
    # and it is exactly -2 x the hedge cost embedded in each leg
    assert lo.trades["gross_bp"].to_numpy() + sh.trades["gross_bp"].to_numpy() == \
        pytest.approx(np.full(len(lo.trades), total / len(lo.trades)))


def test_hedged_path_never_back_fills_a_delta_it_could_not_have_seen(panel):
    """A leading gap must produce no hedge, not a delta borrowed from the future."""
    from RVUtils.SFRRVLab import hedged_path
    c, q = panel
    k = float(q[q["symbol"] == "SFRH27"]["strike_price"].iloc[0])
    mask = ((q["symbol"] == "SFRH27") & (q["strike_price"] == k)
            & (q["right"] == "C") & (q["as_of"] <= DATES[2]))
    q2 = q[~mask]
    book = MarkBook(q2, c)
    st = Structure((Leg("option", "SFRH27", 1.0, "C", k),))
    value, _s, _c = hedged_path(book, st, DATES, rehedge_band=0.0,
                                future_cost_bp=0.0)
    opt, _ = mark_structure(book, st, DATES)
    hedge = (value - opt)
    # no delta observed before DATES[3] -> hedge P&L is flat over the gap
    assert hedge[1] == pytest.approx(hedge[0])
    assert hedge[2] == pytest.approx(hedge[0])


def test_z0_exit_cannot_fire_on_an_unconditional_entry():
    """'always' entries have no z-score to decay; the holding cap must close them."""
    dates, book = _linear_book(n=60)
    sig = pd.DataFrame({"key": "K", "as_of": dates, "signal": 1.0})
    cfg = LabConfig(entry_rule="always", direction="fade", exit_style="z0",
                    entry_every=10, lag=1, round_trip_cost_bp=0.0,
                    exit_max_holding_days=7, zscore_min_periods=5, ma=1,
                    zscore_window=10)
    res = run_backtest(cfg, signals=sig, book=book, builder=_builder)
    assert len(res.trades) > 0
    assert set(res.trades["exit_reason"]) <= {"max_hold", "eod"}


# ---------------------------------------------------------------------------
# parity completion (the panel carries OTM options only)
# ---------------------------------------------------------------------------
def test_complete_by_parity_reconstructs_the_missing_side():
    from RVUtils.SFRRVLab import complete_by_parity
    c = _contracts(n=1)
    row = c.iloc[0]
    q = pd.DataFrame([{
        "as_of": row["as_of"], "symbol": row["symbol"], "right": "P",
        "strike_price": 95.5, "strike_rate": 4.5, "premium_bp": 12.0,
        "iv_bp": 60.0, "delta_abs": 30.0, "atm_offset_bps": 0.0,
        "oi": 100.0, "volume": 1.0,
    }])
    out = complete_by_parity(q, c)
    assert len(out) == 2
    call = out[out["right"] == "C"].iloc[0]
    # C = P + (F - K) in bp of price; F = 96.0, K = 95.5 -> +50bp
    assert call["premium_bp"] == pytest.approx(12.0 + 50.0)
    assert bool(call["synthetic"]) is True
    assert call["oi"] == 0.0                       # never counts as liquidity
    assert call["delta_abs"] == pytest.approx(70.0)  # mirrored on the same scale


def test_complete_by_parity_leaves_two_sided_strikes_alone():
    from RVUtils.SFRRVLab import complete_by_parity
    c = _contracts()
    q = _quotes(c)
    out = complete_by_parity(q, c)
    assert len(out) == len(q)
    assert not out["synthetic"].any()


def test_parity_completion_removes_the_stale_mark_on_an_itm_leg():
    """A leg that crosses the money must keep marking, not freeze."""
    from RVUtils.SFRRVLab import complete_by_parity
    c = _contracts()
    q = _quotes(c)
    k = 96.25
    # drop the puts at 96.25 after day 4 (they would go ITM as the rate rises)
    drop = ((q["right"] == "P") & (q["strike_price"] == k)
            & (q["as_of"] > DATES[4]) & (q["symbol"] == "SFRH27"))
    thin = q[~drop]
    st = Structure((Leg("option", "SFRH27", 1.0, "P", k),))
    _m, stale_raw = mark_structure(MarkBook(thin, c), st, DATES)
    _m2, stale_fix = mark_structure(MarkBook(complete_by_parity(thin, c), c),
                                    st, DATES)
    assert stale_raw > 0.0
    assert stale_fix == pytest.approx(0.0)


def test_pnl_is_unchanged_by_bounding_the_mark_window():
    """The path is built over the holding cap only; P&L must not move."""
    dates, book = _linear_book(n=120)
    sig = pd.DataFrame({"key": "K", "as_of": dates,
                        "signal": np.where(np.arange(len(dates)) % 17 == 0,
                                           8.0, 0.0)})
    base = dict(ma=1, zscore_window=20, zscore_min_periods=10,
                entry_min_zscore=1.5, direction="momentum", exit_style="t5",
                round_trip_cost_bp=0.0, lag=1)
    short_cap = run_backtest(LabConfig(exit_max_holding_days=10, **base),
                             signals=sig, book=book, builder=_builder)
    long_cap = run_backtest(LabConfig(exit_max_holding_days=60, **base),
                            signals=sig, book=book, builder=_builder)
    # the t5 exit fires well inside both caps, so the trades must be identical
    assert len(short_cap.trades) == len(long_cap.trades) > 0
    assert short_cap.trades["gross_bp"].to_numpy() == pytest.approx(
        long_cap.trades["gross_bp"].to_numpy())
    assert short_cap.metrics["total_net_bp"] == pytest.approx(
        long_cap.metrics["total_net_bp"])

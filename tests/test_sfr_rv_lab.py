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
    assert verdict(net_bp_at_taker=-5.0, net_bp_at_maker=-1.0, dsr_prob=0.1,
                   median_net_bp=-2.0, n_trades=50) == "DEAD"
    assert "too few" in verdict(net_bp_at_taker=5.0, net_bp_at_maker=5.0,
                                dsr_prob=0.9, median_net_bp=1.0, n_trades=3)


def test_verdict_requires_a_positive_median_config():
    """A lucky corner with a negative median sweep is never ALIVE."""
    assert verdict(net_bp_at_taker=5.0, net_bp_at_maker=9.0, dsr_prob=0.9,
                   median_net_bp=-3.0, n_trades=50) == "MARGINAL-maker-only"

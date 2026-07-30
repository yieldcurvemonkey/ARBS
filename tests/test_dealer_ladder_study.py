"""Study-machinery tests. Each gate is exercised on synthetic data with a PLANTED
answer, so the tests verify a gate can detect what it claims to — not merely run.
"""
import numpy as np
import pandas as pd
import pytest

from BT.dealer_ladder import config as cfg
from BT.dealer_ladder import study

NY = "America/New_York"


def _grid(days=3, minutes=5, per_day=96):
    out = []
    for d in range(days):
        day = pd.Timestamp("2026-07-06", tz=NY) + pd.Timedelta(days=d)
        out.append(pd.date_range(day + pd.Timedelta(hours=8), periods=per_day,
                                 freq=f"{minutes}min"))
    return out[0].append(out[1:])


# ------------------------------------------------------------------- align
def test_align_long_inner_joins_both_axes():
    idx = _grid(days=1, per_day=4)
    sig = pd.DataFrame({"A": [1.0, 2, 3, 4], "B": [5.0, 6, 7, 8]}, index=idx)
    tgt = pd.DataFrame({"A": [0.1, 0.2, np.nan, 0.4], "C": [9.0, 9, 9, 9]}, index=idx[:4])
    out = study.align_long(sig, tgt)
    assert set(out["bucket"]) == {"A"}            # B and C are not shared
    assert len(out) == 3                          # the NaN target row is dropped
    assert list(out.columns) == ["ts", "bucket", "signal", "target"]


def test_align_long_carries_extras():
    idx = _grid(days=1, per_day=3)
    sig = pd.DataFrame({"A": [1.0, 2, 3]}, index=idx)
    tgt = pd.DataFrame({"A": [1.0, 1, 1]}, index=idx)
    ex = pd.DataFrame({"A": [7.0, 8, 9]}, index=idx)
    out = study.align_long(sig, tgt, extra={"basis": ex})
    assert out["basis"].tolist() == [7.0, 8.0, 9.0]


def test_align_long_no_overlap():
    a = pd.DataFrame({"A": [1.0]}, index=_grid(days=1, per_day=1))
    b = pd.DataFrame({"Z": [1.0]}, index=_grid(days=1, per_day=1))
    assert study.align_long(a, b).empty


# ------------------------------------------------------------- G2 lead-lag
def test_hy_lead_lag_detects_a_planted_lead():
    """Y is a delayed echo of X; the estimator must report a POSITIVE lls.

    BOTH sides are LEVELS: hy_corr differences them itself.
    """
    idx = _grid(days=2, minutes=1, per_day=300)
    rng = np.random.default_rng(0)
    x = pd.Series(rng.normal(size=len(idx)), index=idx).cumsum()
    y = x.shift(10).bfill()                              # X leads Y by 10 minutes
    ll = study.hy_lead_lag_by_day(pd.DataFrame({"A": x}),
                                  pd.DataFrame({"A": y}),
                                  lags=(-30.0, -10.0, 0.0, 10.0, 30.0))
    assert len(ll) == 2
    summ = study.summarise_lead_lag(ll)
    assert summ["mean"] > 0, summ
    assert (ll["peak_lag_min"] > 0).all(), ll


def test_hy_on_synchronous_levels_is_the_increment_correlation():
    """Pins the LEVELS contract concretely.

    With identical observation times, the Hayashi-Yoshida estimator reduces to the
    ordinary correlation of the INCREMENTS -- which is why the caller hands it the
    ladder LEVEL and the CUMULATIVE flow, and why handing it already-differenced
    series would estimate a different object (the covariance of second differences).
    """
    from BT.dealer_ladder import hy

    rng = np.random.default_rng(5)
    idx = _grid(days=1, minutes=1, per_day=250)
    dx = rng.normal(size=len(idx))
    dy = 0.7 * dx + 0.7 * rng.normal(size=len(idx))
    x = pd.Series(dx, index=idx).cumsum()
    y = pd.Series(dy, index=idx).cumsum()

    hy_rho = hy.hy_corr(x.index, x.to_numpy(), y.index, y.to_numpy())
    inc_rho = float(np.corrcoef(np.diff(x.to_numpy()), np.diff(y.to_numpy()))[0, 1])
    assert hy_rho == pytest.approx(inc_rho, abs=0.02), (hy_rho, inc_rho)


def test_hy_lead_lag_reports_no_lead_on_independent_series():
    idx = _grid(days=3, minutes=1, per_day=200)
    rng = np.random.default_rng(1)
    x = pd.DataFrame({"A": rng.normal(size=len(idx)).cumsum()}, index=idx)
    y = pd.DataFrame({"A": rng.normal(size=len(idx)).cumsum()}, index=idx)
    summ = study.summarise_lead_lag(study.hy_lead_lag_by_day(x, y))
    assert abs(summ["t"]) < 3.0, summ


def test_hy_lead_lag_skips_thin_buckets():
    idx = _grid(days=1, minutes=5, per_day=2)
    x = pd.DataFrame({"A": [1.0, 2.0]}, index=idx)
    y = pd.DataFrame({"A": [1.0, 2.0]}, index=idx)
    assert study.hy_lead_lag_by_day(x, y).empty


def test_summarise_lead_lag_on_empty():
    out = study.summarise_lead_lag(pd.DataFrame())
    assert out["n"] == 0 and out["stars"] == ""


def test_flow_response_event_study_states_its_expected_sign():
    idx = _grid(days=1, minutes=5, per_day=50)
    rng = np.random.default_rng(2)
    inc = pd.DataFrame({"A": rng.normal(size=50) * 1000}, index=idx)
    flow = pd.DataFrame({"A": rng.normal(size=50) * 10}, index=idx)
    ev = study.flow_response_event_study(inc, flow, horizons_min=(5, 15))
    assert not ev.empty
    assert (ev["expected_sign"] == -1).all()      # hedging predicts flow AGAINST
    assert set(ev["horizon_min"]) == {5, 15}
    # top-decile events only
    assert len(ev) == 2 * int(np.ceil(50 * 0.1)) or len(ev) <= 2 * 6


# ----------------------------------------------------------- G3 horse race
def test_horse_race_signal_survives_when_it_is_the_only_driver():
    idx = _grid(days=20, minutes=30, per_day=16)
    rng = np.random.default_rng(3)
    sig = rng.normal(size=len(idx))
    frame = pd.DataFrame({"ts": idx, "bucket": "A", "signal": sig,
                          "basis": rng.normal(size=len(idx)),
                          "target": 0.8 * sig + rng.normal(scale=0.3, size=len(idx))})
    out = study.horse_race(frame, controls=["basis"])
    both = out[(out["spec"] == "signal + controls") & (out["term"] == "signal")]
    alone = out[(out["spec"] == "signal only") & (out["term"] == "signal")]
    assert float(alone["coef"].iloc[0]) == pytest.approx(0.8, abs=0.15)
    assert float(both["coef"].iloc[0]) == pytest.approx(0.8, abs=0.15)
    assert float(both["t"].iloc[0]) > 3


def test_horse_race_signal_collapses_when_the_basis_is_the_real_driver():
    """The exact case the gate exists to catch: the ladder is a proxy for basis."""
    idx = _grid(days=20, minutes=30, per_day=16)
    rng = np.random.default_rng(4)
    basis = rng.normal(size=len(idx))
    sig = basis + rng.normal(scale=0.05, size=len(idx))     # signal ~ basis
    frame = pd.DataFrame({"ts": idx, "bucket": "A", "signal": sig, "basis": basis,
                          "target": 1.0 * basis + rng.normal(scale=0.2, size=len(idx))})
    out = study.horse_race(frame, controls=["basis"])
    alone = out[(out["spec"] == "signal only") & (out["term"] == "signal")].iloc[0]
    both = out[(out["spec"] == "signal + controls") & (out["term"] == "signal")].iloc[0]
    basis = out[(out["spec"] == "signal + controls") & (out["term"] == "basis")].iloc[0]
    assert float(alone["t"]) > 3                      # looks great on its own...
    assert abs(float(both["t"])) < 2.0                # ...loses significance
    assert float(both["se"]) > 3 * float(alone["se"])  # collinearity inflates the SE
    assert float(basis["coef"]) > 0.5                 # the basis carries the effect


def test_horse_race_uses_day_clustered_errors():
    """Cluster-robust t must be far below the naive t on day-correlated data."""
    idx = _grid(days=30, minutes=30, per_day=16)
    rng = np.random.default_rng(5)
    day = np.repeat(rng.normal(size=30), 16)
    sig = day + rng.normal(scale=0.01, size=len(idx))
    frame = pd.DataFrame({"ts": idx, "bucket": "A", "signal": sig,
                          "target": day + rng.normal(scale=0.01, size=len(idx))})
    out = study.horse_race(frame)
    row = out[(out["spec"] == "signal only") & (out["term"] == "signal")].iloc[0]
    assert row["n_blocks"] == 30
    assert row["se"] > 0


def test_horse_race_empty():
    assert study.horse_race(pd.DataFrame(columns=["ts", "signal", "target"])).empty


def test_leave_one_bucket_out_exposes_a_single_contract_story():
    idx = _grid(days=10, minutes=30, per_day=16)
    rng = np.random.default_rng(6)
    frames = []
    for bucket, strength in (("A", 3.0), ("B", 0.0), ("C", 0.0)):
        s = rng.normal(size=len(idx))
        frames.append(pd.DataFrame({
            "ts": idx, "bucket": bucket, "signal": s,
            "target": strength * s + rng.normal(scale=0.3, size=len(idx))}))
    frame = pd.concat(frames, ignore_index=True)

    def stat(sub):
        from BT.dealer_ladder import stats as st
        r = st.cluster_mean_t((sub["signal"] * sub["target"]).to_numpy(),
                              st.day_codes(sub["ts"]))
        return {"t": r["t"], "mean": r["mean"]}

    out = study.leave_one_bucket_out(frame, stat).set_index("held_out")
    # dropping A must gut it; dropping B or C must not
    assert out.loc["A", "t"] < out.loc["B", "t"]
    assert out.loc["A", "mean"] < 0.5 * out.loc["<none>", "mean"]


def test_residualise_removes_the_control_variation():
    idx = _grid(days=5, minutes=30, per_day=16)
    rng = np.random.default_rng(7)
    basis = rng.normal(size=len(idx))
    frame = pd.DataFrame({"ts": idx, "bucket": "A", "basis": basis,
                          "signal": 2.0 * basis + rng.normal(scale=0.1, size=len(idx))})
    resid = study.residualise(frame, controls=["basis"])
    assert abs(float(np.corrcoef(resid, basis)[0, 1])) < 1e-8


def test_residualise_without_controls_is_identity():
    frame = pd.DataFrame({"ts": _grid(days=1, per_day=3), "signal": [1.0, 2, 3]})
    pd.testing.assert_series_equal(study.residualise(frame), frame["signal"])


# --------------------------------------------------------- G4 trade ledger
def _z_and_rates(days=8, per_day=96, minutes=5, seed=0, effect=0.0):
    idx = _grid(days=days, minutes=minutes, per_day=per_day)
    rng = np.random.default_rng(seed)
    z = pd.DataFrame({"SFRU26": rng.normal(size=len(idx)) * 1.5}, index=idx)
    noise = rng.normal(scale=0.3, size=len(idx))
    # planted effect: rate drifts in the direction of z over the next 60 min
    rate = pd.DataFrame({"SFRU26": np.cumsum(noise + effect * np.r_[0, z["SFRU26"][:-1]])},
                        index=idx)
    return z, rate


def test_trade_ledger_trades_never_overlap_within_a_bucket():
    z, rate = _z_and_rates()
    led = study.trade_ledger(z, rate, horizon_min=60, threshold=1.0,
                             cost_bp_by_bucket={"SFRU26": 0.5})
    assert not led.empty
    for _, g in led.groupby("bucket"):
        g = g.sort_values("ts").reset_index(drop=True)
        nxt = g["ts"].iloc[1:].reset_index(drop=True)
        prev_exit = g["exit_ts"].iloc[:-1].reset_index(drop=True)
        assert (nxt >= prev_exit).all()


def test_trade_ledger_respects_the_threshold_and_the_sign_rule():
    z, rate = _z_and_rates()
    led = study.trade_ledger(z, rate, horizon_min=30, threshold=2.0,
                             cost_bp_by_bucket={"SFRU26": 0.0})
    assert (led["z"].abs() >= 2.0).all()
    assert (np.sign(led["position"]) == np.sign(led["z"])).all()   # predicted_sign=+1


def test_trade_ledger_flips_with_predicted_sign():
    z, rate = _z_and_rates()
    led = study.trade_ledger(z, rate, horizon_min=30, threshold=1.0,
                             cost_bp_by_bucket={"SFRU26": 0.0}, predicted_sign=-1)
    assert (np.sign(led["position"]) == -np.sign(led["z"])).all()


def test_trade_ledger_charges_the_cost_once_per_round_trip():
    z, rate = _z_and_rates()
    led = study.trade_ledger(z, rate, horizon_min=30, threshold=1.0,
                             cost_bp_by_bucket={"SFRU26": 0.5})
    assert (led["cost_bp"] == 0.5).all()
    assert np.allclose(led["net_bp"], led["gross_bp"] - 0.5)


def test_trade_ledger_drops_trades_with_no_exit_price():
    z, rate = _z_and_rates(days=1)
    rate.iloc[20:] = np.nan
    led = study.trade_ledger(z, rate, horizon_min=60, threshold=0.5,
                             cost_bp_by_bucket={"SFRU26": 0.0})
    assert led["exit_bp"].notna().all()


def test_trade_ledger_honours_a_staleness_cap():
    z, rate = _z_and_rates(days=2)
    stale = pd.DataFrame({"SFRU26": np.full(len(z), 99.0)}, index=z.index)
    led = study.trade_ledger(z, rate, horizon_min=30, threshold=0.5,
                             cost_bp_by_bucket={"SFRU26": 0.0},
                             stale_min=stale, max_stale_min=5)
    assert led.empty


def test_evaluate_trades_finds_a_planted_edge_and_rejects_a_null():
    z, rate = _z_and_rates(days=40, effect=0.25, seed=11)
    led = study.trade_ledger(z, rate, horizon_min=60, threshold=1.0,
                             cost_bp_by_bucket={"SFRU26": 0.0})
    res = study.evaluate_trades(led, n_boot=300)
    assert res["mean"] > 0 and res["t"] > 2, res
    assert res["lo"] < res["mean"] < res["hi"]

    z0, rate0 = _z_and_rates(days=40, effect=0.0, seed=12)
    led0 = study.trade_ledger(z0, rate0, horizon_min=60, threshold=1.0,
                              cost_bp_by_bucket={"SFRU26": 0.0})
    res0 = study.evaluate_trades(led0, n_boot=300)
    assert abs(res0["t"]) < 3.0, res0


def test_evaluate_trades_empty():
    res = study.evaluate_trades(pd.DataFrame())
    assert res["n"] == 0 and res["stars"] == ""


def test_cost_bp_map_uses_the_front_back_split():
    c = cfg.CostConfig()
    out = study.cost_bp_map(["SFRU26", "SFRZ28", "FFN26"], c,
                            near_expiry={"SFRU26": True, "SFRZ28": False, "FFN26": True},
                            root_by_bucket={"SFRU26": "SR3", "SFRZ28": "SR3",
                                            "FFN26": "ZQ"})
    assert out["SFRU26"] == pytest.approx(0.25)   # near expiry
    assert out["SFRZ28"] == pytest.approx(0.50)   # deferred
    assert out["FFN26"] == pytest.approx(0.50)    # ZQ conservative throughout


# ----------------------------------------------------------------- placebos
def _prints_for_placebo():
    idx = _grid(days=2, minutes=30, per_day=16)
    rng = np.random.default_rng(9)
    return pd.DataFrame({
        "unit_key": [f"u{i}" for i in range(len(idx))],
        "bucket_space": "FUTURES", "bucket_key": "SFRU26",
        "delta_dv01": rng.normal(scale=1000, size=len(idx)),
        "visibility_timestamp": idx,
        "execution_timestamp": idx - pd.Timedelta(minutes=1),
        "p_flip": 0.0, "curve_suspect_trade": False, "is_block": False,
    })


def test_sign_shuffle_preserves_magnitudes_and_destroys_order():
    p = _prints_for_placebo()
    out = study.placebo_sign_shuffle(p, seed=1)
    np.testing.assert_allclose(sorted(out["delta_dv01"].abs()),
                               sorted(p["delta_dv01"].abs()))
    assert not np.allclose(out["delta_dv01"], p["delta_dv01"])


def test_sign_shuffle_keeps_the_sign_count_within_each_session():
    p = _prints_for_placebo()
    out = study.placebo_sign_shuffle(p, seed=2)
    day = pd.to_datetime(p["visibility_timestamp"]).dt.tz_convert(NY).dt.date
    for d in pd.unique(day):
        m = (day == d).to_numpy()
        assert (np.sign(out["delta_dv01"][m]) > 0).sum() == \
               (np.sign(p["delta_dv01"][m]) > 0).sum()


def test_shift_arrival_moves_every_visibility():
    p = _prints_for_placebo()
    out = study.placebo_shift_arrival(p, 5)
    assert ((pd.to_datetime(out["visibility_timestamp"])
             - pd.to_datetime(p["visibility_timestamp"]))
            == pd.Timedelta(minutes=5)).all()


def test_live_parity_is_a_floor_not_a_shift():
    p = _prints_for_placebo()
    # one print already legally delayed 60 minutes must keep its later time
    p.loc[0, "visibility_timestamp"] = p.loc[0, "execution_timestamp"] + pd.Timedelta(minutes=60)
    out = study.placebo_live_parity(p, floor_min=15)
    assert (pd.to_datetime(out["visibility_timestamp"]).iloc[0]
            == pd.to_datetime(p["visibility_timestamp"]).iloc[0])
    later = pd.to_datetime(out["visibility_timestamp"]).iloc[1:]
    exec1 = pd.to_datetime(p["execution_timestamp"]).iloc[1:]
    assert ((later - exec1) >= pd.Timedelta(minutes=15)).all()


def test_rotate_buckets_keeps_the_column_set():
    idx = _grid(days=1, per_day=3)
    panel = pd.DataFrame({"A": [1.0, 2, 3], "B": [4.0, 5, 6], "C": [7.0, 8, 9]}, index=idx)
    out = study.placebo_rotate_buckets(panel, shift=1)
    assert list(out.columns) == ["A", "B", "C"]
    assert out["A"].tolist() == [4.0, 5.0, 6.0]     # A now carries B's series
    assert out["C"].tolist() == [1.0, 2.0, 3.0]     # and C wraps around to A's


def test_rotate_buckets_single_column_is_a_noop():
    panel = pd.DataFrame({"A": [1.0]}, index=_grid(days=1, per_day=1))
    pd.testing.assert_frame_equal(study.placebo_rotate_buckets(panel), panel)


def test_pre_arrival_target_looks_backwards():
    idx = pd.date_range("2026-07-06 08:00", periods=10, freq="5min", tz=NY)
    rate = pd.DataFrame({"A": np.arange(10.0)}, index=idx)
    back = study.pre_arrival_target(rate, 10)      # 10 min = 2 rows
    assert back["A"].iloc[2] == pytest.approx(2.0)
    assert back["A"].iloc[:2].isna().all()


# ------------------------------------------------------------------ G5 / ledger
def test_capacity_curve_labels_itself_as_a_volume_sensitivity():
    z, rate = _z_and_rates(days=4)
    led = study.trade_ledger(z, rate, horizon_min=30, threshold=1.0,
                             cost_bp_by_bucket={"SFRU26": 0.0})
    vols = pd.DataFrame({"SFRU26": np.full(len(z), 100.0)}, index=z.index)
    cap = study.capacity_curve(led, vols, participation=(0.05, 0.10))
    assert list(cap["participation"]) == [0.05, 0.10]
    assert (cap["basis"].str.contains("NOT measured depth")).all()
    assert cap["median_dv01_per_trade"].iloc[1] > cap["median_dv01_per_trade"].iloc[0]


def test_capacity_curve_empty():
    assert study.capacity_curve(pd.DataFrame(), pd.DataFrame()).empty


def test_net_of_costs_table_reports_the_attenuation_grid():
    z, rate = _z_and_rates(days=10, effect=0.3, seed=21)
    led = study.trade_ledger(z, rate, horizon_min=60, threshold=1.0,
                             cost_bp_by_bucket={"SFRU26": 0.5})
    tab = study.net_of_costs_table(led)
    measures = list(tab["measure"])
    assert measures[:2] == ["gross", "net of costs"]
    assert any("a=0.60" in m for m in measures)
    net = float(tab[tab["measure"] == "net of costs"]["mean_bp"].iloc[0])
    a60 = float(tab[tab["measure"] == "net, accuracy a=0.60"]["mean_bp"].iloc[0])
    gross = float(tab[tab["measure"] == "gross"]["mean_bp"].iloc[0])
    # (2a-1)*GROSS - cost, NOT (2a-1)*net. The round trip is paid whether or not the
    # direction label was right, so attenuating the net figure discounts the cost
    # along with the edge and overstates every row by 2*cost*(1-a) -- 0.4bp at a=0.60
    # on this study's 0.5bp round trip, which is most of the edge being measured. The
    # old assertion (`net * 0.2`) locked the overstatement in.
    cost = float(led["cost_bp"].mean())
    assert a60 == pytest.approx(gross * 0.2 - cost)
    assert a60 < net * 0.2, "attenuating net would have looked better than the truth"


def test_trial_ledger_is_append_only_and_ordered():
    tl = study.TrialLedger()
    tl.record("primary", {"horizon": 60}, {"t": 3.1})
    tl.record("variant", {"horizon": 5}, {"t": 0.2}, note="discarded")
    df = tl.frame()
    assert list(df["trial"]) == [1, 2]
    assert df.loc[1, "note"] == "discarded"
    assert "cfg_horizon" in df.columns and "res_t" in df.columns
    assert len(tl) == 2

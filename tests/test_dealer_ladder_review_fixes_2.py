"""Regression tests for the second batch of 2026-07-30 adversarial-review findings.

Continues ``test_dealer_ladder_review_fixes.py``. These four arrived from the
statistics and data-and-costs reviewers after the first batch was already fixed, and
three of them were rated *invalidates-a-result*: the family-wise gate did not control
its own error rate, the economics gate could not fail, and the capacity headline was
understated by 4.7x. As with the first batch, every one of them passed the suite that
existed at the time.
"""
import dataclasses

import numpy as np
import pandas as pd
import pytest

from BT.dealer_ladder import controls, data, gates, stats, study
from tests.test_dealer_ladder_integration import _context, _no_write

NY = "America/New_York"


# ============ the bootstrap null must not merge a twice-drawn day into one cluster
def test_resample_blocks_labels_each_draw_as_its_own_cluster():
    """Reusing the ORIGINAL labels collapses the m copies of a day drawn m times into
    one cluster, turning the cluster meat into sum m^2 S^2 instead of sum m S^2. With
    E[m]=1 and E[m^2]~2 that doubles the bootstrap variance and shrinks |t*| by
    ~1/sqrt(2) -- while the OBSERVED t stays correct, so the null it is compared
    against is narrower than it should be."""
    blocks = np.repeat(np.arange(6), 3)
    idx, lab = stats.resample_blocks(blocks, np.random.default_rng(0),
                                     with_labels=True)
    assert idx.size == blocks.size
    assert len(np.unique(lab)) == 6, "one label per DRAW, not per distinct day"

    drawn = np.asarray(blocks)[idx]
    repeated = [g for g in np.unique(drawn) if (drawn == g).sum() > 3]
    assert repeated, "fixture drew no day twice; pick another seed"
    for g in repeated:
        m = int((drawn == g).sum() // 3)
        assert len(np.unique(lab[drawn == g])) == m

    # backward compatible: the plain call still returns just the indices
    plain = stats.resample_blocks(blocks, np.random.default_rng(0))
    assert isinstance(plain, np.ndarray) and plain.size == blocks.size


def test_romano_wolf_controls_family_wise_error_on_a_pure_null():
    """The measured cost of the label bug was FWER 0.19-0.25 at a nominal 0.05, on the
    exact panel shape run_grid builds -- so a grid of near-identical variants had
    roughly a 1-in-4 chance of a spurious "survives Romano-Wolf" verdict on data with
    no edge at all. 60 trials, tolerance 6: passes with p=0.96 at a true 0.05 and
    p=0.02 at 0.19, so unlike its predecessor this test can actually fail."""
    rng = np.random.default_rng(4)
    n_days, n_cols, rho, trials = 60, 12, 0.9, 60
    blocks = np.arange(n_days)
    rejects = 0
    for _ in range(trials):
        common = rng.normal(size=(n_days, 1))
        vals = (np.sqrt(rho) * common
                + np.sqrt(1.0 - rho) * rng.normal(size=(n_days, n_cols)))
        panel = pd.DataFrame(vals, columns=[f"v{i}" for i in range(n_cols)])
        rw = stats.romano_wolf(panel, blocks, n_boot=200,
                               seed=int(rng.integers(1 << 30)))
        rejects += int((rw["p_fwer"] < 0.05).any())
    assert rejects <= 6, f"{rejects}/{trials} false rejections at a nominal 0.05"


def test_bootstrap_p_values_are_never_exactly_zero():
    """A bare share can report 0.0, which is not a p-value: with B draws the strongest
    statement resampling supports is 1/(B+1)."""
    rng = np.random.default_rng(5)
    blocks = np.arange(40)
    panel = pd.DataFrame({"strong": rng.normal(size=40) + 8.0,
                          "weak": rng.normal(size=40)})
    rw = stats.romano_wolf(panel, blocks, n_boot=200, seed=1)
    assert (rw["p_raw"].dropna() > 0).all()
    assert (rw["p_fwer"].dropna() > 0).all()
    assert rw["p_raw"].min() == pytest.approx(1.0 / 201.0)


# ====================== the accuracy haircut applies to GROSS; cost is paid regardless
def test_attenuation_subtracts_the_full_cost():
    """(2a-1)*gross - cost. Attenuating NET discounts the cost along with the edge and
    overstates every row by exactly 2*cost*(1-a) -- an error that grows as accuracy
    falls, i.e. largest precisely where the report is trying to be conservative."""
    gross, cost = 1.0, 0.5
    for a in (0.6, 0.7, 0.8):
        got = stats.attenuate(gross, a, cost)
        assert got == pytest.approx((2 * a - 1) * gross - cost)
        wrong = (2 * a - 1) * (gross - cost)          # the old behaviour
        assert wrong - got == pytest.approx(2 * cost * (1 - a))


def test_at_chance_accuracy_you_lose_exactly_the_cost():
    """a=0.5 is trading noise. The honest answer is -cost, not 0.0."""
    assert stats.attenuate(1.0, 0.5, 0.5) == pytest.approx(-0.5)
    assert stats.attenuate(50.0, 0.5, 0.25) == pytest.approx(-0.25)
    assert stats.attenuate(1.0, 0.8) == pytest.approx(0.6), "cost defaults to zero"


def test_net_of_costs_table_attenuates_gross_and_reports_the_cost_row():
    idx = pd.date_range("2026-03-02 08:00", periods=200, freq="15min", tz=NY)
    rng = np.random.default_rng(6)
    led = pd.DataFrame({
        "ts": idx, "bucket": "A",
        "gross_bp": 1.0 + rng.normal(scale=0.1, size=len(idx)),
        "cost_bp": 0.5})
    led["net_bp"] = led["gross_bp"] - led["cost_bp"]
    tab = study.net_of_costs_table(led, attenuation=(0.6,))
    m = dict(zip(tab["measure"], tab["mean_bp"]))
    assert m["round-trip cost"] == pytest.approx(-0.5)
    assert m["net, accuracy a=0.60"] == pytest.approx(0.2 * m["gross"] - 0.5)
    assert m["net, accuracy a=0.60"] < 0.2 * m["net of costs"]


def test_g5_verdict_fails_when_the_attenuated_edge_cannot_pay_the_cost(monkeypatch):
    """The reviewer's measured case: gross 0.9776, cost 0.5. Attenuating net gave
    +0.0955 and pass=True; the correct worst case is -0.3045 and pass=False. A 0.4bp
    overstatement is most of the edge on offer when the round trip is 0.5bp."""
    _no_write(monkeypatch)
    ctx = _context(effect=0.6, seed=43)
    idx = pd.date_range("2026-03-02 08:00", periods=240, freq="15min", tz=NY)
    rng = np.random.default_rng(7)
    led = pd.DataFrame({
        "ts": idx, "exit_ts": idx + pd.Timedelta(minutes=60), "bucket": "SFRU26",
        "position": 1, "gross_bp": 0.9776 + rng.normal(scale=0.05, size=len(idx)),
        "cost_bp": 0.5})
    led["net_bp"] = led["gross_bp"] - led["cost_bp"]
    out = gates.run_g5(ctx, {"ledger": led})
    assert out["verdict"]["pass"] is False, out["verdict"]["headline"]
    assert "-0.3" in out["verdict"]["headline"]


# ================ volume is a FLOW: aggregate it, never sample one minute in five
def test_to_grid_sum_keeps_every_minute_of_volume():
    """Reindexing a 1-minute volume panel onto the 5-minute decision grid kept one
    minute in five -- measured at 21% of true traded volume, which understated the
    capacity headline by 4.7x and handed the lead-lag test a volume drawn from a
    minute the price move did not touch."""
    minute = pd.date_range("2026-03-02 09:00", periods=60, freq="1min", tz=NY)
    vols = pd.DataFrame({"SFRU26": np.full(60, 100.0)}, index=minute)
    grid = pd.date_range("2026-03-02 09:05", periods=11, freq="5min", tz=NY)
    agg = data.to_grid_sum(vols, grid)
    assert (agg["SFRU26"].dropna() == 500.0).all(), "5 minutes x 100 per bar"
    # a plain reindex sees a fifth of it
    assert vols.reindex(grid)["SFRU26"].sum() == pytest.approx(1100.0)
    assert agg["SFRU26"].sum() > 4.0 * vols.reindex(grid)["SFRU26"].sum()


def test_to_grid_sum_never_includes_volume_from_after_the_stamp():
    minute = pd.date_range("2026-03-02 09:00", periods=20, freq="1min", tz=NY)
    v = pd.DataFrame({"A": np.zeros(20)}, index=minute)
    v.iloc[11] = 999.0                     # 09:11, inside the (09:10, 09:15] bar
    grid = pd.date_range("2026-03-02 09:05", periods=3, freq="5min", tz=NY)
    agg = data.to_grid_sum(v, grid)
    assert agg.at[grid[1], "A"] == 0.0, "the 09:10 stamp must not see 09:11"
    assert agg.at[grid[2], "A"] == 999.0


def test_to_grid_sum_preserves_no_data_as_nan():
    minute = pd.date_range("2026-03-02 09:00", periods=10, freq="1min", tz=NY)
    v = pd.DataFrame({"A": np.full(10, np.nan)}, index=minute)
    agg = data.to_grid_sum(v, pd.date_range("2026-03-02 09:05", periods=2,
                                            freq="5min", tz=NY))
    assert agg["A"].isna().all(), "an absent bar must not be summed to zero"


# ============== rolling windows are in MINUTES and never cross the overnight break
def test_amihud_window_is_minutes_not_rows():
    """rolling(60) on a 5-minute grid is a trailing 5 HOURS. The horse race then
    reported "survives the liquidity control" about a control other than the
    documented one."""
    idx = pd.date_range("2026-03-02 08:00", periods=96, freq="5min", tz=NY)
    rates = pd.DataFrame({"A": np.arange(96.0)}, index=idx)   # 1bp per 5min
    vols = pd.DataFrame({"A": np.full(96, 10.0)}, index=idx)
    am = controls.futures_amihud(rates, vols, window_min=60)
    # 60 minutes = 12 steps: 12 x 1bp of movement over 12 x 10 contracts
    assert am["A"].dropna().iloc[-1] == pytest.approx(12.0 / 120.0)


def test_amihud_and_vol_never_reach_across_the_overnight_break():
    days = ("2026-03-02", "2026-03-03")
    idx = pd.DatetimeIndex(np.concatenate([
        pd.date_range(f"{d} 08:00", periods=48, freq="5min", tz=NY) for d in days]))
    # day two opens 500bp away: an overnight gap that would dominate any window it
    # landed in, and a single .diff() would swallow it whole
    rates = pd.DataFrame({"A": np.r_[np.arange(48.0), 500.0 + np.arange(48.0)]},
                         index=idx)
    vols = pd.DataFrame({"A": np.full(96, 10.0)}, index=idx)
    am = controls.futures_amihud(rates, vols, window_min=60)
    rv = controls.realized_vol_bp(rates, window_min=60)

    open2 = idx[48]
    assert pd.isna(am.at[open2, "A"]) and pd.isna(rv.at[open2, "A"])
    day2 = am[[t.date() == open2.date() for t in am.index]]["A"].dropna()
    assert (day2 <= 12.0 / 120.0 + 1e-9).all(), f"overnight jump leaked: {day2.max()}"
    rv2 = rv[[t.date() == open2.date() for t in rv.index]]["A"].dropna()
    assert (rv2 < 1e-6).all(), "constant 1bp steps have zero stdev within a session"


def test_the_one_step_shift_does_not_carry_yesterdays_last_value():
    days = ("2026-03-02", "2026-03-03")
    idx = pd.DatetimeIndex(np.concatenate([
        pd.date_range(f"{d} 08:00", periods=48, freq="5min", tz=NY) for d in days]))
    rng = np.random.default_rng(8)
    rates = pd.DataFrame({"A": np.cumsum(rng.normal(size=96))}, index=idx)
    assert pd.isna(controls.realized_vol_bp(rates, window_min=60).at[idx[48], "A"])


def test_gate_context_volume_is_aggregated_not_sampled(monkeypatch):
    """The seam that mattered: load_context feeds these panels to capacity_curve and
    to the signed-flow series G2 tests."""
    _no_write(monkeypatch)
    ctx = _context(effect=0.4, seed=44)
    vols = ctx.volumes.get("FUTURES")
    assert vols is not None and not vols.empty
    assert (vols.dropna(how="all").to_numpy() >= 0).all()


# =========================== the label-free cell is the one result immune to the label
def test_label_free_builds_intensity_in_the_TARGET_space(monkeypatch):
    """It used the configured SIGNAL space. Whenever the two differ the SR3 and ZQ
    bucket namespaces are disjoint, so the reindex matched nothing and the cell reported
    "no trades" -- indistinguishable from a real null, on the one diagnostic that is
    supposed to be immune to the direction label."""
    _no_write(monkeypatch)
    ctx = _context(effect=0.6, seed=60)
    ctx = dataclasses.replace(ctx, config=dataclasses.replace(
        ctx.config, signal=dataclasses.replace(ctx.config.signal,
                                               space="FED_FUNDS")))
    out = gates.run_label_free(ctx, space="FUTURES")
    assert out["result"]["n"].iloc[0] > 0, "must not go silently empty"


def test_label_free_is_recorded_in_the_trial_ledger(monkeypatch):
    """A family-wise correction is only honest over the family actually searched, and
    this is a tradable configuration that could be reported as a result."""
    _no_write(monkeypatch)
    sink = study.TrialLedger()
    gates.run_label_free(_context(effect=0.5, seed=61), ledger_sink=sink)
    frame = sink.frame()
    assert len(frame) == 1
    assert "LABEL-FREE" in frame["label"].iloc[0]
    assert "res_t" in frame.columns


def test_label_free_signs_from_z_because_intensity_has_no_zero(monkeypatch):
    """Not an oversight: |delta_dv01| is non-negative, so a level-signed rule would take
    the same side every time. The asymmetry against the primary's level-signing is
    documented rather than hidden, because it weakens what the comparison can claim."""
    _no_write(monkeypatch)
    out = gates.run_label_free(_context(effect=0.6, seed=62))
    led = out["ledger"]
    assert not led.empty
    assert set(led["position"].unique()) <= {-1, 1}
    assert (led["signed_from"] == "zscore").all()


# ================= a conditioner that could not be split must SAY so, not vanish
def test_conditioning_records_conditioners_it_could_not_split(monkeypatch):
    """A split that quietly disappeared is indistinguishable from one that ran and
    showed nothing -- the same failure the grid's skipped-variant ledger exists for."""
    _no_write(monkeypatch)
    ctx = _context(effect=0.7, seed=63)
    primary = gates.run_primary(ctx, in_sample=True)
    out = gates.run_conditioning(ctx, primary)
    assert "skipped" in out
    total = len(out["conditioning"]["conditioner"].unique()) if len(out["conditioning"]) else 0
    from BT.dealer_ladder import controls as C
    declared = len(C.CONDITIONING_PANELS) + len(C.CONDITIONING_SERIES)
    assert total + len(out["skipped"]) == declared, (
        f"{total} split + {len(out['skipped'])} skipped != {declared} declared")
    if len(out["skipped"]):
        assert out["skipped"]["reason"].str.len().gt(0).all()


def test_conditioning_verdict_reports_the_skipped_count(monkeypatch):
    _no_write(monkeypatch)
    ctx = _context(effect=0.7, seed=64)
    out = gates.run_conditioning(ctx, gates.run_primary(ctx, in_sample=True))
    assert "could not be split" in out["verdict"]["headline"]


# ============ capacity must not count volume traded before the position existed
def test_capacity_window_is_strictly_after_entry():
    """The volume panel is right-closed, so the bar stamped at the entry minute covers
    the interval ENDING there -- traded before the position existed. Counting it inflates
    a 60-minute window by one bar in twelve, ~8% of the headline capacity number, in the
    optimistic direction."""
    idx = pd.date_range("2026-03-02 09:00", periods=13, freq="5min", tz=NY)
    vols = pd.DataFrame({"A": [1000.0] + [100.0] * 12}, index=idx)
    led = pd.DataFrame([{"ts": idx[0], "exit_ts": idx[12], "bucket": "A",
                         "net_bp": 0.0}])
    cap = study.capacity_curve(led, vols, participation=(1.0,),
                               dv01_per_contract=1.0)
    # 12 bars of 100 after entry; the 1000 at the entry stamp must NOT be counted
    assert cap["median_dv01_per_trade"].iloc[0] == pytest.approx(1200.0)


def test_capacity_counts_trades_it_could_not_price():
    """A median over a silently reduced subset is not the statistic it claims to be."""
    idx = pd.date_range("2026-03-02 09:00", periods=13, freq="5min", tz=NY)
    vols = pd.DataFrame({"A": 100.0}, index=idx)
    led = pd.DataFrame([
        {"ts": idx[0], "exit_ts": idx[12], "bucket": "A", "net_bp": 0.0},
        {"ts": idx[0], "exit_ts": idx[12], "bucket": "MISSING", "net_bp": 0.0},
    ])
    cap = study.capacity_curve(led, vols, participation=(0.1,))
    assert cap["n_trades_priced"].iloc[0] == 1
    assert cap["n_trades_dropped"].iloc[0] == 1


def test_capacity_on_a_ledger_no_bucket_of_which_can_be_priced():
    idx = pd.date_range("2026-03-02 09:00", periods=5, freq="5min", tz=NY)
    vols = pd.DataFrame({"A": 100.0}, index=idx)
    led = pd.DataFrame([{"ts": idx[0], "exit_ts": idx[4], "bucket": "Z",
                         "net_bp": 0.0}])
    assert study.capacity_curve(led, vols).empty


def test_capacity_says_what_it_is_measuring():
    idx = pd.date_range("2026-03-02 09:00", periods=5, freq="5min", tz=NY)
    vols = pd.DataFrame({"A": 100.0}, index=idx)
    led = pd.DataFrame([{"ts": idx[0], "exit_ts": idx[4], "bucket": "A",
                         "net_bp": 0.0}])
    basis = study.capacity_curve(led, vols)["basis"].iloc[0]
    assert "NOT measured depth" in basis and "(entry, exit]" in basis


# ============== a survival claim over a rank-deficient design is not worth making
def test_horse_race_flags_a_rank_deficient_design():
    """pinv silently absorbs collinearity and returns standard errors that mean very
    little. This is plausible rather than hypothetical here: basis_bp and abs_basis_bp
    coincide whenever the basis rarely changes sign."""
    idx = pd.date_range("2026-03-02 08:00", periods=300, freq="30min", tz=NY)
    rng = np.random.default_rng(9)
    sig = rng.normal(size=len(idx))
    basis = np.abs(rng.normal(size=len(idx)))       # never negative
    frame = pd.DataFrame({"ts": idx, "bucket": "A", "signal": sig,
                          "basis_bp": basis, "abs_basis_bp": np.abs(basis),
                          "target": sig + rng.normal(scale=0.5, size=len(idx))})
    out = study.horse_race(frame, controls=["basis_bp", "abs_basis_bp"])
    ctl = out[out["spec"] == "signal + controls"]
    assert ctl["rank_deficient"].all()
    assert (ctl["design_rank"] < ctl["design_cols"]).all()


def test_horse_race_reports_a_healthy_design_as_full_rank():
    idx = pd.date_range("2026-03-02 08:00", periods=300, freq="30min", tz=NY)
    rng = np.random.default_rng(10)
    sig, ctl_v = rng.normal(size=len(idx)), rng.normal(size=len(idx))
    frame = pd.DataFrame({"ts": idx, "bucket": "A", "signal": sig, "ctl": ctl_v,
                          "target": sig + rng.normal(scale=0.5, size=len(idx))})
    out = study.horse_race(frame, controls=["ctl"])
    assert not out["rank_deficient"].any()
    assert (out["design_cond"] < 100).all()


# ========== a one-sided rule must be readable against a constant-position benchmark
def test_share_long_reports_how_one_sided_the_rule_was():
    """84% of prints are PAID, PAID means negative delta_dv01, and the position is
    signed from the LEVEL -- so the rule can be overwhelmingly directional without that
    showing up in the mean or the t. Measured on Jan-Feb: 80% of triggers short rates."""
    idx = pd.date_range("2026-03-02 08:00", periods=50, freq="15min", tz=NY)
    led = pd.DataFrame({"ts": idx, "bucket": "A",
                        "position": [-1] * 40 + [1] * 10,
                        "entry_bp": 0.0, "exit_bp": 1.0, "cost_bp": 0.0})
    led["gross_bp"] = led["position"] * (led["exit_bp"] - led["entry_bp"])
    led["net_bp"] = led["gross_bp"] - led["cost_bp"]
    r = study.evaluate_trades(led, n_boot=200)
    assert r["share_long"] == pytest.approx(0.2)


def test_constant_position_benchmark_prices_the_same_trades():
    """Same entries, exits and costs; only the position varies. If the rule cannot beat
    the better constant, the ladder is contributing nothing beyond direction."""
    idx = pd.date_range("2026-03-02 08:00", periods=60, freq="15min", tz=NY)
    rng = np.random.default_rng(11)
    move = rng.normal(loc=0.5, scale=0.2, size=len(idx))     # rates drift UP
    led = pd.DataFrame({"ts": idx, "bucket": "A", "position": 1,
                        "entry_bp": 0.0, "exit_bp": move, "cost_bp": 0.0})
    led["gross_bp"] = led["position"] * move
    led["net_bp"] = led["gross_bp"]
    b = study.constant_position_benchmark(led, n_boot=200)
    got = dict(zip(b["variant"], b["mean_bp"]))
    assert got["always long rates (+1)"] == pytest.approx(move.mean())
    assert got["always short rates (-1)"] == pytest.approx(-move.mean())
    assert got["as traded"] == pytest.approx(move.mean())
    assert set(b["variant"]) == {"as traded", "always long rates (+1)",
                                 "always short rates (-1)"}


def test_the_benchmark_subtracts_the_same_cost_from_every_variant():
    idx = pd.date_range("2026-03-02 08:00", periods=20, freq="15min", tz=NY)
    led = pd.DataFrame({"ts": idx, "bucket": "A", "position": 1,
                        "entry_bp": 0.0, "exit_bp": 1.0, "cost_bp": 0.5})
    led["gross_bp"] = 1.0
    led["net_bp"] = 0.5
    b = study.constant_position_benchmark(led, n_boot=100)
    got = dict(zip(b["variant"], b["mean_bp"]))
    assert got["always long rates (+1)"] == pytest.approx(0.5)
    assert got["always short rates (-1)"] == pytest.approx(-1.5)


def test_the_benchmark_is_empty_without_prices():
    led = pd.DataFrame({"ts": [], "bucket": [], "position": []})
    assert study.constant_position_benchmark(led).empty


def test_the_primary_verdict_states_the_position_balance(monkeypatch):
    _no_write(monkeypatch)
    out = gates.run_primary(_context(effect=0.7, seed=65), in_sample=True)
    assert "long-rates" in out["verdict"]["headline"]
    assert not out["directional_benchmark"].empty


# =========== the placebo reference must BE the primary, not merely resemble it
def test_placebo_reference_is_the_primary_verbatim(monkeypatch):
    """run_placebos rebuilds the signal with buckets=rates.columns while load_context
    built it from the contract calendar. Those sets differ whenever a contract returned
    no bars, so the reference matched the primary only by coincidence -- and every one of
    the five placebos is read as a distance FROM that reference."""
    _no_write(monkeypatch)
    ctx = _context(effect=0.7, seed=70)
    primary = gates.run_primary(ctx, in_sample=True)
    plac = gates.run_placebos(ctx, primary=primary)["placebos"]
    ref = plac[plac["placebo"] == "none (reference)"].iloc[0]
    prim = primary["result"].iloc[0]
    for col in ("mean", "t", "n", "n_blocks"):
        assert ref[col] == pytest.approx(prim[col]), col


def test_placebos_still_work_without_a_primary(monkeypatch):
    """The reference falls back to a recomputation, which is what standalone use needs."""
    _no_write(monkeypatch)
    plac = gates.run_placebos(_context(effect=0.7, seed=71))["placebos"]
    assert len(plac) == 6
    assert plac[plac["placebo"] == "none (reference)"]["n"].iloc[0] > 0


def test_every_placebo_row_reports_its_position_balance(monkeypatch):
    """The sign shuffle removes the PAID skew as well as the direction signal, so the
    shuffled rule is near-balanced while the real one is ~80% one-sided. Without
    share_long on every row a reader attributes the whole gap to lost information."""
    _no_write(monkeypatch)
    ctx = _context(effect=0.7, seed=72)
    plac = gates.run_placebos(ctx, primary=gates.run_primary(ctx, in_sample=True))["placebos"]
    assert "share_long" in plac.columns
    assert plac["share_long"].notna().sum() >= 5
    assert ((plac["share_long"].dropna() >= 0) & (plac["share_long"].dropna() <= 1)).all()


# ============ the SR3-vs-ZQ reading must be assembled in code, not left to a reader
def _g2_stub(lls_t, rho_mean, leads):
    return {"lead_lag_summary": pd.DataFrame([{"mean": 1.0, "t": lls_t}]),
            "peak_rho_summary": pd.DataFrame([{"mean": rho_mean, "t": -4.0}]),
            "verdict": {"timing_lead": leads, "direction_ok": leads}}


@pytest.mark.parametrize("sr3_leads, zq_leads, expect", [
    (True, False, "LIQUIDITY-ROUTED"),
    (False, True, "MEETING-TARGETED"),
    (True, True, "undiscriminating"),
    (False, False, "no mechanism evidence"),
])
def test_cross_check_states_the_reading(monkeypatch, sr3_leads, zq_leads, expect):
    """The brief makes this the comparison the mechanism turns on. Leaving a reader to
    hold two tables side by side and infer the label is exactly where a preferred
    reading gets chosen, so the interpretation is attached in code."""
    _no_write(monkeypatch)
    ctx = _context(effect=0.4, seed=80)
    out = gates.run_cross_check_comparison(ctx, {
        "FUTURES": _g2_stub(5.0, -0.3, sr3_leads),
        "FED_FUNDS": _g2_stub(5.0, -0.3, zq_leads)})
    assert expect in out["verdict"]["headline"]
    assert len(out["comparison"]) == 2
    assert set(out["comparison"]["root"]) == {"SR3", "ZQ"}


def test_cross_check_on_no_g2_result(monkeypatch):
    _no_write(monkeypatch)
    out = gates.run_cross_check_comparison(_context(effect=0.4, seed=81), {})
    assert out["comparison"].empty
    assert out["verdict"]["pass"] is None


def test_g2_timing_threshold_comes_from_the_locked_config():
    """A literal here would sit OUTSIDE the configuration fingerprint the lockout ledger
    records, so it could be moved after seeing the holdout without the burn rule
    noticing."""
    import inspect
    src = inspect.getsource(gates.run_g2)
    assert "ctx.config.primary.t_pass" in src
    assert ">= 3.0" not in src

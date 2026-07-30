"""End-to-end gate pipeline on a synthetic multi-session dataset (no DB, no vendor).

Builds a ``GateContext`` by hand with a PLANTED effect — the ladder z-score genuinely
predicts the next hour's rate move — and asserts the pipeline finds it, that the
placebos kill it, and that the same pipeline returns nothing on a matched null.

This exists because the gates' failure modes are integration-shaped: a wrong
estimand, a mis-joined panel, a mask applied to the wrong axis. Unit tests on each
piece do not catch those, and discovering them on the real dataset costs a backfill.
"""
import dataclasses
import datetime

import numpy as np
import pandas as pd
import pytest

from BT.dealer_ladder import config as cfg, controls, gates, signals, study

NY = "America/New_York"
BUCKETS = ["SFRU26", "SFRZ26", "SFRH27", "SFRM27", "SFRU27", "SFRZ27"]


def _sessions(n=30, start="2026-03-02"):
    days = pd.bdate_range(start, periods=n)
    out = []
    for d in days:
        out.append(pd.date_range(d + pd.Timedelta(hours=8), periods=96,
                                 freq="5min", tz=NY))
    return days, out[0].append(out[1:])


def _prints(grid, rng, n_per_day=40):
    """Synthetic classified prints, one visibility per print, spread over sessions."""
    rows = []
    days = pd.Series(grid.tz_convert(NY).date, index=grid)
    for day in pd.unique(days):
        day_grid = grid[(days == day).to_numpy()]
        for i in range(n_per_day):
            ts = day_grid[rng.integers(0, len(day_grid))]
            rows.append(dict(
                unit_key=f"{day}-{i}", bucket_space="FUTURES",
                bucket_key=BUCKETS[rng.integers(0, len(BUCKETS))],
                delta_dv01=float(rng.normal(scale=25_000)),
                execution_timestamp=ts - pd.Timedelta(minutes=1),
                visibility_timestamp=ts,
                p_flip=float(rng.choice([0.0, 0.05, 0.15])),
                direction_confidence="HIGH",
                curve_suspect_trade=False, is_block=bool(rng.random() < 0.15),
                dv01=25_000.0, as_of_date=day, code_vintage="test",
                trade_type="OUTRIGHT", rate_index_clean="SOFR",
                classification_method="RATE_VS_MID",
                dealer_direction="RECEIVED", is_off_market=False,
                structure_dv01=25_000.0, spread_to_mid_bps=0.3,
                dealer_charge_bps=np.nan, tenor_bucket="2Y", dv01_bucket="MID",
                notional=1e8, trade_id=f"{day}-{i}", package_id=None,
                venue_bucket="D2C_WHITELISTED", curve_bucket="CURVE_CLEAN",
                market_bucket="ON_MARKET", has_p_flip=True,
                platform_identifier="TWSF", cleared="I", is_capped=False,
            ))
    return pd.DataFrame(rows)


def _context(effect=0.0, seed=0, n_sessions=30):
    """A GateContext whose rates respond to the ladder z with strength ``effect``."""
    rng = np.random.default_rng(seed)
    days, grid = _sessions(n_sessions)
    window = (days[0].date(), days[-1].date())
    conf = cfg.LadderStudyConfig(
        window=cfg.WindowConfig(start=window[0], end=window[1],
                                lockout_start=days[-5].date()),
        signal=dataclasses.replace(cfg.SignalConfig(), z_window_days=5),
        grid=cfg.GridConfig(horizons_min=(15, 60), spaces=("FUTURES",),
                            half_lives_min=(90.0, 240.0),
                            weightings=("expected",),
                            target_spaces=("FUTURES",)),
        stats=cfg.StatsConfig(n_boot=120, seed=1),
    )
    prints = _prints(grid, rng)
    sig_cfg = dataclasses.replace(conf.signal, space="FUTURES")
    built = signals.build_signal(prints, grid, sig_cfg, buckets=BUCKETS)

    # rates: a random walk plus a response to the LAGGED z (so it is genuinely
    # forward-predictable by z, not contemporaneous with it)
    z = built["z"].fillna(0.0)
    noise = rng.normal(scale=0.35, size=(len(grid), len(BUCKETS)))
    resp = effect * z.shift(1).fillna(0.0).to_numpy()
    rates = pd.DataFrame(400.0 + np.cumsum(noise + resp, axis=0),
                         index=grid, columns=BUCKETS)
    vols = pd.DataFrame(rng.integers(1, 400, size=(len(grid), len(BUCKETS))).astype(float),
                        index=grid, columns=BUCKETS)
    stale = pd.DataFrame(0.0, index=grid, columns=BUCKETS)
    implied = rates + 0.2
    contracts = [(b, datetime.datetime(2026, 9, 16), datetime.datetime(2026, 12, 16), False)
                 for b in BUCKETS]
    front = pd.DataFrame(1.0, index=grid, columns=BUCKETS)

    return gates.GateContext(
        config=conf, window=window, prints_all=prints, prints=prints, grid=grid,
        contracts=contracts,
        rates_bp={"FUTURES": rates}, volumes={"FUTURES": vols},
        stale_min={"FUTURES": stale}, implied_bp={"FUTURES": implied},
        signal={"FUTURES": built}, front_rank={"FUTURES": front},
        indep_implied_bp={"FUTURES": implied - 0.05},   # a second, slightly different mid
        block_share={"FUTURES": pd.DataFrame(
            rng.uniform(0, 0.5, size=(len(grid), len(BUCKETS))),
            index=grid, columns=BUCKETS)},
        results_dir=None)


def _no_write(monkeypatch):
    monkeypatch.setattr(gates, "_write", lambda ctx, name, frame: None)


# --------------------------------------------------------------------------
def test_g1_passes_on_a_well_formed_context(monkeypatch):
    _no_write(monkeypatch)
    res = gates.run_g1(_context(), sample_grid=40)
    assert res["verdict"]["pass"] is True, res["audits"]
    poison = res["audits"].set_index("audit").loc["future_poison"]
    assert poison["max_future_prints"] > 0, "audit passed vacuously"


def test_g2_runs_and_reports_a_day_blocked_verdict(monkeypatch):
    _no_write(monkeypatch)
    res = gates.run_g2(_context(effect=0.4, seed=3))
    assert "lead_lag" in res and not res["lead_lag"].empty
    summ = res["lead_lag_summary"].iloc[0]
    assert summ["n_blocks"] > 5
    assert set(res["lead_lag"].columns) >= {"lls", "peak_lag_min", "peak_rho"}


def test_g3_aligns_and_runs_the_horse_race(monkeypatch):
    _no_write(monkeypatch)
    res = gates.run_g3(_context(effect=0.5, seed=4))
    assert not res["long"].empty, "G3 produced no aligned observations"
    race = res["horse_race"]
    assert {"signal only", "signal + controls"} == set(race["spec"])
    used = res["verdict"]["controls_used"]
    assert "basis_bp" in used and "days_to_expiry" in used
    assert not res["leave_one_out"].empty


def test_primary_finds_a_planted_effect(monkeypatch):
    _no_write(monkeypatch)
    res = gates.run_primary(_context(effect=0.9, seed=11), in_sample=True)
    led = res["ledger"]
    assert len(led) > 20, f"only {len(led)} trades"
    assert (led["cost_bp"] > 0).all(), "costs must be charged"
    row = res["result"].iloc[0]
    assert row["mean"] > 0 and row["t"] > 2, dict(row)


def test_on_a_matched_null_the_cost_floor_dominates(monkeypatch):
    """A null does not come out at zero -- it comes out at MINUS the round trip.

    Which is the point: the gate cannot pass by accident, because every trade pays
    a full tick before it can earn anything. Gross should sit near zero while net
    sits near -0.5 bp, the deferred SR3 round trip.
    """
    _no_write(monkeypatch)
    ctx = _context(effect=0.0, seed=12)
    res = gates.run_primary(ctx, in_sample=True)
    row = res["result"].iloc[0]
    led = res["ledger"]
    assert res["verdict"]["pass"] is False
    assert row["mean"] < 0 and row["t"] < 0, dict(row)
    gross = float(led["gross_bp"].mean())
    net = float(led["net_bp"].mean())
    assert abs(gross) < 0.25, f"gross should be ~0 on a null, got {gross}"
    assert net == pytest.approx(gross - 0.5, abs=1e-9), (gross, net)
    assert float(led["hit_rate"].mean()) if "hit_rate" in led else True


def test_placebos_kill_a_planted_effect(monkeypatch):
    _no_write(monkeypatch)
    res = gates.run_placebos(_context(effect=0.9, seed=13))
    tab = res["placebos"].set_index("placebo")
    ref = float(tab.loc["none (reference)", "mean"])
    assert ref > 0, tab
    shuffled = float(tab.loc["sign shuffle within session", "mean"])
    assert abs(shuffled) < abs(ref), (ref, shuffled)
    # every pre-specified placebo must be present, not a subset
    assert len(tab) == 6
    assert "pre-arrival window" in tab.index
    assert "rotated buckets" in tab.index


def test_grid_publishes_the_whole_family_with_best_and_median(monkeypatch):
    _no_write(monkeypatch)
    res = gates.run_grid(_context(effect=0.7, seed=14), study.TrialLedger())
    league = res["league"]
    # 1 signal space x 2 half-lives x 1 weighting x 2 horizons x 1 target
    assert len(league) == 4, league[["variant"]]
    bm = res["best_and_median"]
    assert list(bm["role"]) == ["best-config", "median-config"]
    rw = res["romano_wolf"]
    assert rw is not None and len(rw) == 4
    assert rw["p_fwer"].is_monotonic_increasing


def test_grid_records_every_variant_in_the_trial_ledger(monkeypatch):
    _no_write(monkeypatch)
    sink = study.TrialLedger()
    gates.run_grid(_context(effect=0.3, seed=15), sink)
    assert len(sink) == 4
    frame = sink.frame()
    assert "cfg_half_life" in frame.columns and "res_t" in frame.columns


def test_g5_reports_costs_and_a_labelled_capacity_sensitivity(monkeypatch):
    _no_write(monkeypatch)
    ctx = _context(effect=0.9, seed=16)
    primary = gates.run_primary(ctx, in_sample=True)
    res = gates.run_g5(ctx, primary)
    net = res["net_table"]
    assert list(net["measure"])[:2] == ["gross", "net of costs"]
    gross = float(net[net["measure"] == "gross"]["mean_bp"].iloc[0])
    netbp = float(net[net["measure"] == "net of costs"]["mean_bp"].iloc[0])
    assert netbp < gross, "costs must reduce the edge"
    assert (res["capacity"]["basis"].str.contains("NOT measured depth")).all()


def test_lockout_segment_is_disjoint_from_in_sample(monkeypatch):
    """The one-shot holdout must not share a single trade with development."""
    _no_write(monkeypatch)
    ctx = _context(effect=0.9, seed=17)
    a = gates.run_primary(ctx, in_sample=True)["ledger"]
    b = gates.run_primary(ctx, in_sample=False)["ledger"]
    assert len(a) and len(b)
    assert not set(a["ts"]) & set(b["ts"])
    assert max(a["ts"]) < min(b["ts"])


def test_front_rank_mask_suppresses_out_of_basket_decisions(monkeypatch):
    """A contract outside the session's front N must produce no trade at all."""
    _no_write(monkeypatch)
    ctx = _context(effect=0.9, seed=18)
    front = ctx.front_rank["FUTURES"].copy()
    front["SFRZ27"] = np.nan                       # drop one contract from the basket
    masked = {k: v.where(front.notna()) for k, v in ctx.signal["FUTURES"].items()}
    ctx = dataclasses.replace(ctx, front_rank={"FUTURES": front},
                              signal={"FUTURES": masked})
    led = gates.run_primary(ctx, in_sample=True)["ledger"]
    assert "SFRZ27" not in set(led["bucket"])
    assert len(set(led["bucket"])) == len(BUCKETS) - 1


# ---------------------------------------------- independent basis / label-free / strata
def test_g3_runs_a_second_race_against_the_independent_basis(monkeypatch):
    """The circularity gate's real teeth: does the ladder also survive a basis our
    own curve did not produce?"""
    _no_write(monkeypatch)
    res = gates.run_g3(_context(effect=0.6, seed=21))
    assert "horse_race_independent" in res, res.get("verdict")
    indep = res["verdict"]["independent_controls"]
    assert "indep_basis_bp" in indep
    race = res["horse_race_independent"]
    assert "indep_basis_bp" in set(race["term"])
    # the headline must carry all three t-statistics, not just two
    assert "independent basis" in res["verdict"]["headline"]


def test_label_free_cell_uses_unsigned_intensity(monkeypatch):
    """If this works and the signed ladder does not, direction carries nothing."""
    _no_write(monkeypatch)
    res = gates.run_label_free(_context(effect=0.8, seed=22))
    assert res["result"].iloc[0]["signal"] == "unsigned print intensity"
    led = res["ledger"]
    assert len(led) > 0
    assert "unsigned intensity" in res["verdict"]["headline"]


def test_conditioning_splits_report_sign_consistency(monkeypatch):
    _no_write(monkeypatch)
    ctx = _context(effect=0.9, seed=23)
    primary = gates.run_primary(ctx, in_sample=True)
    res = gates.run_conditioning(ctx, primary, n_bins=3)
    frame = res["conditioning"]
    assert not frame.empty
    assert set(frame["bucket"]) <= {"q1", "q2", "q3"}
    assert "block_share" in set(frame["conditioner"])
    # every reported stratum must carry its own day-blocked n_blocks
    assert (frame["n_blocks"] >= 1).all()
    assert "sign-consistent" in res["verdict"]["headline"]


def test_conditioning_on_an_empty_ledger_is_a_non_event(monkeypatch):
    _no_write(monkeypatch)
    ctx = _context(effect=0.0, seed=24)
    res = gates.run_conditioning(ctx, {"ledger": pd.DataFrame()})
    assert res["verdict"]["pass"] is None
    assert "no trades" in res["verdict"]["headline"]

"""Task 22: the daily signal runner, and the honesty it is required to carry.

The runner is not shipping a validated edge. Every measured result in this study
is DEAD -- all four markets at DSR <= 1.5e-40 on 3888 trials, three of the four
with a NEGATIVE break-even cost multiplier so no cost assumption rescues them --
and a reader of one day's output must not be able to mistake the row for a
tradeable signal. So most of what is pinned here is about what the row SAYS
beside its sign, and the two places a number could quietly describe something
adjacent to what it is read as:

* the panel diagnostics printed beside a lag-1 sign belong to the INFORMATION
  date (``t-1``), not to the signal date. ``scripts/sv_cross_market._fmt_signal_state``
  prints ``signals.iloc[-1]`` next to ``panel.iloc[-1]``, which are one day
  apart -- the reason string and the BE/RV beside it are from different days;
* ``be_over_realized``'s denominator is the LONGER LEG's forward par rate vol,
  not the package spread's. ``breakeven_h25`` is ``sqrt(2|roll|/gamma)`` with
  gamma measured against a parallel LEVEL bump, so it is a breakeven RATE move
  per day and the spread's own vol is a different quantity roughly 4x smaller.
"""
import dataclasses
import datetime as dt
import math

import numpy as np
import pandas as pd
import pytest

from RVUtils.SFRRVLab.stats import verdict as repo_verdict
from RVUtils.StrikelessVol.conventions import TRADING_DAYS
from RVUtils.StrikelessVol.report import FORBIDDEN_RANK_KEYS
from RVUtils.StrikelessVol.strategy import SignalConfig
from RVUtils.StrikelessVol.universe import ALL_PAIRS

from BT.signals.strikeless_vol import (
    MEASURED_VERDICT,
    REQUIRED_OUTPUT_COLUMNS,
    STUDY_N_TRIALS,
    SignalWindows,
    build_pair_inputs,
    certified_signals,
    greeks_with_cache,
    market_verdict,
    pair_state,
    state_row,
    today_state,
)

USD_PAIR = next(p for p in ALL_PAIRS
                if p.market == "USD" and (p.short.label, p.long.label) == ("10Y10Y", "20Y10Y"))

#: Short windows so the fast gate stays fast. Every one of them still clears
#: ``backtest.MIN_INPUT_AUDIT_OBS`` (100 compared dates) for both certified
#: inputs on the 400-row frame below -- ``drift_t`` is defined from row
#: 120+21=141 (259 values) and ``iv_z`` from row 60 (340 values).
FAST = SignalWindows(realized=10, drift=21, fit_min_periods=120, z_window=120,
                     z_min_periods=60, iv_z_window=120, iv_z_min_periods=60)


# ----------------------------------------------------------------- fixtures


def synthetic_inputs(n=400, seed=3, *, be_scale=1.0, level_vol=5.0, spread_vol=1.2):
    """A greeks-shaped frame and an implied-vol series, on one calendar.

    ``level_vol`` and ``spread_vol`` are set INDEPENDENTLY (the long leg's rate
    is not the spread plus the short leg here) precisely so a test can tell
    which denominator ``be_over_realized`` used: with a level vol of 5.0 bp/day
    and a spread vol of 1.2 bp/day the two candidate ratios differ by ~4x, which
    is the size of the real discrepancy.
    """
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2022-01-03", periods=n)
    iv = pd.Series(4.5 + 0.9 * np.sin(2 * np.pi * np.arange(n) / 180.0)
                   + rng.normal(0, 0.05, n), index=idx)
    vol_ann = iv * math.sqrt(TRADING_DAYS)
    spread = pd.Series(
        -60.0 - 1.4 * (vol_ann.to_numpy() - vol_ann.mean())
        + np.cumsum(rng.normal(0, spread_vol, n)), index=idx)
    long_rate = pd.Series(
        0.042 + np.cumsum(rng.normal(0, level_vol * 1e-4, n)), index=idx)
    short_rate = long_rate - spread * 1e-4
    roll = pd.Series(-700.0 + rng.normal(0, 20.0, n), index=idx)
    gamma = pd.Series(203.0 + rng.normal(0, 2.0, n), index=idx)
    be = pd.Series(np.sqrt(2.0 * roll.abs() / gamma) * be_scale, index=idx)
    greeks = pd.DataFrame({
        "pair": USD_PAIR.name,
        "short_rate": short_rate,
        "long_rate": long_rate,
        "spread_bp": spread,
        "package_dv01": 0.0,
        "daily_roll_usd": roll,
        "gamma_h25": gamma,
        "breakeven_h25": be,
    }, index=idx)
    return greeks, iv


def built(**kw):
    greeks, iv = synthetic_inputs(**kw)
    return build_pair_inputs(USD_PAIR, greeks, iv, windows=FAST), greeks, iv


# ------------------------------------------------- the declared output shape


def test_required_columns_are_declared():
    assert "sign" in REQUIRED_OUTPUT_COLUMNS
    assert "be_over_realized" in REQUIRED_OUTPUT_COLUMNS
    assert "reason" in REQUIRED_OUTPUT_COLUMNS
    assert "sample_start" in REQUIRED_OUTPUT_COLUMNS


def test_the_briefs_fourteen_signal_columns_are_all_declared():
    for col in ("pair", "spread_bp", "breakeven_h25", "realized_vol_bp_day",
                "implied_bp_day", "be_over_realized", "be_over_implied",
                "drift_t", "residual_z", "sign", "size", "dv01_usd", "reason",
                "sample_start"):
        assert col in REQUIRED_OUTPUT_COLUMNS, col


def test_every_row_carries_the_verdict_the_dsr_and_the_six_requirements():
    """A reader of ONE day's output must see what the study measured."""
    for col in ("verdict", "dsr_prob", "n_trials", "requirements_met",
                "certified_signal_inputs", "uncertified_signal_inputs",
                "req_expanding_betas", "req_entry_vintage_hedge",
                "req_rolling_sigma_z", "req_spread_leg_pnl",
                "req_distinct_episodes", "req_random_walk_placebo"):
        assert col in REQUIRED_OUTPUT_COLUMNS, col


def test_no_forbidden_ranking_key_is_emitted():
    """Sharpe, t_stat, skew and resid_skew are refused as ranking keys; a
    runner that emits them invites exactly the ranking the study forbids."""
    assert set(REQUIRED_OUTPUT_COLUMNS) & set(FORBIDDEN_RANK_KEYS) == set()


# ---------------------------------------------------- the measured verdicts


def test_the_measured_verdict_reproduces_the_task_21_league_table():
    """The numbers, not the label: gross/net/DSR as the run printed them."""
    assert STUDY_N_TRIALS == 3888
    expected = {
        # market: (n_trades, gross_bp, net_1x_bp, net_2x_bp, dsr_prob)
        "USD": (116, -4.349373, -191.370916, -378.392458, 9.730617e-127),
        "EUR": (58, 21.239336, -72.739479, -166.718293, 1.508078e-40),
        "JPY": (61, -36.895482, -165.815749, -294.736017, 1.471768e-48),
        "GBP": (93, -25.644988, -215.519128, -405.393268, 1.794651e-95),
    }
    for market, (n_trades, gross, net1, net2, dsr) in expected.items():
        mv = MEASURED_VERDICT[market]
        assert mv.n_trades == n_trades
        assert mv.gross_bp == pytest.approx(gross, rel=1e-9)
        assert mv.net_1x_bp == pytest.approx(net1, rel=1e-9)
        assert mv.net_2x_bp == pytest.approx(net2, rel=1e-9)
        assert mv.dsr_prob == pytest.approx(dsr, rel=1e-9)
        assert mv.n_trials == 3888
    assert max(mv.dsr_prob for mv in MEASURED_VERDICT.values()) <= 1.508078e-40


def test_the_verdict_is_derived_through_the_repo_taxonomy_not_asserted():
    """``verdict`` is recomputed from the stored numbers by the repo's own
    ``stats.verdict``, so a stored string cannot drift away from the numbers
    beside it."""
    median_net = float(np.median([mv.net_1x_bp for mv in MEASURED_VERDICT.values()]))
    for market, mv in MEASURED_VERDICT.items():
        cost_1x = mv.gross_bp - mv.net_1x_bp
        maker = mv.gross_bp - 0.5 * cost_1x
        assert mv.verdict == repo_verdict(
            net_bp_at_taker=mv.net_2x_bp, net_bp_at_maker=maker,
            dsr_prob=mv.dsr_prob, median_net_bp=median_net, n_trades=mv.n_trades)
        assert mv.verdict == "DEAD", market


def test_the_break_even_cost_multiplier_reproduces_the_runs_own_print():
    """Derived from gross and net_1x here; the run printed it independently."""
    printed = {"USD": -0.02, "EUR": 0.23, "JPY": -0.29, "GBP": -0.14}
    for market, x in printed.items():
        assert MEASURED_VERDICT[market].breakeven_cost_mult == pytest.approx(x, abs=5e-3)
    positive = [m for m, mv in MEASURED_VERDICT.items()
                if mv.breakeven_cost_mult > 0.0]
    assert positive == ["EUR"]


def test_market_verdict_refuses_a_market_the_study_never_scored():
    with pytest.raises(KeyError):
        market_verdict("CHF")


# ------------------------------------------------------- what the row reads


def test_the_row_reports_the_panel_at_the_information_date_not_the_signal_date():
    """The crux. A lag-1 sign is decided on ``t-1``; the diagnostics printed
    beside it must be ``t-1``'s, or the reason and the number disagree."""
    inputs, _greeks, _iv = built()
    signals = certified_signals(inputs, SignalConfig())
    row = state_row(inputs, signals, SignalConfig())

    panel = inputs.panel
    assert row["information_date"] == panel.index[-2]
    assert row["signal_date"] == panel.index[-1]
    for col in ("spread_bp", "breakeven_h25", "realized_vol_bp_day",
                "implied_bp_day", "be_over_realized", "drift_t"):
        want = float(panel[col].iloc[-2])
        assert row[col] == pytest.approx(want, rel=1e-12), col
    # and it is a DIFFERENT number from the signal date's, so the assertion
    # above can actually fail
    assert float(panel["spread_bp"].iloc[-1]) != pytest.approx(
        float(panel["spread_bp"].iloc[-2]), rel=1e-9)


def test_be_over_realized_uses_the_long_leg_rate_vol_not_the_spread_vol():
    """``breakeven_h25`` is a breakeven LEVEL move per day (gamma is measured
    against a parallel bump), so the comparator is the longer leg's own rate
    vol. The spread-vol variant is emitted beside it, named, because that is
    what the Task 21 cross-market run divided by."""
    inputs, greeks, _iv = built(level_vol=5.0, spread_vol=1.2)
    panel = inputs.panel

    rate_vol = (greeks["long_rate"].diff() * 10_000.0).rolling(
        FAST.realized, min_periods=FAST.realized).std(ddof=1)
    spread_vol = greeks["spread_bp"].diff().rolling(
        FAST.realized, min_periods=FAST.realized).std(ddof=1)

    assert panel["realized_vol_bp_day"].iloc[-1] == pytest.approx(
        float(rate_vol.iloc[-1]), rel=1e-12)
    assert panel["spread_vol_bp_day"].iloc[-1] == pytest.approx(
        float(spread_vol.iloc[-1]), rel=1e-12)
    assert panel["be_over_realized"].iloc[-1] == pytest.approx(
        float(greeks["breakeven_h25"].iloc[-1] / rate_vol.iloc[-1]), rel=1e-12)
    assert panel["be_over_spread_vol"].iloc[-1] == pytest.approx(
        float(greeks["breakeven_h25"].iloc[-1] / spread_vol.iloc[-1]), rel=1e-12)
    # the two denominators are not interchangeable: on this frame they differ
    # by roughly the 4x that separates a level vol from a slope vol
    ratio = float(panel["be_over_spread_vol"].iloc[-1] / panel["be_over_realized"].iloc[-1])
    assert ratio > 2.5


def test_the_driver_is_the_annualised_normal_not_the_bp_day_print():
    inputs, _greeks, iv = built()
    assert set(inputs.drivers) == {"vol"}
    assert float(inputs.drivers["vol"].iloc[-1]) == pytest.approx(
        float(iv.iloc[-1]) * math.sqrt(TRADING_DAYS), rel=1e-12)


def test_umep_is_off_by_default_because_that_is_the_configuration_measured():
    """Task 21 ran implied vol ALONE in every market and that is the run the
    stored verdict comes from. USD+umep was worth ~3.2bp over 5.5 years and
    changed no sign and no verdict."""
    greeks, iv = synthetic_inputs()
    plain = build_pair_inputs(USD_PAIR, greeks, iv, windows=FAST)
    assert set(plain.drivers) == {"vol"}
    umep = pd.Series(4.3, index=greeks.index)
    withu = build_pair_inputs(USD_PAIR, greeks, iv, umep=umep, windows=FAST)
    assert set(withu.drivers) == {"vol", "umep"}


def test_umep_is_refused_outside_usd():
    greeks, iv = synthetic_inputs()
    jpy = next(p for p in ALL_PAIRS if p.market == "JPY")
    with pytest.raises(ValueError, match="USD"):
        build_pair_inputs(jpy, greeks, iv, umep=pd.Series(4.3, index=greeks.index),
                          windows=FAST)


# ---------------------------------------------------- the certified signal


def test_the_fixtures_reach_both_sides_of_the_rule_and_flat():
    """Otherwise every assertion about the sign below is vacuous."""
    signs = set()
    for be_scale in (1.0, 3.0):
        inputs, _g, _iv = built(be_scale=be_scale)
        s = certified_signals(inputs, SignalConfig())
        signs.update(int(v) for v in pd.Series(s["sign"]).unique())
    assert {-1, 0, 1} <= signs


def test_the_sign_is_the_last_row_of_the_certified_lag_1_signal():
    inputs, _g, _iv = built()
    cfg = SignalConfig()
    signals = certified_signals(inputs, cfg)
    row = state_row(inputs, signals, cfg)
    assert row["sign"] == int(signals["sign"].iloc[-1])
    assert row["size"] == pytest.approx(float(signals["size"].iloc[-1]), rel=1e-12)
    assert row["reason"] == str(signals["reason"].iloc[-1])
    assert row["dv01_usd"] == pytest.approx(
        row["sign"] * row["size"] * cfg.base_dv01_usd, rel=1e-12)


def test_the_certificate_names_residual_z_and_drift_t_and_leaves_the_sign_out():
    """``be_over_realized`` sets the SIGN and cannot be certified by anything
    this engine exposes -- so it must be NAMED, on the row, every day."""
    inputs, _g, _iv = built()
    signals = certified_signals(inputs, SignalConfig())
    row = state_row(inputs, signals, SignalConfig())
    certified = set(row["certified_signal_inputs"])
    uncertified = set(row["uncertified_signal_inputs"])
    assert "residual_z" in certified
    assert "drift_t" in certified
    assert "changes_resid" in certified
    assert "be_over_realized" in uncertified
    assert "be_over_realized" not in certified
    assert row["sign_input_certified"] is False


def test_a_live_runner_can_evidence_five_of_the_six_requirements_and_not_the_sixth():
    """Requirement 6 is a random-walk placebo over a completed backtest; a
    runner emitting one day has no such object, and Task 19 measured it NOT MET
    for this strategy anyway (20/20 nulls traded, 19 beat the headline)."""
    inputs, _g, _iv = built()
    signals = certified_signals(inputs, SignalConfig())
    row = state_row(inputs, signals, SignalConfig())
    flags = {k: v for k, v in row.items() if k.startswith("req_")}
    assert len(flags) == 6
    assert sum(bool(v) for v in flags.values()) == 5
    assert row["req_random_walk_placebo"] is False
    assert row["requirements_met"] is False
    assert "random_walk_placebo" in row["unmet_requirements"]


def test_the_note_states_the_same_trial_count_the_column_carries():
    inputs, _g, _iv = built()
    signals = certified_signals(inputs, SignalConfig())
    row = state_row(inputs, signals, SignalConfig())
    stated = [int(tok) for tok in row["note"].replace(",", " ").split()
              if tok.isdigit()]
    assert row["n_trials"] in stated
    assert row["n_trials"] == STUDY_N_TRIALS


def test_the_reported_z_is_flagged_when_it_is_not_the_number_that_priced_a_hold():
    """``entry_vintage_signals`` prices a continuing hold on the z FROZEN at
    entry, not the live one. The row reports the live z, so it has to say when
    that is not the decision input."""
    inputs, _g, _iv = built()
    cfg = SignalConfig()
    signals = certified_signals(inputs, cfg)
    row = state_row(inputs, signals, cfg)
    assert row["residual_z_is_decision_input"] == (row["held_days"] == 0)
    # the live z reported IS the trailing z of the certified residual at t-1
    assert row["residual_z"] == pytest.approx(
        float(inputs.residual_z.iloc[-2]), rel=1e-12, nan_ok=True)


def _z_quoted_in(reason):
    """The z the engine's own reason string names, or None."""
    if "; z=" not in str(reason):
        return None
    return float(str(reason).rsplit("; z=", 1)[1].split()[0])


def test_decision_z_is_the_number_the_engines_reason_quotes():
    """The runner reports the live z AND the z that actually decided the row.

    On a continuing hold those are different numbers -- the engine prices the
    hold on the z frozen at entry -- so reporting only the live one puts a
    figure next to a ``reason`` string quoting a different figure. This checks
    the reproduction against the engine's own output, on a frame where the two
    genuinely differ (a case whose answer is known independently: the engine
    printed it).
    """
    seen_hold = seen_entry = False
    for be_scale in (1.0, 0.25, 3.0):
        inputs, _g, _iv = built(be_scale=be_scale)
        cfg = SignalConfig()
        signals = certified_signals(inputs, cfg)
        row = state_row(inputs, signals, cfg)
        quoted = _z_quoted_in(row["reason"])
        if quoted is None:
            continue
        assert row["decision_z"] == pytest.approx(quoted, abs=5e-3), be_scale
        if row["held_days"] > 0:
            seen_hold = True
            # the reproduction is not vacuous: the live z is a DIFFERENT number
            assert abs(row["residual_z"] - row["decision_z"]) > 1e-3
        else:
            seen_entry = True
            assert row["decision_z"] == pytest.approx(row["residual_z"], rel=1e-12)
    assert seen_hold, "no held row in the fixtures -- the frozen branch is untested"
    assert seen_entry, "no fresh-entry row in the fixtures"


def test_held_days_counts_the_run_of_identical_signs_ending_yesterday():
    inputs, _g, _iv = built()
    cfg = SignalConfig()
    signals = certified_signals(inputs, cfg)
    row = state_row(inputs, signals, cfg)
    sign = pd.Series(signals["sign"]).astype(int)
    if sign.iloc[-1] == 0:
        assert row["held_days"] == 0
    else:
        run = 0
        for v in reversed(sign.iloc[:-1].tolist()):
            if v == sign.iloc[-1]:
                run += 1
            else:
                break
        assert row["held_days"] == run


def test_the_sample_start_is_the_first_date_of_the_data_behind_the_row():
    inputs, _g, _iv = built()
    signals = certified_signals(inputs, SignalConfig())
    row = state_row(inputs, signals, SignalConfig())
    assert row["sample_start"] == inputs.panel.index.min()
    assert row["sample_end"] == inputs.panel.index.max()
    assert row["n_obs"] == len(inputs.panel)


def test_a_one_row_panel_cannot_state_a_lag_1_signal():
    inputs, _g, _iv = built()
    signals = certified_signals(inputs, SignalConfig()).iloc[:1]
    one = dataclasses.replace(inputs, panel=inputs.panel.iloc[:1])
    with pytest.raises(ValueError, match="lag-1"):
        state_row(one, signals, SignalConfig())


def test_pair_state_composes_the_three_steps_into_one_row():
    greeks, iv = synthetic_inputs()
    cfg = SignalConfig()
    row = pair_state(USD_PAIR, greeks, iv, cfg=cfg, windows=FAST)
    inputs = build_pair_inputs(USD_PAIR, greeks, iv, windows=FAST)
    direct = state_row(inputs, certified_signals(inputs, cfg), cfg)
    assert row["sign"] == direct["sign"]
    assert row["be_over_realized"] == pytest.approx(direct["be_over_realized"], rel=1e-12)
    assert set(REQUIRED_OUTPUT_COLUMNS) <= set(row)


# ----------------------------------------------------------------- the cache


def test_the_greeks_cache_only_fetches_the_dates_it_does_not_have(tmp_path):
    greeks, _iv = synthetic_inputs(n=40)
    dates = list(greeks.index)
    asked = []

    def fake_fetch(missing):
        asked.append(list(missing))
        return {pd.Timestamp(d): object() for d in missing}

    def fake_panel(curve_map, pair):
        return greeks.loc[greeks.index.isin(list(curve_map))]

    first = greeks_with_cache(USD_PAIR, dates[:30], fetch_curves=fake_fetch,
                              cache_dir=tmp_path, panel_fn=fake_panel)
    assert len(first) == 30
    assert len(asked) == 1 and len(asked[0]) == 30

    second = greeks_with_cache(USD_PAIR, dates, fetch_curves=fake_fetch,
                               cache_dir=tmp_path, panel_fn=fake_panel)
    assert len(second) == 40
    assert len(asked) == 2
    assert len(asked[1]) == 10          # only the ten new dates were fetched
    assert list(asked[1]) == [d.date() for d in dates[30:]]

    third = greeks_with_cache(USD_PAIR, dates[:30], fetch_curves=fake_fetch,
                              cache_dir=tmp_path, panel_fn=fake_panel)
    assert len(third) == 30
    assert len(asked) == 2              # nothing new was asked for at all


def test_the_greeks_cache_returns_only_the_dates_requested(tmp_path):
    greeks, _iv = synthetic_inputs(n=40)
    dates = list(greeks.index)

    def fake_fetch(missing):
        return {pd.Timestamp(d): object() for d in missing}

    def fake_panel(curve_map, pair):
        return greeks.loc[greeks.index.isin(list(curve_map))]

    greeks_with_cache(USD_PAIR, dates, fetch_curves=fake_fetch,
                      cache_dir=tmp_path, panel_fn=fake_panel)
    out = greeks_with_cache(USD_PAIR, dates[5:12], fetch_curves=fake_fetch,
                            cache_dir=tmp_path, panel_fn=fake_panel)
    assert list(out.index) == dates[5:12]


# ----------------------------------------------------------------- network


@pytest.mark.network
@pytest.mark.slow
def test_today_state_returns_one_row_per_supported_pair():
    out = today_state(asof=dt.date(2026, 8, 3), markets=("USD",))
    assert not out.empty
    assert set(REQUIRED_OUTPUT_COLUMNS) <= set(out.columns)
    assert out["sign"].isin([-1, 0, 1]).all()
    # every row must be able to explain itself
    assert out["reason"].astype(str).str.len().min() > 0
    # and must not claim a sample it does not have
    assert (out["sample_start"] >= pd.Timestamp("2010-01-01")).all()
    # and must not be readable as a validated edge
    assert (out["verdict"] == "DEAD").all()
    assert (out["n_trials"] == 3888).all()
    assert (~out["requirements_met"]).all()
    assert (~out["sign_input_certified"]).all()

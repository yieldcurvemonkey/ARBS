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
import hashlib
import math
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from RVUtils.SFRRVLab.stats import verdict as repo_verdict
from RVUtils.StrikelessVol.conventions import TRADING_DAYS
from RVUtils.StrikelessVol.report import FORBIDDEN_RANK_KEYS
from RVUtils.StrikelessVol.strategy import SignalConfig
from RVUtils.StrikelessVol.universe import ALL_PAIRS

from BT.signals.strikeless_vol import (
    GREEKS_CACHE_VERSION,
    MEASURED_VERDICT,
    MEASURED_VERDICT_SOURCE,
    MEASURED_VERDICT_SOURCE_SHA256,
    REQUIRED_OUTPUT_COLUMNS,
    STUDY_N_TRIALS,
    TARGET_NOT_RECOMMENDATION,
    SignalWindows,
    _assert_note_is_honest,
    _frozen_z_at,
    _greeks_cache_path,
    build_pair_inputs,
    certified_signals,
    greeks_with_cache,
    market_verdict,
    measured_verdict_drift,
    pair_state,
    parse_league_table,
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


def tmp_write(text):
    """A throwaway file carrying ``text``; returned as a Path."""
    fd, name = tempfile.mkstemp(suffix=".txt")
    Path(name).write_text(text, encoding="utf-8")
    import os

    os.close(fd)
    return Path(name)


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
        "USD": (103, 52.406660, -129.741905, -311.890471, 8.280439e-30),
        "EUR": (51, -18.061138, -112.824072, -207.587007, 3.131033e-23),
        "JPY": (76, 58.470790, -103.564716, -265.600221, 1.842530e-16),
        "GBP": (54, -11.708713, -128.992651, -246.276590, 2.499986e-33),
    }
    for market, (n_trades, gross, net1, net2, dsr) in expected.items():
        mv = MEASURED_VERDICT[market]
        assert mv.n_trades == n_trades
        assert mv.gross_bp == pytest.approx(gross, rel=1e-9)
        assert mv.net_1x_bp == pytest.approx(net1, rel=1e-9)
        assert mv.net_2x_bp == pytest.approx(net2, rel=1e-9)
        assert mv.dsr_prob == pytest.approx(dsr, rel=1e-9)
        assert mv.n_trials == 3888
    assert max(mv.dsr_prob for mv in MEASURED_VERDICT.values()) <= 1.842530e-16


# --- the staleness guards: constants against the FILE, not against constants ---
#
# The two tests below exist because the one above cannot do their job. It
# asserts hardcoded constants in the test against hardcoded constants in the
# module: an excellent mutation detector and a ZERO-strength staleness
# detector. It stayed green for 45 minutes while every emitted row quoted a
# study the source file had already superseded -- USD's DSR wrong by ~97 orders
# of magnitude and three of four break-even multipliers wrong in SIGN -- because
# nothing in the suite ever opened the file the module cites.


def _require_source():
    if not MEASURED_VERDICT_SOURCE.exists():
        pytest.skip(
            f"{MEASURED_VERDICT_SOURCE} is absent (the .superpowers tree is "
            "gitignored, so it is not in every checkout). The staleness guard "
            "binds in the worktree where the study's runs actually live."
        )


def test_the_measured_verdict_still_describes_the_run_it_cites():
    """Parse the run file and diff it against the stored numbers."""
    _require_source()
    drift = measured_verdict_drift()
    assert drift == {}, (
        "MEASURED_VERDICT no longer matches the run it names as its source. "
        "Re-transcribe from the file and update MEASURED_VERDICT_SOURCE_SHA256:\n"
        + "\n".join(f"  {m}: {'; '.join(v)}" for m, v in sorted(drift.items()))
    )


def test_the_measured_verdict_source_has_not_moved():
    """A tripwire on the whole file, not only on the league table.

    Sharper than the drift check on purpose: a re-run that happened to leave the
    league table alone would still change the sample windows, the cost table or
    the book below it, and a reader is entitled to know the numbers on the row
    came from the file as it stands.
    """
    _require_source()
    got = hashlib.sha256(MEASURED_VERDICT_SOURCE.read_bytes()).hexdigest()
    assert got == MEASURED_VERDICT_SOURCE_SHA256, (
        f"{MEASURED_VERDICT_SOURCE.name} changed (sha {got[:16]}... against the "
        f"recorded {MEASURED_VERDICT_SOURCE_SHA256[:16]}...). Run "
        "measured_verdict_drift() to see whether the numbers on every emitted "
        "row moved with it, re-transcribe if so, then update the constant."
    )


def test_the_league_table_parser_refuses_a_reordered_header():
    """A parser that shrugs at a changed header is a guard that cannot fire.

    Swapping two column names would map one column's number onto another and
    the drift check would read as a pass on the wrong figures.
    """
    _require_source()
    text = MEASURED_VERDICT_SOURCE.read_text(encoding="utf-8", errors="replace")
    swapped = text.replace(" net_1x_bp   net_2x_bp ", " net_2x_bp   net_1x_bp ")
    assert swapped != text, "the header line to corrupt was not found"
    p = tmp_write(swapped)
    with pytest.raises(ValueError, match="reordered header|expected"):
        parse_league_table(p)


def test_the_league_table_parser_reads_the_numbers_the_module_stores():
    """Read four independent numbers straight out of the file."""
    _require_source()
    live = parse_league_table()
    assert set(live) == set(MEASURED_VERDICT)
    assert live["USD"]["n_trades"] == 103
    assert live["USD"]["dsr_prob"] == pytest.approx(8.280439e-30, rel=1e-9)
    assert live["JPY"]["gross_bp"] == pytest.approx(58.470790, rel=1e-9)
    assert live["EUR"]["sample_start"] == dt.date(2019, 10, 2)
    assert all(r["verdict"] == "DEAD" for r in live.values())


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
    printed = {"USD": 0.29, "EUR": -0.19, "JPY": 0.36, "GBP": -0.10}
    for market, x in printed.items():
        assert MEASURED_VERDICT[market].breakeven_cost_mult == pytest.approx(x, abs=5e-3)
    positive = sorted(m for m, mv in MEASURED_VERDICT.items()
                      if mv.breakeven_cost_mult > 0.0)
    assert positive == ["JPY", "USD"]
    # and none of them is anywhere near 1: even the positive ones need the true
    # cost to be about a third of the assumed schedule merely to reach zero
    assert max(mv.breakeven_cost_mult for mv in MEASURED_VERDICT.values()) < 0.5


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


# ------------------------------------------- the note: the string a human reads
#
# `format_state` prints `note` under "VERDICT :", so it -- not the `verdict`
# column -- is what anyone actually reads. A review demonstrated two one-line
# edits that left the entire fast suite green: dropping the
# target-not-a-recommendation clause, and hardcoding the note's leading word to
# "ALIVE" over a row whose `verdict` column said "DEAD". Every number on the row
# was pinned; the statements ABOUT the numbers were not. These pin them, and
# `_assert_note_is_honest` additionally refuses to emit such a row at all.


def test_the_note_opens_with_the_same_verdict_the_column_carries():
    inputs, _g, _iv = built()
    row = state_row(inputs, certified_signals(inputs, SignalConfig()), SignalConfig())
    assert row["verdict"] == "DEAD"
    assert row["note"].startswith(row["verdict"] + ":")
    assert "ALIVE" not in row["note"]


def test_the_note_carries_the_target_not_a_recommendation_clause():
    inputs, _g, _iv = built()
    row = state_row(inputs, certified_signals(inputs, SignalConfig()), SignalConfig())
    assert TARGET_NOT_RECOMMENDATION in row["note"]
    assert "TARGET" in row["note"]
    assert "not a recommendation" in row["note"]


def test_the_note_names_the_uncertified_sign_input():
    inputs, _g, _iv = built()
    row = state_row(inputs, certified_signals(inputs, SignalConfig()), SignalConfig())
    assert row["sign_input_certified"] is False
    assert "be_over_realized" in row["note"]


def test_a_row_whose_note_contradicts_it_cannot_be_emitted():
    """The guard is a runtime refusal, not only a test.

    A note that announces a different result from the column beside it must not
    reach a reader at all. Checked here by handing the checker rows whose answer
    is known: the real one passes, and each corruption raises.
    """
    inputs, _g, _iv = built()
    row = state_row(inputs, certified_signals(inputs, SignalConfig()), SignalConfig())
    _assert_note_is_honest(row)  # the real row is fine

    for corrupted, needle in (
        ({**row, "note": row["note"].replace("DEAD:", "ALIVE:", 1)}, "verdict"),
        ({**row, "note": row["note"].replace(TARGET_NOT_RECOMMENDATION, "")},
         "target-not-a-recommendation"),
        ({**row, "note": row["note"].replace(str(row["n_trials"]), "12")},
         "trial count"),
        ({**row, "note": row["note"].replace("be_over_realized", "something")},
         "does not name it"),
    ):
        with pytest.raises(AssertionError, match=needle):
            _assert_note_is_honest(corrupted)


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


def _episode_last_dates(sign):
    """The last held date of every episode in a sign series."""
    s = pd.Series(sign).fillna(0).astype(int)
    out, cur, prev = [], 0, None
    for ts, v in s.items():
        if v != cur:
            if cur != 0 and prev is not None:
                out.append(prev)
            cur = int(v)
        prev = ts
    if cur != 0 and prev is not None:
        out.append(prev)
    return out


def test_decision_z_is_the_number_the_engines_reason_quotes():
    """The runner reports the live z AND the z that actually decided the row.

    On a continuing hold those are different numbers -- the engine prices the
    hold on the z frozen at ENTRY -- so reporting only the live one puts a
    figure next to a ``reason`` string quoting a different figure. Checked on
    the last day of EVERY episode against the engine's own printed reason, i.e.
    against an answer known independently rather than against a re-derivation
    of the thing under test.

    The last two assertions are what make this discriminating rather than
    merely green. The betas move slowly, so on a short hold the entry vintage
    and today's vintage agree to within the reason string's two decimal places
    -- a check that only ever looked at the most recent row passed even when
    the entry date was replaced by today's. ``n_discriminating`` counts the
    episodes where the two genuinely differ, and requiring at least one of them
    is the proof that this test can tell them apart at all.
    """
    inputs, _g, _iv = built()
    cfg = SignalConfig()
    signals = certified_signals(inputs, cfg)

    ends = _episode_last_dates(signals["sign"])
    assert len(ends) >= 5, "too few episodes to say anything"

    n_held = n_discriminating = 0
    for end in ends:
        trunc = dataclasses.replace(inputs, panel=inputs.panel.loc[:end])
        row = state_row(trunc, signals.loc[:end], cfg)
        quoted = _z_quoted_in(row["reason"])
        if quoted is None:
            continue
        assert row["decision_z"] == pytest.approx(quoted, abs=5e-3), end
        if row["held_days"] == 0:
            assert row["decision_z"] == pytest.approx(row["residual_z"], rel=1e-12)
            continue
        n_held += 1
        # not vacuous: on a hold the live z is a different number
        assert abs(row["residual_z"] - row["decision_z"]) > 1e-3, end
        # would using TODAY's beta vintage instead of the entry's give the same
        # answer? On at least one episode it must not, or this test proves
        # nothing about which vintage was used.
        today_vintage = _frozen_z_at(trunc, end, end)
        if abs(today_vintage - quoted) > 5e-3:
            n_discriminating += 1

    assert n_held >= 3, "the frozen-z branch is barely exercised"
    assert n_discriminating >= 1, (
        "on every episode the entry vintage and today's vintage agree to the "
        "reason string's precision, so this test cannot tell which was used")


def test_the_last_row_of_the_default_fixture_is_a_hold_priced_on_a_frozen_z():
    """The headline path, stated as a fact about the fixture rather than left
    to chance: the row the other tests read is a continuing hold, so
    ``residual_z`` and ``decision_z`` are genuinely different numbers there."""
    inputs, _g, _iv = built()
    cfg = SignalConfig()
    row = state_row(inputs, certified_signals(inputs, cfg), cfg)
    assert row["held_days"] > 0
    assert row["residual_z_is_decision_input"] is False
    assert abs(row["residual_z"] - row["decision_z"]) > 0.3


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


def test_two_frames_that_do_not_end_together_are_refused():
    """`signal_date` comes off the signals and `information_date` off the panel.

    Frames that end on different days would put a sign next to another day's
    diagnostics -- the exact adjacency this row exists to prevent. Latent rather
    than live (every path in the module keeps them aligned), which is why it is
    an explicit refusal rather than an assumption.
    """
    inputs, _g, _iv = built()
    signals = certified_signals(inputs, SignalConfig())
    with pytest.raises(ValueError, match="do not end together|ends"):
        state_row(inputs, signals.iloc[:-1], SignalConfig())


def test_a_holiday_only_chunk_does_not_raise_the_same_alarm_as_a_real_failure(caplog):
    """Measured: nine WARNINGs per warm 3-pair USD run, in the same words and at
    the same level as the GBP-SONIA stale-payload failure the chunker exists to
    isolate. An alarm camouflaged by its own routine noise is not an alarm."""
    import logging

    from BT.signals.strikeless_vol import _market_curve_fetcher

    class Boom:
        def __init__(self, msg):
            self.msg = msg

        def bulk_get_data(self, req):
            raise ValueError(self.msg)

    dates = [dt.date(2023, 1, 3)]
    with caplog.at_level(logging.DEBUG, logger="BT.signals.strikeless_vol"):
        caplog.clear()
        _market_curve_fetcher("USD", mdp=Boom("Request 'timestamps' resolved to "
                                              "an empty collection."), n_jobs=1)(dates)
        routine = list(caplog.records)
        caplog.clear()
        _market_curve_fetcher("USD", mdp=Boom("JSONDecodeError on convention"),
                              n_jobs=1)(dates)
        real = list(caplog.records)

    assert routine and all(r.levelno == logging.DEBUG for r in routine)
    assert real and any(r.levelno == logging.WARNING for r in real)


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


def test_the_greeks_cache_key_covers_the_bump_size_and_the_schema_version():
    """Keyed on the pair alone, a changed bump size serves the old numbers.

    ``breakeven_h25`` is only ``h=25`` by convention, and the key reads
    ``compute_greeks``' live signature rather than restating it -- so a changed
    upstream default moves the file, which is the case a hardcoded copy misses.
    """
    base = _greeks_cache_path(USD_PAIR, "/c")
    assert base != _greeks_cache_path(USD_PAIR, "/c",
                                      greeks_kwargs={"h_bps": (10.0, 30.0)})
    assert base != _greeks_cache_path(USD_PAIR, "/c",
                                      greeks_kwargs={"package_dv01_usd": 50_000.0})
    assert base == _greeks_cache_path(USD_PAIR, "/c")
    # a different pair is a different file, as before
    other = next(p for p in ALL_PAIRS
                 if p.market == "USD" and p.short.label != USD_PAIR.short.label)
    assert base != _greeks_cache_path(other, "/c")
    # and the version participates, so a schema change can be forced through
    assert GREEKS_CACHE_VERSION >= 1
    import BT.signals.strikeless_vol as M

    old = M.GREEKS_CACHE_VERSION
    try:
        M.GREEKS_CACHE_VERSION = old + 1
        assert _greeks_cache_path(USD_PAIR, "/c") != base
    finally:
        M.GREEKS_CACHE_VERSION = old


def test_the_greeks_cache_key_tracks_compute_greeks_own_default():
    """Change the upstream default and the digest must move on its own."""
    import RVUtils.StrikelessVol.greeks as G

    base = _greeks_cache_path(USD_PAIR, "/c")
    original = G.compute_greeks
    try:
        def shifted(curve, pair, *, next_date=None, package_dv01_usd=100_000.0,
                    sign=1, h_bps=(10.0, 25.0, 99.0)):
            raise NotImplementedError

        G.compute_greeks = shifted
        assert _greeks_cache_path(USD_PAIR, "/c") != base
    finally:
        G.compute_greeks = original
    assert _greeks_cache_path(USD_PAIR, "/c") == base


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


# ------------------------------------------------------ today_state, offline
#
# `today_state` had NO fast-gate coverage: its only guard was the deselected
# network test. A review's one-line edit -- returning `SIGNAL_COLUMNS` instead of
# `REQUIRED_OUTPUT_COLUMNS`, i.e. every row emitted with no verdict, no DSR, no
# trial count, no requirement flags and no note -- passed the whole fast suite.
# These drive the real composition with the two networked builders stubbed.


class FakeMDP:
    """Returns a sentinel curve for the dates the fixture actually has."""

    def __init__(self, index):
        self.index = pd.DatetimeIndex(index)
        self.requested = []

    def bulk_get_data(self, req):
        self.requested.extend(req["timestamps"])
        return {pd.Timestamp(d): object() for d in req["timestamps"]
                if pd.Timestamp(d) in self.index}


def _offline_today_state(tmp_path, *, greeks=None, iv=None, markets=("USD",),
                         windows=FAST, lookback_days=400):
    if greeks is None or iv is None:
        greeks, iv = synthetic_inputs()
    mdp = FakeMDP(greeks.index)

    def fake_panel(curve_map, pair, **kw):
        return greeks.loc[greeks.index.isin(list(curve_map))]

    out = today_state(
        asof=greeks.index[-1].date(), markets=markets,
        lookback_days=lookback_days, windows=windows, mdp=mdp,
        cache_dir=tmp_path, panel_fn=fake_panel,
        vol_panel_fn=lambda *a, **k: iv.to_frame("2y10y"),
    )
    return out, mdp


def test_today_state_emits_every_required_column_offline(tmp_path):
    out, _mdp = _offline_today_state(tmp_path)
    assert len(out) == 3                      # the three supported USD pairs
    assert list(out.columns) == list(REQUIRED_OUTPUT_COLUMNS)
    assert set(REQUIRED_OUTPUT_COLUMNS) <= set(out.columns)
    assert out["sign"].isin([-1, 0, 1]).all()
    assert out["reason"].astype(str).str.len().min() > 0


def test_today_state_carries_the_verdict_and_the_flags_on_every_row(tmp_path):
    out, _mdp = _offline_today_state(tmp_path)
    assert (out["verdict"] == "DEAD").all()
    assert (out["n_trials"] == STUDY_N_TRIALS).all()
    assert out["dsr_prob"].max() <= 1.842530e-16
    assert (~out["requirements_met"]).all()
    assert (~out["sign_input_certified"]).all()
    assert (~out["req_random_walk_placebo"]).all()
    assert out["req_expanding_betas"].all()
    for note in out["note"]:
        assert note.startswith("DEAD:")
        assert TARGET_NOT_RECOMMENDATION in note
    assert (out["status"] == "ok").all()


def test_today_state_emits_the_lookback_it_was_asked_for(tmp_path):
    """Two days' output cannot be compared for equal provenance without it.

    Measured on this fixture: 60 extra rows of history moves the target dv01 by
    ~6% with the sign unchanged, so a caller diffing yesterday against today has
    to be able to see they asked for the same window.
    """
    out, _mdp = _offline_today_state(tmp_path, lookback_days=400)
    assert (out["lookback_days"] == 400).all()
    assert (out["windows"] == FAST).all()


def test_a_pair_that_cannot_be_stated_still_appears_and_says_why(tmp_path):
    """An empty frame from an outage must not look like an empty universe.

    Measured on this fixture at ``FAST`` windows: the boundary is sharp and is
    ``backtest.MIN_INPUT_AUDIT_OBS``, not the rule's own warm-up --
    ``n=150/200/240`` raise "``drift_t`` was compared on only 9 / 59 / **99**
    dates (minimum 100)", and ``n=260`` emits a row. So a short lookback does
    not produce the visibly-flat rows a docstring once promised; it RAISES
    inside ``certified_signals``, and the pair used to vanish with a log line.
    """
    greeks, iv = synthetic_inputs(n=240)      # 99 comparable dates: one short
    out, _mdp = _offline_today_state(tmp_path, greeks=greeks, iv=iv)
    assert len(out) == 3
    assert list(out.columns) == list(REQUIRED_OUTPUT_COLUMNS)
    assert out["status"].str.startswith("failed:").all()
    assert out["reason"].str.startswith("NO STATE --").all()
    assert (out["sign"] == 0).all()
    assert (out["dv01_usd"] == 0.0).all()
    assert out["n_obs"].max() == 0
    # the honesty payload survives the failure
    assert (out["verdict"] == "DEAD").all()
    assert (out["n_trials"] == STUDY_N_TRIALS).all()
    assert (~out["requirements_met"]).all()
    assert (~out["sign_input_certified"]).all()
    for note in out["note"]:
        assert TARGET_NOT_RECOMMENDATION in note
    # and the diagnostics are absent, not zero
    assert out["be_over_realized"].isna().all()
    assert out["residual_z"].isna().all()


def test_a_market_with_no_vols_reports_every_pair_rather_than_disappearing(tmp_path):
    greeks, iv = synthetic_inputs()
    mdp = FakeMDP(greeks.index)

    def boom(*a, **k):
        raise ValueError("GS returned no swaption vols")

    out = today_state(asof=greeks.index[-1].date(), markets=("USD",),
                      lookback_days=400, windows=FAST, mdp=mdp,
                      cache_dir=tmp_path,
                      panel_fn=lambda cm, pair, **kw: greeks,
                      vol_panel_fn=boom)
    assert len(out) == 3
    assert out["status"].str.contains("no swaption vols").all()
    assert (out["verdict"] == "DEAD").all()


def test_an_empty_universe_is_an_empty_frame_with_the_right_columns(tmp_path):
    """Distinguishable from an outage precisely because an outage is not this."""
    greeks, iv = synthetic_inputs()
    out = today_state(asof=greeks.index[-1].date(), markets=("CHF",),
                      lookback_days=400, windows=FAST,
                      mdp=FakeMDP(greeks.index), cache_dir=tmp_path,
                      panel_fn=lambda cm, pair, **kw: greeks,
                      vol_panel_fn=lambda *a, **k: iv.to_frame("2y10y"))
    assert out.empty
    assert list(out.columns) == list(REQUIRED_OUTPUT_COLUMNS)


def test_today_state_agrees_with_pair_state_on_the_same_inputs(tmp_path):
    """The runner must not be a second, divergent implementation of the rule."""
    greeks, iv = synthetic_inputs()
    out, _mdp = _offline_today_state(tmp_path, greeks=greeks, iv=iv)
    row = out[out["pair"] == USD_PAIR.name].iloc[0]
    direct = pair_state(USD_PAIR, greeks, iv, cfg=SignalConfig(), windows=FAST)
    assert int(row["sign"]) == int(direct["sign"])
    assert float(row["be_over_realized"]) == pytest.approx(
        direct["be_over_realized"], rel=1e-12)
    assert float(row["decision_z"]) == pytest.approx(direct["decision_z"], rel=1e-12)


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

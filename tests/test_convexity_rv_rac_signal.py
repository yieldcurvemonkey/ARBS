r"""The workflow-4 signal: lagging, two-sidedness, and the saturation it avoids.

These are properties of the rule, tested on synthetic panels where the right
answer is known by construction. The *screen* underneath it is graded against
Citi's published table in ``test_convexity_rv_rac_screen.py``; this file grades
the step from screen to rule.

The two failures being designed against are both real and both measured:

* **A rank-only rule is permanently on.** A cross-section always has a cheapest
  pair, so ranking alone produces a rotate-the-flattener book — strat 1's
  degeneracy in new clothes. The rule therefore requires the per-pair
  time-series percentile *as well as* the cross-sectional rank.
* **The published ratio is saturated.** Citi truncates the breakeven to zero
  whenever carry is non-negative, which is 56.2 % of 2023 and 44.9 % of 2022 on
  this data, worst on the tight forward pairs the strategy is about. A
  percentile of a flat-zero series is undefined exactly where the rule wants to
  fire.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from RVUtils.ConvexityRV import rac_signal as R


def _panel(n_days=900, pairs=("A/B", "C/D", "E/F"), seed=0) -> pd.DataFrame:
    """Synthetic screen panel with the columns the signal reads."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n_days)
    rows = []
    for i, p in enumerate(pairs):
        carry = np.cumsum(rng.normal(0, 0.05, n_days)) - i
        vol = np.full(n_days, 4.0)
        be = np.where(carry < 0, np.sqrt(np.abs(np.minimum(carry, 0)) / (252 * 5 / 1e4)), 0.0)
        rows.append(pd.DataFrame({
            "date": dates, "pair": p,
            "carry_1y_bp": carry, "rlzd_vol_bp": vol,
            "level_bp": np.cumsum(rng.normal(0, 0.3, n_days)) - 10.0,
            "be_daily_analytic": be,
            "be_over_rv": be / vol,
        }))
    return pd.concat(rows, ignore_index=True)


# ---------------------------------------------------------------------------
# 1. The statistic
# ---------------------------------------------------------------------------
def test_rac_is_carry_over_annualised_vol():
    p = R.add_rac(_panel(n_days=10, pairs=("A/B",)))
    row = p.iloc[5]
    assert row["rac"] == pytest.approx(
        row["carry_1y_bp"] / (row["rlzd_vol_bp"] * np.sqrt(252.0)))


def test_rac_is_nan_not_zero_when_vol_is_undefined():
    """A warmup is not a neutral reading. Zero would rank as neutral."""
    p = _panel(n_days=10, pairs=("A/B",))
    p.loc[p.index[:3], "rlzd_vol_bp"] = np.nan
    out = R.add_rac(p)
    assert out["rac"].iloc[:3].isna().all()
    assert out["rac"].iloc[3:].notna().all()


def test_rac_is_never_truncated_where_the_published_ratio_is():
    """The whole reason the traded statistic differs from the published one."""
    p = R.add_rac(_panel())
    pos = p["carry_1y_bp"] >= 0
    assert pos.sum() > 0, "the fixture must contain positive-carry days"
    assert (p.loc[pos, "be_daily_analytic"] == 0).all(), "fixture models the truncation"
    assert (p.loc[pos, "rac"] != 0).all(), (
        "rac was truncated too — it must stay signed and continuous through zero"
    )
    assert (p.loc[pos, "rac"] > 0).all()


# ---------------------------------------------------------------------------
# 2. Lagging
# ---------------------------------------------------------------------------
def test_the_signal_never_reads_same_day_information():
    """Move one day's carry by a huge amount; today's signal must not see it."""
    base = _panel(n_days=400, pairs=("A/B", "C/D"))
    sig_a = R.build_signal_panel(base, R.RacConfig(lookback_days=120))

    spiked = base.copy()
    hit = spiked.index[(spiked["pair"] == "A/B")][300]
    spiked.loc[hit, "carry_1y_bp"] += 1000.0
    sig_b = R.build_signal_panel(spiked, R.RacConfig(lookback_days=120))

    d = spiked.loc[hit, "date"]
    same_day = sig_b.loc[(d, "A/B"), "rac_lag"]
    assert same_day == pytest.approx(sig_a.loc[(d, "A/B"), "rac_lag"]), (
        "the spike leaked into its own day's signal"
    )
    nxt = sig_b.index.get_level_values("date")
    after = sorted(x for x in set(nxt) if x > d)[0]
    assert sig_b.loc[(after, "A/B"), "rac_lag"] != pytest.approx(
        sig_a.loc[(after, "A/B"), "rac_lag"]), "the spike never arrived at all"


# ---------------------------------------------------------------------------
# 3. Two-sidedness — the property the design exists for
# ---------------------------------------------------------------------------
def test_the_rule_takes_both_sides():
    sig = R.build_signal_panel(_panel(), R.RacConfig(lookback_days=252))
    st = R.entry_state(sig, R.RacConfig(lookback_days=252))
    assert (st == 1).sum() > 0, "no flattener ever fired"
    assert (st == -1).sum() > 0, "no steepener ever fired — the rule is one-sided"
    assert (st == 0).sum() > 0, "the rule is never flat, i.e. it is permanently on"


def test_rank_alone_would_be_permanently_on():
    """The failure mode, demonstrated rather than asserted.

    With the time-series axis switched off (percentile threshold 0), the
    cross-sectional rank fires on essentially every date — which is the
    permanently-on book this design exists to avoid. The real config must be
    materially less active than that.
    """
    cfg_rank_only = R.RacConfig(lookback_days=252, enter_pct=0.0, top_n=3)
    cfg_real = R.RacConfig(lookback_days=252, enter_pct=0.80, top_n=3)
    sig = R.build_signal_panel(_panel(), cfg_real)

    on_rank_only = (R.entry_state(sig, cfg_rank_only) == 1).sum()
    on_real = (R.entry_state(sig, cfg_real) == 1).sum()
    assert on_real < 0.6 * on_rank_only, (
        f"the two-axis rule fires {on_real} times against {on_rank_only} for "
        "rank alone; it is not adding a timing dimension"
    )


def test_both_axes_are_required_for_an_entry():
    sig = R.build_signal_panel(_panel(), R.RacConfig(lookback_days=252))
    cfg = R.RacConfig(lookback_days=252)
    st = R.entry_state(sig, cfg)
    fired = sig.loc[st == 1]
    assert (fired["rac_pct"] >= cfg.enter_pct).all()
    assert (R.side_ranks(sig, cfg).loc[st == 1, "rank_in_flat"] <= cfg.top_n).all()


# ---------------------------------------------------------------------------
# 4. The universe is not uniform, and the module says so
# ---------------------------------------------------------------------------
def test_the_one_sided_family_is_named_not_averaged_over():
    assert len(R.ONE_SIDED_FAMILY) == 6
    assert all(p.startswith("10Yx10Y/") for p in R.ONE_SIDED_FAMILY)


def test_excluding_the_one_sided_family_is_available_and_off_by_default():
    p = _panel(pairs=("10Yx10Y/20Yx10Y", "15Yx5Y/20Yx10Y"))
    kept = R.build_signal_panel(p, R.RacConfig(lookback_days=252))
    dropped = R.build_signal_panel(p, R.RacConfig(lookback_days=252, exclude_one_sided=True))
    assert "10Yx10Y/20Yx10Y" in kept.index.get_level_values("pair")
    assert "10Yx10Y/20Yx10Y" not in dropped.index.get_level_values("pair")


def test_carry_positive_fraction_measures_two_sidedness():
    p = _panel(n_days=200, pairs=("A/B",))
    p["carry_1y_bp"] = np.where(np.arange(len(p)) < 50, 1.0, -1.0)
    assert R.carry_positive_fraction(p)["A/B"] == pytest.approx(0.25)


def test_saturation_table_reports_the_truncation():
    tbl = R.saturation_table(R.add_rac(_panel()))
    assert {"carry>=0", "be_truncated_to_0", "rac_exactly_0"} <= set(tbl.columns)
    assert (tbl["be_truncated_to_0"] > 0).any(), "fixture has no truncated days"
    assert (tbl["rac_exactly_0"] == 0).all(), "rac must never be exactly zero"

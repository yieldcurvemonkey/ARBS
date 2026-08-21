r"""W3: units, lagging, two-sidedness, and the diagnostic that comes first.

The trade spreads two *curve-implied* vols — a SOFR pack's Ho-Lee inversion
against an ultra-long forward flattener's daily breakeven. The failure this file
is mostly written against is a **unit mismatch**, because it is silent: both
legs are "vol in bp", both look plausible alone, and only their difference is
wrong.

``holee.implied_vol_from_ca_bp`` returns bp per **year**; ``be_daily_analytic``
is bp per **day**. The first run of this module spread them as they came and
printed a STIR leg averaging 100-135 against a long-end leg averaging 2.5-4.0,
with a "spread" of about 100 bp that was almost entirely ``sqrt(252)``.
Correlation is scale-invariant so the link diagnostics survived it untouched;
every level, spread and z-score did not.
"""

from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd
import pytest

from RVUtils.ConvexityRV import w3_ca_vs_longend as W3


def _panel(n=600, rank=13, seed=0) -> pd.DataFrame:
    """A CA panel with the columns the STIR leg reads, plus rolling pack labels."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2021-01-04", periods=n)
    ca = 12.0 + np.cumsum(rng.normal(0, 0.05, n))
    labels = [f"P{i // 63}" for i in range(n)]          # a new label each quarter
    return pd.DataFrame({
        "date": dates, "rank": rank, "pack": labels, "colour": "Blues",
        "ca_bp": ca, "time_weight": np.full(n, 12.25), "gate_ok": True,
    })


# ---------------------------------------------------------------------------
# 1. Units — the whole point
# ---------------------------------------------------------------------------
def test_stir_leg_is_returned_in_bp_per_day():
    """A SOFR normal vol is 50-200 bp/yr, i.e. 3-13 bp/day."""
    s = W3.stir_implied_vol_series(_panel(), W3.W3Config())
    assert len(s) > 100
    med = float(s.median())
    assert 1.0 < med < 30.0, (
        f"median {med:.2f} is not a daily vol; the annual figure would be "
        f"~{med * math.sqrt(252):.0f}"
    )


def test_the_annual_to_daily_conversion_is_exactly_sqrt_252():
    """Pin the constant, so a silent change of convention fails here."""
    from RVUtils.ConvexityRV.holee import implied_vol_from_ca_bp

    p = _panel(n=200)
    s = W3.stir_implied_vol_series(p, W3.W3Config())
    row = p.iloc[100]
    annual = implied_vol_from_ca_bp(float(row["ca_bp"]),
                                    [math.sqrt(float(row["time_weight"]))],
                                    convention="citi")
    assert s.loc[row["date"]] == pytest.approx(annual / math.sqrt(252.0), rel=1e-9)


def test_a_leg_left_in_annual_units_is_rejected_loudly():
    """The guard must fire rather than let a 15.9x error through.

    A wrong-unit series stays plausible in isolation; only the spread against the
    other leg goes wrong, which is the hardest place to notice it.
    """
    p = _panel(n=200)
    # CA ~250bp implies a vol far above any daily figure
    p["ca_bp"] = 2500.0
    with pytest.raises(ValueError, match="bp/DAY"):
        W3.stir_implied_vol_series(p, W3.W3Config())


# ---------------------------------------------------------------------------
# 2. The colour is a rank, stitched across labels
# ---------------------------------------------------------------------------
def test_the_series_spans_every_label_not_just_the_first():
    """A pack label lives one quarter; the colour is a constant-maturity slot."""
    p = _panel(n=600)
    s = W3.stir_implied_vol_series(p, W3.W3Config())
    assert len(s) > 500, (
        f"{len(s)} points from a 600-day panel with 10 rolling labels — the "
        "series has collapsed to one label's life"
    )
    assert s.index.min() == p["date"].iloc[0]
    assert s.index.max() == p["date"].iloc[-1]


def test_an_unknown_colour_raises():
    with pytest.raises(KeyError):
        W3.stir_implied_vol_series(_panel(), W3.W3Config(colour="Purples"))


# ---------------------------------------------------------------------------
# 3. Lagging and two-sidedness
# ---------------------------------------------------------------------------
def _legs(n=800, seed=3):
    idx = pd.bdate_range("2021-01-04", periods=n)
    rng = np.random.default_rng(seed)
    a = pd.Series(6.5 + np.cumsum(rng.normal(0, 0.03, n)), index=idx)
    b = pd.Series(3.0 + np.cumsum(rng.normal(0, 0.02, n)), index=idx)
    return a, b


def test_the_z_score_reads_only_lagged_information():
    a, b = _legs()
    sp = W3.build_vol_spread_panel(a, b, W3.W3Config())
    # spread_lag on date t must equal spread on t-1
    assert sp["spread_lag"].iloc[5] == pytest.approx(sp["spread"].iloc[4])
    # and the z must be built from the lagged column
    assert sp["z"].notna().sum() > 100


def test_a_spike_does_not_enter_its_own_days_signal():
    a, b = _legs()
    sp0 = W3.build_vol_spread_panel(a, b, W3.W3Config())
    a2 = a.copy()
    a2.iloc[400] += 50.0
    sp1 = W3.build_vol_spread_panel(a2, b, W3.W3Config())
    d = a.index[400]
    assert sp1.loc[d, "spread_lag"] == pytest.approx(sp0.loc[d, "spread_lag"])


def test_the_rule_is_two_sided_and_has_hysteresis():
    a, b = _legs()
    sp = W3.build_vol_spread_panel(a, b, W3.W3Config())
    st = W3.entry_state(sp, W3.W3Config())
    assert (st == 1).sum() > 0 and (st == -1).sum() > 0, (
        "the rule only takes one side; a one-sided spread trade is a "
        "directional position on one of its legs"
    )
    assert (st == 0).sum() > 0

    # hysteresis: strictly fewer state changes than a no-hysteresis rule
    naive = np.sign(sp["z"].fillna(0.0).to_numpy())
    assert int((st.diff() != 0).sum()) < int((pd.Series(naive).diff() != 0).sum())


# ---------------------------------------------------------------------------
# 4. The diagnostic that comes before the trade
# ---------------------------------------------------------------------------
def test_link_diagnostics_reports_changes_not_only_levels():
    a, b = _legs()
    d = W3.link_diagnostics(a, b)
    assert {"corr_levels", "corr_changes", "spread_adf_p",
            "spread_half_life_days"} <= set(d)


def test_two_independent_random_walks_do_not_reject_a_unit_root():
    """Verify the checker against a case whose answer is known.

    If ADF rejected here, the test below asserting that the real spreads fail to
    reject would mean nothing.
    """
    idx = pd.bdate_range("2021-01-04", periods=1200)
    rng = np.random.default_rng(19)
    a = pd.Series(np.cumsum(rng.normal(0, 1, 1200)), index=idx)
    b = pd.Series(np.cumsum(rng.normal(0, 1, 1200)), index=idx)
    d = W3.link_diagnostics(a, b)
    assert d["spread_adf_p"] > 0.05, (
        f"ADF p={d['spread_adf_p']:.4f} rejected a unit root on the difference "
        "of two independent random walks; the test is not measuring what it "
        "claims to"
    )


def test_a_stationary_spread_is_detected():
    """The other half of the checker: an OU spread must reject."""
    idx = pd.bdate_range("2021-01-04", periods=1200)
    rng = np.random.default_rng(23)
    common = np.cumsum(rng.normal(0, 1, 1200))
    a = pd.Series(common + rng.normal(0, 0.3, 1200), index=idx)
    b = pd.Series(common + rng.normal(0, 0.3, 1200), index=idx)
    d = W3.link_diagnostics(a, b)
    assert d["spread_adf_p"] < 0.05
    assert 0 < d["spread_half_life_days"] < 60

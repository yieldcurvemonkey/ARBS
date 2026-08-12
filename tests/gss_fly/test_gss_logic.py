"""Known-answer tests for the GSS butterfly logic.

GSS's calibrated outputs did not survive, so there is no artifact to tie out against. Faithfulness
here therefore means: every formula is checked against a value derived by hand from the source, on
inputs whose answer is known before the code runs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from BT.gss_fly.config import CostConfig, FlyConfig, GSSConfig
from BT.gss_fly.costs import fly_tcost_bp, repo_carry_bp, repo_tag, repo_tag_grid
from BT.gss_fly.flies import build_weights, select_wings, wing_window
from BT.gss_fly.signals import cross_sectional_zscore, ewm_zscore, ts_scoring


# ----------------------------------------------------------------- weights
def test_build_weights_hand_derived():
    """w_L = -(M_R-M_B)/(M_R-M_L), w_B = 1, w_R = -(M_B-M_L)/(M_R-M_L).

    For 5/10/30: span 25, w_L = -20/25 = -0.8, w_R = -5/25 = -0.2.
    """
    w = build_weights([5.0, 10.0, 30.0])
    assert w == pytest.approx([-0.8, 1.0, -0.2])


def test_build_weights_sum_to_zero():
    """w_L + w_R = -1 identically, so a GSS fly is maturity-neutral by construction."""
    for legs in ([2.0, 5.0, 10.0], [7.0, 10.0, 12.0], [10.0, 20.0, 30.0], [1.5, 3.25, 9.75]):
        w = build_weights(legs)
        assert sum(w) == pytest.approx(0.0, abs=1e-12)
        assert w[1] == 1.0
        assert w[0] < 0 and w[2] < 0


def test_build_weights_midpoint_belly_is_symmetric():
    w = build_weights([5.0, 10.0, 15.0])
    assert w == pytest.approx([-0.5, 1.0, -0.5])


def test_build_weights_degenerate_raises():
    with pytest.raises(ValueError):
        build_weights([10.0, 10.0, 10.0])


# ------------------------------------------------------------ wing windows
def test_wing_window_three_buckets():
    cfg = FlyConfig()
    assert wing_window(7.0, cfg) == (5.0, 9.0)        # < 10y  -> +/- 2y
    assert wing_window(15.0, cfg) == (10.0, 20.0)     # 10-20y -> +/- 5y
    lo, hi = wing_window(25.0, cfg)                   # >= 20y -> left from 20y, right far out
    assert lo == 20.0 and hi == 125.0


def test_wing_window_boundaries_follow_the_original():
    cfg = FlyConfig()
    assert wing_window(9.999, cfg)[0] == pytest.approx(7.999)   # still bucket 1
    assert wing_window(10.0, cfg) == (5.0, 15.0)                # bucket 2 at exactly 10
    assert wing_window(20.0, cfg)[0] == 20.0                    # bucket 3 at exactly 20


# ---------------------------------------------------------- wing selection
def _curve():
    return pd.DataFrame(
        {
            "ttm": [3.0, 4.0, 5.0, 6.0, 7.0],
            "maturity": [3.0, 4.0, 5.0, 6.0, 7.0],
            "signal": [0.5, -2.0, 0.0, 1.0, 3.0],
        },
        index=["A", "B", "C", "D", "E"],
    )


def test_select_wings_maximises_the_signal_gap():
    """Belly C (ttm 5, signal 0). Window +/-2y -> left {A,B}, right {D,E}.

    |signal - 0|: A 0.5, B 2.0 -> B. D 1.0, E 3.0 -> E.
    """
    assert select_wings(_curve(), "C", FlyConfig(wing_objective="signal_gap")) == ["B", "C", "E"]


def test_legacy_mode_reproduces_the_original_defect():
    """The original subtracts the belly's TIME TO MATURITY from the wing's SIGNAL.

    With belly ttm 5: |signal - 5| is A 4.5, B 7.0 -> B; D 4.0, E 2.0 -> D. The right wing differs
    from the corrected objective, which is the whole point of keeping the mode.
    """
    legacy = select_wings(_curve(), "C", FlyConfig(wing_objective="legacy_ttm_bug"))
    assert legacy == ["B", "C", "D"]
    assert legacy != select_wings(_curve(), "C", FlyConfig(wing_objective="signal_gap"))


def test_select_wings_returns_empty_without_a_side():
    curve = _curve()
    assert select_wings(curve, "A", FlyConfig()) == []   # nothing to the left of the shortest
    assert select_wings(curve, "E", FlyConfig()) == []   # nothing to the right of the longest


def test_select_wings_unknown_belly():
    assert select_wings(_curve(), "ZZZ", FlyConfig()) == []


# ------------------------------------------------------------------ costs
def test_fly_tcost_bucket_lookup():
    """Default table: 0->0.20, 3->0.25, 5->0.30, 7->0.40, 10->0.50, 20->0.80."""
    cfg = CostConfig(cost_legs="belly_only")
    assert fly_tcost_bp([2.0, 4.0, 6.0], [-0.5, 1.0, -0.5], cfg) == pytest.approx(0.25)   # belly 4y
    assert fly_tcost_bp([8.0, 12.0, 25.0], [-0.5, 1.0, -0.5], cfg) == pytest.approx(0.50)  # belly 12y
    assert fly_tcost_bp([1.0, 1.0, 1.0], [-0.5, 1.0, -0.5], cfg) == pytest.approx(0.20)    # clamp low
    assert fly_tcost_bp([25.0, 28.0, 30.0], [-0.5, 1.0, -0.5], cfg) == pytest.approx(0.80)  # clamp high


def test_fly_tcost_all_legs_is_weighted_sum():
    """5/10/30 weights are (-0.8, 1, -0.2); buckets 0.30 / 0.50 / 0.80.

    0.8*0.30 + 1*0.50 + 0.2*0.80 = 0.24 + 0.50 + 0.16 = 0.90
    """
    cfg = CostConfig(cost_legs="all")
    assert fly_tcost_bp([5.0, 10.0, 30.0], build_weights([5.0, 10.0, 30.0]), cfg) == pytest.approx(0.90)


def test_all_legs_costs_more_than_belly_only():
    """The deviation has to bite, otherwise it is not worth carrying."""
    ttms, w = [5.0, 10.0, 30.0], build_weights([5.0, 10.0, 30.0])
    assert fly_tcost_bp(ttms, w, CostConfig(cost_legs="all")) > fly_tcost_bp(
        ttms, w, CostConfig(cost_legs="belly_only")
    )


# ------------------------------------------------------------------- repo
def test_repo_carry_sign_and_scale():
    """GSS books Repo = -(r/360)*days, so a positive rate is a drag."""
    assert repo_carry_bp(3.6, 10.0) == pytest.approx(-0.1)      # 3.6/360*10 = 0.1
    assert repo_carry_bp(4.5, 0.0) == pytest.approx(0.0)
    assert repo_carry_bp(float("nan"), 30.0) == 0.0


def test_repo_carry_scales_by_net_financed_position():
    """A maturity-weighted GSS fly sums to zero, so it is close to self-financing."""
    w = build_weights([5.0, 10.0, 30.0])
    assert repo_carry_bp(4.0, 30.0, weights=w) == pytest.approx(0.0, abs=1e-12)
    assert repo_carry_bp(4.0, 30.0, weights=[1.0, 0.0, 0.0]) == pytest.approx(-4.0 / 360 * 30)


def test_repo_tag_grammar():
    assert repo_tag("USTREASGC", "ON") == "RATES.REPO.USD.USTREASGC.SPOT.ON"
    assert repo_tag("USD10YOTR", "3M") == "RATES.REPO.USD.USD10YOTR.SPOT.3M"
    assert len(repo_tag_grid()) == 4 * 14
    with pytest.raises(ValueError):
        repo_tag("NOTACOLLATERAL", "ON")
    with pytest.raises(ValueError):
        repo_tag("USTREASGC", "13Y")


# ---------------------------------------------------------------- scoring
def test_cross_sectional_zscore_hand_derived():
    """Row [1,2,3]: mean 2, sample std 1 -> [-1, 0, 1]."""
    df = pd.DataFrame([[1.0, 2.0, 3.0]], index=[pd.Timestamp("2026-01-02")], columns=["a", "b", "c"])
    out = cross_sectional_zscore(df)
    assert out.iloc[0].tolist() == pytest.approx([-1.0, 0.0, 1.0])


def test_cross_sectional_zscore_flat_row_is_nan_not_zero():
    """A row with no dispersion has no defined z; emitting 0 would read as 'fairly priced'."""
    df = pd.DataFrame([[5.0, 5.0, 5.0]], index=[pd.Timestamp("2026-01-02")], columns=list("abc"))
    assert cross_sectional_zscore(df).iloc[0].isna().all()


def test_ewm_zscore_of_a_constant_series_is_undefined_not_zero():
    """A series with no dispersion has no z.

    Emitting 0.0 would read as "exactly fairly priced" and would let a dead or stale series sit
    quietly inside the universe; NaN takes it out. Same rule as the cross-sectional flat row.
    """
    s = pd.Series([2.0] * 40, index=pd.bdate_range("2026-01-01", periods=40))
    z = ewm_zscore(s, scoring_com=20.0)
    assert z.isna().all()


def test_ewm_zscore_reacts_to_a_step():
    """A jump makes the last point rich relative to its own trailing mean."""
    s = pd.Series([0.0] * 40 + [5.0], index=pd.bdate_range("2026-01-01", periods=41))
    z = ewm_zscore(s, scoring_com=20.0)
    assert z.iloc[-1] > 2.0


def test_ts_scoring_is_finite_and_trailing():
    rng = np.random.default_rng(7)
    s = pd.Series(rng.normal(size=250).cumsum(), index=pd.bdate_range("2025-01-01", periods=250))
    z = ts_scoring(s, smoothing_halflife=2.0, scoring_com=30.0)
    assert z.index.equals(s.index)
    assert z.dropna().abs().max() < 50  # no blow-up from a near-zero EWM std


def test_ts_scoring_uses_only_the_past():
    """Truncating the future must not change a value computed in the past."""
    rng = np.random.default_rng(11)
    s = pd.Series(rng.normal(size=200).cumsum(), index=pd.bdate_range("2025-01-01", periods=200))
    full = ts_scoring(s, 2.0, 30.0)
    trunc = ts_scoring(s.iloc[:150], 2.0, 30.0)
    common = trunc.dropna().index
    assert np.allclose(full.loc[common].to_numpy(), trunc.loc[common].to_numpy(), equal_nan=True)


def test_config_describe_is_stable():
    assert "gss_fly" in GSSConfig().describe()


# ------------------------------------------------- repo workbook header row
def test_repo_workbook_header_row_is_the_one_with_most_tags(tmp_path):
    """A Velocity export's row 0 is the formula, not the header.

    `=CVTSHIST("RATES.REPO.USD.USTREASGC.SPOT.ON,RATES.REPO...")` is a single cell that contains
    "RATES.REPO", so "first row that mentions it" selects the formula and parses a comma-joined
    tag list as one column name. Every tenor lookup then misses and the workbook reads as having
    no columns for the collateral — which is exactly how the supplied workbook failed to load.
    """
    import pandas as pd

    from BT.gss_fly.costs import load_repo_from_workbook

    formula = '=CVTSHIST("RATES.REPO.USD.USTREASGC.SPOT.ON,RATES.REPO.USD.USTREASGC.SPOT.1M")'
    rows = [
        [formula, None, None],
        ["Date", "RATES.REPO.USD.USTREASGC.SPOT.ON - x", "RATES.REPO.USD.USTREASGC.SPOT.1M - x"],
        ["2025-01-02", 4.30, 4.31],
        ["2025-01-03", 4.28, 4.29],
    ]
    path = tmp_path / "repo.xlsx"
    pd.DataFrame(rows).to_excel(path, header=False, index=False)

    rc = load_repo_from_workbook(path, "USTREASGC")
    assert set(rc.frame.columns) == {"ON", "1M"}
    assert len(rc.frame) == 2
    assert rc.frame["ON"].iloc[0] == pytest.approx(4.30)


# ----------------------------------------------- P&L decomposition identity
class _FakeBT:
    def __init__(self, hist):
        self.frb_component_histories = hist


def _fake_result(*, bond, financing, open_mtm, unwind, fees, equity_end):
    """A GSSResult whose ledgers and closed log are set to known values."""
    import pandas as pd

    from BT.gss_fly.backtest import GSSResult

    idx = pd.date_range("2025-01-01", periods=3, freq="D")
    hist = {
        "bond_realized": {idx[-1]: bond},
        "financing_realized": {idx[-1]: financing},
        "bond_open_mtm": {idx[-1]: open_mtm},
    }
    closed = pd.DataFrame({
        "realized_pnl": [unwind - fees],
        "gross_realized_pnl": [unwind],
        "fee_allocated": [fees],
        "holding_period_days": [7.5],
    })
    return GSSResult(
        equity=pd.Series([0.0, equity_end / 2, equity_end], index=idx),
        closed=closed, trade_log=pd.DataFrame(), backtest=_FakeBT(hist), engine=None,
    )


def test_pnl_decomposition_reconciles_to_the_equity_curve():
    """equity == bond_ledger + financing_ledger - fees + open_mark, identically.

    The numbers are the measured GSS defaults. Two earlier versions of this decomposition were
    confidently wrong, so the identity is pinned rather than described.
    """
    from BT.gss_fly.backtest import summarize

    res = _fake_result(bond=2_450_064.74, financing=355_464.50, open_mtm=444_652.82,
                       unwind=10_736_110.91, fees=2_818_737.56, equity_end=431_444.50)
    s = summarize(res)
    assert s["reconciliation_gap_usd"] == pytest.approx(0.0, abs=1e-6)


def test_the_finer_split_also_sums_to_equity():
    """carry + unwind - fees + open == equity, the split that separates the two economics."""
    from BT.gss_fly.backtest import summarize

    res = _fake_result(bond=2_450_064.74, financing=355_464.50, open_mtm=444_652.82,
                       unwind=10_736_110.91, fees=2_818_737.56, equity_end=431_444.50)
    s = summarize(res)
    total = (s["carry_during_hold_usd"] + s["unwind_proceeds_usd"]
             + s["fees_usd"] + s["open_mtm_usd"])
    assert total == pytest.approx(431_444.50, abs=1e-6)
    # and carry is the ledgers minus what the unwinds booked, i.e. genuinely disjoint from unwind
    assert s["carry_during_hold_usd"] == pytest.approx(
        2_450_064.74 + 355_464.50 - 10_736_110.91, abs=1e-6)


def test_the_per_trade_sum_is_not_a_component_and_would_break_the_identity():
    """Guard on the guard: adding the closed-log sum back in must NOT reconcile.

    This is the exact mistake the first decomposition made — it double-counted every unwind by
    $10.7m. If the identity still held with that term added, this test would be proving nothing.
    """
    from BT.gss_fly.backtest import summarize

    res = _fake_result(bond=2_450_064.74, financing=355_464.50, open_mtm=444_652.82,
                       unwind=10_736_110.91, fees=2_818_737.56, equity_end=431_444.50)
    s = summarize(res)
    wrong = (s["per_trade_pnl_usd"] + s["bond_ledger_usd"]
             + s["financing_ledger_usd"] + s["open_mtm_usd"])
    assert abs(wrong - 431_444.50) > 1_000_000


def test_cost_share_of_gross_is_reported():
    from BT.gss_fly.backtest import summarize

    res = _fake_result(bond=2_450_064.74, financing=355_464.50, open_mtm=444_652.82,
                       unwind=10_736_110.91, fees=2_818_737.56, equity_end=431_444.50)
    s = summarize(res)
    assert s["gross_before_fees_usd"] == pytest.approx(431_444.50 + 2_818_737.56, abs=1e-6)
    assert 0.8 < s["cost_share_of_gross"] < 0.9

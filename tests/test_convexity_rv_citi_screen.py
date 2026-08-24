"""Citi's Figure-20 convexity screen.

The fixtures leave real holes on purpose: a CA that goes negative (so the vol
inversion has something to refuse), a roll date carrying a jump (so the
realized-vol exclusion has something to exclude), and a vol path that moves (so
the model level cannot be a constant that any formula reproduces).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from RVUtils.ConvexityRV import citi_screen as SC


# ---------------------------------------------------------------------------
def _panel(n: int = 400, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2021-01-04", periods=n)
    out = pd.DataFrame(index=idx)
    # w and t1mean are the Ho-Lee moments; a colour four contracts deeper has
    # a larger second moment, which is the whole shape of the CA curve.
    for k, lab in enumerate(SC.SCREEN_STRUCTURES):
        t1 = 0.25 * (4 * k + 2.5)                      # mean years to expiry
        w = t1 ** 2 + 0.3
        sig = 90.0 + 20.0 * np.sin(np.arange(n) / 40.0) + rng.normal(0, 1.0, n)
        l = lab.lower()
        out[f"{l}_w"] = w
        out[f"{l}_t1mean"] = t1
        out[SC.VOL_COL[lab]] = sig
        # a CA that sits near the model but wanders, and goes NEGATIVE for the
        # front pack -- the hole the vol inversion has to refuse
        out[f"{l}_ca_bp"] = (sig ** 2 * w / 2e4
                             + np.cumsum(rng.normal(0, 0.05, n)) - 0.5 * (k == 0))
        out[f"{l}_fwd1y_pct"] = 2.5 + np.cumsum(rng.normal(0, 0.01, n))
    out["is_roll"] = False
    rolls = idx[60::63]
    out.loc[rolls, "is_roll"] = True
    # plant a big jump ON each roll date in every pack rate
    for lab in SC.SCREEN_STRUCTURES:
        l = lab.lower()
        out.loc[rolls, f"{l}_fwd1y_pct"] += 0.50
    return out


# ---------------------------------------------------------------------------
# 1. the columns are the declared algebra
# ---------------------------------------------------------------------------
def test_model_level_is_the_holee_second_moment_form():
    s = pd.Series([100.0, 120.0])
    w = pd.Series([13.22, 13.22])
    got = SC.model_ca_bp(s, w)
    assert got.iloc[0] == pytest.approx(100.0 ** 2 * 13.22 / 2e4)
    assert got.iloc[1] == pytest.approx(120.0 ** 2 * 13.22 / 2e4)


def test_roll_uses_the_FIRST_moment_not_the_second():
    """``mean(T1)`` and ``mean(T1^2)`` do different jobs; using w here would be
    a Jensen-sized error in a first-order term."""
    sig, t1, w = 100.0, 3.5, 13.22
    got = float(SC.roll_3m_bp(pd.Series([sig]), pd.Series([t1])).iloc[0])
    assert got == pytest.approx(sig ** 2 * t1 / 1e4 * 0.25)
    assert got != pytest.approx(sig ** 2 * w / 1e4 * 0.25)


def test_roll_is_positive_for_a_short_position():
    assert float(SC.roll_3m_bp(pd.Series([110.0]), pd.Series([3.5])).iloc[0]) > 0


def test_implied_vol_inverts_the_model_and_refuses_a_negative_ca():
    w = pd.Series([13.22, 13.22, 13.22])
    ca = pd.Series([9.0, 0.0, -1.5])
    v = SC.implied_vol_bp(ca, w)
    assert v.iloc[0] == pytest.approx(np.sqrt(2e4 * 9.0 / 13.22))
    assert np.isnan(v.iloc[1]) and np.isnan(v.iloc[2])
    # and it round-trips
    assert float(v.iloc[0] ** 2 * 13.22 / 2e4) == pytest.approx(9.0)


def test_pack_rate_is_the_matched_forward_plus_the_adjustment():
    r = SC.pack_rate_bp(pd.Series([9.0]), pd.Series([2.5]))
    assert float(r.iloc[0]) == pytest.approx(250.0 + 9.0)


def test_rolling_z_is_causal_and_uses_a_trailing_window():
    x = pd.Series(np.arange(300.0))
    z = SC.rolling_z(x, 63)
    assert z.iloc[:31].isna().all()
    # a strictly rising series must sit ABOVE its own trailing mean
    assert (z.dropna() > 0).all()
    # and moving a FUTURE value must not change a past z
    x2 = x.copy()
    x2.iloc[200:] += 1000.0
    z2 = SC.rolling_z(x2, 63)
    assert float((z.iloc[:200] - z2.iloc[:200]).abs().max()) < 1e-12


def test_realized_vol_excludes_roll_returns_and_it_matters():
    idx = pd.bdate_range("2021-01-04", periods=200)
    rate = pd.Series(np.cumsum(np.random.default_rng(3).normal(0, 1.0, 200)),
                     index=idx)
    is_roll = pd.Series(False, index=idx)
    is_roll.iloc[63] = is_roll.iloc[126] = True
    rate.iloc[63:] += 50.0
    rate.iloc[126:] += 50.0
    with_jump = SC.realized_vol_bp(rate, window=63, ann=252.0)
    without = SC.realized_vol_bp(rate, window=63, ann=252.0, is_roll=is_roll)
    assert float(with_jump.iloc[130]) > 3.0 * float(without.iloc[130]), (
        "the exclusion has to be doing real work in this fixture")


def test_nearer_colour_walks_the_strip_and_stops_at_the_front():
    assert SC.nearer_colour("BLUES") == "GREENS"
    assert SC.nearer_colour("GOLDS") == "BLUES"
    assert SC.nearer_colour("WHITES") is None


# ---------------------------------------------------------------------------
# 2. the screen as a whole
# ---------------------------------------------------------------------------
def test_screen_has_every_declared_column_on_every_structure():
    s = SC.build_screen(_panel())
    assert set(s) == set(SC.COLUMNS)
    for c in SC.COLUMNS:
        assert list(s[c].columns) == list(SC.SCREEN_STRUCTURES)
        assert len(s[c]) == 400


def test_the_notes_first_identity_holds_exactly():
    p = _panel()
    s = SC.build_screen(p)
    ids = SC.verify_identities(s, p)
    assert ids["ca_minus_model_minus_vsmodel"] < 1e-12
    assert ids["implied_reconstructs_ca"] < 1e-9


def test_the_identity_check_can_actually_fail():
    """A vacuous identity test is worth nothing: break the screen and watch it."""
    p = _panel()
    s = dict(SC.build_screen(p))
    s["vs_model"] = s["vs_model"] + 0.5
    ids = SC.verify_identities(s, p)
    assert ids["ca_minus_model_minus_vsmodel"] > 0.4


def test_screen_table_renders_the_notes_own_row_order():
    p = _panel()
    s = SC.build_screen(p)
    t = SC.screen_table(s, p.index[-1])
    assert list(t.index) == list(SC.SCREEN_STRUCTURES)
    assert list(t.columns) == list(SC.COLUMNS)
    assert t.loc["BLUES", "ca"] == pytest.approx(float(p["blues_ca_bp"].iloc[-1]))
    assert (t["ca"] - t["model"] - t["vs_model"]).abs().max() < 1e-12


def test_the_ca_curve_rises_with_pack_depth_in_the_fixture():
    """Sanity on the fixture itself -- a screen built on a flat CA curve would
    make the selection rule untestable."""
    p = _panel()
    s = SC.build_screen(p)
    means = s["ca"].mean()
    assert list(means.sort_values().index) == list(SC.SCREEN_STRUCTURES)


def test_missing_panel_columns_raise_rather_than_silently_dropping_a_structure():
    p = _panel().drop(columns=["blues_t1mean"])
    with pytest.raises(KeyError, match="BLUES"):
        SC.build_screen(p)


def test_roll_identity_compares_two_estimates_of_the_same_quantity():
    p = _panel()
    s = SC.build_screen(p)
    ri = SC.roll_identity(s)
    assert list(ri.index) == list(SC.SCREEN_STRUCTURES[1:])
    assert (ri["n"] > 100).all()
    assert ri["analytic_mean_bp"].gt(0).all()


def test_excluding_roll_returns_can_be_switched_off_and_changes_the_answer():
    p = _panel()
    on = SC.build_screen(p, cfg=SC.ScreenConfig(exclude_roll_returns=True))
    off = SC.build_screen(p, cfg=SC.ScreenConfig(exclude_roll_returns=False))
    a = on["realized"]["BLUES"].dropna()
    b = off["realized"]["BLUES"].dropna()
    common = a.index.intersection(b.index)
    assert float((a.loc[common] - b.loc[common]).abs().max()) > 1.0


def test_z_columns_are_not_the_same_series_at_two_window_lengths():
    s = SC.build_screen(_panel())
    a = s["vs_model_z_3m"]["BLUES"].dropna()
    b = s["vs_model_z_1y"]["BLUES"].dropna()
    common = a.index.intersection(b.index)
    assert len(common) > 50
    assert float((a.loc[common] - b.loc[common]).abs().max()) > 0.1

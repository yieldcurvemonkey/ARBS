"""V1 (option-adjusted basis) tests.

Built on a synthetic panel so they are fast and independent of the multi-hour data build, and so
the P&L identity can be checked against a series whose answer is known by construction.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from RVUtils.BasisVsVol.build_basis_panel import _coupon_years, _mod_duration, front_symbol
from RVUtils.BasisVsVol.v1 import TICK_USD_PER_MM, V1Config, add_model_option, run_v1


# --------------------------------------------------------------------------- panel plumbing
def test_front_symbol_walks_the_calendar_chronologically():
    """The bug this pins: months-outer/years-inner returns next March before this June."""
    assert front_symbol("ZB", dt.date(2024, 4, 15)) == "ZBM24"
    assert front_symbol("ZB", dt.date(2024, 1, 10)) == "ZBH24"
    assert front_symbol("ZB", dt.date(2024, 7, 1)) == "ZBU24"
    assert front_symbol("ZB", dt.date(2024, 11, 5)) == "ZBZ24"


def test_front_symbol_rolls_before_first_notice():
    """First notice is the last business day of the month before delivery; the roll precedes it."""
    assert front_symbol("ZB", dt.date(2024, 2, 15)) == "ZBH24"
    assert front_symbol("ZB", dt.date(2024, 2, 27)) == "ZBM24"  # inside the 7-day buffer


def test_modified_duration_is_sane_and_ordered():
    long_low = _mod_duration(2.0, 4.0, 25.0)
    long_high = _mod_duration(6.0, 4.0, 25.0)
    short = _mod_duration(4.0, 4.0, 5.0)
    assert 12.0 < long_low < 20.0
    assert long_low > long_high > short > 0     # lower coupon = longer duration
    assert np.isnan(_mod_duration(np.nan, 4.0, 10.0))
    assert np.isnan(_mod_duration(4.0, 4.0, np.nan))


def test_coupon_and_maturity_parse_from_the_label():
    cpn, yrs = _coupon_years("T 4 5/8 Nov 44", dt.date(2024, 4, 15))
    assert cpn == pytest.approx(4.625)
    assert 20.0 < yrs < 21.0
    cpn2, _ = _coupon_years("WI-T 5 1/8 Aug 46", dt.date(2026, 8, 12))
    assert cpn2 == pytest.approx(5.125)
    cpn3, _ = _coupon_years("T 3 Nov 44", dt.date(2024, 4, 15))
    assert cpn3 == pytest.approx(3.0)


# --------------------------------------------------------------------------- synthetic panel
def _panel(n=400, seed=7, roll_every=60):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n)
    nb = 3.0 + np.cumsum(rng.normal(0, 0.25, n))            # a mean-reverting-ish net basis
    sym = [f"ZB{'HMUZ'[(i // roll_every) % 4]}2{i // roll_every}" for i in range(n)]
    return pd.DataFrame({
        "date": dates, "root": "ZB", "symbol": sym,
        "futures_price": 120.0 + rng.normal(0, 1, n),
        "repo_pct": 3.5, "delivery_date": [d.date() + dt.timedelta(days=60) for d in dates],
        "n_deliverable": 40,
        "ctd_label": "T 4 Nov 44", "ctd_cf": 0.85, "ctd_price": 100.0, "ctd_ytm": 4.0,
        "ctd_bnoc32": nb, "ctd_gross32": nb + 6.0, "ctd_irr": 3.4, "ctd_dv01": 0.13,
        "alt_label": "T 3 Aug 44", "alt_cf": 0.72, "alt_price": 88.0, "alt_ytm": 4.05,
        "alt_bnoc32": nb + 1.0, "alt_gross32": nb + 7.0, "alt_irr": 3.2, "alt_dv01": 0.125,
    }).assign(is_roll=lambda d: d["symbol"].ne(d["symbol"].shift(1)) & d["symbol"].shift(1).notna())


def test_model_option_has_both_components_and_they_are_positive():
    p = add_model_option(_panel(), V1Config())
    assert p["switch32"].notna().sum() > 300
    assert p["wildcard32"].notna().sum() > 300
    assert (p["switch32"].dropna() >= 0).all()
    assert (p["wildcard32"].dropna() >= 0).all()
    # OABNOC must be the market basis minus the modelled option, exactly
    ok = p[["ctd_bnoc32", "dov32", "oabnoc32"]].dropna()
    assert np.allclose(ok["oabnoc32"], ok["ctd_bnoc32"] - ok["dov32"])


def test_pnl_is_exactly_the_change_in_net_basis():
    """The identity the whole V1 mark rests on: daily P&L = side * d(net basis) * $/32nd."""
    cfg = V1Config(entry_z=0.5, exit_z=0.0, max_hold_days=999, cost_32nds=0.0)
    res = run_v1(_panel(), cfg)
    d = res.daily
    held = d[(d["in_pos"] == 1) & (d["side"] != 0)].copy()
    held["dnb"] = held["nb32"].diff()
    chk = held.dropna(subset=["dnb"]).iloc[1:]
    implied = chk["side"] * chk["dnb"] * cfg.face_mm * TICK_USD_PER_MM
    # compare only where the position was continuous (no roll/gap re-anchor on that step)
    m = chk["gross_pnl"] != 0
    assert m.sum() > 50
    assert np.allclose(chk.loc[m, "gross_pnl"], implied[m], atol=1e-6)


def test_a_roll_is_never_booked_as_pnl():
    cfg = V1Config(entry_z=0.5, exit_z=0.0, max_hold_days=999, cost_32nds=0.0)
    res = run_v1(_panel(), cfg)
    roll_dates = set(res.panel.loc[res.panel["is_roll"], "date"])
    booked = res.daily.loc[res.daily.index.isin(roll_dates), "gross_pnl"]
    assert (booked.abs() < 1e-9).all()


def test_ablation_changes_the_signal():
    """If switching the option model off left the signal identical, the model would be decoration."""
    base = run_v1(_panel(), V1Config())
    raw = run_v1(_panel(), V1Config(use_switch=False, use_wildcard=False))
    assert base.panel["oabnoc32"].notna().sum() > 300
    assert not np.allclose(base.panel["oabnoc32"].dropna().to_numpy()[:100],
                           raw.panel["oabnoc32"].dropna().to_numpy()[:100])


def test_costs_reduce_pnl_monotonically():
    tot = [run_v1(_panel(), V1Config(cost_mult=m)).daily["pnl"].sum() for m in (0.0, 1.0, 3.0)]
    assert tot[0] > tot[1] > tot[2]


# --------------------------------------------------------------------------- engine agreement
def test_query_driven_backtest_matches_the_reference_engine():
    """Two implementations, identical P&L: the framework path and the standalone loop."""
    from BT.signals.basis_pair import qdb_equity, run_v1_qdb

    cfg = V1Config(entry_z=1.0, max_hold_days=21, cost_32nds=0.0)
    bt, ref = run_v1_qdb(_panel(), cfg)
    q = float(qdb_equity(bt).iloc[-1])
    r = float(ref.daily["gross_pnl"].sum())
    assert q == pytest.approx(r, abs=1e-2)
    assert len(bt.portfolio.closed_positions_log) == len(ref.trades)


def test_harness_detects_deliberate_lookahead():
    cfg = V1Config(entry_z=1.0, exec_lag_days=1, cost_32nds=0.0)
    honest = run_v1(_panel(), cfg).daily["pnl"].sum()
    cheating = run_v1(_panel(), V1Config(entry_z=1.0, exec_lag_days=-1, cost_32nds=0.0)).daily["pnl"].sum()
    assert cheating != pytest.approx(honest, rel=1e-6)

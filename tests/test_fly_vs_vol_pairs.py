"""Tests for RVUtils.FlyVsVol.pairs (curve-mode metrics)."""
import datetime

import pandas as pd
import pytest

from RVUtils.FlyVsVol.pairs import adjacent_pairs, build_pair_history


def make_panel():
    rows = []
    for i, d in enumerate(pd.bdate_range("2026-07-01", periods=3).date):
        for sym, fwd, med, mm, fr in (
            ("SFRU26", 3.99, 3.9696, 0.87, -1.18),
            ("SFRZ26", 4.145, 4.1477, -0.38, -0.12),
            ("SFRH27", 4.225, 4.2124, 1.74, 0.49 + (3.0 if i == 2 else 0.0)),
        ):
            rows.append({
                "as_of": d, "symbol": sym, "forward_rate": fwd,
                "median_rate": med, "mm_bp": mm, "fwd_resid_bp": fr,
                "pre_norm_mass": 1.0,
            })
    return pd.DataFrame(rows)


def test_adjacent_pairs():
    assert adjacent_pairs(["A", "B", "C"]) == [("A", "B"), ("B", "C")]
    assert adjacent_pairs(["A"]) == []


def test_identities_and_values():
    hist = build_pair_history(make_panel())
    uz = hist[(hist["label"] == "SFRU26-SFRZ26")].iloc[0]
    assert uz["spread_bp"] == pytest.approx(15.5, abs=1e-9)
    assert uz["median_spread_bp"] == pytest.approx(17.81, abs=0.01)
    assert uz["pair_rent_bp"] == pytest.approx(-2.31, abs=0.01)
    assert uz["pair_rent_skew_bp"] == pytest.approx(-1.25, abs=1e-9)
    assert uz["pair_fit_bp"] == pytest.approx(-1.06, abs=1e-9)
    # decomposition identity holds exactly up to median rounding in fixture
    assert uz["pair_rent_bp"] == pytest.approx(
        uz["pair_fit_bp"] + uz["pair_rent_skew_bp"], abs=0.05
    )


def test_quality_gate_flags_bad_leg_day():
    hist = build_pair_history(make_panel())
    zh = hist[hist["label"] == "SFRZ26-SFRH27"].sort_values("as_of")
    assert bool(zh.iloc[0]["quality_ok"])
    assert not bool(zh.iloc[2]["quality_ok"])  # H27 fwd_resid 3.49 > 2.5 on day 3


def test_missing_leg_dates_dropped():
    panel = make_panel()
    panel = panel[~((panel["symbol"] == "SFRZ26")
                    & (panel["as_of"] == panel["as_of"].min()))]
    hist = build_pair_history(panel)
    uz = hist[hist["label"] == "SFRU26-SFRZ26"]
    assert len(uz) == 2  # inner join drops the missing date


def test_missing_columns_raise():
    with pytest.raises(ValueError):
        build_pair_history(pd.DataFrame({"as_of": [], "symbol": []}))

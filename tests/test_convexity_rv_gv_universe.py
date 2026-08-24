"""GV block — universe, quoted conventions, the two roll clocks, the blackout.

The conventions here are the ones a silent 2x hides in, so each has a
known-answer test and, where a panel exists, a tie-out against the timeseries
layer's own ``FLY RATE`` / ``CURVE RATE`` columns.
"""
from __future__ import annotations

import datetime
import pathlib

import numpy as np
import pandas as pd
import pytest

from RVUtils.ConvexityRV import gv_universe as U

DATA = pathlib.Path(__file__).resolve().parents[1] / "notebooks" / "data" / "convexity_rv"
CA_PANEL = DATA / "cavf_ca_panel.parquet"
PROBE = DATA / "p2_legs_probe_20260701_20260731.parquet"
LEGS = DATA / "p2_legs.parquet"


# ---------------------------------------------------------------------------
# 1. Structures
# ---------------------------------------------------------------------------
def test_pack_front_ranks_are_the_matched_imm_starts():
    assert U.matched_imm_rank("GREENS") == 9
    assert U.matched_imm_rank("BLUES") == 13
    assert U.matched_imm_rank("GOLDS") == 17
    assert U.matched_imm_rank("SFR20") == 20
    assert U.matched_imm_rank("BUNDLE5Y") == 1


def test_pack_ranks_are_four_consecutive_contracts():
    for lab, first in (("WHITES", 1), ("REDS", 5), ("GREENS", 9),
                       ("BLUES", 13), ("GOLDS", 17)):
        st = U.structure_by_label(lab)
        assert st.ranks == tuple(range(first, first + 4))
        assert st.n_legs == 4


def test_ca_col_matches_the_tb_naming():
    assert U.ca_col("BLUES") == "USD-SOFR-1D BLUES PACKS CVX_ADJ"
    assert U.ca_col("SFR20") == "USD-SOFR-1D SFR20 OUTRIGHT CVX_ADJ"


def test_unknown_structure_raises_with_the_declared_list():
    with pytest.raises(KeyError, match="declared"):
        U.structure_by_label("PURPLES")


# ---------------------------------------------------------------------------
# 2. The quoted conventions, and the DV01 that earns them
# ---------------------------------------------------------------------------
def _synth_panel() -> pd.DataFrame:
    idx = pd.bdate_range("2026-01-05", periods=5)
    cols = {}
    for k in (1, 2, 13):
        for t, v in (("1y", 4.00), ("2y", 4.10), ("3y", 4.15),
                     ("5y", 4.30), ("10y", 4.55)):
            cols[f"USD-SOFR-1D IMM_{k}x{t} OUTRIGHT RATE"] = v + 0.01 * k
    for t, v in (("2Y", 4.05), ("5Y", 4.25), ("10Y", 4.50),
                 ("10Yx10Y", 4.70), ("15Yx10Y", 4.60), ("20Yx10Y", 4.40)):
        cols[f"USD-SOFR-1D {t} OUTRIGHT RATE"] = v
    return pd.DataFrame({k: np.full(len(idx), v) for k, v in cols.items()},
                        index=idx)


def test_fly_series_is_two_belly_minus_wings_in_bp():
    p = _synth_panel()
    got = U.leg_series(p, "immF_2s5s10s")
    f = p["USD-SOFR-1D IMM_1x2y OUTRIGHT RATE"]
    b = p["USD-SOFR-1D IMM_1x5y OUTRIGHT RATE"]
    k = p["USD-SOFR-1D IMM_1x10y OUTRIGHT RATE"]
    expect = (2.0 * b - f - k) * 100.0
    assert np.allclose(got.to_numpy(), expect.to_numpy())
    # and it is NOT the half-weight form strat2_fly_universe uses
    half = (b - 0.5 * (f + k)) * 100.0
    assert not np.allclose(got.to_numpy(), half.to_numpy())


def test_curve_series_is_back_minus_front_in_bp():
    p = _synth_panel()
    got = U.leg_series(p, "le_10y10y_20y10y")
    a = p["USD-SOFR-1D 10Yx10Y OUTRIGHT RATE"]
    b = p["USD-SOFR-1D 20Yx10Y OUTRIGHT RATE"]
    assert np.allclose(got.to_numpy(), ((b - a) * 100.0).to_numpy())


def test_matched_leg_resolves_to_the_structures_own_imm_rank():
    p = _synth_panel()
    got = U.leg_series(p, "immM_2s5s10s", "BLUES")
    direct = ((2 * p["USD-SOFR-1D IMM_13x5y OUTRIGHT RATE"]
               - p["USD-SOFR-1D IMM_13x2y OUTRIGHT RATE"]
               - p["USD-SOFR-1D IMM_13x10y OUTRIGHT RATE"]) * 100.0)
    assert np.allclose(got.to_numpy(), direct.to_numpy())


def test_immM_without_a_structure_refuses():
    with pytest.raises(ValueError, match="immM"):
        U.leg_series(_synth_panel(), "immM_2s5s10s")


def test_fly_package_dv01_earns_the_quoted_move():
    """The P&L identity the sizing rests on: a fly quoted ``2b-f-k`` at
    ``leg_dv01`` per bp is a belly of ``2*leg_dv01`` and wings of ``leg_dv01``."""
    d = 50_000.0
    f, b, k = U.leg_dv01_to_leg_notionals("immF_2s5s10s", d)
    assert (f, b, k) == (-d, 2 * d, -d)
    # a 1bp move in the quoted fly, realised as +1bp belly / 0 wings:
    dfly_from_belly = 2.0 * 1.0
    pnl = b * 1.0
    assert pnl == pytest.approx(d * dfly_from_belly)
    # DV01-neutral: the three legs net to zero duration
    assert f + b + k == pytest.approx(0.0)


def test_curve_package_dv01_earns_the_quoted_move():
    d = 50_000.0
    front, back = U.leg_dv01_to_leg_notionals("le_10y10y_20y10y", d)
    assert (front, back) == (-d, d)
    assert front + back == pytest.approx(0.0)


def test_cost_dv01_is_four_x_for_a_fly_and_two_x_for_a_curve():
    assert U.leg_cost_dv01("immF_2s5s10s", 10_000.0) == pytest.approx(40_000.0)
    assert U.leg_cost_dv01("le_10y10y_20y10y", 10_000.0) == pytest.approx(20_000.0)


# ---------------------------------------------------------------------------
# 3. The two roll clocks
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def bdates() -> pd.DatetimeIndex:
    return pd.bdate_range("2021-01-04", "2026-08-21")


def test_the_two_roll_clocks_are_exactly_one_business_day_apart(bdates):
    ca = U.ca_roll_dates(bdates)
    leg = U.leg_roll_dates(bdates)
    assert len(ca) == len(leg) > 0
    assert set(ca).isdisjoint(set(leg)), "the clocks were expected to differ"
    pos = {d: i for i, d in enumerate(bdates)}
    gaps = sorted({pos[a] - pos[b] for a, b in zip(ca, leg)})
    assert gaps == [1], f"expected the CA to roll one bd after the leg, got {gaps}"


def test_ca_rolls_on_the_imm_date_itself(bdates):
    """H21 -> M21 on 2021-03-17, the third Wednesday of March 2021."""
    ca = U.ca_roll_dates(bdates)
    assert pd.Timestamp("2021-03-17") in ca
    assert pd.Timestamp("2021-03-16") not in ca


def test_blackout_covers_both_clocks_and_the_buffer(bdates):
    m = U.blackout_mask(bdates, pre_bd=U.BLACKOUT_PRE_BD,
                        post_bd=U.BLACKOUT_POST_BD)
    for d in U.ca_roll_dates(bdates) + U.leg_roll_dates(bdates):
        assert bool(m.loc[d]), f"{d.date()} is a roll date and is not blacked out"
    assert 0.0 < m.mean() < 0.25


def test_blackout_width_scales_with_the_declared_window(bdates):
    narrow = U.blackout_mask(bdates, pre_bd=0, post_bd=0)
    wide = U.blackout_mask(bdates, pre_bd=5, post_bd=5)
    assert int(narrow.sum()) < int(wide.sum())
    # pre=0/post=0 still has to cover BOTH clocks -- that is the union, not a
    # single-clock blackout, and it is the thing a one-day mismatch defeats.
    assert int(narrow.sum()) == len(U.ca_roll_dates(bdates)) * 2


def test_segments_partition_the_free_dates_and_never_contain_a_roll(bdates):
    m = U.blackout_mask(bdates)
    segs = U.roll_segments(bdates)
    covered = sum(int(bdates.get_loc(b) - bdates.get_loc(a) + 1) for a, b in segs)
    assert covered == int((~m).sum())
    rolls = set(U.ca_roll_dates(bdates)) | set(U.leg_roll_dates(bdates))
    for a, b in segs:
        assert not (rolls & set(bdates[(bdates >= a) & (bdates <= b)]))


# ---------------------------------------------------------------------------
# 4. Time weights
# ---------------------------------------------------------------------------
def test_time_weight_is_the_mean_of_squares_not_the_square_of_the_mean(bdates):
    d = bdates[500]
    t1s = U.contract_t1s(d.date(), "GOLDS")
    w = U.time_weight_series([d], "GOLDS").iloc[0]
    assert w == pytest.approx(float(np.mean(np.square(t1s))))
    assert w > float(np.mean(t1s)) ** 2, "Jensen: mean of squares exceeds the square"


def test_time_weight_orders_by_pack_depth(bdates):
    d = [bdates[500]]
    ws = {lab: U.time_weight_series(d, lab).iloc[0]
          for lab in ("WHITES", "REDS", "GREENS", "BLUES", "GOLDS")}
    assert list(ws.values()) == sorted(ws.values())


def test_contract_t1s_are_quarter_spaced(bdates):
    t1s = U.contract_t1s(bdates[500].date(), "BLUES")
    gaps = np.diff(t1s)
    assert np.all(np.abs(gaps - 0.25) < 0.02), gaps


# ---------------------------------------------------------------------------
# 5. Tie-outs against real panels (skipped when the artifact is absent)
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not PROBE.exists() and not LEGS.exists(),
                    reason="leg panel not built")
def test_fly_and_curve_conventions_tie_out_to_the_timeseries_layer():
    """The decisive one: our arithmetic must reproduce the ``FLY RATE`` and
    ``CURVE RATE`` columns the timeseries layer serves, to zero."""
    p = pd.read_parquet(LEGS if LEGS.exists() else PROBE)
    fly_col = "USD-SOFR-1D IMM_1x2y/IMM_1x5y/IMM_1x10y FLY RATE"
    cur_col = "USD-SOFR-1D 10y10y/20y10y CURVE RATE"
    if fly_col in p.columns:
        got = U.leg_series(p, "immF_2s5s10s")
        j = pd.concat([got.rename("ours"), p[fly_col].rename("theirs")],
                      axis=1).dropna()
        assert len(j) > 10
        assert float((j["ours"] - j["theirs"]).abs().max()) < 1e-8
    if cur_col in p.columns:
        got = U.leg_series(p, "le_10y10y_20y10y")
        j = pd.concat([got.rename("ours"), p[cur_col].rename("theirs")],
                      axis=1).dropna()
        assert len(j) > 10
        assert float((j["ours"] - j["theirs"]).abs().max()) < 1e-8


@pytest.mark.skipif(not CA_PANEL.exists(), reason="CA panel not built")
def test_roll_dates_are_where_the_ca_panel_actually_jumps():
    """A model-free witness: the CA's |daily change| on the measured roll dates
    must be materially larger than off them, for every pack."""
    ca = pd.read_parquet(CA_PANEL)
    rolls = set(U.ca_roll_dates(ca.index))
    assert len(rolls) >= 20
    for lab in ("GREENS", "BLUES", "GOLDS"):
        d = ca[U.ca_col(lab)].dropna().diff().dropna()
        on = d[[t in rolls for t in d.index]]
        off = d[[t not in rolls for t in d.index]]
        assert on.abs().mean() > 1.5 * off.abs().mean(), lab


def test_ca_col_ties_out_to_the_tb_naming_for_every_declared_structure():
    """One naming scheme, not two.  A second scheme that merely looks right
    produces a KeyError on a real panel -- ``BUNDLE4Y`` is tagged ``BUNDLES``,
    not ``PACKS``, and this test is what found that."""
    from TB.IRSwapsTB import _cvx_col_name
    for lab in U.STRUCTURES:
        assert U.ca_col(lab) == _cvx_col_name(U.CURVE, lab), lab


@pytest.mark.skipif(not CA_PANEL.exists(), reason="CA panel not built")
def test_every_declared_structure_has_a_column_in_the_real_ca_panel():
    ca = pd.read_parquet(CA_PANEL)
    missing = [l for l in U.STRUCTURES if U.ca_col(l) not in ca.columns]
    assert not missing, missing

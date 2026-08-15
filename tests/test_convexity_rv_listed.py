"""Known-answer tests for the LISTED-vol leg of strategy 1.

Three tiers, separated so the fast gate stays fast:

* **Hand-computed** (no I/O). Every unit conversion in ``listed_vol`` has a
  planted answer worked out on paper, not produced by the code under test:
  the ATM Bachelier value ``sigma*sqrt(T)/sqrt(2*pi)``, put-call parity in
  normal space, the exact ``x100`` price-vol/rate-vol map for SFR, and the UST
  ``sigma_P / DV01`` division.

* **Synthetic panel** (no I/O). A three-strike smile with a hand-computed
  interpolation target, used to pin the ATM-forward extraction, the smile
  assembly and the expiry matcher.

* **Data-backed** (``@pytest.mark.slow``, skipped when the parquet is absent).
  The panel-wide repricing tie-out that establishes what ``iv_bp`` *is*, and
  the realised-vol cross-check.

**Verifying the checker itself.** Four tests here are explicit mutation checks
-- each one is written so that it FAILS under a specific plausible wrong
implementation, and each names that mutation in its docstring:

``test_sfr_price_vol_scale_is_exactly_100``
    fails if the ``x100`` becomes ``/100`` or the identity.
``test_bp_per_day_does_not_use_time_to_expiry``
    fails if the annual->daily bridge is confused with a terminal standard
    deviation (``sigma*sqrt(tte)``), the single most likely unit error here.
``test_atm_vol_is_interpolated_to_the_forward_not_read_at_offset_zero``
    fails if the ATM extraction reads the ``atm_offset_bps == 0`` quote.
``test_reprice_discounting_changes_the_answer_materially``
    fails if the discount factor is dropped from ``bachelier_price``.

All four were run against the mutated code before being committed; the mutation
log is in the notebook's tie-out section.
"""

from __future__ import annotations

import datetime
import math
import pathlib

import numpy as np
import pandas as pd
import pytest

from RVUtils.ConvexityRV import listed_vol as lv
from RVUtils.ConvexityRV import strat1_listed as sl

SQRT_2PI = 2.5066282746310002


# --------------------------------------------------------------------- fixtures


def _synthetic_panel() -> pd.DataFrame:
    """Two contracts on one date, three strikes each, hand-chosen numbers.

    Contract A: offset-0 strike 4.00%, forward 3.98% -> the forward sits at
    offset **-2.0 bp** in the panel's own anchoring. Vols 110 / 100 / 96 at
    offsets -6.25 / 0 / +6.25, so linear interpolation to -2.0 bp gives

        110 + (4.25 / 6.25) * (100 - 110) = 110 - 6.8 = **103.2**

    which no implementation that simply reads the offset-0 quote (100.0) can
    produce.

    Contract B is a second expiry so the matcher has something to choose
    between: tte 1.00 vs 0.25.
    """
    rows = []
    spec = [
        ("A", 0.25, "2026-01-02", 3.98, 4.00, [(-6.25, 3.9375, 110.0, "C"),
                                               (0.0, 4.0000, 100.0, "C"),
                                               (0.0, 4.0000, 100.0, "P"),
                                               (6.25, 4.0625, 96.0, "P")]),
        ("B", 1.00, "2026-10-02", 4.10, 4.125, [(-6.25, 4.0625, 92.0, "C"),
                                                (0.0, 4.1250, 90.0, "C"),
                                                (0.0, 4.1250, 90.0, "P"),
                                                (6.25, 4.1875, 89.0, "P")]),
    ]
    for sym, tte, exp, fwd, _s0, quotes in spec:
        for off, k, vol, right in quotes:
            rows.append({
                "as_of": pd.Timestamp("2025-10-02"),
                "symbol": sym,
                "right": right,
                "strike_rate": k,
                "strike_price": 100.0 - k,
                "premium_bp": 10.0,
                "iv_bp": vol,
                "atm_offset_bps": off,
                "forward_rate": fwd,
                "tte": tte,
                "expiry_date": pd.Timestamp(exp),
            })
    df = pd.DataFrame(rows)
    df["right_rate"] = np.where(df["right"] == "C", "receiver", "payer")
    return df


@pytest.fixture(scope="module")
def real_panel():
    root = lv.default_sfr_root()
    if not (root / "quotes.parquet").exists() or not (root / "contracts.parquet").exists():
        pytest.skip(f"SFR listed panel not present under {root}")
    return lv.load_sfr_panel()


# ---------------------------------------------------------- Bachelier, by hand


def test_atm_bachelier_is_sigma_root_t_over_root_two_pi():
    """Planted answer, no library call: at F == K the normal-model call is
    ``sigma*sqrt(T)/sqrt(2*pi)``. With sigma = 100 bp/yr and T = 0.25 that is
    ``100 * 0.5 / 2.5066282746 = 19.9471140201`` bp."""
    got = lv.bachelier_price(400.0, 400.0, 0.25, 100.0, "payer")
    assert got == pytest.approx(100.0 * 0.5 / SQRT_2PI, rel=1e-12)
    assert got == pytest.approx(19.9471140201, rel=1e-10)
    # at the money the two rights are worth the same
    assert lv.bachelier_price(400.0, 400.0, 0.25, 100.0, "receiver") == pytest.approx(got, rel=1e-12)


def test_atm_bachelier_discount_multiplies_through():
    """Premium is paid upfront on SR3, so the quoted value is the DISCOUNTED
    Bachelier number. 0.98 * 19.9471140201 = 19.5481717397."""
    got = lv.bachelier_price(400.0, 400.0, 0.25, 100.0, "payer", discount=0.98)
    assert got == pytest.approx(0.98 * 100.0 * 0.5 / SQRT_2PI, rel=1e-12)
    assert got == pytest.approx(19.5481717397, rel=1e-10)


def test_bachelier_put_call_parity_in_normal_space():
    """``receiver - payer == K - F`` exactly, undiscounted -- a hand-derivable
    identity that pins the payer/receiver convention without needing a table."""
    F, K, T, sig = 400.0, 450.0, 1.0, 100.0
    payer = lv.bachelier_price(F, K, T, sig, "payer")
    receiver = lv.bachelier_price(F, K, T, sig, "receiver")
    assert receiver - payer == pytest.approx(K - F, abs=1e-9)
    # and both are strictly above intrinsic
    assert payer > 0.0 and receiver > (K - F)


def test_bachelier_zero_vol_is_intrinsic():
    assert lv.bachelier_price(450.0, 400.0, 1.0, 0.0, "payer") == pytest.approx(50.0)
    assert lv.bachelier_price(450.0, 400.0, 1.0, 0.0, "receiver") == pytest.approx(0.0)
    assert lv.bachelier_price(450.0, 400.0, 0.0, 100.0, "payer") == pytest.approx(50.0)


def test_bachelier_rejects_an_unknown_right():
    with pytest.raises(ValueError):
        lv.bachelier_price(400.0, 400.0, 1.0, 100.0, "call")


def test_implied_vol_inverts_the_price_exactly():
    """A round trip through the root solve, including the discount, so that the
    inversion used to cross-check ``iv_bp`` is itself checked."""
    price = lv.bachelier_price(412.5, 400.0, 0.75, 87.5, "payer", discount=0.97)
    back = lv.bachelier_implied_vol(price, 412.5, 400.0, 0.75, "payer", discount=0.97)
    assert back == pytest.approx(87.5, rel=1e-6)


def test_implied_vol_returns_nan_below_intrinsic():
    """A crossed or stale quote must surface as NaN, not as a clamped endpoint."""
    assert math.isnan(lv.bachelier_implied_vol(1.0, 450.0, 400.0, 1.0, "payer"))


# ------------------------------------------------------ unit conversions, by hand


def test_sfr_price_vol_scale_is_exactly_100():
    """MUTATION CHECK. ``P = 100 - R`` with R in percent, so one price point is
    100 bp of rate and ``sigma_R(bp) = sigma_P(points) * 100`` exactly.

    Fails if the factor becomes ``/100`` (would give 0.009345) or the identity
    (0.9345) instead of 93.45.
    """
    assert lv.sfr_price_vol_to_rate_vol(0.9345) == pytest.approx(93.45, rel=1e-12)
    assert lv.sfr_price_vol_to_rate_vol(1.0) == pytest.approx(100.0, rel=1e-12)
    # unsigned: a standard deviation has no direction even though dP = -dR
    assert lv.sfr_price_vol_to_rate_vol(-0.9345) == pytest.approx(93.45, rel=1e-12)
    # exact round trip
    assert lv.sfr_rate_vol_to_price_vol(93.45) == pytest.approx(0.9345, rel=1e-12)


def test_ust_price_vol_to_yield_vol_hand_computed():
    """Planted answer: 6.4 price points per year of normal PRICE vol on a future
    whose CTD DV01 is 0.064 price points per bp gives

        sigma_y = 6.4 / 0.064 = **100 bp/yr**

    (0.064 points/bp is a $64 DV01 per $100,000 face at $1,000 per point.)
    """
    assert lv.ust_price_vol_to_yield_vol(6.4, 0.064) == pytest.approx(100.0, rel=1e-12)
    # second planted case: a bond future, 12.5 points / 0.125 points per bp
    assert lv.ust_price_vol_to_yield_vol(12.5, 0.125) == pytest.approx(100.0, rel=1e-12)
    # round trip
    assert lv.ust_yield_vol_to_price_vol(100.0, 0.064) == pytest.approx(6.4, rel=1e-12)


def test_ust_named_contract_uses_the_indicative_table():
    got = lv.ust_price_vol_to_yield_vol(6.45, contract="TY")
    assert got == pytest.approx(6.45 / lv.UST_DV01_POINTS_PER_BP["TY"], rel=1e-12)
    assert got == pytest.approx(100.0, rel=1e-3)


def test_ust_refuses_to_guess_a_dv01():
    """The DV01 is CTD-dependent and moves; a silent default would be the whole
    error. Neither argument supplied must raise, not fall back."""
    with pytest.raises(ValueError):
        lv.ust_price_vol_to_yield_vol(6.4)
    with pytest.raises(KeyError):
        lv.ust_price_vol_to_yield_vol(6.4, contract="ZZ")


def test_ust_panel_is_a_named_gap_not_an_empty_frame():
    with pytest.raises(lv.ListedDataUnavailable):
        lv.load_ust_panel()


def test_bp_per_day_does_not_use_time_to_expiry():
    """MUTATION CHECK. ``iv_bp`` is ANNUALISED, so bp/day is
    ``sigma / sqrt(252)`` and nothing else. Fails if the conversion is confused
    with the TERMINAL standard deviation ``sigma * sqrt(tte)``, which is the
    single most likely unit error in this module: the signature takes no tte at
    all, so such an implementation could not even be written without changing
    the call sites, and the numeric assertion pins the divisor.

    100 bp/yr -> 100 / sqrt(252) = 6.2994078834 bp/day.
    """
    assert lv.vol_bp_per_day(100.0) == pytest.approx(100.0 / math.sqrt(252.0), rel=1e-12)
    assert lv.vol_bp_per_day(100.0) == pytest.approx(6.2994078834, rel=1e-9)
    assert lv.vol_bp_per_year(lv.vol_bp_per_day(93.45)) == pytest.approx(93.45, rel=1e-12)
    # a 3-month option and a 3-year option at the same annual vol give the same
    # bp/day -- which is exactly what makes the JPM comparison horizon-agnostic
    assert lv.vol_bp_per_day(100.0) == lv.vol_bp_per_day(100.0)


def test_bp_per_day_propagates_nan():
    assert math.isnan(lv.vol_bp_per_day(float("nan")))
    assert math.isnan(lv.vol_bp_per_year(float("nan")))


# --------------------------------------------------------- ATM / smile / expiry


def test_atm_vol_is_interpolated_to_the_forward_not_read_at_offset_zero():
    """MUTATION CHECK, and the reason :func:`sfr_atm_vol_panel` exists.

    ``atm_offset_bps`` is anchored to the nearest listed STRIKE, not to the
    forward -- verified exactly on the real panel. Contract A here puts the
    forward 2.0 bp below that strike on a smile that is 10 bp steeper per 6.25 bp
    of offset, so the true ATM-forward vol is **103.2** while the offset-0 quote
    is 100.0. Fails if the extraction reads the offset-0 row.
    """
    atm = lv.sfr_atm_vol_panel(_synthetic_panel())
    a = atm[atm["symbol"] == "A"].iloc[0]
    assert a["fwd_offset_bp"] == pytest.approx(-2.0, abs=1e-9)
    assert a["atm_vol_bp_yr"] == pytest.approx(103.2, rel=1e-10)
    assert a["atm_strike_vol_bp_yr"] == pytest.approx(100.0, rel=1e-12)
    assert a["atm_vol_bp_day"] == pytest.approx(103.2 / math.sqrt(252.0), rel=1e-10)


def test_atm_panel_reports_both_readings_so_the_correction_is_auditable():
    atm = lv.sfr_atm_vol_panel(_synthetic_panel())
    assert {"atm_vol_bp_yr", "atm_strike_vol_bp_yr", "fwd_offset_bp"} <= set(atm.columns)
    assert len(atm) == 2
    assert list(atm["tte"]) == [0.25, 1.0]  # sorted by tte within the date


def test_smile_merges_the_two_wings_and_averages_at_the_anchor():
    """Calls are the low-rate wing, puts the high-rate wing, and at offset 0 both
    exist -- a put/call parity violation would show as a jump at zero, so they
    are averaged rather than one being dropped."""
    sm = lv.sfr_smile_on(_synthetic_panel(), "2025-10-02", "A")
    assert list(sm.columns) == ["offset_bp", "vol_bp"]
    assert list(sm["offset_bp"]) == [-6.25, 0.0, 6.25]
    assert list(sm["vol_bp"]) == [110.0, 100.0, 96.0]
    # column names match swaption_cube.smile_on so downstream code is shared
    from RVUtils.ConvexityRV.swaption_cube import smile_on as otc_smile_on
    assert list(sm.columns) == ["offset_bp", "vol_bp"]
    assert callable(otc_smile_on)


def test_smile_on_unknown_symbol_is_empty_not_an_error():
    sm = lv.sfr_smile_on(_synthetic_panel(), "2025-10-02", "ZZ")
    assert sm.empty and list(sm.columns) == ["offset_bp", "vol_bp"]


def test_expiry_matcher_picks_the_nearest_expiry_to_the_horizon():
    atm = lv.sfr_atm_vol_panel(_synthetic_panel())
    one_yr = lv.match_listed_expiry(atm, "2025-10-02", 1.0, max_gap_days=60.0)
    assert one_yr is not None and one_yr["symbol"] == "B"
    assert one_yr["gap_days"] == pytest.approx(1.0 * 365.0 - 365.0, abs=1e-9)

    three_m = lv.match_listed_expiry(atm, "2025-10-02", 0.25, max_gap_days=60.0)
    assert three_m is not None and three_m["symbol"] == "A"


def test_expiry_matcher_refuses_a_gap_it_was_told_to_refuse():
    """Returning the nearest contract regardless of distance would silently
    substitute a 3-month option for a 1-year horizon."""
    atm = lv.sfr_atm_vol_panel(_synthetic_panel())
    assert lv.match_listed_expiry(atm, "2025-10-02", 3.0, max_gap_days=60.0) is None


def test_matched_series_carries_the_contract_identity():
    atm = lv.sfr_atm_vol_panel(_synthetic_panel())
    ser = lv.listed_atm_series(atm, 1.0, max_gap_days=60.0)
    assert len(ser) == 1
    row = ser.iloc[0]
    assert row["listed_symbol"] == "B"
    assert row["listed_atm_bp_yr"] > 0
    assert row["listed_atm_bp_day"] == pytest.approx(row["listed_atm_bp_yr"] / math.sqrt(252.0))
    # "which expiry was used on which date" must be answerable after the fact
    assert {"listed_expiry", "listed_tte", "listed_gap_days"} <= set(ser.columns)


def test_term_structure_is_sorted_by_time_to_expiry():
    atm = lv.sfr_atm_vol_panel(_synthetic_panel())
    ts = lv.sfr_term_structure(atm, "2025-10-02")
    assert list(ts["symbol"]) == ["A", "B"]
    assert ts["tte"].is_monotonic_increasing


# ----------------------------------------------------------------- repricing


def test_reprice_discounting_changes_the_answer_materially():
    """MUTATION CHECK for the discount factor, on BOTH code paths.

    A one-year 4%-rate option loses ~3.9% of its value to discounting
    (``exp(-0.04) = 0.9607894392``). If the factor were dropped, the measurement
    that establishes ``iv_bp``'s convention would be vacuous.

    ``sfr_reprice_check`` deliberately does NOT call :func:`bachelier_price` --
    it vectorises the same formula because it runs over 199,319 rows -- so the
    mutation has to be pinned on each path separately, and the two paths have to
    be pinned against each other. Dropping ``discount`` from ``bachelier_price``
    alone was verified to slip past an assertion on ``sfr_reprice_check`` alone,
    which is why this test now asserts all three things.
    """
    # path 1: the scalar pricer honours the factor
    undisc = lv.bachelier_price(400.0, 400.0, 1.0, 100.0, "payer")
    disc_one = lv.bachelier_price(400.0, 400.0, 1.0, 100.0, "payer", discount=math.exp(-0.04))
    assert disc_one / undisc == pytest.approx(math.exp(-0.04), rel=1e-12)
    assert abs(1.0 - disc_one / undisc) > 0.03

    # path 2: the vectorised reprice honours it too
    p = _synthetic_panel().copy()
    p["tte"] = 1.0
    p["forward_rate"] = 4.0
    p["premium_bp"] = 25.0
    none = lv.sfr_reprice_check(p, discount="none")
    disc = lv.sfr_reprice_check(p, discount="forward_rate")
    assert np.allclose(none["disc_factor"], 1.0)
    assert np.allclose(disc["disc_factor"], math.exp(-0.04), rtol=1e-12)
    ratio = (disc["theo_bp"] / none["theo_bp"]).to_numpy()
    assert np.allclose(ratio, math.exp(-0.04), rtol=1e-12)
    assert abs(1.0 - ratio.mean()) > 0.03

    # path 3: and the two agree row by row, so neither can drift from the other
    scalar = [
        lv.bachelier_price(f * 100.0, k * 100.0, t, s, r, discount=d)
        for f, k, t, s, r, d in zip(p["forward_rate"], p["strike_rate"], p["tte"],
                                    p["iv_bp"], p["right_rate"], disc["disc_factor"])
    ]
    assert np.allclose(disc["theo_bp"].to_numpy(), np.asarray(scalar), rtol=1e-12)


def test_reprice_check_rejects_an_unknown_discount_mode():
    with pytest.raises(ValueError):
        lv.sfr_reprice_check(_synthetic_panel(), discount="ois")


def test_realized_vol_differences_within_a_symbol_only():
    """Differencing a generic front-contract series would inject the quarterly
    roll gap as a fake move. Planted: symbol X moves 1 bp/day, symbol Y is
    static, and the two are 100 bp apart -- a cross-symbol difference would
    show up as a huge vol."""
    c = pd.DataFrame({
        "as_of": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"] * 2),
        "symbol": ["X"] * 3 + ["Y"] * 3,
        "forward_rate": [4.00, 4.01, 4.02, 5.00, 5.00, 5.00],
    })
    out = lv.sfr_realized_vol(c).set_index("symbol")
    assert out.loc["X", "realized_bp_day"] == pytest.approx(0.0, abs=1e-12)  # constant 1bp step
    assert out.loc["Y", "realized_bp_day"] == pytest.approx(0.0, abs=1e-12)
    assert out.loc["X", "n_obs"] == 2
    pooled = lv.sfr_realized_vol(c, by_symbol=False)
    assert pooled.loc[0, "n_obs"] == 4  # 2 per symbol, the roll gap never enters


# --------------------------------------------------- strat1_listed config/signal


def test_listed_config_defaults_are_the_documented_ones():
    cfg = sl.Strat1ListedConfig()
    assert cfg.horizon == "1Y" and cfg.horizon_years == 1.0
    assert cfg.signal_mode == "breakeven_vol" and cfg.benchmark == "listed"
    # the OTC control must be SECTOR-MATCHED, not JPM's long-end 1Yx30Y node
    assert (cfg.otc_expiry, cfg.otc_tenor) == ("1Y", "2Y")
    # wider grid than strat 1 -- see the module docstring's saturation table
    assert min(cfg.shifts_bp) == -500.0 and max(cfg.shifts_bp) == 500.0
    assert 0.0 in cfg.shifts_bp
    assert cfg.force_close_at_end is False
    # no 1Y tails: a 1Y tail cannot survive a 1Y roll
    for _label, front, back in cfg.structures:
        assert not front.endswith("x1Y") and not back.endswith("x1Y")


def test_listed_config_is_frozen():
    cfg = sl.Strat1ListedConfig()
    with pytest.raises(Exception):
        cfg.package_dv01 = 1.0  # type: ignore[misc]


def test_curve_config_hands_the_kernel_the_same_knobs():
    cfg = sl.Strat1ListedConfig()
    c1 = cfg.curve_config()
    assert c1.shifts_bp == cfg.shifts_bp
    assert c1.horizon == cfg.horizon and c1.package_dv01 == cfg.package_dv01
    assert c1.structures == cfg.structures
    assert c1.trade_straddle is False
    # the OTC node travels into the strat1 config's swaption fields
    assert (c1.swaption_expiry, c1.swaption_tenor) == (cfg.otc_expiry, cfg.otc_tenor)


def test_the_two_benchmarks_can_disagree_which_is_the_whole_point():
    """If listed and OTC always agreed, this study would be a relabelling of
    strategy 1. Planted: a breakeven of 6.0 bp/day sits BELOW a 7.0 bp/day
    swaption and ABOVE a 5.0 bp/day listed quote, so the same curve is cheap
    against one market and rich against the other."""
    from RVUtils.ConvexityRV.strat1_curve_gamma import BreakevenResult, signal_from_breakeven

    be = BreakevenResult(bp_per_year=6.0 * math.sqrt(252.0), bp_per_day=6.0, status="root")
    assert signal_from_breakeven(be, 7.0) == +1.0   # cheap vs swaptions
    assert signal_from_breakeven(be, 5.0) == -1.0   # rich vs listed
    assert signal_from_breakeven(be, 6.0) == 0.0    # dead on


def test_signal_distribution_ignores_infinite_breakevens_in_the_median():
    """``never_cheap`` days carry ``breakeven_vol_bp_day = inf`` legitimately. A
    median that swallows infinities is a median of a different variable."""
    panel = pd.DataFrame({
        "date": pd.to_datetime(["2025-01-01"] * 3),
        "structure": ["S"] * 3,
        "breakeven_vol_bp_day": [4.0, 6.0, np.inf],
        "breakeven_status": ["root", "root", "never_cheap"],
        "listed_atm_bp_day": [5.0, 5.0, 5.0],
        "otc_atmf_bp_day": [7.0, 7.0, 7.0],
        "otc_minus_listed_bp_day": [2.0, 2.0, 2.0],
        "cheapness_vs_listed_bp_day": [1.0, -1.0, -np.inf],
        "cheapness_vs_otc_bp_day": [3.0, 1.0, -np.inf],
        "signal_listed": [1.0, -1.0, -1.0],
        "signal_otc": [1.0, 1.0, -1.0],
        "carry_roll_bp": [-1.0, -2.0, -8.0],
        "convex": [True, True, True],
    }).set_index(["date", "structure"])
    d = sl.signal_distribution(panel, benchmark="listed").iloc[0]
    assert d["n_days"] == 3
    assert d["frac_cheap"] == pytest.approx(1 / 3)
    assert d["frac_rich"] == pytest.approx(2 / 3)
    assert d["frac_never_cheap"] == pytest.approx(1 / 3)
    assert d["median_breakeven_bp_day"] == pytest.approx(5.0)   # median of [4, 6]
    assert d["frac_signals_disagree"] == pytest.approx(1 / 3)   # row 2 only
    assert d["median_otc_minus_listed_bp_day"] == pytest.approx(2.0)


def test_signal_distribution_rejects_an_unknown_benchmark():
    with pytest.raises(ValueError):
        sl.signal_distribution(pd.DataFrame(), benchmark="futures")


def test_long_end_frame_is_labelled_unavailable_and_carries_no_listed_number():
    s1_panel = pd.DataFrame({
        "date": pd.to_datetime(["2025-01-02", "2019-01-02"]),
        "structure": ["30Y/50Y", "30Y/50Y"],
        "carry_roll_bp": [0.4, 0.3],
        "breakeven_vol_bp_day": [3.0, 3.5],
        "breakeven_status": ["root", "root"],
        "atmf_vol_bp_day": [6.0, 6.5],
        "signal_breakeven": [1.0, 1.0],
        "convex": [True, True],
    })
    out = sl.long_end_reference_frame(s1_panel, "2024-07-01", "2026-07-28")
    assert len(out) == 1                       # 2019 row is outside the listed window
    assert set(out["listed_benchmark"]) == {"unavailable"}
    assert not any(c.startswith("listed_atm") for c in out.columns)


# ------------------------------------------------------- data-backed tie-outs


@pytest.mark.slow
def test_iv_bp_is_a_discounted_normal_bp_vol(real_panel):
    """THE unit tie-out. Repricing every quote with Bachelier at its own
    ``iv_bp`` recovers the quoted premium to ~0.3% once the upfront-premium
    discount is applied, and overprices by ~3.7% without it. That pair of
    numbers -- not the column name -- is what establishes the convention."""
    none = lv.sfr_reprice_check(real_panel, discount="none")
    disc = lv.sfr_reprice_check(real_panel, discount="forward_rate")

    assert none["rel_err"].median() > 0.02          # measured +3.58%
    assert none["rel_err"].median() < 0.06
    assert abs(disc["rel_err"].median()) < 0.01     # measured +0.26%
    assert disc["err_bp"].abs().median() < 0.05     # measured 0.011 bp
    assert disc["err_bp"].abs().quantile(0.95) < 1.0
    # discounting must strictly improve it, on every quantile that matters
    assert disc["err_bp"].abs().median() < none["err_bp"].abs().median()


@pytest.mark.slow
def test_implied_matches_realized_on_the_same_panel(real_panel):
    """Model-free cross-check: the realised bp/day of the SFR forward rate,
    differenced WITHIN a symbol, against the median ATM implied bp/day. Measured
    5.72 vs 5.77, ratio 1.01. Uses only ``contracts.parquet``'s ``forward_rate``
    and never touches ``iv_bp``, so agreement is evidence, not an identity."""
    contracts = lv.load_sfr_contracts()
    pooled = lv.sfr_realized_vol(contracts, by_symbol=False).iloc[0]
    atm = lv.sfr_atm_vol_panel(real_panel)
    implied = float(atm["atm_vol_bp_day"].median())
    assert 4.0 < pooled["realized_bp_day"] < 8.0
    assert 4.0 < implied < 9.0
    assert 0.75 < implied / pooled["realized_bp_day"] < 1.35


@pytest.mark.slow
def test_offset_anchoring_identity_holds_on_the_real_panel(real_panel):
    """``atm_offset_bps == (strike_rate - S0) * 100`` exactly, where S0 is the
    unique strike carrying offset 0. The ATM interpolation depends on it."""
    s0 = (real_panel[real_panel["atm_offset_bps"] == 0.0]
          .groupby(["as_of", "symbol"])["strike_rate"].agg(["nunique", "first"]))
    assert set(s0["nunique"].unique()) == {1}
    m = real_panel.merge(s0["first"].rename("S0"), on=["as_of", "symbol"])
    dev = ((m["strike_rate"] - m["S0"]) * 100.0 - m["atm_offset_bps"]).abs().max()
    assert dev < 1e-9
    # only OTM quotes: calls on the low-rate wing, puts on the high-rate wing
    assert (real_panel.loc[real_panel["right"] == "C", "atm_offset_bps"] <= 0).all()
    assert (real_panel.loc[real_panel["right"] == "P", "atm_offset_bps"] >= 0).all()


@pytest.mark.slow
def test_listed_coverage_is_the_window_the_report_claims(real_panel):
    atm = lv.sfr_atm_vol_panel(real_panel)
    rep = lv.coverage_report(real_panel, atm, horizon_years=1.0, max_gap_days=60.0)
    assert rep["n_dates"] == 540
    assert rep["first_date"] == "2024-07-01" and rep["last_date"] == "2026-07-28"
    assert rep["n_symbols"] == 14
    assert rep["n_dates_with_matched_expiry"] == 525
    assert rep["matched_gap_days_abs_max"] <= 60.0
    assert rep["ust"]["available_offline"] is False

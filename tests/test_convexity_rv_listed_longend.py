"""Known-answer tests for the UST LONG-END leg of strategy 1-listed.

The thing under test is a benchmark substitution: strategy 1 found its long-end
flatteners cheap against 1Yx30Y swaptions on ~100% of days, and this code asks
whether that survives an exchange-listed benchmark. Almost every way that answer
could be wrong is a **units or a join** error rather than a modelling one, so
that is where the tests concentrate.

Three tiers, so the fast gate stays fast:

* **Hand-computed** (no I/O). The bond maths, the label parse, the
  price-vol/yield-vol identity and the annual->daily bridge all have answers
  worked out on paper rather than produced by the code under test.
* **Synthetic panel** (no I/O). Panels built with planted values whose every
  downstream number is known in closed form -- the sector map, the term
  structure, the two units checks, the long-end signal panel and all four
  reporting functions.
* **Data-backed** (``@pytest.mark.slow``, skipped when the artifacts are
  absent). The real 58,176-row panel and the real CTD store, asserting the
  thresholds the notebook's verdict rests on.

**Verifying the checker itself.** Nine tests below are explicit MUTATION checks:
each is written to fail under one specific plausible wrong implementation, and
each names that mutation in its docstring. Every one was run against the mutated
module and confirmed to fail before being committed:

``test_bp_day_bridge_is_divide_by_sqrt_252``
    fails if ``/sqrt(252)`` becomes ``*sqrt(252)`` or the identity.
``test_atm_rows_get_no_bp_day``
    fails if ``value_bp_day`` is computed for ATM rows too -- a lognormal price
    vol divided by sqrt(252) looks like a bp/day vol and is not one.
``test_implied_duration_uses_atm_over_abpv_not_the_reverse``
    fails if the ratio in the price-free identity is inverted.
``test_sector_map_primary_for_30y50y_is_ultra_bond``
    fails if the map is rebuilt from contract NAMES instead of measured CTD.
``test_control_root_is_a_different_series``
    fails if the control root silently resolves to the primary.
``test_root_alias_folding_is_applied``
    fails if WN/ZB/UXY aliases stop folding onto the panel's globex keys.
``test_longend_panel_join_is_on_date_and_not_positional``
    fails if the listed series is attached by position rather than by date.
``test_signal_respects_never_cheap_branch``
    fails if the breakeven status is dropped and ``inf``/``0.0`` are compared
    numerically instead.
``test_longend_shift_grid_is_strat1s_not_the_wide_one``
    fails if the long-end mode is pointed at ``WIDE_SHIFTS_BP``, which would make
    the reused curve panel and a rebuilt one disagree.

The SFR leg is asserted UNCHANGED at the bottom of this file: ``strat1_threeway``
depends on it, and this work must not have moved it.
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

SQ252 = math.sqrt(252.0)

_DATA = pathlib.Path(__file__).resolve().parents[1] / "notebooks" / "data" / "convexity_rv"
_UST_PANEL = _DATA / "ust_listed_vol.parquet"
_S1_PANEL = _DATA / "strat1_signal_panel.parquet"


# =============================================================================
#  fixtures -- synthetic panels with planted, hand-computable numbers
# =============================================================================


def _ust_panel(n_days: int = 40) -> pd.DataFrame:
    """A CM panel whose every derived number is known in closed form.

    Planted so the arithmetic is trivial:

    * ``UL``: ABPV 80 bp/yr flat -> 80/sqrt(252) bp/day. ATM chosen as
      ``80 * 16 / 1e4 = 0.128`` so the implied duration is EXACTLY 16.0 years.
    * ``US``: ABPV 90 -> ATM ``90 * 12 / 1e4 = 0.108`` -> duration exactly 12.0.
    * ``TY``: ABPV 100 -> ATM ``100 * 6 / 1e4 = 0.06`` -> duration exactly 6.0.

    The 60 and 90-day tenors add exactly +2 and +4 bp to ABPV (and the matching
    ATM), so the 30->90 slope is exactly +4 bp for every root and the implied
    duration stays exactly flat across constant maturity.
    """
    dates = pd.bdate_range("2020-01-01", periods=n_days)
    rows = []
    for root, abpv30, dur in (("UL", 80.0, 16.0), ("US", 90.0, 12.0), ("TY", 100.0, 6.0)):
        for cm, bump in ((30, 0.0), (60, 2.0), (90, 4.0)):
            v = abpv30 + bump
            for d in dates:
                rows.append({"date": d, "symbol": f"{root}_{cm}", "root": root,
                             "cm_days": cm, "value_type": "ABPV", "value": v})
                rows.append({"date": d, "symbol": f"{root}_{cm}", "root": root,
                             "cm_days": cm, "value_type": "ATM", "value": v * dur / 1e4})
    return pd.DataFrame(rows)


def _load_synthetic(tmp_path: pathlib.Path, panel: pd.DataFrame) -> pd.DataFrame:
    """Round-trip a synthetic panel through the real loader."""
    p = tmp_path / "ust.parquet"
    panel.to_parquet(p, index=False)
    return lv.load_ust_cm_panel(p)


#: The planted breakeven of the ``root``-status structure, bp/day. Chosen to sit
#: BETWEEN the fixture's primary and control benchmarks for a UL-mapped
#: structure: UL_30 is 80/sqrt(252) = 5.0395 and TY_30 is 100/sqrt(252) = 6.2994,
#: so 5.5 is RICH against the sector-matched primary and CHEAP against the
#: deliberately-mismatched control. Any test that cannot tell those two apart is
#: not testing the sector map.
ROOT_BE_BP_DAY = 5.5


def _s1_panel(n_days: int = 40) -> pd.DataFrame:
    """A stored-strat1-shaped panel with one structure per breakeven branch.

    * ``30Y/50Y`` -- ``always_cheap`` (breakeven 0.0). Maps to UL / US / TY.
    * ``5Y/30Y`` -- ``never_cheap`` (breakeven +inf). Maps to US / UL / TY.
    * ``20Yx5Y/25Yx5Y`` -- a real ``root`` at :data:`ROOT_BE_BP_DAY`. Maps to
      UL / US / TY, and straddles them, which is what makes the benchmark-
      discrimination tests able to fail.

    ``10Yx10Y/20Yx10Y`` is deliberately NOT used: its alt root is TN, which the
    synthetic vol fixture does not carry, and a fixture that silently dropped a
    benchmark would weaken every count assertion below.
    """
    dates = pd.bdate_range("2020-01-01", periods=n_days)
    rows = []
    for d in dates:
        for label, be, status in (("30Y/50Y", 0.0, "always_cheap"),
                                  ("5Y/30Y", float("inf"), "never_cheap"),
                                  ("20Yx5Y/25Yx5Y", ROOT_BE_BP_DAY, "root")):
            rows.append({
                "date": d, "structure": label,
                "carry_roll_bp": 1.25,
                "breakeven_vol_bp_yr": be * SQ252,
                "breakeven_vol_bp_day": be,
                "breakeven_status": status,
                "atmf_vol_bp_yr": 95.0,
                "atmf_vol_bp_day": 95.0 / SQ252,
                "convex": True,
                **{f"payoff_bp_{int(s):+d}": float(s) ** 2 / 1000.0
                   for s in sl.LONGEND_SHIFTS_BP},
            })
    return pd.DataFrame(rows)


@pytest.fixture()
def ust(tmp_path):
    return _load_synthetic(tmp_path, _ust_panel())


@pytest.fixture()
def cfg():
    return sl.Strat1ListedConfig(
        longend_structures=(("30Y/50Y", "30Y", "50Y"),
                            ("20Yx5Y/25Yx5Y", "20Yx5Y", "25Yx5Y"),
                            ("5Y/30Y", "5Y", "30Y")),
        longend_start=datetime.date(2019, 1, 1),
        longend_end=datetime.date(2027, 1, 1),
    )


# =============================================================================
#  1. hand-computed bond maths -- the foundation of the DV01 units check
# =============================================================================


def test_par_bond_duration_matches_the_closed_form():
    """A 10y 4% semiannual bond at 4% prices at par with modified duration 8.1757.

    Closed form for a par bond: ``D_mac = (1+y/m)/y * (1 - (1+y/m)^-mn)``, i.e.
    ``1.02/0.04 * (1 - 1.02^-20) = 8.33933`` years Macaulay, ``/1.02 = 8.17572``
    modified. Computed on paper, not by this module.
    """
    dirty, clean, mod = lv.bond_price_and_duration(
        4.0, datetime.date(2030, 1, 15), datetime.date(2020, 1, 15), 4.0)
    assert clean == pytest.approx(100.0, abs=1e-9)
    assert dirty == pytest.approx(100.0, abs=1e-9)   # settles on a coupon date
    mac = mod * 1.02
    assert mac == pytest.approx(8.339231, abs=1e-5)
    assert mod == pytest.approx(8.175714, abs=1e-5)


def test_zero_coupon_duration_equals_its_maturity():
    """With no coupons, Macaulay duration IS the time to maturity.

    A 0% 5-year bond has Macaulay 5.0 exactly, so modified = 5/(1+y/2). At a 6%
    yield that is 5/1.03 = 4.854369 years. Independent of any price level.
    """
    _, _, mod = lv.bond_price_and_duration(
        0.0, datetime.date(2025, 1, 15), datetime.date(2020, 1, 15), 6.0)
    assert mod == pytest.approx(5.0 / 1.03, abs=1e-6)


def test_duration_falls_as_yield_rises():
    """Elementary monotonicity -- a sanity net under the maturity-day resolver."""
    args = (5.0, datetime.date(2045, 5, 15), datetime.date(2020, 5, 15))
    _, _, lo = lv.bond_price_and_duration(*args, 2.0)
    _, _, hi = lv.bond_price_and_duration(*args, 8.0)
    assert lo > hi > 0


def test_matured_bond_returns_nan_rather_than_a_number():
    """A settlement past maturity must not silently produce a duration."""
    d, c, m = lv.bond_price_and_duration(
        3.0, datetime.date(2019, 1, 15), datetime.date(2020, 1, 15), 3.0)
    assert np.isnan(d) and np.isnan(c) and np.isnan(m)


@pytest.mark.parametrize("label,expect", [
    ("T 4 1/2 Aug 39", (4.5, 8, 2039)),
    ("T 2 Nov 22", (2.0, 11, 2022)),
    ("T 7/8 Feb 27", (0.875, 2, 2027)),
    ("T 3 3/4 Nov 43", (3.75, 11, 2043)),
])
def test_treasury_label_parse(label, expect):
    assert lv.parse_treasury_label(label) == expect


@pytest.mark.parametrize("bad", ["", "X 4 1/2 Aug 39", "T 4 Foo 39", "T 4"])
def test_treasury_label_parse_raises_rather_than_guessing(bad):
    """A silent default here would corrupt every duration downstream."""
    with pytest.raises(ValueError):
        lv.parse_treasury_label(bad)


# =============================================================================
#  2. hand-computed unit conversions
# =============================================================================


def test_abpv_from_price_vol_is_hand_computed():
    """``ATM * P / FV01``: 0.10 x 120 = 12 points, / 0.12 = exactly 100 bp/yr."""
    assert lv.ust_abpv_from_price_vol(0.10, 120.0, 0.12) == 100.0
    assert lv.ust_abpv_from_price_vol(0.14, 150.0, 0.25) == pytest.approx(84.0, abs=1e-12)
    assert lv.ust_abpv_from_price_vol(0.20, 100.0, 0.10) == 200.0


def test_abpv_from_price_vol_refuses_a_non_positive_dv01():
    assert np.isnan(lv.ust_abpv_from_price_vol(0.1, 120.0, 0.0))
    assert np.isnan(lv.ust_abpv_from_price_vol(0.1, 120.0, -0.12))
    assert np.isnan(lv.ust_abpv_from_price_vol(float("nan"), 120.0, 0.12))


def test_bp_day_bridge_is_divide_by_sqrt_252(ust):
    """MUTATION: fails if ``/sqrt(252)`` becomes ``*sqrt(252)``, or the identity.

    The whole comparison is made in bp/day, and an inverted bridge would move
    every benchmark by a factor of 252 -- which is large enough to be obvious in
    a plot and small enough to survive a sloppy assertion like ``> 0``. Pinned
    to a hand-computed value: 80 / sqrt(252) = 5.03953 bp/day.
    """
    s = lv.ust_listed_atm_series(ust, "UL", 30)
    assert s["listed_atm_bp_yr"].iloc[0] == pytest.approx(80.0)
    assert s["listed_atm_bp_day"].iloc[0] == pytest.approx(80.0 / SQ252, rel=1e-12)
    assert s["listed_atm_bp_day"].iloc[0] == pytest.approx(5.039526, abs=1e-6)
    assert s["listed_atm_bp_day"].iloc[0] < s["listed_atm_bp_yr"].iloc[0]


def test_atm_rows_get_no_bp_day(ust):
    """MUTATION: fails if ``value_bp_day`` is filled for ATM rows too.

    ``ATM`` is a LOGNORMAL PRICE vol. Dividing it by sqrt(252) yields a number
    that renders happily in a bp/day column and means nothing. The loader must
    leave it NaN, so the mistake is impossible rather than merely discouraged.
    """
    abpv = ust[ust.value_type == "ABPV"]
    atm = ust[ust.value_type == "ATM"]
    assert abpv["value_bp_day"].notna().all()
    assert atm["value_bp_day"].isna().all()
    assert abpv["value_bp_day"].iloc[0] == pytest.approx(abpv["value"].iloc[0] / SQ252)


def test_root_alias_folding_is_applied(tmp_path):
    """MUTATION: fails if WN/ZB/UXY stop folding onto the panel's globex keys.

    The basis store files the Ultra Bond under ``WN`` and the CM panel under
    ``UL``; ``UXY`` and ``TN`` are the same contract. Without folding, a caller
    asking for ``WN`` gets an empty frame and reports "0 days of coverage" as if
    it were a measurement.
    """
    raw = _ust_panel(5)
    raw["root"] = raw["root"].replace({"UL": "WN", "US": "ZB"})
    raw["symbol"] = raw["symbol"].str.replace("UL_", "WN_").str.replace("US_", "ZB_")
    panel = lv.load_ust_cm_panel(_write(tmp_path, raw))
    assert set(panel["root"]) == {"UL", "US", "TY"}
    for alias, canonical in (("WN", "UL"), ("ZB", "US"), ("UXY", "TN"), ("ZN", "TY")):
        assert lv.UST_ROOT_ALIAS[alias] == canonical
    assert len(lv.ust_cm_series(panel, "WN", 30)) == 5
    assert len(lv.ust_cm_series(panel, "UL", 30)) == 5


def _write(tmp_path: pathlib.Path, df: pd.DataFrame) -> pathlib.Path:
    p = tmp_path / "ust.parquet"
    df.to_parquet(p, index=False)
    return p


def test_loader_raises_on_a_missing_panel(tmp_path):
    """A named failure, not an empty frame -- the repo's standing rule."""
    with pytest.raises(lv.ListedDataUnavailable):
        lv.load_ust_cm_panel(tmp_path / "nope.parquet")


# =============================================================================
#  3. the units checks themselves, on planted data
# =============================================================================


def test_implied_duration_is_exact_on_planted_data(ust):
    """``1e4 * ATM / ABPV`` must return the duration the fixture planted."""
    out = lv.ust_implied_ctd_duration(ust).set_index("root")
    assert out.loc["UL", "implied_mod_duration"] == pytest.approx(16.0, rel=1e-12)
    assert out.loc["US", "implied_mod_duration"] == pytest.approx(12.0, rel=1e-12)
    assert out.loc["TY", "implied_mod_duration"] == pytest.approx(6.0, rel=1e-12)
    assert out["std"].to_numpy() == pytest.approx(0.0, abs=1e-12)


def test_implied_duration_uses_atm_over_abpv_not_the_reverse(ust):
    """MUTATION: fails if the ratio is inverted to ``1e4 * ABPV / ATM``.

    An inverted identity still returns a positive, stable, CM-invariant number,
    so it survives every structural assertion; only the VALUE catches it. The
    inverted answer for UL would be 1e4*80/0.128 = 6,250,000, not 16.
    """
    out = lv.ust_implied_ctd_duration(ust).set_index("root")
    assert out.loc["UL", "implied_mod_duration"] == pytest.approx(16.0, rel=1e-12)
    assert out.loc["UL", "implied_mod_duration"] < 100.0
    # and the ordering must follow the sector, not reverse it
    assert (out.loc["UL", "implied_mod_duration"]
            > out.loc["US", "implied_mod_duration"]
            > out.loc["TY", "implied_mod_duration"])


def test_implied_duration_does_not_depend_on_constant_maturity(ust):
    """Duration is a property of the BOND, so it cannot move with the option."""
    w = lv.ust_implied_ctd_duration(ust, by_cm=True).pivot(
        index="root", columns="cm_days", values="implied_mod_duration")
    assert (w.max(axis=1) - w.min(axis=1)).max() == pytest.approx(0.0, abs=1e-9)


def test_implied_duration_requires_both_value_types(ust):
    with pytest.raises(ValueError):
        lv.ust_implied_ctd_duration(ust[ust.value_type == "ABPV"])


def test_dv01_units_check_is_exact_when_the_inputs_are_consistent(ust):
    """With FV01 built from the same planted duration, implied/actual must be 1.

    ``FV01 = ModDur * P / 1e4`` and ``ABPV_implied = ATM * P / FV01``, so the
    price cancels and the ratio is exactly 1 for any price. The fixture uses
    P = 137.5 to prove the cancellation rather than assume it.
    """
    dates = sorted(ust["date"].unique())
    ctd = pd.DataFrame([
        {"root": r, "date": d, "futures_price": 137.5,
         "ctd_mod_duration": dur,
         "fv01_points_per_bp": dur * 137.5 / 1e4,
         "label": "T 3 Aug 45", "price_err_pts": 0.001}
        for r, dur in (("UL", 16.0), ("US", 12.0), ("TY", 6.0)) for d in dates])
    out = lv.ust_units_check_dv01(ust, ctd, cm_days=30).set_index("root")
    assert out["ratio"].to_numpy() == pytest.approx(1.0, rel=1e-12)
    assert out.loc["UL", "ctd_mod_duration_implied"] == pytest.approx(16.0, rel=1e-12)
    assert out.loc["UL", "ctd_mod_duration_measured"] == pytest.approx(16.0, rel=1e-12)


def test_dv01_units_check_detects_a_scaled_panel(ust):
    """A panel whose ABPV is 10x too large must NOT pass with ratio ~1.

    This is the failure the check exists to catch, so it is asserted directly
    rather than inferred from the happy path passing.
    """
    bad = ust.copy()
    bad.loc[bad.value_type == "ABPV", "value"] *= 10.0
    dates = sorted(bad["date"].unique())
    ctd = pd.DataFrame([
        {"root": r, "date": d, "futures_price": 120.0, "ctd_mod_duration": dur,
         "fv01_points_per_bp": dur * 120.0 / 1e4, "label": "T 3 Aug 45",
         "price_err_pts": 0.001}
        for r, dur in (("UL", 16.0), ("US", 12.0), ("TY", 6.0)) for d in dates])
    out = lv.ust_units_check_dv01(bad, ctd, cm_days=30)
    assert (out["ratio"] < 0.2).all()


def test_dv01_units_check_raises_on_no_overlap(ust):
    ctd = pd.DataFrame([{"root": "UL", "date": pd.Timestamp("1999-01-04"),
                         "futures_price": 120.0, "ctd_mod_duration": 16.0,
                         "fv01_points_per_bp": 0.192, "label": "x",
                         "price_err_pts": 0.0}])
    with pytest.raises(ValueError):
        lv.ust_units_check_dv01(ust, ctd, cm_days=30)


def test_swaption_units_check_recovers_a_planted_ratio(ust):
    """Listed at 80, OTC at 64 -> ratio exactly 1.25 and correlation exactly 1."""
    dates = sorted(ust["date"].unique())
    otc = pd.DataFrame([{"date": d, "expiry": "1M", "tenor": "30Y",
                         "offset_bp": 0.0, "vol_bp": 64.0} for d in dates])
    out = lv.ust_units_check_vs_swaptions(ust, otc, [("UL", 30, "1M", "30Y")])
    row = out.iloc[0]
    assert row["n"] == len(dates)
    assert row["ratio"] == pytest.approx(1.25, rel=1e-12)
    assert row["median_listed_bp_day"] == pytest.approx(80.0 / SQ252, rel=1e-12)
    assert row["mean_diff_bp_yr"] == pytest.approx(16.0, rel=1e-12)


def test_term_structure_slope_is_the_planted_one(ust):
    """The fixture plants +4 bp from 30 to 90 days for every root."""
    ts = lv.ust_cm_term_structure(ust).set_index("root")
    assert ts["slope_90_30"].to_numpy() == pytest.approx(4.0, rel=1e-12)
    assert ts.loc["UL", "slope_90_30_pct"] == pytest.approx(100.0 * 4.0 / 80.0, rel=1e-12)
    assert ts.loc["UL", "slope_90_30_bp_day"] == pytest.approx(4.0 / SQ252, rel=1e-12)
    assert ts.loc["UL", "median_30_bp_day"] == pytest.approx(80.0 / SQ252, rel=1e-12)


# =============================================================================
#  4. the sector map
# =============================================================================


def test_sector_map_primary_for_30y50y_is_ultra_bond():
    """MUTATION: fails if the map is rebuilt from contract NAMES.

    The obvious-looking map sends 30Y/50Y to ``US`` because that contract is
    called "30-year bond". Its CTD has a median 15.9 years left; the Ultra
    Bond's has 25.6. Getting this backwards is a silent sector error that no
    downstream number would flag.
    """
    b = lv.ust_benchmarks_for("30Y/50Y")
    assert b["primary"] == "UL"
    assert b["alt"] == "US"
    assert lv.UST_CTD_PROFILE["UL"]["ctd_ttm_yrs"] > lv.UST_CTD_PROFILE["US"]["ctd_ttm_yrs"]
    assert lv.UST_CTD_PROFILE["US"]["ctd_ttm_yrs"] < 20.0


def test_every_long_end_structure_has_a_ty_control():
    for label, _, _ in sl.LONG_END_STRUCTURES:
        b = lv.ust_benchmarks_for(label)
        assert b["control"] == "TY"
        assert b["control"] not in (b["primary"], b["alt"])
        assert b["why"]
        assert len(b["roots"]) == 3


def test_ctd_profile_is_monotone_in_maturity_and_duration():
    """A profile table that is not monotone would make the map indefensible."""
    order = ["TU", "FV", "TY", "TN", "US", "UL"]
    ttm = [lv.UST_CTD_PROFILE[r]["ctd_ttm_yrs"] for r in order]
    dur = [lv.UST_CTD_PROFILE[r]["ctd_mod_duration"] for r in order]
    assert ttm == sorted(ttm)
    assert dur == sorted(dur)
    for r in order:
        assert lv.UST_CTD_PROFILE[r]["ctd_mod_duration"] < lv.UST_CTD_PROFILE[r]["ctd_ttm_yrs"]


def test_unknown_structure_raises_rather_than_defaulting():
    with pytest.raises(KeyError):
        lv.ust_benchmarks_for("2Y/5Y")


def test_basis_root_map_covers_every_cm_root():
    for r in lv.UST_CM_ROOTS:
        assert r in lv.UST_BASIS_ROOT
        assert r in lv.UST_CTD_PROFILE
    assert lv.UST_BASIS_ROOT["UL"] == "WN"
    assert lv.UST_BASIS_ROOT["TN"] == "UXY"


# =============================================================================
#  5. the long-end panel
# =============================================================================


def test_longend_panel_shape_and_planted_arithmetic(ust, cfg):
    """Every derived column is checked against a number computed on paper."""
    panel = sl.build_longend_listed_panel(_s1_panel(), ust, cfg)
    df = panel.reset_index()

    # 3 structures x 3 roles x 3 CM tenors x 40 days -- but UL/US/TY are the only
    # roots the fixture carries, and every structure maps into that set.
    assert set(df["structure"]) == {"30Y/50Y", "20Yx5Y/25Yx5Y", "5Y/30Y"}
    assert set(df["listed_cm_days"]) == {30, 60, 90}
    assert set(df["listed_role"]) == {"primary", "alt", "control"}

    row = df[(df.structure == "30Y/50Y") & (df.listed_symbol == "UL_30")].iloc[0]
    assert row["listed_atm_bp_day"] == pytest.approx(80.0 / SQ252, rel=1e-12)
    assert row["otc_atmf_bp_day"] == pytest.approx(95.0 / SQ252, rel=1e-12)
    # always_cheap -> breakeven 0.0, so cheapness == the benchmark itself
    assert row["cheapness_vs_listed_bp_day"] == pytest.approx(80.0 / SQ252, rel=1e-12)
    assert row["otc_minus_listed_bp_day"] == pytest.approx((95.0 - 80.0) / SQ252, rel=1e-12)


def test_longend_panel_join_is_on_date_and_not_positional(ust, cfg):
    """MUTATION: fails if the listed series is attached by position.

    The listed roots have DIFFERENT date coverage in reality (US 1,917 days, UL
    1,662, TN 639). A positional join would look perfect on a fixture where the
    two frames happen to align and would silently shift the whole benchmark on
    real data. Here UL's series is thinned to every other day, so a positional
    join attaches the wrong dates and the planted value stops matching.
    """
    thin = ust.copy()
    keep_dates = sorted(thin["date"].unique())[::2]
    mask = (thin["root"] == "UL") & (~thin["date"].isin(keep_dates))
    thin = thin[~mask]
    # make UL's value vary with the date so a mis-join is detectable
    thin.loc[(thin.root == "UL") & (thin.value_type == "ABPV"), "value"] = (
        80.0 + thin.loc[(thin.root == "UL") & (thin.value_type == "ABPV"), "date"].dt.day)

    panel = sl.build_longend_listed_panel(_s1_panel(), thin, cfg).reset_index()
    ul = panel[panel.listed_symbol == "UL_30"]
    # all three fixture structures carry UL somewhere in their map
    n_ul_structures = sum(1 for lab, _, _ in cfg.longend_structures
                          if "UL" in lv.ust_benchmarks_for(lab)["roots"])
    assert n_ul_structures == 3
    assert len(ul) == len(keep_dates) * n_ul_structures
    for r in ul.itertuples():
        assert r.listed_atm_bp_yr == pytest.approx(80.0 + r.date.day, rel=1e-12)


def test_signal_respects_never_cheap_branch(ust, cfg):
    """MUTATION: fails if ``breakeven_status`` is dropped from the comparison.

    ``5Y/30Y`` is planted ``never_cheap`` (breakeven ``+inf``) and ``30Y/50Y``
    ``always_cheap`` (breakeven ``0.0``), so every signal must be -1 and +1
    respectively.

    At a ZERO entry threshold the status is redundant with the number -- ``inf``
    compares rich and ``0.0`` compares cheap all by themselves -- so that pass
    alone does NOT prove the status branch is used. It is proved by re-running
    with a threshold WIDER than the benchmark itself: ``always_cheap`` must stay
    +1 because carry alone makes the package cheap, whereas a status-blind
    ``0.0 < benchmark - threshold`` would fall into the no-trade band and return
    0. That second assertion is what this mutation check actually turns on, and
    it was confirmed to fail against a build with ``status`` hard-coded.
    """
    panel = sl.build_longend_listed_panel(_s1_panel(), ust, cfg).reset_index()
    never = panel[panel.structure == "5Y/30Y"]
    always = panel[panel.structure == "30Y/50Y"]
    assert (never["signal_listed"] == -1).all()
    assert (never["signal_otc"] == -1).all()
    assert (always["signal_listed"] == 1).all()
    assert (always["signal_otc"] == 1).all()
    assert np.isinf(never["breakeven_vol_bp_day"]).all()
    assert (always["breakeven_vol_bp_day"] == 0.0).all()

    # Threshold 6.0 bp/day exceeds every planted benchmark (UL_30 is 5.0395).
    wide = sl.Strat1ListedConfig(
        longend_structures=cfg.longend_structures,
        longend_start=cfg.longend_start, longend_end=cfg.longend_end,
        entry_threshold_bp_per_day=6.0)
    p2 = sl.build_longend_listed_panel(_s1_panel(), ust, wide).reset_index()
    assert (p2[p2.structure == "30Y/50Y"]["signal_listed"] == 1).all(),         "always_cheap must survive a threshold wider than the benchmark"
    assert (p2[p2.structure == "5Y/30Y"]["signal_listed"] == -1).all()
    # ...and the root-status structure must NOT: it falls into the no-trade band.
    assert (p2[p2.structure == "20Yx5Y/25Yx5Y"]["signal_listed"] == 0).all(),         "a real root inside the band must stand aside — proves the band is live"


def test_control_root_is_a_different_series(ust, cfg):
    """MUTATION: fails if the control silently resolves to the primary.

    The planted benchmarks separate cleanly: UL is 80 bp/yr and TY is 100, so a
    structure whose breakeven is 5.5 bp/day (= 87.3 bp/yr) is RICH against UL and
    CHEAP against TY. If the control collapsed onto the primary the two verdicts
    would agree and this test would fail.
    """
    panel = sl.build_longend_listed_panel(_s1_panel(), ust, cfg).reset_index()
    g = panel[(panel.structure == "20Yx5Y/25Yx5Y") & (panel.listed_cm_days == 30)]
    ul = g[g.listed_root == "UL"]
    ty = g[g.listed_root == "TY"]
    assert len(ul) and len(ty)
    assert (ul["signal_listed"] == -1).all(), "5.5 bp/day breakeven is RICH vs UL's 5.04"
    assert (ty["signal_listed"] == +1).all(), "5.5 bp/day breakeven is CHEAP vs TY's 6.30"


def test_longend_panel_rejects_a_malformed_curve_panel(ust, cfg):
    bad = _s1_panel().drop(columns=["breakeven_status"])
    with pytest.raises(ValueError):
        sl.build_longend_listed_panel(bad, ust, cfg)


def test_longend_panel_window_is_honoured(ust):
    narrow = sl.Strat1ListedConfig(
        longend_structures=(("30Y/50Y", "30Y", "50Y"),),
        longend_start=datetime.date(2020, 1, 1),
        longend_end=datetime.date(2020, 1, 10))
    panel = sl.build_longend_listed_panel(_s1_panel(), ust, narrow).reset_index()
    assert panel["date"].min() >= pd.Timestamp("2020-01-01")
    assert panel["date"].max() <= pd.Timestamp("2020-01-10")


# =============================================================================
#  6. the reporting layer
# =============================================================================


def test_signal_distribution_shares_are_the_planted_ones(ust, cfg):
    panel = sl.build_longend_listed_panel(_s1_panel(), ust, cfg)
    dist = sl.longend_signal_distribution(panel).set_index(["structure", "listed_symbol"])

    assert dist.loc[("30Y/50Y", "UL_30"), "frac_cheap_vs_listed"] == 1.0
    assert dist.loc[("30Y/50Y", "UL_30"), "frac_always_cheap"] == 1.0
    assert dist.loc[("5Y/30Y", "US_30"), "frac_cheap_vs_listed"] == 0.0
    assert dist.loc[("5Y/30Y", "US_30"), "frac_never_cheap"] == 1.0
    # the root-status structure straddles the planted benchmarks: RICH against
    # the sector-matched primary (UL, 5.0395 bp/day) and CHEAP against the
    # mismatched control (TY, 6.2994) and the alt (US, 5.6695).
    assert dist.loc[("20Yx5Y/25Yx5Y", "UL_30"), "frac_cheap_vs_listed"] == 0.0
    assert dist.loc[("20Yx5Y/25Yx5Y", "US_30"), "frac_cheap_vs_listed"] == 1.0
    assert dist.loc[("20Yx5Y/25Yx5Y", "TY_30"), "frac_cheap_vs_listed"] == 1.0
    # the OTC benchmark (95 bp/yr = 5.9845 bp/day) says CHEAP, so listed-vs-OTC
    # disagree on every day for UL and on no day for TY
    assert dist.loc[("20Yx5Y/25Yx5Y", "UL_30"), "frac_signals_disagree"] == 1.0
    assert dist.loc[("20Yx5Y/25Yx5Y", "TY_30"), "frac_signals_disagree"] == 0.0
    assert dist.loc[("30Y/50Y", "UL_30"), "frac_signals_disagree"] == 0.0


def test_signal_distribution_median_excludes_infinities(ust, cfg):
    """``never_cheap`` days carry ``+inf``; a median that swallows them is wrong."""
    panel = sl.build_longend_listed_panel(_s1_panel(), ust, cfg)
    dist = sl.longend_signal_distribution(panel).set_index(["structure", "listed_symbol"])
    med = dist.loc[("5Y/30Y", "US_30"), "median_breakeven_bp_day"]
    assert np.isnan(med), "all-infinite breakevens must give NaN, never inf"
    assert dist.loc[("5Y/30Y", "US_30"), "frac_never_cheap"] == 1.0


def test_signal_distribution_carries_n_and_window(ust, cfg):
    """Per-root windows differ on real data; a table without n compares samples."""
    panel = sl.build_longend_listed_panel(_s1_panel(), ust, cfg)
    dist = sl.longend_signal_distribution(panel)
    for col in ("n_days", "first", "last", "listed_role", "listed_swap_point"):
        assert col in dist.columns
    assert (dist["n_days"] > 0).all()


def test_term_structure_effect_is_flat_on_flat_planted_data(ust, cfg):
    """The fixture's slope moves the LEVEL but not the verdict, and both show."""
    panel = sl.build_longend_listed_panel(_s1_panel(), ust, cfg)
    tse = sl.longend_term_structure_effect(panel).set_index(["structure", "listed_root"])
    assert tse["cheap_share_spread"].to_numpy() == pytest.approx(0.0, abs=1e-12)
    row = tse.loc[("30Y/50Y", "UL")]
    assert row["listed_bp_day_30"] == pytest.approx(80.0 / SQ252, rel=1e-12)
    assert row["listed_bp_day_90"] == pytest.approx(84.0 / SQ252, rel=1e-12)
    assert row["listed_level_spread_bp_day"] == pytest.approx(4.0 / SQ252, rel=1e-12)


def test_benchmark_separation_reports_the_planted_level_gap(ust, cfg):
    panel = sl.build_longend_listed_panel(_s1_panel(), ust, cfg)
    sep = sl.longend_benchmark_separation(panel)
    row = sep[(sep.structure == "30Y/50Y") & (sep.listed_cm_days == 30)].iloc[0]
    assert row["primary"] == "UL" and row["control"] == "TY"
    assert row["primary_bp_day"] == pytest.approx(80.0 / SQ252, rel=1e-12)
    assert row["control_bp_day"] == pytest.approx(100.0 / SQ252, rel=1e-12)
    assert row["level_diff_bp_day"] == pytest.approx(-20.0 / SQ252, rel=1e-12)
    assert row["n_common"] > 0


def test_vol_basis_is_one_row_per_date(ust, cfg):
    panel = sl.build_longend_listed_panel(_s1_panel(), ust, cfg)
    basis = sl.longend_vol_basis(panel)
    assert basis.index.is_unique
    assert basis.index.name == "date"
    assert basis["UL_30"].iloc[0] == pytest.approx((95.0 - 80.0) / SQ252, rel=1e-12)
    assert basis["TY_30"].iloc[0] == pytest.approx((95.0 - 100.0) / SQ252, rel=1e-12)


# =============================================================================
#  7. config / grid guards
# =============================================================================


def test_longend_shift_grid_is_strat1s_not_the_wide_one():
    """MUTATION: fails if the long-end mode is pointed at ``WIDE_SHIFTS_BP``.

    The long-end mode REUSES ``strat1_signal_panel.parquet``, which was built on
    the +/-250 grid. Driving the regression through the wide grid would make the
    reused numbers and the rebuilt ones disagree for a reason that has nothing to
    do with the listed benchmark -- and the disagreement would look like a data
    problem rather than a config one.
    """
    from RVUtils.ConvexityRV.strat1_curve_gamma import Strat1Config

    assert sl.LONGEND_SHIFTS_BP == Strat1Config().shifts_bp
    assert sl.LONGEND_SHIFTS_BP != sl.WIDE_SHIFTS_BP
    assert min(sl.LONGEND_SHIFTS_BP) == -250.0 and max(sl.LONGEND_SHIFTS_BP) == 250.0
    cfg = sl.Strat1ListedConfig()
    assert cfg.longend_shifts_bp == sl.LONGEND_SHIFTS_BP
    assert tuple(cfg.longend_curve_config().shifts_bp) == sl.LONGEND_SHIFTS_BP


def test_longend_curve_config_matches_strat1s_pricing_knobs():
    """The regression is only a proof if it prices the way strat 1 priced."""
    from RVUtils.ConvexityRV.strat1_curve_gamma import Strat1Config

    s1 = Strat1Config()
    lc = sl.Strat1ListedConfig().longend_curve_config()
    for field in ("curve", "package_dv01", "horizon", "horizon_years",
                  "business_days_per_year", "swaption_expiry", "swaption_tenor",
                  "trade_straddle"):
        assert getattr(lc, field) == getattr(s1, field), field
    assert lc.structures == sl.LONG_END_STRUCTURES


# =============================================================================
#  8. the SFR leg must be UNCHANGED -- strat1_threeway depends on it
# =============================================================================


def test_sfr_config_defaults_are_untouched():
    c = sl.Strat1ListedConfig()
    assert c.structures == sl.SFR_STRUCTURES
    assert c.shifts_bp == sl.WIDE_SHIFTS_BP
    assert c.listed_source == "SFR"
    assert c.otc_expiry == "1Y" and c.otc_tenor == "2Y"
    assert c.horizon == "1Y" and c.horizon_years == 1.0
    assert c.cohort_freq == "weekly"
    assert c.start == datetime.date(2024, 7, 1)
    assert c.end == datetime.date(2026, 7, 28)
    assert c.listed_max_gap_days == 60.0
    # the new fields must not have displaced the old curve_config()
    assert tuple(c.curve_config().shifts_bp) == sl.WIDE_SHIFTS_BP
    assert c.curve_config().structures == sl.SFR_STRUCTURES


def test_load_ust_panel_still_refuses():
    """The SMILE loader must keep raising -- the CM harvest did not close that gap.

    ``USTFutureOptionMDP.sabr_smile`` is still uncached and still costs one HTTP
    call per strike. The constant-maturity panel carries ATM only.
    """
    with pytest.raises(lv.ListedDataUnavailable):
        lv.load_ust_panel()


def test_coverage_report_ust_block_tells_the_new_truth():
    """The SFR coverage report must not still say "no UST data offline".

    ``available_offline`` is kept under its original name -- it has always meant
    "is there a SMILE", and the existing SFR test pins it -- but the report now
    additionally states that constant-maturity ATM vol IS available, so a reader
    of the SFR study is not left with a claim the data directory contradicts.
    """
    sfr = pd.DataFrame({"as_of": pd.to_datetime(["2024-07-01", "2024-07-02"]),
                        "symbol": ["SFRH25", "SFRH25"]})
    rep = lv.coverage_report(sfr)
    assert rep["ust"]["available_offline"] is False
    assert rep["ust"]["smiles_available_offline"] is False
    assert rep["ust"]["atm_cm_available_offline"] == _UST_PANEL.exists()
    assert "load_ust_cm_panel" in rep["ust"]["atm_cm_note"]
    assert "SMILE" in rep["ust"]["reason"]


def test_sfr_public_api_is_intact():
    for name in ("SFR_STRUCTURES", "WIDE_SHIFTS_BP", "listed_signal_row",
                 "build_listed_signal_panel", "signal_distribution",
                 "vol_basis_frame", "long_end_reference_frame", "shift_density"):
        assert hasattr(sl, name), name
    for name in ("load_sfr_panel", "sfr_atm_vol_panel", "listed_atm_series",
                 "match_listed_expiry", "sfr_smile_on", "vol_bp_per_day",
                 "ust_price_vol_to_yield_vol", "coverage_report"):
        assert hasattr(lv, name), name


# =============================================================================
#  9. data-backed -- the thresholds the notebook's verdict rests on
# =============================================================================


@pytest.mark.slow
@pytest.mark.skipif(not _UST_PANEL.exists(), reason="UST CM panel not built")
def test_real_panel_shape_and_coverage():
    p = lv.load_ust_cm_panel()
    assert len(p) == 58176
    assert p.groupby(["symbol", "value_type"]).ngroups == 36
    assert set(p["value_type"]) == {"ABPV", "ATM"}
    assert set(p["cm_days"]) == {30, 60, 90}
    assert set(p["root"]) == set(lv.UST_CM_ROOTS)
    abpv = p[p.value_type == "ABPV"]
    per_root = abpv[abpv.cm_days == 30].groupby("root")["value"].agg(["size", "median"])
    assert per_root.loc["US", "size"] == 1917
    assert per_root.loc["US", "median"] == pytest.approx(89.1, abs=0.5)
    assert per_root.loc["UL", "median"] == pytest.approx(84.4, abs=0.5)
    assert per_root.loc["TN", "size"] == 639


@pytest.mark.slow
@pytest.mark.skipif(not _UST_PANEL.exists(), reason="UST CM panel not built")
def test_real_implied_duration_matches_known_ctd_durations():
    """The price-free units check, on the real panel, against the real profile."""
    out = lv.ust_implied_ctd_duration(lv.load_ust_cm_panel()).set_index("root")
    for root in lv.UST_CM_ROOTS:
        got = out.loc[root, "implied_mod_duration"]
        ref = lv.UST_CTD_PROFILE[root]["ctd_mod_duration"]
        assert 0.85 < got / ref < 1.15, f"{root}: implied {got:.2f} vs reference {ref:.2f}"
    assert (out.loc["UL", "implied_mod_duration"]
            > out.loc["US", "implied_mod_duration"]
            > out.loc["TN", "implied_mod_duration"]
            > out.loc["TY", "implied_mod_duration"]
            > out.loc["FV", "implied_mod_duration"]
            > out.loc["TU", "implied_mod_duration"])


@pytest.mark.slow
@pytest.mark.skipif(not _UST_PANEL.exists(), reason="UST CM panel not built")
def test_real_term_structure_slope_is_small():
    """The 1-year-horizon vs 30-day-CM mismatch must stay a few percent."""
    ts = lv.ust_cm_term_structure(lv.load_ust_cm_panel()).set_index("root")
    for root in ("US", "UL", "TY", "TN"):
        assert 0.0 < ts.loc[root, "slope_90_30_pct"] < 8.0
        assert abs(ts.loc[root, "slope_90_30_bp_day"]) < 0.4


@pytest.mark.slow
@pytest.mark.skipif(not (_UST_PANEL.exists() and _S1_PANEL.exists()),
                    reason="UST CM panel or strat1 panel not built")
def test_real_longend_headline_survives():
    """The study's headline claim, asserted on the real artifacts.

    Two things must both hold, and they are the whole result: the three forward
    structures are cheap against every listed benchmark on ~every day, AND the
    listed benchmark prices MORE vol than the 1Yx30Y swaption (a negative
    ``otc_minus_listed``), which is what makes "swaptions were the expensive
    comparison" the wrong explanation.
    """
    cfg = sl.Strat1ListedConfig()
    panel = sl.build_longend_listed_panel(
        pd.read_parquet(_S1_PANEL), lv.load_ust_cm_panel(), cfg)
    dist = sl.longend_signal_distribution(panel)
    fwd = dist[dist.structure.isin(["30Y/50Y", "20Yx5Y/25Yx5Y", "10Yx10Y/20Yx10Y"])]
    assert (fwd["frac_cheap_vs_listed"] > 0.99).all()
    assert (fwd["frac_cheap_vs_otc"] > 0.99).all()
    assert (dist["median_otc_minus_listed_bp_day"] < 0).all(), \
        "listed UST vol must price MORE than 1Yx30Y swaptions -- the crux"
    unsat = dist[dist.structure == "5Y/30Y"]
    assert (unsat["frac_cheap_vs_listed"] < 0.7).all(), \
        "5Y/30Y is the unsaturated control structure"


@pytest.mark.slow
@pytest.mark.skipif(not lv.default_ust_basis_root().exists(),
                    reason="UST basis-report store not present")
def test_real_ctd_frame_reprices_the_stores_own_prices():
    """The check on the DV01 check: independent repricing of every CTD."""
    ctd = lv.load_ctd_basis_frame(roots=["US", "UL"])
    assert len(ctd) > 500
    assert ctd["price_err_pts"].median() < 0.01
    assert ctd["price_err_pts"].quantile(0.99) < 0.05
    med = ctd.groupby("root")["ctd_mod_duration"].median()
    assert 10.0 < med.loc["US"] < 13.5
    assert 15.0 < med.loc["UL"] < 19.0
    assert (ctd["fv01_points_per_bp"] > 0).all()


@pytest.mark.slow
@pytest.mark.skipif(not (_UST_PANEL.exists() and lv.default_ust_basis_root().exists()),
                    reason="UST CM panel or basis store not present")
def test_real_dv01_units_check_passes_on_the_long_end():
    """Step 1b on real data: implied ABPV within 5% of quoted for US and UL."""
    panel = lv.load_ust_cm_panel()
    ctd = lv.load_ctd_basis_frame(roots=["US", "UL"])
    out = lv.ust_units_check_dv01(panel, ctd, cm_days=30).set_index("root")
    for root in ("US", "UL"):
        assert 0.95 < out.loc[root, "ratio"] < 1.05, out.loc[root].to_dict()
        assert out.loc[root, "n"] > 200

"""Tests for the cap/floor-calibrated model CA and the 3m realized pack vol.

Nothing here touches the network. The cap/floor path is exercised against a
**stub MDP** returning a real ``STIRCapFloorMarketContext`` built from stub
pricers, so the leg-identity guards, the unit claim and the no-fallback rule are
all tested for real while the vendor is never called.

Every assertion below was mutation-checked: the mutation is named in the
docstring of the test that catches it, and each was applied to
``RVUtils/ConvexityRV/ca_valuation.py`` and confirmed to make that test fail.

The two external known-answers are Citi's own published SOFR screen (*Rates Vol
Lab*, 12-Jun-2023, Figure 58, close 6/9/2023), which prints both the model CA
and the 3m realized vol per pack. Neither number came from this codebase.
"""

from __future__ import annotations

import datetime
import math
from collections import OrderedDict

import numpy as np
import pandas as pd
import pytest

from Query.STIRCapFloors.pricer import STIRCapFloorLegMarket
from Query.STIRFutureOptions._STIRFutureOptionGenericPricer import (
    _STIRFutureOptionGenericPricer,
)
from RVUtils.ConvexityRV import ca_valuation as CV
from RVUtils.ConvexityRV.holee import pack_ca_bp
from RVUtils.ConvexityRV.strat2_q20 import CITI_SOFR_20230609

CFG = CV.CAValuationConfig()
AS_OF = datetime.date(2023, 6, 9)


# ===========================================================================
# Pack geometry
# ===========================================================================
def test_pack_spec_matches_citis_published_swap_dates():
    """Citi pins the matched swap verbatim; rank 13 on 6/9/23 is Blues M6-H7."""
    label, cts, start, end, t1s = CV.pack_spec_for_rank(AS_OF, 13)
    assert label == "M6-H7"
    assert start == datetime.date(2026, 6, 17)
    assert end == datetime.date(2027, 6, 16)
    assert len(cts) == 4 and len(t1s) == 4
    assert t1s == sorted(t1s)


def test_pack_spec_rank_5_is_reds():
    label, _, start, end, _ = CV.pack_spec_for_rank(AS_OF, 5)
    assert label == "M4-H5"
    assert start == datetime.date(2024, 6, 19)
    assert end == datetime.date(2025, 6, 18)


def test_sfr_option_contract_root_translation():
    """The futures side speaks SR3; the option MDP speaks SFR. Same contract."""
    assert CV.sfr_option_contract(2024, 6) == "SFRM24"
    assert CV.sfr_option_contract(2026, 12) == "SFRZ26"


# ===========================================================================
# The model leg
# ===========================================================================
def _panel_row(pack="M6-H7", rank=13, ca_bp=15.0, time_weight=11.5,
               date="2023-06-09") -> pd.DataFrame:
    return pd.DataFrame([{"date": pd.Timestamp(date), "rank": rank, "pack": pack,
                          "ca_bp": ca_bp, "time_weight": time_weight}])


def test_model_ca_is_half_sigma_squared_times_time_weight():
    """Planted answer. MUTATION: dropping the 1e4 scaling, or using T1*T2."""
    panel = _panel_row(ca_bp=15.0, time_weight=11.5)
    sig = pd.DataFrame({"M6-H7": [130.0]}, index=[pd.Timestamp("2023-06-09")])
    out = CV.model_ca_from_sigma(panel, sig, CFG)
    expected = 0.5 * (130.0 / 1e4) ** 2 * 11.5 * 1e4
    assert out["ca_model_capfloor_bp"].iloc[0] == pytest.approx(expected, abs=1e-12)
    assert out["vs_model_capfloor_bp"].iloc[0] == pytest.approx(15.0 - expected, abs=1e-12)


def test_citi_convention_is_pinned_not_inherited():
    """``holee.DEFAULT_CONVENTION`` is not ours to depend on.

    It was observed flipping from ``citi`` to ``hull`` while this module was
    being written. Under ``hull`` the same sigma and the same four T1s give a
    materially different CA, so a module that inherited the default would
    silently change answer. MUTATION: replace ``convention=cfg.holee_convention``
    with the imported default in ``model_ca_from_sigma``.
    """
    _, _, _, _, t1s = CV.pack_spec_for_rank(AS_OF, 13)
    citi = pack_ca_bp(130.0, t1s, convention="citi")
    hull = pack_ca_bp(130.0, t1s, convention="hull")
    assert abs(hull - citi) / citi > 0.02, "the two conventions must differ materially"
    assert CV.CITI_CONVENTION == "citi"
    assert CFG.holee_convention == "citi"

    panel = _panel_row(time_weight=float(np.mean(np.asarray(t1s) ** 2)))
    sig = pd.DataFrame({"M6-H7": [130.0]}, index=[pd.Timestamp("2023-06-09")])
    got = CV.model_ca_from_sigma(panel, sig, CFG)["ca_model_capfloor_bp"].iloc[0]
    assert got == pytest.approx(citi, rel=1e-12)
    assert got != pytest.approx(hull, rel=1e-6)


def test_missing_sigma_gives_nan_model_and_never_falls_back():
    """The no-silent-fallback rule.

    A model leg quietly backfilled from the observed CA would make ``vs_model``
    zero by construction and read as a perfect fit. MUTATION: fill the missing
    sigma with the CA-implied vol; ``vs_model_capfloor_bp`` becomes 0.0 and this
    test fails on both the isnan assertions.
    """
    panel = _panel_row(ca_bp=15.0)
    out = CV.model_ca_from_sigma(panel, pd.DataFrame(), CFG)
    assert np.isnan(out["sigma_capfloor_bp"].iloc[0])
    assert np.isnan(out["ca_model_capfloor_bp"].iloc[0])
    assert np.isnan(out["vs_model_capfloor_bp"].iloc[0])

    sig = pd.DataFrame({"SOMETHING-ELSE": [130.0]}, index=[pd.Timestamp("2023-06-09")])
    out2 = CV.model_ca_from_sigma(panel, sig, CFG)
    assert np.isnan(out2["ca_model_capfloor_bp"].iloc[0])


def test_implied_vol_inversion_round_trips_the_model():
    """If sigma_capfloor equals the implied vol the dislocation must be zero."""
    panel = _panel_row(ca_bp=15.0, time_weight=11.5)
    iv = CV.model_ca_from_sigma(panel, pd.DataFrame(), CFG)["implied_vol_bp"].iloc[0]
    sig = pd.DataFrame({"M6-H7": [iv]}, index=[pd.Timestamp("2023-06-09")])
    out = CV.model_ca_from_sigma(panel, sig, CFG)
    assert out["vs_model_capfloor_bp"].iloc[0] == pytest.approx(0.0, abs=1e-9)
    assert out["implied_minus_capfloor_bp"].iloc[0] == pytest.approx(0.0, abs=1e-9)


def test_negative_ca_gives_no_implied_vol():
    """A negative adjustment is not representable under Ho-Lee; Citi prints n/a."""
    out = CV.model_ca_from_sigma(_panel_row(ca_bp=-2.0), pd.DataFrame(), CFG)
    assert np.isnan(out["implied_vol_bp"].iloc[0])


def test_citi_published_model_column_inverts_and_reprices():
    """External known-answer: invert Citi's Model column, reprice it, get it back.

    Citi publishes the model CA but not the sigma behind it, so the only way to
    compare calibrations is to invert their column. The inversion is exact, so
    this is a self-consistency check on :func:`citi_implied_model_sigma` -- and
    it is not vacuous: the recovered sigma term structure is a real, downward-
    sloping curve, which the range assertion pins.
    """
    weights = {lab: 2.0 * rec["ca_bp"] / (rec["implied_vol_bp"] / 1e4) ** 2 / 1e4
               for lab, rec in CITI_SOFR_20230609.items()}
    tab = CV.citi_implied_model_sigma(CITI_SOFR_20230609, weights)
    assert len(tab) == 13
    for lab, row in tab.iterrows():
        back = pack_ca_bp(row["citi_model_sigma_bp"], [math.sqrt(row["time_weight"])],
                          convention="citi")
        assert back == pytest.approx(row["citi_model_bp"], rel=1e-9), lab
    sig = tab["citi_model_sigma_bp"]
    assert sig.iloc[0] > sig.iloc[-1], "Citi's model sigma slopes down with maturity"
    assert 100.0 < sig.min() < sig.max() < 250.0


# ===========================================================================
# 3m realized vol
# ===========================================================================
def _rate_panel(changes_bp, pack="M6-H7", start="2022-01-03") -> pd.DataFrame:
    """Long CA-panel-shaped frame whose pack rate has the given daily bp changes."""
    idx = pd.bdate_range(start, periods=len(changes_bp) + 1)
    rate = np.concatenate([[3.0], 3.0 + np.cumsum(np.asarray(changes_bp, float)) / 100.0])
    return pd.DataFrame({"date": idx, "rank": 13, "pack": pack, "pack_rate": rate})


def test_realized_vol_is_sample_sd_of_daily_bp_changes_times_sqrt_252():
    """Planted answer. MUTATION: sqrt(365), or ddof=0, or forgetting the *100."""
    rng = np.random.default_rng(11)
    changes = rng.normal(0.0, 5.0, 200)
    panel = _rate_panel(changes)
    rv = CV.pack_realized_vol(panel, CFG)
    last = rv["M6-H7"].dropna().iloc[-1]
    expected = float(np.std(changes[-63:], ddof=1) * math.sqrt(252.0))
    assert last == pytest.approx(expected, rel=1e-9)


def test_annualisation_factor_is_load_bearing():
    """252 business days, because the window is 63 BUSINESS days.

    A 63-business-day window annualised at 365 overstates the vol by 20%.
    MUTATION: ``realized_annualisation=365`` -- the ratio assertion fails.
    """
    changes = np.full(120, 4.0)
    changes[::2] = -4.0
    panel = _rate_panel(changes)
    a = CV.pack_realized_vol(panel, CFG)["M6-H7"].dropna().iloc[-1]
    b = CV.pack_realized_vol(
        panel, CV.CAValuationConfig(realized_annualisation=365.0)
    )["M6-H7"].dropna().iloc[-1]
    assert b / a == pytest.approx(math.sqrt(365.0 / 252.0), rel=1e-12)


def test_min_obs_gate_binds_exactly():
    """41 observed daily changes -> NaN; 42 -> a number. MUTATION: min_periods=1."""
    rng = np.random.default_rng(3)
    panel = _rate_panel(rng.normal(0.0, 5.0, 100))
    strict = CV.pack_realized_vol(panel, CV.CAValuationConfig(realized_min_obs=42))
    n_before_first = int(strict["M6-H7"].isna().sum() - 0)
    first_idx = strict["M6-H7"].first_valid_index()
    # the first finite value sits on the 42nd available daily change
    diffs = strict.index.get_loc(first_idx)
    assert diffs == 42, f"first realized vol on row {diffs}, expected 42"
    assert n_before_first == 42

    loose = CV.pack_realized_vol(panel, CV.CAValuationConfig(realized_min_obs=2))
    assert loose.index.get_loc(loose["M6-H7"].first_valid_index()) == 2


def test_a_two_hundred_day_hole_is_not_bridged():
    """The specific defect being fixed.

    On a sparse index ``.diff()`` computes a 200-day change and calls it daily,
    which would inflate the realized vol by ~sqrt(200). On the business-day grid
    the change across the hole is NaN and never enters the window.
    MUTATION: drop the ``bday_reindex`` call in ``pack_realized_vol`` -- the
    post-hole value explodes and both assertions fail.
    """
    rng = np.random.default_rng(7)
    left = _rate_panel(rng.normal(0.0, 5.0, 120), start="2022-01-03")
    right_idx = pd.bdate_range("2023-06-01", periods=80)
    right = pd.DataFrame({
        "date": right_idx, "rank": 13, "pack": "M6-H7",
        "pack_rate": 3.0 + np.cumsum(rng.normal(0.0, 5.0, 80)) / 100.0})
    panel = pd.concat([left, right], ignore_index=True)

    rv = CV.pack_realized_vol(panel, CFG)["M6-H7"]
    # nothing is emitted for the 42 business days after the hole reopens
    just_after = rv.loc["2023-06-01":"2023-07-28"]
    assert just_after.notna().sum() == 0, "a number was emitted inside the hole's shadow"
    # and once it recovers it is a sane ~5bp/day series, not sqrt(200)x that
    later = rv.dropna().iloc[-1]
    assert 40.0 < later < 130.0, later


def test_bday_reindex_creates_the_gap_the_chart_needs():
    """``connectgaps=False`` can only skip a gap that exists in the series."""
    idx = pd.DatetimeIndex(["2023-01-02", "2023-01-03", "2023-11-01"])
    wide = pd.DataFrame({"A": [1.0, 2.0, 3.0]}, index=idx)
    out = CV.bday_reindex(wide)
    assert len(out) > 200
    assert out["A"].isna().sum() == len(out) - 3
    assert out.index.equals(pd.bdate_range("2023-01-02", "2023-11-01"))


def test_realized_vol_coverage_counts_only_finite_cells():
    rng = np.random.default_rng(5)
    panel = _rate_panel(rng.normal(0.0, 5.0, 300))
    cov = CV.realized_vol_coverage(CV.pack_realized_vol(panel, CFG))
    assert set(cov.columns) >= {"bdays", "grid_cells", "computable", "pct"}
    assert cov["computable"].sum() == 300 - 42 + 1


# ===========================================================================
# The cap/floor call, against a stub MDP
# ===========================================================================
class _StubPricer(_STIRFutureOptionGenericPricer):
    """Deterministic Bachelier pricer: everything ATM, discount 1, one vol."""

    def __init__(self, symbol: str, expiry: datetime.date, vol_price_pts: float,
                 forward: float = 96.0):
        self._sym = symbol
        self._expiry = expiry
        self._vol = float(vol_price_pts)
        self._fwd = float(forward)

    def id(self): return self._sym
    def symbol(self): return self._sym
    def right(self): return "P"
    def underlying_symbol(self): return self._sym.split("|")[0]
    def strike(self): return self._fwd
    def quote_timestamp(self): return datetime.datetime(2023, 6, 9, 17, 0)
    def expiry_date(self): return self._expiry
    def model_price(self): return self.price()
    def iv_normal(self): return self._vol
    def iv_normal_bps(self): return self._vol * 100.0
    def delta(self): return 0.5
    def gamma(self): return 0.0
    def vega(self): return 0.0
    def theta(self): return 0.0
    def discount(self): return 1.0
    def forward(self): return self._fwd
    def meta(self): return {}
    def resolve_pricable(self, priceable, risk_weight=None): return priceable
    def build_pricable(self, *args, **kwargs): return None

    def price(self) -> float:
        import QuantLib as ql
        tte = max((self._expiry - datetime.date(2023, 6, 9)).days / 365.0, 1e-12)
        return float(ql.bachelierBlackFormula(
            ql.Option.Put, self._fwd, self._fwd, self._vol * math.sqrt(tte), 1.0))

    def npv(self, leg=None) -> float:
        return self.price()


def _stub_context(contracts, vols_price_pts, *, as_of=AS_OF,
                  swap_start=None, swap_end=None):
    from MDP.STIRCapFloors.STIRCapFloorMDP import STIRCapFloorMarketContext
    from RVUtils.ConvexityRV.packs import imm_date

    legs = []
    n = len(contracts)
    for i, (c, v) in enumerate(zip(contracts, vols_price_pts)):
        code, yy = c[3], int(c[4:])
        month = {"H": 3, "M": 6, "U": 9, "Z": 12}[code]
        expiry = imm_date(2000 + yy, month)
        pricer = _StubPricer(f"{c}|ATMP", expiry, v)
        legs.append(STIRCapFloorLegMarket(
            option_symbol=pricer.symbol(), requested_symbol=pricer.symbol(),
            right="P", underlying_contract=c,
            reference_quarter_start=expiry, reference_quarter_end=expiry,
            strike_price=96.0, strike_rate=4.0, requested_strike_price=96.0,
            requested_strike_rate=4.0, economic_weight=1.0 / n,
            unit_quantity=1.0, quantity=1.0, quote_source="market",
            quarter_end_flag=False, fomc_loading=0.0, pricer=pricer))
    return STIRCapFloorMarketContext(
        structure="CAP", curve_name="USD-SOFR-1D", as_of_date=as_of,
        swap_start=swap_start or datetime.date(2026, 6, 17),
        swap_end=swap_end or datetime.date(2027, 6, 16),
        weight_method="equal", strike_convention="atm_per_caplet", contracts=1.0,
        curve=None, legs=tuple(legs), metadata={})


class _StubMDP:
    def __init__(self, ctx=None, exc=None):
        self._ctx, self._exc, self.calls = ctx, exc, []

    def get_data(self, req):
        self.calls.append(dict(req))
        if self._exc is not None:
            raise self._exc
        return self._ctx


def test_flat_strip_calibrates_to_its_own_vol_in_bp_per_year():
    """The units claim, tested rather than asserted in prose.

    Four caplets all quoted at the same normal vol must calibrate to a flat vol
    equal to that vol, and the answer must come out in **bp/yr** -- i.e. 100x
    the price-point vol, because the SR3 underlying is the price ``100 - R`` and
    ``dP = -dR``. MUTATION: return the value map's raw sigma without the 100x
    and this fails by exactly two orders of magnitude.
    """
    ctx = _stub_context(["SFRM26", "SFRU26", "SFRZ26", "SFRH27"], [1.30] * 4)
    flat, mean = CV._strip_vols(ctx)
    assert flat == pytest.approx(130.0, abs=0.05)
    assert mean == pytest.approx(130.0, abs=1e-9)


def test_happy_path_returns_ok_and_the_packs_own_contracts():
    ctx = _stub_context(["SFRM26", "SFRU26", "SFRZ26", "SFRH27"], [1.28, 1.29, 1.30, 1.31])
    got = CV.pack_capfloor_vol(AS_OF, 13, CFG, mdp=_StubMDP(ctx))
    assert got.reason == "ok"
    assert got.pack == "M6-H7"
    assert got.contracts == ("SFRM26", "SFRU26", "SFRZ26", "SFRH27")
    assert 120.0 < got.sigma_flat_bp < 140.0
    assert got.caplet_vols_bp == pytest.approx((128.0, 129.0, 130.0, 131.0))


def test_expiry_tail_request_form_is_used_not_the_explicit_window():
    """``_contracts_for_explicit_window`` truncates forward-starting strips.

    Measured on 2023-06-09: the explicit ``swap_start``/``swap_end`` form
    returned ONE leg for rank 9 instead of four, because the MDP sizes its
    candidate ladder from the front of the curve. The expiry/tail form resolves
    exactly ``tail/3`` contracts from ``start_index=expiry/3``.
    MUTATION: switch the request back to swap_start/swap_end -- this fails.
    """
    mdp = _StubMDP(_stub_context(["SFRM26", "SFRU26", "SFRZ26", "SFRH27"], [1.3] * 4))
    CV.pack_capfloor_vol(AS_OF, 13, CFG, mdp=mdp)
    req = mdp.calls[0]
    assert req["expiry"] == "36M" and req["tail"] == "12M"
    assert "swap_start" not in req and "swap_end" not in req


def test_wrong_contracts_are_rejected_not_silently_used():
    """MUTATION: drop the ``got != want`` guard -- reason becomes 'ok'."""
    ctx = _stub_context(["SFRM25", "SFRU25", "SFRZ25", "SFRH26"], [1.3] * 4)
    got = CV.pack_capfloor_vol(AS_OF, 13, CFG, mdp=_StubMDP(ctx))
    assert got.reason == "contract_mismatch"
    assert np.isnan(got.sigma_flat_bp)


def test_short_strip_is_rejected():
    """The one-leg truncation must surface as a reason, never as a pack vol."""
    ctx = _stub_context(["SFRM26"], [1.3])
    got = CV.pack_capfloor_vol(AS_OF, 13, CFG, mdp=_StubMDP(ctx))
    assert got.reason == "leg_count"
    assert np.isnan(got.sigma_flat_bp) and np.isnan(got.sigma_mean_bp)


def test_wrong_accrual_window_is_rejected():
    ctx = _stub_context(["SFRM26", "SFRU26", "SFRZ26", "SFRH27"], [1.3] * 4,
                        swap_end=datetime.date(2027, 9, 15))
    got = CV.pack_capfloor_vol(AS_OF, 13, CFG, mdp=_StubMDP(ctx))
    assert got.reason == "window_mismatch"


def test_missing_listed_option_is_reported_as_no_option():
    mdp = _StubMDP(exc=ValueError("Could not resolve listed ATM option for SFRM29|ATMP"))
    got = CV.pack_capfloor_vol(AS_OF, 17, CFG, mdp=mdp)
    assert got.reason == "no_option"
    assert np.isnan(got.sigma_flat_bp)


def test_sigma_wide_trusts_the_reason_not_the_presence_of_a_number():
    """``reason`` is the gate, not ``isfinite(sigma)``.

    A resumed panel can carry a row that has a number in the sigma column and a
    reason saying the calibration was rejected -- a leg-identity failure that
    still produced a strip vol, say, from the wrong four contracts. Such a row
    must not reach the model leg. MUTATION: drop the ``reason == "ok"`` filter
    in ``sigma_wide`` -- the rejected pack appears as a column and this fails.
    """
    rows = [
        CV.CapFloorVol(AS_OF, 13, "M6-H7", 130.0, 130.5, "ok").as_row(),
        CV.CapFloorVol(AS_OF, 14, "U6-M7", float("nan"), float("nan"), "no_option").as_row(),
        dict(CV.CapFloorVol(AS_OF, 15, "Z6-U7", 99.0, 99.0, "ok").as_row(),
             reason="contract_mismatch"),
    ]
    wide = CV.sigma_wide(pd.DataFrame(rows), CFG)
    assert list(wide.columns) == ["M6-H7"]
    assert wide.iloc[0, 0] == pytest.approx(130.0)


def test_vol_measure_selects_flat_or_mean():
    row = CV.CapFloorVol(AS_OF, 13, "M6-H7", 130.0, 141.0, "ok").as_row()
    df = pd.DataFrame([row])
    assert CV.sigma_wide(df, CFG).iloc[0, 0] == pytest.approx(130.0)
    assert CV.sigma_wide(df, CV.CAValuationConfig(vol_measure="mean")).iloc[0, 0] \
        == pytest.approx(141.0)


# ===========================================================================
# The screen and the flags
# ===========================================================================
def _screen(vs_model, im_ir, ratio) -> pd.DataFrame:
    packs = [f"P{i}" for i in range(len(vs_model))]
    return pd.DataFrame({
        "pack": packs, "rank": range(5, 5 + len(packs)),
        "vs_model_capfloor_bp": vs_model,
        "implied_minus_realized_bp": im_ir,
        "implied_over_realized": ratio,
    }).set_index("pack", drop=False)


def test_three_best_short_convexity_are_the_three_highest():
    """Short convexity is attractive where the market OVERPAYS for convexity.

    MUTATION: use ``nsmallest`` -- the flagged set inverts and this fails.
    """
    s = _screen([1.0, 5.0, 2.0, 4.0, 3.0], [10, 50, 20, 40, 30], [1.0, 5.0, 2.0, 4.0, 3.0])
    flags = CV.short_convexity_flags(s, CFG)
    flagged = set(flags.index[flags["vs_model_capfloor_bp"]])
    assert flagged == {"P1", "P3", "P4"}
    assert int(flags["n_flags"].max()) == 3


def test_an_all_nan_metric_casts_no_vote():
    """MUTATION: rank NaNs as zero -- every pack picks up a spurious flag."""
    s = _screen([1.0, 5.0, 2.0], [np.nan] * 3, [np.nan] * 3)
    flags = CV.short_convexity_flags(s, CFG)
    assert not flags["implied_minus_realized_bp"].any()
    assert int(flags.loc["P1", "n_flags"]) == 1


def test_top_short_convexity_orders_by_agreement_then_percentile():
    s = _screen([1.0, 5.0, 2.0, 4.0, 3.0], [10, 50, 20, 40, 30], [1.0, 5.0, 2.0, 4.0, 3.0])
    top = CV.top_short_convexity(s, CFG)
    assert list(top.index[:3]) == ["P1", "P3", "P4"]
    assert top["n_flags"].is_monotonic_decreasing


def test_screen_emits_nan_where_the_vol_or_the_window_is_missing():
    panel = _panel_row(ca_bp=15.0, time_weight=11.5)
    valued = CV.model_ca_from_sigma(panel, pd.DataFrame(), CFG)
    scr = CV.valuation_screen("2023-06-09", valued, pd.DataFrame(), CFG)
    assert np.isnan(scr["vs_model_capfloor_bp"].iloc[0])
    assert np.isnan(scr["realized_vol_bp"].iloc[0])
    assert np.isnan(scr["implied_over_realized"].iloc[0])
    assert np.isfinite(scr["ca_bp"].iloc[0]), "the OBSERVED CA must survive intact"


def test_a_date_with_no_ranked_rows_returns_an_empty_frame_not_a_KeyError():
    """A date can carry a cap/floor vol and no CA row at that rank.

    The vol panel is built from pack geometry; the CA panel from what settled.
    A partially repaired CA panel has dates with ranks 1-4 only, and the screen
    is asked for ranks 5-13. MUTATION: move the `day.empty` check back BEFORE
    the rank filter -- `pd.DataFrame([]).set_index("pack")` then raises
    `KeyError: None of ['pack'] are in the columns` and this test fails.
    """
    panel = _panel_row(rank=2, ca_bp=1.0)
    valued = CV.model_ca_from_sigma(panel, pd.DataFrame(), CFG)
    out = CV.valuation_screen("2023-06-09", valued, pd.DataFrame(), CFG,
                              ranks=range(5, 14))
    assert isinstance(out, pd.DataFrame) and out.empty


def test_observed_ca_is_untouched_by_the_model_leg():
    """The contract with the existing tie-out: only the MODEL leg changes.

    MUTATION: rescale ``ca_bp`` anywhere in ``model_ca_from_sigma``.
    """
    panel = _panel_row(ca_bp=15.715068, time_weight=11.5)
    for sig in (pd.DataFrame(),
                pd.DataFrame({"M6-H7": [130.0]}, index=[pd.Timestamp("2023-06-09")]),
                pd.DataFrame({"M6-H7": [55.0]}, index=[pd.Timestamp("2023-06-09")])):
        out = CV.model_ca_from_sigma(panel, sig, CFG)
        assert out["ca_bp"].iloc[0] == pytest.approx(15.715068, abs=0.0)


# ===========================================================================
# Config guards
# ===========================================================================
def test_config_rejects_nonsense():
    with pytest.raises(ValueError):
        CV.CAValuationConfig(vol_measure="whatever")
    with pytest.raises(ValueError):
        CV.CAValuationConfig(strike_convention="mid")
    with pytest.raises(ValueError):
        CV.CAValuationConfig(realized_min_obs=100, realized_window_days=63)


def test_network_is_blocked_by_default():
    assert CFG.allow_network is False
    assert CFG.max_network_cells == 0

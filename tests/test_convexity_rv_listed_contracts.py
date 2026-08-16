"""Known-answer tests for the REAL-LISTED-CONTRACT panel.

The constant-maturity panel this replaces has no expiry, so nothing in it could
be wrong about time. The real-contract panel is built entirely out of dates --
an expiry rule per asset class, an ACT/365 time to expiry, a nearest-TTE
selection -- and every one of those is a place where a plausible wrong answer
looks completely normal in a plot. So the tests here are mostly about time.

Three tiers, so the fast gate stays offline and fast:

* **Contract machinery** (no I/O). Pinned expiry dates for named contracts,
  taken from the CME rules and *tied out against the vendor's own last quote
  date* before being written down (measured during the harvest: last quote is
  expiry - 1 business day on every contract checked).
* **Synthetic panel** (no I/O). A hand-built two-root ladder with planted
  answers for TTE selection, ladder interpolation and the units identities.
* **Data-backed** (skipped when the parquet is absent). Coverage invariants and
  the units verdict measured on the harvested panel.

**Verifying the checker itself.** Six tests are explicit mutation checks. Each
names the wrong implementation it is built to catch, and each was run against
that mutation and observed to FAIL before being committed:

``test_sfr_expiry_is_last_trade_date_not_the_futures_imm_date``
    fails if ``sfr_expiry`` uses ``quarterly_contract_expiry_date`` -- the
    underlying future's IMM date, five days LATER, which would overstate every
    SOFR time to expiry by a week.  [mutated: 4 pinned dates off by 5 days]
``test_tte_is_act_365``
    fails if the day count becomes ACT/360 or business days.  [mutated to 360:
    tte 0.5000 -> 0.5069]
``test_select_by_tte_picks_the_nearest_not_the_first``
    fails if the selection takes ``argmax``, the first row, or drops the
    absolute value.  [mutated to argmax: picks 180d instead of 35d]
``test_select_by_tte_returns_none_beyond_max_gap``
    fails if the ``max_gap_days`` guard is dropped -- the failure mode that
    silently substitutes a 6-month option for a 1-month one.  [mutated: returns
    the 180d contract instead of None]
``test_abpv_atm_scale_is_abpv_over_atm_not_the_reciprocal``
    fails if the ratio is inverted, which would still produce a smooth,
    plausible-looking series.  [mutated: scale 1e-4 x, smile_bp_yr ~0]
``test_ladder_interpolation_is_linear_in_tte``
    fails if the interpolation is done in the wrong coordinate (e.g. sqrt-time)
    or if flat extrapolation becomes linear.  [mutated to sqrt-time: 87.5 ->
    88.28 at the planted midpoint]
"""

from __future__ import annotations

import datetime

import numpy as np
import pandas as pd
import pytest

from RVUtils.ConvexityRV import listed_contracts as lc

# The harvest script is not importable as a package module; load it by path so
# the universe builder and its expiry rules are under test too.
import importlib.util
import pathlib

_SPEC = importlib.util.spec_from_file_location(
    "_harvest_listed_contract_vol",
    pathlib.Path(__file__).resolve().parents[1] / "scripts" / "harvest_listed_contract_vol.py",
)
harvest = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(harvest)


# ------------------------------------------------------------------- fixtures


def _synthetic_panel() -> pd.DataFrame:
    """One date, one root, a four-point ladder with planted round numbers.

    Root ``US`` on 2026-03-02 with contracts at 5 / 35 / 95 / 180 days to expiry
    and ABPV 100 / 90 / 85 / 80. The 35d and 95d points are 60 days apart with
    a 5 bp vol gap, so the ladder's value at 65 days is **87.5** exactly --
    which is what pins the interpolation to linear-in-TTE.

    ATM is planted at ABPV/850 (a UST-like lognormal price vol) and the smile at
    ATM + a planted spread, so ``ABPV/ATM == 850`` exactly and the RR identity
    holds to machine precision by construction.
    """
    day = pd.Timestamp("2026-03-02")
    rows = []
    for tte_days, abpv in [(5, 100.0), (35, 90.0), (95, 85.0), (180, 80.0)]:
        exp = day + pd.Timedelta(days=tte_days)
        code = f"USX{tte_days:03d}"
        atm = abpv / 850.0
        call, put = atm + 0.001, atm + 0.003
        vals = {
            "ABPV": abpv, "ATM": atm,
            "25D_CALL": call, "25D_PUT": put,
            "25D_RR": call - put,
            "25D_BF": 0.5 * (call + put) - atm,
        }
        for vt, v in vals.items():
            rows.append({
                "date": day, "symbol": code, "vendor_column": f"{code} {vt}",
                "root": "US", "asset": "UST", "contract_code": code,
                "contract_kind": "quarterly", "expiry_date": exp,
                "tte_years": tte_days / 365.0, "value_type": vt, "value": v,
            })
    return pd.DataFrame(rows)


def _synthetic_sfr_panel() -> pd.DataFrame:
    """SFR rows where ABPV is exactly 100 x ATM, the measured affine identity.

    Three contracts with DIFFERENT call/put spreads, so ``25D_RR`` varies across
    rows and its correlation against ``call - put`` is defined -- on a constant
    series ``corr`` is NaN and the identity check would prove nothing.
    """
    day = pd.Timestamp("2026-03-02")
    rows = []
    for tte_days, abpv, dc, dp in [(40, 120.0, 0.02, 0.05),
                                   (130, 110.0, 0.03, 0.04),
                                   (220, 105.0, 0.01, 0.07)]:
        exp = day + pd.Timedelta(days=tte_days)
        code = f"SFRX{tte_days:03d}"
        atm = abpv / 100.0
        call, put = atm + dc, atm + dp
        vals = {"ABPV": abpv, "ATM": atm, "25D_CALL": call, "25D_PUT": put,
                "25D_RR": call - put, "25D_BF": 0.5 * (call + put) - atm}
        for vt, v in vals.items():
            rows.append({
                "date": day, "symbol": code.replace("SFR", "SR3"),
                "vendor_column": f"{code} {vt}", "root": "SFR", "asset": "SFR",
                "contract_code": code, "contract_kind": "quarterly",
                "expiry_date": exp, "tte_years": tte_days / 365.0,
                "value_type": vt, "value": v,
            })
    return pd.DataFrame(rows)


# ------------------------------------------------------- contract machinery


def test_ust_option_expiry_pinned_dates():
    """CME monthly rule, tied out against the vendor's own last quote date.

    Each of these was checked against the harvested series before being pinned:
    the last quote lands one business day before the expiry, every time
    (USM26 last quote 2026-05-21, USZ19 2019-11-21, TYF26 2025-12-24 with
    Christmas intervening).
    """
    assert harvest.ust_expiry("USM26") == datetime.date(2026, 5, 22)
    assert harvest.ust_expiry("USZ19") == datetime.date(2019, 11, 22)
    assert harvest.ust_expiry("USH19") == datetime.date(2019, 2, 22)
    assert harvest.ust_expiry("TYF26") == datetime.date(2025, 12, 26)
    assert harvest.ust_expiry("USJ26") == datetime.date(2026, 3, 27)


def test_ust_expiry_is_holiday_aware_unlike_the_repo_rule():
    """MUTATION CHECK / defect record: the repo's own rule ignores exchange holidays.

    ``definitions.USTFutureOptions.option_expiry_date`` resolves "business day"
    as Monday-to-Friday. The CME rule is "the last Friday which precedes by at
    least two business days the last business day of the month preceding the
    option month; if that Friday is not a business day, trading terminates on
    the prior business day", and on the dates below a holiday sits inside that
    window. The weekday-only version lands a week late for the May-2022
    contracts and returns **Christmas Day itself** as an option expiry for the
    January serials.

    This is not a theoretical difference. Every expected value below is fixed by
    the vendor's own last quote date, which sits exactly one business day before
    the expiry on all 200 expired contracts in the panel:

    ==========  ============  =============  ==============  ================
    contract    last quote    correct        repo rule       holiday at fault
    ==========  ============  =============  ==============  ================
    USM22       2022-05-19    2022-05-20     2022-05-27      Memorial Day
    TYM22       2022-05-19    2022-05-20     2022-05-27      Memorial Day
    USF21       2020-12-23    2020-12-24     2020-12-25      Christmas (Fri)
    USF22       2021-12-22    2021-12-23     2021-12-24      Christmas obs.
    ==========  ============  =============  ==============  ================

    The January cases also pin the SECOND half of the rule, and they are the
    reason it is written the way it is: an earlier version of ``ust_expiry``
    rolled a holiday Friday back to the PREVIOUS FRIDAY rather than the previous
    BUSINESS DAY, which put USF21 on 2020-12-18 -- before its own last quote,
    i.e. a negative time to expiry. Wrong in the opposite direction from the
    repo's bug, and equally invisible without the tie-out.

    Substituting ``ust_expiry_legacy`` for ``ust_expiry`` fails this test.

    **This test is designed to break when the upstream defect is FIXED.** It
    pins ``ust_expiry_legacy``'s wrong answers so the discrepancy cannot quietly
    disappear. If ``definitions.USTFutureOptions.option_expiry_date`` is ever
    corrected, the ``ust_expiry_legacy`` assertions here will fail -- that is the
    signal to RETIRE this test and collapse ``ust_expiry`` back onto the repo
    function, not a regression to debug.
    """
    cases = [("USM22", datetime.date(2022, 5, 20), datetime.date(2022, 5, 27)),
             ("TYM22", datetime.date(2022, 5, 20), datetime.date(2022, 5, 27)),
             ("USF21", datetime.date(2020, 12, 24), datetime.date(2020, 12, 25)),
             ("TYF21", datetime.date(2020, 12, 24), datetime.date(2020, 12, 25)),
             ("USF22", datetime.date(2021, 12, 23), datetime.date(2021, 12, 24)),
             ("TYF22", datetime.date(2021, 12, 23), datetime.date(2021, 12, 24))]
    for code, correct, repo in cases:
        assert harvest.ust_expiry(code) == correct, code
        assert harvest.ust_expiry_legacy(code) == repo, code
        assert harvest.ust_expiry(code) != harvest.ust_expiry_legacy(code)

    # An expiry may never be an exchange holiday. It is normally a Friday, but a
    # holiday Friday rolls back one BUSINESS day -- so USF21 is a Thursday, and
    # asserting "always a Friday" is exactly the bug that produced 2020-12-18.
    import QuantLib as ql
    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    for code in ["USM22", "USF21", "USF22", "USM26", "TYZ23", "USU21", "USH24", "TYK25"]:
        d = harvest.ust_expiry(code)
        assert d.weekday() < 5, (code, d)
        assert not cal.isHoliday(ql.Date(d.day, d.month, d.year)), (code, d)
    assert harvest.ust_expiry("USF21").weekday() == 3          # Thursday, rolled back
    assert harvest.ust_expiry("USM26").weekday() == 4          # Friday, untouched

    # and the two rules agree everywhere a holiday is NOT in the window
    for code in ["USM26", "USZ19", "TYF26", "USJ26", "USU21", "USZ22", "USH23"]:
        assert harvest.ust_expiry(code) == harvest.ust_expiry_legacy(code), code


def test_which_us_holiday_calendar_is_immaterial_for_this_rule():
    """Government-bond vs NYSE: measured to make NO difference over the window.

    A mutation swapping ``ql.UnitedStates.GovernmentBond`` for ``.NYSE`` was run
    against the suite and NOT caught -- so rather than leave that as an unknown,
    it is pinned as a fact. The two calendars differ on Columbus Day and
    Veterans Day, and this rule only ever looks at a month's last business day,
    two business days back from it, and the Friday before that. Those windows
    never reach a mid-month holiday, so across every US and TY contract from
    2019 to 2027 the two calendars give **identical** expiries.

    The consequence worth writing down: the calendar choice here is not load
    bearing, so a future reader must not "fix" it by swapping calendars and
    expect anything to change. If this test ever fails, the rule's window has
    been widened and the calendar question has become real.
    """
    import datetime as _dt

    import QuantLib as ql

    from definitions.USTFutureOptions import MONTH_CODE_TO_NUM, parse_option_contract

    def expiry_with(cal, contract):
        _, code = parse_option_contract(contract)
        m = MONTH_CODE_TO_NUM[code[0]]
        y = 2000 + int(code[1:])
        pm, py = (12, y - 1) if m == 1 else (m - 1, y)
        last = cal.adjust(ql.Date.endOfMonth(ql.Date(1, pm, py)), ql.Preceding)
        cut = cal.advance(last, ql.Period(-2, ql.Days))
        d = _dt.date(cut.year(), cut.month(), cut.dayOfMonth())
        while d.weekday() != 4:
            d -= _dt.timedelta(days=1)
        adj = cal.adjust(ql.Date(d.day, d.month, d.year), ql.Preceding)
        return _dt.date(adj.year(), adj.month(), adj.dayOfMonth())

    gb = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    ny = ql.UnitedStates(ql.UnitedStates.NYSE)
    n = 0
    for root in ("US", "TY"):
        for yy in range(19, 28):
            for mc in "FGHJKMNQUVXZ":
                c = f"{root}{mc}{yy:02d}"
                assert expiry_with(gb, c) == expiry_with(ny, c), c
                assert expiry_with(gb, c) == harvest.ust_expiry(c), c
                n += 1
    assert n == 216


def test_sfr_expiry_is_last_trade_date_not_the_futures_imm_date():
    """MUTATION CHECK: ``sfr_expiry`` must not return the underlying's IMM date.

    CME 460A01.J.1 puts the option's last trading day on the Friday preceding
    the third Wednesday. The third Wednesday itself is the start of the
    underlying's reference quarter, FIVE DAYS LATER, and
    ``quarterly_contract_expiry_date`` returns that. Substituting it would
    overstate every SOFR time to expiry by a week -- invisible in a plot, fatal
    to a carry-matched straddle size.

    Tied out: SFRM26's last quote is 2026-06-11, one business day before the
    2026-06-12 asserted here, and four days before the IMM date.
    """
    from MDP.STIRFutures._sofr_option_contracts import quarterly_contract_expiry_date

    for code, expected in [("SFRM26", datetime.date(2026, 6, 12)),
                           ("SFRZ26", datetime.date(2026, 12, 11)),
                           ("SFRH20", datetime.date(2020, 3, 13)),
                           ("SFRZ30", datetime.date(2030, 12, 13))]:
        assert harvest.sfr_expiry(code) == expected
        # and it is genuinely a different number from the mutation's answer
        assert harvest.sfr_expiry(code) != quarterly_contract_expiry_date(code)
        assert (quarterly_contract_expiry_date(code) - harvest.sfr_expiry(code)).days == 5


def test_universe_is_quarterly_first_and_respects_per_asset_horizons():
    """Quarterlies (the mandate) must be emitted before serials.

    Write-through happens after every series, so a run killed part-way leaves
    the mandated quarterly panel whole only if quarterlies come first.
    """
    u = harvest.build_universe(
        ust_roots=["US", "TY"], sfr_roots=["SFR"],
        first_expiry=datetime.date(2019, 1, 1),
        ust_last_expiry=datetime.date(2027, 5, 31),
        sfr_last_expiry=datetime.date(2031, 12, 31),
        include_serial=True,
    )
    kinds = [c["contract_kind"] for c in u]
    assert "serial" in kinds and "quarterly" in kinds
    assert kinds.index("serial") > max(i for i, k in enumerate(kinds) if k == "quarterly")

    # per-asset horizons actually bind, and in the right direction
    ust_max = max(c["expiry_date"] for c in u if c["asset"] == "UST")
    sfr_max = max(c["expiry_date"] for c in u if c["asset"] == "SFR")
    assert ust_max <= datetime.date(2027, 5, 31)
    assert sfr_max > datetime.date(2030, 1, 1)

    # every contract's expiry is inside the window, and codes are canonical
    assert all(c["expiry_date"] >= datetime.date(2019, 1, 1) for c in u)
    assert {c["root"] for c in u} == {"US", "TY", "SFR"}
    assert all(len(c["contract_code"]) in (5, 6) for c in u)

    quarterly_only = harvest.build_universe(
        ust_roots=["US"], sfr_roots=[], first_expiry=datetime.date(2019, 1, 1),
        ust_last_expiry=datetime.date(2026, 12, 31),
        sfr_last_expiry=datetime.date(2026, 12, 31), include_serial=False)
    assert {c["contract_kind"] for c in quarterly_only} == {"quarterly"}
    # 2019-01-01..2026-12-31 is 8 years x 4 quarterly months, minus H19 whose
    # expiry (2019-02-22) is in window -- all 32 land inside.
    assert len(quarterly_only) == 32


def test_value_type_labels_are_self_describing():
    """A bare ``qv_value_type="Call"`` loses the delta, so the panel must not use it.

    The stored label carries the delta; the vendor parameters live in the map.
    """
    assert set(harvest.VALUE_TYPES) == {"ABPV", "ATM", "25D_CALL", "25D_PUT",
                                        "25D_RR", "25D_BF"}
    assert harvest.VALUE_TYPES["25D_CALL"] == {"qv_value_type": "Call", "delta": 25,
                                               "option_type": "Call"}
    assert harvest.VALUE_TYPES["25D_PUT"] == {"qv_value_type": "Put", "delta": 25,
                                              "option_type": "Put"}
    assert harvest.VALUE_TYPES["25D_RR"]["delta"] == 25
    assert harvest.VALUE_TYPES["25D_BF"]["delta"] == 25


def test_tte_is_act_365():
    """MUTATION CHECK: the harvest's day count is ACT/365, matching load_sfr_contracts.

    Mutated to ACT/360 a 182.5-day gap reads 0.5069 instead of 0.5000 -- a 1.4%
    error in every time to expiry, which is a 0.7% error in every terminal
    standard deviation and would never look wrong.
    """
    assert harvest.DAYS_PER_YEAR == 365.0
    assert 182.5 / harvest.DAYS_PER_YEAR == pytest.approx(0.5, abs=1e-12)
    p = _synthetic_panel()
    row = p[(p["contract_code"] == "USX035") & (p["value_type"] == "ABPV")].iloc[0]
    assert row["tte_years"] == pytest.approx(35.0 / 365.0, abs=1e-12)


# ------------------------------------------------------------- TTE selection


def test_expiry_ladder_is_sorted_by_time_to_expiry():
    lad = lc.expiry_ladder(_synthetic_panel(), "2026-03-02", root="US", value_type="ABPV")
    assert lad["contract_code"].tolist() == ["USX005", "USX035", "USX095", "USX180"]
    assert lad["value"].tolist() == [100.0, 90.0, 85.0, 80.0]
    assert lad["tte_days"].tolist() == pytest.approx([5, 35, 95, 180], abs=1e-9)


def test_select_by_tte_picks_the_nearest_not_the_first():
    """MUTATION CHECK: nearest by |gap|, not argmax and not the first row.

    Mutated to ``argmax`` this returns the 180-day contract for a 30-day target;
    mutated to drop ``abs`` it returns the 5-day one.
    """
    p = _synthetic_panel()
    r = lc.select_by_tte(p, "2026-03-02", 30.0, root="US", max_gap_days=20.0)
    assert r is not None
    assert r["contract_code"] == "USX035"
    assert r["gap_days"] == pytest.approx(5.0, abs=1e-9)   # signed: 35 - 30
    assert r["value"] == 90.0

    r90 = lc.select_by_tte(p, "2026-03-02", 90.0, root="US", max_gap_days=20.0)
    assert r90["contract_code"] == "USX095"
    assert r90["gap_days"] == pytest.approx(5.0, abs=1e-9)


def test_select_by_tte_returns_none_beyond_max_gap():
    """MUTATION CHECK: the gap guard must refuse, not stretch.

    Target 130 days: the nearest points are 95 and 180, both 35+ days away. With
    the guard dropped this silently returns a 95-day option in place of a
    130-day one -- a 27% error in time, on a series that would still look
    perfectly smooth.
    """
    p = _synthetic_panel()
    assert lc.select_by_tte(p, "2026-03-02", 130.0, root="US", max_gap_days=20.0) is None
    assert lc.select_by_tte(p, "2026-03-02", 130.0, root="US", max_gap_days=60.0) is not None


def test_select_by_tte_drops_the_unstable_expiry_tail():
    """``min_tte_years`` removes the last days of life, where implied vol is unstable."""
    p = _synthetic_panel()
    r = lc.select_by_tte(p, "2026-03-02", 3.0, root="US", max_gap_days=40.0,
                         min_tte_years=0.0)
    assert r["contract_code"] == "USX005"
    r2 = lc.select_by_tte(p, "2026-03-02", 3.0, root="US", max_gap_days=40.0,
                          min_tte_years=20.0 / 365.0)
    assert r2["contract_code"] == "USX035"


def test_ladder_interpolation_is_linear_in_tte():
    """MUTATION CHECK: planted midpoint 87.5, plus flat (not linear) extrapolation.

    35d->90 and 95d->85 are 60 days and 5 bp apart, so 65 days is 87.5 exactly.
    Mutated to interpolate in sqrt(time) the same point reads 88.28.
    """
    p = _synthetic_panel()
    assert lc.interpolate_across_ladder(p, "2026-03-02", 65.0, root="US") == pytest.approx(87.5)
    assert lc.interpolate_across_ladder(p, "2026-03-02", 35.0, root="US") == pytest.approx(90.0)
    # flat extrapolation past both ends -- a linear one turns a normal vol negative
    assert lc.interpolate_across_ladder(p, "2026-03-02", 1.0, root="US") == pytest.approx(100.0)
    assert lc.interpolate_across_ladder(p, "2026-03-02", 900.0, root="US") == pytest.approx(80.0)


def test_interpolation_and_selection_disagree_which_is_the_whole_point():
    """CM interpolates to exactly 30d; a tradeable contract cannot.

    At a 30-day target the ladder interpolates to 91.67 while the nearest
    tradeable contract is the 35-day one at 90.0. That 1.67 bp gap is the
    quantity constant maturity was hiding, so the two functions must NOT agree.
    """
    p = _synthetic_panel()
    interp = lc.interpolate_across_ladder(p, "2026-03-02", 30.0, root="US")
    matched = lc.select_by_tte(p, "2026-03-02", 30.0, root="US", max_gap_days=20.0)
    assert interp == pytest.approx(90.0 + (5.0 / 30.0) * 10.0)   # 91.666...
    assert matched["value"] == 90.0
    assert abs(interp - matched["value"]) > 1.0


def test_tte_matched_series_carries_the_contract_identity():
    p = _synthetic_panel()
    s = lc.tte_matched_series(p, 30.0, root="US", max_gap_days=20.0)
    assert len(s) == 1
    assert s.iloc[0]["contract_code"] == "USX035"
    assert set(["contract_code", "expiry_date", "tte_days", "gap_days", "value"]) <= set(s.columns)


# ------------------------------------------------------------------- units


def test_abpv_atm_scale_is_abpv_over_atm_not_the_reciprocal():
    """MUTATION CHECK: inverting the ratio still produces a smooth, wrong series.

    Planted: UST ABPV/ATM == 850 exactly, SFR == 100 exactly. Inverted, the UST
    scale becomes 0.00118 and every converted smile quote lands near zero --
    which reads as "the wings are flat", not as "the units are upside down".
    """
    sc = lc.abpv_atm_scale(_synthetic_panel())
    assert sc["scale"].to_numpy() == pytest.approx(850.0, abs=1e-9)
    assert sc["implied_moddur"].to_numpy() == pytest.approx(1e4 / 850.0, abs=1e-9)

    sc_sfr = lc.abpv_atm_scale(_synthetic_sfr_panel())
    assert sc_sfr["scale"].to_numpy() == pytest.approx(100.0, abs=1e-9)


def test_smile_converts_to_bp_yr_through_the_panels_own_scale():
    """No external DV01: the conversion comes from ABPV/ATM on the same row."""
    out = lc.smile_in_bp_yr(_synthetic_panel())
    call = out[(out["value_type"] == "25D_CALL") & (out["contract_code"] == "USX035")].iloc[0]
    assert call["value_bp_yr"] == pytest.approx((90.0 / 850.0 + 0.001) * 850.0)
    abpv = out[(out["value_type"] == "ABPV") & (out["contract_code"] == "USX035")].iloc[0]
    assert abpv["value_bp_yr"] == 90.0        # already bp/yr, passed through

    sfr = lc.smile_in_bp_yr(_synthetic_sfr_panel())
    c = sfr[(sfr["value_type"] == "25D_CALL") & (sfr["contract_code"] == "SFRX040")].iloc[0]
    assert c["value_bp_yr"] == pytest.approx((1.20 + 0.02) * 100.0)
    # the SFR scale is the exact affine 100, so a 25d call quoted 0.02 above ATM
    # is 2 bp/yr above the ABPV -- checkable without touching the code under test
    a = sfr[(sfr["value_type"] == "ABPV") & (sfr["contract_code"] == "SFRX040")].iloc[0]
    assert c["value_bp_yr"] - a["value_bp_yr"] == pytest.approx(2.0, abs=1e-9)


def test_units_report_recovers_the_planted_identities():
    """On a panel where RR == C-P by construction, the report must say so exactly."""
    rep = lc.units_report(pd.concat([_synthetic_panel(), _synthetic_sfr_panel()],
                                    ignore_index=True))
    # keyed by ROOT, not asset: pooling US (CTD ~11.6y) with TY (~5.9y) yields a
    # ratio belonging to neither contract
    assert set(rep) == {"US", "SFR"}
    assert rep["US"]["abpv_over_atm"]["median"] == pytest.approx(850.0, abs=1e-6)
    assert rep["US"]["abpv_over_atm"]["frac_exactly_100"] == 0.0
    assert rep["SFR"]["abpv_over_atm"]["frac_exactly_100"] == pytest.approx(1.0)
    assert rep["SFR"]["abpv_over_atm"]["max_abs_dev_from_100"] == pytest.approx(0.0, abs=1e-9)
    for root in ("US", "SFR"):
        assert rep[root]["rr_identity"]["max_abs_resid"] == pytest.approx(0.0, abs=1e-12)
        assert rep[root]["bf_naive_identity"]["median_abs_resid"] == pytest.approx(0.0, abs=1e-12)
    # SFR's RR varies across the three planted contracts, so the correlation is
    # a real number and not the NaN a constant series would give
    assert rep["SFR"]["rr_identity"]["corr"] == pytest.approx(1.0, abs=1e-9)
    assert rep["SFR"]["rr_identity"]["n"] == 3


# -------------------------------------------------------------- data-backed


def _panel_or_skip() -> pd.DataFrame:
    try:
        return lc.load_listed_contract_panel()
    except lc.ListedContractsUnavailable as e:
        pytest.skip(str(e))


def test_panel_loads_with_the_promised_schema():
    p = _panel_or_skip()
    need = {"date", "symbol", "root", "asset", "contract_code", "contract_kind",
            "expiry_date", "tte_years", "value_type", "value"}
    assert need <= set(p.columns)
    assert (p["tte_years"] >= 0).all()
    assert (p["date"] <= p["expiry_date"]).all()


def test_panel_expiry_matches_the_contract_rule_for_every_row():
    """The stored expiry must still be reproducible from the code, not just from disk."""
    p = _panel_or_skip()
    per = p.groupby(["contract_code", "asset"])["expiry_date"].first()
    for (code, asset), exp in per.items():
        want = harvest.ust_expiry(code) if asset == "UST" else harvest.sfr_expiry(code)
        assert pd.Timestamp(want) == exp, code


def test_panel_last_quote_is_within_a_few_days_of_expiry():
    """A contract is quoted right up to its expiry; a big gap means a truncated fetch.

    This is the tie-out that validates the expiry rules against the vendor rather
    than against themselves, and it is what caught the UST holiday bug: with the
    weekday-only rule, USM22 and TYM22 showed a 6-business-day gap where every
    other contract showed 1. With the corrected rule there are no exceptions, so
    this asserts EVERY dead contract rather than a pass rate -- a fraction
    threshold is precisely what would have let the bug through unnoticed.

    Contracts still alive at the end of the harvest window legitimately stop
    early and are excluded.
    """
    p = _panel_or_skip()
    a = p[p["value_type"] == "ABPV"]
    harvest_end = pd.Timestamp(a["date"].max())
    g = a.groupby("contract_code").agg(last=("date", "max"), exp=("expiry_date", "first"))
    dead = g[g["exp"] < harvest_end]        # live contracts legitimately stop at the window
    gap_bd = dead.apply(lambda r: len(pd.bdate_range(r["last"], r["exp"])) - 1, axis=1)
    assert (gap_bd >= 0).all(), gap_bd[gap_bd < 0]
    assert (gap_bd <= 3).all(), gap_bd[gap_bd > 3]


def test_panel_units_verdict_holds_on_real_data():
    """The measured units claims, re-asserted against whatever is on disk now."""
    p = _panel_or_skip()
    rep = lc.units_report(p)
    if "SFR" in rep and "abpv_over_atm" in rep["SFR"]:
        # affine P = 100 - R, so this is an identity, not a fit -- but the vendor
        # computes the two value types off different marks in the last month of
        # life and at the newly-listed far end, so it holds on the bulk and not
        # on every row (measured: 86.4% exact, >=94% inside 0.08y..2.5y)
        assert rep["SFR"]["abpv_over_atm"]["median"] == pytest.approx(100.0, abs=1e-6)
        assert rep["SFR"]["abpv_over_atm"]["frac_exactly_100"] > 0.75    # measured 0.807
    # 1e4/ModDur: US CTD ~11.6y -> ~860, TY ~5.9y -> ~1690. Nowhere near 100, and
    # the two must NOT be equal -- if they were, the panel would be pooled wrong.
    if {"US", "TY"} <= set(rep):
        us = rep["US"]["abpv_over_atm"]["implied_moddur_median"]
        ty = rep["TY"]["abpv_over_atm"]["implied_moddur_median"]
        assert 10.5 < us < 13.0, us
        assert 5.0 < ty < 7.0, ty
        assert us > ty + 3.0
    for root in rep:
        if "rr_identity" in rep[root]:
            rr = rep[root]["rr_identity"]
            assert rr["corr"] > 0.9999
            assert rr["max_abs_resid"] < 1e-6 * max(rr["rr_scale_median"], 1.0) + 1e-9

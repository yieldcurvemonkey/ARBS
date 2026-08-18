"""Tests for the J.P. Morgan tie-out: the swaption-page parser and
:mod:`RVUtils.ConvexityRV.jpm_tieout`.

Three families, and they fail for different reasons on purpose:

``parse_swaption_report``
    Every expected number was read off the fixture PDF by eye first and is
    quoted in the assertion, so a green run means the parser reproduces the
    printed page rather than merely producing *some* number.  Both document
    generations are covered, including the ``12m`` -> ``1y`` relabelling and
    the fact that the historical block is per *tenor*, not per maturity.

pure helpers
    ``contract_code``, ``dedupe``, ``implied_moddur``, ``interp_swaption``,
    ``modal_expiry`` and ``grade_expiry_rule`` are exercised on hand-built
    frames whose right answers are arithmetic, not data.

panel tie-out
    The headline facts from ``jpm_package_tieout``: the date convention, the
    ATM units, the duration bridge, the OTC basis sign and the expiry rule.
    These read the real parquets and skip if they are missing, so a rebuilt
    panel that breaks any of those five claims fails here rather than in a
    notebook nobody re-runs.
"""

from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

fitz = pytest.importorskip("fitz")

from RVUtils.ConvexityRV import jpm_package as jp  # noqa: E402
from RVUtils.ConvexityRV import jpm_tieout as jt  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "jpm_packages"
DATA = jt.DATA_DIR

needs_fixtures = pytest.mark.skipif(
    not (FIX / "jpm_2023-06-09.pdf").exists(),
    reason="run tests/fixtures/build_jpm_package_fixtures.py first")

needs_panels = pytest.mark.skipif(
    not (DATA / "jpm_pkg_treasury_vol.parquet").exists()
    or not (DATA / "jpm_pkg_swaption_vol.parquet").exists()
    or not (DATA / "listed_contract_vol.parquet").exists(),
    reason="run scripts/parse_jpm_packages.py and scripts/parse_jpm_swaptions.py")

LEGACY_TITLE = "Short-Dated Swaption Volatility Report"
SOFR_TITLE = "Short-Dated SOFR Swaption Volatility Report"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def swpn_pages():
    """tag -> (page, PageDates) for the swaption page of each fixture."""
    out, docs = {}, []
    for tag, title in (("2019-08-27", LEGACY_TITLE),
                       ("2023-06-09", SOFR_TITLE),
                       ("2026-08-13", SOFR_TITLE)):
        d = fitz.open(str(FIX / f"jpm_{tag}.pdf"))
        docs.append(d)
        pno = jp.locate_reports(d, [title])[title][0]
        out[tag] = (d[pno - 1], jp.page_dates(d[pno - 1], jp.document_dates(d)))
    yield out
    for d in docs:
        d.close()


def cell(recs, tenor, maturity):
    hits = [r for r in recs
            if r["tenor_years"] == tenor and r["maturity_months"] == maturity]
    assert len(hits) == 1, f"{len(hits)} rows for {tenor}yr {maturity}m"
    return hits[0]


# --------------------------------------------------------------------------
# 1. the swaption page parser, against numbers read off the PDF
# --------------------------------------------------------------------------
@needs_fixtures
@pytest.mark.parametrize("tag", ["2019-08-27", "2023-06-09", "2026-08-13"])
def test_swaption_page_shape(swpn_pages, tag):
    """Five tenors x four maturities, on both generations."""
    recs = jp.parse_swaption_report(swpn_pages[tag][0])
    assert len(recs) == 20
    assert sorted({r["tenor_years"] for r in recs}) == [1, 2, 5, 10, 30]
    assert sorted({r["maturity_months"] for r in recs}) == [1, 3, 6, 12]
    assert all(r["impl_pct"] is not None and r["impl_bp_day"] is not None
               for r in recs)


@needs_fixtures
def test_swaption_legacy_2019_values(swpn_pages):
    """2019-08-26, page 24: "Options on 1yr Swaps / 1m  50.73  5.47  0.11  1.52"."""
    page, dates = swpn_pages["2019-08-27"]
    assert dates.as_of == _dt.date(2019, 8, 26)
    assert dates.business_date == _dt.date(2019, 8, 27)
    recs = jp.parse_swaption_report(page)
    r = cell(recs, 1, 1)
    assert r["impl_pct"] == pytest.approx(50.73)
    assert r["impl_bp_day"] == pytest.approx(5.47)
    assert r["impl_bp_chg_5d"] == pytest.approx(0.11)
    assert r["impl_bp_chg_20d"] == pytest.approx(1.52)
    # the printed grid is monotonically decreasing in maturity for 1yr swaps
    assert [cell(recs, 1, m)["impl_bp_day"] for m in (1, 3, 6, 12)] == \
        pytest.approx([5.47, 5.06, 4.87, 4.56])
    # and the far corner of the page
    assert cell(recs, 30, 12)["impl_pct"] == pytest.approx(40.96)
    assert cell(recs, 30, 12)["impl_bp_day"] == pytest.approx(4.22)


@needs_fixtures
def test_swaption_sofr_2023_values(swpn_pages):
    """2023-06-08, page 25 -- the date the whole tie-out is spot-checked on."""
    page, dates = swpn_pages["2023-06-09"]
    assert dates.as_of == _dt.date(2023, 6, 8)
    recs = jp.parse_swaption_report(page)
    assert [cell(recs, 10, m)["impl_pct"] for m in (1, 3, 6, 12)] == \
        pytest.approx([30.75, 31.05, 31.67, 32.40])
    assert [cell(recs, 10, m)["impl_bp_day"] for m in (1, 3, 6, 12)] == \
        pytest.approx([6.64, 6.63, 6.64, 6.60])
    assert cell(recs, 30, 1)["impl_bp_day"] == pytest.approx(5.16)
    assert cell(recs, 30, 1)["impl_pct"] == pytest.approx(25.66)
    assert cell(recs, 1, 12)["impl_bp_day"] == pytest.approx(9.79)
    assert cell(recs, 2, 1)["impl_bp_day"] == pytest.approx(10.51)


@needs_fixtures
def test_swaption_v2025_values_and_1y_label(swpn_pages):
    """2026-08-12: the v2025 layout prints ``1y`` where legacy printed ``12m``."""
    page, dates = swpn_pages["2026-08-13"]
    assert dates.as_of == _dt.date(2026, 8, 12)
    recs = jp.parse_swaption_report(page)
    assert {r["maturity_label"] for r in recs} == {"1m", "3m", "6m", "1y"}
    assert cell(recs, 12 // 12, 12)["maturity_label"] == "1y"
    assert cell(recs, 1, 1)["impl_pct"] == pytest.approx(18.58)
    assert cell(recs, 1, 1)["impl_bp_day"] == pytest.approx(4.74)
    assert cell(recs, 1, 1)["impl_bp_chg_5d"] == pytest.approx(-0.01)
    assert cell(recs, 1, 1)["impl_bp_chg_20d"] == pytest.approx(0.07)
    assert cell(recs, 10, 1)["impl_bp_day"] == pytest.approx(4.33)
    assert cell(recs, 30, 12)["impl_pct"] == pytest.approx(16.11)


@needs_fixtures
@pytest.mark.parametrize("tag,tenor,daily,chg", [
    ("2019-08-27", 10, (6.14, 6.66, 4.97), (6.66, 5.98, 4.83)),
    ("2023-06-09", 10, (7.84, 6.08, 7.43), (6.08, 5.28, 4.66)),
    ("2026-08-13", 30, (3.69, 3.27, 3.12), (3.27, 2.06, 1.43)),
])
def test_swaption_historicals_are_per_tenor(swpn_pages, tag, tenor, daily, chg):
    """The historical block belongs to the tenor, not the maturity.

    The page prints one 10d/20d/60d triple and one 1dc/1wc/2wc triple per
    ``Options on <n>yr Swaps`` block, laid out beside the ``1m`` and ``6m``
    rows.  Reading them as per-maturity numbers -- which the raw text order
    invites -- would put a realised vol on three maturities that never had one.
    """
    recs = jp.parse_swaption_report(swpn_pages[tag][0])
    block = [r for r in recs if r["tenor_years"] == tenor]
    for r in block:
        assert (r["hist_bp_10d"], r["hist_bp_20d"], r["hist_bp_60d"]) == \
            pytest.approx(daily)
        assert (r["hist_bp_1dc"], r["hist_bp_1wc"], r["hist_bp_2wc"]) == \
            pytest.approx(chg)


@needs_fixtures
def test_swaption_blank_page_raises_empty_not_zeros():
    """2025-06-12 prints the grid with every cell blank.

    That is a legitimate state -- J.P. Morgan published the page without the
    numbers -- and it must surface as :class:`JpmEmptyPage` so the batch driver
    counts it as ``parsed_empty``.  Returning rows of ``None`` would put nine
    dates of silent holes into the OTC leg of test 4.
    """
    if not (FIX / "jpm_2025-06-12.pdf").exists():
        pytest.skip("rebuild fixtures for the blank-page case")
    d = fitz.open(str(FIX / "jpm_2025-06-12.pdf"))
    try:
        pno = jp.locate_reports(d, [SOFR_TITLE])[SOFR_TITLE][0]
        with pytest.raises(jp.JpmEmptyPage):
            jp.parse_swaption_report(d[pno - 1])
    finally:
        d.close()


def test_subseq_finds_a_run_anywhere_and_reports_absence():
    """The header/caption matcher must not be anchored to the row start."""
    assert jp._subseq(["a", "b", "c"], ["b", "c"]) == 1
    assert jp._subseq(["Mat", "%", "bp"], ["Mat", "%"]) == 0
    assert jp._subseq(["a", "b"], ["b", "a"]) == -1
    assert jp._subseq([], ["a"]) == -1


@needs_fixtures
def test_swaption_rejects_a_page_it_does_not_understand(swpn_pages):
    """A non-swaption page must hard-fail, not return an empty list."""
    d = fitz.open(str(FIX / "jpm_2023-06-09.pdf"))
    try:
        pno = jp.locate_reports(d, ["Treasury Volatility Summary"])[
            "Treasury Volatility Summary"][0]
        with pytest.raises(jp.JpmParseError):
            jp.parse_swaption_report(d[pno - 1])
    finally:
        d.close()


@needs_fixtures
def test_swaption_titles_are_both_locatable(swpn_pages):
    """The LIBOR-era and SOFR-era titles must not shadow each other."""
    assert LEGACY_TITLE in jp.REPORT_TITLES and SOFR_TITLE in jp.REPORT_TITLES
    d = fitz.open(str(FIX / "jpm_2023-06-09.pdf"))
    try:
        loc = jp.locate_reports(d, [LEGACY_TITLE, SOFR_TITLE])
        assert SOFR_TITLE in loc and LEGACY_TITLE not in loc
    finally:
        d.close()


# --------------------------------------------------------------------------
# 2. pure helpers
# --------------------------------------------------------------------------
@pytest.mark.parametrize("root,ym,code", [
    ("US", "2023-07", "USN23"),   # the Jul-23 column = USN23, expiring 2023-06-23
    ("TY", "2023-12", "TYZ23"),
    ("FV", "2020-01", "FVF20"),
    ("US", "2026-06", "USM26"),
])
def test_contract_code(root, ym, code):
    assert jt.contract_code(root, ym) == code


def test_contract_code_covers_all_twelve_months():
    got = [jt.contract_code("US", f"2024-{m:02d}") for m in range(1, 13)]
    assert [c[2] for c in got] == list("FGHJKMNQUVXZ")


def test_dedupe_keeps_first_and_counts():
    # the values differ so that keep="last" would be caught, not just the count
    df = pd.DataFrame({"k": [1, 1, 2], "v": [10, 11, 20]})
    out, n = jt.dedupe(df, ["k"])
    assert n == 1 and len(out) == 2
    assert out["v"].tolist() == [10, 20]


def test_implied_moddur_is_the_price_over_yield_vol_identity():
    # a 30-year bond with ModDur 12: 6 bp/day yield vol -> 6*sqrt(252) bp/yr
    abpv = 6.0 * jt.SQRT_252
    price_vol_pct = 12.0 * abpv / 1e4 * 100.0
    assert jt.implied_moddur([price_vol_pct], [abpv])[0] == pytest.approx(12.0)
    # and it is linear in the price vol
    assert jt.implied_moddur([2 * price_vol_pct], [abpv])[0] == pytest.approx(24.0)


def test_implied_moddur_returns_nan_not_inf_on_zero_vol():
    out = jt.implied_moddur([10.0, 10.0], [0.0, np.nan])
    assert np.isnan(out).all()


def _toy_grid():
    idx = pd.DatetimeIndex(["2023-06-08", "2023-06-09"])
    cols = pd.MultiIndex.from_tuples([(t, m) for t in (1, 2, 5, 10, 30)
                                      for m in (1, 3, 6, 12)])
    # value = tenor-independent in the first date so interpolation is checkable
    vals = np.tile(np.repeat([10.0, 20.0, 30.0, 40.0, 50.0], 4), (2, 1))
    vals[:, 1::4] = vals[:, 0::4] + 1.0     # 3m node = 1m node + 1
    return pd.DataFrame(vals, index=idx, columns=cols)


def test_interp_swaption_hits_the_printed_nodes_exactly():
    g = _toy_grid()
    out = jt.interp_swaption(g, ["2023-06-08"] * 3, [1, 10, 30], [1, 1, 1])
    assert out == pytest.approx([10.0, 40.0, 50.0])


def test_interp_swaption_is_log_linear_in_tenor():
    """A tenor midway in *log* space between 1 and 2 must land midway in value."""
    g = _toy_grid()
    mid = float(np.sqrt(1 * 2))
    out = jt.interp_swaption(g, ["2023-06-08"], [mid], [1])
    assert out[0] == pytest.approx(15.0)
    # ... and NOT at the linear-in-tenor answer for a wider bracket
    lin = jt.interp_swaption(g, ["2023-06-08"], [float(np.sqrt(10 * 30))], [1])
    assert lin[0] == pytest.approx(45.0)
    assert lin[0] != pytest.approx(40 + (20 - 10) * (np.sqrt(300) - 10) / 20)


def test_interp_swaption_clips_rather_than_extrapolates():
    g = _toy_grid()
    lo = jt.interp_swaption(g, ["2023-06-08"], [0.25], [1])
    hi = jt.interp_swaption(g, ["2023-06-08"], [50.0], [1])
    assert lo[0] == pytest.approx(10.0) and hi[0] == pytest.approx(50.0)


def test_interp_swaption_returns_nan_for_a_missing_date():
    g = _toy_grid()
    assert np.isnan(jt.interp_swaption(g, ["2020-01-02"], [10], [1])[0])


def test_modal_expiry_survives_one_wrong_page():
    jpm = pd.DataFrame({
        "as_of": pd.to_datetime(["2022-05-02", "2022-05-03", "2022-05-04"]),
        "root": "US", "contract_code": "USM22",
        "days_cal": [18, 17, 99],       # the third page is wrong
    })
    out = jt.modal_expiry(jpm)
    assert len(out) == 1
    assert out.loc[0, "jpm_expiry"] == pd.Timestamp("2022-05-20")
    assert out.loc[0, "n_dates"] == 3 and out.loc[0, "n_modal"] == 2


def test_grade_expiry_rule_records_a_raising_rule_as_an_error():
    def boom(code):
        raise ValueError("no rule")
    out = jt.grade_expiry_rule(["USM22"], boom)
    assert out.loc[0, "expiry"] is pd.NaT
    assert "ValueError" in out.loc[0, "error"]


def test_join_treasury_honours_the_date_lag():
    jpm = pd.DataFrame({"as_of": pd.to_datetime(["2023-06-08"]),
                        "business_date": pd.to_datetime(["2023-06-09"]),
                        "root": ["US"], "contract_code": ["USN23"],
                        "days_cal": [15]})
    listed = pd.DataFrame({"date": pd.to_datetime(["2023-06-08"]),
                           "root": ["US"], "contract_code": ["USN23"],
                           "expiry_date": pd.to_datetime(["2023-06-23"]),
                           "ATM": [0.11065]})
    hit = jt.join_treasury(jpm, listed)
    assert len(hit) == 1
    assert hit.loc[0, "jpm_implied_expiry"] == pd.Timestamp("2023-06-23")
    assert len(jt.join_treasury(jpm, listed, lag_days=1)) == 0
    # business_date-1 lands on the same day here, which is exactly why it is
    # the dangerous wrong answer
    assert len(jt.join_treasury(jpm, listed, date_col="business_date",
                                lag_days=-1)) == 1


# --------------------------------------------------------------------------
# 3. the panel tie-out itself
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def panels():
    jpm = jt.load_jpm_treasury()
    listed = jt.load_listed_pivot()
    return jpm, listed, jt.join_treasury(jpm, listed)


@needs_panels
def test_date_convention_is_as_of_lag_zero(panels):
    """Only ``as_of+0`` satisfies as_of + Days-to-Expiration == our expiry."""
    jpm, listed, _ = panels
    scores = {}
    for col, lag in (("as_of", 0), ("as_of", -1), ("as_of", 1),
                     ("business_date", 0), ("business_date", -1)):
        m = jt.join_treasury(jpm, listed, date_col=col, lag_days=lag)
        scores[f"{col}{lag:+d}"] = ((m["jpm_implied_expiry"] == m["expiry_date"]).mean(),
                                    len(m))
    assert scores["as_of+0"][0] == 1.0
    # the wrong days are not merely worse, they are ~0: a couple of rows in
    # 21,054 survive by coincidence when a holiday makes two rules agree
    assert scores["as_of-1"][0] < 0.001 and scores["as_of+1"][0] < 0.001
    assert scores["business_date+0"][0] < 0.001
    # the near-alias: right on 99.2% but not 100%, and 2,618 rows short
    assert 0.98 < scores["business_date-1"][0] < 1.0
    assert scores["business_date-1"][1] < scores["as_of+0"][1]


@needs_panels
@pytest.mark.parametrize("root", ["US", "TY"])
def test_atm_is_a_lognormal_price_vol_as_a_decimal(panels, root):
    """our ATM x 100 == JPM's printed price vol, per root, never pooled."""
    _, _, J = panels
    g = J[J["root"] == root].dropna(subset=["ATM", "pct_impl_current"])
    assert len(g) > 5000
    ratio = g["ATM"] * 100 / g["pct_impl_current"]
    assert ratio.median() == pytest.approx(1.0, abs=0.002)
    assert ratio.quantile(0.75) - ratio.quantile(0.25) < 0.005
    err = (g["ATM"] * 100 - g["pct_impl_current"]).abs()
    assert err.median() < 0.01          # JPM prints to 2 dp
    # a scale error of 100 or 1/100 would be caught by the median ratio; make
    # sure the test would actually notice one
    assert not np.isclose(ratio.median(), 100.0, rtol=0.5)


@needs_panels
@pytest.mark.parametrize("root,lo,hi", [("US", 11.0, 12.3), ("TY", 5.6, 6.2)])
def test_duration_bridge_recovers_the_store_ctd_duration(panels, root, lo, hi):
    """JPM's percent over OUR ABPV lands on the measured CTD modified duration."""
    _, _, J = panels
    ctd = pd.read_parquet(DATA / "ust_ctd_fv01.parquet")[
        ["root", "date", "ctd_mod_duration"]].rename(columns={"date": "as_of"})
    g = J[J["root"] == root].merge(ctd, on=["as_of", "root"], how="inner")
    dur = pd.Series(jt.implied_moddur(g["pct_impl_current"], g["ABPV"]))
    assert len(dur.dropna()) > 1000
    assert lo < dur.median() < hi
    r = (dur.to_numpy() / g["ctd_mod_duration"].to_numpy())
    assert np.nanmedian(r) == pytest.approx(1.0, abs=0.03)


@needs_panels
def test_jpm_own_bp_column_implies_a_longer_bond_than_ours_for_US(panels):
    """The disagreement must not be quietly lost: ABPV/(JPM bp*sqrt252) > 1.02."""
    _, _, J = panels
    g = J[J["root"] == "US"].dropna(subset=["ABPV", "bp_impl_current"])
    r = g["ABPV"] / (g["bp_impl_current"] * jt.SQRT_252)
    assert len(r) > 5000
    assert r.median() > 1.02
    ty = J[J["root"] == "TY"].dropna(subset=["ABPV", "bp_impl_current"])
    rty = ty["ABPV"] / (ty["bp_impl_current"] * jt.SQRT_252)
    assert rty.median() < r.median()   # TY reconciles far better than US


@needs_panels
def test_listed_runs_above_otc_on_jpms_own_two_pages():
    """The headline claim, tested entirely on J.P. Morgan's data."""
    jpm = jt.load_jpm_treasury()
    grid = jt.swaption_grid(jt.load_jpm_swaptions())
    pair = {"US": 30.0, "TY": 10.0, "FV": 5.0}
    a = jpm[jpm["root"].isin(pair)].dropna(subset=["bp_impl_current", "days_cal"])
    a = a[a["bp_impl_current"] > 0]     # a printed 0.0 bp is a dashed cell
    otc = jt.interp_swaption(grid, a["as_of"], a["root"].map(pair),
                             a["days_cal"] / 30.4375)
    ratio = pd.Series(otc / a["bp_impl_current"].to_numpy(), index=a.index)
    for root in pair:
        sub = ratio[a["root"] == root].dropna()
        assert len(sub) > 5000, root
        assert 0.88 < sub.median() < 0.99, f"{root}: {sub.median():.4f}"
    # and the ordering JPM's own marks imply: the longer the bond, the wider
    assert (ratio[a["root"] == "US"].median()
            < ratio[a["root"] == "FV"].median())


@needs_panels
def test_otc_exchange_ratio_page_never_publishes_an_implied():
    """The page that looks like the right test publishes no implied ratio."""
    otc, _ = jt.dedupe(pd.read_parquet(DATA / "jpm_pkg_otc_exchange_ratio.parquet"),
                       ["as_of", "panel"])
    assert otc["as_of"].nunique() > 1200
    assert otc["implied_current"].notna().sum() == 0
    assert otc["implied_avg"].notna().sum() == 0
    # ... while the cells that DO populate are a model FV and a realised vol
    assert otc["implied_fv"].notna().mean() > 0.7
    assert otc["historical_current"].notna().mean() > 0.7


@needs_panels
def test_expiry_rules_graded_against_jpms_days_to_expiration():
    """Our corrected rule is exact; the repo's legacy rule fails on holidays."""
    from scripts.harvest_listed_contract_vol import ust_expiry, ust_expiry_legacy

    me = jt.modal_expiry(jt.load_jpm_treasury())
    assert len(me) > 250
    new = jt.grade_expiry_rule(me["contract_code"], ust_expiry)
    old = jt.grade_expiry_rule(me["contract_code"], ust_expiry_legacy)
    ok_new = (new["expiry"].to_numpy() == me["jpm_expiry"].to_numpy())
    ok_old = (old["expiry"].to_numpy() == me["jpm_expiry"].to_numpy())
    assert ok_new.all(), me.loc[~ok_new, "contract_code"].tolist()
    bad = set(me.loc[~ok_old, "contract_code"])
    assert bad == {"USF21", "USF22", "USF27", "USM22",
                   "TYF21", "TYF22", "TYM22",
                   "FVF21", "FVF22", "FVM22"}


def test_legacy_expiry_rule_returns_christmas_day():
    """The concrete defect, independent of any panel."""
    from scripts.harvest_listed_contract_vol import ust_expiry, ust_expiry_legacy

    assert ust_expiry_legacy("USF21") == _dt.date(2020, 12, 25)
    assert ust_expiry("USF21") == _dt.date(2020, 12, 24)
    # Memorial Day 2022-05-30 counted as a business day moves USM22 a week
    assert ust_expiry_legacy("USM22") == _dt.date(2022, 5, 27)
    assert ust_expiry("USM22") == _dt.date(2022, 5, 20)


@needs_panels
def test_jpm_midcurves_do_not_overlap_our_sofr_probe():
    """Test 6 is a coverage fact, and the number that decides it is zero."""
    mc, _ = jt.dedupe(pd.read_parquet(DATA / "jpm_pkg_midcurve_vol.parquet"),
                      ["as_of", "product", "expiry_ym"])
    assert mc["product"].str.startswith("Eurodollar").all()
    live = mc.dropna(subset=["pct_impl_current"])
    probe = pd.read_parquet(DATA / "sofr_midcurve_probe.parquet")
    ours = probe[probe["is_midcurve"]]
    assert len(ours) > 0
    overlap = set(live["as_of"].dt.normalize()) & set(ours["date"].dt.normalize())
    assert overlap == set()
    assert live["as_of"].max() < ours["date"].min()

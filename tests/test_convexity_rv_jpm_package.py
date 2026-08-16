"""Tests for :mod:`RVUtils.ConvexityRV.jpm_package`.

Fixtures are page extracts from three real J.P. Morgan *U.S. Futures and
Options Package* issues, built by
``tests/fixtures/build_jpm_package_fixtures.py`` (gitignored; rebuild if
missing).  Every expected number in this file was read off the PDF by eye
first and is quoted in the assertion, so a "green" run means the parser
reproduces the printed page, not merely that it produced *some* number.

Coverage of the two document generations:

``legacy`` (2019-08-27 .. 2024-11-17)
    cover "As of 3:00 pm" / "For Business", page header "08 June 2023",
    "Mon YY" column headers, decimal money-market futures prices.

``v2025`` (2024-12-12 .. 2026-08-13)
    no cover dates, page header "Dec 11, 2024" or "Closes as Of: Aug 12,
    2026", glued "Jan25" column headers, "Change(5d)" with no space,
    "Implied (bp) per day" section labels, the "VOLATLITY" typo, glued
    "$167.35$167.35" cells, and money-market futures prices in 32nds.
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

fitz = pytest.importorskip("fitz")

from RVUtils.ConvexityRV import jpm_package as jp  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "jpm_packages"

pytestmark = pytest.mark.skipif(
    not (FIX / "jpm_2023-06-09.pdf").exists(),
    reason="run tests/fixtures/build_jpm_package_fixtures.py first",
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def docs():
    out = {}
    for tag in ("2019-08-27", "2023-06-09", "2024-12-12", "2026-08-13"):
        out[tag] = fitz.open(str(FIX / f"jpm_{tag}.pdf"))
    yield out
    for d in out.values():
        d.close()


def _page(doc, title, which=0):
    loc = jp.locate_reports(doc)
    assert title in loc, f"{title!r} not located; got {sorted(loc)}"
    return doc[loc[title][which] - 1]


def _by_expiry(recs, product):
    return {r["expiry_label"]: r for r in recs if r["product"] == product}


# --------------------------------------------------------------------------
# 1. locator
# --------------------------------------------------------------------------
def test_locator_finds_reports_by_title_not_index(docs):
    """The same report sits on different pages in different vintages."""
    l19 = jp.locate_reports(docs["2019-08-27"])
    l23 = jp.locate_reports(docs["2023-06-09"])
    l26 = jp.locate_reports(docs["2026-08-13"])
    assert "Eurodollar MidCurve Volatility Summary" in l19
    assert set(l23) >= {"Treasury Volatility Summary",
                        "Eurodollar Volatility Summary",
                        "Eurodollar MidCurve Volatility Summary",
                        "Treasury OTC and Exchange Volatility",
                        "Maturity Structure of Treasury Volatility",
                        "U.S. Treasuries Volatility Skew Report"}
    # the v2025 generation carries no Eurodollar / OTC / skew pages at all
    assert "Eurodollar MidCurve Volatility Summary" not in l26
    assert "Treasury OTC and Exchange Volatility" not in l26
    assert "U.S. Treasuries Volatility Skew Report" not in l26
    # ...and prints "Treasury Volatility Summary" on TWO pages
    assert len(l26["Treasury Volatility Summary"]) == 2


def test_locator_skips_the_table_of_contents(docs):
    """Page 1 lists every report title; it must never be returned."""
    for doc in docs.values():
        for pages in jp.locate_reports(doc).values():
            assert 1 not in pages


# --------------------------------------------------------------------------
# 2. dates
# --------------------------------------------------------------------------
def test_legacy_dates_come_from_the_cover(docs):
    d = jp.document_dates(docs["2023-06-09"])
    assert d.generation == "legacy"
    # cover: "As of 3:00 pm Thursday, June 08, 2023" /
    #        "For Business: Friday, June 09, 2023"
    assert d.as_of == datetime.date(2023, 6, 8)
    assert d.business_date == datetime.date(2023, 6, 9)


def test_v2025_dates_come_from_the_page_header(docs):
    """The v2025 cover carries no dates; the report page does."""
    d24 = jp.document_dates(docs["2024-12-12"])
    assert d24.generation == "v2025"
    assert d24.as_of == datetime.date(2024, 12, 11)     # header "Dec 11, 2024"
    assert d24.business_date == datetime.date(2024, 12, 12)

    d26 = jp.document_dates(docs["2026-08-13"])
    assert d26.generation == "v2025"
    # header "Closes as Of: Aug 12, 2026"
    assert d26.as_of == datetime.date(2026, 8, 12)
    assert d26.business_date == datetime.date(2026, 8, 13)


def test_as_of_is_the_close_and_business_date_is_the_next_day(docs):
    for tag in ("2019-08-27", "2023-06-09", "2024-12-12", "2026-08-13"):
        d = jp.document_dates(docs[tag])
        assert d.as_of < d.business_date, tag


# --------------------------------------------------------------------------
# 3. Treasury Volatility Summary -- values read off the 2023-06-08 page
# --------------------------------------------------------------------------
def test_treasury_vol_summary_legacy_matches_the_printed_page(docs):
    page = _page(docs["2023-06-09"], "Treasury Volatility Summary")
    recs = jp.parse_vol_summary(page, as_of=datetime.date(2023, 6, 8))
    assert len(recs) == 12
    assert sorted({r["product"] for r in recs}) == [
        "5 Year Treasury Note", "Treasury Bond", "Treasury Note"]

    bond = _by_expiry(recs, "Treasury Bond")
    # printed: Implied Current  11.07  11.12  11.40  11.51
    assert [bond[k]["pct_impl_current"] for k in ("Jul 23", "Aug 23", "Sep 23", "Dec 23")] \
        == [11.07, 11.12, 11.40, 11.51]
    # printed: Change (1d)  -0.34  -0.21  -0.15  -0.16
    assert bond["Jul 23"]["pct_impl_chg_1d"] == -0.34
    # printed: 20 day High 13.96 / 20 day Low 10.66 / Business Day 11.24
    assert bond["Jul 23"]["pct_impl_high_20d"] == 13.96
    assert bond["Jul 23"]["pct_impl_low_20d"] == 10.66
    assert bond["Jul 23"]["pct_impl_business_day"] == 11.24
    # printed: BASIS POINT VOLATILITY / Implied (bp) Current 5.8 5.9 6.0 6.1
    assert [bond[k]["bp_impl_current"] for k in ("Jul 23", "Aug 23", "Sep 23", "Dec 23")] \
        == [5.8, 5.9, 6.0, 6.1]
    # printed: Cal/Bus Days to Expiry 15/10 ... 169/116
    assert (bond["Jul 23"]["days_cal"], bond["Jul 23"]["days_bus"]) == (15, 10)
    assert (bond["Dec 23"]["days_cal"], bond["Dec 23"]["days_bus"]) == (169, 116)
    # printed: BPV per Contract $185.68 / Futures Price 127-20
    assert bond["Jul 23"]["bpv_per_contract"] == 185.68
    assert bond["Jul 23"]["futures_price_raw"] == "127-20"
    assert bond["Jul 23"]["futures_price"] == pytest.approx(127 + 20 / 32)
    # the Bond block's % historical rows are dashed, and its *bp* historical
    # rows carry the '*' marker ("taken from old otr bond").  The marker is a
    # per-column fact: it must NOT leak onto the Note / 5-Year blocks.
    assert bond["Jul 23"]["pct_hist_10d"] is None
    assert bond["Jul 23"]["bp_hist_10d"] == 4.9
    assert all(bond[k]["hist_from_old_otr"] is True for k in bond)
    assert all(r["hist_from_old_otr"] is False
               for r in recs if r["product"] != "Treasury Bond")

    note = _by_expiry(recs, "Treasury Note")
    # printed:  7.24  7.10  7.34  7.41 ; Historical 10 day 8.10 ; 113-235
    assert [note[k]["pct_impl_current"] for k in ("Jul 23", "Aug 23", "Sep 23", "Dec 23")] \
        == [7.24, 7.10, 7.34, 7.41]
    assert note["Jul 23"]["pct_hist_10d"] == 8.10
    assert note["Sep 23"]["futures_price_raw"] == "113-235"
    assert note["Sep 23"]["futures_price"] == pytest.approx(113 + 23.5 / 32)

    five = _by_expiry(recs, "5 Year Treasury Note")
    # printed:  5.89  5.61  5.69  5.65
    assert [five[k]["pct_impl_current"] for k in ("Jul 23", "Aug 23", "Sep 23", "Dec 23")] \
        == [5.89, 5.61, 5.69, 5.65]


def test_treasury_vol_summary_v2025_layout(docs):
    """2026-08-12: unequal column counts, glued BPV cells, VOLATLITY typo."""
    page = _page(docs["2026-08-13"], "Treasury Volatility Summary", 0)
    recs = jp.parse_vol_summary(page, as_of=datetime.date(2026, 8, 12))
    # Treasury Bond has FIVE expiry columns here, the other two have four
    counts = {p: sum(1 for r in recs if r["product"] == p)
              for p in {r["product"] for r in recs}}
    assert counts == {"Treasury Bond": 5, "Treasury Note": 4,
                      "5 Year Treasury Note": 4}
    bond = _by_expiry(recs, "Treasury Bond")
    # printed: 8.70 9.28 9.41 9.67 9.74
    assert [bond[k]["pct_impl_current"]
            for k in ("Sep 26", "Oct 26", "Nov 26", "Dec 26", "Jan 27")] \
        == [8.70, 9.28, 9.41, 9.67, 9.74]
    # the bond block's basis-point rows are dashed on this date
    assert bond["Sep 26"]["bp_impl_current"] is None
    # "$161.52 $167.35 $167.35$167.35 $173.57" -- the third token is glued
    assert [bond[k]["bpv_per_contract"]
            for k in ("Sep 26", "Oct 26", "Nov 26", "Dec 26", "Jan 27")] \
        == [161.52, 167.35, 167.35, 167.35, 173.57]
    note = _by_expiry(recs, "Treasury Note")
    assert note["Sep 26"]["bp_impl_current"] == 4.6
    assert note["Sep 26"]["futures_price"] == pytest.approx(108 + 17.5 / 32)


def test_v2025_second_page_is_sofr_despite_the_treasury_title(docs):
    """The v2025 SOFR page is mis-titled; routing must use the product."""
    page = _page(docs["2026-08-13"], "Treasury Volatility Summary", 1)
    recs = jp.parse_vol_summary(page, as_of=datetime.date(2026, 8, 12))
    assert {r["product"] for r in recs} == {"Secured ON Financing Rate 3M"}
    assert jp.product_family("Secured ON Financing Rate 3M") == "stir"
    assert jp.product_family("Treasury Bond") == "treasury"
    assert jp.product_family("Eurodollar 1Yr MidCurve") == "midcurve"
    d = _by_expiry(recs, "Secured ON Financing Rate 3M")
    # printed: Aug 26 12.19, Sep 26 11.21 ; bp 2.9 / 2.7 ; 96-06 for both
    assert d["Aug 26"]["pct_impl_current"] == 12.19
    assert d["Sep 26"]["pct_impl_current"] == 11.21
    assert d["Aug 26"]["bp_impl_current"] == 2.9
    assert d["Aug 26"]["futures_price_raw"] == "96-06"
    assert d["Aug 26"]["futures_price"] == pytest.approx(96 + 6 / 32)
    assert d["Aug 26"]["bpv_per_contract"] == 25.0


def test_v2025_dec2024_label_variants(docs):
    """"Jan25" column headers, "Change(5d)", "Implied (bp) per day"."""
    page = _page(docs["2024-12-12"], "Treasury Volatility Summary", 0)
    recs = jp.parse_vol_summary(page, as_of=datetime.date(2024, 12, 11))
    bond = _by_expiry(recs, "Treasury Bond")
    assert set(bond) == {"Jan 25", "Feb 25", "Mar 25", "Apr 25", "Jun 25"}
    assert bond["Jan 25"]["expiry_ym"] == "2025-01"
    # printed: Implied (%) Current 8.39 9.88 10.46 11.00 11.23
    assert [bond[k]["pct_impl_current"]
            for k in ("Jan 25", "Feb 25", "Mar 25", "Apr 25", "Jun 25")] \
        == [8.39, 9.88, 10.46, 11.00, 11.23]
    # printed under "Implied (bp) per day": Current 4.5 ; Change(5d) -1.0
    assert bond["Jan 25"]["bp_impl_current"] == 4.5
    assert bond["Jan 25"]["bp_impl_chg_5d"] == -1.0
    assert bond["Jan 25"]["bp_impl_chg_20d"] == -1.7


def test_eurodollar_summary_prices_are_decimal_not_32nds(docs):
    page = _page(docs["2023-06-09"], "Eurodollar Volatility Summary")
    recs = jp.parse_vol_summary(page, as_of=datetime.date(2023, 6, 8))
    assert {r["product"] for r in recs} == {"Eurodollar"}
    jun = _by_expiry(recs, "Eurodollar")["Jun 23"]
    assert jun["futures_price_raw"] == "94.460"
    assert jun["futures_price"] == pytest.approx(94.460)
    assert jun["pct_impl_current"] == 10.31


# --------------------------------------------------------------------------
# 4. MidCurve: populated in 2019, legitimately empty in 2023
# --------------------------------------------------------------------------
def test_midcurve_populated_2019(docs):
    page = _page(docs["2019-08-27"], "Eurodollar MidCurve Volatility Summary")
    recs = jp.parse_vol_summary(page, as_of=datetime.date(2019, 8, 26))
    assert len(recs) == 21
    one = _by_expiry(recs, "Eurodollar 1Yr MidCurve")
    # printed: 73.54 75.53 72.02 70.51 66.23 ; bp 6.3 ; futures 98.675
    assert [one[k]["pct_impl_current"]
            for k in ("Sep 19", "Oct 19", "Nov 19", "Dec 19", "Mar 20")] \
        == [73.54, 75.53, 72.02, 70.51, 66.23]
    assert one["Sep 19"]["bp_impl_current"] == 6.3
    assert one["Sep 19"]["futures_price"] == pytest.approx(98.675)
    # the 5Yr block is entirely dashed even on this date
    five = _by_expiry(recs, "Eurodollar 5Yr MidCurve")
    assert all(r["pct_impl_current"] is None for r in five.values())


def test_midcurve_all_dashes_raises_empty_not_failure(docs):
    """2023-06-08's MidCurve page matches the layout but carries no numbers."""
    page = _page(docs["2023-06-09"], "Eurodollar MidCurve Volatility Summary")
    with pytest.raises(jp.JpmEmptyPage):
        jp.parse_vol_summary(page, as_of=datetime.date(2023, 6, 8))
    # JpmEmptyPage must remain distinguishable from a genuine parse failure
    assert issubclass(jp.JpmEmptyPage, jp.JpmParseError)


# --------------------------------------------------------------------------
# 5. OTC / exchange ratios
# --------------------------------------------------------------------------
def test_otc_exchange_five_cells_per_panel(docs):
    page = _page(docs["2023-06-09"], "Treasury OTC and Exchange Volatility")
    recs = {r["panel"]: r for r in jp.parse_otc_exchange(page)}
    assert set(recs) == {"OTC 30's / CBOT 30's", "OTC 10's / CBOT 10's",
                         "OTC 5's / CBOT 5's",
                         "OTC 2's / 1-Yr Eurodollar midcurves"}
    p30 = recs["OTC 30's / CBOT 30's"]
    # printed:            Current  6M Avg   FV
    #          Implied      N/A     N/A    0.84
    #          Historical  0.93    1.02
    assert p30["implied_current"] is None
    assert p30["implied_avg"] is None
    assert p30["implied_fv"] == 0.84
    assert p30["historical_current"] == 0.93
    assert p30["historical_avg"] == 1.02
    assert "historical_fv" not in p30          # Historical has no FV column
    p10 = recs["OTC 10's / CBOT 10's"]
    assert (p10["implied_fv"], p10["historical_current"], p10["historical_avg"]) \
        == (1.01, 1.04, 1.06)
    p5 = recs["OTC 5's / CBOT 5's"]
    assert (p5["implied_fv"], p5["historical_current"], p5["historical_avg"]) \
        == (0.96, 1.00, 0.97)


def test_otc_panel_titles_survive_mojibake_apostrophes(docs):
    """The archive renders the apostrophe as U+FFFD on this page."""
    page = _page(docs["2023-06-09"], "Treasury OTC and Exchange Volatility")
    raw = page.get_text("text")
    assert "OTC 30" in raw
    recs = jp.parse_otc_exchange(page)
    assert all("'" in r["panel"] for r in recs)


# --------------------------------------------------------------------------
# 6. maturity structure
# --------------------------------------------------------------------------
def test_maturity_structure_three_ratios(docs):
    page = _page(docs["2023-06-09"],
                 "Maturity Structure of Treasury Volatility")
    recs = {r["ratio"]: r for r in jp.parse_maturity_structure(page)}
    assert set(recs) == {"5yr/10yr", "5yr/30yr", "10yr/30yr"}
    # printed 5yr/10yr:  Implied 0.78 0.73 ; Historical 0.75 0.74
    assert recs["5yr/10yr"]["implied_current"] == 0.78
    assert recs["5yr/10yr"]["implied_avg"] == 0.73
    assert recs["5yr/10yr"]["historical_current"] == 0.75
    assert recs["5yr/10yr"]["historical_avg"] == 0.74
    # printed 5yr/30yr:  Implied 0.50 0.43 ; Historical N/A 0.45
    assert recs["5yr/30yr"]["implied_current"] == 0.50
    assert recs["5yr/30yr"]["historical_current"] is None
    assert recs["5yr/30yr"]["historical_avg"] == 0.45
    # printed 10yr/30yr: Implied 0.64 0.59
    assert recs["10yr/30yr"]["implied_current"] == 0.64


def test_maturity_structure_v2025(docs):
    page = _page(docs["2026-08-13"],
                 "Maturity Structure of Treasury Volatility")
    recs = {r["ratio"]: r for r in jp.parse_maturity_structure(page)}
    # printed 2026-08-12: 5/10 implied 0.71 avg 0.69 ; 10/30 implied 0.51
    assert recs["5yr/10yr"]["implied_current"] == 0.71
    assert recs["5yr/10yr"]["implied_avg"] == 0.69
    assert recs["10yr/30yr"]["implied_current"] == 0.51
    assert recs["5yr/30yr"]["implied_current"] == 0.36


# --------------------------------------------------------------------------
# 7. skew report
# --------------------------------------------------------------------------
def test_skew_report_captions_and_strikes(docs):
    page = _page(docs["2023-06-09"], "U.S. Treasuries Volatility Skew Report")
    got = jp.parse_skew_report(page)
    caps = {(c["product"], c["expiry_label"]): c for c in got["captions"]}
    # caption: "Sep 23 Bond futures @ 127-20; ATM imp. vol. = 11.41%;
    #           Vol. beta = -0.2515;"
    c = caps[("Bond", "Sep 23")]
    assert c["futures_price_raw"] == "127-20"
    assert c["atm_vol_pct"] == 11.41
    assert c["vol_beta"] == -0.2515
    assert caps[("Note", "Sep 23")]["atm_vol_pct"] == 7.33
    assert got["strikes"], "no strike rows parsed"
    row = next(r for r in got["strikes"]
               if r["product"] == "Bond" and r["expiry_label"] == "Sep 23"
               and r["strike"] == 123.0)
    # printed row: 123 P 0.56 0.58 0.37 11.7 -0.02 0.19 -0.06
    assert (row["put_call"], row["actual"], row["model"], row["avg"],
            row["vega"], row["act_minus_mod"], row["act_minus_avg"],
            row["z_score"]) == ("P", 0.56, 0.58, 0.37, 11.7, -0.02, 0.19, -0.06)
    # the chart's own axis tick labels sit at x>=335 and must be excluded
    assert all(abs(r["z_score"]) < 20 for r in got["strikes"])


# --------------------------------------------------------------------------
# 8. price decoding
# --------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("127-20", 127 + 20 / 32),
    ("113-235", 113 + 23.5 / 32),
    ("114-075", 114 + 7.5 / 32),
    ("106-11+", 106 + 11.5 / 32),
    ("96-06", 96 + 6 / 32),
    ("99.880", 99.880),
    ("94.460", 94.460),
    ("N/A", None),
    ("-", None),
])
def test_parse_price_32nds(raw, expected):
    got = jp.parse_price_32nds(raw)
    if expected is None:
        assert got is None
    else:
        assert got == pytest.approx(expected)


# --------------------------------------------------------------------------
# 9. hard-fail behaviour (the mutation guard)
# --------------------------------------------------------------------------
def test_missing_expiry_header_hard_fails(docs):
    """A page with no "Mon YY" header must raise, never return NaNs."""
    cover = docs["2023-06-09"][0]
    with pytest.raises(jp.JpmParseError) as exc:
        jp.parse_vol_summary(cover, as_of=datetime.date(2023, 6, 8),
                             source="cover")
    assert "expiry header" in str(exc.value)
    assert exc.value.source == "cover"


def test_required_metrics_are_enforced(monkeypatch, docs):
    """Renaming a section label must fail loudly, not drop a column.

    This is the mutation check: if the "Implied (bp)" banner ever changes and
    we do not notice, the basis-point block would silently vanish.  Break the
    lookup on purpose and assert the parser refuses the page.
    """
    page = _page(docs["2023-06-09"], "Treasury Volatility Summary")
    broken = dict(jp._SUBSECTIONS)
    broken.pop("implied (bp)")
    monkeypatch.setattr(jp, "_SUBSECTIONS", broken)
    with pytest.raises(jp.JpmParseError) as exc:
        jp.parse_vol_summary(page, as_of=datetime.date(2023, 6, 8))
    assert "required metrics absent" in str(exc.value)


def test_column_snap_mutation_is_caught(monkeypatch, docs):
    """Shifting the product banner must not silently scramble the panel.

    ``_assign_columns`` asserts the product/column grouping is contiguous
    *and* in banner order; force a bogus banner order and the parser must
    refuse rather than emit a panel whose Treasury Note column carries
    Treasury Bond numbers.  Note that a plain permutation stays contiguous --
    the order assertion is what actually catches it, and this test fails if
    that assertion is removed.
    """
    page = _page(docs["2023-06-09"], "Treasury Volatility Summary")
    real = jp._find_product_row

    def scrambled(rows, hdr_idx):
        prods = real(rows, hdr_idx)
        # swap the x-centres of the first and last banner
        prods[0]["xc"], prods[-1]["xc"] = prods[-1]["xc"], prods[0]["xc"]
        return prods

    monkeypatch.setattr(jp, "_find_product_row", scrambled)
    with pytest.raises(jp.JpmParseError) as exc:
        jp.parse_vol_summary(page, as_of=datetime.date(2023, 6, 8))
    assert "does not match banner order" in str(exc.value)


def test_glued_dollar_cells_are_split():
    """``$167.35$167.35`` is one PDF word but two cells."""
    word = (100.0, 10.0, 140.0, 20.0, "$167.35$167.35", 0, 0, 0)
    got = jp._split_glued([word])
    assert [t[0] for t in got] == ["$167.35", "$167.35"]
    assert got[0][1] == 100.0 and got[1][2] == pytest.approx(140.0)


def test_label_canonicalisation():
    assert jp._canon_label("Change(5d)") == "change (5d)"
    assert jp._canon_label(" Change (1d) ") == "change (1d)"
    assert jp._canon_label("Implied (bp) per day") == "implied (bp) per day"


def test_normalise_text_folds_broken_apostrophes():
    assert jp.normalise_text("OTC 30�s") == "OTC 30's"
    assert jp.normalise_text("OTC 30’s") == "OTC 30's"


# --------------------------------------------------------------------------
# 10. internal coherence on real pages
# --------------------------------------------------------------------------
def test_days_to_expiry_countdown_is_consistent_with_as_of(docs):
    """as_of + Cal days must land on the same date from either vintage.

    Both 2023-06-09 fixtures below describe the *same* Sep-23 Treasury Bond
    option, so the two independently-parsed pages must agree on its expiry.
    """
    tvs = jp.parse_vol_summary(
        _page(docs["2023-06-09"], "Treasury Volatility Summary"),
        as_of=datetime.date(2023, 6, 8))
    bond = _by_expiry(tvs, "Treasury Bond")
    as_of = datetime.date(2023, 6, 8)
    # CME rule puts USU23 on 2023-08-25; 78 calendar days after 2023-06-08
    assert as_of + datetime.timedelta(days=bond["Sep 23"]["days_cal"]) \
        == datetime.date(2023, 8, 25)
    # ...and the Jul-23 serial on 2023-06-23
    assert as_of + datetime.timedelta(days=bond["Jul 23"]["days_cal"]) \
        == datetime.date(2023, 6, 23)


def test_expiry_ym_century_rollover_unit():
    """Direct cover for the century logic the archive never exercises.

    Every issue in the archive is 2019-2026, so ``2000 + yy`` happens to be
    right for all of it and the roll-forward branch is dead there.  Pin it
    here instead, or a future archive that crosses 2099 (or a back-fill of
    the 1990s issues) would silently produce a century-wrong expiry.
    """
    assert jp._expiry_ym("Mar", "20", datetime.date(2019, 8, 26)) == "2020-03"
    assert jp._expiry_ym("Sep", "19", datetime.date(2019, 8, 26)) == "2019-09"
    # a 2098 issue quoting "Mar 01" means 2101, not 2001
    assert jp._expiry_ym("Mar", "01", datetime.date(2098, 12, 1)) == "2101-03"
    # a 1999 issue quoting "Mar 00" means 2000
    assert jp._expiry_ym("Mar", "00", datetime.date(1999, 12, 1)) == "2000-03"
    # with no as-of date at all we fall back to the 2000s
    assert jp._expiry_ym("Mar", "23", None) == "2023-03"


def test_expiry_ym_century_expansion(docs):
    """"Mar 20" on a 2019 page means 2020-03, not 2120-03 or 2019-03."""
    recs = jp.parse_vol_summary(
        _page(docs["2019-08-27"], "Eurodollar MidCurve Volatility Summary"),
        as_of=datetime.date(2019, 8, 26))
    one = _by_expiry(recs, "Eurodollar 1Yr MidCurve")
    assert one["Mar 20"]["expiry_ym"] == "2020-03"
    assert one["Sep 19"]["expiry_ym"] == "2019-09"

"""Provider tests for the SSGA and Vanguard holdings scrapers. Transports are stubbed.

Each test names a way this could produce wrong data quietly. The three that matter most:

* a **403 recorded as absence** -- how a prior iShares backfill wrote 2,515 fabricated
  "no file for this date" rows and exited 0;
* Vanguard's **silently ignored ``asOfDate``** -- 200 OK with a different date in the
  body, which would stamp one month-end snapshot with twelve different dates; and
* a **shifted header row** in the SSGA workbook -- a preamble line added upstream moves
  every column by one and the numbers still parse as numbers.

``tests/_mutate_etf_providers.py`` breaks each of those on purpose and confirms the test
goes red. A test that does not fail when its defect is reintroduced is decoration.
"""

from __future__ import annotations

import datetime
import io
import json

import numpy as np
import pandas as pd
import pytest

from MDP.ETFHoldings import backfill as BF
from MDP.ETFHoldings.providers import _base, ishares, ssga, vanguard
from MDP.ETFHoldings.universe import REGISTRY, provider_module, spec

REQ = datetime.date(2026, 8, 20)

# --------------------------------------------------------------------------- fixtures


SSGA_HEADER = ("Name", "Identifier", "SEDOL", "Weight", "Coupon", "Par Value",
               "Market Value", "Local Currency", "Maturity")

#: Two real SPTL rows and the two real non-bond rows, verbatim from the 2026-08-19 file.
SSGA_BOND_A = ("US TREASURY N/B 05/56 5", "US912810UU06", "BSHW985", 2.291776, 5,
               260738700, 253323943.22, "USD", "05/15/2056")
SSGA_BOND_B = ("US TREASURY N/B 05/55 4.75", "US912810UK24", "BPJK9V9", 2.126395, 4.75,
               252057200, 235043339.0, "USD", "05/15/2055")
#: The SSgA government money-market sweep. Its identifier is nine characters and looks
#: exactly like a CUSIP; ``[2:11]`` off it would be "4QSGII3" padded with junk.
SSGA_MMF = ("SSI US GOV MONEY MARKET CLASS", "924QSGII3", "", 1.066557, 3.650365,
            117892979.94, 117892979.94, "USD", "12/31/2030")
SSGA_CASH = ("US DOLLAR", "999USDZ92", "", 0.003443, 0, 380600.06, 380600.06, "USD", "-")
SSGA_DISCLAIMER = ("Before investing in a fund, consider its investment objectives.",
                   None, None, None, None, None, None, None, None)


def ssga_workbook(rows=(SSGA_BOND_A, SSGA_BOND_B, SSGA_MMF, SSGA_CASH, SSGA_DISCLAIMER),
                  *, as_of="As of 19-Aug-2026", ticker="SPTL",
                  header=SSGA_HEADER, extra_preamble=0, sheet="holdings"):
    """Build a workbook shaped like SSGA's, with the pieces a change could move."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    for i in range(extra_preamble):
        ws.append([f"Marketing line {i}", None])
    ws.append(["Fund Name:", "State Street SPDR Portfolio Long Term Treasury ETF"])
    ws.append(["Ticker Symbol:", ticker])
    if as_of is not None:
        ws.append(["Holdings:", as_of])
    ws.append([None])
    ws.append(list(header))
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


VG_ENTITY = {
    "type": "portfolioHolding", "asOfDate": "2026-07-31T00:00:00-04:00",
    "longName": "United States Treasury Note/Bond", "shortName": "US TREASURY N/B",
    "sharesHeld": "0", "marketValue": 323789895.78, "couponRate": "5.000",
    "maturityDate": "05/15/2056", "faceAmount": "336569000", "ticker": "",
    "isin": "US912810UU06", "percentWeight": "2.22", "notionalValue": "0",
    "cusip": "912810UU0", "sedol": "BSHW985",
}


def vg_payload(as_of="2026-07-31T00:00:00-04:00", entities=None):
    ents = [dict(VG_ENTITY)] if entities is None else [dict(e) for e in entities]
    return json.dumps({"size": len(ents), "asOfDate": as_of,
                       "self": {"ref": "self"}, "fund": {"entity": ents}}).encode()


class StubResponse:
    def __init__(self, status_code=200, content=b"", headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}

    @property
    def text(self):
        return self.content.decode("utf-8", "replace")


class StubSession:
    """Records every URL it is asked for, so a test can assert what went on the wire."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.urls: list[str] = []

    def get(self, url, **kw):
        self.urls.append(url)
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


@pytest.fixture
def nosleep(monkeypatch):
    """The retry loop backs off for seconds on a refusal. Tests should not pay for it."""
    monkeypatch.setattr(_base.time, "sleep", lambda *_a, **_k: None)


# --------------------------------------------------------------- the shared contract


def test_required_cols_matches_what_the_panel_actually_indexes():
    """``_base.REQUIRED_COLS`` is a copy of a list that lives in RVUtils. Catch the drift.

    The duplication exists so ``MDP`` need not import ``RVUtils``. Its cost is that a
    rename in ``holdings_panel.HOLDING_COLS`` would leave the providers validating
    against a stale contract -- and the symptom of a missing column downstream is an
    empty book, not an exception.
    """
    from RVUtils.ETFRebalance import holdings_panel as HP

    missing = set(HP.HOLDING_COLS) - set(_base.REQUIRED_COLS)
    assert not missing, f"holdings_panel indexes {missing} which no provider guarantees"
    for c in ("Asset Class", "Sector", "shares_outstanding"):
        assert c in _base.REQUIRED_COLS       # load_holdings indexes these directly


def test_all_three_issuers_raise_one_blocked_and_return_one_record():
    """A caller that catches ``ishares.Blocked`` must also catch an SSGA refusal."""
    assert ishares.Blocked is ssga.Blocked is vanguard.Blocked is _base.Blocked
    assert ishares.HoldingsFile is ssga.HoldingsFile is vanguard.HoldingsFile
    assert ishares.BLOCKED_STATUSES is _base.BLOCKED_STATUSES


def test_the_ishares_frame_already_satisfies_the_shared_contract():
    """The contract is not new rules for the new issuers; it is what iShares already does."""
    hdr = ("Name,Sector,Asset Class,Market Value,Weight (%),Notional Value,Par Value,"
           "CUSIP,ISIN,SEDOL,Price,Location,Exchange,Currency,Duration,YTM (%),FX Rate,"
           "Maturity,Coupon (%),Mod. Duration,Yield to Call (%),Yield to Worst (%),"
           "Real Duration,Real YTM (%),Market Currency,Accrual Date,Effective Date\n")
    row = ('"TREASURY BOND","Treasuries","Fixed Income","2,119,419,144.95","4.52",'
           '"2,119,419,144.95","2,243,213,900.00","912810UK2","US912810UK24","BPJK9V9",'
           '"93.24","United States","-","USD","14.57","5.21","1.00","May 15, 2055",'
           '"4.75","14.91","-","5.21","14.91","5.21","USD","May 15, 2025","May 15, 2025"\n')
    doc = ('iShares 20+ Year Treasury Bond ETF\n'
           'Fund Holdings as of,"Aug 19, 2026"\nInception Date,"Jul 22, 2002"\n'
           'Shares Outstanding,"565,000,000.00"\n\n' + hdr + row)
    hf = ishares.parse(doc, ticker="TLT", requested=REQ)
    _base.validate_frame(hf.frame, ticker="TLT", source="ishares")   # must not raise


# --------------------------------------------------------------------- ISIN -> CUSIP


def test_isin_to_cusip_takes_the_nsin_out_of_a_us_isin():
    assert _base.isin_to_cusip("US912810UU06") == "912810UU0"
    assert _base.isin_to_cusip("US912803HQ99") == "912803HQ9"      # a principal STRIP
    assert _base.isin_to_cusip("us912810uk24") == "912810UK2"      # case-insensitive


def test_isin_to_cusip_rejects_the_identifiers_that_merely_look_like_one():
    """SSGA's Identifier column is not homogeneous, and the near-misses are the danger.

    ``924QSGII3`` (money-market sweep) and ``999USDZ92`` (cash) are nine characters. A
    length or prefix test alone lets a mangled slice through as a CUSIP, and a
    nine-character string joins to a bond panel silently -- either to nothing, or to the
    wrong bond. The check digit is what separates them.
    """
    assert _base.isin_to_cusip("924QSGII3") is None                # too short, no US
    assert _base.isin_to_cusip("999USDZ92") is None
    assert _base.isin_to_cusip("US912810UU07") is None             # check digit wrong
    assert _base.isin_to_cusip("GB0002634946") is None             # valid ISIN, no CUSIP
    assert _base.isin_to_cusip(None) is None
    assert _base.isin_check_digit_ok("GB0002634946")               # the check itself works


# --------------------------------------------------------------------------- SSGA


def test_ssga_parses_the_real_layout_and_converts_isins():
    hf = ssga.parse(ssga_workbook(), ticker="SPTL", requested=REQ)
    assert hf.as_of == datetime.date(2026, 8, 19)
    assert hf.requested == REQ and hf.honoured_request is False
    f = hf.frame
    bonds = f[f["Asset Class"] == "Fixed Income"]
    assert list(bonds["CUSIP"]) == ["912810UU0", "912810UK2"]
    assert bonds.iloc[0]["Par Value"] == pytest.approx(260_738_700.0)
    assert bonds.iloc[0]["Weight (%)"] == pytest.approx(2.291776)
    assert bonds.iloc[0]["Maturity"] == pd.Timestamp("2056-05-15")
    assert set(bonds["Sector"]) == {"Treasuries"}


def test_ssga_puts_the_sweep_and_the_cash_line_outside_fixed_income():
    """They are positions, so they are kept -- but a bond panel must not try to price them."""
    hf = ssga.parse(ssga_workbook(), ticker="SPTL", requested=REQ)
    cash = hf.frame[hf.frame["Asset Class"] != "Fixed Income"]
    assert list(cash["Name"]) == ["SSI US GOV MONEY MARKET CLASS", "US DOLLAR"]
    assert set(cash["Sector"]) == {"Cash"}
    # Each keeps its own identifier: store.append_holdings dedupes on ["date","CUSIP"],
    # so two NaN keys on one date would silently collapse into one row.
    assert list(cash["CUSIP"]) == ["924QSGII3", "999USDZ92"]
    assert cash["CUSIP"].is_unique


def test_ssga_drops_the_disclaimer_lines_without_dropping_a_position():
    hf = ssga.parse(ssga_workbook(), ticker="SPTL", requested=REQ)
    assert len(hf.frame) == 4                      # 2 bonds + sweep + cash, no footer
    assert not hf.frame["Name"].str.contains("Before investing").any()


def test_ssga_survives_a_preamble_line_being_added():
    """The header row is FOUND, not assumed. This is the test a hard-coded offset fails.

    A marketing line added above the table shifts every row. Reading row 4 would then
    take a data row as the header and every column in the frame would be one out of
    alignment -- and the numbers would still be numbers, so nothing downstream complains.
    """
    hf = ssga.parse(ssga_workbook(extra_preamble=2), ticker="SPTL", requested=REQ)
    assert hf.as_of == datetime.date(2026, 8, 19)
    assert list(hf.frame.columns[:3]) == ["ticker", "date", "Name"]
    assert hf.frame[hf.frame["Asset Class"] == "Fixed Income"].iloc[0]["CUSIP"] == "912810UU0"


def test_ssga_refuses_a_workbook_whose_header_row_is_gone():
    bad = ssga_workbook(header=("Security", "Ident", "SEDOL", "Weight", "Coupon",
                                "Par Value", "Market Value", "Local Currency", "Maturity"))
    with pytest.raises(_base.LayoutChanged, match="Identifier"):
        ssga.parse(bad, ticker="SPTL", requested=REQ)


def test_ssga_refuses_a_workbook_with_no_as_of_line():
    """Without the document's own date the row could only be keyed on the request -- and
    this endpoint serves the current file whatever date you ask for."""
    with pytest.raises(_base.LayoutChanged, match="As of"):
        ssga.parse(ssga_workbook(as_of=None), ticker="SPTL", requested=REQ)


def test_ssga_refuses_a_workbook_where_nothing_converts_to_a_cusip():
    """A column reordering that leaves SEDOLs under 'Identifier' parses fine and is wrong."""
    rows = [tuple(["US TREASURY N/B 05/56 5", "BSHW985"] + list(SSGA_BOND_A[2:]))]
    with pytest.raises(_base.LayoutChanged, match="NOT ONE Identifier"):
        ssga.parse(ssga_workbook(rows=rows), ticker="SPTL", requested=REQ)


def test_ssga_refuses_another_funds_workbook():
    """The URL is keyed by ticker and 301-redirects; confirm we got the fund we asked for."""
    with pytest.raises(_base.WrongDocument, match="SPTL"):
        ssga.parse(ssga_workbook(ticker="SPMD"), ticker="SPTL", requested=REQ)


def test_ssga_returns_none_for_a_body_that_is_not_a_workbook():
    """A 200 that is not a holdings document is the ONLY genuine "no file"."""
    assert ssga.parse(b"<html><title>Error</title></html>", ticker="SPTL", requested=REQ) is None
    assert ssga.parse(b"", ticker="SPTL", requested=REQ) is None


def test_ssga_publishes_no_share_count_and_does_not_invent_one():
    """NaN, never zero: a zero share count makes par_per_share infinite rather than absent."""
    hf = ssga.parse(ssga_workbook(), ticker="SPTL", requested=REQ)
    assert np.isnan(hf.shares_outstanding)
    assert hf.frame["shares_outstanding"].isna().all()
    assert spec("SPTL").publishes_shares_outstanding is False
    # What IS published stands in its place, and it is a measured sum, not a guess.
    assert hf.frame["fund_market_value"].iloc[0] == pytest.approx(
        float(hf.frame["Market Value"].sum()))


def test_ssga_403_raises_blocked_rather_than_reporting_absence(nosleep):
    """The defect that wrote 2,515 fabricated absences and exited 0."""
    sess = StubSession(StubResponse(403, b"<HTML><TITLE>Access Denied</TITLE></HTML>"))
    with pytest.raises(_base.Blocked):
        ssga.fetch("SPTL", ticker="SPTL", session=sess, max_attempts=2)
    assert 403 in ssga.BLOCKED_STATUSES


def test_ssga_fetch_follows_the_redirect():
    """The real URL 301s to a shorter path; a fetch that does not follow gets the 301 body."""
    sess = StubSession(StubResponse(200, ssga_workbook()))
    seen = {}
    orig = sess.get

    def spy(url, **kw):
        seen.update(kw)
        return orig(url, **kw)

    sess.get = spy
    hf = ssga.fetch("SPTL", ticker="SPTL", session=sess)
    assert hf is not None and seen["allow_redirects"] is True


# ------------------------------------------------------------------------ Vanguard


def test_vanguard_keys_on_the_document_date_not_the_requested_one():
    """``?asOfDate=`` is accepted and SILENTLY IGNORED -- 200 with a different date.

    Keying on the request would write a year of byte-identical month-end snapshots under
    twelve different dates, and every diff() over that panel would report eleven months
    of no rebalancing and one month of a year's worth.
    """
    hf = vanguard.parse(vg_payload(), ticker="VGLT", requested=datetime.date(2026, 6, 30))
    assert hf.as_of == datetime.date(2026, 7, 31)
    assert hf.requested == datetime.date(2026, 6, 30)
    assert hf.honoured_request is False
    assert hf.frame["date"].iloc[0] == pd.Timestamp("2026-07-31")
    assert hf.frame["requested_date"].iloc[0] == pd.Timestamp("2026-06-30")


def test_vanguard_never_puts_the_ignored_date_on_the_wire(recwarn):
    """Sending a knob that does nothing dresses a snapshot up as a dated request."""
    sess = StubSession(StubResponse(200, vg_payload()))
    vanguard.fetch("VGLT", datetime.date(2026, 6, 30), ticker="VGLT", session=sess)
    assert len(sess.urls) == 1
    assert "asOfDate" not in sess.urls[0] and "?" not in sess.urls[0]


def test_vanguard_warns_when_the_date_it_served_is_not_the_one_asked_for():
    sess = StubSession(StubResponse(200, vg_payload()))
    with pytest.warns(RuntimeWarning, match="no working date parameter"):
        hf = vanguard.fetch("VGLT", datetime.date(2026, 6, 30), ticker="VGLT", session=sess)
    assert hf.as_of == datetime.date(2026, 7, 31)


def test_vanguard_strict_date_turns_the_ignored_request_into_a_refusal():
    sess = StubSession(StubResponse(200, vg_payload()))
    with pytest.raises(_base.IgnoredDateRequest):
        vanguard.fetch("VGLT", datetime.date(2026, 6, 30), ticker="VGLT",
                       session=sess, strict_date=True)


def test_vanguard_snapshot_mode_does_not_complain(recwarn):
    """A caller that asked for "whatever is current" has nothing to be warned about."""
    sess = StubSession(StubResponse(200, vg_payload()))
    hf = vanguard.fetch("VGLT", ticker="VGLT", session=sess)
    assert hf.as_of == datetime.date(2026, 7, 31)
    assert hf.requested == datetime.date.today()
    assert not [w for w in recwarn if issubclass(w.category, RuntimeWarning)]


def test_vanguard_as_of_is_sliced_not_timezone_converted():
    """The stamp's offset is New York's. Converting a month-end midnight to UTC would
    move the file onto the 1st of the next month and mis-key every row in it."""
    hf = vanguard.parse(vg_payload(as_of="2026-07-31T00:00:00-04:00"),
                        ticker="VGLT", requested=REQ)
    assert hf.as_of == datetime.date(2026, 7, 31)


def test_vanguard_maps_the_wire_names_onto_the_shared_schema():
    hf = vanguard.parse(vg_payload(), ticker="VGLT", requested=REQ)
    r = hf.frame.iloc[0]
    assert r["CUSIP"] == "912810UU0" and r["ISIN"] == "US912810UU06"
    assert r["Par Value"] == pytest.approx(336_569_000.0)        # faceAmount
    assert r["Market Value"] == pytest.approx(323_789_895.78)
    assert r["Weight (%)"] == pytest.approx(2.22)                # percentWeight, percent
    assert r["Coupon (%)"] == pytest.approx(5.0)
    assert r["Maturity"] == pd.Timestamp("2056-05-15")
    assert r["Asset Class"] == "Fixed Income" and r["Sector"] == "Treasuries"


def test_vanguard_labels_strips_as_strips():
    e = dict(VG_ENTITY, longName="United States Treasury Strip Principal",
             isin="US912803HQ99", cusip="912803HQ9", couponRate="0.000")
    hf = vanguard.parse(vg_payload(entities=[e]), ticker="EDV", requested=REQ)
    assert hf.frame["Sector"].iloc[0] == "Treasury STRIPS"
    assert spec("EDV").instrument == "strips" and spec("EDV").prices_from_fedinvest is False


def test_vanguard_refuses_a_payload_whose_cusip_and_isin_disagree():
    """Both fields agreed on 99/99 VGLT and 80/80 EDV rows. A disagreement means one of
    the two columns moved, and the wrong one joins to a real but different bond."""
    e = dict(VG_ENTITY, cusip="912810UK2")           # isin still says ...UU06
    with pytest.raises(_base.LayoutChanged, match="disagree"):
        vanguard.parse(vg_payload(entities=[e]), ticker="VGLT", requested=REQ)


def test_vanguard_returns_none_for_a_body_that_is_not_a_holdings_payload():
    assert vanguard.parse(b"<html>maintenance</html>", ticker="VGLT", requested=REQ) is None
    assert vanguard.parse(b'{"error":"not found"}', ticker="VGLT", requested=REQ) is None
    assert vanguard.parse(json.dumps({"asOfDate": "2026-07-31T00:00:00-04:00",
                                      "fund": {"entity": []}}).encode(),
                          ticker="VGLT", requested=REQ) is None


def test_vanguard_refuses_a_payload_with_an_unparseable_as_of():
    payload = vg_payload(as_of="most recent")
    with pytest.raises(_base.LayoutChanged, match="asOfDate"):
        vanguard.parse(payload, ticker="VGLT", requested=REQ)


def test_vanguard_403_raises_blocked_rather_than_reporting_absence(nosleep):
    sess = StubSession(StubResponse(403, b"Access Denied"))
    with pytest.raises(_base.Blocked):
        vanguard.fetch("VGLT", ticker="VGLT", session=sess, max_attempts=2)


def test_vanguard_publishes_no_share_count_and_shares_held_is_not_one():
    hf = vanguard.parse(vg_payload(), ticker="VGLT", requested=REQ)
    assert np.isnan(hf.shares_outstanding)
    assert hf.frame["shares_outstanding"].isna().all()
    assert spec("VGLT").publishes_shares_outstanding is False


def test_vanguard_documents_describe_the_fund_not_the_etf_share_class():
    """VGLT fact sheet 2026-06-30: ETF net assets $10,482mm, FUND net assets $15,152mm.

    ``Par Value`` is therefore whole-fund par. Any footprint number built from it measures
    the index fund's demand, not the ETF's. The registry says so rather than a comment.
    """
    assert spec("VGLT").book_scope == "fund"
    assert spec("EDV").book_scope == "fund"
    assert spec("SPTL").book_scope == "etf"          # SPTL is a standalone ETF


# ------------------------------------------------------------------ weight units gate


def _vg_book(n, scale=1.0):
    """A complete synthetic book of ``n`` positions whose weights sum to 100 * scale."""
    w = 100.0 * scale / n
    return [dict(VG_ENTITY, cusip=f"91281{i:04d}", isin=None, percentWeight=f"{w:.6f}")
            for i in range(n)]


def test_a_complete_book_whose_weights_sum_to_one_hundred_is_accepted():
    hf = vanguard.parse(vg_payload(entities=_vg_book(25)), ticker="VGLT", requested=REQ)
    assert len(hf.frame) == 25


def test_a_weight_column_that_flips_to_fractions_is_refused():
    """Percent -> fraction is a change nothing else notices.

    Every active weight downstream comes out 100x too small, which reads as "this fund
    tracks its index almost perfectly" -- the most plausible possible wrong answer. This
    repo has already paid for one 100x units flip of exactly this kind.
    """
    with pytest.raises(_base.LayoutChanged, match="factor of 100"):
        vanguard.parse(vg_payload(entities=_vg_book(25, scale=0.01)),
                       ticker="VGLT", requested=REQ)


def test_the_units_gate_is_waived_only_for_a_book_too_small_to_check():
    """A two-position stub has no reason to sum to anything, and the waiver is explicit."""
    assert _base.WEIGHT_GATE_MIN_ROWS == 20
    small = vanguard.parse(vg_payload(entities=_vg_book(3, scale=0.01)),
                           ticker="VGLT", requested=REQ)
    assert small is not None and len(small.frame) == 3


# --------------------------------------------------------------------------- registry


def test_the_new_funds_use_the_bloomberg_long_band_not_tlts_ice_band():
    """SPTL/VGLT track 10+ year indices. Treating them as 20+ funds would put sixty of
    their hundred positions outside their own benchmark."""
    assert spec("SPTL").maturity_band[0] == 10.0
    assert spec("VGLT").maturity_band[0] == 10.0
    assert spec("TLT").maturity_band[0] == 20.0
    assert spec("EDV").maturity_band == (20.0, 30.0)


def test_every_registered_fund_resolves_to_a_provider_with_the_right_shape():
    """A fund in the registry with no module behind it is a backfill that dies at 3am.

    The shape matters as much as the existence: ``backfill.fetch_one`` dispatches with
    one call signature for all issuers, so a provider missing ``fetch``/``parse`` is a
    registry entry that only fails once a runner reaches it.
    """
    for t, sp in REGISTRY.items():
        mod = provider_module(sp)
        assert hasattr(mod, "fetch") and hasattr(mod, "parse"), f"{t} -> {mod.__name__}"


def test_aum_carries_the_date_it_was_read():
    for t in ("SPTL", "VGLT", "EDV"):
        assert spec(t).aum_usd >= 1e9
        assert spec(t).aum_asof == datetime.date(2026, 8, 20)


def test_strips_funds_are_not_in_the_coupon_set():
    from MDP.ETFHoldings.universe import COUPON_LONG, STRIPS_LONG, tickers_above

    assert set(COUPON_LONG) == {"TLT", "SPTL", "VGLT"}
    assert "EDV" in STRIPS_LONG and "EDV" not in COUPON_LONG
    assert "EDV" not in tickers_above(1e9)           # coupon_only excludes STRIPS


# --------------------------------------------------------------------------- backfill


def test_backfill_refuses_to_loop_a_current_only_fund():
    """SSGA and Vanguard serve one document. A business-day grid over ten years would be
    ~2,500 requests for the same bytes and ~2,500 manifest rows pointing at one as_of."""
    with pytest.raises(ValueError, match="only its CURRENT holdings"):
        BF.backfill_ticker("SPTL", datetime.date(2016, 1, 1), REQ, pool=None, workers=1)


def test_snapshot_refuses_a_fund_that_has_a_real_history():
    with pytest.raises(ValueError, match="dated endpoint"):
        BF.snapshot_ticker("TLT", pool=None)


def test_snapshot_stores_on_the_documents_date_and_records_the_request(tmp_path, monkeypatch):
    monkeypatch.setenv("ARBS_ETF_HOLDINGS_DIR", str(tmp_path))
    monkeypatch.setattr(vanguard, "fetch",
                        lambda *a, **k: vanguard.parse(vg_payload(), ticker="VGLT",
                                                       requested=datetime.date(2026, 8, 20)))
    from MDP.ETFHoldings import store

    out = BF.snapshot_ticker("VGLT", pool=None, on_date=datetime.date(2026, 8, 20))
    assert out["stored"] == 1 and out["blocked"] == 0
    man = store.read_manifest("VGLT")
    assert pd.Timestamp(man["requested_date"].iloc[0]) == pd.Timestamp("2026-08-20")
    assert pd.Timestamp(man["as_of"].iloc[0]) == pd.Timestamp("2026-07-31")
    assert store.load("VGLT")["date"].unique().tolist() == [pd.Timestamp("2026-07-31")]


def test_snapshot_does_not_write_a_manifest_row_when_it_is_refused(tmp_path, monkeypatch):
    """A manifest row is a claim the endpoint was asked and had nothing, and resume
    honours that claim. A refusal must leave no such claim behind."""
    monkeypatch.setenv("ARBS_ETF_HOLDINGS_DIR", str(tmp_path))

    def boom(*a, **k):
        raise _base.Blocked("SPTL: refused after 6 attempts (HTTP 403)")

    monkeypatch.setattr(ssga, "fetch", boom)
    from MDP.ETFHoldings import store

    out = BF.snapshot_ticker("SPTL", pool=None, on_date=datetime.date(2026, 8, 20))
    assert out == {"ticker": "SPTL", "requested": 1, "stored": 0, "no_file": 0, "blocked": 1}
    assert store.read_manifest("SPTL").empty
    assert store.attempted_dates("SPTL") == set()


def test_snapshot_records_a_200_with_no_document_as_a_real_absence(tmp_path, monkeypatch):
    monkeypatch.setenv("ARBS_ETF_HOLDINGS_DIR", str(tmp_path))
    monkeypatch.setattr(ssga, "fetch", lambda *a, **k: None)
    from MDP.ETFHoldings import store

    out = BF.snapshot_ticker("SPTL", pool=None, on_date=datetime.date(2026, 8, 20))
    assert out["no_file"] == 1 and out["blocked"] == 0
    man = store.read_manifest("SPTL")
    assert len(man) == 1 and pd.isna(man["as_of"].iloc[0]) and man["n_rows"].iloc[0] == 0


def test_snapshot_is_idempotent_across_a_re_serve(tmp_path, monkeypatch):
    """Vanguard serves one month-end file for ~21 business days. Re-storing it must land
    on the same date rather than inventing a second observation of that month."""
    monkeypatch.setenv("ARBS_ETF_HOLDINGS_DIR", str(tmp_path))
    monkeypatch.setattr(vanguard, "fetch",
                        lambda *a, **k: vanguard.parse(vg_payload(), ticker="VGLT",
                                                       requested=datetime.date(2026, 8, 21)))
    from MDP.ETFHoldings import store

    BF.snapshot_ticker("VGLT", pool=None, on_date=datetime.date(2026, 8, 20))
    BF.snapshot_ticker("VGLT", pool=None, on_date=datetime.date(2026, 8, 21))
    panel = store.load("VGLT")
    assert panel["date"].nunique() == 1
    assert len(panel) == 1                             # one CUSIP in the fixture, one row
    assert len(store.read_manifest("VGLT")) == 2       # but two attempts recorded

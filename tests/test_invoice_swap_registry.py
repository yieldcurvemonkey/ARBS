"""Registry completeness check for CBOT Treasury Invoice Swap codes.

Canonical CME table (PM24IR010, "Invoice Swap Spread Codes"):

  DELIVERY DATE  |  LAST to deliver  |   FIRST to deliver
  CTD CANDIDATE  |   A   |  B  |  C  |   A   |   B   |   C
  ---------------+-------+-----+-----+-------+-------+------
  2Y   (TU)      |  TVA  | TVB | TVC |  TVD  |  TVE  | TVF
  5Y   (FV)      |  FYA  | FYB | FYC |  FYD  |  FYE  | FYF
  10Y  (TY)      |  TYA  | TYB | TYC |  TYD  |  TAY  | TAB
  U10Y (UXY)     |  TNA  | TNB | TNC |  TND  |  TNE  | TNF
  US   (US)      |  UTA  | UTB | UTC |  UTD  |  UTE  | UET
  UB   (WN)      |  UBA  | UBB | UBC |  UBI  |  UBP  | UBF
"""
import pytest

from Query.IRSwaps._CME_INVOICE_SWAP_TICKERS import (
    _CME_INVOICE_SWAP_TICKERS,
    _INDICATOR_TO_TICKER,
)


CANONICAL_LAYOUT = {
    "TU":  {"A": "TVA", "B": "TVB", "C": "TVC", "D": "TVD", "E": "TVE", "F": "TVF"},
    "FV":  {"A": "FYA", "B": "FYB", "C": "FYC", "D": "FYD", "E": "FYE", "F": "FYF"},
    "TY":  {"A": "TYA", "B": "TYB", "C": "TYC", "D": "TYD", "E": "TAY", "F": "TAB"},
    "UXY": {"A": "TNA", "B": "TNB", "C": "TNC", "D": "TND", "E": "TNE", "F": "TNF"},
    "US":  {"A": "UTA", "B": "UTB", "C": "UTC", "D": "UTD", "E": "UTE", "F": "UET"},
    "WN":  {"A": "UBA", "B": "UBB", "C": "UBC", "D": "UBI", "E": "UBP", "F": "UBF"},
}


def test_all_six_roots_present():
    assert set(_INDICATOR_TO_TICKER) == set(CANONICAL_LAYOUT)


@pytest.mark.parametrize("root", sorted(CANONICAL_LAYOUT))
def test_root_has_all_six_indicators(root):
    got = _INDICATOR_TO_TICKER[root]
    assert set(got) == {"A", "B", "C", "D", "E", "F"}, f"{root} missing indicators"
    assert got == CANONICAL_LAYOUT[root], f"{root} mismatch vs canonical"


def test_ticker_registry_has_all_canonical_codes():
    all_expected = {
        ticker
        for row in CANONICAL_LAYOUT.values()
        for ticker in row.values()
    }
    assert set(_CME_INVOICE_SWAP_TICKERS) == all_expected


@pytest.mark.parametrize(
    "ticker,expected_root,expected_delivery",
    [
        ("TVC", "TU", "last"),
        ("TVF", "TU", "first"),
        ("FYC", "FV", "last"),
        ("FYF", "FV", "first"),
        ("TYC", "TY", "last"),
        ("TAB", "TY", "first"),
        ("TNC", "UXY", "last"),
        ("TNF", "UXY", "first"),
        ("UTC", "US", "last"),
        ("UET", "US", "first"),
        ("UBC", "WN", "last"),
        ("UBF", "WN", "first"),
    ],
)
def test_newly_added_codes_have_correct_root_and_delivery(
    ticker, expected_root, expected_delivery
):
    spec = _CME_INVOICE_SWAP_TICKERS[ticker]
    assert spec["root"] == expected_root
    assert spec["delivery"] == expected_delivery

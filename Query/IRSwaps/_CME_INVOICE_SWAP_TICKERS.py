# https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457094970/CBOT+Treasury+Invoice+Swaps
#
# Canonical CME invoice-swap-spread codes. Each code identifies a
# (related futures root, delivery date side, CTD candidate) triple:
#
#   DELIVERY DATE  |  LAST to deliver  |   FIRST to deliver
#   CTD CANDIDATE  |   A   |  B  |  C  |   A   |   B   |   C
#   ---------------+-------+-----+-----+-------+-------+------
#   2Y   (TU)      |  TVA  | TVB | TVC |  TVD  |  TVE  | TVF
#   5Y   (FV)      |  FYA  | FYB | FYC |  FYD  |  FYE  | FYF
#   10Y  (TY)      |  TYA  | TYB | TYC |  TYD  |  TAY  | TAB
#   U10Y (UXY)     |  TNA  | TNB | TNC |  TND  |  TNE  | TNF
#   US   (US)      |  UTA  | UTB | UTC |  UTD  |  UTE  | UET
#   UB   (WN)      |  UBA  | UBB | UBC |  UBI  |  UBP  | UBF
#
# Ref: CBOT Treasury Invoice Swap Spread contract specifications sheet,
#      "Invoice Swap Spread Codes" table (CME Group, PM24IR010).
_CME_INVOICE_SWAP_TICKERS = {
    # 2Y — Last delivery
    "TVA": {"root": "TU", "delivery": "last"},
    "TVB": {"root": "TU", "delivery": "last"},
    "TVC": {"root": "TU", "delivery": "last"},
    # 2Y — First delivery
    "TVD": {"root": "TU", "delivery": "first"},
    "TVE": {"root": "TU", "delivery": "first"},
    "TVF": {"root": "TU", "delivery": "first"},
    # 5Y — Last delivery
    "FYA": {"root": "FV", "delivery": "last"},
    "FYB": {"root": "FV", "delivery": "last"},
    "FYC": {"root": "FV", "delivery": "last"},
    # 5Y — First delivery
    "FYD": {"root": "FV", "delivery": "first"},
    "FYE": {"root": "FV", "delivery": "first"},
    "FYF": {"root": "FV", "delivery": "first"},
    # 10Y — Last delivery
    "TYA": {"root": "TY", "delivery": "last"},
    "TYB": {"root": "TY", "delivery": "last"},
    "TYC": {"root": "TY", "delivery": "last"},
    # 10Y — First delivery
    "TYD": {"root": "TY", "delivery": "first"},
    "TAY": {"root": "TY", "delivery": "first"},
    "TAB": {"root": "TY", "delivery": "first"},
    # Ultra 10Y (TN / UXY) — Last delivery
    "TNA": {"root": "UXY", "delivery": "last"},
    "TNB": {"root": "UXY", "delivery": "last"},
    "TNC": {"root": "UXY", "delivery": "last"},
    # Ultra 10Y — First delivery
    "TND": {"root": "UXY", "delivery": "first"},
    "TNE": {"root": "UXY", "delivery": "first"},
    "TNF": {"root": "UXY", "delivery": "first"},
    # Bonds (US) — Last delivery
    "UTA": {"root": "US", "delivery": "last"},
    "UTB": {"root": "US", "delivery": "last"},
    "UTC": {"root": "US", "delivery": "last"},
    # Bonds — First delivery
    "UTD": {"root": "US", "delivery": "first"},
    "UTE": {"root": "US", "delivery": "first"},
    "UET": {"root": "US", "delivery": "first"},
    # Ultra Bonds (WN) — Last delivery
    "UBA": {"root": "WN", "delivery": "last"},
    "UBB": {"root": "WN", "delivery": "last"},
    "UBC": {"root": "WN", "delivery": "last"},
    # Ultra Bonds — First delivery
    "UBI": {"root": "WN", "delivery": "first"},
    "UBP": {"root": "WN", "delivery": "first"},
    "UBF": {"root": "WN", "delivery": "first"},
}

# Indicator letter -> ticker, per (futures root, CTD delivery indicator).
# Per CME conventions: indicators A/B/C refer to CTD candidates 1/2/3 on the
# LAST-delivery date; indicators D/E/F refer to CTD candidates 1/2/3 on the
# FIRST-delivery date. 10Y first-delivery candidates 2/3 use the irregular
# "TAY"/"TAB" codes (rather than TYE/TYF). Bond first-delivery candidate 3
# uses "UET" (not UTF). Ultra Bond first-delivery candidates 1/2/3 use
# UBI/UBP/UBF (not UBD/UBE/UBG).
_INDICATOR_TO_TICKER = {
    "TU":  {"A": "TVA", "B": "TVB", "C": "TVC", "D": "TVD", "E": "TVE", "F": "TVF"},
    "FV":  {"A": "FYA", "B": "FYB", "C": "FYC", "D": "FYD", "E": "FYE", "F": "FYF"},
    "TY":  {"A": "TYA", "B": "TYB", "C": "TYC", "D": "TYD", "E": "TAY", "F": "TAB"},
    "UXY": {"A": "TNA", "B": "TNB", "C": "TNC", "D": "TND", "E": "TNE", "F": "TNF"},
    "US":  {"A": "UTA", "B": "UTB", "C": "UTC", "D": "UTD", "E": "UTE", "F": "UET"},
    "WN":  {"A": "UBA", "B": "UBB", "C": "UBC", "D": "UBI", "E": "UBP", "F": "UBF"},
}

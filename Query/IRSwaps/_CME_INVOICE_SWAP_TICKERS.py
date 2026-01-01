# https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457094970/CBOT+Treasury+Invoice+Swaps
_CME_INVOICE_SWAP_TICKERS = {
    # 2Y
    "TVA": {"root": "TU", "delivery": "last"},
    "TVB": {"root": "TU", "delivery": "last"},
    "TVD": {"root": "TU", "delivery": "first"},
    "TVE": {"root": "TU", "delivery": "first"},
    
    # 5Y
    "FYA": {"root": "FV", "delivery": "last"},
    "FYB": {"root": "FV", "delivery": "last"},
    "FYD": {"root": "FV", "delivery": "first"},
    "FYE": {"root": "FV", "delivery": "first"},
    
    # 10Y
    "TYA": {"root": "TY", "delivery": "last"},
    "TYB": {"root": "TY", "delivery": "last"},
    "TYD": {"root": "TY", "delivery": "first"},
    "TAY": {"root": "TY", "delivery": "first"},

    # Ultra 10Y
    "TNA": {"root": "UXY", "delivery": "last"},
    "TNB": {"root": "UXY", "delivery": "last"},
    "TND": {"root": "UXY", "delivery": "first"},
    "TNE": {"root": "UXY", "delivery": "first"},
    
    # Bonds
    "UTA": {"root": "US", "delivery": "last"},
    "UTB": {"root": "US", "delivery": "last"},
    "UTD": {"root": "US", "delivery": "first"},
    "UTE": {"root": "US", "delivery": "first"},
    
    # Ultra Bonds
    "UBA": {"root": "WN", "delivery": "last"},
    "UBB": {"root": "WN", "delivery": "last"},
    "UBI": {"root": "WN", "delivery": "first"},
    "UBP": {"root": "WN", "delivery": "first"},
}

_INDICATOR_TO_TICKER = {
    "TU": {"A": "TVA", "B": "TVB", "D": "TVD", "E": "TVE"},
    "FV": {"A": "FYA", "B": "FYB", "D": "FYD", "E": "FYE"},
    "TY": {"A": "TYA", "B": "TYB", "D": "TYD", "E": "TAY", "Y": "TAY"},
    "UXY": {"A": "TNA", "B": "TNB", "D": "TND", "E": "TNE"},
    "US": {"A": "UTA", "B": "UTB", "D": "UTD", "E": "UTE"},
    "WN": {"A": "UBA", "B": "UBB", "D": "UBI", "E": "UBP", "I": "UBI", "P": "UBP"},
}
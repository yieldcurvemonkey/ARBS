import datetime

from definitions.IRSwaps import CURVE_DEFINITIONS


# TODO automate with caching like rl curvce build in oasis

_CENTRAL_BANK_DATES = {
    "USD-SOFR-1D": {
        "sep25": (datetime.date(2025, 9, 17), datetime.date(2025, 10, 29)),
        "oct25": (datetime.date(2025, 10, 29), datetime.date(2025, 12, 10)),
        "dec25": (datetime.date(2025, 12, 10), datetime.date(2026, 1, 28)),
        "jan26": (datetime.date(2026, 1, 28), datetime.date(2026, 3, 18)),
        "mar26": (datetime.date(2026, 3, 18), datetime.date(2026, 4, 29)),
        "apr26": (datetime.date(2026, 4, 29), datetime.date(2026, 6, 17)),
        "jun26": (datetime.date(2026, 6, 17), datetime.date(2026, 7, 29)),
        "jul26": (datetime.date(2026, 7, 29), datetime.date(2026, 9, 16)),
        "sep26": (datetime.date(2026, 9, 16), datetime.date(2026, 10, 28)),
        "oct26": (datetime.date(2026, 10, 28), datetime.date(2026, 12, 9)),
        "dec26": (datetime.date(2026, 12, 9), datetime.date(2027, 1, 27)),
        "jan27": (datetime.date(2027, 1, 27), datetime.date(2027, 3, 17)),
        "mar27": (datetime.date(2027, 3, 17), datetime.date(2027, 4, 28)),
        "apr27": (datetime.date(2027, 4, 28), datetime.date(2027, 6, 9)),
        "jun27": (datetime.date(2027, 6, 9), datetime.date(2027, 7, 28)),
        "jul27": (datetime.date(2027, 7, 28), datetime.date(2027, 9, 15)),
        "sep27": (datetime.date(2027, 9, 15), datetime.date(2027, 10, 27)),
        "oct27": (datetime.date(2027, 10, 27), datetime.date(2027, 12, 8)),
        "dec27": (datetime.date(2027, 12, 8), datetime.date(2028, 1, 26)),
    },
    "USD-FEDFUNDS": {
        "sep25": (datetime.date(2025, 9, 17), datetime.date(2025, 10, 29)),
        "oct25": (datetime.date(2025, 10, 29), datetime.date(2025, 12, 10)),
        "dec25": (datetime.date(2025, 12, 10), datetime.date(2026, 1, 28)),
        "jan26": (datetime.date(2026, 1, 28), datetime.date(2026, 3, 18)),
        "mar26": (datetime.date(2026, 3, 18), datetime.date(2026, 4, 29)),
        "apr26": (datetime.date(2026, 4, 29), datetime.date(2026, 6, 17)),
        "jun26": (datetime.date(2026, 6, 17), datetime.date(2026, 7, 29)),
        "jul26": (datetime.date(2026, 7, 29), datetime.date(2026, 9, 16)),
        "sep26": (datetime.date(2026, 9, 16), datetime.date(2026, 10, 28)),
        "oct26": (datetime.date(2026, 10, 28), datetime.date(2026, 12, 9)),
        "dec26": (datetime.date(2026, 12, 9), datetime.date(2027, 1, 27)),
        "jan27": (datetime.date(2027, 1, 27), datetime.date(2027, 3, 17)),
        "mar27": (datetime.date(2027, 3, 17), datetime.date(2027, 4, 28)),
        "apr27": (datetime.date(2027, 4, 28), datetime.date(2027, 6, 9)),
        "jun27": (datetime.date(2027, 6, 9), datetime.date(2027, 7, 28)),
        "jul27": (datetime.date(2027, 7, 28), datetime.date(2027, 9, 15)),
        "sep27": (datetime.date(2027, 9, 15), datetime.date(2027, 10, 27)),
        "oct27": (datetime.date(2027, 10, 27), datetime.date(2027, 12, 8)),
        "dec27": (datetime.date(2027, 12, 8), datetime.date(2028, 1, 26)),
    },
}

for k in _CENTRAL_BANK_DATES.keys():
    assert k in CURVE_DEFINITIONS, f"key {k} in '_CENTRAL_BANK_DATES' must exist in global 'CURVE_DEFINITIONS'"

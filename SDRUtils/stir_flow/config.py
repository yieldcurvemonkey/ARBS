"""Constants for the STIR dealer-direction classifier (spec 2026-07-12)."""

CURVE_SOURCE = "BARCHART_STIRF-RL"
CURVE_FOR = {
    "SOFR": "USD-SOFR-1D-Q12xM12STIRT",
    "FED_FUNDS": "USD-OIS-Q12xM12STIRT-SERFFX-MIX23",
}

# CME rulebook minimum ticks (bps). FF futures Ch.22 / 1M SOFR Ch.461 = 0.5bp,
# SR3 Ch.460 = 0.25bp. Near-expiry halving deferred (POC).
_FF_TICK = 0.50
_SER_TICK = 0.50
_SR3_TICK = 0.25

# DV01 buckets per Clarus tick-vs-size methodology.
DV01_BUCKETS = (
    ("MICRO", 0.0, 5_000.0),
    ("SMALL", 5_000.0, 15_000.0),
    ("MID", 15_000.0, 50_000.0),
    ("LARGE", 50_000.0, 150_000.0),
    ("BLOCK", 150_000.0, float("inf")),
)

PTP_USD_FLOOR = 500.0          # |PTP| below this = notation-polluted price, not USD
PTP_UFRO_DISAGREE_RATIO = 2.0  # flag when both present and >2x apart
TICK_PAIR_MAX_GAP_MIN = 60     # consecutive-print pairs beyond this measure drift
MIN_DISP_VW_BPS = 0.05         # ratio-denominator floor for the curve_suspect gate
CURVE_SUSPECT_RATIO = 2.0      # DispJNS/DispVW above this -> bucket-day curve_suspect
HUMP_OUTLIER_MULT = 3.0        # |s2m| > 3*S -> curve_suspect_trade, LOW
AMBIGUOUS_FRAC = 0.5           # |s2m| < 0.5*(S/2) -> tick-rule fallback
P_FLIP_HIGH = 0.05
P_FLIP_MEDIUM = 0.20
SUB3Y_HORIZON_DAYS = 1105      # ~3.02y: maturity cutoff from as_of_date

EXCLUDED_LABEL_TOKENS = ("CME Term", "Amortizing")
EXCLUDED_TRADE_TYPES = (
    "MAC", "SPREADOVER", "SPREADOVER_CURVE", "SPREADOVER_FLY",
    "MATCHED_MATURITY", "MATCHED_MATURITY_CURVE", "MATCHED_MATURITY_FLY",
    "INVOICE", "INVOICE_SWAP", "INVOICE_CALENDAR", "INVOICE_SWITCH",
)


def assign_dv01_bucket(dv01) -> str:
    if dv01 is None:
        return "UNKNOWN"
    try:
        v = abs(float(dv01))
    except (TypeError, ValueError):
        return "UNKNOWN"
    if v != v:  # NaN
        return "UNKNOWN"
    for name, lo, hi in DV01_BUCKETS:
        if lo <= v < hi:
            return name
    return "UNKNOWN"


def futures_tick_bps(rate_index: str, special_tenor_type) -> float:
    if rate_index == "FED_FUNDS":
        return _FF_TICK
    if special_tenor_type == "FOMC":
        return _SER_TICK
    return _SR3_TICK

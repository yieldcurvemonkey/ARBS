"""V2 classifiers must classify special tenors (IMM / FOMC) like V1 does.

User rules:
  * FOMC-to-FOMC (effective AND maturity both land on FOMC meetings, within a
    1-day tolerance) => special_tenor_type "FOMC"  -> tape labels "FOMC SEP26".
  * Effective on a quarterly IMM date with a constant-maturity tenor => "IMM"
    -> tape labels "IMM_<code> <tenor>". IMM wins the IMM/FOMC overlap ONLY when
    the maturity is not also FOMC.
  * Plain spot benchmark swaps stay "STANDARD".

detect_special_tenor already encodes this; the bug was that the V2 classifiers
(sofr_ois / fed_funds_ois / basis_swaps) never called it.
"""
import pandas as pd

from SDRUtils.core.tenors import get_fomc_label, get_imm_label
from SDRUtils.products.usd.sofr_ois import classify_sofr_ois_trade
from SDRUtils.products.usd.fed_funds_ois import classify_fed_funds_ois_trade
from SDRUtils.products.usd.basis_swaps import classify_basis_swap_trade


def _row(underlier, fisn, **overrides):
    base = {
        "Action type": "NEWT", "Event type": "TRAD",
        "Execution Timestamp": "2026-05-29 14:00:00+00:00",
        "Effective Date": "2026-06-01", "Expiration Date": "2031-06-01",
        "Notional amount-Leg 1": "100,000,000", "Notional currency-Leg 1": "USD",
        "Fixed rate-Leg 1": None,
        "UPI Underlier Name": underlier, "UPI FISN": fisn,
        "Cleared": "Y", "Package indicator": False,
    }
    base.update(overrides)
    return pd.Series(base)


class TestFomcLabelTolerance:
    def test_one_business_day_before_meeting(self):
        # 2026-09-15 is one business day before the 2026-09-16 FOMC decision date
        assert get_fomc_label(pd.Timestamp("2026-09-15")) == "FOMC_20260916"

    def test_exact_meeting_date_unchanged(self):
        assert get_fomc_label(pd.Timestamp("2026-09-16")) == "FOMC_20260916"


class TestV2SpecialTenorClassification:
    def test_fed_funds_fomc_to_fomc(self):
        # eff 9/15 (Sep FOMC, ±1), mat 10/27 (Oct FOMC, ±1) -> FOMC swap (Tier 1)
        r = classify_fed_funds_ois_trade(
            _row("USD-Federal Funds-H.15-OIS-COMPOUND", "NA/Swap OIS USD",
                 **{"Effective Date": "2026-09-15", "Expiration Date": "2026-10-27"}),
            trade_id=1,
        )
        assert r.special_tenor_type == "FOMC"

    def test_sofr_imm_constant_maturity_30y(self):
        # eff 6/17 (Jun IMM AND Jun FOMC), mat 6/17/2056 constant 30Y -> IMM (Tier 2)
        r = classify_sofr_ois_trade(
            _row("USD-SOFR-COMPOUND", "NA/Swap OIS USD",
                 **{"Effective Date": "2026-06-17", "Expiration Date": "2056-06-17"}),
            trade_id=2,
        )
        assert r.special_tenor_type == "IMM"

    def test_basis_fomc_to_fomc(self):
        r = classify_basis_swap_trade(
            _row("USD-Federal Funds vs USD-SOFR", "NA/Swap Basis USD",
                 **{"Effective Date": "2026-09-15", "Expiration Date": "2026-10-27"}),
            trade_id=3,
        )
        assert r.special_tenor_type == "FOMC"

    def test_plain_spot_benchmark_stays_standard(self):
        # spot 5Y benchmark (eff 6/1, mat 6/1/2031) is NOT special
        r = classify_sofr_ois_trade(_row("USD-SOFR-COMPOUND", "NA/Swap OIS USD"), trade_id=4)
        assert r.special_tenor_type == "STANDARD"

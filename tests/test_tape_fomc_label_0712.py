# tests/test_tape_fomc_label_0712.py
"""07/12/2026 tape bugs — FOMC vs IMM package labels.

FOMC notation must only appear when a leg is a genuine consecutive-FOMC
meeting-to-meeting swap (its own fomc_meeting_label is populated). A standard
tenor (2Y/5Y/1Y) that merely STARTS on an IMM date that coincides with a FOMC
meeting must render the IMM anchor at package scope, matching the per-leg
label. Large PKG-N packages render "PKG-N" with no forward/tenor/FOMC prefix.
"""
import pandas as pd

from SDRUtils.analytics.trade_tape import TradeTape


def _base_leg(**over):
    row = {
        "trade_id": "T1",
        "execution_timestamp": pd.Timestamp("2026-07-06 14:30:00", tz="UTC"),
        "product_type": "OIS_SWAP",
        "upi_underlier_name": "USD-SOFR-COMPOUND 1D",
        "upi_reset_freq": "1D",
        "upi_notional_schedule": "Constant",
        "upi_delivery_type": "PHYS",
        "trade_type": "OUTRIGHT",
        "package_type": "OUTRIGHT",
        "forward_label": "spot",
        "forward_start_years": 0.0,
        "tenor_label": "10Y",
        "tenor_display": "10Y",
        "tenor_years": 10.0,
        "package_tenors": "10Y",
        "cleared": "Y",
        "special_tenor_type": "STANDARD",
        "package_indicator": True,
        "effective_date": pd.Timestamp("2026-07-08"),
        "expiration_date": pd.Timestamp("2036-07-08"),
        "is_unwind": False, "is_mac": False, "is_ufro": False, "is_block": False,
    }
    row.update(over)
    return row


def _labels(rows):
    df = pd.DataFrame(rows)
    tape = TradeTape(df=df, raw_df=None)
    out = tape._enrich_context(df.copy())
    return tape._build_enriched_label(out)


def _curve_leg(tid, fwd, fy, eff, exp, stt, tenor="2Y", ty=2.0):
    return _base_leg(
        trade_id=tid, trade_type="CURVE", package_type="CURVE",
        package_legs=["A", "B"], forward_label=fwd, forward_start_years=fy,
        tenor_label=tenor, tenor_display=tenor, tenor_years=ty,
        package_tenors=f"{tenor}/{tenor}", special_tenor_type=stt,
        effective_date=pd.Timestamp(eff), expiration_date=pd.Timestamp(exp),
    )


def test_bug8_spot_imm_curve_renders_imm_not_fomc():
    rows = [
        _curve_leg("A", "spot", 0.0, "2026-07-08", "2028-07-08", "STANDARD"),
        _curve_leg("B", "FOMC_20260916", 0.18, "2026-09-16", "2028-09-16", "IMM"),
    ]
    lbl = _labels(rows).loc[0, "tape_label"]
    assert "IMM_U2026" in lbl, lbl
    assert "FOMC" not in lbl, lbl
    assert "Spot/IMM_U2026 2Y" in lbl, lbl


def test_bug9_spot_imm_5y_curve_renders_imm_not_fomc():
    rows = [
        _curve_leg("A", "spot", 0.0, "2026-07-08", "2031-07-08", "STANDARD", "5Y", 5.0),
        _curve_leg("B", "FOMC_20260916", 0.18, "2026-09-16", "2031-09-16", "IMM", "5Y", 5.0),
    ]
    lbl = _labels(rows).loc[0, "tape_label"]
    assert "Spot/IMM_U2026 5Y" in lbl and "FOMC" not in lbl, lbl


def test_bug13_imm_fly_renders_imm_not_fomc():
    rows = [
        _base_leg(
            trade_id=tid, trade_type="FLY", package_type="FLY",
            package_legs=["F0", "F1", "F2"], forward_label=fwd, forward_start_years=fy,
            tenor_label="1Y", tenor_display="1Y", tenor_years=1.0, package_tenors="1Y/1Y/1Y",
            special_tenor_type="IMM",
            effective_date=pd.Timestamp(eff), expiration_date=pd.Timestamp(exp),
        )
        for tid, fwd, fy, eff, exp in [
            ("F0", "FOMC_20270915", 1.2, "2027-09-15", "2028-09-15"),
            ("F1", "FOMC_20280920", 2.2, "2028-09-20", "2029-09-20"),
            ("F2", "FOMC_20290919", 3.2, "2029-09-19", "2030-09-19"),
        ]
    ]
    lbl = _labels(rows).loc[0, "tape_label"]
    assert "IMM_U2027/IMM_U2028/IMM_U2029 1Y" in lbl, lbl
    assert "FOMC" not in lbl, lbl


def test_bug10_large_pkg_n_renders_pkg_label():
    # 16-leg Fed Funds package -> "PKG-16", no FOMC/tenor prefix.
    legs = [f"L{i}" for i in range(16)]
    rows = [
        _base_leg(
            trade_id=legs[i], trade_type="FOMC", package_type="PKG-16",
            package_legs=legs, n_package_legs=16,
            upi_underlier_name="USD-Federal Funds-OIS Compound 1D",
            forward_label="FOMC_20261209", special_tenor_type="FOMC",
            tenor_label="FOMC DEC26", tenor_display="FOMC DEC26",
            effective_date=pd.Timestamp("2026-12-09"), expiration_date=pd.Timestamp("2027-01-27"),
        )
        for i in range(16)
    ]
    lbl = _labels(rows).loc[0, "tape_label"]
    assert lbl.rstrip().endswith("PKG-16 PHYS"), lbl
    assert "FOMC DEC26" not in lbl, lbl

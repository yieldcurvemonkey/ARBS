import pandas as pd
from SDRUtils.analytics.trade_tape import TradeTape


def _labels(rows):
    df = pd.DataFrame(rows)
    tape = TradeTape(df=df, raw_df=None)
    out = tape._enrich_context(df.copy())
    return tape._build_enriched_label(out)


def _leg(tid, tenor, ty):
    return {
        "trade_id": tid, "execution_timestamp": pd.Timestamp("2026-07-10 21:00:32", tz="UTC"),
        "product_type": "OIS_SWAP", "upi_underlier_name": "USD-SOFR-OIS Compound",
        "upi_reset_freq": "1D", "upi_notional_schedule": "Constant", "upi_delivery_type": "PHYS",
        "trade_type": "SPREADOVER_CURVE", "package_type": "SPREADOVER_CURVE",
        "package_legs": ["S1", "S2"], "forward_label": "spot", "forward_start_years": 0.0,
        "tenor_label": tenor, "tenor_display": tenor, "tenor_years": ty,
        "package_tenors": "10Y/30Y", "cleared": "Y", "special_tenor_type": "STANDARD",
        "effective_date": pd.Timestamp("2026-07-14"),
        "expiration_date": pd.Timestamp(f"20{36 if ty==10 else 56}-07-14"),
        "is_unwind": False, "is_mac": False,
    }


def test_spreadover_curve_label():
    out = _labels([_leg("S1", "10Y", 10.0), _leg("S2", "30Y", 30.0)])
    lbl = out.loc[0, "tape_label"]
    assert "SPREADOVER_CURVE" in lbl
    assert "10Y/30Y SPREADOVER_CURVE" in lbl
    # leg scope stays Outright
    assert "Outright" in out.loc[0, "leg_tape_label"]

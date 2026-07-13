import datetime
import numpy as np
import pandas as pd
import pytest
from SDRUtils.stir_flow import tick_size as tk


def test_tenor_bucket_for():
    assert tk.tenor_bucket_for({"special_tenor_type": "FOMC", "fomc_meeting_label": "JUL26",
                                "tenor_label": "2M", "forward_label": None,
                                "forward_start_years": 0.0}) == "FOMC_JUL26"
    assert tk.tenor_bucket_for({"special_tenor_type": "IMM", "fomc_meeting_label": None,
                                "tenor_label": "1Y", "forward_label": "IMM_Z2027",
                                "forward_start_years": 1.4}) == "IMM_1Y"
    assert tk.tenor_bucket_for({"special_tenor_type": "STANDARD", "fomc_meeting_label": None,
                                "tenor_label": "2Y", "forward_label": None,
                                "forward_start_years": 0.0}) == "2Y"
    assert tk.tenor_bucket_for({"special_tenor_type": "STANDARD", "fomc_meeting_label": None,
                                "tenor_label": "1Y", "forward_label": "1Y",
                                "forward_start_years": 1.0}) == "1Yx1Y"


def _prints(rows):
    df = pd.DataFrame(rows)
    df["as_of_date"] = datetime.date(2026, 7, 10)
    df["tenor_bucket"] = "FOMC_JUL26"
    df["structure_type"] = "OUTRIGHT"
    df["execution_session"] = "NY_AM"
    return df


def test_build_tick_pairs_gap_and_session_rules():
    t0 = pd.Timestamp("2026-07-10 14:00:00+00:00")
    rows = [
        dict(execution_timestamp=t0, rate_pct=3.710, dv01=10_000),
        dict(execution_timestamp=t0 + pd.Timedelta(minutes=10), rate_pct=3.715, dv01=10_000),
        dict(execution_timestamp=t0 + pd.Timedelta(minutes=100), rate_pct=3.700, dv01=10_000),  # gap>60m dropped
    ]
    pairs = tk.build_tick_pairs(_prints(rows))
    assert len(pairs) == 1
    assert pairs.iloc[0]["tick_bps"] == pytest.approx(0.5)
    assert pairs.iloc[0]["dv01_bucket"] == "SMALL"

    # different sessions never pair
    df = _prints([
        dict(execution_timestamp=t0, rate_pct=3.710, dv01=10_000),
        dict(execution_timestamp=t0 + pd.Timedelta(minutes=5), rate_pct=3.715, dv01=10_000),
    ])
    df.loc[1, "execution_session"] = "NY_PM"
    assert len(tk.build_tick_pairs(df)) == 0


def test_compute_dispersion_and_curve_suspect():
    # trades agree with each other (disp_vw ~ 0) but sit 2bp from our mid -> suspect
    df = _prints([
        dict(execution_timestamp=pd.Timestamp("2026-07-10 14:00:00+00:00"),
             rate_pct=3.710, dv01=10_000, s2m_bps=2.0),
        dict(execution_timestamp=pd.Timestamp("2026-07-10 14:10:00+00:00"),
             rate_pct=3.7101, dv01=10_000, s2m_bps=2.01),
    ])
    disp = tk.compute_dispersion(df)
    row = disp.iloc[0]
    assert row["disp_jns"] == pytest.approx(2.005, abs=0.01)
    assert row["disp_vw"] < 0.1
    assert bool(row["curve_suspect"]) is True


def test_compute_bucket_stats_medians():
    pairs = pd.DataFrame({
        "tenor_bucket": ["FOMC_JUL26"] * 4, "structure_type": ["OUTRIGHT"] * 4,
        "dv01_bucket": ["SMALL"] * 4, "as_of_date": [datetime.date(2026, 7, 10)] * 4,
        "tick_bps": [0.25, 0.5, 0.5, 1.0],
    })
    prints = _prints([dict(execution_timestamp=pd.Timestamp("2026-07-10 14:00:00+00:00"),
                           rate_pct=3.71, dv01=10_000)])
    prints["rate_index_clean"] = "FED_FUNDS"
    offmkt = pd.DataFrame({
        "tenor_bucket": ["FOMC_JUL26"], "structure_type": ["OUTRIGHT"],
        "dv01_bucket": ["SMALL"], "as_of_date": [datetime.date(2026, 7, 10)],
        "dealer_charge_bps": [0.18],
    })
    stats = tk.compute_bucket_stats(pairs, prints, offmkt)
    small = stats[stats["dv01_bucket"] == "SMALL"].iloc[0]
    assert small["median_tick_bps"] == pytest.approx(0.5)
    assert small["tick_sample_count"] == 4
    assert small["median_dealer_charge_bps"] == pytest.approx(0.18)
    assert small["futures_min_tick_bps"] == pytest.approx(0.5)
    assert (stats["dv01_bucket"] == "ALL").any()


def test_compute_amihud():
    daily = pd.DataFrame({
        "tenor_bucket": ["2Y", "2Y"], "structure_type": ["OUTRIGHT"] * 2,
        "as_of_date": [datetime.date(2026, 7, 9), datetime.date(2026, 7, 10)],
        "vwap_rate_pct": [4.060, 4.065], "total_dv01": [1e6, 2e6],
    })
    am = tk.compute_amihud(daily)
    row = am[am["as_of_date"] == datetime.date(2026, 7, 10)].iloc[0]
    assert row["amihud"] == pytest.approx(0.5 / 2e6)   # 0.5bp move / 2M dv01
    assert am[am["as_of_date"] == datetime.date(2026, 7, 9)]["amihud"].isna().all()

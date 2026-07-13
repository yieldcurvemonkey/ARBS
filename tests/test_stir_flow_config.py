from SDRUtils.stir_flow import config


def test_curve_mapping():
    assert config.CURVE_FOR["SOFR"] == "USD-SOFR-1D-Q12xM12STIRT"
    assert config.CURVE_FOR["FED_FUNDS"] == "USD-OIS-Q12xM12STIRT-SERFFX-MIX23"


def test_dv01_bucket_edges():
    assert config.assign_dv01_bucket(0) == "MICRO"
    assert config.assign_dv01_bucket(4_999) == "MICRO"
    assert config.assign_dv01_bucket(5_000) == "SMALL"
    assert config.assign_dv01_bucket(14_999) == "SMALL"
    assert config.assign_dv01_bucket(15_000) == "MID"
    assert config.assign_dv01_bucket(49_999) == "MID"
    assert config.assign_dv01_bucket(50_000) == "LARGE"
    assert config.assign_dv01_bucket(149_999) == "LARGE"
    assert config.assign_dv01_bucket(150_000) == "BLOCK"
    assert config.assign_dv01_bucket(None) == "UNKNOWN"


def test_futures_tick():
    assert config.futures_tick_bps("FED_FUNDS", "FOMC") == 0.50
    assert config.futures_tick_bps("FED_FUNDS", "STANDARD") == 0.50
    assert config.futures_tick_bps("SOFR", "FOMC") == 0.50   # 1M SOFR futures hedge
    assert config.futures_tick_bps("SOFR", "IMM") == 0.25    # SR3 hedge
    assert config.futures_tick_bps("SOFR", "STANDARD") == 0.25
    assert config.futures_tick_bps("SOFR", None) == 0.25

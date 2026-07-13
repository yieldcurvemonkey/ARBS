import datetime
import pandas as pd
import pytest
import pytz
from SDRUtils.stir_flow import pricing

NY = pytz.timezone("America/New_York")


def test_snap_timestamp_floor_minus_one():
    orig = pd.Timestamp("2026-07-10 16:57:28+00:00")   # 12:57:28 ET
    snap = pricing.snap_timestamp(orig, None)
    assert snap == NY.localize(datetime.datetime(2026, 7, 10, 12, 56))


def test_snap_timestamp_fallback_to_exec():
    exec_ts = pd.Timestamp("2026-07-10 19:41:45+00:00")  # 15:41:45 ET
    snap = pricing.snap_timestamp(pd.NaT, exec_ts)
    assert snap == NY.localize(datetime.datetime(2026, 7, 10, 15, 40))


def test_curve_pricer_memoizes_handles():
    calls = []

    class FakeMDP:
        def _get_curve(self, curve_name, timestamp):
            calls.append((curve_name, timestamp))
            return object()

    p = pricing.CurvePricer(mdp=FakeMDP())
    ts = NY.localize(datetime.datetime(2026, 7, 10, 12, 56))
    h1 = p.handle("USD-OIS-Q12xM12STIRT-SERFFX-MIX23", ts)
    h2 = p.handle("USD-OIS-Q12xM12STIRT-SERFFX-MIX23", ts)
    assert h1 is h2 and len(calls) == 1


@pytest.mark.network
@pytest.mark.slow
def test_price_leg_golden_ff_jul26():
    """User-verified print 4137861837000000101 (POC report 2026-07-12)."""
    import datetime
    p = pricing.CurvePricer()
    ts = NY.localize(datetime.datetime(2026, 7, 10, 15, 40))
    lp = p.price_leg(
        "USD-OIS-Q12xM12STIRT-SERFFX-MIX23", ts,
        datetime.date(2026, 7, 29), datetime.date(2026, 9, 16),
        notional=3_700_000_000, fixed_rate=0.03713,
    )
    assert abs(lp.mid_pct - 3.717511) < 5e-4
    assert abs(lp.npv_pay - 22_555) < 200
    assert abs(lp.pv01 - 50_001) < 25

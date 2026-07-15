# tests/test_stir_ladder_book.py
import datetime
import pandas as pd
import pytest
import pytz
from SDRUtils.stir_flow import book
from SDRUtils.stir_flow.pricing import LegPricing

NY = pytz.timezone("America/New_York")


def test_snap_mtm_floors_without_minus_one():
    ts = NY.localize(datetime.datetime(2026, 7, 14, 8, 29, 45))
    assert book.snap_mtm(ts) == NY.localize(datetime.datetime(2026, 7, 14, 8, 29))


def test_reval_unit_dealer_signed():
    legs = pd.DataFrame([
        dict(effective_date=datetime.date(2026, 7, 29),
             expiration_date=datetime.date(2026, 9, 16),
             notional=3.7e9, fixed_rate=0.03713),
    ])

    class FakePricer:
        def price_leg(self, curve_name, ts, eff, mat, notional, fixed_rate=None):
            return LegPricing(3.7175, 22554.95, 50001.0)

    # dealer PAID (sign -1): dealer npv = +npv_pay
    v = book.reval_unit(legs, [-1], FakePricer(), "C", None)
    assert v == pytest.approx(22554.95)
    # dealer RECEIVED (+1): dealer npv = -npv_pay
    assert book.reval_unit(legs, [1], FakePricer(), "C", None) == pytest.approx(-22554.95)


def test_open_positions_eps_cutoff_and_unwinds():
    ts0 = pd.Timestamp("2026-07-10 14:00:00+00:00")
    prints = pd.DataFrame([
        dict(unit_key="FRESH", bucket_space="MEETING", bucket_key="x", delta_dv01=1.0,
             visibility_timestamp=ts0, p_flip=0.0, curve_suspect_trade=False, is_block=False),
        dict(unit_key="STALE", bucket_space="MEETING", bucket_key="x", delta_dv01=1.0,
             visibility_timestamp=ts0 - pd.Timedelta(minutes=90 * 4), p_flip=0.0,
             curve_suspect_trade=False, is_block=False),
        dict(unit_key="DEAD", bucket_space="MEETING", bucket_key="x", delta_dv01=1.0,
             visibility_timestamp=ts0, p_flip=0.0, curve_suspect_trade=False, is_block=False),
    ])
    unw = pd.DataFrame([dict(unit_key="DEAD", unwind_visibility_ts=ts0 + pd.Timedelta(minutes=1))])
    hl = {"default": 90.0, "block": 240.0}
    open_df = book.open_positions(prints, unw, ts0 + pd.Timedelta(minutes=10), hl)
    assert set(open_df["unit_key"]) == {"FRESH"}     # STALE beyond 3 half-lives, DEAD unwound


def test_book_snapshot_gross_and_residual():
    ts0 = pd.Timestamp("2026-07-10 14:00:00+00:00")
    legs = pd.DataFrame([
        dict(effective_date=datetime.date(2026, 7, 29),
             expiration_date=datetime.date(2026, 9, 16),
             notional=1e9, fixed_rate=0.037),
    ])

    class FakeUnit:
        kind = "OUTRIGHT"
        def __init__(self):
            self.legs = legs

    units = {"T1": FakeUnit()}
    directions = {"T1": dict(unit_key="T1", classification_method="RATE_VS_MID",
                             dealer_direction="PAID", rate_index_clean="FED_FUNDS")}
    prints = pd.DataFrame([
        dict(unit_key="T1", bucket_space="MEETING", bucket_key="2026-07-29",
             delta_dv01=-50000.0, visibility_timestamp=ts0, p_flip=0.0,
             curve_suspect_trade=False, is_block=False),
    ])
    entry_marks = {"T1": 10_000.0}

    class FakePricer:
        def price_leg(self, curve_name, ts, eff, mat, notional, fixed_rate=None):
            return LegPricing(3.71, 25_000.0, 50_000.0)   # npv_pay now 25K

    snap = book.book_snapshot(units, directions, prints, None, FakePricer(),
                              ts0 + pd.Timedelta(minutes=90),
                              half_lives={"default": 90.0, "block": 240.0},
                              entry_marks=entry_marks)
    # dealer PAID: npv = +25,000; pnl = 25,000 - 10,000 = 15,000 gross
    assert snap.gross_pnl_usd == pytest.approx(15_000.0)
    assert snap.residual_pnl_usd == pytest.approx(7_500.0)   # weight 0.5 at one half-life
    assert snap.ladders["MEETING"]["2026-07-29"] == pytest.approx(-25_000.0)


@pytest.mark.network
@pytest.mark.slow
def test_reval_golden_ff_jul26_at_entry_snapshot():
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from SDRUtils.stir_flow.pricing import CurvePricer
    legs = pd.DataFrame([
        dict(effective_date=datetime.date(2026, 7, 29),
             expiration_date=datetime.date(2026, 9, 16),
             notional=3.7e9, fixed_rate=0.03713),
    ])
    ts = NY.localize(datetime.datetime(2026, 7, 10, 15, 40))
    pricer = CurvePricer(mdp=IRSwapsMDP(source="BARCHART_STIRF-RL"))
    v = book.reval_unit(legs, [-1], pricer, "USD-OIS-Q12xM12STIRT-SERFFX-MIX23", ts)
    assert abs(v - 22554.95) < 200

"""G0 label-study tests. The load-bearing one is the STALE-CURVE guard: without it
an independent source that silently returns its last snapshot turns "no data" into
a false flip.
"""
import datetime

import numpy as np
import pandas as pd
import pytest

from BT.dealer_ladder import labels

NY = "America/New_York"


class _Handle:
    def __init__(self, ts):
        self._ts = ts

    def meta(self):
        return {"timestamp": self._ts}


class _Pricer:
    """Stands in for CurvePricer: a fixed curve timestamp and a fixed mid."""

    def __init__(self, curve_ts, mid_pct=4.00, raise_on_price=False):
        self._curve_ts = curve_ts
        self._mid = mid_pct
        self._raise = raise_on_price

    def handle(self, curve_name, ts):
        return _Handle(self._curve_ts)

    def price_leg(self, curve_name, ts, eff, mat, notional, fixed_rate=None):
        from SDRUtils.stir_flow.pricing import LegPricing

        if self._raise:
            raise ValueError("no curve here")
        return LegPricing(mid_pct=self._mid, npv_pay=0.0, pv01=10_000.0)


class _Unit:
    """Mirrors SDRUtils.stir_flow.trade_selection.Unit's surface."""

    kind = "OUTRIGHT"
    is_off_market = False
    unit_key = "T1"
    package_id = None

    def __init__(self, fixed_rate=0.0405):
        self.legs = pd.DataFrame([dict(
            trade_id="T1", as_of_date=datetime.date(2026, 3, 10),
            execution_timestamp=pd.Timestamp("2026-03-10 14:01:00", tz=NY),
            original_execution_timestamp=pd.Timestamp("2026-03-10 14:01:00", tz=NY),
            effective_date=datetime.date(2026, 3, 12),
            expiration_date=datetime.date(2028, 3, 12),
            notional=1e8, fixed_rate=fixed_rate, is_block=False, risk=10_000.0,
            rate_index_clean="SOFR", special_tenor_type="STANDARD",
            # classify_unit reads the upfront columns even on the on-market path
            other_payment_ufro=None, pkg_ptp=None, pkg_pts=None,
            n_package_legs=1, trade_type="OUTRIGHT",
        )])


def _drow(**kw):
    base = dict(unit_key="T1", dealer_direction="RECEIVED",
                classification_method="RATE_VS_MID", spread_to_mid_bps=0.5,
                direction_confidence="HIGH", curve_suspect_trade=False,
                rate_index_clean="SOFR")
    base.update(kw)
    return base


# ------------------------------------------------------------ staleness guard
def test_a_stale_independent_curve_is_no_coverage_not_a_flip():
    """A 14:00 decision against an 11:59 curve is not a comparison."""
    p = _Pricer(curve_ts=pd.Timestamp("2026-03-10 11:59:00"))
    out = labels.reclassify_one(_Unit(), _drow(), p, "USD-SOFR-1D")
    assert out["coverage_ok"] is False
    assert "STALE_INDEPENDENT_CURVE" in out["reason"]
    assert out["ind_direction"] is None
    assert out["ind_staleness_min"] == pytest.approx(121.0, abs=1.0)


def test_a_fresh_curve_is_compared():
    p = _Pricer(curve_ts=pd.Timestamp("2026-03-10 14:00:00"))
    out = labels.reclassify_one(_Unit(), _drow(), p, "USD-SOFR-1D")
    assert out["coverage_ok"] is True
    assert out["ind_direction"] in ("PAID", "RECEIVED")
    assert abs(out["ind_staleness_min"]) <= 5.0


def test_staleness_threshold_is_configurable():
    p = _Pricer(curve_ts=pd.Timestamp("2026-03-10 13:50:00"))
    tight = labels.reclassify_one(_Unit(), _drow(), p, "USD-SOFR-1D",
                                  max_staleness_min=5)
    loose = labels.reclassify_one(_Unit(), _drow(), p, "USD-SOFR-1D",
                                  max_staleness_min=30)
    assert tight["coverage_ok"] is False
    assert loose["coverage_ok"] is True


def test_a_pricing_failure_is_recorded_not_raised():
    p = _Pricer(curve_ts=pd.Timestamp("2026-03-10 14:00:00"), raise_on_price=True)
    out = labels.reclassify_one(_Unit(), _drow(), p, "USD-SOFR-1D")
    assert out["coverage_ok"] is False and "ValueError" in out["reason"]


# ------------------------------------------------------------- flip detection
def test_flip_is_detected_when_the_independent_mid_sits_the_other_side():
    """Traded 4.05%; our mid said BELOW (dealer RECEIVED). An independent mid ABOVE
    the trade flips it to PAID."""
    p = _Pricer(curve_ts=pd.Timestamp("2026-03-10 14:00:00"), mid_pct=4.10)
    out = labels.reclassify_one(_Unit(fixed_rate=0.0405), _drow(), p, "USD-SOFR-1D")
    assert out["coverage_ok"] is True
    assert out["ind_direction"] == "PAID"
    assert out["our_direction"] == "RECEIVED"


def test_agreement_when_both_mids_agree():
    p = _Pricer(curve_ts=pd.Timestamp("2026-03-10 14:00:00"), mid_pct=4.00)
    out = labels.reclassify_one(_Unit(fixed_rate=0.0405), _drow(), p, "USD-SOFR-1D")
    assert out["ind_direction"] == "RECEIVED" == out["our_direction"]


# ------------------------------------------------------------------- tables
def _recon():
    return pd.DataFrame([
        dict(unit_key="a", our_confidence="HIGH", trade_type="OUTRIGHT",
             our_direction="PAID", ind_direction="PAID", coverage_ok=True,
             flipped=0.0),
        dict(unit_key="b", our_confidence="HIGH", trade_type="OUTRIGHT",
             our_direction="PAID", ind_direction="RECEIVED", coverage_ok=True,
             flipped=1.0),
        dict(unit_key="c", our_confidence="LOW", trade_type="CURVE",
             our_direction="PAID", ind_direction="RECEIVED", coverage_ok=True,
             flipped=1.0),
        dict(unit_key="d", our_confidence="LOW", trade_type="CURVE",
             our_direction=None, ind_direction=None, coverage_ok=False,
             flipped=np.nan),
    ])


def test_flip_rate_table_reports_the_coverage_denominator():
    """A stratum the independent source barely covers must not look clean."""
    out = labels.flip_rate_table(_recon(), ("our_confidence",)).set_index("our_confidence")
    assert out.loc["HIGH", "n_compared"] == 2
    assert out.loc["HIGH", "flip_rate"] == pytest.approx(0.5)
    assert out.loc["LOW", "n_compared"] == 1
    assert out.loc["LOW", "n_no_coverage"] == 1


def test_flip_rate_table_empty():
    assert labels.flip_rate_table(pd.DataFrame()).empty


def test_direction_skew_table_puts_the_two_paid_shares_side_by_side():
    """The adjudication of the ~67-72% PAID skew."""
    out = labels.direction_skew_table(_recon())
    row = out.iloc[0]
    assert row["n"] == 3
    assert row["our_paid_share"] == pytest.approx(1.0)     # all three ours say PAID
    assert row["ind_paid_share"] == pytest.approx(1 / 3)   # independent says PAID once
    assert row["flip_rate"] == pytest.approx(2 / 3)


def test_direction_skew_table_ignores_uncovered_rows():
    df = _recon()
    df.loc[df["unit_key"] == "d", "our_direction"] = "PAID"
    out = labels.direction_skew_table(df)
    assert out.iloc[0]["n"] == 3     # 'd' still excluded: flipped is NaN


@pytest.mark.parametrize("flip,ceiling,atten", [
    (0.0, 1.0, 1.0),
    (0.2, 0.9, 0.8),
    (0.5, 0.75, 0.5),
    (1.0, 0.5, 0.0),
])
def test_implied_accuracy_bounds(flip, ceiling, atten):
    out = labels.implied_accuracy_bounds(flip)
    assert out["accuracy_ceiling"] == pytest.approx(ceiling)
    assert out["attenuation_at_ceiling"] == pytest.approx(atten)


def test_implied_accuracy_bounds_on_nan():
    out = labels.implied_accuracy_bounds(np.nan)
    assert np.isnan(out["accuracy_ceiling"])


def test_independent_pricer_rejects_an_unknown_source():
    with pytest.raises(ValueError, match="unknown independent source"):
        labels.independent_pricer("not_a_source")


def test_reclassify_units_skips_fed_funds():
    """Both independent sources are SOFR curves; FF has no cross-check."""
    units = {"T1": _Unit()}
    rows = [_drow(rate_index_clean="FED_FUNDS")]
    out = labels.reclassify_units(units, rows, source="citivelo")
    assert out.empty


# --------------------------------------------------- stratified sampling for G0
def _pool(n_per_hour=6, hours=(2, 3, 9, 10, 14, 15), days=("2026-03-10", "2026-03-11")):
    rows = []
    for d in days:
        for h in hours:
            for i in range(n_per_hour):
                rows.append(dict(
                    unit_key=f"{d}-{h}-{i}", as_of_date=d,
                    execution_timestamp=pd.Timestamp(f"{d} {h:02d}:{i:02d}:00", tz=NY),
                    rate_index_clean="SOFR"))
    return rows


def test_stratified_sample_spreads_across_the_session():
    """A head-N took 25 prints all from 02:16-03:59 ET -- the thinnest hours, where
    mid quality is worst. The sample must describe the day, not its quiet corner."""
    pool = _pool()
    out = labels.stratified_sample(pool, per_day=12, seed=0)
    frame = pd.DataFrame(out)
    hours = (pd.to_datetime(frame["execution_timestamp"], utc=True)
             .dt.tz_convert(NY).dt.hour)
    assert frame["as_of_date"].nunique() == 2
    # every hour present in the pool must be represented, not just the earliest
    assert set(hours.unique()) == {2, 3, 9, 10, 14, 15}


def test_stratified_sample_respects_per_day_cap():
    out = labels.stratified_sample(_pool(), per_day=6, seed=1)
    frame = pd.DataFrame(out)
    assert (frame.groupby("as_of_date").size() <= 6).all()


def test_stratified_sample_tops_up_a_thin_hour_day():
    """A day whose hours cannot fill the quota must still return what it has."""
    pool = _pool(n_per_hour=1, hours=(9, 10))
    out = labels.stratified_sample(pool, per_day=20, seed=2)
    assert len(out) == 4          # 2 days x 2 hours x 1 print


def test_stratified_sample_is_deterministic_for_a_seed():
    a = labels.stratified_sample(_pool(), per_day=10, seed=7)
    b = labels.stratified_sample(_pool(), per_day=10, seed=7)
    assert [r["unit_key"] for r in a] == [r["unit_key"] for r in b]


def test_stratified_sample_empty_and_passthrough():
    assert labels.stratified_sample([], per_day=5) == []
    plain = [{"unit_key": "x"}, {"unit_key": "y"}]     # no date/timestamp columns
    assert len(labels.stratified_sample(plain, per_day=1)) == 1

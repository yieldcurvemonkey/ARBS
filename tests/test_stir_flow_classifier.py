import datetime
import pandas as pd
import pytest
from SDRUtils.stir_flow.classifier import classify_unit, structure_dv01
from SDRUtils.stir_flow.pricing import LegPricing
from SDRUtils.stir_flow.trade_selection import Unit


def _legs(rows):
    return pd.DataFrame(rows)


def _leg_row(trade_id, rate, ufro=0.0, ptp=None, notional=1e9,
             eff="2026-07-29", mat="2026-09-16"):
    return dict(
        trade_id=trade_id, package_id="P", fixed_rate=rate,
        other_payment_ufro=ufro, pkg_ptp=ptp, notional=notional,
        effective_date=datetime.date.fromisoformat(eff),
        expiration_date=datetime.date.fromisoformat(mat),
        is_block=False,
    )


def test_structure_dv01_conventions():
    assert structure_dv01("OUTRIGHT", [50_000.0]) == 50_000.0
    assert structure_dv01("CURVE", [100_003.0, 100_328.0]) == 100_328.0
    assert structure_dv01("FLY", [8_578.0, 16_986.0, 8_471.0]) == 16_986.0
    assert structure_dv01("PKG", [10_000.0, 10_000.0, 20_000.0]) == 20_000.0


def test_on_market_outright_received():
    # FF FOMC SEP26 print 4135037480000000101: traded 3.8320 vs mid 3.812597
    u = Unit("T", "OUTRIGHT", _legs([_leg_row("T", 0.03832)]), None, False)
    r = classify_unit(u, [LegPricing(3.812597, None, 149_917.0)])
    assert r.classification_method == "RATE_VS_MID"
    assert r.dealer_direction == "RECEIVED"
    assert abs(r.spread_to_mid_bps - 1.9403) < 0.01


def test_off_market_outright_bought_paid():
    # user-verified 4137861837000000101: NPV_pay 22,555 vs UFRO 13,427.27
    u = Unit("T", "OUTRIGHT", _legs([_leg_row("T", 0.03713, ufro=13427.26854, notional=3.7e9)]), None, True)
    r = classify_unit(u, [LegPricing(3.717511, 22554.95, 50000.99)])
    assert r.classification_method == "NPV_VS_UPFRONT"
    assert r.dealer_bought is True and r.dealer_direction == "PAID"
    assert abs(r.dealer_charge - 9127.68) < 1.0
    assert abs(r.dealer_charge_bps - 0.1826) < 0.005


def test_on_market_curve_paid_spread():
    # FF SEP26/OCT26 curve: traded 5.550bp vs mid 8.251bp
    legs = _legs([
        _leg_row("A", 0.038151, eff="2026-09-16", mat="2026-10-28"),
        _leg_row("B", 0.038706, eff="2026-10-28", mat="2026-12-09"),
    ])
    u = Unit("P", "CURVE", legs, "P", False)
    r = classify_unit(u, [
        LegPricing(3.800453, None, 74_960.34),
        LegPricing(3.882959, None, 74_622.04),
    ])
    assert r.classification_method == "SPREAD_VS_MID"
    assert r.dealer_direction == "PAID"
    assert abs(r.traded_spread_bps - 5.550) < 0.01
    assert abs(r.curve_mid_spread_bps - 8.2506) < 0.01
    assert abs(r.spread_to_mid_bps - (-2.7006)) < 0.01
    assert r.structure_dv01 == pytest.approx(74_960.34)


def test_off_market_curve_bought_via_ptp():
    # user-verified PTP_4135370792000000201: NPV_pay -94,254 vs |PTP| 48,419
    legs = _legs([
        _leg_row("A", 0.037097, ufro=22998.45996, ptp=-48419.0, notional=7.4e9),
        _leg_row("B", 0.038335, ufro=25502.85562, ptp=-48419.0, notional=8.7e9,
                 eff="2026-09-16", mat="2026-10-28"),
    ])
    u = Unit("P", "CURVE", legs, "P", True)
    r = classify_unit(u, [
        LegPricing(3.711621, 19207.35, 100_003.19),
        LegPricing(3.822191, -113461.62, 100_327.57),
    ])
    assert r.reported_ptp == -48419.0
    assert r.dealer_bought is True and r.dealer_direction == "RECEIVED"
    assert abs(r.repriced_npv - (-94254.26)) < 1.0
    assert abs(r.dealer_charge - 45835.26) < 1.0
    assert abs(r.dealer_charge_bps - 0.4569) < 0.005


def test_off_market_curve_sold():
    # PTP_4129543090000000501: NPV_pay -201,564 vs |PTP| 251,977 -> SOLD/PAID
    legs = _legs([
        _leg_row("A", 0.03713, ufro=204640.92, ptp=-251977.0, notional=5.5e9),
        _leg_row("B", 0.03799, ufro=45463.44, ptp=-251977.0, notional=6.5e9,
                 eff="2026-09-16", mat="2026-10-28"),
    ])
    u = Unit("P", "CURVE", legs, "P", True)
    r = classify_unit(u, [
        LegPricing(3.692295, -153895.99, 74_328.99),
        LegPricing(3.792641, -47667.82, 74_962.26),
    ])
    assert r.dealer_bought is False and r.dealer_direction == "PAID"
    assert abs(r.dealer_charge_bps - 0.6725) < 0.005


def test_on_market_fly_received():
    # SOFR 8M/9M/1Y fly: traded -3.970 vs mid -4.031
    legs = _legs([
        _leg_row("A", 0.039060, eff="2026-07-14", mat="2027-03-14"),
        _leg_row("B", 0.039339, eff="2026-07-14", mat="2027-04-14"),
        _leg_row("C", 0.040015, eff="2026-07-14", mat="2027-07-14"),
    ])
    u = Unit("P", "FLY", legs, "P", False)
    r = classify_unit(u, [
        LegPricing(3.906754, None, 8578.47),
        LegPricing(3.934867, None, 16985.91),
        LegPricing(4.003289, None, 8471.46),
    ])
    assert r.classification_method == "FLY_VS_MID"
    assert r.dealer_direction == "RECEIVED"
    assert abs(r.spread_to_mid_bps - 0.0610) < 0.005


def test_off_market_missing_upfront_is_unknown():
    u = Unit("T", "OUTRIGHT", _legs([_leg_row("T", 0.03713)]), None, True)
    r = classify_unit(u, [LegPricing(3.7175, 22554.95, 50001.0)])
    # unit flagged off-market but no UFRO/PTP resolvable -> UNKNOWN + flag
    assert r.dealer_direction == "UNKNOWN"
    assert "NO_UPFRONT" in r.quality_flags

import datetime as dt

import pandas as pd
import pytest
import pytz
import rateslib as rl
from rateslib.scheduling import get_imm

from MDP.IRSwaps.BARCHART_STIRF.rl import BARCHART_STIRF_CURVE, _build_curve_from_pricers_core
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue
from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve
from Query.STIRFutures.backends.rateslib.RLSTIRFuturePricer import RLSTIRFuturePricer


class _FakePricer:
    def __init__(self, symbol: str, price: float):
        self._rl_stirf_id = symbol
        self._meta_data = {"symbol": symbol}
        self._effective_date = dt.date(2026, 6, 17)
        self._maturity_date = dt.date(2026, 9, 16)
        self._price = float(price)
        self._rate = float(100.0 - price)
        self._contracts = 1


def _curve_tail_value(curve: rl.Curve) -> float:
    return float(list(curve.nodes.nodes.values())[-1])


def _imm_date(code: str) -> dt.date:
    imm = get_imm(code=code)
    if isinstance(imm, dt.datetime):
        return imm.date()
    return imm


def test_build_curve_coalesces_identical_pricer_snapshots(monkeypatch):
    builder = BARCHART_STIRF_CURVE()
    curve_name = "USD-SOFR-1D-Q12STIRT"
    cfg = builder._STIRF_CURVE_CONFIGS[curve_name]
    utc = pytz.UTC
    ts1 = utc.localize(dt.datetime(2026, 3, 12, 12, 0))
    ts2 = utc.localize(dt.datetime(2026, 3, 12, 12, 1))
    ts3 = utc.localize(dt.datetime(2026, 3, 12, 12, 2))

    pricers_by_ts = {
        ts1: {"LEG": [_FakePricer("SFRCM1", 95.25)]},
        ts2: {"LEG": [_FakePricer("SFRCM1", 95.25)]},
        ts3: {"LEG": [_FakePricer("SFRCM1", 95.10)]},
    }
    build_calls: list[dt.datetime] = []

    monkeypatch.setattr(builder, "_curve_cache_daily_bundle_get", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder, "_curve_cache_bulk_get", lambda curve_name, timestamps, cfg: ({}, list(timestamps)))
    monkeypatch.setattr(builder, "_persist_bulk_curves", lambda **kwargs: None)
    monkeypatch.setattr(builder, "_mem_cache_put", lambda *args, **kwargs: None)

    def _resolve_fetchers(*, cfg, is_live_request):
        _ = cfg, is_live_request
        return (
            lambda request: pricers_by_ts[request["timestamp"]],
            lambda request: {ts: pricers_by_ts[ts] for ts in request["timestamps"]},
        )

    monkeypatch.setattr(builder, "_resolve_fetchers_for_request", _resolve_fetchers)

    def _build_curve_from_pricers(*, curve_name, timestamp, cfg, pricers, initial_nodes=None, solver_tolerances=None):
        _ = curve_name, timestamp, initial_nodes, solver_tolerances
        build_calls.append(timestamp)
        price = next(iter(pricers.values()))[0]._price
        curve = rl.Curve(
            nodes={
                rl.dt(2026, 3, 12): 1.0,
                rl.dt(2027, 3, 12): 1.0 - price / 10_000.0,
            },
            id=cfg["reference_key"],
        )
        return curve, None

    monkeypatch.setattr(builder, "_build_curve_from_pricers", _build_curve_from_pricers)

    out = builder.build_curve(
        curve_name=curve_name,
        timestamp=[ts1, ts2, ts3],
        kwargs={
            "show_tqdm": False,
            "auto_prime_bulk": False,
            "calibration_max_workers": 1,
        },
        curve_only=True,
    )

    assert build_calls == [ts1, ts3]
    assert set(out) == {ts1, ts2, ts3}
    assert out[ts1] is not out[ts2]
    assert out[ts1].timestamp == ts1
    assert out[ts2].timestamp == ts2
    assert _curve_tail_value(out[ts1]) == _curve_tail_value(out[ts2])
    assert _curve_tail_value(out[ts1]) != _curve_tail_value(out[ts3])


def test_q12stirt_explicit_imm_swap_rate_matches_raw_sfr_contract():
    builder = BARCHART_STIRF_CURVE()
    curve_name = "USD-SOFR-1D-Q12STIRT"
    cfg = builder._STIRF_CURVE_CONFIGS[curve_name]
    timestamp = pytz.timezone("America/New_York").localize(dt.datetime(2026, 5, 4, 14, 0))
    codes = ["M26", "U26", "Z26", "H27", "M27", "U27", "Z27", "H28", "M28", "U28", "Z28", "H29", "M29"]
    rates = [3.655, 3.705, 3.800, 3.865, 3.850, 3.775, 3.700, 3.660, 3.650, 3.660, 3.685, 3.710, 3.740]

    pricers = {}
    for idx, code in enumerate(codes):
        next_code = codes[idx + 1] if idx + 1 < len(codes) else "U29"
        pricers[f"SFRCM{idx + 1}"] = [
            RLSTIRFuturePricer(
                rl_stirf_id=f"SR3{code}",
                reference_date=timestamp.date(),
                effective_date=_imm_date(code),
                maturity_date=_imm_date(next_code),
                curve="USD-SOFR-1D",
                rate=rates[idx],
                contracts=1,
                meta_data={},
            )
        ]

    rl_curve, _ = _build_curve_from_pricers_core(
        curve_name=curve_name,
        timestamp=timestamp,
        cfg=cfg,
        pricers=pricers,
    )
    curve = RLIRSwapCurve(
        rl_curve_id="USD-SOFR-1D",
        rl_curve_handle=rl_curve,
        fixings=pd.Series([3.64], index=[pd.Timestamp("2026-05-01")]),
        meta_data={"curve_name": curve_name, "timestamp": timestamp},
    )
    query = IRSwapQuery(curve=curve_name, tenor="IMM_Z26xIMM_H27", structure_kwargs={"bpv": 100_000}).resolve_query(
        timestamp,
        pricer_or_curve=curve,
    )
    package, risk_weights = query.resolve_package(pricer_or_curve=curve)
    value_map = query.build_value_map(pricer_or_curve=curve, package=package, risk_weights=risk_weights)

    assert value_map.apply(value=IRSwapValue.RATE) == pytest.approx(3.800, abs=1e-7)

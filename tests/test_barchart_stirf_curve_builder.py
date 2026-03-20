import datetime as dt

import pytz
import rateslib as rl

from MDP.IRSwaps.BARCHART_STIRF.rl import BARCHART_STIRF_CURVE


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

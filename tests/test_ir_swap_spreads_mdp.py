import datetime
from dataclasses import dataclass
from typing import Any, Dict, Optional

import pandas as pd
import pytest

from MDP.IRSwapSpreads.IRSwapSpreadsMDP import IRSwapSpreadsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue
from TB.TimeseriesBuilder import TimeseriesBuilder


@dataclass
class _FakeSwapInstrument:
    tenor: Optional[str]
    effective_date: Optional[datetime.date]
    maturity_date: Optional[datetime.date]
    fixed_rate: float
    notional: float


class _FakeCurve:
    def __init__(self, *, reference_date: datetime.date, rate_decimal: float):
        self._reference_date = reference_date
        self._rate_decimal = float(rate_decimal)
        self.build_calls: list[_FakeSwapInstrument] = []

    def id(self) -> str:
        return "USD-SOFR-1D"

    def reference_date(self) -> datetime.date:
        return self._reference_date

    def calendar(self) -> Any:
        return None

    def calendar_advance(self, dt1: datetime.date, dt2: Any) -> datetime.date:
        if isinstance(dt2, str) and dt2.upper() == "2D":
            return dt1 + datetime.timedelta(days=2)
        return dt1

    def daycounter(self) -> Any:
        return None

    def handle(self) -> Any:
        return None

    def index(self) -> pd.Series:
        return pd.Series(dtype=float)

    def meta(self) -> Dict[str, Any]:
        return {"requested_curve_name": "USD-SOFR-1D"}

    def effective_date(self, irswap: _FakeSwapInstrument) -> datetime.date:
        return irswap.effective_date or self._reference_date

    def maturity_date(self, irswap: _FakeSwapInstrument) -> datetime.date:
        return irswap.maturity_date or self._reference_date

    def fixed_rate(self, irswap: _FakeSwapInstrument) -> float:
        return irswap.fixed_rate

    def set_fixed_rate(self, irswap: _FakeSwapInstrument, rate_decimal: float) -> None:
        irswap.fixed_rate = float(rate_decimal)

    def notional(self, irswap: _FakeSwapInstrument) -> float:
        return irswap.notional

    def fair_rate(self, irswap: _FakeSwapInstrument) -> float:
        _ = irswap
        return self._rate_decimal

    def npv(self, irswap: _FakeSwapInstrument) -> float:
        _ = irswap
        return 0.0

    def pv01(self, irswap: _FakeSwapInstrument) -> float:
        _ = irswap
        return 100.0

    def dv01(self, irswap: _FakeSwapInstrument, shift: float = 1e-4) -> float:
        _ = irswap, shift
        return 100.0

    def gamma(self, irswap: _FakeSwapInstrument, shift: float = 1e-4) -> float:
        _ = irswap, shift
        return 0.0

    def dollar_carry(self, irswap: _FakeSwapInstrument, horizon: str) -> float:
        _ = irswap, horizon
        return 0.0

    def carry_bps_running(self, irswap: _FakeSwapInstrument, horizon: str) -> float:
        _ = irswap, horizon
        return 0.0

    def roll_bps_running(self, irswap: _FakeSwapInstrument, horizon: str) -> float:
        _ = irswap, horizon
        return 0.0

    def carry_and_roll_bps_running(self, irswap: _FakeSwapInstrument, horizon: str) -> float:
        _ = irswap, horizon
        return 0.0

    def nodes(self) -> Dict[datetime.date, float]:
        return {self._reference_date: 0.95}

    def resolve_pricable(self, irswap: _FakeSwapInstrument, risk_weight: Optional[float] = None) -> _FakeSwapInstrument:
        _ = risk_weight
        return irswap

    def build_irswap(
        self,
        fwd: Optional[str] = None,
        tenor: Optional[str] = None,
        effective_date: Optional[datetime.date] = None,
        maturity_date: Optional[datetime.date] = None,
        fixed_rate: Optional[float] = -0.00,
        notional: Optional[float] = None,
        bpv: Optional[float] = None,
    ) -> _FakeSwapInstrument:
        _ = fwd
        resolved_notional = float(notional if notional is not None else (bpv / 0.0001 if bpv is not None else 1_000_000.0))
        inst = _FakeSwapInstrument(
            tenor=tenor,
            effective_date=effective_date,
            maturity_date=maturity_date,
            fixed_rate=float(fixed_rate or 0.0),
            notional=resolved_notional,
        )
        self.build_calls.append(inst)
        return inst


class _FakeBondPricer:
    def __init__(self, ytm_percent: float):
        self._ytm_percent = float(ytm_percent)

    def id(self) -> str:
        return "USTS"

    def reference_date(self) -> datetime.date:
        return datetime.date(2026, 1, 2)

    def calendar(self) -> Any:
        return None

    def calendar_advance(self, dt1: datetime.date, dt2: Any) -> datetime.date:
        _ = dt2
        return dt1

    def meta(self) -> Dict[str, Any]:
        return {}

    def issue_date(self) -> datetime.date:
        return datetime.date(2025, 1, 15)

    def maturity_date(self) -> datetime.date:
        return datetime.date(2036, 3, 1)

    def coupon(self) -> float:
        return 0.04

    def notional(self) -> float:
        return 100.0

    def ytm(self) -> float:
        return self._ytm_percent

    def dirty_price(self) -> float:
        return 101.0

    def clean_price(self) -> float:
        return 100.5

    def npv(self) -> float:
        return 0.0

    def accured(self) -> float:
        return 0.0

    def pv01(self) -> float:
        return 1.0

    def mod_duration(self) -> float:
        return 0.0

    def convexity(self) -> float:
        return 0.0

    def time_to_maturity(self) -> float:
        return 10.0

    def resolve_pricable(self, frb: Any, risk_weight: Optional[float] = None) -> Any:
        _ = risk_weight
        return frb

    def build_fixed_rate_bond(
        self,
        issue_date: Optional[datetime.date] = None,
        maturity_date: Optional[datetime.date] = None,
        coupon: Optional[float] = -0.00,
        notional: Optional[float] = None,
        bpv: Optional[float] = None,
    ) -> Any:
        return {
            "issue_date": issue_date,
            "maturity_date": maturity_date,
            "coupon": coupon,
            "notional": notional,
            "bpv": bpv,
        }


class _CaptureIRSMDP:
    def __init__(self, curve: _FakeCurve):
        self.curve = curve
        self.requests: list[Dict[str, Any]] = []

    def get_pricer(self, request: Dict[str, Any]) -> _FakeCurve:
        self.requests.append(dict(request))
        return self.curve


class _CaptureFRBMDP:
    def __init__(self, bond_pricer: _FakeBondPricer):
        self.bond_pricer = bond_pricer
        self.requests: list[Dict[str, Any]] = []

    def get_pricer(self, request: Dict[str, Any]) -> Dict[str, _FakeBondPricer]:
        req = dict(request)
        self.requests.append(req)
        symbol = req["cusips"][0]
        return {symbol: self.bond_pricer}


class _StaticSpreadPricer:
    def __init__(self, value_bps: float):
        self._value_bps = float(value_bps)

    def value_bps(self) -> float:
        return self._value_bps


class _StaticSpreadMDP:
    def __init__(self, mmss_bps: float = 18.5):
        self.mmss_bps = float(mmss_bps)
        self.requests: list[Dict[str, Any]] = []

    def get_pricer(self, request: Dict[str, Any]) -> _StaticSpreadPricer:
        self.requests.append(dict(request))
        value = request.get("value")
        if value == IRSwapValue.MARKET_ASW:
            return _StaticSpreadPricer(27.25)
        if value in {
            IRSwapValue.MMSS_CARRY_ADJUSTED,
            IRSwapValue.SPREADOVER_CARRY_ADJUSTED,
            IRSwapValue.MMSS_ROLL_ADJUSTED,
            IRSwapValue.SPREADOVER_ROLL_ADJUSTED,
            IRSwapValue.MMSS_CR_ADJUSTED,
            IRSwapValue.SPREADOVER_CR_ADJUSTED,
        }:
            return _StaticSpreadPricer(21.75)
        return _StaticSpreadPricer(self.mmss_bps)


def test_mmss_pricer_uses_matched_maturity_swap_query(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "Query.IRSwaps.adapter._resolve_cusip_or_alias",
        lambda token, as_of: ("91282CLZ0", datetime.date(2036, 3, 1)),
    )

    ref_date = datetime.date(2026, 1, 2)
    curve = _FakeCurve(reference_date=ref_date, rate_decimal=0.0425)
    irs_mdp = _CaptureIRSMDP(curve)
    frb_mdp = _CaptureFRBMDP(_FakeBondPricer(ytm_percent=4.00))
    mdp = IRSwapSpreadsMDP(_irs_mdp=irs_mdp, _frb_mdp=frb_mdp)

    pricer = mdp.get_pricer(
        {
            "curve_name": "USD-SOFR-1D",
            "timestamp": ref_date,
            "tenor": "CT10",
            "value": IRSwapValue.MMSS,
        }
    )

    assert irs_mdp.requests == [{"curve_name": "USD-SOFR-1D", "timestamp": ref_date}]
    assert frb_mdp.requests == [{"cusips": ["CT10"], "timestamp": ref_date}]
    assert pricer.swap_query is not None
    assert pricer.swap_query.tenor == "CT10"
    assert pricer.swap_rate_percent() == pytest.approx(4.25)
    assert pricer.spread_bps() == pytest.approx(25.0)
    assert curve.build_calls[-1].effective_date == datetime.date(2026, 1, 4)
    assert curve.build_calls[-1].maturity_date == datetime.date(2036, 3, 1)


def test_spreadover_maps_ct_alias_to_benchmark_swap_tenor():
    ref_date = datetime.date(2026, 1, 2)
    curve = _FakeCurve(reference_date=ref_date, rate_decimal=0.0430)
    irs_mdp = _CaptureIRSMDP(curve)
    frb_mdp = _CaptureFRBMDP(_FakeBondPricer(ytm_percent=4.00))
    mdp = IRSwapSpreadsMDP(_irs_mdp=irs_mdp, _frb_mdp=frb_mdp)

    pricer = mdp.get_pricer(
        {
            "curve_name": "USD-SOFR-1D",
            "timestamp": ref_date,
            "tenor": "CT10",
            "value": IRSwapValue.SPREADOVER,
        }
    )

    assert irs_mdp.requests == [{"curve_name": "USD-SOFR-1D", "timestamp": ref_date}]
    assert frb_mdp.requests == [{"cusips": ["CT10"], "timestamp": ref_date}]
    assert pricer.swap_query is not None
    assert pricer.swap_query.tenor == "10Y"
    assert pricer.spread_bps() == pytest.approx(30.0)
    assert curve.build_calls[-1].tenor == "10Y"


def test_asset_swap_values_dispatch_to_quantlib_helper(monkeypatch: pytest.MonkeyPatch):
    ref_date = datetime.date(2026, 1, 2)
    curve = _FakeCurve(reference_date=ref_date, rate_decimal=0.0425)
    irs_mdp = _CaptureIRSMDP(curve)
    frb_mdp = _CaptureFRBMDP(_FakeBondPricer(ytm_percent=4.00))
    mdp = IRSwapSpreadsMDP(_irs_mdp=irs_mdp, _frb_mdp=frb_mdp)

    seen: Dict[str, Any] = {}

    def _fake_asw(swap_curve, frb_pricer, *, curve_name=None, par_par_asw=True):
        seen["swap_curve"] = swap_curve
        seen["frb_pricer"] = frb_pricer
        seen["curve_name"] = curve_name
        seen["par_par_asw"] = par_par_asw
        return 37.5

    monkeypatch.setattr(
        "MDP.IRSwapSpreads.IRSwapSpreadsMDP.fair_asset_swap_spread_bps",
        _fake_asw,
    )

    pricer = mdp.get_pricer(
        {
            "curve_name": "USD-SOFR-1D",
            "timestamp": ref_date,
            "tenor": "CT10",
            "value": IRSwapValue.PAR_PAR_ASW,
        }
    )

    assert pricer.value_bps() == pytest.approx(37.5)
    assert seen["swap_curve"] is curve
    assert seen["curve_name"] == "USD-SOFR-1D"
    assert seen["par_par_asw"] is True


@pytest.mark.parametrize(
    ("value", "expected_bps"),
    [
        (IRSwapValue.MMSS_CARRY_ADJUSTED, 26.5),
        (IRSwapValue.MMSS_ROLL_ADJUSTED, 24.5),
        (IRSwapValue.MMSS_CR_ADJUSTED, 26.0),
        (IRSwapValue.SPREADOVER_CARRY_ADJUSTED, 31.5),
        (IRSwapValue.SPREADOVER_ROLL_ADJUSTED, 29.5),
        (IRSwapValue.SPREADOVER_CR_ADJUSTED, 31.0),
    ],
)
def test_adjusted_swap_spread_values_add_cached_adjustments(monkeypatch: pytest.MonkeyPatch, value: IRSwapValue, expected_bps: float):
    ref_date = datetime.date(2026, 1, 2)
    curve = _FakeCurve(reference_date=ref_date, rate_decimal=0.0425 if value.name.startswith("MMSS") else 0.0430)
    irs_mdp = _CaptureIRSMDP(curve)
    frb_mdp = _CaptureFRBMDP(_FakeBondPricer(ytm_percent=4.00))
    mdp = IRSwapSpreadsMDP(_irs_mdp=irs_mdp, _frb_mdp=frb_mdp)

    monkeypatch.setattr(
        IRSwapSpreadsMDP,
        "_compute_adjustment_bps",
        lambda self, **kwargs: {"carry": 1.5, "roll": -0.5, "carry_and_roll": 1.0},
    )

    pricer = mdp.get_pricer(
        {
            "curve_name": "USD-SOFR-1D",
            "timestamp": ref_date,
            "tenor": "CT10",
            "value": value,
        }
    )

    assert pricer.value_bps() == pytest.approx(expected_bps)


def test_timeseries_builder_can_use_explicit_irswap_spreads_mdp():
    spread_mdp = _StaticSpreadMDP(mmss_bps=18.5)
    tb = TimeseriesBuilder()

    q = IRSwapQuery(curve="USD-SOFR-1D", tenor="CT10", value=IRSwapValue.MMSS)
    out = tb.get_timeseries(
        start=datetime.date(2026, 1, 5),
        end=datetime.date(2026, 1, 6),
        queries=[q],
        mdps={"IRSWAPSPREADS": spread_mdp},
        drop_multilevel_cols=False,
    )

    assert not out.empty
    assert len(spread_mdp.requests) == 2
    assert all(req["value"] == IRSwapValue.MMSS for req in spread_mdp.requests)
    assert out.iloc[0, 0] == pytest.approx(18.5)


def test_timeseries_builder_routes_adjusted_swap_spreads_to_explicit_spread_mdp():
    spread_mdp = _StaticSpreadMDP(mmss_bps=18.5)
    tb = TimeseriesBuilder()

    q = IRSwapQuery(curve="USD-SOFR-1D", tenor="CT10", value=IRSwapValue.MMSS_CR_ADJUSTED)
    out = tb.get_timeseries(
        start=datetime.date(2026, 1, 5),
        end=datetime.date(2026, 1, 6),
        queries=[q],
        mdps={"IRSWAPSPREADS": spread_mdp},
        drop_multilevel_cols=False,
    )

    assert not out.empty
    assert len(spread_mdp.requests) == 2
    assert all(req["value"] == IRSwapValue.MMSS_CR_ADJUSTED for req in spread_mdp.requests)
    assert out.iloc[0, 0] == pytest.approx(21.75)


def test_timeseries_builder_explicit_spread_mdp_handles_asw_only_queries():
    spread_mdp = _StaticSpreadMDP(mmss_bps=18.5)
    tb = TimeseriesBuilder()

    q = IRSwapQuery(curve="USD-SOFR-1D", tenor="CT10", value=IRSwapValue.MARKET_ASW)
    out = tb.get_timeseries(
        start=datetime.date(2026, 1, 5),
        end=datetime.date(2026, 1, 6),
        queries=[q],
        mdps={"IRSWAPSPREADS": spread_mdp},
    )

    assert not out.empty
    assert list(out.columns) == [q.col_name()]
    assert out.iloc[0, 0] == pytest.approx(27.25)

import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd

from BT.signals.rv_backtest import RVBacktestConfig, run_query_rv_backtest
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue


class _BondInstrument:
    def __init__(self, *, cusip: str, issue_date: dt.date, maturity_date: dt.date, cpn: float, notional: float):
        self.cusip = cusip
        self.issue_date = issue_date
        self.maturity_date = maturity_date
        self.cpn = cpn
        self.notional = notional


class _MockBondPricer:
    def __init__(
        self,
        cusip: str | None = None,
        *,
        as_of: dt.date | None = None,
        reference_date: dt.date | None = None,
        issue_date: dt.date | None = None,
        maturity_date: dt.date | None = None,
        cpn: float | None = None,
        coupon: float | None = None,
        clean_price: float | None = None,
        ytm: float | None = None,
        notional: float | None = None,
        meta_data: dict | None = None,
        ql_frb_id: str | None = None,
        rl_frb_id: str | None = None,
    ):
        resolved_meta = dict(meta_data or {})
        self._cusip = str(cusip or resolved_meta.get("cusip") or "MOCK")
        self._as_of = reference_date or as_of or dt.date.today()
        self._issue_date = issue_date or (self._as_of - dt.timedelta(days=365))
        self._maturity_date = maturity_date or (self._as_of + dt.timedelta(days=3650))
        coupon_value = 4.0 if coupon is None else coupon
        if cpn is not None:
            coupon_value = cpn
        self._coupon = float(coupon_value)
        self._clean_price = float(clean_price if clean_price is not None else 100.0)
        self._ytm = float(ytm if ytm is not None else self._coupon)
        self._notional = float(notional) if notional is not None else None
        self._meta_data = {"cusip": self._cusip, "timestamp": self._as_of.isoformat(), **resolved_meta}
        self._ql_frb_id = ql_frb_id
        self._rl_frb_id = rl_frb_id

    def id(self) -> str:
        return "USTS"

    def reference_date(self) -> dt.date:
        return self._as_of

    def meta(self):
        return dict(self._meta_data)

    def issue_date(self) -> dt.date:
        return self._issue_date

    def maturity_date(self) -> dt.date:
        return self._maturity_date

    def coupon(self) -> float:
        return self._coupon

    def ytm(self) -> float:
        return self._ytm

    def clean_price(self) -> float:
        return self._clean_price

    def dirty_price(self, notional=None):
        effective_notional = 100.0 if notional is None else float(notional)
        return self._clean_price * effective_notional / 100.0

    def npv(self, notional=None):
        effective_notional = 100.0 if notional is None else float(notional)
        return self._clean_price * effective_notional / 100.0

    def pv01(self, notional=None):
        effective_notional = 1.0 if notional is None else float(notional)
        return 0.01 * effective_notional

    def mod_duration(self):
        return 5.0

    def convexity(self):
        return 1.0

    def build_pricable(
        self,
        *,
        cusip: str,
        issue_date: dt.date,
        maturity_date: dt.date,
        cpn: float,
        notional: float | None = None,
        bpv: float | None = None,
    ) -> _BondInstrument:
        resolved_notional = notional
        if resolved_notional is None:
            if bpv is None:
                resolved_notional = self._notional if self._notional is not None else 100.0
            else:
                resolved_notional = float(bpv) / self.pv01(1.0)
        return _BondInstrument(
            cusip=cusip,
            issue_date=issue_date,
            maturity_date=maturity_date,
            cpn=float(cpn),
            notional=float(resolved_notional),
        )

    def notional(self, instrument: _BondInstrument) -> float:
        return float(instrument.notional)


class _MockBondMDP:
    def __init__(self, pricer_table: dict[dt.date, dict[str, _MockBondPricer]]):
        self._pricer_table = pricer_table

    def get_pricer(self, request):
        ts = request.get("timestamp")
        if isinstance(ts, dt.datetime):
            ts = ts.date()
        return dict(self._pricer_table[ts])


@dataclass(frozen=True)
class _FakeSwap:
    tenor: str
    notional: float
    fixed_rate: float = 0.0

    def with_notional(self, notional: float) -> "_FakeSwap":
        return _FakeSwap(tenor=self.tenor, notional=notional, fixed_rate=self.fixed_rate)


class _FakeCurve:
    def __init__(self, as_of_date: dt.date):
        self.as_of_date = as_of_date
        self.day_index = as_of_date.day

    def id(self) -> str:
        return "FAKE-CURVE"

    def reference_date(self) -> dt.date:
        return self.as_of_date

    def build_irswap(
        self,
        fwd=None,
        tenor=None,
        effective_date=None,
        maturity_date=None,
        fixed_rate=-0.0,
        notional=None,
        bpv=None,
    ) -> _FakeSwap:
        tenor_label = tenor or "1Y"
        tenor_years = float(str(tenor_label).rstrip("Y"))
        if notional is None and bpv is not None:
            notional = bpv / max(tenor_years * 1e-4, 1e-12)
        if notional is None:
            notional = 1_000_000.0
        return _FakeSwap(tenor=tenor_label, notional=float(notional), fixed_rate=float(fixed_rate or 0.0))

    def fair_rate(self, instrument: _FakeSwap) -> float:
        tenor_years = float(str(instrument.tenor).rstrip("Y"))
        return 0.02 + self.day_index * 0.0001 + tenor_years * 0.0002

    def npv(self, instrument: _FakeSwap) -> float:
        return instrument.notional * self.fair_rate(instrument)

    def pv01(self, instrument: _FakeSwap) -> float:
        tenor_years = float(str(instrument.tenor).rstrip("Y"))
        return instrument.notional * tenor_years * 1e-4

    def resolve_pricable(self, pricable: _FakeSwap, risk_weight: float = 1.0) -> _FakeSwap:
        return pricable.with_notional(pricable.notional * risk_weight)


class _FakeSwapMDP:
    def get_pricer(self, request):
        ts = request["timestamp"]
        if isinstance(ts, dt.datetime):
            ts = ts.date()
        return _FakeCurve(ts)


def _weight_frame(dates: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame({"belly": np.ones(len(dates), dtype=float)}, index=dates)


def _fit_frame(dates: pd.DatetimeIndex, value: float = 0.95) -> pd.Series:
    return pd.Series(value, index=dates)


def _residual_stats_frame(dates: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame({"mean": 0.0, "std": 1.0}, index=dates)


def _entry_snapshots(dates: pd.DatetimeIndex) -> dict[pd.Timestamp, object]:
    return {dates[0]: {"kind": "flat"}}


def _frozen_residual_getter(residuals: dict[str, pd.Series]):
    return lambda fid, date_key, snapshot: float(residuals[fid].loc[pd.Timestamp(date_key)])


def test_query_frb_economic_exit_triggers_before_mean_reversion():
    dates = pd.bdate_range("2025-06-16", periods=3)
    residuals = {"F/B": pd.Series([0.0005, 0.00004, 0.00004], index=dates)}
    zscores = {"F/B": pd.Series([2.0, 0.1, 0.1], index=dates)}
    fit_quality = {"F/B": _fit_frame(dates)}
    weights = {"F/B": _weight_frame(dates)}
    residual_stats = {"F/B": _residual_stats_frame(dates)}
    regime = pd.Series("green", index=dates)
    mdp = _MockBondMDP(
        {
            dates[0].date(): {
                "F": _MockBondPricer("F", as_of=dates[0].date(), clean_price=110.0),
                "B": _MockBondPricer("B", as_of=dates[0].date(), clean_price=95.0),
            },
            dates[1].date(): {
                "F": _MockBondPricer("F", as_of=dates[1].date(), clean_price=110.0),
                "B": _MockBondPricer("B", as_of=dates[1].date(), clean_price=95.0),
            },
            dates[2].date(): {
                "F": _MockBondPricer("F", as_of=dates[2].date(), clean_price=110.0),
                "B": _MockBondPricer("B", as_of=dates[2].date(), clean_price=95.0),
            },
        }
    )

    def _query_factory(fid: str, w: np.ndarray, direction: int):
        return FixedRateBondQuery(
            cusip=fid,
            value=FixedRateBondValue.NPV,
            structure_kwargs={"bpv": 100_000.0 * float(direction)},
            meta={
                "financing": {
                    "mode": "gc_plus_specialness",
                    "gc_rate": 0.05,
                    "leg_specialness_bps": {"front": 0.0, "back": 0.0},
                    "day_count": "ACT/360",
                    "haircut": 0.0,
                }
            },
        )

    result = run_query_rv_backtest(
        residuals=residuals,
        zscores=zscores,
        fit_quality=fit_quality,
        weights=weights,
        fly_categories={"F/B": "frb_curve"},
        entry_snapshots={"F/B": _entry_snapshots(dates)},
        residual_stats=residual_stats,
        regime=regime,
        mdp=mdp,
        query_factory=_query_factory,
        frozen_residual_getter=_frozen_residual_getter(residuals),
        config=RVBacktestConfig(
            trade_belly_bpv=100_000.0,
            entry_min_fit=0.5,
            entry_min_residual_bp=1.0,
            entry_min_zscore=0.5,
            round_trip_cost_bp=0.5,
            min_profit_to_cost_ratio=0.0,
            exit_mean_reversion=False,
            exit_stop_loss_sd=999.0,
            exit_max_holding_days=10,
            exit_carry_adjusted=True,
        ),
        show_progress=False,
    )

    assert len(result.trades) == 1
    assert result.trades.iloc[0]["exit_reason"] == "economic_exit"
    assert pd.Timestamp(result.trades.iloc[0]["exit_date"]).normalize() == dates[1]


def test_query_frb_positive_signed_carry_keeps_trade_open():
    dates = pd.bdate_range("2025-06-16", periods=3)
    residuals = {"F/B": pd.Series([-0.0005, -0.00002, -0.00002], index=dates)}
    zscores = {"F/B": pd.Series([-2.0, -0.1, -0.1], index=dates)}
    fit_quality = {"F/B": _fit_frame(dates)}
    weights = {"F/B": _weight_frame(dates)}
    residual_stats = {"F/B": _residual_stats_frame(dates)}
    regime = pd.Series("green", index=dates)
    carry_roll = {"F/B": pd.Series([1.0, 1.0, 1.0], index=dates)}
    mdp = _MockBondMDP(
        {
            dates[0].date(): {
                "F": _MockBondPricer("F", as_of=dates[0].date(), clean_price=110.0),
                "B": _MockBondPricer("B", as_of=dates[0].date(), clean_price=95.0),
            },
            dates[1].date(): {
                "F": _MockBondPricer("F", as_of=dates[1].date(), clean_price=110.0),
                "B": _MockBondPricer("B", as_of=dates[1].date(), clean_price=95.0),
            },
            dates[2].date(): {
                "F": _MockBondPricer("F", as_of=dates[2].date(), clean_price=110.0),
                "B": _MockBondPricer("B", as_of=dates[2].date(), clean_price=95.0),
            },
        }
    )

    def _query_factory(fid: str, w: np.ndarray, direction: int):
        return FixedRateBondQuery(
            cusip=fid,
            value=FixedRateBondValue.NPV,
            structure_kwargs={"bpv": 100_000.0 * float(direction)},
            meta={
                "financing": {
                    "mode": "gc_plus_specialness",
                    "gc_rate": 0.05,
                    "leg_specialness_bps": {"front": 0.0, "back": 0.0},
                    "day_count": "ACT/360",
                    "haircut": 0.0,
                }
            },
        )

    result = run_query_rv_backtest(
        residuals=residuals,
        zscores=zscores,
        fit_quality=fit_quality,
        weights=weights,
        fly_categories={"F/B": "frb_curve"},
        entry_snapshots={"F/B": _entry_snapshots(dates)},
        residual_stats=residual_stats,
        regime=regime,
        mdp=mdp,
        query_factory=_query_factory,
        frozen_residual_getter=_frozen_residual_getter(residuals),
        config=RVBacktestConfig(
            trade_belly_bpv=100_000.0,
            entry_min_fit=0.5,
            entry_min_residual_bp=1.0,
            entry_min_zscore=0.5,
            round_trip_cost_bp=0.5,
            min_profit_to_cost_ratio=0.0,
            exit_mean_reversion=False,
            exit_stop_loss_sd=999.0,
            exit_max_holding_days=10,
            exit_carry_adjusted=True,
        ),
        carry_roll=carry_roll,
        show_progress=False,
    )

    assert len(result.trades) == 1
    assert result.trades.iloc[0]["exit_reason"] == "end_of_backtest"


def test_non_frb_query_trade_keeps_old_exit_behavior_without_financing():
    dates = pd.bdate_range("2025-06-16", periods=3)
    residuals = {"2Y/5Y/10Y": pd.Series([0.0005, 0.00004, 0.00004], index=dates)}
    zscores = {"2Y/5Y/10Y": pd.Series([2.0, 0.1, 0.1], index=dates)}
    fit_quality = {"2Y/5Y/10Y": _fit_frame(dates)}
    weights = {"2Y/5Y/10Y": _weight_frame(dates)}
    residual_stats = {"2Y/5Y/10Y": _residual_stats_frame(dates)}
    regime = pd.Series("green", index=dates)

    def _query_factory(fid: str, w: np.ndarray, direction: int):
        return IRSwapQuery(
            structure=IRSwapStructure.FLY,
            value=IRSwapValue.NPV,
            curve="USD-SOFR-1D",
            structure_kwargs={
                "front_tenor": "2Y",
                "belly_tenor": "5Y",
                "back_tenor": "10Y",
                "bpv": 1_000.0 * float(direction),
                "risk_weights": [-0.9, 1.0, -0.46],
            },
        )

    result = run_query_rv_backtest(
        residuals=residuals,
        zscores=zscores,
        fit_quality=fit_quality,
        weights=weights,
        fly_categories={"2Y/5Y/10Y": "irs_curve"},
        entry_snapshots={"2Y/5Y/10Y": _entry_snapshots(dates)},
        residual_stats=residual_stats,
        regime=regime,
        mdp=_FakeSwapMDP(),
        query_factory=_query_factory,
        frozen_residual_getter=_frozen_residual_getter(residuals),
        config=RVBacktestConfig(
            trade_belly_bpv=100_000.0,
            entry_min_fit=0.5,
            entry_min_residual_bp=1.0,
            entry_min_zscore=0.5,
            round_trip_cost_bp=0.5,
            min_profit_to_cost_ratio=0.0,
            exit_mean_reversion=False,
            exit_stop_loss_sd=999.0,
            exit_max_holding_days=10,
            exit_carry_adjusted=True,
        ),
        show_progress=False,
    )

    assert len(result.trades) == 1
    assert result.trades.iloc[0]["exit_reason"] == "end_of_backtest"

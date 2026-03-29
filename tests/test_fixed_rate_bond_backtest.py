import datetime as dt
from dataclasses import dataclass

import pandas as pd
import pytest
import QuantLib as ql

from BT.data_handler import TimeGrid
from BT.misc import _last_business_day_of_month, _month_iter, _n_business_days_before, _nth_business_day_of_month
from BT.query_actions import AddQueryAction, UnwindPositionsAction
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.triggers import DateTrigger, DateTriggerRequirements
from Query.Base.query_resolution import resolve_query
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue


@dataclass
class _BondInstrument:
    cusip: str
    issue_date: dt.date
    maturity_date: dt.date
    cpn: float
    notional: float


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
        default_coupon: float = 4.0,
        pv01_per_unit: float = 0.01,
        cashflow_per_100: dict[dt.date, float] | None = None,
    ):
        resolved_meta = dict(meta_data or {})
        self._cusip = str(cusip or resolved_meta.get("cusip") or "MOCK")
        self._as_of = reference_date or as_of or dt.date.today()
        self._issue_date = issue_date or (self._as_of - dt.timedelta(days=365))
        self._maturity_date = maturity_date or (self._as_of + dt.timedelta(days=3650))
        self._clean_price = float(clean_price if clean_price is not None else 100.0)
        coupon_value = default_coupon if coupon is None else coupon
        if cpn is not None:
            coupon_value = cpn
        self._coupon = float(coupon_value)
        self._ytm = float(ytm if ytm is not None else self._coupon)
        self._notional = float(notional) if notional is not None else None
        self._pv01_per_unit = float(pv01_per_unit)
        self._cashflow_per_100 = dict(cashflow_per_100 or {})
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
        return self._pv01_per_unit * effective_notional

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

    def cashflows_between(
        self,
        instrument: _BondInstrument,
        *,
        start: dt.datetime,
        end: dt.datetime,
        include_coupons: bool = True,
        include_redemption: bool = True,
        include_end: bool = True,
    ) -> float:
        total = 0.0
        for pay_date, amount_per_100 in self._cashflow_per_100.items():
            pay_dt = dt.datetime.combine(pay_date, dt.time())
            if pay_dt <= start:
                continue
            if include_end:
                if pay_dt > end:
                    continue
            elif pay_dt >= end:
                continue
            total += float(amount_per_100) * float(instrument.notional) / 100.0
        return float(total)


class _MockBondMDP:
    def __init__(self, pricer_table: dict[dt.date, dict[str, _MockBondPricer]]):
        self._pricer_table = pricer_table

    def get_pricer(self, request):
        ts = request.get("timestamp")
        if isinstance(ts, dt.datetime):
            ts = ts.date()
        if isinstance(ts, str):
            raise TypeError(f"Unexpected timestamp literal for _MockBondMDP: {ts!r}")
        return dict(self._pricer_table[ts])


def _patch_reference_data(monkeypatch) -> None:
    ref_df = pd.DataFrame(
        [
            {
                "record_date": "2025-01-27",
                "cusip": "OLD30A",
                "oi": "30-Year",
                "issue_date": dt.date(2024, 5, 15),
                "maturity_date": dt.date(2054, 5, 15),
            },
            {
                "record_date": "2025-01-27",
                "cusip": "OLD30B",
                "oi": "30-Year",
                "issue_date": dt.date(2024, 11, 15),
                "maturity_date": dt.date(2054, 11, 15),
            },
            {
                "record_date": "2025-01-27",
                "cusip": "OLD30C",
                "oi": "30-Year",
                "issue_date": dt.date(2025, 2, 15),
                "maturity_date": dt.date(2055, 2, 15),
            },
            {
                "record_date": "2025-01-27",
                "cusip": "CT30A",
                "oi": "30-Year",
                "issue_date": dt.date(2025, 5, 15),
                "maturity_date": dt.date(2055, 5, 15),
            },
        ]
    )
    monkeypatch.setattr(
        "MDP.FixedRateBonds.reference_data_cache.ust_reference_data.update_reference_data",
        lambda source="fiscaldata", force_refresh=False: ref_df.copy(),
    )


def _two_day_grid(start: dt.date | None = None, end: dt.date | None = None) -> TimeGrid:
    d1 = start or dt.date(2025, 1, 27)
    d2 = end or dt.date(2025, 1, 28)
    return TimeGrid(
        [
            dt.datetime.combine(d1, dt.time()),
            dt.datetime.combine(d2, dt.time()),
        ]
    )


def test_month_end_dates_match_intended_business_day_rule() -> None:
    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    start = dt.date(2025, 1, 1)
    end = dt.date(2025, 3, 31)

    cycles = []
    for y, m in _month_iter(start, end):
        eom_bd = _last_business_day_of_month(cal, y, m)
        entry = _n_business_days_before(cal, eom_bd, 4)
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        exit_ = _nth_business_day_of_month(cal, ny, nm, 1)
        if entry < start or exit_ > end:
            continue
        cycles.append((entry, exit_))

    assert cycles == [
        (dt.date(2025, 1, 27), dt.date(2025, 2, 3)),
        (dt.date(2025, 2, 24), dt.date(2025, 3, 3)),
    ]


def test_negative_bpv_ooo30_ct30_resolves_long_front_short_back(monkeypatch) -> None:
    _patch_reference_data(monkeypatch)
    as_of = dt.datetime(2025, 6, 16)
    pricers = {
        "OLD30A": _MockBondPricer("OLD30A", as_of=as_of.date(), clean_price=110.0),
        "OLD30B": _MockBondPricer("OLD30B", as_of=as_of.date(), clean_price=108.0),
        "OLD30C": _MockBondPricer("OLD30C", as_of=as_of.date(), clean_price=106.0),
        "CT30A": _MockBondPricer("CT30A", as_of=as_of.date(), clean_price=102.0),
    }
    query = FixedRateBondQuery(
        cusip="ooo30/CT30",
        value=FixedRateBondValue.NPV,
        structure_kwargs={"bpv": -100_000},
    )

    resolved = resolve_query(query, timestamp=as_of, pricer_or_curve=pricers)
    package, weights = resolved.resolve_package(pricer_or_curve=pricers)

    assert resolved.cusip == "OLD30A/CT30A"
    assert weights == [1.0, -1.0]
    assert package[0].cusip == "OLD30A"
    assert package[0].notional > 0
    assert package[1].cusip == "CT30A"
    assert package[1].notional < 0


def test_curve_financing_accrues_per_leg_even_when_weights_net_to_zero(monkeypatch) -> None:
    _patch_reference_data(monkeypatch)
    d1 = dt.date(2025, 6, 16)
    d2 = dt.date(2025, 6, 17)
    mdp = _MockBondMDP(
        {
            d1: {
                "OLD30A": _MockBondPricer("OLD30A", as_of=d1, clean_price=110.0),
                "OLD30B": _MockBondPricer("OLD30B", as_of=d1, clean_price=108.0),
                "OLD30C": _MockBondPricer("OLD30C", as_of=d1, clean_price=106.0),
                "CT30A": _MockBondPricer("CT30A", as_of=d1, clean_price=95.0),
            },
            d2: {
                "OLD30A": _MockBondPricer("OLD30A", as_of=d2, clean_price=110.0),
                "OLD30B": _MockBondPricer("OLD30B", as_of=d2, clean_price=108.0),
                "OLD30C": _MockBondPricer("OLD30C", as_of=d2, clean_price=106.0),
                "CT30A": _MockBondPricer("CT30A", as_of=d2, clean_price=95.0),
            },
        }
    )
    query = FixedRateBondQuery(
        cusip="ooo30/CT30",
        value=FixedRateBondValue.NPV,
        structure_kwargs={"bpv": -100_000},
        meta={
            "financing": {
                "mode": "gc_plus_specialness",
                "gc_rate": 0.05,
                "leg_specialness_bps": {"front": 0.0, "back": 200.0},
                "day_count": "ACT/360",
                "haircut": 0.0,
            }
        },
        tags=("curve-financing",),
    )

    enter = DateTrigger(
        DateTriggerRequirements(dates=[d1]),
        actions=[AddQueryAction(query=query)],
    )
    bt = QueryDrivenBacktest(
        time_grid=_two_day_grid(d1, d2),
        mdp=mdp,
        strategy=QueryStrategy(name="FRB curve financing", triggers=[enter]),
        show_progress=False,
    )

    bt.run()

    position = list(bt.portfolio.iter_positions())[0]
    assert sum(position.weights) == 0.0
    assert [leg["role"] for leg in position.meta["financing_legs"]] == ["front", "back"]

    initial_front_value = 110.0 * abs(position.package[0].notional) / 100.0
    initial_back_value = 95.0 * abs(position.package[1].notional) / 100.0
    expected = (
        -(initial_front_value * 0.05 / 360.0)
        + (initial_back_value * 0.03 / 360.0)
    )

    first_step = list(_two_day_grid(d1, d2))[0]
    assert bt.realized_pnl_history[first_step] == pytest.approx(expected)
    assert bt.frb_component_histories["financing_total"][first_step] == pytest.approx(expected)


def test_scalar_and_dated_gc_rate_accrue_identically() -> None:
    d1 = dt.date(2025, 6, 16)
    d2 = dt.date(2025, 6, 17)
    pricer_table = {
        d1: {
            "F": _MockBondPricer("F", as_of=d1, clean_price=110.0),
            "B": _MockBondPricer("B", as_of=d1, clean_price=95.0),
        },
        d2: {
            "F": _MockBondPricer("F", as_of=d2, clean_price=110.0),
            "B": _MockBondPricer("B", as_of=d2, clean_price=95.0),
        },
    }
    financing_base = {
        "mode": "gc_plus_specialness",
        "leg_specialness_bps": {"front": 0.0, "back": 200.0},
        "day_count": "ACT/360",
        "haircut": 0.0,
    }

    def _run_backtest(gc_rate) -> QueryDrivenBacktest:
        query = FixedRateBondQuery(
            cusip="F/B",
            value=FixedRateBondValue.NPV,
            structure_kwargs={"bpv": -100_000},
            meta={"financing": financing_base | {"gc_rate": gc_rate}},
            tags=("curve-financing",),
        )
        enter = DateTrigger(
            DateTriggerRequirements(dates=[d1]),
            actions=[AddQueryAction(query=query)],
        )
        bt = QueryDrivenBacktest(
            time_grid=_two_day_grid(d1, d2),
            mdp=_MockBondMDP(pricer_table),
            strategy=QueryStrategy(name="FRB dated financing parity", triggers=[enter]),
            show_progress=False,
        )
        bt.run()
        return bt

    scalar_bt = _run_backtest(0.05)
    dated_bt = _run_backtest(pd.Series([0.05, 0.05], index=[d1, d2]))
    first_step = list(_two_day_grid(d1, d2))[0]

    assert dated_bt.realized_pnl_history[first_step] == pytest.approx(scalar_bt.realized_pnl_history[first_step])
    assert dated_bt.frb_component_histories["financing_total"][first_step] == pytest.approx(
        scalar_bt.frb_component_histories["financing_total"][first_step]
    )


def test_coupon_financing_and_unwind_fee_realize_once_through_unwind() -> None:
    d1 = dt.date(2025, 6, 16)
    d2 = dt.date(2025, 6, 17)
    mdp = _MockBondMDP(
        {
            d1: {
                "BOND1": _MockBondPricer(
                    "BOND1",
                    as_of=d1,
                    clean_price=100.0,
                    cashflow_per_100={d2: 1.5},
                )
            },
            d2: {
                "BOND1": _MockBondPricer(
                    "BOND1",
                    as_of=d2,
                    clean_price=100.0,
                    cashflow_per_100={d2: 1.5},
                )
            },
        }
    )
    query = FixedRateBondQuery(
        cusip="BOND1",
        value=FixedRateBondValue.NPV,
        structure_kwargs={"notional": 1_000_000},
        meta={
            "financing": {
                "mode": "gc_plus_specialness",
                "gc_rate": 0.05,
                "leg_specialness_bps": {"outright": 0.0},
                "day_count": "ACT/360",
                "haircut": 0.0,
            }
        },
        tags=("outright-financing",),
    )
    dates = list(_two_day_grid(d1, d2))
    unwind_fee = 250.0
    strategy = QueryStrategy(
        name="FRB coupon financing unwind",
        triggers=[
            DateTrigger(DateTriggerRequirements(dates=[d1]), actions=[AddQueryAction(query=query)]),
            DateTrigger(
                DateTriggerRequirements(dates=[d2]),
                actions=[UnwindPositionsAction(match_tag="outright-financing", fee=unwind_fee)],
            ),
        ],
    )
    bt = QueryDrivenBacktest(time_grid=TimeGrid(dates), mdp=mdp, strategy=strategy, show_progress=False)

    bt.run()

    expected_coupon = 1.5 * 1_000_000 / 100.0
    expected_financing = -(1_000_000 * 0.05 / 360.0)
    expected_total = expected_coupon + expected_financing - unwind_fee

    assert bt.realized_pnl == pytest.approx(expected_total)
    assert bt.frb_component_histories["bond_realized"][dates[0]] == pytest.approx(expected_coupon)
    assert bt.frb_component_histories["financing_realized"][dates[0]] == pytest.approx(expected_financing)
    assert bt.realized_pnl_history[dates[1]] == pytest.approx(expected_total)


def test_no_financing_config_preserves_unfinanced_behavior() -> None:
    d1 = dt.date(2025, 6, 16)
    d2 = dt.date(2025, 6, 17)
    mdp = _MockBondMDP(
        {
            d1: {"BOND2": _MockBondPricer("BOND2", as_of=d1, clean_price=100.0)},
            d2: {"BOND2": _MockBondPricer("BOND2", as_of=d2, clean_price=100.0)},
        }
    )
    query = FixedRateBondQuery(
        cusip="BOND2",
        value=FixedRateBondValue.NPV,
        structure_kwargs={"notional": 1_000_000},
        tags=("plain-outright",),
    )
    dates = list(_two_day_grid(d1, d2))
    strategy = QueryStrategy(
        name="FRB no financing",
        triggers=[
            DateTrigger(DateTriggerRequirements(dates=[d1]), actions=[AddQueryAction(query=query)]),
            DateTrigger(DateTriggerRequirements(dates=[d2]), actions=[UnwindPositionsAction(match_tag="plain-outright")]),
        ],
    )
    bt = QueryDrivenBacktest(time_grid=TimeGrid(dates), mdp=mdp, strategy=strategy, show_progress=False)

    bt.run()

    assert bt.realized_pnl == pytest.approx(0.0)
    assert bt.mtm_history[dates[0]] == pytest.approx(0.0)
    assert "financing_total" not in getattr(bt, "frb_component_histories", {}) or bt.frb_component_histories["financing_total"].get(dates[0], 0.0) == pytest.approx(0.0)

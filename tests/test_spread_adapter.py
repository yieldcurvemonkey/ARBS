import pytest
import datetime
from dataclasses import dataclass
from tests.conftest import MockPricer
from MDP.Spreads.SpreadPricer import SpreadPricer


def _make_spread_pricer(rate_a=0.04, rate_b=0.05):
    pa = MockPricer("USD-SOFR-1D", datetime.date(2026, 3, 15), base_rate=rate_a)
    pb = MockPricer("USD-FEDFUNDS", datetime.date(2026, 3, 15), base_rate=rate_b)
    return SpreadPricer(pricer_a=pa, pricer_b=pb, meta_data={"source": "TEST"})


@dataclass
class _CapturedSwap:
    fwd: str | None
    tenor: str | None
    effective_date: datetime.date | None
    maturity_date: datetime.date | None
    fixed_rate: float | None
    notional: float | None
    bpv: float | None


class _ForwardCapturePricer:
    def __init__(self, curve_name: str, as_of_date: datetime.date):
        self.curve_name = curve_name
        self.as_of_date = as_of_date
        self.calls: list[_CapturedSwap] = []

    def id(self) -> str:
        return self.curve_name

    def reference_date(self) -> datetime.date:
        return self.as_of_date

    def calendar_advance(self, ref_date: datetime.date, tenor: str) -> datetime.date:
        _ = tenor
        return ref_date

    def build_irswap(
        self,
        fwd: str | None = None,
        tenor: str | None = None,
        effective_date: datetime.date | None = None,
        maturity_date: datetime.date | None = None,
        fixed_rate: float | None = None,
        notional: float | None = None,
        bpv: float | None = None,
    ) -> _CapturedSwap:
        built = _CapturedSwap(
            fwd=fwd,
            tenor=tenor,
            effective_date=effective_date,
            maturity_date=maturity_date,
            fixed_rate=fixed_rate,
            notional=notional,
            bpv=bpv,
        )
        self.calls.append(built)
        return built

    def fair_rate(self, instrument: _CapturedSwap) -> float:
        _ = instrument
        return 0.04

    def pv01(self, instrument: _CapturedSwap) -> float:
        _ = instrument
        return 100.0

    def npv(self, instrument: _CapturedSwap) -> float:
        _ = instrument
        return 0.0


class TestSpreadAdapter:
    def test_adapter_registered(self):
        from Query.Base.product_adapter import get_adapter
        import Query.Spreads.adapter  # noqa: F401
        adapter_cls = get_adapter("IRSPREAD")
        assert adapter_cls is not None

    def test_build_structure_map_outright(self):
        from Query.Base.product_adapter import get_adapter
        import Query.Spreads.adapter  # noqa: F401
        from Query.Spreads.SpreadStructure import SpreadStructure

        sp = _make_spread_pricer()
        adapter = get_adapter("IRSPREAD")()
        struct_map = adapter.build_structure_map(pricer_or_curve=sp)
        package, weights = struct_map.apply(SpreadStructure.OUTRIGHT, tenor="5Y")
        assert len(package) == 1
        assert len(weights) == 1

    def test_build_value_map_spread_bps(self):
        from Query.Base.product_adapter import get_adapter
        import Query.Spreads.adapter  # noqa: F401
        from Query.Spreads.SpreadStructure import SpreadStructure
        from Query.Spreads.SpreadValue import SpreadValue

        sp = _make_spread_pricer()
        adapter = get_adapter("IRSPREAD")()
        struct_map = adapter.build_structure_map(pricer_or_curve=sp)
        package, weights = struct_map.apply(SpreadStructure.OUTRIGHT, tenor="5Y")

        val_map = adapter.build_value_map(pricer_or_curve=sp, package=package, risk_weights=weights)
        spread_bps = val_map.apply(SpreadValue.SPREAD_BPS)
        assert isinstance(spread_bps, float)

    def test_leg_a_rate(self):
        from Query.Base.product_adapter import get_adapter
        import Query.Spreads.adapter  # noqa: F401
        from Query.Spreads.SpreadStructure import SpreadStructure
        from Query.Spreads.SpreadValue import SpreadValue

        sp = _make_spread_pricer()
        adapter = get_adapter("IRSPREAD")()
        struct_map = adapter.build_structure_map(pricer_or_curve=sp)
        package, weights = struct_map.apply(SpreadStructure.OUTRIGHT, tenor="5Y")
        val_map = adapter.build_value_map(pricer_or_curve=sp, package=package, risk_weights=weights)

        leg_a = val_map.apply(SpreadValue.LEG_A_RATE)
        assert isinstance(leg_a, float)
        assert leg_a > 0

    def test_curve_forward_tenor_shorthand_resolves_into_forward_starting_legs(self):
        from Query.Base.product_adapter import get_adapter
        import Query.Spreads.adapter  # noqa: F401
        from Query.Spreads.SpreadStructure import SpreadStructure

        pricer_a = _ForwardCapturePricer("USD-SOFR-1D-Q12STIRT", datetime.date(2026, 3, 15))
        pricer_b = _ForwardCapturePricer("USD-OIS-Q12xM12STIRT-SERFFX", datetime.date(2026, 3, 15))
        spread_pricer = SpreadPricer(pricer_a=pricer_a, pricer_b=pricer_b, meta_data={"source": "TEST"})

        adapter = get_adapter("IRBASIS")()
        struct_map = adapter.build_structure_map(pricer_or_curve=spread_pricer)
        package, weights = struct_map.apply(SpreadStructure.CURVE, front_tenor="1Y1Y", back_tenor="2Y1Y", bpv=10_000)

        assert len(package) == 2
        assert weights == [-1.0, 1.0]

        assert len(pricer_a.calls) == 2
        assert len(pricer_b.calls) == 2

        assert pricer_a.calls[0].fwd == "1Y"
        assert pricer_a.calls[0].tenor == "1Y"
        assert pricer_a.calls[0].bpv == 10_000
        assert pricer_a.calls[1].fwd == "2Y"
        assert pricer_a.calls[1].tenor == "1Y"

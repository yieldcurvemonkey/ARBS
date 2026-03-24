import datetime as dt
from dataclasses import dataclass

from rateslib.scheduling import get_imm, next_imm

from Query.IRSwaps.IRSwapQuery import IRSwapQuery


def _nth_imm_after(ref_date: dt.date, n: int) -> dt.date:
    imm = dt.datetime(ref_date.year, ref_date.month, ref_date.day) + dt.timedelta(days=1)
    for _ in range(n):
        imm = next_imm(imm)
    return imm.date()


@dataclass
class _BuiltSwap:
    effective_date: dt.date | dt.datetime
    maturity_date: dt.date | dt.datetime
    fixed_rate: float
    notional: float | None


class _CurveStub:
    def __init__(self, ref_date: dt.date):
        self._ref_date = ref_date

    def reference_date(self) -> dt.date:
        return self._ref_date

    def build_irswap(
        self,
        fwd=None,
        tenor=None,
        effective_date=None,
        maturity_date=None,
        fixed_rate=-0.0,
        notional=None,
        bpv=None,
    ) -> _BuiltSwap:
        _ = fwd, tenor, bpv
        return _BuiltSwap(
            effective_date=effective_date,
            maturity_date=maturity_date,
            fixed_rate=fixed_rate,
            notional=notional,
        )


def test_numeric_imm_pair_resolves_against_curve_reference_date():
    curve = _CurveStub(dt.date(2026, 3, 23))
    query = IRSwapQuery(curve="USD-SOFR-1D", tenor="IMM_4xIMM_5")

    package, weights = query.resolve_package(pricer_or_curve=curve)

    assert weights == [1]
    assert len(package) == 1
    assert package[0].effective_date == _nth_imm_after(curve.reference_date(), 4)
    assert package[0].maturity_date == _nth_imm_after(curve.reference_date(), 5)


def test_explicit_imm_code_pair_resolves_to_consecutive_imm_dates():
    curve = _CurveStub(dt.date(2026, 1, 2))
    query = IRSwapQuery(curve="USD-SOFR-1D", tenor="IMM_H26xIMM_M26")

    package, _ = query.resolve_package(pricer_or_curve=curve)

    assert len(package) == 1
    assert package[0].effective_date == get_imm(code="H26")
    assert package[0].maturity_date == get_imm(code="M26")

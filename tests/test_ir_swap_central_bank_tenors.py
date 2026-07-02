import datetime as dt
from dataclasses import dataclass

import pandas as pd
import pytest

from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure


@dataclass
class _BuiltSwap:
    effective_date: dt.date | None
    maturity_date: dt.date | None
    tenor: str | None
    notional: float | None
    bpv: float | None


class _CurveStub:
    def __init__(self, curve_id: str, ref_date: dt.date):
        self._curve_id = curve_id
        self._ref_date = ref_date

    def id(self) -> str:
        return self._curve_id

    def reference_date(self) -> dt.date:
        return self._ref_date

    def build_irswap(
        self,
        *,
        fwd=None,
        tenor=None,
        effective_date=None,
        maturity_date=None,
        fixed_rate=None,
        notional=None,
        bpv=None,
    ):
        return _BuiltSwap(
            effective_date=effective_date,
            maturity_date=maturity_date,
            tenor=tenor,
            notional=notional,
            bpv=bpv,
        )


def _resolve_outright(curve_id: str, ref_date: dt.date, tenor: str) -> _BuiltSwap:
    query = IRSwapQuery(
        structure=IRSwapStructure.OUTRIGHT,
        tenor=tenor,
        curve=curve_id,
        structure_kwargs={"bpv": 100_000},
    )
    package, _ = query.resolve_package(pricer_or_curve=_CurveStub(curve_id, ref_date))
    assert len(package) == 1
    return package[0]


def test_explicit_fomc_tenor_resolves_to_meeting_window():
    swap = _resolve_outright("USD-SOFR-1D", dt.date(2026, 3, 13), "fomc_dec26")

    assert swap.tenor is None
    assert swap.effective_date == dt.date(2026, 12, 9)
    assert swap.maturity_date == dt.date(2027, 1, 27)


def test_ranked_fomc_tenor_resolves_from_curve_reference_date():
    swap = _resolve_outright("USD-SOFR-1D", dt.date(2026, 3, 13), "fomc_1")

    assert swap.tenor is None
    # production ranked-tenor resolver returns pd.Timestamp; normalise for comparison
    assert pd.Timestamp(swap.effective_date) == pd.Timestamp("2026-03-18")
    assert pd.Timestamp(swap.maturity_date) == pd.Timestamp("2026-04-29")


def test_ranked_ecb_tenor_resolves_second_upcoming_meeting():
    swap = _resolve_outright("EUR-ESTR", dt.date(2026, 3, 13), "ecb_2")

    assert swap.tenor is None
    # production ranked-tenor resolver returns pd.Timestamp; normalise for comparison
    assert pd.Timestamp(swap.effective_date) == pd.Timestamp("2026-04-30")
    assert pd.Timestamp(swap.maturity_date) == pd.Timestamp("2026-06-11")


def test_explicit_central_bank_prefix_must_match_curve():
    with pytest.raises(ValueError, match="does not match curve"):
        _resolve_outright("USD-SOFR-1D", dt.date(2026, 3, 13), "ecb_dec26")


def test_unprefixed_meeting_label_works_for_usd_ois_curve():
    swap = _resolve_outright("USD-OIS", dt.date(2026, 3, 13), "dec26")

    assert swap.tenor is None
    assert swap.effective_date == dt.date(2026, 12, 9)
    assert swap.maturity_date == dt.date(2027, 1, 27)

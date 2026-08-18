"""Regression coverage for the exact slash-tenor RATE fast path."""

from __future__ import annotations

import datetime as dt

import pytest

from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue
from TB.IRSwapsTB import _build_row_for_query


class _Curve:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def id(self):
        return "USD-SOFR-1D"

    def build_irswap(self, *, fwd, tenor, **_kwargs):
        self.calls.append((fwd, tenor))
        return fwd, tenor

    @staticmethod
    def fair_rate(swap):
        return {
            ("1Y", "5Y"): 0.04,
            ("1Y", "10Y"): 0.045,
            ("1Y", "30Y"): 0.048,
        }[swap]


def test_standard_fly_rate_uses_three_par_legs_not_bpv_sizing(monkeypatch):
    raw = IRSwapQuery(
        curve="USD-SOFR-1D",
        tenor="1y5y/1y10y/1y30y",
        value=IRSwapValue.RATE,
    )
    resolved = IRSwapQuery(
        curve="USD-SOFR-1D",
        tenor=raw.tenor,
        structure=IRSwapStructure.FLY,
        value=IRSwapValue.RATE,
        structure_kwargs={
            "front_tenor": "1Yx5Y",
            "belly_tenor": "1Yx10Y",
            "back_tenor": "1Yx30Y",
            "bpv": 1.0,
        },
    )
    monkeypatch.setattr("TB.IRSwapsTB.resolve_query", lambda *_args, **_kwargs: resolved)
    curve = _Curve()

    row = _build_row_for_query(curve, raw, dt.date(2026, 8, 14), "Date")

    assert curve.calls == [("1Y", "5Y"), ("1Y", "10Y"), ("1Y", "30Y")]
    assert row[2] == pytest.approx(20.0)

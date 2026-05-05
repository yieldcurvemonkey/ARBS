"""Tests for STIRAsymmetricScreener._market_data."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest


@dataclass
class _StubSmileParams:
    forward_price: float


@dataclass
class _StubSmile:
    forward_price: float

    @property
    def params(self):
        return _StubSmileParams(forward_price=self.forward_price)


def test_leg_market_dataclass_round_trip():
    from RVUtils.STIRAsymmetricScreener._market_data import LegMarket

    lm = LegMarket(
        contract="SFRU26",
        expiry=datetime.date(2026, 9, 11),
        right="P",
        strike=96.50,
        premium_ticks=3.0,
        open_interest=1500.0,
        volume=120.0,
        bid=2.75,
        ask=3.25,
    )
    d = lm.to_dict()
    assert d["contract"] == "SFRU26"
    assert d["right"] == "P"
    assert d["strike"] == 96.50


def test_smile_fallback_walks_back_one_business_day_on_failure():
    from RVUtils.STIRAsymmetricScreener._market_data import _try_with_fallback

    state = {"calls": 0}

    def fn(d: datetime.date):
        state["calls"] += 1
        if state["calls"] == 1:
            raise RuntimeError("transient")
        return ("ok", d)

    val, eff_date, err = _try_with_fallback(
        fn, as_of=datetime.date(2026, 4, 28), max_fallback_days=3
    )
    assert val is not None
    # Either previous business day (Mon) or two days back when test starts on weekend
    assert eff_date < datetime.date(2026, 4, 28)
    assert err is None


def test_load_market_data_with_stub_dependencies():
    from RVUtils.STIRAsymmetricScreener._market_data import (
        STIRMarketData,
        load_market_data,
    )
    from RVUtils.STIRAsymmetricScreener._types import ScreenerConfig
    from RVUtils.STIRAsymmetricScreener._universe import (
        ContractEntry,
        UniverseEntry,
    )

    cfg = ScreenerConfig(
        underlyings=("SR3",),
        include_midcurves=False,
        include_serials=False,
        dte_floor=30,
        dte_ceiling=200,
    )

    def smile_loader(*, contract: str, as_of: datetime.date):
        return _StubSmile(forward_price=96.30)

    def curve_loader(*, as_of: datetime.date):
        return MagicMock(name="curve_handle")

    def fomc_schedule_loader(*, curve_name: str):
        return pd.DataFrame(
            [
                {
                    "meeting_label": "Jun26",
                    "effective_date": pd.Timestamp("2026-06-17"),
                    "maturity_date": pd.Timestamp("2026-07-29"),
                    "period_days": 42,
                }
            ]
        )

    def leg_quote_loader(*, contract, expiry, strikes, as_of):
        # Return zero-OI rows so liquidity gates can fire downstream
        out: Dict[Tuple[str, datetime.date, str, float], Any] = {}
        for s in strikes:
            for right in ("C", "P"):
                out[(contract, expiry, right, s)] = {
                    "premium_ticks": 1.5,
                    "open_interest": 1000.0,
                    "volume": 50.0,
                    "bid": 1.25,
                    "ask": 1.75,
                }
        return out

    def history_loader(*, contract, expiry, as_of, lookback_days):
        idx = pd.bdate_range(end=as_of, periods=lookback_days)
        return pd.DataFrame(
            {
                "atm_iv": np.linspace(0.05, 0.07, len(idx)),
                "rr25": np.linspace(-0.005, 0.005, len(idx)),
            },
            index=idx,
        )

    md = load_market_data(
        cfg,
        as_of=datetime.date(2026, 4, 28),
        smile_loader=smile_loader,
        curve_loader=curve_loader,
        fomc_schedule_loader=fomc_schedule_loader,
        leg_quote_loader=leg_quote_loader,
        history_loader=history_loader,
    )

    assert isinstance(md, STIRMarketData)
    assert md.as_of == datetime.date(2026, 4, 28)
    assert len(md.universe) > 0
    # Smiles attached for every entry
    for entry in md.universe:
        assert (entry.contract, entry.expiry) in md.smiles
    # FOMC schedule present
    assert isinstance(md.fomc_schedule, pd.DataFrame)
    # Per-leg market data present for every (contract, expiry, right, strike) we asked about
    assert len(md.leg_market) > 0


def test_load_market_data_records_warnings_on_smile_fail():
    from RVUtils.STIRAsymmetricScreener._market_data import load_market_data
    from RVUtils.STIRAsymmetricScreener._types import ScreenerConfig

    cfg = ScreenerConfig(
        underlyings=("SR3",),
        include_midcurves=False,
        include_serials=False,
        dte_floor=30,
        dte_ceiling=200,
    )

    def failing_loader(*, contract: str, as_of: datetime.date):
        raise RuntimeError("simulated smile failure")

    def curve_loader(*, as_of: datetime.date):
        return MagicMock(name="curve_handle")

    def fomc_schedule_loader(*, curve_name: str):
        return pd.DataFrame()

    def leg_quote_loader(*, contract, expiry, strikes, as_of):
        return {}

    def history_loader(*, contract, expiry, as_of, lookback_days):
        return pd.DataFrame()

    md = load_market_data(
        cfg,
        as_of=datetime.date(2026, 4, 28),
        smile_loader=failing_loader,
        curve_loader=curve_loader,
        fomc_schedule_loader=fomc_schedule_loader,
        leg_quote_loader=leg_quote_loader,
        history_loader=history_loader,
    )

    # Universe ends up empty because smiles all failed
    assert len(md.universe) == 0
    # And we recorded warnings
    assert len(md.warnings) > 0

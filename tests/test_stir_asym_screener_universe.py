"""Tests for STIRAsymmetricScreener._universe."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import pytest


# --- Stub smile / forward loader -----------------------------------------------


@dataclass
class _StubSmile:
    forward_price: float
    contract: str

    @property
    def params(self):
        return self


def _make_stub_loader(forward_by_contract: Dict[str, float]):
    def _loader(*, contract: str, as_of: datetime.date):
        if contract in forward_by_contract:
            return _StubSmile(forward_price=forward_by_contract[contract], contract=contract)
        raise ValueError(f"no smile stub for {contract}")
    return _loader


# --- Tests --------------------------------------------------------------------


def test_enumerate_contracts_returns_only_inside_dte_band():
    from RVUtils.STIRAsymmetricScreener._types import ScreenerConfig
    from RVUtils.STIRAsymmetricScreener._universe import enumerate_contracts

    cfg = ScreenerConfig(
        underlyings=("SR3",),
        include_midcurves=False,
        include_serials=False,
        include_weeklies=False,
        dte_floor=30,
        dte_ceiling=200,
    )
    entries = enumerate_contracts(cfg, as_of=datetime.date(2026, 4, 28))
    assert entries, "expected at least one quarterly SOFR option contract in 30-200d window"
    for e in entries:
        dte = (e.expiry - datetime.date(2026, 4, 28)).days
        assert 30 <= dte <= 200, f"{e.contract} dte={dte} outside band"


def test_enumerate_contracts_excludes_weeklies_by_default():
    from RVUtils.STIRAsymmetricScreener._types import ScreenerConfig
    from RVUtils.STIRAsymmetricScreener._universe import enumerate_contracts

    cfg = ScreenerConfig(
        underlyings=("SR3",),
        include_midcurves=True,
        include_serials=True,
        include_weeklies=False,
        dte_floor=7,
        dte_ceiling=730,
    )
    entries = enumerate_contracts(cfg, as_of=datetime.date(2026, 4, 28))
    # No "WK"-tagged entries
    for e in entries:
        assert "WK" not in e.option_root


def test_enumerate_contracts_includes_midcurves_when_enabled():
    from RVUtils.STIRAsymmetricScreener._types import ScreenerConfig
    from RVUtils.STIRAsymmetricScreener._universe import enumerate_contracts

    cfg = ScreenerConfig(
        underlyings=("SR3",),
        include_midcurves=True,
        include_serials=False,
        include_weeklies=False,
        dte_floor=7,
        dte_ceiling=400,
    )
    entries = enumerate_contracts(cfg, as_of=datetime.date(2026, 4, 28))
    midcurve_roots = {e.option_root for e in entries if e.option_root in {"0Q", "2Q", "3Q", "4Q"}}
    assert midcurve_roots, "expected at least one midcurve root when include_midcurves=True"


def test_enumerate_contracts_includes_serials_when_enabled():
    from RVUtils.STIRAsymmetricScreener._types import ScreenerConfig
    from RVUtils.STIRAsymmetricScreener._universe import enumerate_contracts

    cfg = ScreenerConfig(
        underlyings=("SR3",),
        include_midcurves=False,
        include_serials=True,
        include_weeklies=False,
        dte_floor=7,
        dte_ceiling=200,
    )
    entries = enumerate_contracts(cfg, as_of=datetime.date(2026, 4, 28))
    # Serial month codes are non-quarterly: F, G, J, K, N, Q, V, X
    NON_Q_CODES = {"F", "G", "J", "K", "N", "Q", "V", "X"}
    found_serial = False
    for e in entries:
        if e.contract[-3] in NON_Q_CODES and e.option_root == "SFR":
            found_serial = True
            break
    assert found_serial, "expected at least one serial SFR option"


def test_attach_strike_grid_uses_listed_helper():
    from RVUtils.STIRAsymmetricScreener._types import ScreenerConfig
    from RVUtils.STIRAsymmetricScreener._universe import (
        ContractEntry,
        UniverseEntry,
        attach_strike_grid,
    )

    entries = (
        ContractEntry(
            underlying="SFRU26",
            contract="SFRU26",
            option_root="SFR",
            expiry=datetime.date(2026, 9, 11),
        ),
    )
    loader = _make_stub_loader({"SFRU26": 96.30})

    universe = attach_strike_grid(entries, smile_loader=loader, as_of=datetime.date(2026, 4, 28))

    assert len(universe) == 1
    u = universe[0]
    assert isinstance(u, UniverseEntry)
    assert u.underlying == "SFRU26"
    assert u.forward_price == 96.30
    assert u.fine_step in (0.0625, 0.125)
    # ATM should be near forward, strike grid should be sorted ascending
    assert min(u.strikes) <= u.forward_price <= max(u.strikes)
    assert list(u.strikes) == sorted(u.strikes)


def test_resolve_universe_full_pipeline_with_stub_loader():
    from RVUtils.STIRAsymmetricScreener._types import ScreenerConfig
    from RVUtils.STIRAsymmetricScreener._universe import resolve_universe

    cfg = ScreenerConfig(
        underlyings=("SR3",),
        include_midcurves=False,
        include_serials=False,
        include_weeklies=False,
        dte_floor=30,
        dte_ceiling=200,
    )

    # stub: just return a flat 96.30 forward for everything
    def loader(*, contract: str, as_of: datetime.date):
        return _StubSmile(forward_price=96.30, contract=contract)

    universe = resolve_universe(cfg, as_of=datetime.date(2026, 4, 28), smile_loader=loader)
    assert universe
    for u in universe:
        assert hasattr(u, "strikes")
        assert hasattr(u, "atm_strike")


def test_underlying_root_to_smile_root_mapping():
    """Maps user-facing underlyings (SR3/SR1/ER) to actual option roots."""
    from RVUtils.STIRAsymmetricScreener._universe import (
        EUR_OPTION_ROOT,
        SR1_OPTION_ROOT,
        SR3_OPTION_ROOT,
    )

    assert SR3_OPTION_ROOT == "SFR"
    assert SR1_OPTION_ROOT == "SER"
    # Euribor uses ER prefix
    assert EUR_OPTION_ROOT == "ER"

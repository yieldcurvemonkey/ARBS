"""Regression: STIRFutureStructure FLY and BASIS builders must not NameError.

Both ``_build_fly`` and ``_build_basis`` referenced ``kwargs`` in their
leg-construction lines while their signatures swallowed extras as ``**_`` —
every call raised ``NameError: name 'kwargs' is not defined`` (found in the
2026-08 CvxSuite recon; production had routed flies through IRSwapQuery to
avoid it). The fix renames the catch-all to ``**kwargs`` so the per-leg
prefixed overrides (``front_price`` etc.) that ``_leg_kwargs`` reads keep
working, matching ``_build_curve``.

MUTATION: reverting either ``**kwargs`` back to ``**_`` makes the
corresponding test here fail with NameError.
"""
from __future__ import annotations

import pytest

from Query.STIRFutures.STIRFutureStructure import (
    STIRFutureStructure,
    STIRFutureStructureFunctionMap,
)


class _FakePricable:
    def __init__(self, key, **kw):
        self.key = key
        self.kw = kw


class _FakePricer:
    """Implements the ``build_pricable`` entry point ``_build_leg`` prefers."""

    def __init__(self, key: str):
        self._key = key

    def build_pricable(self, **kw):
        return _FakePricable(self._key, **kw)

    def pv01(self, stirf):  # unused unless constrained sizing is requested
        return 25.0


def _fmap(keys):
    return STIRFutureStructureFunctionMap(pricer={k: _FakePricer(k) for k in keys})


def test_fly_builds_three_legs_without_nameerror():
    fmap = _fmap(["SR3H26", "SR3M26", "SR3U26"])
    legs, weights = fmap._map[STIRFutureStructure.FLY](
        symbols=["SR3H26", "SR3M26", "SR3U26"]
    )
    assert [l.key for l in legs] == ["SR3H26", "SR3M26", "SR3U26"]
    assert weights == [1.0, -2.0, 1.0]


def test_fly_per_leg_prefixed_overrides_reach_the_legs():
    # The reason the catch-all must be **kwargs: _leg_kwargs reads prefixed fields.
    fmap = _fmap(["A", "B", "C"])
    legs, _ = fmap._map[STIRFutureStructure.FLY](
        symbols=["A", "B", "C"], belly_price=97.5, price=96.0
    )
    assert legs[0].kw.get("price") == 96.0
    assert legs[1].kw.get("price") == 97.5  # belly override wins over shared
    assert legs[2].kw.get("price") == 96.0


def test_basis_builds_two_legs_without_nameerror():
    fmap = _fmap(["CME", "LCH"])
    legs, weights = fmap._map[STIRFutureStructure.BASIS](
        basis_front_key="CME", basis_back_key="LCH"
    )
    assert [l.key for l in legs] == ["CME", "LCH"]
    assert weights == [1.0, -1.0]


def test_fly_wrong_symbol_count_still_raises():
    # Negative control: the fix must not have loosened validation.
    fmap = _fmap(["A", "B", "C"])
    with pytest.raises(ValueError, match="length 3"):
        fmap._map[STIRFutureStructure.FLY](symbols=["A", "B"])

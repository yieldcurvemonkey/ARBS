"""Tests for STIRAsymmetricScreener._types."""

from __future__ import annotations

import datetime

import pytest


def test_archetype_type_has_eight_members():
    from RVUtils.STIRAsymmetricScreener._types import ArchetypeType

    assert {m.value for m in ArchetypeType} == {
        "wing",
        "wide_vertical",
        "risk_reversal",
        "ratio",
        "ladder",
        "conditional_curve",
        "tree",
        "condor",
    }

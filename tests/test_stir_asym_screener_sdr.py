"""Tests for the SDR / block-trade lookup module."""

from __future__ import annotations

import datetime
from typing import List

import pytest


def _make_candidate(*, archetype, strikes=(96.50,)):
    from RVUtils.STIRAsymmetricScreener._types import (
        CandidateDef,
        OptionLeg,
    )

    legs = tuple(
        OptionLeg(
            contract="SFRU26",
            expiry=datetime.date(2026, 9, 11),
            right="P",
            strike=k,
            quantity=1,
        )
        for k in strikes
    )
    return CandidateDef.from_components(
        archetype=archetype,
        underlying="SFRU26",
        expiry=datetime.date(2026, 9, 11),
        legs=legs,
    )


def test_default_loader_returns_empty_list():
    from RVUtils.STIRAsymmetricScreener._sdr import (
        lookup_recent_block_trades_default,
    )
    from RVUtils.STIRAsymmetricScreener._types import ArchetypeType

    trades = lookup_recent_block_trades_default(
        underlying="SFRU26",
        expiry=datetime.date(2026, 9, 11),
        archetype=ArchetypeType.WING,
        as_of=datetime.date(2026, 4, 28),
    )
    assert trades == []


def test_is_sdr_confirmed_false_when_no_block_trades():
    from RVUtils.STIRAsymmetricScreener._sdr import is_sdr_confirmed
    from RVUtils.STIRAsymmetricScreener._types import ArchetypeType

    cand = _make_candidate(archetype=ArchetypeType.WING)
    assert (
        is_sdr_confirmed(
            candidate=cand, as_of=datetime.date(2026, 4, 28)
        )
        is False
    )


def test_is_sdr_confirmed_true_when_proximate_block_match():
    from RVUtils.STIRAsymmetricScreener._sdr import (
        BlockTrade,
        is_sdr_confirmed,
    )
    from RVUtils.STIRAsymmetricScreener._types import ArchetypeType

    cand = _make_candidate(archetype=ArchetypeType.WING, strikes=(96.50,))

    def stub_loader(**_kwargs):
        return [
            BlockTrade(
                trade_date=datetime.date(2026, 4, 25),
                underlying="SFRU26",
                archetype=ArchetypeType.WING,
                anchor_strike=96.4375,  # within 12.5bp
                size=10000.0,
                side="buy",
            )
        ]

    assert is_sdr_confirmed(
        candidate=cand,
        as_of=datetime.date(2026, 4, 28),
        block_trade_loader=stub_loader,
    )


def test_is_sdr_confirmed_false_when_archetype_mismatches():
    from RVUtils.STIRAsymmetricScreener._sdr import (
        BlockTrade,
        is_sdr_confirmed,
    )
    from RVUtils.STIRAsymmetricScreener._types import ArchetypeType

    cand = _make_candidate(archetype=ArchetypeType.WING)

    def stub_loader(**_kwargs):
        return [
            BlockTrade(
                trade_date=datetime.date(2026, 4, 25),
                underlying="SFRU26",
                archetype=ArchetypeType.WIDE_VERTICAL,  # different family
                anchor_strike=96.50,
                size=10000.0,
                side="buy",
            )
        ]

    assert not is_sdr_confirmed(
        candidate=cand,
        as_of=datetime.date(2026, 4, 28),
        block_trade_loader=stub_loader,
    )


def test_is_sdr_confirmed_false_when_strike_too_far():
    from RVUtils.STIRAsymmetricScreener._sdr import (
        BlockTrade,
        is_sdr_confirmed,
    )
    from RVUtils.STIRAsymmetricScreener._types import ArchetypeType

    cand = _make_candidate(archetype=ArchetypeType.WING, strikes=(96.50,))

    def stub_loader(**_kwargs):
        return [
            BlockTrade(
                trade_date=datetime.date(2026, 4, 25),
                underlying="SFRU26",
                archetype=ArchetypeType.WING,
                anchor_strike=95.50,  # 100bp away
                size=10000.0,
                side="buy",
            )
        ]

    assert not is_sdr_confirmed(
        candidate=cand,
        as_of=datetime.date(2026, 4, 28),
        block_trade_loader=stub_loader,
    )

"""Tests for structure_to_query / structure_position_tag."""
import datetime

import pytest

from RVUtils.SFRConvexScreener import Leg, StructureDef, StructureType
from RVUtils.SFRConvexScreener._backtest_signals import BacktestSignal
from RVUtils.SFRConvexScreener._backtest_query import (
    structure_to_query,
    structure_position_tag,
)


def _signal(structure_def, *, flip=False):
    return BacktestSignal(
        as_of=datetime.date(2026, 4, 28),
        structure_def=structure_def,
        direction="X",
        flip=flip,
        asymmetry_ratio=1.5 if not flip else 0.5,
        composite_score=0.5,
        mean_bp=1.0,
        std_bp=10.0,
        rolldown_bp=0.5,
        carry_3m_bp=100.0,
        is_stale=False,
    )


def test_structure_to_query_outright_pay():
    sd = StructureDef(
        structure_id="SFRZ26_OUTRIGHT",
        structure_type=StructureType.OUTRIGHT,
        legs=(Leg("SFRZ26", 1.0, 96.5, 25),),
    )
    q = structure_to_query(_signal(sd), curve="USD-SOFR-1D-Q12STIRT", bpv=100_000)
    assert q.structure_kwargs["tenor"] == "IMM_Z2026xIMM_H2027"
    assert q.structure_kwargs["bpv"] == 100_000


def test_structure_to_query_outright_receive_flips_sign():
    sd = StructureDef(
        structure_id="SFRZ26_OUTRIGHT",
        structure_type=StructureType.OUTRIGHT,
        legs=(Leg("SFRZ26", 1.0, 96.5, 25),),
    )
    q = structure_to_query(_signal(sd, flip=True), curve="USD-SOFR-1D-Q12STIRT", bpv=100_000)
    assert q.structure_kwargs["bpv"] == -100_000


def test_structure_to_query_calendar():
    sd = StructureDef(
        structure_id="SFRM27_SFRU27_CAL_1",
        structure_type=StructureType.CALENDAR,
        legs=(Leg("SFRM27", 1.0, 96.5, 25), Leg("SFRU27", -1.0, 96.6, 25)),
    )
    q = structure_to_query(_signal(sd), curve="USD-SOFR-1D-Q12STIRT", bpv=100_000)
    kw = q.structure_kwargs
    assert kw["front_tenor"] == "IMM_M2027xIMM_U2027"
    assert kw["back_tenor"] == "IMM_U2027xIMM_Z2027"


def test_structure_to_query_fly_long_rate():
    sd = StructureDef(
        structure_id="SFRM27_SFRU27_SFRZ27_FLY_1_-2_1",
        structure_type=StructureType.BUTTERFLY,
        legs=(
            Leg("SFRM27", 1.0, 96.5, 25),
            Leg("SFRU27", -2.0, 96.6, 25),
            Leg("SFRZ27", 1.0, 96.7, 25),
        ),
    )
    q = structure_to_query(_signal(sd), curve="USD-SOFR-1D-Q12STIRT", bpv=100_000)
    kw = q.structure_kwargs
    assert kw["front_tenor"] == "IMM_M2027xIMM_U2027"
    assert kw["belly_tenor"] == "IMM_U2027xIMM_Z2027"
    assert kw["back_tenor"] == "IMM_Z2027xIMM_H2028"


def test_structure_to_query_fly_flip_inverts_bpv():
    sd = StructureDef(
        structure_id="FLIPFLY",
        structure_type=StructureType.BUTTERFLY,
        legs=(
            Leg("SFRM27", 1.0, 96.5, 25),
            Leg("SFRU27", -2.0, 96.6, 25),
            Leg("SFRZ27", 1.0, 96.7, 25),
        ),
    )
    q = structure_to_query(_signal(sd, flip=True), curve="USD-SOFR-1D-Q12STIRT", bpv=100_000)
    assert q.structure_kwargs["bpv"] == -100_000


def test_structure_position_tag_uses_structure_id():
    sd = StructureDef(
        structure_id="SFRZ26_OUTRIGHT",
        structure_type=StructureType.OUTRIGHT,
        legs=(Leg("SFRZ26", 1.0, 96.5, 25),),
    )
    sig = _signal(sd)
    assert structure_position_tag(sig) == "sfr_screener_SFRZ26_OUTRIGHT"

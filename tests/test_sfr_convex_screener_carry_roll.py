"""Unit tests for the pure-string SFR → IMM tenor transformation."""

import pytest

from RVUtils.SFRConvexScreener._carry_roll import sfr_to_imm_tenor


def test_sfr_to_imm_tenor_z26():
    assert sfr_to_imm_tenor("SFRZ26") == "IMM_Z2026xIMM_H2027"


def test_sfr_to_imm_tenor_h27():
    assert sfr_to_imm_tenor("SFRH27") == "IMM_H2027xIMM_M2027"


def test_sfr_to_imm_tenor_z29_wrap():
    """Year wraps when month is December."""
    assert sfr_to_imm_tenor("SFRZ29") == "IMM_Z2029xIMM_H2030"


def test_sfr_to_imm_tenor_invalid_root_raises():
    with pytest.raises(ValueError):
        sfr_to_imm_tenor("ZZZ26")

# fmt: off
# ruff: noqa: E501
# flake8: noqa
r"""XCCY_SWAP_IUO tags, generated from the Citi Velocity catalog. DO NOT EDIT BY HAND.

Regenerate with::

    python scripts/gen_citivelo_tag_enums.py

10 tags under ``RATES.XCCY_SWAP_IUO``, arranged as one flat enum.

Edits to this file are lost on the next regeneration, and
``tests/test_citivelo_tag_enums.py`` fails the moment it disagrees with the
catalog - so there is no window in which a hand edit merely looks like it worked.
"""

from __future__ import annotations

from Query.CitiVelocity.tag_enums._base import CitiVeloTag, TagNamespace

__all__ = ["XCCY_SWAP_IUO"]

class XCCY_SWAP_IUO(CitiVeloTag):
    """10 tags under ``RATES.XCCY_SWAP_IUO``."""

    __node__ = "RATES.XCCY_SWAP_IUO"

    HKD_USD_FWD = "RATES.XCCY_SWAP_IUO.HKD.USD.FWD"
    HKD_USD_PAR = "RATES.XCCY_SWAP_IUO.HKD.USD.PAR"
    KRW_USD_FWD = "RATES.XCCY_SWAP_IUO.KRW.USD.FWD"
    KRW_USD_PAR = "RATES.XCCY_SWAP_IUO.KRW.USD.PAR"
    SGD_USD_FWD = "RATES.XCCY_SWAP_IUO.SGD.USD.FWD"
    SGD_USD_PAR = "RATES.XCCY_SWAP_IUO.SGD.USD.PAR"
    THB_USD_FWD = "RATES.XCCY_SWAP_IUO.THB.USD.FWD"
    THB_USD_PAR = "RATES.XCCY_SWAP_IUO.THB.USD.PAR"
    TWD_USD_FWD = "RATES.XCCY_SWAP_IUO.TWD.USD.FWD"
    TWD_USD_PAR = "RATES.XCCY_SWAP_IUO.TWD.USD.PAR"


# fmt: off
# ruff: noqa: E501
# flake8: noqa
r"""TSY tags, generated from the Citi Velocity catalog. DO NOT EDIT BY HAND.

Regenerate with::

    python scripts/gen_citivelo_tag_enums.py

38 tags under ``RATES.TSY``, arranged as one flat enum.

Edits to this file are lost on the next regeneration, and
``tests/test_citivelo_tag_enums.py`` fails the moment it disagrees with the
catalog - so there is no window in which a hand edit merely looks like it worked.
"""

from __future__ import annotations

from Query.CitiVelocity.tag_enums._base import CitiVeloTag, TagNamespace

__all__ = ["TSY"]

class TSY(CitiVeloTag):
    """38 tags under ``RATES.TSY``."""

    __node__ = "RATES.TSY"

    TIPS_EXT_POLATED_10Y = "RATES.TSY.TIPS.EXT_POLATED.10Y"
    TIPS_USD_10Y = "RATES.TSY.TIPS.USD.10Y"
    TIPS_USD_30Y = "RATES.TSY.TIPS.USD.30Y"
    TIPS_USD_5Y = "RATES.TSY.TIPS.USD.5Y"
    TSY_BFLY_10Y = "RATES.TSY.TSY.BFLY.10Y"
    TSY_BFLY_1Y = "RATES.TSY.TSY.BFLY.1Y"
    TSY_BFLY_2Y = "RATES.TSY.TSY.BFLY.2Y"
    TSY_BFLY_3Y = "RATES.TSY.TSY.BFLY.3Y"
    TSY_BFLY_5Y = "RATES.TSY.TSY.BFLY.5Y"
    TSY_BFLY_7Y = "RATES.TSY.TSY.BFLY.7Y"
    TSY_CMT_BFLY = "RATES.TSY.TSY.CMT.BFLY"
    TSY_CMT_PAR = "RATES.TSY.TSY.CMT.PAR"
    TSY_CURVES_10Y = "RATES.TSY.TSY.CURVES.10Y"
    TSY_CURVES_1Y = "RATES.TSY.TSY.CURVES.1Y"
    TSY_CURVES_20Y = "RATES.TSY.TSY.CURVES.20Y"
    TSY_CURVES_2Y = "RATES.TSY.TSY.CURVES.2Y"
    TSY_CURVES_3Y = "RATES.TSY.TSY.CURVES.3Y"
    TSY_CURVES_5Y = "RATES.TSY.TSY.CURVES.5Y"
    TSY_CURVES_7Y = "RATES.TSY.TSY.CURVES.7Y"
    TSY_OLD_1_10Y = "RATES.TSY.TSY.OLD_1.10Y"
    TSY_OLD_1_20Y = "RATES.TSY.TSY.OLD_1.20Y"
    TSY_OLD_1_2Y = "RATES.TSY.TSY.OLD_1.2Y"
    TSY_OLD_1_30Y = "RATES.TSY.TSY.OLD_1.30Y"
    TSY_OLD_1_3Y = "RATES.TSY.TSY.OLD_1.3Y"
    TSY_OLD_1_5Y = "RATES.TSY.TSY.OLD_1.5Y"
    TSY_OLD_1_7Y = "RATES.TSY.TSY.OLD_1.7Y"
    TSY_OTR_10Y = "RATES.TSY.TSY.OTR.10Y"
    TSY_OTR_1Y = "RATES.TSY.TSY.OTR.1Y"
    TSY_OTR_20Y = "RATES.TSY.TSY.OTR.20Y"
    TSY_OTR_2Y = "RATES.TSY.TSY.OTR.2Y"
    TSY_OTR_30Y = "RATES.TSY.TSY.OTR.30Y"
    TSY_OTR_3Y = "RATES.TSY.TSY.OTR.3Y"
    TSY_OTR_5Y = "RATES.TSY.TSY.OTR.5Y"
    TSY_OTR_7Y = "RATES.TSY.TSY.OTR.7Y"
    T_BILL_OTR_1M = "RATES.TSY.T_BILL.OTR.1M"
    T_BILL_OTR_1Y = "RATES.TSY.T_BILL.OTR.1Y"
    T_BILL_OTR_3M = "RATES.TSY.T_BILL.OTR.3M"
    T_BILL_OTR_6M = "RATES.TSY.T_BILL.OTR.6M"


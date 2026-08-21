# fmt: off
# ruff: noqa: E501
# flake8: noqa
r"""POS_MON tags, generated from the Citi Velocity catalog. DO NOT EDIT BY HAND.

Regenerate with::

    python scripts/gen_citivelo_tag_enums.py

16 tags under ``RATES.POS_MON``, arranged as one flat enum.

Edits to this file are lost on the next regeneration, and
``tests/test_citivelo_tag_enums.py`` fails the moment it disagrees with the
catalog - so there is no window in which a hand edit merely looks like it worked.
"""

from __future__ import annotations

from Query.CitiVelocity.tag_enums._base import CitiVeloTag, TagNamespace

__all__ = ["POS_MON"]

class POS_MON(CitiVeloTag):
    """16 tags under ``RATES.POS_MON``."""

    __node__ = "RATES.POS_MON"

    AUS_10Y_RPM_CASH = "RATES.POS_MON.AUS.10Y.RPM_CASH"
    AUS_10Y_RPM_FUT = "RATES.POS_MON.AUS.10Y.RPM_FUT"
    CAN_10Y_RPM_CASH = "RATES.POS_MON.CAN.10Y.RPM_CASH"
    CAN_10Y_RPM_FUT = "RATES.POS_MON.CAN.10Y.RPM_FUT"
    DEU_10Y_RPM_CASH = "RATES.POS_MON.DEU.10Y.RPM_CASH"
    DEU_10Y_RPM_FUT = "RATES.POS_MON.DEU.10Y.RPM_FUT"
    FRA_10Y_RPM_CASH = "RATES.POS_MON.FRA.10Y.RPM_CASH"
    FRA_10Y_RPM_FUT = "RATES.POS_MON.FRA.10Y.RPM_FUT"
    GBR_10Y_RPM_CASH = "RATES.POS_MON.GBR.10Y.RPM_CASH"
    GBR_10Y_RPM_FUT = "RATES.POS_MON.GBR.10Y.RPM_FUT"
    ITA_10Y_RPM_CASH = "RATES.POS_MON.ITA.10Y.RPM_CASH"
    ITA_10Y_RPM_FUT = "RATES.POS_MON.ITA.10Y.RPM_FUT"
    JPN_10Y_RPM_CASH = "RATES.POS_MON.JPN.10Y.RPM_CASH"
    JPN_10Y_RPM_FUT = "RATES.POS_MON.JPN.10Y.RPM_FUT"
    USA_10Y_RPM_CASH = "RATES.POS_MON.USA.10Y.RPM_CASH"
    USA_10Y_RPM_FUT = "RATES.POS_MON.USA.10Y.RPM_FUT"


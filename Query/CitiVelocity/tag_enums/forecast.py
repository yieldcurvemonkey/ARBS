# fmt: off
# ruff: noqa: E501
# flake8: noqa
r"""FORECAST tags, generated from the Citi Velocity catalog. DO NOT EDIT BY HAND.

Regenerate with::

    python scripts/gen_citivelo_tag_enums.py

12 tags under ``RATES.FORECAST``, arranged as one flat enum.

Edits to this file are lost on the next regeneration, and
``tests/test_citivelo_tag_enums.py`` fails the moment it disagrees with the
catalog - so there is no window in which a hand edit merely looks like it worked.
"""

from __future__ import annotations

from Query.CitiVelocity.tag_enums._base import CitiVeloTag, TagNamespace

__all__ = ["FORECAST"]

class FORECAST(CitiVeloTag):
    """12 tags under ``RATES.FORECAST``."""

    __node__ = "RATES.FORECAST"

    ECB_DEPO_FCST_QTR_CITI = "RATES.FORECAST.ECB_DEPO_FCST.QTR.CITI"
    FED_FUNDS_FCST_ANNUAL_CITI = "RATES.FORECAST.FED_FUNDS_FCST.ANNUAL.CITI"
    FED_FUNDS_FCST_QTR_CITI = "RATES.FORECAST.FED_FUNDS_FCST.QTR.CITI"
    GER_10Y_YLD_FCST_QTR_CITI = "RATES.FORECAST.GER_10Y_YLD_FCST.QTR.CITI"
    JGB_10Y_YLD_FCST_ANNUAL_CITI = "RATES.FORECAST.JGB_10Y_YLD_FCST.ANNUAL.CITI"
    JGB_10Y_YLD_FCST_QTR_CITI = "RATES.FORECAST.JGB_10Y_YLD_FCST.QTR.CITI"
    UK_10Y_YLD_FCST_ANNUAL_CITI = "RATES.FORECAST.UK_10Y_YLD_FCST.ANNUAL.CITI"
    UK_10Y_YLD_FCST_QTR_CITI = "RATES.FORECAST.UK_10Y_YLD_FCST.QTR.CITI"
    UST_10Y_YLD_FCST_ANNUAL_CITI = "RATES.FORECAST.UST_10Y_YLD_FCST.ANNUAL.CITI"
    UST_10Y_YLD_FCST_QTR_CITI = "RATES.FORECAST.UST_10Y_YLD_FCST.QTR.CITI"
    UST_2Y_YLD_FCST_ANNUAL_CITI = "RATES.FORECAST.UST_2Y_YLD_FCST.ANNUAL.CITI"
    UST_2Y_YLD_FCST_QTR_CITI = "RATES.FORECAST.UST_2Y_YLD_FCST.QTR.CITI"


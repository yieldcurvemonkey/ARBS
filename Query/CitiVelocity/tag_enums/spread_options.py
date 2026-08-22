# fmt: off
# ruff: noqa: E501
# flake8: noqa
r"""SPREAD_OPTIONS tags, generated from the Citi Velocity catalog. DO NOT EDIT BY HAND.

Regenerate with::

    python scripts/gen_citivelo_tag_enums.py

12 tags under ``RATES.SPREAD_OPTIONS``, arranged as one flat enum.

Edits to this file are lost on the next regeneration, and
``tests/test_citivelo_tag_enums.py`` fails the moment it disagrees with the
catalog - so there is no window in which a hand edit merely looks like it worked.
"""

from __future__ import annotations

from Query.CitiVelocity.tag_enums._base import CitiVeloTag, TagNamespace

__all__ = ["SPREAD_OPTIONS"]

class SPREAD_OPTIONS(CitiVeloTag):
    """12 tags under ``RATES.SPREAD_OPTIONS``."""

    __node__ = "RATES.SPREAD_OPTIONS"

    EUR_OPT_CAP_PRICE = "RATES.SPREAD_OPTIONS.EUR.OPT_CAP.PRICE"
    EUR_OPT_CAP_VOL = "RATES.SPREAD_OPTIONS.EUR.OPT_CAP.VOL"
    EUR_OPT_FLR_PRICE = "RATES.SPREAD_OPTIONS.EUR.OPT_FLR.PRICE"
    EUR_OPT_FLR_VOL = "RATES.SPREAD_OPTIONS.EUR.OPT_FLR.VOL"
    EUR_OPT_STR_PRICE = "RATES.SPREAD_OPTIONS.EUR.OPT_STR.PRICE"
    EUR_OPT_STR_VOL = "RATES.SPREAD_OPTIONS.EUR.OPT_STR.VOL"
    USD_OPT_CAP_PRICE = "RATES.SPREAD_OPTIONS.USD.OPT_CAP.PRICE"
    USD_OPT_CAP_VOL = "RATES.SPREAD_OPTIONS.USD.OPT_CAP.VOL"
    USD_OPT_FLR_PRICE = "RATES.SPREAD_OPTIONS.USD.OPT_FLR.PRICE"
    USD_OPT_FLR_VOL = "RATES.SPREAD_OPTIONS.USD.OPT_FLR.VOL"
    USD_OPT_STR_PRICE = "RATES.SPREAD_OPTIONS.USD.OPT_STR.PRICE"
    USD_OPT_STR_VOL = "RATES.SPREAD_OPTIONS.USD.OPT_STR.VOL"


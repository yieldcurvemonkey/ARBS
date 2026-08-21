# fmt: off
# ruff: noqa: E501
# flake8: noqa
r"""INVOICESPREAD tags, generated from the Citi Velocity catalog. DO NOT EDIT BY HAND.

Regenerate with::

    python scripts/gen_citivelo_tag_enums.py

14 tags under ``RATES.INVOICESPREAD``, arranged as one flat enum.

Edits to this file are lost on the next regeneration, and
``tests/test_citivelo_tag_enums.py`` fails the moment it disagrees with the
catalog - so there is no window in which a hand edit merely looks like it worked.
"""

from __future__ import annotations

from Query.CitiVelocity.tag_enums._base import CitiVeloTag, TagNamespace

__all__ = ["INVOICESPREAD"]

class INVOICESPREAD(CitiVeloTag):
    """14 tags under ``RATES.INVOICESPREAD``."""

    __node__ = "RATES.INVOICESPREAD"

    USD_10Y = "RATES.INVOICESPREAD.USD.10Y"
    USD_2Y = "RATES.INVOICESPREAD.USD.2Y"
    USD_3Y = "RATES.INVOICESPREAD.USD.3Y"
    USD_5Y = "RATES.INVOICESPREAD.USD.5Y"
    USD_ULTRA10Y = "RATES.INVOICESPREAD.USD.ULTRA10Y"
    USD_ULTRA30Y = "RATES.INVOICESPREAD.USD.ULTRA30Y"
    USD_ULTRABOND = "RATES.INVOICESPREAD.USD.ULTRABOND"
    USD_BACKMONTH_10Y = "RATES.INVOICESPREAD.USD_BACKMONTH.10Y"
    USD_BACKMONTH_2Y = "RATES.INVOICESPREAD.USD_BACKMONTH.2Y"
    USD_BACKMONTH_3Y = "RATES.INVOICESPREAD.USD_BACKMONTH.3Y"
    USD_BACKMONTH_5Y = "RATES.INVOICESPREAD.USD_BACKMONTH.5Y"
    USD_BACKMONTH_ULTRA10Y = "RATES.INVOICESPREAD.USD_BACKMONTH.ULTRA10Y"
    USD_BACKMONTH_ULTRA30Y = "RATES.INVOICESPREAD.USD_BACKMONTH.ULTRA30Y"
    USD_BACKMONTH_ULTRABOND = "RATES.INVOICESPREAD.USD_BACKMONTH.ULTRABOND"


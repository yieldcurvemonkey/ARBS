# fmt: off
# ruff: noqa: E501
# flake8: noqa
r"""MIDCURVES tags, generated from the Citi Velocity catalog. DO NOT EDIT BY HAND.

Regenerate with::

    python scripts/gen_citivelo_tag_enums.py

5 tags under ``RATES.MIDCURVES``, arranged as one flat enum.

Edits to this file are lost on the next regeneration, and
``tests/test_citivelo_tag_enums.py`` fails the moment it disagrees with the
catalog - so there is no window in which a hand edit merely looks like it worked.
"""

from __future__ import annotations

from Query.CitiVelocity.tag_enums._base import CitiVeloTag, TagNamespace

__all__ = ["MIDCURVES"]

class MIDCURVES(CitiVeloTag):
    """5 tags under ``RATES.MIDCURVES``."""

    __node__ = "RATES.MIDCURVES"

    EUR = "RATES.MIDCURVES.EUR"
    EURIBOR = "RATES.MIDCURVES.EURIBOR"
    GBP = "RATES.MIDCURVES.GBP"
    USD = "RATES.MIDCURVES.USD"
    USD_SOFR = "RATES.MIDCURVES.USD_SOFR"


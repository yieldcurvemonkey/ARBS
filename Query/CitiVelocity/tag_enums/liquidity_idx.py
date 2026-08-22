# fmt: off
# ruff: noqa: E501
# flake8: noqa
r"""LIQUIDITY_IDX tags, generated from the Citi Velocity catalog. DO NOT EDIT BY HAND.

Regenerate with::

    python scripts/gen_citivelo_tag_enums.py

1 tags under ``RATES.LIQUIDITY_IDX``, arranged as one flat enum.

Edits to this file are lost on the next regeneration, and
``tests/test_citivelo_tag_enums.py`` fails the moment it disagrees with the
catalog - so there is no window in which a hand edit merely looks like it worked.
"""

from __future__ import annotations

from Query.CitiVelocity.tag_enums._base import CitiVeloTag, TagNamespace

__all__ = ["LIQUIDITY_IDX"]

class LIQUIDITY_IDX(CitiVeloTag):
    """1 tags under ``RATES.LIQUIDITY_IDX``."""

    __node__ = "RATES.LIQUIDITY_IDX"

    UST_AVG_DEPTH = "RATES.LIQUIDITY_IDX.UST.AVG_DEPTH"


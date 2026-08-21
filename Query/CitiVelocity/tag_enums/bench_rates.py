# fmt: off
# ruff: noqa: E501
# flake8: noqa
r"""BENCH_RATES tags, generated from the Citi Velocity catalog. DO NOT EDIT BY HAND.

Regenerate with::

    python scripts/gen_citivelo_tag_enums.py

10 tags under ``RATES.BENCH_RATES``, arranged as one flat enum.

Edits to this file are lost on the next regeneration, and
``tests/test_citivelo_tag_enums.py`` fails the moment it disagrees with the
catalog - so there is no window in which a hand edit merely looks like it worked.
"""

from __future__ import annotations

from Query.CitiVelocity.tag_enums._base import CitiVeloTag, TagNamespace

__all__ = ["BENCH_RATES"]

class BENCH_RATES(CitiVeloTag):
    """10 tags under ``RATES.BENCH_RATES``."""

    __node__ = "RATES.BENCH_RATES"

    ECB = "RATES.BENCH_RATES.ECB"
    FED_FUNDS = "RATES.BENCH_RATES.FED_FUNDS"
    JPY_DISCOUNT = "RATES.BENCH_RATES.JPY_DISCOUNT"
    JPY_TARGET = "RATES.BENCH_RATES.JPY_TARGET"
    UK_BASE = "RATES.BENCH_RATES.UK_BASE"
    US_FED_CP_1M = "RATES.BENCH_RATES.US_FED_CP_1M"
    US_FED_CP_2M = "RATES.BENCH_RATES.US_FED_CP_2M"
    US_FED_CP_3M = "RATES.BENCH_RATES.US_FED_CP_3M"
    US_FED_FUNDS_TARGET = "RATES.BENCH_RATES.US_FED_FUNDS_TARGET"
    US_FED_PRIME = "RATES.BENCH_RATES.US_FED_PRIME"


r"""What the generated tag tree was built from. DO NOT EDIT BY HAND.

:data:`CATALOG_FINGERPRINT` is a SHA-256 over the catalog artefacts listed in
:data:`GENERATED_FROM`. ``tests/test_citivelo_tag_enums.py`` recomputes it, so a
catalog refresh that is not followed by ``python scripts/gen_citivelo_tag_enums.py``
fails the fast gate rather than silently leaving the enum describing a catalog
that no longer exists.

The fingerprint is derived from the inputs on purpose. A hand-maintained version
number is bumped by whoever remembers, which is exactly the moment they do not.
"""

from __future__ import annotations

from typing import Dict, Tuple

__all__ = ["CATALOG_FINGERPRINT", "COUNTS", "FAMILIES", "GENERATED_FROM", "TOTAL", "THRESHOLD"]

#: SHA-256 over ``GENERATED_FROM``, in that order, names included.
CATALOG_FINGERPRINT = "de9c1d6b50a0b58298cacd8572f9aa9d3cf2eb76e98e107b190f865d554e19f7"

#: The catalog artefacts hashed into the fingerprint.
GENERATED_FROM: Tuple[str, ...] = ('dag_rates_deep.json', 'shapes2.json')

#: The split threshold in force when this tree was emitted.
THRESHOLD = 1024

#: Every family, in catalog order.
FAMILIES: Tuple[str, ...] = (
    "AGENCY_INVENTORY",
    "BASIS_SWAPS",
    "BENCH_RATES",
    "BOND",
    "FLOWS",
    "FORECAST",
    "FRA",
    "FRA_OIS",
    "FUTURES",
    "INFLATION",
    "INVOICESPREAD",
    "LIQUIDITY_IDX",
    "MBS",
    "MIDCURVES",
    "MONEY_MARKETS",
    "OIS",
    "OIS_INVOICESPREAD",
    "OIS_MEETING",
    "POS_MON",
    "REPO",
    "SOV",
    "SPREAD_OPTIONS",
    "SSA",
    "SSA_CS",
    "SWAP_INTERNAL",
    "SWAP_LIBOR",
    "TSY",
    "VOL",
    "XCCY_BASIS_INTERNAL",
    "XCCY_OIS_SWAP",
    "XCCY_OIS_SWAP_IUO",
    "XCCY_SWAP",
    "XCCY_SWAP_IUO",
)

#: ``{family: tag count}``. Available without importing any family module.
COUNTS: Dict[str, int] = {
    "AGENCY_INVENTORY": 504,
    "BASIS_SWAPS": 312,
    "BENCH_RATES": 10,
    "BOND": 1,
    "FLOWS": 337,
    "FORECAST": 12,
    "FRA": 324,
    "FRA_OIS": 121,
    "FUTURES": 302,
    "INFLATION": 6864,
    "INVOICESPREAD": 14,
    "LIQUIDITY_IDX": 1,
    "MBS": 584,
    "MIDCURVES": 5,
    "MONEY_MARKETS": 192,
    "OIS": 3113,
    "OIS_INVOICESPREAD": 44,
    "OIS_MEETING": 449,
    "POS_MON": 16,
    "REPO": 224,
    "SOV": 1240,
    "SPREAD_OPTIONS": 12,
    "SSA": 304,
    "SSA_CS": 100,
    "SWAP_INTERNAL": 7800,
    "SWAP_LIBOR": 5329,
    "TSY": 38,
    "VOL": 26233,
    "XCCY_BASIS_INTERNAL": 16,
    "XCCY_OIS_SWAP": 10980,
    "XCCY_OIS_SWAP_IUO": 1880,
    "XCCY_SWAP": 54,
    "XCCY_SWAP_IUO": 10,
}

#: Total tags across every family.
TOTAL = 67425

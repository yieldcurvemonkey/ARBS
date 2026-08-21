"""The ``CITIVELO`` query product: structures over Citi Velocity tags.

Importing this package registers the product adapter, so a bare
``from Query.CitiVelocity import CitiVeloQuery`` is enough to make the product
usable.
"""

from __future__ import annotations

import Query.CitiVelocity.adapter  # noqa: F401  (registers the product)
from Query.CitiVelocity._CitiVeloLeg import CitiVeloKind, CitiVeloLeg, CitiVeloUnit
from Query.CitiVelocity.CitiVeloQuery import CitiVeloQuery, CitiVeloQueryWrapper
from Query.CitiVelocity.CitiVeloStructure import (
    CitiVeloStructure,
    CitiVeloStructureFunctionMap,
)
from Query.CitiVelocity.CitiVeloValue import CitiVeloValue, CitiVeloValueFunctionMap
from Query.CitiVelocity.tag_enums import CitiVeloTag, CitiVeloTags

__all__ = [
    "CitiVeloKind",
    "CitiVeloLeg",
    "CitiVeloQuery",
    "CitiVeloQueryWrapper",
    "CitiVeloStructure",
    "CitiVeloStructureFunctionMap",
    "CitiVeloTag",
    "CitiVeloTags",
    "CitiVeloUnit",
    "CitiVeloValue",
    "CitiVeloValueFunctionMap",
]

"""Utilities for resolving SFR futures strip/bundle symbols.

Pre-packaged bundles:
    whites  — front 4 quarterly contracts (CM1-CM4)
    reds    — next 4 quarterly contracts (CM5-CM8)
    greens  — next 4 quarterly contracts (CM9-CM12)
    blues   — next 4 quarterly contracts (CM13-CM16)
    2y      — front 8 quarterly contracts (CM1-CM8)
    3y      — front 12 quarterly contracts (CM1-CM12)

Each pack is relative to a reference date (as_of) using IMM cutoff logic.
"""

from __future__ import annotations

import datetime
from typing import Dict, List, Optional, Sequence, Tuple, Union

# Bundle presets: (start_index, count) for resolve_quarterly_contracts
STRIP_PRESETS: Dict[str, Tuple[int, int]] = {
    "whites": (0, 4),
    "reds": (4, 4),
    "greens": (8, 4),
    "blues": (12, 4),
    "2y": (0, 8),
    "2y_bundle": (0, 8),
    "3y": (0, 12),
    "3y_bundle": (0, 12),
}


def resolve_strip_symbols(
    strip: Union[str, Sequence[str]],
    *,
    as_of: Optional[datetime.date] = None,
) -> List[str]:
    """Resolve a strip specifier to a list of SFR contract symbols.

    Parameters
    ----------
    strip : str or list of str
        Either a preset name (``"whites"``, ``"reds"``, ``"greens"``,
        ``"blues"``, ``"2y"``, ``"3y"``) or an explicit list of symbols
        (e.g. ``["SFRZ26", "SFRH27", "SFRM27", "SFRU27"]``).
    as_of : date, optional
        Reference date for resolving preset bundles. Required when
        *strip* is a preset name.

    Returns
    -------
    list of str
        Ordered list of contract symbols (e.g. ``["SFRM26", "SFRU26", "SFRZ26", "SFRH27"]``).
    """
    # Explicit symbol list
    if not isinstance(strip, str):
        return list(strip)

    key = strip.lower().replace(" ", "_").replace("-", "_")
    if key not in STRIP_PRESETS:
        # Maybe it's a single symbol like "SFRZ26"
        if key.upper().startswith("SFR") and len(key) >= 5:
            return [strip.upper()]
        raise ValueError(
            f"Unknown strip preset: {strip!r}. "
            f"Valid presets: {sorted(STRIP_PRESETS.keys())}. "
            f"Or pass a list of explicit symbols."
        )

    if as_of is None:
        raise ValueError(f"as_of date is required when using preset strip name {strip!r}")

    start_index, count = STRIP_PRESETS[key]

    # Import here to avoid circular imports at module level
    from MDP.STIRFutures._sofr_option_contracts import resolve_quarterly_contracts

    return resolve_quarterly_contracts(as_of, start_index=start_index, count=count, root="SFR")

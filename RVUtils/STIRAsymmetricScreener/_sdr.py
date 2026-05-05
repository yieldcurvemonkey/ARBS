"""SDR / CME-block co-movement lookup for the STIR Options Asymmetric Screener.

Spec §2.10 / §11. v1: no canonical listed-STIR-options block tape feed
exists in the repo (SDR is for swaps). This module provides an interface
that the orchestrator wires through but defaults to "no recent
confirmation" — a structured warning surfaces the gap. Callers can pass
in a callable to inject an external feed when one becomes available.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from RVUtils.STIRAsymmetricScreener._types import ArchetypeType, CandidateDef

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BlockTrade:
    """A single block trade record."""

    trade_date: datetime.date
    underlying: str
    archetype: ArchetypeType
    anchor_strike: float
    size: float
    side: str  # "buy" or "sell" or "unknown"


def lookup_recent_block_trades_default(
    *,
    underlying: str,
    expiry: datetime.date,
    archetype: ArchetypeType,
    as_of: datetime.date,
    lookback_sessions: int = 5,
) -> List[BlockTrade]:
    """Default block-trade lookup — empty list with a structured log.

    TODO(blocker): wire to an actual CME block-trade tape ingestor when
    one exists. The orchestrator passes a callable in
    ``screener.build_snapshot``; tests inject deterministic stubs.
    """
    logger.debug(
        "sdr_block_lookup_unavailable",
        extra={
            "underlying": underlying,
            "expiry": expiry.isoformat(),
            "archetype": archetype.value,
            "as_of": as_of.isoformat(),
        },
    )
    return []


def is_sdr_confirmed(
    *,
    candidate: CandidateDef,
    as_of: datetime.date,
    lookback_sessions: int = 5,
    proximity_bps: float = 12.5,
    block_trade_loader: Optional[Callable[..., List[BlockTrade]]] = None,
) -> bool:
    """Return True if a recent block trade matches this candidate's family.

    Match rules:
    - Archetype matches.
    - Underlying contract matches.
    - Anchor strike within ``proximity_bps`` of any leg strike.
    - Trade date within last ``lookback_sessions`` business sessions.
    """
    loader = block_trade_loader or lookup_recent_block_trades_default
    try:
        trades = loader(
            underlying=candidate.underlying,
            expiry=candidate.expiry,
            archetype=candidate.archetype,
            as_of=as_of,
            lookback_sessions=lookback_sessions,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("sdr_loader_failed: %s", exc)
        return False

    if not trades:
        return False

    candidate_strikes = {round(leg.strike, 4) for leg in candidate.legs}
    proximity_price = proximity_bps / 100.0

    for t in trades:
        if t.archetype != candidate.archetype:
            continue
        if t.underlying != candidate.underlying:
            continue
        for k in candidate_strikes:
            if abs(t.anchor_strike - k) <= proximity_price:
                return True
    return False

r"""Recorded live Citi Velocity snapshots, so the spot check can run offline.

A synthetic cube proves the arithmetic is self-consistent. It cannot prove the
cube prices a real market, and it cannot be mutation-tested against anything a
real skew would object to - a smooth generated smile has no kinks, no wing
flattening and no stale corner. Both matter here, because
:mod:`MDP.CitiVelocityExcel.vol.spot_check` exists specifically to catch errors a
self-consistent cube hides.

So one snapshot is recorded verbatim from a signed-in add-in and committed:

``harvest/snapshots/usd_cube_2026-08-06.json``
    USD, 2026-08-06. 5 expiries x 4 tenors x 12 signed strike offsets plus the
    ATM surface (260 tags, zero per-tag failures), the 44-tenor ``RATES.OIS``
    par grid the curve is stripped from, and six of Citi's own published
    ``RATES.OIS.USD_SOFR.FWD.<e>.<t>`` forwards. Captured in 8 ``CV*`` calls on
    2026-08-07; the observation date is the last on which all three were
    simultaneously complete.

Nothing here fetches. :func:`load_snapshot` reads the file, and the cube it
returns is assembled by the ordinary :func:`cube_from_quotes` path from the raw
served numbers, so the unit guard and the ragged-cube guard both run exactly as
they do on live data.
"""

from __future__ import annotations

import datetime
import json
import pathlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from MDP.CitiVelocityExcel.vol.cube_data import SwaptionCubeData, cube_from_quotes

__all__ = ["LiveCubeSnapshot", "SNAPSHOT_DIR", "available_snapshots", "load_snapshot"]

#: Where the committed snapshots live.
SNAPSHOT_DIR = pathlib.Path(__file__).resolve().parents[1] / "harvest" / "snapshots"

#: The one recorded today. Named rather than globbed so a new file cannot
#: silently change what the tests are asserting against.
DEFAULT_SNAPSHOT = "usd_cube_2026-08-06.json"


@dataclass(frozen=True)
class LiveCubeSnapshot:
    """One dated capture: the vol tags, the par grid and Citi's own forwards.

    Attributes
    ----------
    as_of
        The observation date every number below shares.
    currency, citi_index
        ``'USD'`` / ``'USD_SOFR'``.
    vol_quotes
        ``{tag: served number}`` exactly as the add-in gave it - no rescaling, so
        :func:`~MDP.CitiVelocityExcel.vol.cube_data.assert_vol_units` still has
        something to check.
    par_rates
        ``{tenor: percent}``, ready for ``build_rl_ois_curve`` /
        ``build_ql_ois_curve``.
    citi_forwards
        ``{(expiry, tenor): percent}`` from ``RATES.OIS.<idx>.FWD.<e>.<t>``. This
        is the only external witness to where Citi anchors its strike offsets.
    """

    as_of: datetime.date
    currency: str
    citi_index: str
    expiries: Tuple[str, ...]
    tenors: Tuple[str, ...]
    offsets_bp: Tuple[float, ...]
    vol_quotes: Dict[str, float]
    par_rates: Dict[str, float]
    citi_forwards: Dict[Tuple[str, str], float]
    captured_at: str
    path: pathlib.Path

    def cube(
        self,
        *,
        expiries: Optional[Sequence[str]] = None,
        tenors: Optional[Sequence[str]] = None,
        offsets_bp: Optional[Sequence[float]] = None,
        strict: bool = True,
    ) -> SwaptionCubeData:
        """Assemble the :class:`SwaptionCubeData` through the normal path.

        Narrow the axes to make a smaller cube; the default is everything that
        was captured.
        """
        return cube_from_quotes(
            quotes=self.vol_quotes,
            currency=self.currency,
            as_of=self.as_of,
            expiries=list(expiries) if expiries is not None else list(self.expiries),
            tenors=list(tenors) if tenors is not None else list(self.tenors),
            offsets_bp=list(offsets_bp) if offsets_bp is not None else list(self.offsets_bp),
            served_unit="bp",
            strict=strict,
            source=f"citivelo_live_snapshot/{self.as_of.isoformat()}",
        )

    def __repr__(self) -> str:
        return (
            f"LiveCubeSnapshot({self.currency} {self.as_of}, "
            f"{len(self.expiries)}x{len(self.tenors)}x{len(self.offsets_bp)} nodes, "
            f"{len(self.par_rates)} par tenors, {len(self.citi_forwards)} published forwards)"
        )


def available_snapshots() -> List[str]:
    """File names under :data:`SNAPSHOT_DIR`, sorted."""
    if not SNAPSHOT_DIR.is_dir():
        return []
    return sorted(p.name for p in SNAPSHOT_DIR.glob("*.json"))


def load_snapshot(name: str = DEFAULT_SNAPSHOT) -> LiveCubeSnapshot:
    """Read one committed snapshot.

    Raises
    ------
    FileNotFoundError
        Naming the snapshots that do exist - a missing fixture is a checkout
        problem, not something to paper over with synthetic data.
    """
    path = SNAPSHOT_DIR / str(name)
    if not path.is_file():
        raise FileNotFoundError(
            f"No Citi Velocity snapshot at {path}. Available: {available_snapshots() or '(none)'}. "
            "Re-record one with MDP/CitiVelocityExcel/harvest/verify_live.py --capture."
        )
    payload: Dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    forwards: Dict[Tuple[str, str], float] = {}
    for tag, value in payload.get("citi_forwards", {}).items():
        point = payload.get("fwd_points", {}).get(tag)
        if point:
            forwards[(str(point[0]), str(point[1]))] = float(value)
    return LiveCubeSnapshot(
        as_of=datetime.date.fromisoformat(str(payload["as_of"])),
        currency=str(payload["currency"]),
        citi_index=str(payload["citi_index"]),
        expiries=tuple(str(e) for e in payload["expiries"]),
        tenors=tuple(str(t) for t in payload["tenors"]),
        offsets_bp=tuple(float(o) for o in payload["offsets_bp"]),
        vol_quotes={str(k): float(v) for k, v in payload["vol_quotes"].items()},
        par_rates={str(k): float(v) for k, v in payload["par_rates"].items()},
        citi_forwards=forwards,
        captured_at=str(payload.get("captured_at", "")),
        path=path,
    )

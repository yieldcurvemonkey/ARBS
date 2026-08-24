r"""The CA-vs-fly universe: which CA structures trade against which butterflies.

Frozen by ``docs/convexityrv/cavf-grid-preregistration.md`` BEFORE any scoring.
Everything here is a catalogue or a pure date computation; nothing touches
market data.

Two vocabularies meet here and the seams are deliberate:

* **CA structures** are TB labels — the same strings ``IRSwapsTB.sfr_cvx_adj``
  accepts, so the panel column for a structure is exactly
  ``_cvx_col_name(curve, label)`` and there is no second labelling scheme to
  drift. ``BUNDLE{N}Y`` is the CME front-anchored bundle (ranks ``1..4N``),
  added to the TB vocabulary by this block; the legacy ``BUNDLE{b}`` 16-quarter
  windows are NOT in the tradeable set.
* **Flies** are ``strat2_fly_universe.FlySpec`` objects. The tradeable fly set
  per structure is Citi's shape (2s5s10s), the front fly with the only measured
  R² plateau (1s2s3s), and the shape nearest pack expiries (2s3s5s) — each at
  spot and at the structure's *matched* forward start, the start nearest its
  mean contract expiry ``T1``. The matched start is how the forward-start
  hypothesis ("vol at the pack's own expiry should hedge it better") becomes a
  declared, falsifiable comparison instead of a 54-cell fishing trip.

Sizing identities used downstream (verified against Citi's published tickets in
``strat2_sofr_convexity`` and re-asserted in the notebook's sign probe):

* ``CA_DV01 = n_legs · contracts_per_leg · $25`` → ``contracts_per_leg =
  round(CA_DV01 / (n_legs · 25))``.
* β is fitted in **bp of CA per bp of fly**, so ``belly_DV01 = β · CA_DV01``
  directly. (Citi's printed β≈21 lives in bp-per-percent units; divide by 100
  to compare: 21.4 → 0.214 bp/bp.)
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from RVUtils.ConvexityRV.strat2_fly_universe import (
    FLY_SHAPES,
    FlySpec,
    fly_universe,
    tenor_key,
)

__all__ = [
    "CA_DV01_DEFAULT",
    "DV01_PER_CONTRACT",
    "FLY_SHAPE_NAMES",
    "MATCHED_STARTS",
    "StructureSpec",
    "STRUCTURES",
    "ca_col",
    "contracts_for",
    "contracts_per_leg",
    "flies_for",
    "fly_leg_tenors",
    "matched_start",
    "structure_by_label",
    "swap_window",
    "tradeable_fly_specs",
]

DV01_PER_CONTRACT = 25.0
CA_DV01_DEFAULT = 100_000.0

#: The three declared shapes (see the pre-registration for why these three).
FLY_SHAPE_NAMES: Tuple[str, ...] = ("1s2s3s", "2s3s5s", "2s5s10s")

#: Forward starts available in the leg panel. 4y exists so a fly can start at
#: the Golds expiry; it is this block's addition to the module universe.
MATCHED_STARTS: Tuple[float, ...] = (1.0, 2.0, 3.0, 4.0, 5.0)


@dataclass(frozen=True)
class StructureSpec:
    """One tradeable CA structure.

    ``t1_mean_y`` is the average ACT-year distance to the member contracts'
    IMM dates, approximated on the rank grid as ``0.25·(rank + 1)`` per member
    and then averaged — the quantity the matched forward start is chosen
    against. It is an approximation by construction (the true T1 moves inside
    each quarter); the matched start only needs the nearest integer year.
    """

    label: str
    kind: str                 # "pack" | "bundle" | "outright"
    ranks: Tuple[int, ...]

    @property
    def n_legs(self) -> int:
        return len(self.ranks)

    @property
    def t1_mean_y(self) -> float:
        return sum(0.25 * (r + 1) for r in self.ranks) / len(self.ranks)

    @property
    def matched_start_y(self) -> float:
        return matched_start(self.t1_mean_y)


def matched_start(t1_mean_y: float, starts: Sequence[float] = MATCHED_STARTS) -> float:
    """The available forward start nearest the structure's mean expiry."""
    return min(starts, key=lambda s: abs(s - t1_mean_y))


def _spec(label: str, kind: str, ranks: Sequence[int]) -> StructureSpec:
    return StructureSpec(label=label, kind=kind, ranks=tuple(ranks))


#: The 14 tradeable structures of the pre-registration, in screen order.
STRUCTURES: Tuple[StructureSpec, ...] = (
    _spec("WHITES", "pack", range(1, 5)),
    _spec("REDS", "pack", range(5, 9)),
    _spec("GREENS", "pack", range(9, 13)),
    _spec("BLUES", "pack", range(13, 17)),
    _spec("GOLDS", "pack", range(17, 21)),
    _spec("BUNDLE2Y", "bundle", range(1, 9)),
    _spec("BUNDLE3Y", "bundle", range(1, 13)),
    _spec("BUNDLE4Y", "bundle", range(1, 17)),
    _spec("BUNDLE5Y", "bundle", range(1, 21)),
    _spec("SFR4", "outright", [4]),
    _spec("SFR8", "outright", [8]),
    _spec("SFR12", "outright", [12]),
    _spec("SFR16", "outright", [16]),
    _spec("SFR20", "outright", [20]),
)

_BY_LABEL: Dict[str, StructureSpec] = {s.label: s for s in STRUCTURES}


def structure_by_label(label: str) -> StructureSpec:
    try:
        return _BY_LABEL[label.upper()]
    except KeyError:
        raise KeyError(
            f"{label!r} is not a tradeable CA structure; expected one of "
            f"{sorted(_BY_LABEL)}") from None


def ca_col(curve: str, label: str) -> str:
    """The CA panel column for a structure — the TB's own naming, not a copy."""
    from TB.IRSwapsTB import _cvx_col_name

    return _cvx_col_name(curve, label.upper())


def contracts_for(label: str, as_of: datetime.date, *,
                  root: str = "SR3") -> List[str]:
    """Member futures symbols on *as_of*, via the TB's own rank→IMM map.

    Delegating to ``_cvx_imm_code_from_date_rank`` keeps the roll rule (roll ON
    the IMM date) in exactly one place; a second copy here would be an
    invisible divergence — both would return plausible codes.
    """
    from TB.IRSwapsTB import _cvx_imm_code_from_date_rank

    spec = structure_by_label(label)
    return [f"{root}{_cvx_imm_code_from_date_rank(as_of, r)}" for r in spec.ranks]


def swap_window(label: str, as_of: datetime.date) -> Tuple[datetime.date, datetime.date]:
    """The matched swap's (effective, maturity): IMM(first) → IMM after last.

    For a pack this is Citi's "3/18/20–3/17/21" window verbatim; for a bundle
    or an outright it is the same rule on that structure's own span — the
    reference quarters tile the window exactly, which is what makes the swap
    "matched-maturity".
    """
    import rateslib as rl

    from TB.IRSwapsTB import _cvx_imm_code_from_date_rank

    spec = structure_by_label(label)
    first = _cvx_imm_code_from_date_rank(as_of, spec.ranks[0])
    last = _cvx_imm_code_from_date_rank(as_of, spec.ranks[-1])
    eff = rl.get_imm(code=first).date()
    mat = rl.next_imm(rl.get_imm(code=last)).date()
    return eff, mat


def contracts_per_leg(label: str, ca_dv01: float = CA_DV01_DEFAULT) -> int:
    """``CA_DV01 = n_legs · contracts · $25`` inverted, integer-rounded."""
    spec = structure_by_label(label)
    return int(round(ca_dv01 / (spec.n_legs * DV01_PER_CONTRACT)))


# ---------------------------------------------------------------------------
# Flies
# ---------------------------------------------------------------------------
_ALL_FLIES: Dict[str, FlySpec] = {f.fly_id: f for f in fly_universe(
    shapes=FLY_SHAPES,
    forward_starts=(0.0, 1.0, 2.0, 3.0, 4.0, 5.0),
)}


def _fly_id(shape: str, start_y: float) -> str:
    """Reproduce ``strat2_fly_universe``'s id convention via the catalogue."""
    for fid, f in _ALL_FLIES.items():
        if f.shape == shape and f.forward_start_y == start_y:
            return fid
    raise KeyError(f"no fly {shape!r} @ start {start_y}")


def flies_for(spec: StructureSpec, *,
              shapes: Sequence[str] = FLY_SHAPE_NAMES) -> List[FlySpec]:
    """The declared fly set for one structure: each shape at spot AND at the
    structure's matched forward start. Order: spot shapes then matched."""
    out: List[FlySpec] = []
    for start in (0.0, spec.matched_start_y):
        for shape in shapes:
            out.append(_ALL_FLIES[_fly_id(shape, start)])
    return out


def tradeable_fly_specs(*, shapes: Sequence[str] = FLY_SHAPE_NAMES) -> List[FlySpec]:
    """Every distinct fly any declared cell can reference (for controls)."""
    seen: Dict[str, FlySpec] = {}
    for s in STRUCTURES:
        for f in flies_for(s, shapes=shapes):
            seen[f.fly_id] = f
    return [seen[k] for k in sorted(seen)]


def fly_leg_tenors(specs: Optional[Sequence[FlySpec]] = None) -> Tuple[str, ...]:
    """Distinct leg tenor tokens the declared flies need from the leg panel."""
    specs = list(specs) if specs is not None else tradeable_fly_specs()
    out: List[str] = []
    for f in specs:
        for start, tenor in ((f.forward_start_y, f.front_y),
                             (f.forward_start_y, f.belly_y),
                             (f.forward_start_y, f.back_y)):
            key = tenor_key(start, tenor)
            if key not in out:
                out.append(key)
    return tuple(out)

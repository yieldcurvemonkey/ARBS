r"""GV block — the CA / linear-proxy universe, the IMM roll calendar, time weights.

Frozen by ``docs/convexityrv/gv-preregistration.md`` BEFORE any scoring.
Everything here is a catalogue, a pure date computation, or arithmetic on an
already-built leg panel; nothing touches market data.

Three things live here that the block-3 vocabulary (``cavf_universe``) does not
express, and each one is a measured defect it was carrying:

1. **IMM-dated legs.** A CA structure label is CONSTANT RANK: at each quarterly
   roll it switches contracts and its level jumps (measured: BLUES +0.946 bp per
   roll, t=+2.70, 22 rolls 2021-2026).  A constant-maturity forward fly does not
   roll, so pairing the two leaves that jump unhedged.  An ``IMM_k`` leg rolls
   with the strip.

2. **The two roll clocks are one business day apart.**
   ``IRSwapsTB._cvx_front_imm_code`` advances the SR3 rank map ON the IMM date;
   ``Query.Base.imm_resolution.resolve_imm_token("IMM_1", d)`` searches from
   ``d + 1 day`` and therefore advances on the business day BEFORE.  Measured
   over 1,409 dates: 22 roll dates each, **zero in common**.  The blackout is
   the union of the two, which is why it is asymmetric around the IMM date.

3. **The quoted fly and curve conventions are 2x / 1x combinations, and the
   package DV01 that earns them is not the belly DV01.**  Pinned in
   :data:`FLY_CONVENTION` and :func:`leg_dv01_to_leg_notionals`, tied out to
   0.00000000 against the timeseries layer's own ``FLY RATE`` / ``CURVE RATE``
   columns in ``tests/test_convexity_rv_gv_universe.py``.

Units, stated once and never re-stated:

* panel par rates are **percent**; every quantity this module returns is **bp**;
* ``fly_bp = 2*belly - front - back`` (the ``FLY RATE`` column, exactly);
* ``curve_bp = back - front`` (the ``CURVE RATE`` column, exactly);
* a leg's size is carried as ``leg_dv01`` = **USD P&L per bp of the quoted
  combination**, never as a belly notional, because those differ by a factor of
  two for the fly and by one for the curve and mixing them is a silent 2x.
"""
from __future__ import annotations

import datetime
import functools
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "CA_DV01_DEFAULT",
    "CURVE",
    "FLY_CONVENTION",
    "CURVE_CONVENTION",
    "GVStructure",
    "LegSpec",
    "STRUCTURES",
    "LEGS",
    "PRIMARY_STRUCTURES",
    "SECONDARY_STRUCTURES",
    "EXCLUDED_STRUCTURES",
    "BLACKOUT_PRE_BD",
    "BLACKOUT_POST_BD",
    "ca_col",
    "structure_by_label",
    "matched_imm_rank",
    "leg_series",
    "leg_cost_dv01",
    "leg_dv01_to_leg_notionals",
    "contract_t1s",
    "time_weight_series",
    "ca_roll_dates",
    "leg_roll_dates",
    "blackout_mask",
    "roll_segments",
]

CURVE = "USD-SOFR-1D"
CA_DV01_DEFAULT = 100_000.0

#: ``FLY RATE`` = ``(2*belly - front - back) * 100``, tied out at max|diff| 0.0
#: on the 2026-07 probe panel.  The alternative ``belly - (front+back)/2`` form
#: (which ``strat2_fly_universe`` uses) is exactly half of it; block 3's betas
#: are therefore NOT directly comparable to a beta fitted against this column
#: without the factor of two, and that is why the convention is a named constant.
FLY_CONVENTION = "2*belly - front - back, bp"

#: ``CURVE RATE`` = ``(back - front) * 100``, tied out at max|diff| 0.0.
CURVE_CONVENTION = "back - front, bp"

#: Blackout half-widths in business days around each quarterly IMM date.  The
#: union of the two measured roll clocks is {IMM-1, IMM}; the extra buffer is
#: declared, not fitted, and swept only on finalists.
BLACKOUT_PRE_BD = 3
BLACKOUT_POST_BD = 1


# ---------------------------------------------------------------------------
# Structures (the CA / gamma side)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class GVStructure:
    label: str                 # the TB label -- the same string sfr_cvx_adj takes
    kind: str                  # "pack" | "bundle" | "outright"
    ranks: Tuple[int, ...]
    tier: str                  # "primary" | "secondary" | "excluded"
    exclusion_reason: str = ""

    @property
    def n_legs(self) -> int:
        return len(self.ranks)

    @property
    def front_rank(self) -> int:
        return self.ranks[0]

    @property
    def structure_tag(self) -> str:
        return "OUTRIGHT" if self.kind == "outright" else "PACKS"


def _pack(label: str, a: int, tier: str, reason: str = "") -> GVStructure:
    return GVStructure(label, "pack", tuple(range(a, a + 4)), tier, reason)


#: The measured reason WHITES/REDS/front outrights are out: AC1 of the daily CA
#: change is at or past the pure-noise bound of -0.5 (WHITES -0.540, REDS
#: -0.517), i.e. their daily marks carry no measurable signal.  See the
#: pre-registration section 0 / M2.
_NOISE = "AC1(dCA) at or past the -0.5 pure-noise bound (pre-reg M2)"

STRUCTURES: Dict[str, GVStructure] = {
    s.label: s for s in (
        _pack("WHITES", 1, "secondary", _NOISE),
        _pack("REDS", 5, "secondary", _NOISE),
        _pack("GREENS", 9, "primary"),
        _pack("BLUES", 13, "primary"),
        _pack("GOLDS", 17, "primary"),
        GVStructure("BUNDLE4Y", "bundle", tuple(range(1, 17)), "secondary"),
        GVStructure("BUNDLE5Y", "bundle", tuple(range(1, 21)), "secondary"),
        GVStructure("SFR12", "outright", (12,), "secondary"),
        GVStructure("SFR16", "outright", (16,), "secondary"),
        GVStructure("SFR20", "outright", (20,), "secondary"),
    )
}

PRIMARY_STRUCTURES: Tuple[str, ...] = tuple(
    k for k, v in STRUCTURES.items() if v.tier == "primary")
SECONDARY_STRUCTURES: Tuple[str, ...] = tuple(
    k for k, v in STRUCTURES.items() if v.tier == "secondary")
EXCLUDED_STRUCTURES: Tuple[str, ...] = tuple(
    k for k, v in STRUCTURES.items() if v.tier == "excluded")


def structure_by_label(label: str) -> GVStructure:
    try:
        return STRUCTURES[label.upper()]
    except KeyError as exc:                                    # noqa: PERF203
        raise KeyError(f"unknown GV structure {label!r}; "
                       f"declared: {sorted(STRUCTURES)}") from exc


def ca_col(label: str, curve: str = CURVE) -> str:
    """The CA panel column for a structure -- the TB's own naming, not a second
    scheme that can drift from it."""
    return f"{curve} {label.upper()} {structure_by_label(label).structure_tag} CVX_ADJ"


def matched_imm_rank(label: str) -> int:
    """The IMM rank a structure's *matched* forward leg starts at: its own front
    contract.  GREENS -> 9, BLUES -> 13, GOLDS -> 17, SFR20 -> 20, bundles -> 1.

    This is the IMM-space statement of the forward-start-matched-fly hypothesis
    ("vol at the structure's own expiry should hedge it better").  Block 3
    approximated it with a constant-maturity forward start rounded to the
    nearest year; here it is exact, and it rolls with the structure."""
    return structure_by_label(label).front_rank


# ---------------------------------------------------------------------------
# Legs (the vega / linear-proxy side)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LegSpec:
    leg_id: str
    kind: str                    # "fly" | "curve"
    start: str                   # "immF" | "imm2" | "immM" | "spot" | "fwd"
    tenors: Tuple[str, ...]      # 3 for a fly, 2 for a curve (front..back)
    why: str

    @property
    def n_legs(self) -> int:
        return len(self.tenors)


LEGS: Dict[str, LegSpec] = {
    s.leg_id: s for s in (
        LegSpec("immF_2s5s10s", "fly", "immF", ("2y", "5y", "10y"),
                "the brief's own regressor, verbatim"),
        LegSpec("imm2_2s5s10s", "fly", "imm2", ("2y", "5y", "10y"),
                "the brief's second regressor"),
        LegSpec("immM_2s5s10s", "fly", "immM", ("2y", "5y", "10y"),
                "vol-locality: the fly starts at the structure's own front IMM"),
        LegSpec("immM_1s2s3s", "fly", "immM", ("1y", "2y", "3y"),
                "the only fly shape with a measured R2 plateau in block 2"),
        LegSpec("le_10y10y_20y10y", "curve", "fwd", ("10Yx10Y", "20Yx10Y"),
                "the brief's ultra-long regressor (printed R2 0.505)"),
        LegSpec("le_10y10y_15y10y", "curve", "fwd", ("10Yx10Y", "15Yx10Y"),
                "the brief's tighter ultra-long sibling"),
        LegSpec("spot_2s5s10s", "fly", "spot", ("2Y", "5Y", "10Y"),
                "Citi's published shape -- the incumbent control"),
    )
}


def _leg_col(tenor: str, curve: str = CURVE) -> str:
    return f"{curve} {tenor} OUTRIGHT RATE"


def _resolved_tenors(spec: LegSpec, structure: Optional[str]) -> List[str]:
    """The panel tenor strings for one leg spec against one structure."""
    if spec.start == "spot" or spec.start == "fwd":
        return list(spec.tenors)
    if spec.start == "immF":
        k = 1
    elif spec.start == "imm2":
        k = 2
    elif spec.start == "immM":
        if structure is None:
            raise ValueError(f"{spec.leg_id} needs a structure to resolve immM")
        k = matched_imm_rank(structure)
    else:                                                       # pragma: no cover
        raise ValueError(f"unknown start {spec.start!r}")
    return [f"IMM_{k}x{t}" for t in spec.tenors]


def leg_series(panel: pd.DataFrame, leg_id: str,
               structure: Optional[str] = None,
               *, curve: str = CURVE) -> pd.Series:
    """The quoted combination in **bp**, from a wide panel of percent par rates.

    ``fly  -> (2*belly - front - back) * 100``  (the ``FLY RATE`` convention)
    ``curve -> (back - front) * 100``           (the ``CURVE RATE`` convention)
    """
    spec = LEGS[leg_id]
    tenors = _resolved_tenors(spec, structure)
    cols = [_leg_col(t, curve) for t in tenors]
    missing = [c for c in cols if c not in panel.columns]
    if missing:
        raise KeyError(f"{leg_id} (structure={structure}) needs {missing}")
    if spec.kind == "fly":
        f, b, k = (panel[c].astype(float) for c in cols)
        out = (2.0 * b - f - k) * 100.0
    elif spec.kind == "curve":
        f, b = (panel[c].astype(float) for c in cols)
        out = (b - f) * 100.0
    else:                                                       # pragma: no cover
        raise ValueError(f"unknown leg kind {spec.kind!r}")
    sid = leg_id if structure is None or spec.start != "immM" else f"{leg_id}[{structure}]"
    return out.rename(sid)


def leg_dv01_to_leg_notionals(leg_id: str, leg_dv01: float) -> List[float]:
    """Per-leg DV01s (front, belly, back) or (front, back) that earn ``leg_dv01``
    USD per bp of the QUOTED combination.

    Fly, quoted ``2b - f - k`` with DV01-neutral 50/50 wings::

        P&L = D_b*db - (D_b/2)*df - (D_b/2)*dk = (D_b/2) * d(fly)

    so ``D_b = 2*leg_dv01`` and each wing is ``-leg_dv01`` (opposite sign to the
    belly).  Curve, quoted ``back - front``::

        P&L = D*dback - D*dfront = D * d(curve)   ->   D = leg_dv01.

    Signs are returned relative to a LONG position in the quoted combination
    (long fly = receive belly / pay wings is the +ve convention here; the caller
    applies the trade side).
    """
    d = float(leg_dv01)
    if LEGS[leg_id].kind == "fly":
        return [-d, 2.0 * d, -d]
    return [-d, d]


def leg_cost_dv01(leg_id: str, leg_dv01: float) -> float:
    """Sum of |per-leg DV01| -- the base a per-leg round-trip cost is charged on.

    A fly quoted ``2b-f-k`` at ``leg_dv01`` per bp costs **4x** ``leg_dv01`` of
    charged DV01 (2 belly + 1 + 1 wings); a curve costs 2x.  Getting this wrong
    is a 2x error in the cost of exactly the leg this block resizes, so it is
    its own function with its own test.
    """
    return float(sum(abs(x) for x in leg_dv01_to_leg_notionals(leg_id, leg_dv01)))


# ---------------------------------------------------------------------------
# The IMM roll calendar and the time weights
# ---------------------------------------------------------------------------
@functools.lru_cache(maxsize=8192)
def _front_code(d: datetime.date) -> str:
    from TB.IRSwapsTB import _cvx_front_imm_code
    return _cvx_front_imm_code(d)


@functools.lru_cache(maxsize=65536)
def _rank_imm_date(d: datetime.date, rank: int) -> datetime.date:
    """The IMM date of the *rank*-th SR3 contract on *d*, via the CA path's own
    rank map -- so the time weights and the CA come from one contract set."""
    import rateslib as rl
    from TB.IRSwapsTB import _cvx_imm_code_from_date_rank
    code = _cvx_imm_code_from_date_rank(d, int(rank))
    dt_ = rl.get_imm(code=code)
    return dt_.date() if hasattr(dt_, "date") else dt_


def contract_t1s(as_of: datetime.date, label: str) -> List[float]:
    """``T1_i`` (ACT/365 to each member contract's IMM date) for a structure."""
    st = structure_by_label(label)
    return [max(0.0, (_rank_imm_date(as_of, r) - as_of).days / 365.0)
            for r in st.ranks]


def time_weight_series(dates: Sequence, label: str,
                       convention: str = "citi") -> pd.Series:
    """``w(t) = mean_i(T1_i^2)`` per date -- the Ho-Lee time weight of a structure.

    Per date, never ``T1_mean**2``: for GOLDS the two differ by 1.2%, which lands
    straight in the vega and therefore in the hedge ratio.
    """
    from RVUtils.ConvexityRV.holee import pack_time_weight
    idx = pd.DatetimeIndex(pd.to_datetime(list(dates)))
    vals = [pack_time_weight(contract_t1s(d.date(), label), convention=convention)
            for d in idx]
    return pd.Series(vals, index=idx, name=f"w_{label}")


def ca_roll_dates(dates: Sequence) -> List[pd.Timestamp]:
    """Dates on which the CA rank->contract map switches (the SR3 roll, ON the
    IMM date).  The first panel date is never a roll."""
    idx = pd.DatetimeIndex(pd.to_datetime(list(dates))).sort_values()
    codes = pd.Series([_front_code(d.date()) for d in idx], index=idx)
    changed = codes.ne(codes.shift())
    changed.iloc[0] = False
    return list(idx[changed])


def leg_roll_dates(dates: Sequence) -> List[pd.Timestamp]:
    """Dates on which an ``IMM_k`` swap leg switches its effective date (the
    business day BEFORE the IMM date -- ``resolve_imm_token`` searches from
    ``d + 1 day``)."""
    from Query.Base.imm_resolution import resolve_imm_token
    idx = pd.DatetimeIndex(pd.to_datetime(list(dates))).sort_values()
    eff = pd.Series([resolve_imm_token("IMM_1", d.date()) for d in idx], index=idx)
    changed = eff.ne(eff.shift())
    changed.iloc[0] = False
    return list(idx[changed])


def blackout_mask(dates: Sequence, *, pre_bd: int = BLACKOUT_PRE_BD,
                  post_bd: int = BLACKOUT_POST_BD) -> pd.Series:
    """``True`` where NO position may be open.

    Covers ``[roll - pre_bd, roll + post_bd]`` in panel business days around the
    union of the CA roll dates and the ``IMM_k`` leg roll dates.  Taking the
    union rather than either clock is the point: the two are one business day
    apart and a blackout on one leaves the other jumping unhedged.
    """
    idx = pd.DatetimeIndex(pd.to_datetime(list(dates))).sort_values()
    mask = pd.Series(False, index=idx)
    pos = {d: i for i, d in enumerate(idx)}
    n = len(idx)
    for d in set(ca_roll_dates(idx)) | set(leg_roll_dates(idx)):
        i = pos.get(d)
        if i is None:
            continue
        lo = max(0, i - int(pre_bd))
        hi = min(n - 1, i + int(post_bd))
        mask.iloc[lo:hi + 1] = True
    return mask


def roll_segments(dates: Sequence, *, pre_bd: int = BLACKOUT_PRE_BD,
                  post_bd: int = BLACKOUT_POST_BD
                  ) -> List[Tuple[pd.Timestamp, pd.Timestamp]]:
    """The tradeable windows between blackouts, as inclusive (first, last) pairs.

    A position may open and must close inside one segment; there is no such
    thing as a position that survives a roll in this block.
    """
    m = blackout_mask(dates, pre_bd=pre_bd, post_bd=post_bd)
    free = m.index[~m.to_numpy()]
    if len(free) == 0:
        return []
    # a segment breaks wherever consecutive free dates are not adjacent in the
    # panel; positional adjacency, not calendar adjacency, is the right test
    # because the panel is the trading grid.
    pos = pd.Series(range(len(m)), index=m.index).loc[free].to_numpy()
    brk = np.flatnonzero(np.diff(pos) != 1)
    starts = np.concatenate([[0], brk + 1])
    ends = np.concatenate([brk, [len(free) - 1]])
    return [(free[a], free[b]) for a, b in zip(starts, ends)]

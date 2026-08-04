"""The outcome map: count cells priced by the surface and by the lattice.

For a quarterly SR3 option every resolved-by-expiry meeting has day-weight 1, so
the orderings collapse to the total move COUNT and the identified object is a
set of atoms on a 25bp grid around the forward. Each atom is a *cell*; each cell
is priced twice — by the listed 25bp butterfly centred on it, and by the same
butterfly under the ZQ/swap lattice with its unresolved-meeting smear.

The richness map ``r_i = market_i - fair_i`` is then split, per contract-day, on
the signed cell distance ``d_i = (atom_rate_i - forward) / 0.25``:

    r_i = a + b*d_i + c*d_i^2 + e_i        (weighted by the lattice mass p_i)

* ``a``, ``c`` (even) — the standing dispersion / off-lattice premium. Probability
  conservation makes the modal deficit identically the wing surplus: ONE price,
  measured fairly-priced in both directions by the linvol grid and family B.
* ``b`` (odd) — the TILT. Both the mean (parity) and the total mass are pinned,
  so an on-lattice tilt is compensated off-lattice: the surface is saying the
  priced path sits somewhere the lattice does not put it. That is the one
  component a linear market also prices, and the one a linear hedge is for.
* ``e_i`` — local per-cell disagreement.

The fit is weighted by the lattice cell mass ``p_i`` for two reasons, one
structural and one practical. Structural: mean-pinning gives ``sum_i p_i d_i =
0`` exactly, so under that measure the constant and the tilt are ORTHOGONAL and
"even" and "odd" mean what they say — under a flat weighting an atom grid that
happens to straddle the forward asymmetrically manufactures a tilt out of a
perfectly symmetric smile. Practical: a wing cell carrying 0.1% of the lattice
mass has a noisy, kernel-contaminated richness and must not set the tilt.

What gets traded is the **odd part** ``o_i = r_i - (a + c*d_i^2)`` — the fitted
tilt plus whatever local asymmetry survives it — never the raw richness, which
is dominated by the standing premium.

Nothing here touches the network: the map is built from arrays plus a
``mark_fn`` callback, so every path is testable on planted numbers.
"""
from __future__ import annotations

import dataclasses
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from RVUtils.OutcomeMap.structures import FLY_WING, fly_legs, package_mark

__all__ = ["Cell", "CellMap", "distinct_atoms", "snap_center", "decompose",
           "build_cell_map", "pair_raw_signal", "pair_odd_signal",
           "map_full_weights"]

MarkFn = Callable[[str, float], float]


@dataclasses.dataclass(frozen=True)
class Cell:
    """One count cell of the outcome map."""

    atom_rate: float          # percent
    p_lattice: float          # lattice mass on this atom (pre-smear)
    center_px: float          # listed strike the butterfly is centred on
    offset_bp: float          # (100 - atom_rate) - center_px, in bp
    d: float                  # signed distance from the forward, in 25bp cells
    mkt_bp: float             # listed butterfly premium
    fair_bp: float            # lattice-fair butterfly premium

    @property
    def rich_bp(self) -> float:
        return self.mkt_bp - self.fair_bp

    @property
    def p_opt(self) -> float:
        """Kernel-read option probability of the cell (premium / 25bp)."""
        return self.mkt_bp / (FLY_WING * 100.0)

    @property
    def p_fair(self) -> float:
        return self.fair_bp / (FLY_WING * 100.0)

    def legs(self, weight: float = 1.0):
        return fly_legs(self.center_px, weight=weight)


@dataclasses.dataclass
class CellMap:
    """One (as_of, symbol) outcome map plus its even/odd decomposition."""

    symbol: str
    as_of: object
    forward_rate: float
    smear_bp: float
    n_resolved: int
    cells: Tuple[Cell, ...]
    a: float                  # level (even)
    b: float                  # tilt  (odd)
    c: float                  # curvature (even)
    resid: Tuple[float, ...]  # r_i - (a + b d + c d^2)

    # -- vectors -----------------------------------------------------------
    @property
    def d(self) -> np.ndarray:
        return np.array([x.d for x in self.cells], dtype=float)

    @property
    def rich(self) -> np.ndarray:
        return np.array([x.rich_bp for x in self.cells], dtype=float)

    @property
    def p_lattice(self) -> np.ndarray:
        return np.array([x.p_lattice for x in self.cells], dtype=float)

    @property
    def tilt(self) -> np.ndarray:
        """The fitted tilt contribution per cell (the pure odd basis term)."""
        return self.b * self.d

    @property
    def even_fit(self) -> np.ndarray:
        """The fitted standing premium: level plus curvature."""
        return self.a + self.c * self.d ** 2

    @property
    def odd(self) -> np.ndarray:
        """Richness with the standing (even) premium projected out."""
        return self.rich - self.even_fit

    @property
    def n_cells(self) -> int:
        return len(self.cells)

    # -- conservation ------------------------------------------------------
    @property
    def p_opt_sum(self) -> float:
        return float(sum(x.p_opt for x in self.cells))

    @property
    def p_fair_sum(self) -> float:
        return float(sum(x.p_fair for x in self.cells))

    @property
    def off_lattice_premium(self) -> float:
        """Kernel-read mass the surface holds OUTSIDE the on-lattice cells.

        The butterfly kernels are a partition of unity only in the interior, so
        this is a like-for-like comparison (both sides read through the same
        kernels), not an absolute tail measurement.
        """
        return self.p_fair_sum - self.p_opt_sum


def distinct_atoms(rates: Sequence[float], probs: Sequence[float],
                   *, merge_bp: float = 1.0) -> Tuple[np.ndarray, np.ndarray]:
    """Collapse the raw combination grid onto distinct atoms.

    ``AtomEngine.rates_probs`` returns one row per outcome COMBINATION; for
    weight-1 meetings many combinations land on the same displacement (that IS
    exchangeability). Cells are the distinct rates.
    """
    r = np.asarray(rates, dtype=float)
    p = np.asarray(probs, dtype=float)
    step = merge_bp / 100.0
    key = np.round(r / step) * step
    uniq = np.unique(key)
    out_p = np.array([p[key == k].sum() for k in uniq], dtype=float)
    return uniq, out_p


def snap_center(center_px: float, strikes: Sequence[float],
                *, wing: float = FLY_WING,
                max_offset: float = 0.125) -> Optional[float]:
    """Nearest listed strike whose butterfly wings are also listed.

    Returns None when no candidate within ``max_offset`` price points has both
    wings — the cell is then unmarkable and is dropped rather than synthesised.
    """
    ks = np.asarray(sorted(set(round(float(k), 6) for k in strikes)), dtype=float)
    if ks.size == 0:
        return None
    have = set(ks.tolist())
    cand = ks[np.abs(ks - center_px) <= max_offset + 1e-9]
    order = np.argsort(np.abs(cand - center_px))
    for k in cand[order]:
        if round(k - wing, 6) in have and round(k + wing, 6) in have:
            return float(round(k, 6))
    return None


def decompose(d: Sequence[float], r: Sequence[float],
              w: Optional[Sequence[float]] = None
              ) -> Tuple[float, float, float, np.ndarray]:
    """Mass-weighted LS of the richness map on {1, d, d^2}; degrades gracefully.

    ``w`` defaults to a flat weighting; callers pass the lattice cell masses, in
    which case ``sum w_i d_i = 0`` (mean-pinning) makes the constant and the
    tilt orthogonal. With fewer cells than basis functions the higher terms are
    dropped rather than fitted to noise (3 cells: exact fit, zero residual — the
    local-residual reading is gated on ``n_cells >= 4`` by the caller).
    """
    dd = np.asarray(d, dtype=float)
    rr = np.asarray(r, dtype=float)
    n = dd.size
    if n == 0:
        return 0.0, 0.0, 0.0, np.zeros(0)
    if n == 1:
        return float(rr[0]), 0.0, 0.0, np.zeros(1)
    ww = np.ones(n) if w is None else np.asarray(w, dtype=float)
    ww = np.where(np.isfinite(ww) & (ww > 0), ww, 0.0)
    if ww.sum() <= 0:
        ww = np.ones(n)
    cols = [np.ones(n), dd] + ([dd ** 2] if n >= 3 else [])
    X = np.column_stack(cols)
    sw = np.sqrt(ww)[:, None]
    beta, *_ = np.linalg.lstsq(X * sw, rr * sw[:, 0], rcond=None)
    a = float(beta[0])
    b = float(beta[1])
    c = float(beta[2]) if len(beta) > 2 else 0.0
    resid = rr - X @ beta
    return a, b, c, resid


def build_cell_map(
    symbol: str,
    as_of,
    forward_rate: float,
    rates: Sequence[float],
    probs: Sequence[float],
    smear_bp: float,
    strikes: Sequence[float],
    mark_fn: MarkFn,
    fair_fn: Callable[[Sequence[Tuple[str, float, float]]], float],
    *,
    n_resolved: int = 0,
    merge_bp: float = 1.0,
    max_offset: float = 0.125,
    min_cells: int = 3,
) -> Optional[CellMap]:
    """Build the outcome map for one (as_of, symbol).

    ``mark_fn(right, strike) -> listed premium bp`` (parity-completed surface);
    ``fair_fn(legs) -> lattice-fair premium bp`` on the SAME legs, so richness is
    market-vs-tree on an identical package rather than on an idealised one.
    Cells whose butterfly cannot be assembled from listed strikes are dropped.
    """
    ar, ap = distinct_atoms(rates, probs, merge_bp=merge_bp)
    cells: List[Cell] = []
    used: set = set()
    for rate, p in zip(ar, ap):
        target = 100.0 - float(rate)
        c_px = snap_center(target, strikes, max_offset=max_offset)
        if c_px is None or c_px in used:
            continue
        legs = fly_legs(c_px)
        mk = package_mark(legs, mark_fn)
        if not np.isfinite(mk):
            continue
        fair = float(fair_fn(legs))
        if not np.isfinite(fair):
            continue
        used.add(c_px)
        cells.append(Cell(
            atom_rate=float(rate), p_lattice=float(p), center_px=float(c_px),
            offset_bp=float((target - c_px) * 100.0),
            d=float((rate - forward_rate) / FLY_WING),
            mkt_bp=float(mk), fair_bp=fair,
        ))
    if len(cells) < min_cells:
        return None
    cells.sort(key=lambda x: x.atom_rate)
    a, b, c, resid = decompose([x.d for x in cells], [x.rich_bp for x in cells],
                               [x.p_lattice for x in cells])
    return CellMap(symbol=symbol, as_of=as_of, forward_rate=float(forward_rate),
                   smear_bp=float(smear_bp), n_resolved=int(n_resolved),
                   cells=tuple(cells), a=a, b=b, c=c,
                   resid=tuple(float(v) for v in resid))


# ---------------------------------------------------------------------------
# Signals: which cells to trade, and how strong the disagreement is
# ---------------------------------------------------------------------------

#: cells carrying less lattice mass than this are measured but never traded —
#: their butterfly is a few ticks wide and its richness is kernel noise
P_FLOOR = 0.01


def _tradeable(cm: CellMap, p_floor: float) -> np.ndarray:
    return np.array([x.p_lattice >= p_floor for x in cm.cells], dtype=bool)


def _extremes(vals: np.ndarray, ok: np.ndarray) -> Optional[Tuple[int, int]]:
    idx = np.flatnonzero(ok)
    if idx.size < 2:
        return None
    i_long = int(idx[np.argmin(vals[idx])])
    i_short = int(idx[np.argmax(vals[idx])])
    if i_long == i_short:
        return None
    return i_long, i_short


def pair_raw_signal(cm: CellMap, *, p_floor: float = P_FLOOR
                    ) -> Optional[Dict[str, object]]:
    """Long the cheapest cell, short the richest, on RAW richness.

    The control expression. With the standing premium left in, "cheapest" is
    normally the modal cell and "richest" a wing, so this should reproduce the
    already-dead short-dispersion trade — if the even/odd split buys nothing,
    ``pair_odd`` will not separate from this row.
    """
    if cm.n_cells < 2:
        return None
    r = cm.rich
    pick = _extremes(r, _tradeable(cm, p_floor))
    if pick is None:
        return None
    i_long, i_short = pick
    return {"i_long": i_long, "i_short": i_short,
            "strength_bp": float(r[i_short] - r[i_long]),
            "kind": "pair_raw"}


def pair_odd_signal(cm: CellMap, *, p_floor: float = P_FLOOR
                    ) -> Optional[Dict[str, object]]:
    """Long the cheapest cell, short the richest, on the ODD component.

    ``o_i = r_i - (a + c d_i^2)`` strips the standing dispersion premium — the
    part probability conservation says is one price, and that both the linvol
    grid and family B measured as fairly-priced insurance — and leaves the
    asymmetry: the surface putting on-lattice mass where the lattice does not.
    The resulting package is a count-space risk reversal, directional by
    construction, which is precisely what a linear hedge leg is for.
    """
    if cm.n_cells < 3 or not np.isfinite(cm.b):
        return None
    o = cm.odd
    pick = _extremes(o, _tradeable(cm, p_floor))
    if pick is None:
        return None
    i_long, i_short = pick
    return {"i_long": i_long, "i_short": i_short,
            "strength_bp": float(o[i_short] - o[i_long]),
            "tilt_bp_per_cell": float(cm.b), "kind": "pair_odd"}


def map_full_weights(cm: CellMap, *, p_floor: float = P_FLOOR
                     ) -> Optional[Dict[str, object]]:
    """Sell every odd-rich cell and buy every odd-cheap cell, gap-proportional.

    The distribution-arbitrage book on the odd component: weights are the
    mass-demeaned odd richness, normalised to ``sum|w| = 2`` — the same gross
    size as a pair — and handed to :func:`telescope` downstream, where adjacent
    butterflies collapse into the SECOND DIFFERENCE of the weight vector, which
    is what makes a whole-map book affordable at all.
    """
    if cm.n_cells < 3:
        return None
    ok = _tradeable(cm, p_floor)
    if ok.sum() < 3:
        return None
    o = np.where(ok, cm.odd, 0.0)
    p = np.where(ok, cm.p_lattice, 0.0)
    mean = float((o * p).sum() / p.sum()) if p.sum() > 0 else float(o.mean())
    dev = np.where(ok, o - mean, 0.0)
    s = np.abs(dev).sum()
    if s <= 1e-12:
        return None
    w = -2.0 * dev / s                              # long cheap, short rich
    return {"weights": w, "strength_bp": float(np.abs(dev).sum() / ok.sum()),
            "kind": "map_full"}

"""Mapping a risk weighting back to SR3 contracts, and what that costs.

Every SR3 contract has exactly the same DV01 -- **$25 per bp of its own rate** --
which makes the futures case much cleaner than swaps, and makes one fact
decisive:

    for a package with rate-exposure weights ``w`` (in contracts),
        DV01      = $25 per bp of the spread ``S = sum(w_i * r_i)``, ALWAYS
        contracts = sum(|w_i|)
        round trip= sum(|w_i|) * 2 * half_spread_$  =  sum(|w_i|) * 0.5 bp of S
                    (at a 0.25bp / $6.25 half-spread per contract)

The DV01 per bp of the spread does not depend on ``w`` at all, while the cost
does. So the **cost of a package, measured in bp of its own spread, is just its
contract count times 0.5bp**, and the only way to trade a fly more cheaply is to
trade fewer contracts.

Two consequences that drive everything downstream:

1. A level-neutral 3-leg package has its wings summing to its belly, so
   ``sum(|w|) = 2 * belly`` and the cost in bp of the spread is exactly the
   belly size. The spread also scales with the belly, so **cost measured in
   spread sigmas is invariant to package scale** -- you cannot make a fly
   cheaper by trading it bigger or smaller.
2. ``(1, -2, 1)`` is the **cheapest possible** level-neutral 3-leg package: 4
   contracts. Any tilt away from equal wings needs a larger integer belly to
   express (a 0.43/0.57 tilt needs a belly of 7, so 14 contracts), and the
   penalty is paid in cost per unit of spread volatility.

Costs here are per **contract**, not per leg. The earlier lab charged 0.25bp per
*leg* one-way, i.e. 1.5bp round trip on a fly; the belly is two contracts and
you cross the spread on both, so the correct figure is **2.0bp**.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "SR3_DV01_USD", "SR3_HALF_SPREAD_BP", "SR3_TICK_BP",
    "PackageWeights", "package_cost_bp", "package_cost_usd", "package_contracts",
    "package_dv01_usd", "spread_from_weights", "integer_weight_frontier",
    "best_integer_weights", "FLY_WEIGHTS_CONTRACTS",
]

#: DV01 of one SR3 contract, in dollars per bp of its own rate.
SR3_DV01_USD = 25.0

#: Minimum tick, in bp of rate. 0.005 price points outside the final four
#: months (0.0025 inside), and the market is typically one tick wide.
SR3_TICK_BP = 0.5

#: Cost of crossing, per contract, one way: half a tick.
SR3_HALF_SPREAD_BP = 0.25

#: The conventional butterfly, as rate-exposure contract counts.
FLY_WEIGHTS_CONTRACTS: Tuple[int, int, int] = (-1, 2, -1)


@dataclasses.dataclass(frozen=True)
class PackageWeights:
    """A tradeable package as integer contract counts per leg.

    ``w`` is rate exposure: ``w_i > 0`` means the position gains when leg ``i``'s
    rate rises, i.e. the position is **short** that many futures contracts. The
    spread is ``S = sum(w_i * r_i)`` in bp and the package makes ``$25 per bp of
    S`` regardless of the weights.
    """

    w: Tuple[float, ...]
    label: str = ""

    @property
    def contracts(self) -> float:
        return float(np.abs(np.asarray(self.w, dtype=float)).sum())

    @property
    def net_exposure(self) -> float:
        """Sum of the rate weights. Zero = level-neutral; non-zero leaks direction."""
        return float(np.asarray(self.w, dtype=float).sum())

    @property
    def belly(self) -> float:
        a = np.abs(np.asarray(self.w, dtype=float))
        return float(a.max())

    @property
    def wing_split(self) -> Tuple[float, float]:
        """The two wings as fractions of the belly (0.5/0.5 for a plain fly)."""
        a = np.asarray(self.w, dtype=float)
        b = self.belly
        if b <= 0:
            return (np.nan, np.nan)
        return (abs(a[0]) / b, abs(a[-1]) / b)

    def cost_bp(self, half_spread_bp: float = SR3_HALF_SPREAD_BP) -> float:
        return package_cost_bp(self.w, half_spread_bp=half_spread_bp)

    def cost_usd(self, half_spread_bp: float = SR3_HALF_SPREAD_BP) -> float:
        return package_cost_usd(self.w, half_spread_bp=half_spread_bp)

    def __str__(self) -> str:
        core = "/".join(f"{v:+g}" for v in self.w)
        return f"{self.label or core} [{core}] {self.contracts:g}c"


def package_contracts(w: Sequence[float]) -> float:
    """Total contracts traded to establish the package."""
    return float(np.abs(np.asarray(w, dtype=float)).sum())


def package_dv01_usd(w: Sequence[float]) -> float:
    """Dollars per bp of the package's own spread.

    Always ``SR3_DV01_USD``: the spread is a weighted sum of rates and each
    contract delivers $25 per bp of its own rate, so the weights cancel. This
    function exists to make that explicit rather than surprising.
    """
    return SR3_DV01_USD


def package_cost_usd(w: Sequence[float],
                     half_spread_bp: float = SR3_HALF_SPREAD_BP) -> float:
    """Round-trip cost in dollars: contracts x 2 sides x half-spread x $25/bp."""
    return (package_contracts(w) * 2.0 * float(half_spread_bp) * SR3_DV01_USD)


def package_cost_bp(w: Sequence[float],
                    half_spread_bp: float = SR3_HALF_SPREAD_BP) -> float:
    """Round-trip cost in **bp of the package's own spread**.

    ``contracts * 2 * half_spread``. For ``(1, -2, 1)`` at a 0.25bp half-spread
    that is ``4 * 2 * 0.25 = 2.0bp`` -- not the 1.5bp a per-*leg* charge gives.
    """
    return package_contracts(w) * 2.0 * float(half_spread_bp)


def spread_from_weights(legs: pd.DataFrame, w: Sequence[float], *,
                        scale: float = 100.0) -> pd.Series:
    """``S = sum(w_i * r_i)`` in bp, from leg rates in percent."""
    a = np.asarray(w, dtype=float)
    if legs.shape[1] != a.size:
        raise ValueError(f"{legs.shape[1]} legs but {a.size} weights")
    return (legs.to_numpy(dtype=float) @ a) * float(scale) * pd.Series(
        1.0, index=legs.index)


def integer_weight_frontier(
    beta_front: float, beta_back: float, *, max_belly: int = 24,
    level_neutral: bool = True, half_spread_bp: float = SR3_HALF_SPREAD_BP,
) -> pd.DataFrame:
    """All integer packages approximating a fitted wing split, by contract count.

    ``beta_front``/``beta_back`` are the fitted wing loadings on a belly of 1
    (a plain fly is 0.5/0.5). Returns one row per candidate belly with the best
    integer wings for that belly, the resulting wing split, the fidelity error,
    the contract count and the round-trip cost in bp of the spread.

    This is the trade-off the desk actually faces: **fidelity to the fitted
    vector costs contracts, and contracts are the only thing that costs money.**
    With ``level_neutral=True`` the wings are forced to sum to the belly, which
    keeps the package free of outright direction.
    """
    s = float(beta_front) + float(beta_back)
    if not np.isfinite(s) or abs(s) < 1e-9:
        return pd.DataFrame()
    tf = float(beta_front) / s          # target front share of the belly
    rows = []
    for b in range(2, int(max_belly) + 1):
        best = None
        for nf in range(1, b):
            nk = b - nf if level_neutral else nf  # level-neutral: wings sum to belly
            if nk < 1:
                continue
            err = abs(nf / b - tf)
            if best is None or err < best[0]:
                best = (err, nf, nk)
        if best is None:
            continue
        err, nf, nk = best
        w = (-float(nf), float(b), -float(nk))
        rows.append({
            "belly": b, "n_front": nf, "n_back": nk,
            "weights": w,
            "contracts": package_contracts(w),
            "front_share": nf / b, "back_share": nk / b,
            "target_front_share": tf,
            "wing_error": err,
            "cost_bp_of_spread": package_cost_bp(w, half_spread_bp),
            "cost_usd": package_cost_usd(w, half_spread_bp),
            "net_exposure": float(sum(w)),
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    # the frontier: only bellies that strictly improve on every smaller belly
    out = out.sort_values("belly").reset_index(drop=True)
    out["is_frontier"] = out["wing_error"] < out["wing_error"].cummin().shift(1).fillna(np.inf)
    out.loc[0, "is_frontier"] = True
    return out


def best_integer_weights(
    beta_front: float, beta_back: float, *, max_belly: int = 24,
    tol: float = 0.01, level_neutral: bool = True,
) -> Optional[PackageWeights]:
    """Smallest integer package whose wing split is within ``tol`` of the fit.

    Returns None if no belly up to ``max_belly`` gets close enough. ``tol`` is an
    absolute error on the front wing's share of the belly, so ``tol=0.01`` means
    "within one percentage point of the fitted 0.43".
    """
    fr = integer_weight_frontier(beta_front, beta_back, max_belly=max_belly,
                                 level_neutral=level_neutral)
    if fr.empty:
        return None
    ok = fr[fr["wing_error"] <= float(tol)]
    if ok.empty:
        return None
    r = ok.iloc[0]
    return PackageWeights(w=tuple(r["weights"]),
                          label=f"{int(r['n_front'])}/-{int(r['belly'])}/{int(r['n_back'])}")

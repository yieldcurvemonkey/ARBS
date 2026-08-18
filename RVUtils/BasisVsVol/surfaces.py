"""Daily normal-vol surfaces for the two legs, queryable at arbitrary (tte, strike offset).

A backtest cannot use the stored constant-maturity slots directly. A position opened as a 3M
option is a 2M option a month later, and the ``3M`` column on that later date is a different
instrument. So each day is turned into a small surface that can be asked for the vol at the
position's *remaining* time to expiry and its *current* moneyness.

Construction, per (date, leg key):

* **term structure** -- the available expiry nodes are interpolated linearly in total variance
  ``w = sigma^2 * T``, which is the additive quantity. Vol is held flat outside the node range.
* **skew** -- the smile is carried as a spread to that node's ATM, in strike-offset space, taken
  from the nearest expiry node in log-tte. So
  ``sigma(T, x) = sigma_atm(T) + [sigma_node(x) - sigma_node(0)]``.
  This is "sticky skew in bp offset": the shape rides with the forward, only the level moves with
  the term structure. It is an approximation, and it is the honest one available from a three-node
  term structure -- interpolating the whole smile across expiries would invent a term structure of
  skew that the data does not contain.

Offset sign convention on **both** legs: positive ``offset_bps`` means a strike at a HIGHER rate
than the forward. On the futures-option leg that is a put on price; on the swaption leg a payer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .voldata import VolData, vol_term_structure_interp

__all__ = ["SurfaceNode", "DailySurface", "SurfaceBook", "build_ustf_surfaces",
           "build_swaption_surfaces"]


@dataclass(frozen=True)
class SurfaceNode:
    tte: float
    atm_vol: float
    offsets: np.ndarray  # signed bp offsets, sorted
    vols: np.ndarray  # vol at each offset


@dataclass
class DailySurface:
    """One leg, one date. ``forward`` is in bp; ``dv01_per_unit`` is leg-specific metadata."""

    date: pd.Timestamp
    key: str
    forward_bp: float
    nodes: list[SurfaceNode] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def _node_tte(self) -> np.ndarray:
        return np.array([n.tte for n in self.nodes], float)

    @property
    def min_node_tte(self) -> float:
        """Shortest expiry actually quoted. Below this the surface is extrapolated, not observed."""
        t = self._node_tte()
        t = t[np.isfinite(t) & (t > 0)]
        return float(t.min()) if t.size else float("nan")

    def atm_vol(self, tte: float) -> float:
        return vol_term_structure_interp(
            self._node_tte(), np.array([n.atm_vol for n in self.nodes], float), tte
        )

    def _nearest_node(self, tte: float) -> SurfaceNode | None:
        if not self.nodes:
            return None
        t = np.array([n.tte for n in self.nodes], float)
        t = np.where(t > 0, t, np.nan)
        if np.all(~np.isfinite(t)) or not np.isfinite(tte) or tte <= 0:
            return self.nodes[0]
        return self.nodes[int(np.nanargmin(np.abs(np.log(t) - np.log(tte))))]

    def skew(self, tte: float, offset_bps: float) -> float:
        """Vol spread to ATM at ``offset_bps``, taken from the nearest expiry node."""
        n = self._nearest_node(tte)
        if n is None or n.offsets.size == 0 or not np.isfinite(offset_bps):
            return 0.0
        at_x = float(np.interp(float(offset_bps), n.offsets, n.vols))
        at_0 = float(np.interp(0.0, n.offsets, n.vols))
        return at_x - at_0

    def vol(self, tte: float, offset_bps: float = 0.0) -> float:
        """Normal vol in bp at remaining time ``tte`` (years) and signed strike offset (bp)."""
        a = self.atm_vol(tte)
        if not np.isfinite(a):
            return float("nan")
        return a + self.skew(tte, offset_bps)


def _collapse(offsets: np.ndarray, vols: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ok = np.isfinite(offsets) & np.isfinite(vols)
    offsets, vols = offsets[ok], vols[ok]
    if offsets.size == 0:
        return offsets, vols
    x_u = np.unique(offsets)
    y_u = np.array([vols[offsets == xv].mean() for xv in x_u])
    return x_u, y_u


def build_ustf_surfaces(vd: VolData, product: str) -> dict[pd.Timestamp, DailySurface]:
    """One surface per date for a futures-option leg.

    The smile comes from ``smile_points`` (delta-based, correct) rather than from
    ``strike_offset_otm_vols``, which is corrupt for this leg -- see :mod:`voldata`.
    """
    u = vd.ustf[vd.ustf["product"] == product]
    sm = vd.ustf_smile[vd.ustf_smile["product"] == product]
    sm_by = {k: g for k, g in sm.groupby(["as_of_date", "expiry_label"], sort=False)}

    out: dict[pd.Timestamp, DailySurface] = {}
    for date, g in u.groupby("as_of_date", sort=True):
        g = g.sort_values("time_to_expiry")
        fwd_bp = float(g["forward_yield"].iloc[0]) * 100.0
        nodes = []
        for r in g.itertuples(index=False):
            sub = sm_by.get((date, r.expiry_label))
            if sub is None or sub.empty:
                offs, vols = np.array([0.0]), np.array([float(r.atm_nvol_bps)])
            else:
                offs, vols = _collapse(
                    sub["yield_offset_bps"].to_numpy(float), sub["iv_normal_bps"].to_numpy(float)
                )
                if offs.size == 0:
                    offs, vols = np.array([0.0]), np.array([float(r.atm_nvol_bps)])
            nodes.append(SurfaceNode(float(r.time_to_expiry), float(r.atm_nvol_bps), offs, vols))
        if not nodes:
            continue
        row0 = g.iloc[0]
        out[date] = DailySurface(
            date=date,
            key=product,
            forward_bp=fwd_bp,
            nodes=nodes,
            meta={
                "fv01": float(row0["fv01"]),
                "forward_price": float(row0["forward_price"]),
                "underlying_contract": row0["underlying_contract"],
                "is_roll": bool(row0.get("is_roll", False)),
            },
        )
    return out


def build_swaption_surfaces(vd: VolData, tail: str) -> dict[pd.Timestamp, DailySurface]:
    """One surface per date for a swaption tail. Offsets come from the (correct) stored payload."""
    from .voldata import expand_swaption_offsets

    s = vd.swpt[vd.swpt["tail_label"] == tail].copy()
    off = expand_swaption_offsets(s)
    off_by = {k: g for k, g in off.groupby(["as_of_date", "expiry_label"], sort=False)}

    out: dict[pd.Timestamp, DailySurface] = {}
    for date, g in s.groupby("as_of_date", sort=True):
        g = g.sort_values("expiry_time")
        g = g[np.isfinite(g["atm_nvol_bps"].astype(float)) & (g["atm_nvol_bps"].astype(float) > 0)]
        if g.empty:
            continue
        fwd_bp = float(g["atmf_rate"].iloc[0]) * 10_000.0
        nodes = []
        for r in g.itertuples(index=False):
            sub = off_by.get((date, r.expiry_label))
            atm = float(r.atm_nvol_bps)
            if sub is None or sub.empty:
                offs, vols = np.array([0.0]), np.array([atm])
            else:
                x = np.concatenate([sub["signed_offset_bps"].to_numpy(float), [0.0]])
                y = np.concatenate([sub["vol_bps"].to_numpy(float), [atm]])
                offs, vols = _collapse(x, y)
            nodes.append(SurfaceNode(float(r.expiry_time), atm, offs, vols))
        out[date] = DailySurface(
            date=date, key=tail, forward_bp=fwd_bp, nodes=nodes,
            meta={"atmf_rate": float(g["atmf_rate"].iloc[0])},
        )
    return out


class SurfaceBook:
    """Memoised surface builder.

    Surface construction dominates the cost of a single backtest, and a grid search re-runs the
    same product/tail hundreds of times. Building once and reusing turns an overnight grid into a
    few minutes, and -- more importantly -- guarantees every cell of the grid sees byte-identical
    inputs, so a difference between cells is a difference in the configuration and nothing else.
    """

    def __init__(self, vd: VolData):
        self.vd = vd
        self._u: dict[str, dict] = {}
        self._s: dict[str, dict] = {}

    def ustf(self, product: str) -> dict:
        if product not in self._u:
            self._u[product] = build_ustf_surfaces(self.vd, product)
        return self._u[product]

    def swpt(self, tail: str) -> dict:
        if tail not in self._s:
            self._s[tail] = build_swaption_surfaces(self.vd, tail)
        return self._s[tail]

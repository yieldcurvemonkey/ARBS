"""Panels, marks and placebos for the outcome-map RV study.

Everything marks from LISTED premiums on the parity-completed surface (the lab
quotes are OTM-only; ``famb_common.premium_surface`` completes them with
``C = P + DF(F-K)``, ~0.03bp on settle forwards). The lattice side is the strict
ZQ-null tree used by every previous panel in this line: atoms from
``AtomEngine``, smear ``sqrt(unresolved_var + 3^2)``.

The sample is the full backfilled quote panel — 2021-02 → 2026-07, 26
quarterlies — so the study covers ZIRP, the 2022 hiking cycle, SVB, the 2024
cuts and the 2025-26 pause rather than the one-cycle window the previous
frameworks ran on.
"""
from __future__ import annotations

import datetime
import functools
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "data" / "outcome_map"

import famb_common as fc                                   # noqa: E402

from RVUtils.MeetingProb.atoms import AtomEngine, split_meetings  # noqa: E402
from RVUtils.MeetingProb.pricer import price_option        # noqa: E402
from RVUtils.OutcomeMap import (                           # noqa: E402
    HedgeContext, build_cell_map, decompose, fly_legs, map_full_weights,
    package_contracts, package_hedge_ratios, pair_odd_dev_signal,
    pair_odd_signal, pair_raw_signal,
)
from RVUtils.OutcomeMap.cells import CellMap, Cell, P_FLOOR  # noqa: E402

RANKS = (1, 2, 3)
SMEAR_FLOOR_BP = 3.0


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------

class Context:
    """Marks, forwards, the lattice and the calendar for the whole sample."""

    def __init__(self, quotes: Optional[pd.DataFrame] = None,
                 max_dte: int = 200):
        self.quotes = fc.load_quotes() if quotes is None else quotes
        self.symbols = sorted(self.quotes["symbol"].unique())
        self.fwd = fc.sr3_forwards(self.symbols)
        self.surface = fc.premium_surface(self.quotes, self.fwd)
        self.fwd_idx = self.fwd.set_index(["as_of", "symbol"])["fwd_rate"]
        self.dates = pd.DatetimeIndex(
            sorted(pd.to_datetime(self.quotes["as_of"].unique())))
        self.max_dte = max_dte
        self.tree = fc.TreeCtx([d.date() for d in self.dates])
        # (right, symbol, strike) -> daily premium series, for fast fixed-leg marks
        self._leg: Dict[Tuple[str, str, float], pd.Series] = {}
        for key, s in self.surface.groupby(level=[0, 1, 2]):
            self._leg[(key[0], key[1], round(float(key[2]), 6))] = \
                s.droplevel([0, 1, 2]).sort_index()
        self._strikes: Dict[Tuple[pd.Timestamp, str], np.ndarray] = {
            k: np.sort(g["strike_price"].unique())
            for k, g in self.quotes.groupby(["as_of", "symbol"], sort=False)}
        self._fair_cache: Dict[tuple, float] = {}
        self._atom_cache: Dict[tuple, object] = {}
        from SDRUtils.analytics.fomc import load_fomc_schedule
        sched = load_fomc_schedule("USD-SOFR-1D")
        self.decisions = pd.DatetimeIndex(sorted(
            pd.Timestamp(d) - pd.Timedelta(days=1)
            for d in pd.to_datetime(sched["effective_date"])))

    # -- lattice ----------------------------------------------------------
    def atoms(self, ts: pd.Timestamp, sym: str):
        key = (ts, sym)
        if key not in self._atom_cache:
            try:
                f = float(self.fwd_idx.loc[(ts, sym)])
            except KeyError:
                self._atom_cache[key] = None
                return None
            if not np.isfinite(f):
                self._atom_cache[key] = None
                return None
            out = self.tree.atoms(ts.date(), sym, f)
            self._atom_cache[key] = None if out is None else (out[0], out[1],
                                                              out[2], f)
        return self._atom_cache[key]

    def cell_atoms(self, ts: pd.Timestamp, sym: str):
        """Where the cells SIT (real world: the lattice's atoms)."""
        return self.atoms(ts, sym)

    def pricing_atoms(self, ts: pd.Timestamp, sym: str):
        """What the fair value is computed under (real world: the lattice)."""
        return self.atoms(ts, sym)

    # -- marks ------------------------------------------------------------
    def mark_fn(self, sym: str) -> Callable[[pd.Timestamp, Sequence], float]:
        legs_cache = self._leg

        def _mark(ts: pd.Timestamp, legs) -> float:
            total = 0.0
            for right, k, w in legs:
                s = legs_cache.get((right, sym, round(float(k), 6)))
                if s is None:
                    return np.nan
                try:
                    v = float(s.loc[ts])
                except KeyError:
                    return np.nan
                if not np.isfinite(v):
                    return np.nan
                total += w * v
            return total
        return _mark

    def mark_any(self, ts: pd.Timestamp, sym: str, legs) -> float:
        return self.mark_fn(sym)(ts, legs)

    def fair(self, ts: pd.Timestamp, sym: str, legs) -> float:
        key = (ts, sym, tuple((r, round(k, 6), round(w, 6))
                              for r, k, w in legs))
        if key in self._fair_cache:
            return self._fair_cache[key]
        a = self.pricing_atoms(ts, sym)
        if a is None:
            self._fair_cache[key] = np.nan
            return np.nan
        rates, probs, smear, _ = a
        v = float(sum(w * price_option(rates, probs, right, 100.0 - k,
                                       smear_bp=smear)
                      for right, k, w in legs))
        self._fair_cache[key] = v
        return v

    def strikes(self, ts: pd.Timestamp, sym: str) -> np.ndarray:
        return self._strikes.get((ts, sym), np.zeros(0))

    def expiry(self, sym: str) -> datetime.date:
        from MDP.STIRFutures._sofr_option_contracts import (
            sofr_option_last_trade_date)
        return sofr_option_last_trade_date(sym)

    def next_decision(self, ts: pd.Timestamp) -> Optional[pd.Timestamp]:
        later = self.decisions[self.decisions > ts]
        return later[0] if len(later) else None

    def sessions_to_decision(self, ts: pd.Timestamp) -> float:
        d = self.next_decision(ts)
        if d is None:
            return np.inf
        n = int(((self.dates > ts) & (self.dates <= d)).sum())
        return float(n)


# ---------------------------------------------------------------------------
# The cell panel
# ---------------------------------------------------------------------------

def _cell_map(ctx: Context, ts: pd.Timestamp, sym: str) -> Optional[CellMap]:
    """The map for one contract-day, in whatever world ``ctx`` represents.

    Cell PLACEMENT comes from ``cell_atoms`` and the fair value from
    ``pricing_atoms``; in the real world both are the lattice, in the P1 placebo
    neither is. Routing the placebo through this one function is what stops the
    panel and the backtest from drifting into different worlds.
    """
    a = ctx.cell_atoms(ts, sym)
    if a is None:
        return None
    rates, probs, smear, fwd = a
    cm = ctx.tree.cm(ts.date(), sym)
    if cm is None or cm.n_resolved == 0:
        return None
    mark = ctx.mark_fn(sym)

    def _mark_leg(right: str, k: float) -> float:
        return mark(ts, [(right, k, 1.0)])

    return build_cell_map(sym, ts, fwd, rates, probs, smear,
                          ctx.strikes(ts, sym), _mark_leg,
                          lambda legs: ctx.fair(ts, sym, legs),
                          n_resolved=cm.n_resolved)


def build_cell_panel(ctx: Context, *, ranks: Sequence[int] = RANKS,
                     progress: int = 0) -> pd.DataFrame:
    """One row per (as_of, symbol, cell) with the map and its decomposition."""
    rows: List[dict] = []
    for i, ts in enumerate(ctx.dates):
        if progress and i % progress == 0:
            print(f"  [{i}/{len(ctx.dates)}] {ts.date()} rows={len(rows)}",
                  flush=True)
        for rank in ranks:
            sym = fc.rank_symbol(ts.date(), rank)
            if sym is None:
                continue
            cmap = _cell_map(ctx, ts, sym)
            if cmap is None:
                continue
            xp = ctx.expiry(sym)
            dte = (xp - ts.date()).days
            if dte > ctx.max_dte:
                continue
            odd = cmap.odd
            even = cmap.even_fit
            for j, cell in enumerate(cmap.cells):
                rows.append({
                    "as_of": ts, "symbol": sym, "rank": rank, "cell": j,
                    "n_cells": cmap.n_cells, "dte": dte,
                    "n_resolved": cmap.n_resolved,
                    "forward_rate": cmap.forward_rate,
                    "smear_bp": cmap.smear_bp,
                    "atom_rate": cell.atom_rate, "p_lattice": cell.p_lattice,
                    "center_px": cell.center_px, "offset_bp": cell.offset_bp,
                    "d": cell.d, "mkt_bp": cell.mkt_bp, "fair_bp": cell.fair_bp,
                    "rich_bp": cell.rich_bp, "even_bp": float(even[j]),
                    "odd_bp": float(odd[j]), "resid_bp": float(cmap.resid[j]),
                    "fit_a": cmap.a, "fit_b": cmap.b, "fit_c": cmap.c,
                    "p_opt": cell.p_opt, "p_fair": cell.p_fair,
                    "off_lattice_premium": cmap.off_lattice_premium,
                })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Linear panels
# ---------------------------------------------------------------------------

def zq_jump_panel(ctx: Context) -> pd.DataFrame:
    rows = []
    for d, lad in ctx.tree.ladders.items():
        for m in lad:
            rows.append({"as_of": pd.Timestamp(d), "effective": m.effective,
                         "jump_bp": float(m.jump_bp), "source": "zq"})
    return pd.DataFrame(rows)


def swap_jump_panel(dates: Sequence[pd.Timestamp], *,
                    curve: str = "USD-SOFR-1D-Q12xM12STIRT",
                    progress: int = 0) -> pd.DataFrame:
    """Daily meeting-dated swap ladder -> per-meeting jumps.

    No bootstrap and no expiry seam (the curve carries the whole meeting strip
    on every build date), which is exactly why this is the sturdier linear read.
    The FIRST upcoming meeting's jump is measured off the overnight fixing and
    is known to be contaminated when the fixing is stale relative to the curve —
    it is published here with ``is_first`` so the gate can drop it rather than
    silently trusting it.
    """
    from RVUtils.MeetingProb.swap_ladder import swap_meeting_ladder
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from SDRUtils.analytics.fomc import get_current_fixing, load_fomc_schedule

    fomc = load_fomc_schedule("USD-SOFR-1D")
    mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    rows = []
    for i, ts in enumerate(dates):
        d = pd.Timestamp(ts).date()
        if progress and i % progress == 0:
            print(f"  swap [{i}/{len(dates)}] {d} rows={len(rows)}", flush=True)
        try:
            base = get_current_fixing("USD-SOFR-1D", d)
            pricer = mdp.get_pricer(dict(curve_name=curve, timestamp=d))
            lad = swap_meeting_ladder(d, pricer, fomc, base)
        except Exception:
            continue
        for j, m in enumerate(lad):
            rows.append({"as_of": pd.Timestamp(d), "effective": m.effective,
                         "jump_bp": float(m.jump_bp), "source": "swap",
                         "is_first": j == 0})
    return pd.DataFrame(rows)


def jump_lookup(panel: pd.DataFrame, *, drop_first: bool = False):
    """``(as_of, effective) -> jump_bp`` as a fast callable."""
    p = panel
    if drop_first and "is_first" in p.columns:
        p = p[~p["is_first"]]
    idx = p.set_index(["as_of", "effective"])["jump_bp"].sort_index()
    d = idx.to_dict()

    def _fn(ts: pd.Timestamp, eff) -> float:
        return float(d.get((pd.Timestamp(ts), eff), np.nan))
    return _fn


def make_hedge_ctx_fn(ctx: Context):
    """Frame-frozen package hedge ratios per (entry day, symbol, legs)."""
    def _fn(ts: pd.Timestamp, sym: str, legs) -> Optional[HedgeContext]:
        a = ctx.atoms(ts, sym)
        cm = ctx.tree.cm(ts.date(), sym)
        if a is None or cm is None or cm.n_resolved == 0:
            return None
        _, _, smear, fwd = a
        cache: Dict[tuple, np.ndarray] = {}

        def ratios(outcomes: Dict[int, int]) -> np.ndarray:
            key = tuple(sorted(outcomes.items()))
            if key not in cache:
                cache[key] = package_hedge_ratios(
                    cm, fwd, legs, smear, outcomes=dict(outcomes))
            return cache[key]
        return HedgeContext(
            effectives=tuple(r.effective for r in cm.resolved),
            supports=tuple(r.support for r in cm.resolved),
            ratios=ratios)
    return _fn


# ---------------------------------------------------------------------------
# Signal frames
# ---------------------------------------------------------------------------

EXPRESSIONS = ("pair_raw", "pair_odd", "pair_odd_dev", "map_full", "reswin")

#: sessions of trailing tilt used by ``pair_odd_dev`` (fixed, not a grid axis;
#: ~7 half-lives of the measured odd component)
TILT_WINDOW = 20

#: which signal metric each expression enters AND exits on
SIGNAL_MODE = {"pair_raw": "raw", "pair_odd": "odd", "pair_odd_dev": "odd_dev",
               "map_full": "odd", "reswin": "odd"}


def trailing_tilt(panel: pd.DataFrame, window: int = TILT_WINDOW) -> pd.Series:
    """Causal trailing mean of the fitted tilt per symbol, EXCLUDING today."""
    day = (panel.drop_duplicates(["as_of", "symbol"])
           .sort_values(["symbol", "as_of"])
           .set_index(["as_of", "symbol"])["fit_b"])
    out = (day.groupby(level="symbol")
           .apply(lambda s: s.droplevel("symbol").shift(1)
                  .rolling(window, min_periods=max(5, window // 4)).mean()))
    out = out.reorder_levels(["as_of", "symbol"]).sort_index()
    return out.rename("b_bar")


def _pair_legs(cmap: CellMap, i_long: int, i_short: int):
    return (list(cmap.cells[i_long].legs(1.0))
            + list(cmap.cells[i_short].legs(-1.0)))


def signal_frame(ctx: Context, panel: pd.DataFrame, expression: str,
                 *, p_floor: float = P_FLOOR,
                 b_bar: Optional[pd.Series] = None) -> pd.DataFrame:
    """Per (as_of, symbol) package legs + signal strength for one expression.

    Rebuilt from the panel (not from the surface) so a placebo panel produces a
    placebo signal frame through exactly the same code path. Each row carries
    the package's CELL decomposition (centres + weights) as well as its option
    legs, because the exit signal has to re-evaluate the even (and, for
    ``pair_odd_dev``, the trailing-tilt) projection on the same cells daily.
    """
    if b_bar is None and expression == "pair_odd_dev":
        b_bar = trailing_tilt(panel)
    rows = []
    for (ts, sym), g in panel.groupby(["as_of", "symbol"], sort=False):
        g = g.sort_values("cell")
        cmap = _cellmap_from_rows(ts, sym, g)
        if cmap is None:
            continue
        weights = np.zeros(cmap.n_cells)
        if expression == "pair_raw":
            s = pair_raw_signal(cmap, p_floor=p_floor)
        elif expression in ("pair_odd", "reswin"):
            s = pair_odd_signal(cmap, p_floor=p_floor)
        elif expression == "pair_odd_dev":
            try:
                bb = float(b_bar.loc[(ts, sym)])
            except (KeyError, TypeError):
                continue
            s = pair_odd_dev_signal(cmap, bb, p_floor=p_floor)
        elif expression == "map_full":
            s = map_full_weights(cmap, p_floor=p_floor)
        else:
            raise ValueError(expression)
        if s is None:
            continue
        if expression == "map_full":
            weights = np.asarray(s["weights"], dtype=float)
        else:
            weights[s["i_long"]] = 1.0
            weights[s["i_short"]] = -1.0
        legs = []
        for j, w in enumerate(weights):
            if abs(w) > 1e-9:
                legs += list(cmap.cells[j].legs(float(w)))
        if not legs:
            continue
        if expression == "reswin":
            k = ctx.sessions_to_decision(ts)
            if not (1 <= k <= 5):
                continue
        keep = np.abs(weights) > 1e-9
        rows.append({
            "as_of": ts, "symbol": sym, "expression": expression,
            "legs": legs, "strength_bp": float(s["strength_bp"]),
            "cell_centers": [float(c.center_px)
                             for c, k2 in zip(cmap.cells, keep) if k2],
            "cell_weights": [float(w) for w in weights[keep]],
            "n_contracts": package_contracts(legs),
            "dte": int(g["dte"].iloc[0]), "n_cells": int(g["n_cells"].iloc[0]),
            "fit_b": float(g["fit_b"].iloc[0]),
            "off_lattice_premium": float(g["off_lattice_premium"].iloc[0]),
        })
    return pd.DataFrame(rows)


def make_signal_fn(ctx: Context, panel: pd.DataFrame, mode: str,
                   b_bar: Optional[pd.Series] = None):
    """Daily value of the signal an expression enters on — and must exit on.

    ``raw``      the package's plain richness (market minus lattice-fair);
    ``odd``      that, minus the day's fitted standing premium evaluated on the
                 package's OWN cells at TODAY's forward (they drift as the
                 forward moves, which is exactly why it is re-evaluated);
    ``odd_dev``  that, minus the contract's trailing tilt on the same cells.
    """
    fits = (panel.drop_duplicates(["as_of", "symbol"])
            .set_index(["as_of", "symbol"])[["fit_a", "fit_b", "fit_c"]])
    fit_map = {k: (v[0], v[1], v[2]) for k, v in
               zip(fits.index, fits.to_numpy())}
    bb_map = {} if b_bar is None else b_bar.dropna().to_dict()

    def _fn(ts: pd.Timestamp, row) -> float:
        sym = row["symbol"]
        m = ctx.mark_any(ts, sym, row["legs"])
        if not np.isfinite(m):
            return np.nan
        f = ctx.fair(ts, sym, row["legs"])
        if not np.isfinite(f):
            return np.nan
        sig = m - f
        if mode == "raw":
            return sig
        fit = fit_map.get((ts, sym))
        if fit is None:
            return np.nan
        a, b, c = fit
        try:
            fwd = float(ctx.fwd_idx.loc[(ts, sym)])
        except KeyError:
            return np.nan
        d = (100.0 - np.asarray(row["cell_centers"], dtype=float) - fwd) / 0.25
        w = np.asarray(row["cell_weights"], dtype=float)
        sig -= float(np.dot(w, a + c * d ** 2))
        if mode == "odd_dev":
            bb = bb_map.get((ts, sym))
            if bb is None or not np.isfinite(bb):
                return np.nan
            sig -= float(bb * np.dot(w, d))
        return sig
    return _fn


def _cellmap_from_rows(ts, sym, g: pd.DataFrame) -> Optional[CellMap]:
    if len(g) < 3:
        return None
    cells = tuple(
        Cell(atom_rate=float(r["atom_rate"]), p_lattice=float(r["p_lattice"]),
             center_px=float(r["center_px"]), offset_bp=float(r["offset_bp"]),
             d=float(r["d"]), mkt_bp=float(r["mkt_bp"]),
             fair_bp=float(r["fair_bp"]))
        for _, r in g.iterrows())
    return CellMap(symbol=sym, as_of=ts,
                   forward_rate=float(g["forward_rate"].iloc[0]),
                   smear_bp=float(g["smear_bp"].iloc[0]),
                   n_resolved=int(g["n_resolved"].iloc[0]), cells=cells,
                   a=float(g["fit_a"].iloc[0]), b=float(g["fit_b"].iloc[0]),
                   c=float(g["fit_c"].iloc[0]),
                   resid=tuple(float(v) for v in g["resid_bp"]))


# ---------------------------------------------------------------------------
# Placebos — both re-derive everything inside the placebo world
# ---------------------------------------------------------------------------

class GaussianContext(Context):
    """P1: no lattice anywhere — moment-matched Gaussian, lattice-free cells.

    The placebo world keeps only what the tree knows BESIDES the lattice: the
    forward and the total width (event std composed with the smear). Fair values
    come from a single atom at the forward smeared by that width, and cell
    CENTRES are placed on a 25bp grid centred on the forward — so neither the
    prices nor the atom locations borrow anything from the FOMC lattice. Only
    the map's SIZE is kept (a calendar fact: how many meetings resolve), so the
    two worlds offer the same number of packages to choose between.

    Cell masses are the Gaussian's own mass in each 25bp cell, which keeps the
    tradeability floor meaningful in the placebo world too.
    """

    def cell_atoms(self, ts: pd.Timestamp, sym: str):
        key = ("cells", ts, sym)
        if key not in self._atom_cache:
            self._atom_cache[key] = self._gaussian(ts, sym, placement=True)
        return self._atom_cache[key]

    def pricing_atoms(self, ts: pd.Timestamp, sym: str):
        key = ("pricing", ts, sym)
        if key not in self._atom_cache:
            self._atom_cache[key] = self._gaussian(ts, sym, placement=False)
        return self._atom_cache[key]

    def _gaussian(self, ts, sym, *, placement: bool):
        from scipy.stats import norm
        a = self.atoms(ts, sym)
        if a is None:
            return None
        rates, probs, smear, fwd = a
        mu = float(np.dot(rates, probs))
        var_bp2 = float(np.dot(probs, (rates - mu) ** 2)) * 1e4
        std_bp = float(np.sqrt(max(var_bp2, 0.0) + smear ** 2))
        if not placement:
            return np.array([fwd]), np.array([1.0]), std_bp, fwd
        n = int(len(np.unique(np.round(rates, 4))))
        grid = np.array([fwd + (j - (n - 1) / 2.0) * 0.25 for j in range(n)])
        edges = np.concatenate([[-np.inf], (grid[:-1] + grid[1:]) / 2.0,
                                [np.inf]]) if n > 1 else np.array([-np.inf,
                                                                   np.inf])
        z = (edges - fwd) / max(std_bp / 100.0, 1e-9)
        mass = np.diff(norm.cdf(z))
        return grid, mass / mass.sum(), std_bp, fwd


def gaussian_context(base: Context) -> Context:
    new = GaussianContext.__new__(GaussianContext)
    new.__dict__.update(base.__dict__)
    new._fair_cache = {}
    new._atom_cache = dict(base._atom_cache)
    return new


def shifted_context(base: Context) -> Context:
    """P2: wrong calendar — every meeting wears the NEXT meeting's jump/q.

    Replacing the ladders on a fresh Context (with the caches cleared) keeps the
    atoms, the cell centres, the fair values AND the hedge ratios all inside the
    shifted world. Re-deriving only the signal would leak the real lattice back
    in through the marks — the bug the linvol grid's first placebo run hit.
    """
    from linvol_grid_common import shifted_ladders

    new = Context.__new__(Context)
    new.__dict__.update(base.__dict__)
    new._fair_cache = {}
    new._atom_cache = {}
    tree = fc.TreeCtx.__new__(fc.TreeCtx)
    tree.ladders = shifted_ladders(base.tree.ladders)
    tree._cm_cache = {}
    new.tree = tree
    return new

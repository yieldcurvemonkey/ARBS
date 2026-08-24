r"""The declared CA-vs-fly grid: cells, costs, statistics, null bars.

The cell list is generated from ``docs/convexityrv/cavf-grid-preregistration.md``
and counted against it in the test suite — a scored cell that is not declared
there is a trial-count leak, which is the precise mechanism by which this
package's previous grid winners died at their own null.

Cost convention (per leg, round trip, on leg DV01, charged at the unwind):

* futures package 0.25 bp on the CA DV01 (half a 0.25bp tick each way,
  independent of leg count — a 20-leg bundle pays the same package tick as a
  single outright, which is CME's own bundle-execution economics);
* matched swap 0.5 bp on the CA DV01 (the 0.5 bp two-way IMM-swap quote);
* each fly leg 0.5 bp on ITS OWN DV01: belly ``|β|·CA_DV01``, wings half the
  belly each under 50/50 weights → 1.0 bp on the belly DV01 in total.

Swept ×{0, 0.5, 1, 2}. The incumbent w2b convention (one fee per epoch on the
CA DV01 alone) is reported alongside by the notebook for comparability.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.ConvexityRV.cavf_signals import (
    Episode,
    SignalConfig,
    apply_overlay,
    build_signal_frame,
    episode_pnl,
    episodes_from_signals,
    fill_date,
)
from RVUtils.ConvexityRV.cavf_universe import (
    CA_DV01_DEFAULT,
    STRUCTURES,
    StructureSpec,
    flies_for,
    structure_by_label,
    tradeable_fly_specs,
)

__all__ = [
    "COST_MULTS",
    "CellSpec",
    "CellResult",
    "declared_cells",
    "episode_cost_usd",
    "run_cell",
    "run_grid",
    "grid_stats_frame",
    "null_bars",
    "fs_hypothesis_matrix",
    "PINNED_CITI_BLUES",
]

COST_MULTS: Tuple[float, ...] = (0.0, 0.5, 1.0, 2.0)

_FUT_RT_BP = 0.25
_SWAP_RT_BP = 0.5
_FLY_LEG_RT_BP = 0.5

#: Citi's published Blues fair-value line (13-Jan-2017 print), carried as a
#: fixed-coefficient variant: CA_bp = 10.2 + 21.4·(−0.70·r2 + r5 − 0.46·r10)
#: with rates in PERCENT — in this module's bp-per-bp convention the fixed β
#: is 21.4/100 against the 0.70/1/0.46-weighted 2s5s10s fly in bp.
PINNED_CITI_BLUES: Dict[str, float] = {
    "alpha_bp": 10.2, "beta_bp_per_bp": 0.214, "w_front": 0.70, "w_back": 0.46,
}


@dataclass(frozen=True)
class CellSpec:
    cell_id: str
    family: str                    # A | A_ca | A_fly | B | B_pinned | B_jpm | C_pos | D_basis | E_carry
    mode: str                      # pairs | fv | ca_only | fly_only
    structure: Optional[str]       # TB label, None for fly-only controls
    fly_id: Optional[str]
    cfg: SignalConfig
    overlay: Optional[str] = None  # positioning | basis | carry
    base_cell: Optional[str] = None


@dataclass
class CellResult:
    spec: CellSpec
    episodes: List[Episode]
    equity_by_mult: Dict[float, pd.Series]
    per_episode_usd: List[float] = field(default_factory=list)  # zero cost, at fills
    daily_zero_cost: pd.Series = field(default=None)  # type: ignore[assignment]

    @property
    def n_episodes(self) -> int:
        return len(self.episodes)


def _primary() -> SignalConfig:
    return SignalConfig(z_entry=2.0, z_exit=0.5, max_hold_bd=63)


def _sensitivity() -> SignalConfig:
    return SignalConfig(z_entry=1.5, z_exit=0.5, max_hold_bd=63)


def _jpm() -> SignalConfig:
    # exit at zero-cross is handled by z_exit≈0 (the state machine exits when
    # |z| <= z_exit); the pre-registration names 21bd max hold and a 3.5z stop
    # (the stop is applied inside run_cell by truncating at the stop date).
    return SignalConfig(z_entry=1.5, z_exit=1e-9, max_hold_bd=21)


def declared_cells() -> List[CellSpec]:
    """Exactly the pre-registered grid, in a deterministic order."""
    cells: List[CellSpec] = []

    # Families A and B: 14 structures × 6 flies × 2 threshold sets
    for s in STRUCTURES:
        for f in flies_for(s):
            for tag, cfg in (("p", _primary()), ("s", _sensitivity())):
                cells.append(CellSpec(
                    cell_id=f"A|{s.label}|{f.fly_id}|{tag}", family="A",
                    mode="pairs", structure=s.label, fly_id=f.fly_id, cfg=cfg))
                cells.append(CellSpec(
                    cell_id=f"B|{s.label}|{f.fly_id}|{tag}", family="B",
                    mode="fv", structure=s.label, fly_id=f.fly_id, cfg=cfg))
            cells.append(CellSpec(
                cell_id=f"Bj|{s.label}|{f.fly_id}", family="B_jpm",
                mode="fv", structure=s.label, fly_id=f.fly_id, cfg=_jpm()))

    # A-controls: CA-only per structure, both threshold sets
    for s in STRUCTURES:
        for tag, cfg in (("p", _primary()), ("s", _sensitivity())):
            cells.append(CellSpec(
                cell_id=f"Aca|{s.label}|{tag}", family="A_ca", mode="ca_only",
                structure=s.label, fly_id=None, cfg=cfg))

    # A-controls: fly-only per distinct fly, both threshold sets
    for f in tradeable_fly_specs():
        for tag, cfg in (("p", _primary()), ("s", _sensitivity())):
            cells.append(CellSpec(
                cell_id=f"Afly|{f.fly_id}|{tag}", family="A_fly",
                mode="fly_only", structure=None, fly_id=f.fly_id, cfg=cfg))

    # B-pinned: Citi's published Blues line, one cell
    cells.append(CellSpec(
        cell_id="Bpin|BLUES|2s5s10s", family="B_pinned", mode="fv",
        structure="BLUES", fly_id="2s5s10s", cfg=_primary()))

    # Overlays C/D/E on the 5 packs × spot 2s5s10s, families A and B primary
    for s in ("WHITES", "REDS", "GREENS", "BLUES", "GOLDS"):
        for fam, mode in (("A", "pairs"), ("B", "fv")):
            base = f"{fam}|{s}|2s5s10s|p"
            for overlay, tag in (("positioning", "C"), ("basis", "D"), ("carry", "E")):
                cells.append(CellSpec(
                    cell_id=f"{tag}|{base}", family=f"{tag}_{overlay[:5]}",
                    mode=mode, structure=s, fly_id="2s5s10s", cfg=_primary(),
                    overlay=overlay, base_cell=base))
    return cells


def episode_cost_usd(spec: CellSpec, ep: Episode, *, ca_dv01: float,
                     mult: float) -> float:
    """Per-leg round-trip cost of one episode at one sweep multiplier."""
    if mult == 0.0:
        return 0.0
    bp = 0.0
    if spec.mode in ("pairs", "fv", "ca_only"):
        bp += _FUT_RT_BP + _SWAP_RT_BP                     # the CA package
    belly = 0.0
    if spec.mode in ("pairs", "fv"):
        belly = abs(ep.beta_entry) * ca_dv01
    elif spec.mode == "fly_only":
        belly = ca_dv01
    fly_cost = _FLY_LEG_RT_BP * (belly + 2 * 0.5 * belly)  # belly + two wings
    return mult * (bp * ca_dv01 + fly_cost)


def _series_for(spec: CellSpec, ca_by_label: Mapping[str, pd.Series],
                fly_by_id: Mapping[str, pd.Series]
                ) -> Tuple[pd.Series, Optional[pd.Series]]:
    if spec.mode == "fly_only":
        return fly_by_id[spec.fly_id], fly_by_id[spec.fly_id]
    ca = ca_by_label[spec.structure]
    fly = fly_by_id[spec.fly_id] if spec.fly_id is not None else None
    return ca, fly


def run_cell(spec: CellSpec, ca_by_label: Mapping[str, pd.Series],
             fly_by_id: Mapping[str, pd.Series], *,
             ca_dv01: float = CA_DV01_DEFAULT,
             masks: Optional[Mapping[str, Callable]] = None,
             base_episodes: Optional[Sequence[Episode]] = None,
             signal_lag_bd: int = 0,
             exec_lag_bd: int = 1) -> CellResult:
    """One cell end to end. ``signal_lag_bd`` shifts the whole signal frame —
    the placebo: a real edge dies when its signal arrives 20 days late.
    ``exec_lag_bd=1`` (primary) fills at the mark AFTER the decision;
    ``exec_lag_bd=0`` is the same-day diagnostic whose gap to the primary
    measures the mark-noise harvest."""
    ca, fly = _series_for(spec, ca_by_label, fly_by_id)

    if spec.overlay is not None:
        if base_episodes is None:
            raise ValueError(f"overlay cell {spec.cell_id} needs base_episodes")
        if masks is None or spec.overlay not in masks:
            raise ValueError(f"no mask supplied for overlay {spec.overlay!r}")
        episodes = apply_overlay(base_episodes, masks[spec.overlay])
    else:
        if spec.family == "B_pinned":
            p = PINNED_CITI_BLUES
            resid = ca - p["alpha_bp"] - p["beta_bp_per_bp"] * fly
            sd = resid.rolling(spec.cfg.window).std(ddof=1).shift(1)
            z = resid / sd.replace(0.0, np.nan)
            sig = pd.DataFrame({
                "beta": p["beta_bp_per_bp"], "z": z,
                "gate_ok": np.isfinite(z)})
        else:
            sig = build_signal_frame(
                ca if spec.mode != "fly_only" else fly,
                fly if spec.mode in ("pairs", "fv", "fly_only") else None,
                spec.cfg, mode=spec.mode)
        if signal_lag_bd:
            sig[["beta", "z"]] = sig[["beta", "z"]].shift(signal_lag_bd)
            g = sig["gate_ok"].shift(signal_lag_bd)
            sig["gate_ok"] = g.where(g.notna(), False).astype(bool)
        if spec.family == "B_jpm":
            # the R² gate: rolling levels-correlation² through t−1 ≥ 0.60
            both = pd.concat([ca.rename("ca"), fly.rename("fly")], axis=1).dropna()
            r2 = (both["ca"].rolling(spec.cfg.window).corr(both["fly"]) ** 2).shift(1)
            sig["gate_ok"] = sig["gate_ok"] & (r2.reindex(sig.index) >= 0.60)
        episodes = episodes_from_signals(sig, spec.cfg)
        if spec.family == "B_jpm":
            episodes = _apply_z_stop(episodes, sig, stop_z=3.5)

    eq = {}
    if spec.mode == "fly_only":
        pnl_ca_leg, pnl_hedge_leg = fly, None
    elif spec.mode == "ca_only":
        pnl_ca_leg, pnl_hedge_leg = ca, None
    else:
        pnl_ca_leg, pnl_hedge_leg = ca, fly
    idx = pnl_ca_leg.dropna().index
    per_ep: List[float] = []
    for m in COST_MULTS:
        daily = pd.Series(0.0, index=idx)
        for ep in episodes:
            p = episode_pnl(ep, pnl_ca_leg, pnl_hedge_leg, ca_dv01,
                            exec_lag_bd=exec_lag_bd)
            daily = daily.add(p, fill_value=0.0)
            if m == COST_MULTS[0]:
                per_ep.append(float(p.sum()))
            c = episode_cost_usd(spec, ep, ca_dv01=ca_dv01, mult=m)
            if c:
                tx = fill_date(idx, ep.exit, exec_lag_bd) or idx[-1]
                daily.loc[tx] = daily.get(tx, 0.0) - c
        eq[m] = daily.cumsum()
    res = CellResult(spec=spec, episodes=episodes, equity_by_mult=eq,
                     per_episode_usd=per_ep)
    res.daily_zero_cost = eq[0.0].diff().fillna(0.0)
    return res


def _apply_z_stop(episodes: List[Episode], sig: pd.DataFrame, *,
                  stop_z: float) -> List[Episode]:
    """Truncate an episode at the first date its z moves BEYOND stop_z against
    the position (entry was at −sign(z), so 'against' is |z| growing)."""
    out: List[Episode] = []
    z = sig["z"]
    for ep in episodes:
        win = z.loc[ep.entry:ep.exit].iloc[1:]
        breach = win[(win.abs() >= stop_z) & (np.sign(win) == -ep.side)]
        if len(breach):
            out.append(replace(ep, exit=breach.index[0], exit_reason="z_stop"))
        else:
            out.append(ep)
    return out


def run_grid(cells: Sequence[CellSpec], ca_by_label: Mapping[str, pd.Series],
             fly_by_id: Mapping[str, pd.Series], *,
             ca_dv01: float = CA_DV01_DEFAULT,
             masks: Optional[Mapping[str, Callable]] = None,
             exec_lag_bd: int = 1,
             progress: bool = False) -> Dict[str, CellResult]:
    """Run every declared cell; overlay cells reuse their base's episodes."""
    results: Dict[str, CellResult] = {}
    base_first = sorted(cells, key=lambda c: c.overlay is not None)
    for i, spec in enumerate(base_first):
        base_eps = None
        if spec.base_cell is not None:
            if spec.base_cell not in results:
                raise KeyError(f"{spec.cell_id} declared before its base "
                               f"{spec.base_cell} was run")
            base_eps = results[spec.base_cell].episodes
        results[spec.cell_id] = run_cell(
            spec, ca_by_label, fly_by_id, ca_dv01=ca_dv01, masks=masks,
            base_episodes=base_eps, exec_lag_bd=exec_lag_bd)
        if progress and (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(base_first)} cells", flush=True)
    return results


def grid_stats_frame(results: Mapping[str, CellResult], *,
                     ca_dv01: float = CA_DV01_DEFAULT) -> pd.DataFrame:
    """One row per cell: the numbers the verdict is made from."""
    rows = []
    for cid, r in results.items():
        eq0 = r.equity_by_mult[0.0]
        d = eq0.diff().dropna()
        span_y = max((eq0.index[-1] - eq0.index[0]).days / 365.25, 1e-9)
        sd = float(d.std(ddof=1))
        ann_sr = float(d.mean() / sd * math.sqrt(252)) if sd > 0 else float("nan")
        per_ep = list(r.per_episode_usd)
        holds = [ep.hold_bd for ep in r.episodes]
        mean_hold = float(np.mean(holds)) if holds else float("nan")
        n_eff = span_y * 252.0 / mean_hold if holds else float("nan")
        gross = float(eq0.iloc[-1])
        cost_1x = gross - float(r.equity_by_mult[1.0].iloc[-1])
        rows.append({
            "cell_id": cid, "family": r.spec.family, "structure": r.spec.structure,
            "fly": r.spec.fly_id, "z_in": r.spec.cfg.z_entry,
            "n_ep": len(r.episodes), "mean_hold_bd": mean_hold,
            "hit": float(np.mean([p > 0 for p in per_ep])) if per_ep else float("nan"),
            "gross_usd": gross,
            "net_0p5x": float(r.equity_by_mult[0.5].iloc[-1]),
            "net_1x": float(r.equity_by_mult[1.0].iloc[-1]),
            "net_2x": float(r.equity_by_mult[2.0].iloc[-1]),
            "ann_sharpe": ann_sr,
            "sharpe_per_trade": (float(np.mean(per_ep) / np.std(per_ep, ddof=1))
                                 if len(per_ep) > 2 and np.std(per_ep, ddof=1) > 0
                                 else float("nan")),
            "n_eff": n_eff, "span_y": span_y,
            "be_mult": gross / cost_1x if cost_1x > 0 else float("inf"),
        })
    return pd.DataFrame(rows).set_index("cell_id")


def null_bars(n_trials: int, *, n_eff: float, span_years: float) -> Dict[str, float]:
    """E[max SR | null] on both clocks, the w2b discipline verbatim."""
    from RVUtils.StatisticalFinance.deflated_sharpe import expected_max_sharpe

    return {
        "emax_perhold": expected_max_sharpe(n_trials, 1.0 / n_eff),
        "emax_annualised": expected_max_sharpe(n_trials, 1.0 / span_years),
    }


def fs_hypothesis_matrix(ca_by_label: Mapping[str, pd.Series],
                         fly_by_id: Mapping[str, pd.Series], *,
                         shapes: Sequence[str] = ("1s2s3s", "2s3s5s", "2s5s10s"),
                         starts: Sequence[float] = (0.0, 1.0, 2.0, 3.0, 4.0, 5.0),
                         ) -> pd.DataFrame:
    """The headline measurement: hedge R² of ΔCA on Δfly by (structure × fly
    forward start), max over the three shapes — at Blues/Golds depth for the
    first time. Long frame: structure, t1_mean_y, start, shape, r2, beta, n."""
    rows = []
    for s in STRUCTURES:
        ca = ca_by_label.get(s.label)
        if ca is None:
            continue
        dca = ca.diff()
        for start in starts:
            for shape in shapes:
                fid = shape if start == 0.0 else f"{shape}@{start:.0f}Y"
                fly = fly_by_id.get(fid)
                if fly is None:
                    continue
                both = pd.concat([dca.rename("y"), fly.diff().rename("x")],
                                 axis=1).dropna()
                if len(both) < 60:
                    continue
                r = float(both["y"].corr(both["x"]))
                beta = float(both["y"].cov(both["x"]) / both["x"].var(ddof=1))
                rows.append({"structure": s.label, "t1_mean_y": s.t1_mean_y,
                             "start_y": start, "shape": shape, "fly_id": fid,
                             "r2": r * r, "beta_bp_per_bp": beta,
                             "n": len(both)})
    return pd.DataFrame(rows)

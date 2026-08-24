r"""GV block — the declared cell list, cell execution, statistics and null bars.

The cell list is generated here and counted against
``docs/convexityrv/gv-preregistration.md`` in the test suite.  A scored cell
that is not declared there is a trial-count leak, which is the precise mechanism
by which this package's previous grid winners died at their own null.

Declared total: **298** cells (252 primary grid + 6 CA-only controls + 12
variance-basis + 28 secondary), of which **12** carry ``headline=True`` — the
brief's own trade at the incumbent sizing and at the fix, nothing else.

One benchmark vol per structure, used for BOTH derivatives
----------------------------------------------------------
A vega match is only a hedge if the two vegas are taken with respect to the
**same** volatility factor.  Taking ``dCA/dsigma_A`` against ``dleg/dsigma_B``
would be a hedge only if ``sigma_A`` and ``sigma_B`` moved one-for-one.  So each
structure carries one ATMF normal-vol benchmark — the straddle whose expiry sits
at the structure's own mean contract expiry and whose tenor is the matched 1y
swap's — and both ``dCA/dsigma`` and ``dleg/dsigma`` are taken against it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.ConvexityRV.gv_signals import (
    Episode,
    SignalConfig,
    book_daily,
    build_signal_frame,
    episode_cost_usd,
    episode_pnl,
    episodes_from_signals,
    fill_date,
    inv_vol_scale,
)
from RVUtils.ConvexityRV.gv_sizing import (
    SIZING_RULES,
    SizingInputs,
    ca_implied_variance_bp2,
    ca_theta_bp_per_year,
    denoise,
    episode_decomposition,
    sizing_beta,
)
from RVUtils.ConvexityRV.gv_universe import (
    CA_DV01_DEFAULT,
    CURVE,
    LEGS,
    PRIMARY_STRUCTURES,
    SECONDARY_STRUCTURES,
    ca_col,
    leg_cost_dv01,
    leg_series,
    mean_t1_series,
    roll_segments,
    time_weight_series,
)

#: Panel columns used as the level and slope controls in the vega regression.
LEVEL_COL = f"{CURVE} 10Y OUTRIGHT RATE"
SLOPE_COLS = (f"{CURVE} 2Y OUTRIGHT RATE", f"{CURVE} 10Y OUTRIGHT RATE")

__all__ = [
    "COST_MULTS",
    "BOOK_SCALES",
    "SIGNALS",
    "VOL_BENCH",
    "HEADLINE_LEGS",
    "HEADLINE_SIZINGS",
    "SECONDARY_LEGS",
    "SECONDARY_SIZINGS",
    "VARBASIS_LEG",
    "VARBASIS_SIZINGS",
    "CellSpec",
    "CellResult",
    "declared_cells",
    "vol_bench_col",
    "run_cell",
    "run_grid",
    "grid_stats_frame",
    "null_bars",
    "vol_proxy_matrix",
]

COST_MULTS: Tuple[float, ...] = (0.0, 0.5, 1.0, 2.0)
BOOK_SCALES: Tuple[str, ...] = ("const_dv01", "inv_vol")
SIGNALS: Tuple[str, ...] = ("z_resid", "z_ca", "z_varbasis")

#: The one ATMF straddle per structure: expiry at the structure's own mean
#: contract expiry, tenor = the matched 1y swap.
VOL_BENCH: Dict[str, str] = {
    "WHITES": "1Yx1Y", "REDS": "2Yx1Y", "GREENS": "3Yx1Y",
    "BLUES": "4Yx1Y", "GOLDS": "5Yx1Y",
    "SFR12": "3Yx1Y", "SFR16": "4Yx1Y", "SFR20": "5Yx1Y",
    "BUNDLE4Y": "2Yx1Y", "BUNDLE5Y": "3Yx1Y",
}

HEADLINE_LEGS: Tuple[str, ...] = ("immF_2s5s10s", "immM_2s5s10s")
HEADLINE_SIZINGS: Tuple[str, ...] = ("beta_lvl", "vega_match")
SECONDARY_LEGS: Tuple[str, ...] = HEADLINE_LEGS
SECONDARY_SIZINGS: Tuple[str, ...] = HEADLINE_SIZINGS
VARBASIS_LEG = "immM_2s5s10s"
VARBASIS_SIZINGS: Tuple[str, ...] = ("vega_match", "vol_ratio")


def vol_bench_col(structure: str, curve: str = CURVE) -> str:
    return f"{curve} {VOL_BENCH[structure.upper()]} STRADDLE BUY ATMF NVOL"


@dataclass(frozen=True)
class CellSpec:
    cell_id: str
    tier: str                     # "primary" | "secondary"
    signal: str                   # z_resid | z_ca | z_varbasis
    structure: str
    leg_id: Optional[str]
    sizing: str
    book_scale: str
    headline: bool = False
    cfg: SignalConfig = field(default_factory=SignalConfig)


@dataclass
class CellResult:
    spec: CellSpec
    episodes: List[Episode]
    daily_by_mult: Dict[float, pd.Series]
    per_episode_usd: List[float]
    n_gate_refusals: int = 0
    n_dates: int = 0
    #: deterministic CA decay booked by the episodes, USD -- carry, not alpha
    carry_usd: float = 0.0
    #: mean |beta| and the resulting hedge notional, for the before/after table
    mean_abs_beta: float = float("nan")

    @property
    def n_episodes(self) -> int:
        return len(self.episodes)


def declared_cells() -> List[CellSpec]:
    """Exactly the pre-registered grid, in a deterministic order."""
    cells: List[CellSpec] = []
    cfg = SignalConfig()

    # --- primary grid: 3 x 7 x 6 x 2 = 252 -------------------------------
    for s in PRIMARY_STRUCTURES:
        for leg in LEGS:
            for sz in SIZING_RULES:
                for bs in BOOK_SCALES:
                    head = (leg in HEADLINE_LEGS and sz in HEADLINE_SIZINGS
                            and bs == "const_dv01")
                    cells.append(CellSpec(
                        f"A|{s}|{leg}|{sz}|{bs}", "primary", "z_resid",
                        s, leg, sz, bs, head, cfg))

    # --- CA-only controls: 3 x 2 = 6 -------------------------------------
    for s in PRIMARY_STRUCTURES:
        for bs in BOOK_SCALES:
            cells.append(CellSpec(f"C|{s}|caonly|{bs}", "primary", "z_ca",
                                  s, None, "none", bs, False, cfg))

    # --- variance basis: 3 x 2 x 2 = 12 ----------------------------------
    for s in PRIMARY_STRUCTURES:
        for sz in VARBASIS_SIZINGS:
            for bs in BOOK_SCALES:
                cells.append(CellSpec(
                    f"V|{s}|{VARBASIS_LEG}|{sz}|{bs}", "primary", "z_varbasis",
                    s, VARBASIS_LEG, sz, bs, False, cfg))

    # --- secondary structures: 7 x 2 x 2 x 1 = 28 ------------------------
    for s in SECONDARY_STRUCTURES:
        for leg in SECONDARY_LEGS:
            for sz in SECONDARY_SIZINGS:
                cells.append(CellSpec(
                    f"S|{s}|{leg}|{sz}|const_dv01", "secondary", "z_resid",
                    s, leg, sz, "const_dv01", False, cfg))

    ids = [c.cell_id for c in cells]
    assert len(set(ids)) == len(ids), "duplicate cell id"
    return cells


# ---------------------------------------------------------------------------
def run_cell(spec: CellSpec, ca_panel: pd.DataFrame, legs: pd.DataFrame,
             *, halflives: Mapping[str, float],
             ca_dv01: float = CA_DV01_DEFAULT,
             segments: Optional[Sequence[Tuple[pd.Timestamp, pd.Timestamp]]] = None,
             blackout: bool = True,
             cost_mults: Sequence[float] = COST_MULTS) -> CellResult:
    """One declared cell, end to end, on precomputed panels."""
    col = ca_col(spec.structure)
    ca_raw = ca_panel[col].astype(float).dropna()
    idx = ca_raw.index

    if segments is None:
        segments = (roll_segments(idx) if blackout
                    else [(idx[0], idx[-1])])

    hl = float(halflives.get(col, 0.0))
    ca_dn = denoise(ca_raw, hl)

    if spec.leg_id is None:
        leg = pd.Series(0.0, index=idx, name="none")
    else:
        leg = leg_series(legs, spec.leg_id, spec.structure).reindex(idx)

    nvol = legs[vol_bench_col(spec.structure)].astype(float).reindex(idx)
    w = time_weight_series(idx, spec.structure)
    t1m = mean_t1_series(idx, spec.structure)
    theta_bd = ca_theta_bp_per_year(nvol, t1m) / 252.0

    level = legs[LEVEL_COL].astype(float).reindex(idx)
    slope = (legs[SLOPE_COLS[1]].astype(float)
             - legs[SLOPE_COLS[0]].astype(float)).reindex(idx) * 100.0

    inp = SizingInputs(ca=ca_raw, ca_denoised=ca_dn, leg=leg, nvol=nvol, w=w,
                       window=spec.cfg.window, level=level, slope=slope)
    beta, gate = sizing_beta(spec.sizing, inp)
    beta = beta.reindex(idx)
    gate = gate.reindex(idx).fillna(False).astype(bool)

    if spec.signal == "z_ca":
        frame = build_signal_frame(ca_raw, ca_dn, pd.Series(0.0, index=idx),
                                   pd.Series(0.0, index=idx),
                                   pd.Series(True, index=idx), cfg=spec.cfg)
        beta = pd.Series(0.0, index=idx)
    elif spec.signal == "z_varbasis":
        v_ca = ca_implied_variance_bp2(ca_dn, w)
        v_bench = nvol.astype(float) ** 2
        basis = (v_ca - v_bench).rename("varbasis")
        frame = build_signal_frame(ca_raw, basis, pd.Series(0.0, index=idx),
                                   pd.Series(0.0, index=idx), gate, cfg=spec.cfg)
        # the SIGNAL is the variance basis; the POSITION is still CA vs leg at
        # the declared beta, so restore it after the z is built.
        frame["beta"] = beta
        frame["leg"] = leg
    else:
        frame = build_signal_frame(ca_raw, ca_dn, leg, beta, gate, cfg=spec.cfg)

    if spec.book_scale == "inv_vol":
        dv = inv_vol_scale(ca_raw, leg, beta.fillna(0.0), base_dv01=ca_dv01)
    else:
        dv = None

    eps = episodes_from_signals(frame, spec.cfg, segments,
                                ca_dv01_series=dv, ca_dv01=ca_dv01)

    daily = {m: book_daily(eps, ca_raw, leg, leg_id=spec.leg_id, index=idx,
                           cost_mult=m, exec_lag_bd=spec.cfg.exec_lag_bd)
             for m in cost_mults}
    per_ep = []
    carry = 0.0
    for e in eps:
        p = episode_pnl(e, ca_raw, leg, exec_lag_bd=spec.cfg.exec_lag_bd)
        per_ep.append(float(p.sum()))
        carry += episode_decomposition(p, theta_bd, e.side, e.ca_dv01)["carry_usd"]
    refusals = int((~gate).sum())
    mab = float(np.mean([abs(e.beta_entry) for e in eps])) if eps else float("nan")
    return CellResult(spec, eps, daily, per_ep, refusals, len(idx),
                      float(carry), mab)


def run_grid(cells: Sequence[CellSpec], ca_panel: pd.DataFrame,
             legs: pd.DataFrame, *, halflives: Mapping[str, float],
             ca_dv01: float = CA_DV01_DEFAULT, blackout: bool = True,
             progress: bool = False) -> List[CellResult]:
    idx = ca_panel.index
    segs = roll_segments(idx) if blackout else [(idx[0], idx[-1])]
    out = []
    for i, c in enumerate(cells):
        if progress and i % 25 == 0:
            print(f"  cell {i}/{len(cells)}  {c.cell_id}", flush=True)
        out.append(run_cell(c, ca_panel, legs, halflives=halflives,
                            ca_dv01=ca_dv01, segments=segs, blackout=blackout))
    return out


# ---------------------------------------------------------------------------
ANN = 252.0


def _sharpe(daily: pd.Series) -> float:
    d = pd.Series(daily).astype(float)
    nz = d[d != 0.0]
    if len(nz) < 10 or d.std(ddof=1) == 0:
        return float("nan")
    return float(d.mean() / d.std(ddof=1) * math.sqrt(ANN))


def grid_stats_frame(results: Sequence[CellResult], *,
                     span_years: float) -> pd.DataFrame:
    rows = []
    for r in results:
        s = r.spec
        holds = [int(np.busday_count(e.entry.date(), e.exit.date()))
                 for e in r.episodes]
        mean_hold = float(np.mean(holds)) if holds else float("nan")
        # Two clocks, and the SMALLER one is the honest count.  ``span*252/hold``
        # assumes the book is always in the market; a roll-blackout book with 9
        # episodes over 5.6 years has made 9 bets, not 48, and quoting the larger
        # number understates every null bar this grid is graded against.
        n_eff_hold = ((span_years * ANN / mean_hold)
                      if mean_hold and mean_hold > 0 else float("nan"))
        n_eff = (float(min(n_eff_hold, len(r.episodes)))
                 if r.episodes and np.isfinite(n_eff_hold) else float("nan"))
        pe = np.asarray(r.per_episode_usd, dtype=float)
        gross_cost_dv01 = float(sum(
            (2.0 * e.ca_dv01) +
            (leg_cost_dv01(s.leg_id, abs(e.beta_entry) * e.ca_dv01)
             if s.leg_id and e.beta_entry else 0.0)
            for e in r.episodes))
        row = {
            "cell_id": s.cell_id, "tier": s.tier, "headline": s.headline,
            "signal": s.signal, "structure": s.structure, "leg_id": s.leg_id,
            "sizing": s.sizing, "book_scale": s.book_scale,
            "n_episodes": r.n_episodes, "mean_hold_bd": mean_hold,
            "n_eff": n_eff, "n_eff_hold_clock": n_eff_hold,
            "gate_refusal_frac": r.n_gate_refusals / max(1, r.n_dates),
            "hit_rate": float((pe > 0).mean()) if len(pe) else float("nan"),
            "mean_beta": float(np.mean([e.beta_entry for e in r.episodes]))
            if r.episodes else float("nan"),
            "mean_leg_dv01": float(np.mean(
                [abs(e.beta_entry) * e.ca_dv01 for e in r.episodes]))
            if r.episodes else float("nan"),
            "gross_dv01_traded": gross_cost_dv01,
            "carry_usd": r.carry_usd,
            "mean_abs_beta": r.mean_abs_beta,
        }
        for m in sorted(r.daily_by_mult):
            d = r.daily_by_mult[m]
            row[f"net_{m}"] = float(d.sum())
            row[f"sharpe_{m}"] = _sharpe(d)
        g = row.get("net_0.0", np.nan)
        row["breakeven_bp"] = (g / gross_cost_dv01) if gross_cost_dv01 else np.nan
        row["residual_usd"] = g - r.carry_usd
        row["carry_share"] = (r.carry_usd / g) if g else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def null_bars(n_trials: int, *, n_eff: float, span_years: float) -> Dict[str, float]:
    """E[max SR | null] on both clocks — the house discipline, verbatim.

    A per-hold Sharpe has null SE ``1/sqrt(n_eff)``; an ANNUALISED Sharpe has
    ``1/sqrt(span_years)``.  With quarterly-capped holds the annualised bar is
    the larger one, so quoting only the per-hold null understates the bar.
    """
    from RVUtils.StatisticalFinance.deflated_sharpe import expected_max_sharpe
    return {
        "emax_perhold": expected_max_sharpe(n_trials, 1.0 / max(n_eff, 1e-9)),
        "emax_annualised": expected_max_sharpe(n_trials, 1.0 / max(span_years, 1e-9)),
    }


def vol_proxy_matrix(legs: pd.DataFrame, *, structures: Sequence[str],
                     window: int = 252) -> pd.DataFrame:
    """**Is a swap butterfly a volatility proxy at all?**

    The premise of this whole block. For every declared leg against every ATMF
    normal-vol column in the panel, the full-sample levels regression of the leg
    on the vol, plus the fraction of days the rolling fit clears the
    ``vega_match`` gate.  If this comes back empty the brief's premise is
    answered by measurement and no backtest is needed to say so.
    """
    from RVUtils.ConvexityRV.gv_sizing import (VOL_BETA_R2_MIN, VOL_BETA_T_MIN,
                                               rolling_vol_beta)
    vol_cols = [c for c in legs.columns if c.endswith("ATMF NVOL")]
    rows = []
    for leg_id, spec in LEGS.items():
        needs_struct = spec.start == "immM"
        for st in (structures if needs_struct else [structures[0]]):
            try:
                lg = leg_series(legs, leg_id, st)
            except KeyError:
                continue
            for vc in vol_cols:
                j = pd.concat([lg.rename("y"),
                               legs[vc].astype(float).rename("x")],
                              axis=1).dropna()
                if len(j) < 120:
                    continue
                r = float(j["y"].corr(j["x"]))
                b = float(j["y"].cov(j["x"]) / j["x"].var(ddof=1))
                n = len(j)
                t = r * math.sqrt(max(n - 2, 1) / max(1e-12, 1 - r * r))
                rb, rt, rr2 = rolling_vol_beta(lg, legs[vc].astype(float),
                                               window=window)
                ok = ((rt.abs() >= VOL_BETA_T_MIN) & (rr2 >= VOL_BETA_R2_MIN))
                rows.append({
                    "leg_id": leg_id,
                    "structure": st if needs_struct else "",
                    "vol": vc.split(" ")[1], "n": n,
                    "beta_bp_per_bpyr": b, "r2": r * r, "t": t,
                    "roll_gate_pass_frac": float(ok.mean()),
                    "roll_beta_median": float(rb.median()),
                    "roll_beta_sd": float(rb.std(ddof=1)),
                })
    return pd.DataFrame(rows)

"""Shared plumbing for the ZQ (Fed Funds) kink-fade lab.

Same shape as ``sfr_kink_fade_common``: every reporting block is imported
unchanged from ``sfr_fly_meanrev_common`` so all three labs -- SR3 butterflies,
SR3 kink, ZQ kink -- are graded by identical code and their league tables rank
side by side. What differs here is what the contract forces.

**Cost.** ZQ is $41.67 per bp (SR3 is $25) and its tick is 0.005 index points =
0.5bp, halving to 0.0025 near delivery on a rule with a precise onset
(``RVUtils.MeanRev.ff.half_tick_onset``). Cost is per **contract** as in SR3, so
a 2-leg calendar spread is 1.0bp round trip and a ``1/-2/1`` fly is 2.0bp -- the
same bp figures as SR3, on an instrument worth 1.67x as much per bp.

**Structures.** ZQ trades every calendar month, so the strip is monthly and a
"fly" spans three consecutive months rather than three quarters. The natural FF
structures are the **meeting reads**: a blended delivery month against the clean
month that follows it.

**Marks.** Settles, always. The MIX23 curve reproduces the ZQ strip with no
material bias but ~0.85bp of dispersion per contract (measured in
``notebooks/rv/_probe_zq_curve.py``), which is 1.7 ZQ ticks -- bigger than the
object any kink definition is trying to isolate. The curve is a diagnostic here
and never a mark.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import sfr_fly_meanrev_common as _fm  # noqa: E402

from RVUtils.MeanRev.diagnostics import (  # noqa: E402
    move_profile, oracle_table, selectivity_table, signal_entry_mask,
    variance_decomposition,
)
from RVUtils.MeanRev.engine import DOLLARS_PER_BP  # noqa: E402
from RVUtils.MeanRev.ff import (  # noqa: E402
    ZQ_DV01_USD, ZQ_HALF_TICK_BP, ZQ_POINT_USD, ZQ_TICK_BP, delivery_window,
    half_tick_onset, tick_bp, zq_exposure_vector,
)
from RVUtils.MeanRev.meetings import fomc_decisions, solve_smooth_path  # noqa: E402

DATA_DIR = REPO / "notebooks" / "data" / "zq_kink_fade"
PANEL_DIR = DATA_DIR

#: 2 contracts x 2 sides x half a 0.5bp tick
TAKER_SPREAD_BP = 1.0
#: 4 contracts x 2 sides x half a 0.5bp tick
TAKER_FLY_BP = 2.0
COST_CURVE_BP = (0.0, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0)
SHADOW_COST_MODE = "per_contract"

_FLY_DEFAULTS = {"path": _fm.DATA_DIR, "taker_bp": _fm.TAKER_BP,
                 "cost_curve_bp": _fm.COST_CURVE_BP,
                 "shadow_cost_mode": _fm.SHADOW_COST_MODE}

_fm.set_output_dir(DATA_DIR, taker_bp=TAKER_SPREAD_BP, cost_curve_bp=COST_CURVE_BP,
                   shadow_cost_mode=SHADOW_COST_MODE)


def restore_fly_meanrev_defaults() -> None:
    """Undo this module's import-time repointing of ``sfr_fly_meanrev_common``."""
    _fm.set_output_dir(**_FLY_DEFAULTS)


def set_taker(bp: float) -> None:
    """Grade subsequent league rows at a different round trip.

    A ZQ spread is 2 contracts and a fly is 4, so they do not share a taker
    figure the way SR3's structures do. Rows carry a ``taker_bp`` column so the
    table stays readable.
    """
    _fm.set_output_dir(DATA_DIR, taker_bp=float(bp), cost_curve_bp=COST_CURVE_BP,
                       shadow_cost_mode=SHADOW_COST_MODE)


# reporting blocks, unchanged
config_from_row = _fm.config_from_row
cost_block = _fm.cost_block
exit_comparison = _fm.exit_comparison
grid_block = _fm.grid_block
header_block = _fm.header_block
league_row = _fm.league_row
median_row = _fm.median_row
regime_block = _fm.regime_block
run_family = _fm.run_family
shadow_block = _fm.shadow_block
sign_test = _fm.sign_test
signal_params_from_row = _fm.signal_params_from_row
stability_block = _fm.stability_block
three_panel_equity = _fm.three_panel_equity
REGIME_ORDER = _fm.REGIME_ORDER

__all__ = [
    "DATA_DIR", "PANEL_DIR", "TAKER_SPREAD_BP", "TAKER_FLY_BP", "COST_CURVE_BP",
    "SHADOW_COST_MODE", "REGIME_ORDER", "set_taker",
    "restore_fly_meanrev_defaults",
    "config_from_row", "cost_block", "exit_comparison", "grid_block",
    "header_block", "league_row", "median_row", "regime_block", "run_family",
    "shadow_block", "sign_test", "signal_params_from_row", "stability_block",
    "three_panel_equity",
    "move_profile", "oracle_table", "selectivity_table", "signal_entry_mask",
    "variance_decomposition",
    "load_zq", "zq_structures", "meeting_residual_panel_zq", "zq_cost_panel",
    "oracle_block", "zq_shadow_block", "zq_run_family", "implied_jump_panel",
    "ZQ_DV01_USD", "ZQ_TICK_BP", "ZQ_HALF_TICK_BP", "ZQ_POINT_USD",
]


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------

def load_zq(*, start: Optional[str] = None, end: Optional[str] = None,
            max_rank: int = 12, min_oi: float = 0.0,
            data_dir: Path = PANEL_DIR) -> Dict[str, object]:
    """The ZQ contract panel plus everything the meeting calendar contributes.

    Only **pre-accrual** contracts are kept. Once a delivery month starts, part
    of the settle is realised fixings and the rate is a blend of history and
    expectation -- the same rule the SR3 lab applies by dropping a contract once
    its IMM quarter begins.
    """
    c = pd.read_parquet(data_dir / "contracts.parquet")
    c["as_of"] = pd.to_datetime(c["as_of"])
    if start:
        c = c[c["as_of"] >= pd.Timestamp(start)]
    if end:
        c = c[c["as_of"] <= pd.Timestamp(end)]
    c = c[~c["accruing"]].copy()
    c["rank"] = c.groupby("as_of")["imm_start"].rank(method="first").astype(int)
    c = c[c["rank"] <= int(max_rank)]
    if min_oi > 0:
        c = c[c["open_interest"].fillna(0.0) >= float(min_oi)]

    codes = sorted(c["code"].unique(), key=lambda k: delivery_window(k)[0])
    win = {k: delivery_window(k) for k in codes}
    meetings = fomc_decisions(
        min(w[0] for w in win.values()) - datetime.timedelta(days=400),
        max(w[1] for w in win.values()))
    exposure = {k: zq_exposure_vector(win[k][:2], meetings) for k in codes}

    rates = c.pivot_table(index="as_of", columns="code", values="rate_pct",
                          aggfunc="first").sort_index()
    rank = c.pivot_table(index="as_of", columns="code", values="rank",
                         aggfunc="first").reindex(index=rates.index,
                                                  columns=rates.columns)
    oi = c.pivot_table(index="as_of", columns="code", values="open_interest",
                       aggfunc="first").reindex(index=rates.index,
                                                columns=rates.columns)
    regimes = _fm.regime_tag(rates.index) if hasattr(_fm, "regime_tag") else None
    if regimes is None:
        from RVUtils.MeanRev.panel import regime_tag

        regimes = regime_tag(rates.index)
    return {"contracts": c, "codes": codes, "windows": win, "meetings": meetings,
            "exposure": exposure, "rates": rates, "rank": rank, "oi": oi,
            "regimes": regimes, "max_rank": int(max_rank)}


def zq_structures(lab: Dict[str, object], *, n_legs: int = 2,
                  weights: Optional[Sequence[float]] = None,
                  max_rank: Optional[int] = None) -> Dict[str, object]:
    """Consecutive-month ZQ packages, keyed on ABSOLUTE contract codes.

    Returns ``levels`` (bp), ``gate`` (both legs inside ``max_rank``),
    ``diff_exposure`` (see below), ``struct`` (a long frame in the shape the
    shared shadow/CM blocks expect) and ``cost_bp``.

    ``diff_exposure`` is ``max_m |sum_j w_j * W[leg_j, m]|`` -- how much of a
    single policy decision the package carries. It is **zero only if every
    meeting loads identically on every leg**, which is the real definition of a
    structurally pinned spread. The obvious alternative -- "is there a meeting
    between the two delivery months" -- is wrong, and measurably so: Nov/Dec has
    no meeting between the 1st of November and the 1st of December, yet the
    December contract is 22/31 exposed to the December meeting *inside its own
    month* and November is not exposed at all, so the spread carries most of a
    decision.
    """
    w = list(weights) if weights is not None else (
        [-1.0, 1.0] if n_legs == 2 else [-1.0, 2.0, -1.0])
    n_legs = len(w)
    max_rank = int(max_rank if max_rank is not None else lab["max_rank"])
    codes, rates, rank = lab["codes"], lab["rates"], lab["rank"]
    exposure = lab["exposure"]

    lv, gt, de, rows = {}, {}, {}, []
    for i in range(len(codes) - n_legs + 1):
        legs = codes[i:i + n_legs]
        if any(l not in rates.columns for l in legs):
            continue
        key = "-".join(legs)
        val = sum(x * rates[l] for x, l in zip(w, legs)) * 100.0
        ok = np.ones(len(rates), dtype=bool)
        for l in legs:
            ok &= (rank[l] <= max_rank).fillna(False).to_numpy()
        ok &= val.notna().to_numpy()
        lv[key] = val.where(ok)
        # a Series, NOT a bare ndarray: a dict of ndarrays builds a DataFrame on
        # a positional index, which then reindexes to all-NaN against the date
        # index and silently gates every cell off -- zero trades, no error.
        gt[key] = pd.Series(ok, index=rates.index)
        de[key] = float(np.abs(sum(x * exposure[l] for x, l in zip(w, legs))).max())
        blk = pd.DataFrame({"as_of": rates.index, "key": key,
                            "value": lv[key].to_numpy()})
        for j, l in enumerate(legs):
            blk[f"leg{j}_id"] = l
            blk[f"leg{j}_value"] = rates[l].to_numpy()
        blk["cm_slot"] = int(np.median(rank[legs[0]].dropna())) if rank[legs[0]].notna().any() else 0
        blk["cm_label_short"] = key
        rows.append(blk.dropna(subset=["value"]))

    levels = pd.DataFrame(lv)
    gate = (pd.DataFrame(gt).reindex(index=levels.index, columns=levels.columns)
            .astype("boolean").fillna(False).astype(bool))
    struct = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    cost = float(sum(abs(x) for x in w)) * 2.0 * (ZQ_TICK_BP / 2.0)
    return {"levels": levels, "gate": gate, "diff_exposure": pd.Series(de),
            "struct": struct, "weights": tuple(w), "n_legs": n_legs,
            "cost_bp": cost, "regimes": lab["regimes"]}


def meeting_residual_panel_zq(lab: Dict[str, object], *, lam: float = 100.0,
                              max_rank: Optional[int] = None) -> pd.DataFrame:
    """``date x code`` residual from a smooth per-meeting jump path, in bp.

    The exposure matrix is exact -- ZQ settles on precisely this blend -- so the
    only modelling choice is how smooth the jump path is forced to be. ``lam``
    penalises the **second difference** of the jump sequence, the same
    construction the SR3 kink lab uses, so a linearly accelerating policy path
    is fitted for free and only what such a path cannot express survives.

    The sweep matters more than any single ``lam``: the strip carries 12
    contracts against 8-9 identifiable meetings, so a loose fit tracks the strip
    almost exactly and reports a residual that is an artifact of its own
    flexibility rather than a dislocation.
    """
    max_rank = int(max_rank if max_rank is not None else lab["max_rank"])
    rates, rank, win = lab["rates"], lab["rank"], lab["windows"]
    exposure, meetings = lab["exposure"], lab["meetings"]
    m_arr = np.array([pd.Timestamp(m) for m in meetings])
    resid = pd.DataFrame(np.nan, index=rates.index, columns=rates.columns)
    for d in rates.index:
        row = rates.loc[d].dropna()
        legs = [k for k in row.index if rank.at[d, k] <= max_rank]
        if len(legs) < 6:
            continue
        lo = min(win[k][0] for k in legs)
        hi = max(win[k][1] for k in legs)
        sel = np.flatnonzero((m_arr >= pd.Timestamp(lo)) & (m_arr < pd.Timestamp(hi)))
        if sel.size == 0:
            continue
        W = np.vstack([exposure[k][sel] for k in legs])
        y = row[legs].to_numpy(dtype=float) * 100.0
        fit = solve_smooth_path(y, W, lam=float(lam))
        resid.loc[d, legs] = fit["resid"]
    return resid


def zq_cost_panel(lab: Dict[str, object], struct: Dict[str, object]) -> pd.DataFrame:
    """Per (date, key) round-trip cost in bp, honouring the half-tick onset.

    Unlike SR3, a ZQ package's cost is not constant: the front leg can be
    quoting in quarter-ticks while the back leg is still in half-ticks, so a
    spread straddling the onset costs 0.75bp rather than 1.0bp. Reported as a
    panel so the notebook can show how much of the sample is actually cheaper
    than the headline figure rather than assuming it away.

    **Masked to the gate.** A contract that expired years ago is trivially "past
    its half-tick onset", so an unmasked panel reports the cheap tick on every
    dead cell and grossly overstates how often the discount is available. NaN
    outside the structure's live window.
    """
    levels, w = struct["levels"], struct["weights"]
    gate = struct["gate"]
    idx = levels.index
    dates = np.array([d.date() for d in idx])
    out = pd.DataFrame(0.0, index=idx, columns=levels.columns)
    onset_of = {}
    for key in levels.columns:
        legs = key.split("-")
        tot = np.zeros(len(idx))
        for x, l in zip(w, legs):
            if l not in onset_of:
                onset_of[l] = half_tick_onset(l)
            half = dates >= onset_of[l]
            tot += abs(x) * np.where(half, ZQ_HALF_TICK_BP, ZQ_TICK_BP)
        out[key] = tot
    return out.where(gate.reindex(index=idx, columns=levels.columns).fillna(False))


def zq_shadow_block(signal: pd.DataFrame, lab: Dict[str, object],
                    struct: Dict[str, object], base, *, framework: str = "",
                    write: bool = True) -> pd.DataFrame:
    """Run the identical signal on the package's own outright legs.

    The SR3 shadow test asks whether a butterfly is worth its extra legs by
    running the same signal on the outright belly and on each belly-versus-wing
    spread. The ZQ analogue is simpler and sharper: a calendar spread is two
    outrights, each costing **1 contract = 0.5bp** round trip against the
    spread's 1.0bp, so if either leg alone carries the edge the spread is paying
    double for nothing.

    Each instrument pays its own contract count, which is the whole point --
    charging them all the spread's cost would manufacture the conclusion that
    the spread is best.
    """
    import dataclasses

    from RVUtils.MeanRev.engine import run_backtest

    rates, w = lab["rates"], struct["weights"]
    levels, gate = struct["levels"], struct["gate"]
    panels: Dict[str, pd.DataFrame] = {"package": levels}
    n_ct: Dict[str, float] = {"package": float(sum(abs(x) for x in w))}
    for j in range(len(w)):
        cols = {}
        for key in levels.columns:
            leg = key.split("-")[j]
            cols[key] = rates[leg] * 100.0 if leg in rates.columns else np.nan
        panels[f"leg{j}_outright"] = pd.DataFrame(cols).reindex(
            index=levels.index, columns=levels.columns)
        n_ct[f"leg{j}_outright"] = 1.0

    rows = []
    for name, lv in panels.items():
        cfg = dataclasses.replace(base, round_trip_cost_bp=n_ct[name] * ZQ_TICK_BP)
        res = run_backtest(cfg, levels=lv, signal=signal, gate=gate)
        m = res.metrics
        rows.append({"instrument": name, "n_contracts": n_ct[name],
                     "round_trip_bp": cfg.round_trip_cost_bp,
                     "n_trades": m["n_trades"],
                     "total_gross_bp": round(m["total_gross_bp"], 1),
                     "total_net_bp": round(m["total_net_bp"], 1),
                     "avg_net_bp": (round(m["avg_net_bp"], 3)
                                    if np.isfinite(m["avg_net_bp"]) else np.nan),
                     "hit_rate": (round(m["hit_rate"], 3)
                                  if np.isfinite(m["hit_rate"]) else np.nan),
                     "sharpe": (round(m["sharpe"], 3)
                                if np.isfinite(m["sharpe"]) else np.nan),
                     "net_usd": round(m["total_net_bp"] * ZQ_DV01_USD
                                      * base.n_packages, 0)})
    out = pd.DataFrame(rows)
    pkg = float(out.loc[out["instrument"] == "package", "total_net_bp"].iloc[0])
    out["beats_package"] = out["total_net_bp"] > pkg
    print("\nLINEAR-SHADOW DECOMPOSITION (same signal on each outright leg, own cost)")
    print(out.round(3).to_string(index=False))
    beat = out[out["instrument"] != "package"]["beats_package"].any()
    print(f"  -> {'SHADOWED - an outright leg beats the package' if beat else 'the package beats both outright legs'}")
    if write and framework:
        o = out.copy()
        o.insert(0, "framework", framework)
        p = DATA_DIR / "zq_shadow_tests.csv"
        if p.exists():
            old = pd.read_csv(p)
            o = pd.concat([old[old["framework"] != framework], o], ignore_index=True)
        o.to_csv(p, index=False)
    return out


def oracle_block(levels: pd.DataFrame, cost_bp: float, *,
                 masks: Optional[Dict[str, pd.DataFrame]] = None,
                 horizons: Sequence[int] = (5, 10, 21),
                 tag: str = "") -> pd.DataFrame:
    """The oracle ceiling, printed. Runs BEFORE anything is built on it.

    The SR3 lesson stated as a rule: a structure whose ``E[|forward move|]`` on
    the days a signal fires does not exceed its round trip cannot be rescued by
    a better signal, because that expectation is what a trader with perfect
    knowledge of the direction would capture.
    """
    t = oracle_table(levels, masks or {}, horizons=horizons, round_trip_bp=cost_bp)
    print(f"\nORACLE CEILING{' -- ' + tag if tag else ''} "
          f"(round trip {cost_bp}bp = {cost_bp * ZQ_DV01_USD:,.2f} $/contract)")
    print(t.round(3).to_string(index=False))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    t.to_csv(DATA_DIR / f"oracle{'_' + tag if tag else ''}.csv", index=False)
    return t


def implied_jump_panel(lab: Dict[str, object], struct: Dict[str, object], *,
                       min_exposure: float = 0.15) -> Dict[str, pd.DataFrame]:
    """What each adjacent-month spread says the next policy move is worth.

    A spread's differential exposure ``dW`` is how much of a single decision it
    carries, so ``jump = spread / dW`` is that pair's own read on the meeting, in
    bp of policy move. Two pairs straddling the same meeting should agree; the
    amount by which they do not **is** the FF kink, expressed in the units a
    trader thinks in (bp of jump) rather than bp of spread.

    ``min_exposure`` drops pairs that barely see a decision -- dividing a 1bp
    spread by an exposure of 0.02 manufactures a 50bp "implied jump" out of one
    tick of noise.
    """
    de = struct["diff_exposure"]
    lv = struct["levels"]
    keep = [k for k in lv.columns if de.get(k, 0.0) >= float(min_exposure)]
    jump = lv[keep].div(de[keep], axis=1)
    return {"jump": jump, "kept": keep,
            "dropped": [k for k in lv.columns if k not in keep]}


def zq_run_family(name: str, *, lab: Dict[str, object], struct: Dict[str, object],
                  signal_fn, grid_spec: Dict[str, Sequence],
                  params: Sequence[str], base, cls: str, note: str = "",
                  plot: bool = True, league: bool = True, show_trades: int = 20,
                  exits: Sequence[str] = ("z0", "band", "t5", "t10", "t21", "t42"),
                  ) -> Dict[str, object]:
    """The house ``run_family``, with the SR3 butterfly shadow swapped for ZQ's.

    Byte-for-byte the same sequence as ``sfr_fly_meanrev_common.run_family`` --
    grid, distribution, neighbourhood, sign test, best config, equity in bp and
    dollars, trade log, exit comparison, cost curve, regime split, shadow,
    median-config control, league rows -- so a ZQ row and an SR3 row in the same
    league table mean the same thing. Only the shadow differs, because a
    calendar spread's linear shadows are its two outright legs and not a
    butterfly's belly and wings.
    """
    import dataclasses

    import matplotlib.pyplot as plt

    from RVUtils.MeanRev.engine import grid_search, run_backtest

    levels, gate = struct["levels"], struct["gate"]
    print(f"\n### GRID  ({len(levels.columns)} keys, {len(levels)} sessions, "
          f"round trip {base.round_trip_cost_bp}bp)")
    grid = grid_search(grid_spec, levels=levels, signal=None, gate=gate,
                       base=base, signal_fn=signal_fn, show_progress=True)
    best = grid_block(grid, params)
    stability_block(grid, best, params)
    sign_test(grid, framework=name)

    sig_best = signal_fn(levels, **signal_params_from_row(best, params))
    cfg_best = config_from_row(base, best, params)
    res = run_backtest(cfg_best, levels=levels, signal=sig_best, gate=gate)
    header_block(f"{name} - best config", res, grid=grid, note=note)
    if plot:
        three_panel_equity(res, f"{name} - best config")
        plt.show()
    if not res.trades.empty:
        print("\n  trade log (first rows):")
        print(res.trades.sort_values("entry").head(show_trades).to_string(index=False))
    print("\n  exit comparison:")
    print(exit_comparison(cfg_best, levels=levels, signal=sig_best, gate=gate,
                          exits=tuple(exits)).round(3).to_string(index=False))
    cost_block(res)
    regime_block(res, struct["regimes"], framework=name)
    zq_shadow_block(sig_best, lab, struct, cfg_best, framework=name)

    med = median_row(grid)
    sig_med = signal_fn(levels, **signal_params_from_row(med, params))
    res_med = run_backtest(config_from_row(base, med, params), levels=levels,
                           signal=sig_med, gate=gate)
    header_block(f"{name} - MEDIAN config (the anti-selection control)", res_med,
                 grid=grid)

    if league:
        league_row(name, "best-config", res, grid=grid, cls=cls, note=note,
                   window="zq", structure=f"{struct['n_legs']}leg")
        league_row(name, "median-config", res_med, grid=grid, cls=cls,
                   note="median of the sweep, not selected",
                   window="zq", structure=f"{struct['n_legs']}leg")
    return {"grid": grid, "best": best, "config": cfg_best, "result": res,
            "median_result": res_med, "signal": sig_best}

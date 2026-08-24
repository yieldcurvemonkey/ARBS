r"""One sample, end to end: inputs, grid, two nulls, deflation, diagnostics.

Kept out of the notebook so the notebook can show results rather than plumbing,
and so the same code runs from a shell for the long FedLock legs. Every number
the notebook prints comes from :func:`run_sample`; nothing is recomputed by
hand in a cell.
"""
from __future__ import annotations

import dataclasses
import pathlib
import sys
import time
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _p in (str(HERE), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fed_detachment_data as D  # noqa: E402
import fed_detachment_grid as G  # noqa: E402
import fed_detachment_prices as PX  # noqa: E402
import fed_sentiment_lead_data as L  # noqa: E402

SR3_STRUCTURES = ("out1", "out2", "out3", "out4", "spr1x3", "spr2x4", "pack1")
ALL_STRUCTURES = SR3_STRUCTURES + ("ois2y",)


def run_sample(
    *,
    label: str,
    source: str = "jpm",
    structures: Sequence[str] = ALL_STRUCTURES,
    start: Optional[str] = None,
    end: Optional[str] = None,
    rotation_draws: Optional[int] = None,
    spectral_draws: int = 400,
    cfg: Optional[D.DetachConfig] = None,
    min_trades: int = 8,
    entry_lag_sessions: Optional[int] = None,
    cost_bp_one_way: Optional[float] = None,
    constructions: Optional[Sequence[str]] = None,
    week_anchor: Optional[str] = None,
    verbose: bool = True,
) -> Dict[str, object]:
    """Everything for one (sample, instrument set) pair.

    ``start`` exists because SR3 does not trade before 2018-05 while FedLock
    runs from 1985: a grid that mixes an instrument which cannot be priced for
    two thirds of the support with one that can is not a like-for-like
    comparison, so the two are run as separate samples with their own nulls
    rather than as one grid with holes in it.
    """
    t_start = time.time()
    cfg = cfg or D.PRIMARY
    cfg = dataclasses.replace(cfg, source=source)
    if entry_lag_sessions is not None:
        cfg = dataclasses.replace(cfg, entry_lag_sessions=int(entry_lag_sessions))
    if cost_bp_one_way is not None:
        cfg = dataclasses.replace(cfg, cost_bp_one_way=float(cost_bp_one_way))

    def _say(msg: str) -> None:
        if verbose:
            print(f"[{label}] {msg}", flush=True)

    lead_cfg = L.LeadConfig()
    if week_anchor is not None:
        lead_cfg = dataclasses.replace(lead_cfg, week_anchor=str(week_anchor))
    constructions = tuple(constructions or D.CONSTRUCTIONS)

    zc, zs, prov = D.load_sides(cfg, lead_cfg)
    bank = G.build_signal_bank(zc, zs, cfg, constructions=constructions)
    support = G.common_support(bank)
    full_support = support
    if start is not None:
        support = support[support >= pd.Timestamp(start)]
    if end is not None:
        support = support[support <= pd.Timestamp(end)]
    _say(f"support {len(support)} weeks {support.min().date()}..{support.max().date()} "
         f"(of {len(full_support)} where every construction is defined)")

    rate = PX.curve_store_par_rate(2) if "ois2y" in structures else None
    rate_gate = PX.gate_rate_sanity(rate, name="2y SOFR par") if rate is not None else None
    panel = pd.DataFrame()
    if any(s not in D.NON_FUTURES for s in structures):
        syms = PX.sr3_universe(support.min().date(),
                               support.max().date() + pd.Timedelta(weeks=12), 4)
        panel = PX.settle_panel(syms)
    return_bank, return_diag = G.build_return_bank(
        panel, support, cfg, structures=structures, rate=rate)

    keys = G.cell_keys(constructions=constructions, structures=structures)
    league, dmat, streams, keys, key_row, streams_both = G.run_grid(
        bank, return_bank, support, cfg, keys=keys, min_trades=min_trades)
    observed, best, sharpes = G.grid_statistic(dmat, keys, key_row, return_bank, cfg,
                                               min_trades=min_trades)
    _say(f"{len(keys)} cells, best weekly Sharpe {observed:.4f} at {keys[best]}")

    t0 = time.time()
    rot = G.rotation_null(dmat, keys, key_row, return_bank, cfg, draws=rotation_draws,
                          min_trades=min_trades, show_progress=False)
    p_rot = G.rotation_pvalue(observed, rot)
    _say(f"rotation null {rot['draws_used']}/{rot['distinct_rotations']} "
         f"(exhaustive={rot['exhaustive']}) q50 {rot['q50']:.4f} q95 {rot['q95']:.4f} "
         f"floor {rot['p_floor']:.4f} -> p {p_rot:.4f}  [{time.time()-t0:.0f}s]")

    spec, p_spec = None, np.nan
    if spectral_draws:
        t0 = time.time()
        spec = G.spectral_null(zc, zs, support, keys, return_bank, cfg,
                               draws=spectral_draws, min_trades=min_trades)
        p_spec = G.rotation_pvalue(observed, spec)
        _say(f"spectral null {spec['draws_used']} draws q50 {spec['q50']:.4f} "
             f"q95 {spec['q95']:.4f} -> p {p_spec:.4f}  [{time.time()-t0:.0f}s]")

    family = G.family_test(sharpes, rot, league)
    _say(f"Romano-Wolf stepdown: {family.get('n_rejected')} of "
         f"{family.get('n_tested')} cells survive familywise control at 5%")

    deflation = G.deflate(streams_both, league)
    _say(f"DSR {deflation.get('dsr', float('nan')):.4f} "
         f"(best {deflation.get('best_sharpe', float('nan')):.4f} vs SR0 "
         f"{deflation.get('sr0', float('nan')):.4f}, N {deflation.get('n_trials_raw')} "
         f"-> N_eff {deflation.get('n_trials_effective', float('nan')):.0f} bailey / "
         f"{deflation.get('n_eff_evt_mc', float('nan')):.0f} evt_mc)")

    bj = int(np.nanargmax(sharpes)) if np.isfinite(sharpes).any() else -1
    flip = {}
    if bj >= 0:
        # recomputed rather than read off the zero-padded stream: a trade whose
        # NET P&L lands exactly on zero -- possible, since settles sit on a tick
        # lattice and the cost is a round number -- is indistinguishable from a
        # week with no trade once it is in the stream, and would silently drop
        # out of the sign-flip reference set
        c, k, thr, h, struct = keys[bj]
        cost_b = (2.0 * cfg.cost_bp_one_way * D.STRUCTURES[struct][2]
                  / D.STRUCTURES[struct][3])
        _sr, _sg, _ix, pnl = G.best_of_both(
            dmat[key_row[bj]], return_bank[(struct, int(h))], threshold=float(thr),
            horizon=int(h), cost_bp=cost_b, n_weeks=len(support), min_trades=min_trades)
        flip = G.sign_flip_pvalue(pnl, rng=cfg.rng(21))
        _say(f"sign-flip on the winner: |SR/trade| {flip['observed']:.4f} "
             f"p {flip['p']:.4f}")

    primary = league[(league.construction == cfg.construction)
                     & (league.lead_k == cfg.lead_k)
                     & (league.threshold == cfg.threshold)
                     & (league.horizon_w == cfg.horizon_w)
                     & (league.structure == cfg.structure)]

    out = {
        "label": label, "cfg": cfg, "prov": prov,
        "z_composite": zc, "z_sentiment": zs, "bank": bank,
        "support": support, "full_support": full_support,
        "panel": panel, "rate": rate, "rate_gate": rate_gate,
        "return_bank": return_bank, "return_diag": return_diag,
        "league": league, "dmat": dmat, "streams": streams,
        "streams_both": streams_both, "keys": keys, "key_row": key_row,
        "sharpes": sharpes, "observed": observed, "best_index": bj,
        "best_key": keys[bj] if bj >= 0 else None,
        "rotation": rot, "p_rotation": p_rot,
        "spectral": spec, "p_spectral": p_spec,
        "deflation": deflation, "sign_flip": flip, "family": family,
        "primary_row": primary, "seconds": time.time() - t_start,
    }
    _say(f"done in {out['seconds']:.0f}s")
    return out


#: The robustness sweep. Each entry is (label, kwargs for run_sample, note).
#:
#: These are NOT extra grid cells and they are not deflated with the grid: each
#: one asks whether a *convention* is what produced the headline, and the answer
#: that matters is that none of them turns a dead grid into a live one. Reporting
#: them as further trials would be the wrong accounting in the other direction --
#: a robustness check that cannot rescue a null result costs the null nothing.
ROBUSTNESS: List[dict] = [
    dict(label="frozen", kwargs={}),
    dict(label="same-day fill",
         kwargs=dict(entry_lag_sessions=0),
         note="fills at the settle the signal was read from -- the optimistic timing"),
    dict(label="cost 0.125bp one-way",
         kwargs=dict(cost_bp_one_way=0.125),
         note="the handover's reading of the cost line, half the frozen one"),
    dict(label="cost ZERO",
         kwargs=dict(cost_bp_one_way=0.0),
         note="is there anything there GROSS? separates a cost problem from a signal problem"),
    dict(label="sentiment z 104w/52",
         kwargs=dict(sent_z_window_w=104, sent_z_min_w=52),
         note="a slower standardisation, at the price of half the tradeable sample"),
    dict(label="sentiment z 26w/13",
         kwargs=dict(sent_z_window_w=26, sent_z_min_w=13),
         note="a faster one, which buys sample back"),
    dict(label="gap+dchg only, maximal support",
         kwargs=dict(constructions=("gap", "dchg")),
         note="drops the two constructions whose rolling window costs 25 weeks"),
    dict(label="Wednesday weeks",
         kwargs=dict(week_anchor="W-WED"),
         note="is the answer a property of Friday?"),
]


def run_robustness(*, source: str = "jpm", structures: Sequence[str] = ALL_STRUCTURES,
                   start: Optional[str] = None, rotation_draws: Optional[int] = None,
                   spectral_draws: int = 0, verbose: bool = True) -> pd.DataFrame:
    """Every entry in :data:`ROBUSTNESS`, as one table."""
    rows = []
    for spec in ROBUSTNESS:
        kw = dict(spec["kwargs"])
        cfg = D.PRIMARY
        for knob in ("sent_z_window_w", "sent_z_min_w"):
            if knob in kw:
                cfg = dataclasses.replace(cfg, **{knob: kw.pop(knob)})
        constructions = kw.pop("constructions", None)
        anchor = kw.pop("week_anchor", None)
        res = run_sample(label=spec["label"], source=source, structures=structures,
                         start=start, rotation_draws=rotation_draws,
                         spectral_draws=spectral_draws, cfg=cfg,
                         constructions=constructions, week_anchor=anchor,
                         verbose=verbose, **kw)
        rot = res["rotation"]
        rows.append({
            "variant": spec["label"], "note": spec.get("note", ""),
            "weeks": len(res["support"]), "cells": len(res["keys"]),
            "best_sharpe": res["observed"],
            # A short sample has NO valid rotation set: ``min_offset`` is 39 and
            # a rotation needs 3x that to exist at all, so a 69-week variant
            # cannot be tested this way and says so rather than reporting a NaN
            # that reads like a missing number.
            "rotations": int(rot.get("draws_used", 0)),
            "null_median": rot["q50"],
            "null_q95": rot["q95"],
            "p_rotation": res["p_rotation"],
            "p_floor": rot["p_floor"],
            "best_cell": f"{res['best_key']}" if res["best_key"] else None,
            "DSR": res["deflation"].get("dsr", np.nan),
            "RW_rejected": res["family"].get("n_rejected"),
        })
    out = pd.DataFrame(rows)
    out["verdict"] = np.where(
        out["rotations"] == 0,
        "sample too short to rotate -- read the DSR",
        np.where(out["p_rotation"] < 0.05, "CLEARS", "dead"))
    return out


def headline(res: Dict[str, object]) -> pd.Series:
    """The five numbers that decide the question, for one sample."""
    lg = res["league"]
    best = lg.iloc[int(res["best_index"])] if res["best_index"] >= 0 else None
    d = res["deflation"]
    return pd.Series({
        "sample": res["label"],
        "weeks": len(res["support"]),
        "cells": len(res["keys"]),
        "best_sharpe_weekly": res["observed"],
        "best_sharpe_ann": res["observed"] * np.sqrt(52.0),
        "best_cell": None if best is None else
        f"{best['construction']}/k{best['lead_k']}/thr{best['threshold']}/"
        f"h{best['horizon_w']}/{best['structure']}/{best['sign']}",
        "best_trades": None if best is None else int(best["trades"]),
        "best_avg_bp": None if best is None else float(best["avg_bp"]),
        "null_median_sharpe": res["rotation"]["q50"],
        "null_q95_sharpe": res["rotation"]["q95"],
        "p_rotation": res["p_rotation"],
        "p_rotation_floor": res["rotation"]["p_floor"],
        "p_spectral": res["p_spectral"],
        "DSR": d.get("dsr", np.nan),
        "SR0": d.get("sr0", np.nan),
        "RW_rejected": res["family"].get("n_rejected"),
        "RW_tested": res["family"].get("n_tested"),
    })


def league_summary(league: pd.DataFrame, by: str) -> pd.DataFrame:
    g = league.groupby(by)
    return pd.DataFrame({
        "best_sharpe": g["sharpe"].max(),
        "median_sharpe": g["sharpe"].median(),
        "best_avg_bp": g["avg_bp"].max(),
        "median_avg_bp": g["avg_bp"].median(),
        "cells": g.size(),
    }).sort_values("best_sharpe", ascending=False)


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--source", default="jpm")
    ap.add_argument("--structures", default="all", help="'all', 'sr3', 'ois2y'")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--rotation-draws", type=int, default=None)
    ap.add_argument("--spectral-draws", type=int, default=400)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)

    structures = {"all": ALL_STRUCTURES, "sr3": SR3_STRUCTURES,
                  "ois2y": ("ois2y",)}.get(a.structures)
    if structures is None:
        structures = tuple(a.structures.split(","))

    res = run_sample(label=a.label, source=a.source, structures=structures,
                     start=a.start, end=a.end, rotation_draws=a.rotation_draws,
                     spectral_draws=a.spectral_draws)
    pd.set_option("display.width", 240)
    pd.set_option("display.max_columns", 40)
    print("\nHEADLINE")
    print(headline(res).to_string())
    print("\nPRE-REGISTERED PRIMARY")
    print(res["primary_row"].to_string(index=False))
    print("\nTOP 15")
    print(res["league"].sort_values("sharpe", ascending=False).head(15).to_string(index=False))
    for axis in ("structure", "construction", "lead_k", "horizon_w", "threshold", "sign"):
        print(f"\nBY {axis.upper()}")
        print(league_summary(res["league"], axis).to_string())
    if a.out:
        res["league"].to_parquet(a.out)
        print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

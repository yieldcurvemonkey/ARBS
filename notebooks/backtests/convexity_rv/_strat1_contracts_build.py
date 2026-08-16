"""Artifact builder for the strategy-1 study on **REAL LISTED CONTRACTS**.

Builds every parquet/CSV/JSON that ``strat1_listed_contracts.ipynb`` and
``strat1_threeway_contracts.ipynb`` read, so the notebooks stay a report over
stored artifacts rather than a second implementation of the study.

**Zero engine runs, zero network.** Everything is a pure function of three
files that already exist on disk and are not being written by anything else:

* ``strat1_signal_panel.parquet``   -- strategy 1's own curve breakeven and the
  1Yx30Y swaption ATMF, per (date, structure). The curve side is REUSED, never
  recomputed, so the real-contract run and the constant-maturity control share
  bit-identical curve rows and the only thing that differs between them is the
  listed benchmark.
* ``ust_listed_vol.parquet``        -- the constant-maturity panel. The CONTROL.
* ``listed_contract_vol.parquet``   -- the real contracts. The treatment.

plus ``ust_ctd_fv01.parquet`` (optional; only for the straddle's contract count)
and the four stored ``strat1_cohorts_*.parquet`` tables (only for the gate
books, which are derived arithmetically -- see ``strat1_threeway``'s linearity
identity).

Usage (from the repo root, conda env ``stir``)::

    python notebooks/backtests/convexity_rv/_strat1_contracts_build.py panels
    python notebooks/backtests/convexity_rv/_strat1_contracts_build.py payoff
    python notebooks/backtests/convexity_rv/_strat1_contracts_build.py threeway
    python notebooks/backtests/convexity_rv/_strat1_contracts_build.py all

``payoff`` is split out because it is the only slow command: it builds one
Breeden-Litzenberger density per (date, contract) through the shared
``swaption_cube`` kernel, which prices a Bachelier call at each of 2,001 strikes
in a Python loop. At ~1,900 densities that is minutes, against seconds for
everything else, and it feeds a SECONDARY signal -- so it is a separate step
that the other commands do not wait on.
"""

from __future__ import annotations

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import json
import pathlib
import sys
import time
from typing import Any, Dict

import numpy as np
import pandas as pd

_REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO))

from RVUtils.ConvexityRV import listed_contracts as lc
from RVUtils.ConvexityRV import listed_vol as lv
from RVUtils.ConvexityRV import strat1_listed as sl
from RVUtils.ConvexityRV import strat1_real_contracts as rc
from RVUtils.ConvexityRV import strat1_threeway as tw

DATA = _REPO / "notebooks" / "data" / "convexity_rv"

#: Every artifact this script writes, so the notebook can assert on presence.
ARTIFACTS = {
    "panel": "strat1_contracts_panel.parquet",
    "cm_control": "strat1_contracts_cm_control.parquet",
    "selection": "strat1_contracts_selection.csv",
    "roll": "strat1_contracts_roll.csv",
    "ageing": "strat1_contracts_ageing.csv",
    "cm_vs_real": "strat1_contracts_cm_vs_real.csv",
    "straddle": "strat1_contracts_straddle.parquet",
    "straddle_summary": "strat1_contracts_straddle_summary.csv",
    "smile": "strat1_contracts_smile.parquet",
    "expected_payoff": "strat1_contracts_expected_payoff.parquet",
    "verdict": "strat1_contracts_verdict.json",
    "tw_basis": "strat1_threeway_contracts_basis.parquet",
    "tw_books": "strat1_threeway_contracts_books.parquet",
    "tw_sweep": "strat1_threeway_contracts_sweep.csv",
    "tw_verdict": "strat1_threeway_contracts_verdict.json",
}

HEADLINE = f"{rc.HEADLINE_ROOT}@{rc.HEADLINE_TARGET}"
#: The constant-maturity benchmark the real one is compared against. Same ROOT
#: (US) and the shortest, best-populated constant maturity -- so the comparison
#: isolates "real contract vs interpolation", not "US vs UL".
CM_HEADLINE = f"{rc.HEADLINE_ROOT}_30"


def _p(name: str) -> pathlib.Path:
    return DATA / ARTIFACTS[name]


def load_inputs() -> Dict[str, Any]:
    """The three stable inputs, loaded once. Nothing here is fetched."""
    s1 = pd.read_parquet(DATA / "strat1_signal_panel.parquet")
    s1["date"] = pd.to_datetime(s1["date"])
    contracts = lc.load_listed_contract_panel(roots=list(rc.REAL_ROOTS))
    cm = lv.load_ust_cm_panel()
    fv01 = None
    p = DATA / "ust_ctd_fv01.parquet"
    if p.exists():
        fv01 = pd.read_parquet(p)
    return {"s1": s1, "contracts": contracts, "cm": cm, "fv01": fv01}


def load_cohorts() -> Dict[str, pd.DataFrame]:
    """Strategy 1's stored cohort tables, one per long-end structure."""
    out: Dict[str, pd.DataFrame] = {}
    for label, _f, _b in rc.RealContractConfig().structures:
        p = DATA / f"strat1_cohorts_{label.replace('/', '-').replace(' ', '_')}.parquet"
        if p.exists():
            out[label] = pd.read_parquet(p)
    return out


# ---------------------------------------------------------------------- panels


def cmd_panels() -> None:
    t0 = time.time()
    inp = load_inputs()
    cfg = rc.RealContractConfig()

    real = rc.build_longend_contract_panel(inp["s1"], inp["contracts"], cfg)
    real.reset_index().to_parquet(_p("panel"), index=False)
    print(f"panel        {real.shape}  -> {_p('panel').name}", flush=True)

    # The CONTROL, rebuilt here from the same stable inputs rather than read from
    # another run's output -- so its curve rows are provably the same object the
    # real panel used, and no concurrently-running job can move it underneath.
    cm_panel = sl.build_longend_listed_panel(inp["s1"], inp["cm"], cfg.listed_config())
    cm_panel.reset_index().to_parquet(_p("cm_control"), index=False)
    print(f"cm_control   {cm_panel.shape}  -> {_p('cm_control').name}", flush=True)

    #: ``cm_control_days`` must name the constant maturity the study actually
    #: compares against (``CM_HEADLINE``), not the target -- see the function's
    #: docstring for the 0.0 that the naive version reports on the H365 row.
    sel = rc.contract_selection_report(
        real, inp["contracts"], cm_control_days=int(CM_HEADLINE.split("_")[1]))
    sel.to_csv(_p("selection"), index=False)
    print(f"selection    {sel.shape}", flush=True)

    roll = rc.contract_roll_report(real)
    roll.to_csv(_p("roll"), index=False)
    print(f"roll         {roll.shape}", flush=True)

    age = rc.ageing_table(inp["contracts"], inp["cm"])
    age.to_csv(_p("ageing"), index=False)
    print(f"ageing       {age.shape}", flush=True)

    cvr = rc.cm_vs_real_table(real, cm_panel, real_symbol=HEADLINE, cm_symbol=CM_HEADLINE)
    cvr.to_csv(_p("cm_vs_real"), index=False)
    print(f"cm_vs_real   {cvr.shape}", flush=True)

    head = real.reset_index()
    head = head[head["listed_symbol"] == HEADLINE]
    st = rc.funded_straddle_frame(head, inp["fv01"], cfg)
    st.to_parquet(_p("straddle"), index=False)
    sts = rc.funded_straddle_summary(st)
    sts.to_csv(_p("straddle_summary"), index=False)
    print(f"straddle     {st.shape} / summary {sts.shape}", flush=True)

    smile = rc.real_smile_frame(inp["contracts"])
    smile.to_parquet(_p("smile"), index=False)
    print(f"smile        {smile.shape}", flush=True)
    print(f"panels done in {time.time() - t0:.0f}s", flush=True)


# ------------------------------------------------------------- expected payoff


def cmd_payoff() -> None:
    """The density-based signal. Slow, secondary, and separate for that reason."""
    t0 = time.time()
    cfg = rc.RealContractConfig()
    real = pd.read_parquet(_p("panel"))
    smile = pd.read_parquet(_p("smile"))
    head = real[real["listed_symbol"] == HEADLINE]
    if head.empty:
        raise SystemExit(f"no {HEADLINE} rows in the stored panel; run `panels` first")
    ep = rc.real_expected_payoff_frame(head, smile, cfg=cfg)
    ep.to_parquet(_p("expected_payoff"), index=False)
    shares = ep["ep_status"].value_counts(normalize=True).to_dict()
    print(f"expected_payoff {ep.shape} statuses={ {k: round(v, 4) for k, v in shares.items()} } "
          f"in {time.time() - t0:.0f}s", flush=True)


# -------------------------------------------------------------------- threeway


def cmd_threeway() -> None:
    t0 = time.time()
    cfg = tw.longend_config()
    real = pd.read_parquet(_p("panel"))
    cm_panel = pd.read_parquet(_p("cm_control"))
    cohorts = load_cohorts()

    frames = rc.real_threeway_frames(real, cfg)
    three = frames[HEADLINE]
    print(f"frames       {sorted(frames)}", flush=True)

    basis = tw.longend_basis_frame(real, cfg)
    basis.to_parquet(_p("tw_basis"), index=False)
    print(f"basis        {basis.shape}", flush=True)

    # One gate book per (gate mode, structure), scored on strategy 1's own stored
    # cohorts. No engine run: swap NPV is linear in bpv, which
    # ``_strat1_threeway_longend_build.py verify`` ties out against the engine.
    books = tw.all_gate_books(three, cohorts, cfg) if cohorts else None
    if books is not None:
        books.to_parquet(_p("tw_books"), index=False)
        print(f"books        {books.shape}", flush=True)

    sweep = _real_sweep(real, cfg)
    sweep.to_csv(_p("tw_sweep"), index=False)
    print(f"sweep        {sweep.shape}", flush=True)

    # The CM control's own three-way frame, at the SAME root and the shortest
    # constant maturity, so the gate comparison is real-vs-interpolated and not
    # US-vs-UL.
    cm_sel = tw.select_longend_benchmark(cm_panel, role=None, root=rc.HEADLINE_ROOT,
                                         cm_days=30)
    three_cm = tw.threeway_frame(cm_sel, cfg)

    inp_cm = lv.load_ust_cm_panel()
    verdict = rc.real_contract_verdict(
        three, basis[basis["listed_symbol"] == HEADLINE],
        three_cm=three_cm,
        cm_vs_real=pd.read_csv(_p("cm_vs_real")),
        selection=pd.read_csv(_p("selection")),
        rolls=pd.read_csv(_p("roll")),
        straddle=pd.read_csv(_p("straddle_summary")),
        ep=(pd.read_parquet(_p("expected_payoff")) if _p("expected_payoff").exists() else None),
        ul_penalty=rc.unavailable_root_penalty(inp_cm),
        books=books, cohorts=cohorts or None, cfg=cfg,
    )
    verdict["artifacts"] = ARTIFACTS
    _write_json(_p("tw_verdict"), verdict)
    _write_json(_p("verdict"), verdict)
    print(f"verdict      -> {_p('tw_verdict').name}", flush=True)
    print(f"threeway done in {time.time() - t0:.0f}s", flush=True)


def _real_sweep(panel: pd.DataFrame, cfg: "tw.Strat1ThreeWayConfig") -> pd.DataFrame:
    """``benchmark_sweep_table`` over the real benchmarks.

    Not a call to that function: it keys on ``listed_role`` x ``listed_cm_days``,
    which on the real panel would collapse US@D30 and US@H365 onto the same role.
    Same columns, selected by ``listed_symbol`` instead.
    """
    frames = rc.real_threeway_frames(panel, cfg)
    meta = panel.reset_index() if "date" not in panel.columns else panel
    rows = []
    for sym, three in frames.items():
        agree = tw.agreement_table(three).set_index("structure")
        ranks = tw.rank_table(three).set_index("structure")
        flips = tw.flip_threshold_table(three, include_reference=False).set_index("structure")
        trans = tw.transition_table(three).set_index("structure")
        df = three.reset_index()
        df = df[df["usable"].to_numpy(bool)]
        m = meta[meta["listed_symbol"] == sym]
        for label, g in df.groupby("structure", sort=True):
            rows.append({
                "benchmark": sym,
                "listed_root": (str(m["listed_root"].iloc[0]) if len(m) else None),
                "listed_target": (str(m["listed_target"].iloc[0]) if len(m) else None),
                "structure": label,
                "is_headline": bool(sym == HEADLINE),
                "n_days": int(len(g)),
                "first": str(g["date"].min().date()), "last": str(g["date"].max().date()),
                "frac_cheapest_curve": float(ranks.loc[label, "frac_cheapest_curve"]),
                "frac_cheapest_swaption": float(ranks.loc[label, "frac_cheapest_swaption"]),
                "frac_cheapest_listed": float(ranks.loc[label, "frac_cheapest_listed"]),
                "frac_days_ranking_changes": float(trans.loc[label, "frac_days_ranking_changes"]),
                "median_curve_bp_day": float(ranks.loc[label, "median_curve_bp_day"]),
                "median_swaption_bp_day": float(ranks.loc[label, "median_swaption_bp_day"]),
                "median_listed_bp_day": float(ranks.loc[label, "median_listed_bp_day"]),
                "frac_disagree": float(agree.loc[label, "frac_disagree"]),
                "median_basis_bp_day": float(flips.loc[label, "median_basis_bp_day"]),
                "median_abs_basis_bp_day": float(flips.loc[label, "median_abs_basis_bp_day"]),
                "flip_p25_bp_day": float(flips.loc[label, "flip_p25_bp_day"]),
                "shortfall_multiple_p25": float(flips.loc[label, "shortfall_multiple_p25"]),
                "frac_curve_at_sentinel": float(flips.loc[label, "frac_curve_at_sentinel"]),
            })
    return pd.DataFrame(rows).sort_values(["structure", "benchmark"]).reset_index(drop=True)


def _write_json(path: pathlib.Path, obj: Any) -> None:
    def _default(o: Any) -> Any:
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            v = float(o)
            return v if np.isfinite(v) else None
        if isinstance(o, (np.bool_,)):
            return bool(o)
        if isinstance(o, (pd.Timestamp,)):
            return str(o)
        if isinstance(o, (np.ndarray,)):
            return o.tolist()
        return str(o)

    path.write_text(json.dumps(obj, indent=2, default=_default), encoding="utf-8")


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "all"
    if cmd in ("panels", "all"):
        cmd_panels()
    if cmd in ("payoff", "all"):
        cmd_payoff()
    if cmd in ("threeway", "all"):
        cmd_threeway()
    if cmd not in ("panels", "payoff", "threeway", "all"):
        raise SystemExit(f"unknown command {cmd!r}; use panels|payoff|threeway|all")


if __name__ == "__main__":
    main(sys.argv)

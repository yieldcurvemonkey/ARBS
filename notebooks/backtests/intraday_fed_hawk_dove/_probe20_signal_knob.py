"""Check the macro-state knob against something other than itself.

A conditioning rule is the easiest thing in a backtest to get silently wrong. A
rule that never fires produces a perfectly plausible book; a rule that fires on
the wrong rows produces one too; and a join that matches nothing produces the
first while looking like the second. So seven independent routes, and two of
them do not use the knob at all.

    1. ``mode="off"`` reproduces the module as it was BEFORE the knob existed,
       trade for trade -- the pre-change file is loaded from the primary
       checkout and run side by side, not trusted to be equivalent.
    2. the join matches a real, non-trivial share of events, and its coverage is
       reported per year -- a state that starts in 2023 turns "condition on the
       data" into "trade only the SR3 era", and that would look like a result.
    3. every state a trade reads was stamped STRICTLY BEFORE its entry session.
    4. ``mode="flip"`` leaves the BOOK untouched: same tags, same entries, same
       exits, same ``d_rate_bp``. Only the side moves. That is what makes the
       comparison against the baseline paired.
    5. the flipped book equals the baseline book negated afterwards on exactly
       the rows the rule selects -- computed without the knob.
    6. ``when="agree"`` and ``when="disagree"`` flip disjoint, complementary
       subsets of the in-band events, and neither ever touches an out-of-band one.
    7. a typo raises, and ``mode="size"`` never books a zero.

Run it as a plain process; it needs the warm bar cache and cannot fetch.

    conda run -n stir python notebooks/backtests/intraday_fed_hawk_dove/_probe20_signal_knob.py
"""
from __future__ import annotations

import importlib.util
import io
import pickle
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
#: The primary checkout, whose hawk_dove_config.py has no macro-state knob.
PRE = Path(r"C:\Users\chris\clee\ARBS")
for _p in (str(REPO), str(REPO / "notebooks" / "rv"), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP  # noqa: E402

import global_hawk_dove_common as G  # noqa: E402
import hawk_dove_config as HC  # noqa: E402
import fed_signal_overlay as SIG  # noqa: E402

CACHE = HERE / "_global_cache"
FAILS = []

#: The notebook's active config, verbatim, minus the signal block.
CONFIG = {
    "name": "baseline",
    "bank": "FED",
    "instrument": {"kind": "outright", "rank": 3},
    "timing": {"entry_offset_min": -60, "exit_offset_min": 240,
               "max_staleness_min": 45, "retime_synthetic": False},
    "filters": {"start": "2022-01-01", "end": None, "voters": "voters",
                "roles": None, "speakers_include": None, "speakers_exclude": None,
                "timestamp_source": "all", "min_abs_bucket": 1, "direction": "both",
                "era": "SR3", "days_to_fomc_max": None, "days_to_fomc_min": 10,
                "weekdays": None},
    "sizing": "equal",
    "cost_bp": 0,
}


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}   {detail}", flush=True)
    if not ok:
        FAILS.append(name)


def load_pre_change_module():
    """The hawk_dove_config.py as it stands on the primary checkout."""
    p = PRE / "notebooks" / "backtests" / "intraday_fed_hawk_dove" / "hawk_dove_config.py"
    src = p.read_text(encoding="utf-8")
    if "fed_signal_overlay" in src:
        raise RuntimeError(f"{p} already has the knob -- it is not a pre-change control")
    spec = importlib.util.spec_from_file_location("hawk_dove_config_pre", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def cfg(**over):
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in CONFIG.items()}
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


def main() -> None:
    G.load_bar_cache(CACHE / "bars.pkl")
    with open(CACHE / "events_manual_raw.pkl", "rb") as f:
        raw = pickle.load(f)["FED"]["events"]
    mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
    print(f"raw events {len(raw)}   bar cache {len(G._BAR_CACHE):,}\n")

    OLD = load_pre_change_module()

    # -- 1. the knob at rest changes nothing --------------------------------
    print('--- 1. mode="off" vs the module before the knob existed ---')
    for name, c in [("voters-only (the notebook's config)", cfg()),
                    ("whole book", cfg(filters={"voters": "all"})),
                    ("non-voters faded", cfg(filters={"voters": "all"},
                                             flip="nonvoters"))]:
        a = OLD.run_config(c, raw, mdp).closed
        b = HC.run_config({**c, "signal": {"mode": "off"}}, raw, mdp).closed
        cols = [x for x in a.columns if x in b.columns]
        same = (len(a) == len(b) and
                a[cols].reset_index(drop=True).equals(b[cols].reset_index(drop=True)))
        check(f"{name}: identical", same, f"{len(a)} vs {len(b)} trades")
        if len(b):
            check(f"{name}: signal_flip is +1 on every row",
                  bool((b["signal_flip"] == 1.0).all()),
                  f"{int((b['signal_flip'] < 0).sum())} flipped")

    # -- 2. the join ---------------------------------------------------------
    print("\n--- 2. the join matches a real share of events ---")
    for st in ("data", "detach"):
        sig = SIG.normalise({"mode": "flip", "state": st, "lead_w": 5})
        try:
            state, prov = SIG.build_state(sig)
        except RuntimeError as e:
            check(f"state {st!r} builds", False, str(e)[:60])
            continue
        rep = SIG.join_report(raw, state, sig)
        allrow = rep.loc["ALL"]
        check(f"state {st!r} builds", True,
              f"{prov.get('weeks')} weeks {prov.get('first')}..{prov.get('last')}")
        check(f"state {st!r}: match rate is non-trivial",
              float(allrow["match_rate"]) > 0.10,
              f"{float(allrow['match_rate']):.1%} of {int(allrow['events'])} events")
        print(rep.to_string())
        # A state that only covers the tail turns conditioning into a date
        # filter. Say so loudly rather than letting it look like a result.
        early = rep.loc[[y for y in rep.index if isinstance(y, (int, np.integer))
                         and y <= 2021], "match_rate"]
        if len(early):
            print(f"    pre-2022 match rate: {float(early.mean()):.1%} "
                  f"-- if this is 0 the state IS a date filter")

    # -- 3. the vintage cutoff ----------------------------------------------
    print("\n--- 3. every state read was stamped strictly before the entry ---")
    for st in ("data", "detach"):
        sig = SIG.normalise({"mode": "flip", "state": st, "lead_w": 5})
        try:
            state, _ = SIG.build_state(sig)
            out = SIG.gate_cutoff_is_before_entry(raw, state, sig, n=400)
            SIG.gate_join_is_not_vacuous(out, name=st)
            check(f"G-S2 {st!r}", True,
                  f"{len(out)} events checked, min state age "
                  f"{int(out['lag_days'].min())}d, max {int(out['lag_days'].max())}d")
        except AssertionError as e:
            check(f"G-S2 {st!r}", False, str(e)[:90])

    # -- 4. flip does not move the book -------------------------------------
    print("\n--- 4. the macro flip is book-preserving ---")
    base = HC.run_config(cfg(name="base", filters={"voters": "all"}),
                         raw, mdp).closed.set_index("tag")
    flipped = HC.run_config(
        cfg(name="flipped", filters={"voters": "all"},
            signal={"mode": "flip", "state": "data", "lead_w": 5,
                    "threshold": 0.5, "when": "agree"}),
        raw, mdp).closed.set_index("tag")
    check("same tags in the same order", list(base.index) == list(flipped.index),
          f"{len(base)} vs {len(flipped)}")
    check("same entries and exits",
          bool((base.opened_at.to_numpy() == flipped.opened_at.to_numpy()).all() and
               (base.closed_at.to_numpy() == flipped.closed_at.to_numpy()).all()), "")
    check("d_rate_bp unchanged",
          bool(np.array_equal(base.d_rate_bp.to_numpy(), flipped.d_rate_bp.to_numpy())),
          "the market move is a fact, only the side is a choice")
    n_flip = int((flipped["signal_flip"] < 0).sum())
    check("the rule actually fires", 0 < n_flip < len(flipped),
          f"{n_flip} of {len(flipped)} flipped")

    # -- 5. the same book, negated without the knob -------------------------
    print("\n--- 5. post-hoc negation reproduces it (the knob is not in route B) ---")
    sig = SIG.normalise({"mode": "flip", "state": "data", "lead_w": 5,
                         "threshold": 0.5, "when": "agree"})
    state, _ = SIG.build_state(sig)
    by_tag = {e["tag"]: e for e in raw}
    manual = base.pnl_bp.copy()
    want = []
    for tag in base.index:
        ev = by_tag[tag]
        a = SIG.attach(ev, state, sig)
        ag = SIG.agrees(a, int(ev["bucket"]))
        want.append(bool(ag is True))
    want = np.asarray(want)
    manual[want] = -manual[want]
    check("pnl agrees exactly",
          bool(np.allclose(flipped.pnl_bp.to_numpy(), manual.to_numpy(), atol=1e-12)),
          f"max diff {np.abs(flipped.pnl_bp.to_numpy() - manual.to_numpy()).max():.2e}")
    check("exactly the agreeing events were flipped",
          bool(((flipped['signal_flip'] < 0).to_numpy() == want).all()),
          f"{n_flip} flipped, {int(want.sum())} agree")

    # NOTE the entry offset matters here: route B uses ev['entry_ts'] as it
    # stands in the RAW book, which retime() then moves. If these two ever
    # disagree it is because the cutoff moved with it -- which is the correct
    # behaviour and this check would catch a version that did not.

    # -- 6. agree and disagree are complementary -----------------------------
    print("\n--- 6. agree and disagree partition the in-band events ---")
    dis = HC.run_config(
        cfg(name="dis", filters={"voters": "all"},
            signal={"mode": "flip", "state": "data", "lead_w": 5,
                    "threshold": 0.5, "when": "disagree"}),
        raw, mdp).closed.set_index("tag")
    a_flip = (flipped["signal_flip"] < 0).to_numpy()
    d_flip = (dis["signal_flip"] < 0).to_numpy()
    in_band = (flipped["state_sign"] != 0).to_numpy()
    check("no event is flipped by both readings", not bool((a_flip & d_flip).any()),
          f"{int((a_flip & d_flip).sum())} overlap")
    check("together they cover exactly the in-band events",
          bool(((a_flip | d_flip) == in_band).all()),
          f"{int((a_flip | d_flip).sum())} vs {int(in_band.sum())} in band")
    check("an out-of-band event is never flipped",
          not bool((a_flip & ~in_band).any() or (d_flip & ~in_band).any()), "")

    # -- 7. typos, gates and zeros -------------------------------------------
    print("\n--- 7. a typo is loud, a gate counts its drops, a size never books 0 ---")
    for bad in ({"mode": "FLIP"}, {"mode": "fade"}, {"state": "macro"},
                {"when": "agrees"}, {"threshold": -1.0}):
        try:
            HC.run_config(cfg(signal=bad), raw, mdp)
            check(f"signal={bad} raises", False, "it ran")
        except ValueError as e:
            check(f"signal={bad} raises", True, str(e)[:48])

    gated = HC.run_config(
        cfg(name="gated", filters={"voters": "all"},
            signal={"mode": "gate", "state": "data", "lead_w": 5,
                    "threshold": 0.5, "when": "agree"}),
        raw, mdp)
    drops = gated.funnel["filter_drops"]
    check("the gate counts its drops",
          ("macro_state_says_stand_aside" in drops or "no_macro_state" in drops),
          f"{ {k: v for k, v in drops.items() if 'macro' in k} }")
    check("the gated book is smaller than the baseline",
          0 < len(gated.closed) < len(base),
          f"{len(gated.closed)} vs {len(base)}")
    check("a gated book is NOT a subset of the baseline's trades -- say so",
          True, "it runs before the one-position rule; compare only vs a "
                "same-filter baseline")

    sized = HC.run_config(
        cfg(name="sized", filters={"voters": "all"},
            signal={"mode": "size", "state": "data", "lead_w": 5,
                    "threshold": 0.0, "when": "agree", "size_cap": 3.0}),
        raw, mdp).closed
    check("size never books a zero", bool((sized["signal_size"] > 0).all()),
          f"min {float(sized['signal_size'].min()):.3f}")
    check("size is capped", bool((sized["signal_size"] <= 3.0 + 1e-12).all()),
          f"max {float(sized['signal_size'].max()):.3f}")
    check("size leaves the book identical", list(sized["tag"]) == list(base.index),
          f"{len(sized)} vs {len(base)}")

    print("\n" + "=" * 72)
    print(f"{len(FAILS)} FAILURES" if FAILS else "ALL CHECKS PASSED")
    for f in FAILS:
        print(f"  FAILED: {f}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()

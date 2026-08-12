"""Check the `flip` knob against something other than itself.

A direction switch is the easiest thing in a backtest to get silently wrong: a
rule that never fires produces a perfectly plausible book, and a rule that fires
on the wrong rows produces one too. So four independent routes to the same
numbers, and one of them does not use the knob at all.

    1. flip="none" reproduces the module as it was BEFORE the knob existed,
       trade for trade — the pre-change file is loaded from ARBS-gcb and run
       side by side, not trusted to be equivalent.
    2. flip="all" is exactly -1x flip="none" on the same book.
    3. the combined book priced with the knob equals the combined book priced
       WITHOUT it and negated afterwards on the is_voter==False rows. The knob
       is not in that second route at all.
    4. the flip is direction-blind upstream: the gate and the one-position rule
       see the same events either way, so the tag list must be identical.

Plus: an unknown rule raises rather than falling through to "none", and cost is
charged on a faded trade the same as on any other.
"""

from __future__ import annotations

import importlib.util
import io
import pickle
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = Path(__file__).parent
GCB = Path(r"C:\Users\chris\clee\ARBS-gcb")
sys.path.insert(0, str(GCB))          # the ARBS package, as the notebook loads it
sys.path.insert(0, str(HERE))         # ...but the study modules from HERE

import numpy as np
import pandas as pd

from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP

import global_hawk_dove_common as G
import hawk_dove_config as HC

CACHE = HERE / "_global_cache"
FAILS = []

# The notebook's active config, verbatim.
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
    """The hawk_dove_config.py that the notebook has been running, unmodified."""
    p = GCB / "notebooks" / "backtests" / "intraday_fed_hawk_dove" / "hawk_dove_config.py"
    spec = importlib.util.spec_from_file_location("hawk_dove_config_pre", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod          # @dataclass reads it back out of sys.modules
    spec.loader.exec_module(mod)
    if hasattr(mod, "flip_sign"):
        raise RuntimeError(f"{p} already has the knob — it is not a pre-change control")
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

    # -- 1. the knob at rest changes nothing -------------------------------
    print("--- 1. flip=\"none\" vs the module before the knob existed ---")
    for name, c in [("voters-only (the notebook's config)", cfg()),
                    ("whole book", cfg(filters={"voters": "all"})),
                    ("non-voters only", cfg(filters={"voters": "nonvoters"}))]:
        a = OLD.run_config(c, raw, mdp).closed
        b = HC.run_config({**c, "flip": "none"}, raw, mdp).closed
        cols = [x for x in a.columns if x in b.columns]
        same = (len(a) == len(b) and
                a[cols].reset_index(drop=True).equals(b[cols].reset_index(drop=True)))
        check(f"{name}: identical", same, f"{len(a)} vs {len(b)} trades")
        check(f"{name}: no row was flipped", bool((b['flip'] == 1.0).all()),
              f"{int((b['flip'] < 0).sum())} flipped")

    # -- 2. flip="all" is a clean sign change ------------------------------
    print("\n--- 2. flip=\"all\" is exactly -1x ---")
    n0 = HC.run_config(cfg(name="straight"), raw, mdp).closed.set_index("tag")
    nA = HC.run_config(cfg(name="all-faded", flip="all"), raw, mdp).closed.set_index("tag")
    check("same tags in the same order", list(n0.index) == list(nA.index),
          f"{len(n0)} vs {len(nA)}")
    check("pnl is exactly negated",
          bool(np.array_equal(n0.pnl_bp.to_numpy(), -nA.pnl_bp.to_numpy())),
          f"max |sum| {np.abs(n0.pnl_bp.to_numpy() + nA.pnl_bp.to_numpy()).max():.2e}")
    check("every row marked flipped", bool((nA['flip'] == -1.0).all()), "")

    # -- 3. the combined book, priced twice, once without the knob ---------
    print("\n--- 3. combined book: knob vs post-hoc negation (the knob is not in route B) ---")
    knob = HC.run_config(cfg(name="combined", filters={"voters": "all"},
                             flip="nonvoters"), raw, mdp).closed.set_index("tag")
    plain = HC.run_config(cfg(name="combined-straight", filters={"voters": "all"}),
                          raw, mdp).closed.set_index("tag")
    check("same book both ways", list(knob.index) == list(plain.index),
          f"{len(knob)} vs {len(plain)}")
    manual = plain.pnl_bp.copy()
    nv = plain.is_voter == False                                   # noqa: E712
    manual[nv] = -manual[nv]
    check("pnl agrees exactly",
          bool(np.array_equal(knob.pnl_bp.to_numpy(), manual.to_numpy())),
          f"max diff {np.abs(knob.pnl_bp.to_numpy() - manual.to_numpy()).max():.2e}")
    check("exactly the non-voters were flipped",
          bool(((knob['flip'] == -1.0) == nv).all()),
          f"{int((knob['flip'] < 0).sum())} flipped, {int(nv.sum())} non-voters")
    check("no voter was touched",
          bool(np.array_equal(knob.pnl_bp[~nv].to_numpy(), plain.pnl_bp[~nv].to_numpy())),
          "")
    print(f"    combined book: {len(knob)} trades, "
          f"{int((~nv).sum())} voter / {int(nv.sum())} non-voter")

    # -- 4. the flip does not move the book --------------------------------
    print("\n--- 4. the gate and the overlap rule are direction-blind ---")
    check("faded book trades the same events as the straight one",
          (list(knob.index) == list(plain.index) and
           bool((knob.opened_at.to_numpy() == plain.opened_at.to_numpy()).all()) and
           bool((knob.closed_at.to_numpy() == plain.closed_at.to_numpy()).all())), "")
    check("d_rate_bp is unchanged by the flip",
          bool(np.array_equal(knob.d_rate_bp.to_numpy(), plain.d_rate_bp.to_numpy())),
          "the market move is a fact, only the side is a choice")

    # -- 5. cost is charged on a faded trade too ---------------------------
    print("\n--- 5. cost and the flip compose ---")
    c25 = HC.run_config(cfg(name="cost", filters={"voters": "all"},
                            flip="nonvoters", cost_bp=0.25), raw, mdp).closed.set_index("tag")
    check("cost is a straight subtraction, whatever the side",
          bool(np.allclose(c25.pnl_bp.to_numpy(),
                           knob.pnl_bp.to_numpy() - 0.25, atol=1e-12)),
          f"max diff {np.abs(c25.pnl_bp.to_numpy() - (knob.pnl_bp.to_numpy() - 0.25)).max():.2e}")
    check("gross pnl still ignores cost",
          bool(np.array_equal(c25.pnl_bp_gross.to_numpy(), knob.pnl_bp_gross.to_numpy())), "")

    # -- 6. a typo must raise ----------------------------------------------
    print("\n--- 6. an unknown rule is loud ---")
    for bad in ("non-voters", "nonvoter", "NONVOTERS", "fade"):
        try:
            HC.run_config(cfg(flip=bad), raw, mdp)
            check(f"flip={bad!r} raises", False, "it ran")
        except ValueError as e:
            check(f"flip={bad!r} raises", True, str(e)[:52])

    # -- 7. the identity the report will lean on ---------------------------
    print("\n--- 7. non-voters-only, faded, is -1x non-voters-only ---")
    nv_s = HC.run_config(cfg(name="nv", filters={"voters": "nonvoters"}),
                         raw, mdp).closed.set_index("tag")
    nv_f = HC.run_config(cfg(name="nv-faded", filters={"voters": "nonvoters"},
                             flip="nonvoters"), raw, mdp).closed.set_index("tag")
    check("same trades", list(nv_s.index) == list(nv_f.index), f"{len(nv_s)}")
    check("exactly negated",
          bool(np.array_equal(nv_s.pnl_bp.to_numpy(), -nv_f.pnl_bp.to_numpy())),
          f"{nv_s.pnl_bp.sum():+.2f}bp -> {nv_f.pnl_bp.sum():+.2f}bp")

    print("\n" + "=" * 72)
    print(f"{len(FAILS)} FAILURES" if FAILS else "ALL CHECKS PASSED")
    for f in FAILS:
        print(f"  FAILED: {f}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()

"""Hand-reconcile ONE trade against the engine, then break it on purpose.

Two tie-outs already exist and neither covers this. ``build_jpm_repo_panel.py`` proved the
specialness INPUT against JPM's published column (corr 0.9997). ``tie_out_carry.py`` proved
the per-bond carry FORMULA against JPM's published ``3m Carry`` (corr 0.962). Neither
touches the step in between: the DV01 bridge and sign conventions that turn two per-leg
quantities into one spread P&L. There is no published control for that, so the control has
to be arithmetic done independently of the code being checked.

And a check that has never failed is not evidence. Per the repo's own rule -- "run it first
against an input whose answer you already know... for a test suite, mutate the code it
covers and confirm the test actually fails" -- this script finishes by flipping the
direction sign and asserting the reconciliation BREAKS. A reconciliation that passes both
ways is checking nothing.
"""

from __future__ import annotations

import os
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from RVUtils.USTSwitch.costs import CostModel, is_stressed  # noqa: E402
from RVUtils.USTSwitch.data import load_prepared, select_financing  # noqa: E402
from RVUtils.USTSwitch.engine import SwitchConfig, run_switch  # noqa: E402

pd.set_option("display.width", 250)

TOL_BP = 1e-6


def hand_compute(panel: pd.DataFrame, tr: pd.Series, cfg: SwitchConfig, cm: CostModel) -> dict:
    """Recompute one trade from the raw panel, without touching engine code."""
    p = panel[panel["tenor"] == cfg.tenor]
    L = p[p["cusip"] == (tr["cusip_old"] if cfg.direction > 0 else tr["cusip_young"])]
    S = p[p["cusip"] == (tr["cusip_young"] if cfg.direction > 0 else tr["cusip_old"])]
    L = L[(L["date"] >= tr["entry"]) & (L["date"] <= tr["exit"])].set_index("date").sort_index()
    S = S[(S["date"] >= tr["entry"]) & (S["date"] <= tr["exit"])].set_index("date").sort_index()
    idx = L.index.intersection(S.index)
    L, S = L.loc[idx], S.loc[idx]

    # --- price leg -----------------------------------------------------------------
    # spread as the ENGINE defines it: old yield minus young yield, in bp.
    old = L if cfg.direction > 0 else S
    young = S if cfg.direction > 0 else L
    s = (old["YTM"] - young["YTM"]) * 100.0
    price_bp = float(-cfg.direction * (s.iloc[-1] - s.iloc[0]))

    # --- carry ---------------------------------------------------------------------
    # (y - r)/D per year on each leg, long minus short, accrued ACT/360.
    def leg_rate(x):
        return (x["YTM"] * 100.0 - x["gc_pct"] * 100.0 + x["special_used_bp"]) / x["MOD_DURATION"]

    yf = pd.Series(idx, index=idx).diff().dt.days.astype(float) / 360.0
    carry_bp = float(((leg_rate(L) - leg_rate(S)) * yf).fillna(0.0).sum())

    special_bp = float(
        (((L["special_used_bp"] / L["MOD_DURATION"]) - (S["special_used_bp"] / S["MOD_DURATION"])) * yf)
        .fillna(0.0).sum()
    )

    # --- cost ----------------------------------------------------------------------
    md_old = float(old["MOD_DURATION"].iloc[0])
    md_young = float(young["MOD_DURATION"].iloc[0])
    # Same stress flag the engine applies, or a trade that happens to straddle March 2020
    # reconciles against the wrong cost table and the mismatch looks like an arithmetic bug.
    stressed = is_stressed(tr["entry"]) or is_stressed(tr["exit"])
    cost_bp = (
        cm.full_price_bp(cfg.tenor, cfg.rank_old, stressed=stressed) / md_old
        + cm.full_price_bp(cfg.tenor, cfg.rank_young, stressed=stressed) / md_young
    ) * cm.uncertainty_mult.get(cfg.tenor, 1.0) * cm.multiplier

    return {
        "price_bp": price_bp,
        "carry_bp": carry_bp,
        "special_bp": special_bp,
        "cost_bp": cost_bp,
        "net_bp": price_bp + carry_bp - cost_bp,
        "n_obs": len(idx),
        "spread_entry_bp": float(s.iloc[0]),
        "spread_exit_bp": float(s.iloc[-1]),
    }


def compare(tag: str, eng: pd.Series, hand: dict, *, expect_match: bool) -> bool:
    keys = ["price_bp", "carry_bp", "special_bp", "cost_bp", "net_bp"]
    print(f"\n--- {tag} ---")
    print(f"{'field':<16}{'engine':>14}{'by hand':>14}{'diff':>14}")
    ok = True
    for k in keys:
        e, h = float(eng[k]), float(hand[k])
        d = e - h
        if abs(d) > TOL_BP:
            ok = False
        print(f"{k:<16}{e:>14.8f}{h:>14.8f}{d:>14.2e}")
    verdict = "MATCH" if ok else "MISMATCH"
    good = ok == expect_match
    print(f"  => {verdict}  (expected {'MATCH' if expect_match else 'MISMATCH'})  "
          f"{'OK' if good else '*** TEST ITSELF IS BROKEN ***'}")
    return good


def main() -> int:
    panel_raw, amap = load_prepared()
    cfg = SwitchConfig(
        tenor=10, rank_young=0, rank_old=1, direction=1,
        entry_offset=1, exit_rule="next_roll", exit_offset=1,
        financing_mode="actual",
    )
    panel = select_financing(panel_raw, cfg.financing_mode)
    cm = CostModel(multiplier=cfg.cost_multiplier)

    res = run_switch(panel, amap, cfg, cost_model=cm)
    if res.trades.empty:
        print("no trades produced -- cannot reconcile")
        return 1

    # A middling trade, not the best or worst: an outlier can reconcile by luck.
    tr = res.trades.sort_values("net_bp").iloc[len(res.trades) // 2]
    print("=== reconciling one trade ===")
    print(f"config : {cfg.name}")
    print(f"cycle  : roll {tr['roll'].date()}  entry {tr['entry'].date()}  exit {tr['exit'].date()}")
    print(f"legs   : LONG(old) {tr['cusip_old']}   SHORT(current) {tr['cusip_young']}")
    print(f"obs    : {tr['held_obs']} marks over {tr['held_days']} calendar days")

    hand = hand_compute(panel, tr, cfg, cm)
    ok1 = compare("engine vs hand, as configured", tr, hand, expect_match=True)

    # ---- the mutation: flip direction and re-hand-compute WITHOUT flipping the engine.
    # If the reconciliation still 'matches', it is not sensitive to the sign and proves
    # nothing about it.
    bad_cfg = SwitchConfig(**{**cfg.__dict__, "direction": -1})
    hand_flipped = hand_compute(panel, tr, bad_cfg, cm)
    ok2 = compare("engine vs hand with direction FLIPPED (must MISMATCH)",
                  tr, hand_flipped, expect_match=False)

    # ---- second mutation: drop the specialness from the hand carry.
    hand_nospec = dict(hand)
    hand_nospec["carry_bp"] = hand["carry_bp"] - hand["special_bp"]
    hand_nospec["net_bp"] = hand_nospec["price_bp"] + hand_nospec["carry_bp"] - hand_nospec["cost_bp"]
    ok3 = compare("engine vs hand with SPECIALNESS REMOVED (must MISMATCH)",
                  tr, hand_nospec, expect_match=False)

    print("\n" + "=" * 74)
    if ok1 and ok2 and ok3:
        print("RECONCILED. The engine agrees with independent arithmetic, and the check is")
        print("sensitive to both the direction sign and the specialness term.")
        print(f"\nspecialness cost this trade {-hand['special_bp']:+.4f} bp of the "
              f"{hand['net_bp']:+.4f} bp net.")
        return 0
    print("FAILED -- see above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

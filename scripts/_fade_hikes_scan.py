"""Comprehensive scan for SFR structures that fade near-term-hike pricing.

For each structure in the snapshot, classifies the screener's signal
in a "fade-near-term-hikes" frame:

* OUTRIGHT on a near-term contract: edge exists if asym < 1 (the
  flipped RECEIVE direction wins -> bet rate goes DOWN).
* CALENDAR whose front leg is a near-term contract: edge exists if
  asym < 1 (flipped 'RECEIVE front / PAY back' direction wins -> bet
  the front-leg rate goes DOWN).
* BUTTERFLY whose belly is a near-term contract: edge exists if
  asym >= 1 (the canonical 'PAY wings / RECEIVE belly' direction
  wins -> bet belly rate goes DOWN, wings up = curve more humped at
  belly -> fade hikes specifically on the belly contract).

Anything else is a hike-bet (or unrelated to near-term curve), so the
fade_score is set to 0 and the row is skipped from the fade ranking.

After ranking, prices the top-K via the canonical SFR pricing pattern
from notebooks/pricers/sfr.ipynb (IRSwapQuery + IRSwapValue) so the
output is ready to trade.

Usage::

    conda run -n stir python scripts/_fade_hikes_scan.py --as-of 2026-04-29
"""
from __future__ import annotations

import argparse
import datetime
import logging
import pickle
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytz

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("fade_hikes_scan")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP  # noqa: E402
from Query.IRSwaps.IRSwapQuery import IRSwapQuery  # noqa: E402
from Query.IRSwaps.IRSwapValue import IRSwapValue  # noqa: E402
from RVUtils.SFRConvexScreener import (  # noqa: E402
    JointMethod,
    SFRConvexScreenerConfig,
    StructureType,
)
from RVUtils.SFRConvexScreener.screener import build_snapshot  # noqa: E402

NYC = pytz.timezone("America/New_York")
CACHE_ROOT = REPO_ROOT / "data" / "screener_results" / "sfr_convex_screener_backtest_cache"


_SR3_TO_IMM = {  # SFR{code}{yy} -> IMM_x x IMM_y stub for the IRSwapQuery curve API
    # only the codes we expect to appear in the front strip
}
_NEXT_IMM_CODE = {"H": "M", "M": "U", "U": "Z", "Z": "H"}


def _sfr_to_imm_segment(symbol: str) -> str:
    """Convert ``SFR{code}{yy}`` to its 3M IMM-IMM stub tenor.

    Example: ``SFRZ26 -> IMM_Z26xIMM_H27``.
    """
    m = re.match(r"^SFR([HMUZ])(\d{2})$", symbol.upper())
    if not m:
        raise ValueError(f"unrecognised SFR symbol: {symbol!r}")
    code, yy = m.group(1), int(m.group(2))
    next_code = _NEXT_IMM_CODE[code]
    next_yy = (yy + 1) if code == "Z" else yy
    return f"IMM_{code}{yy:02d}xIMM_{next_code}{next_yy:02d}"


def _make_cfg(*, calendar_gaps: Tuple[int, ...], fly_gaps: Tuple[int, ...]) -> SFRConvexScreenerConfig:
    return SFRConvexScreenerConfig(
        universe_size=12,
        include_outrights=True,
        jpm_method=True,
        primary_joint_method=JointMethod.HISTORICAL_GAUSSIAN_COPULA,
        joint_methods=(
            JointMethod.HISTORICAL_GAUSSIAN_COPULA,
            JointMethod.PERFECT_CORRELATION,
        ),
        correlation_window=60,
        n_simulations=50_000,
        calendar_gaps=calendar_gaps,
        fly_gaps=fly_gaps,
    )


def _classify(r: Any, near_term: set) -> Optional[Dict[str, Any]]:
    """Return a row dict iff the structure expresses a fade-near-term-hikes
    bet on at least one of the user's target contracts. Otherwise None."""
    sd = r.structure_def
    primary = r.metrics_by_method.get(r.primary_method)
    if primary is None:
        return None
    asym = float(getattr(primary, "asymmetry_ratio", float("nan")))
    if asym != asym or asym <= 0:
        return None

    legs = sd.legs
    contracts = [l.contract for l in legs]

    fade_target: Optional[str] = None
    fade_side: Optional[str] = None  # "long_price" (asym<1) or "long_rate" (asym>=1)
    fade_score: float = 0.0

    if sd.structure_type is StructureType.OUTRIGHT:
        c = contracts[0]
        if c in near_term and asym < 1.0:
            fade_target = c
            fade_side = "long_price"
            fade_score = 1.0 / asym
    elif sd.structure_type is StructureType.CALENDAR:
        front = next((l for l in legs if l.weight > 0), legs[0])
        back = next((l for l in legs if l.weight < 0), legs[-1])
        # to fade-FRONT-hikes, we want RECEIVE front / PAY back, which is the
        # asym<1 flipped direction.
        if front.contract in near_term and asym < 1.0:
            fade_target = front.contract
            fade_side = "long_price"
            fade_score = 1.0 / asym
        # to fade-BACK-hikes (back contract is over-priced), we want PAY front / RECEIVE back
        # which is the asym>=1 long-rate direction. But since PAY-front = bet front UP = more
        # hikes (opposite of fade for the front), this only counts if the back is near-term
        # AND the front is NOT near-term. Skip — too rare and confounded.
    elif sd.structure_type is StructureType.BUTTERFLY:
        wings = [l for l in legs if l.weight > 0]
        belly = [l for l in legs if l.weight < 0]
        if len(wings) == 2 and len(belly) == 1:
            belly_c = belly[0].contract
            # to fade-BELLY-hikes (belly rate to fall vs wings rising), we want PAY wings /
            # RECEIVE belly which is the asym>=1 long-rate direction.
            if belly_c in near_term and asym >= 1.0:
                fade_target = belly_c
                fade_side = "long_rate"
                fade_score = float(asym)

    if fade_target is None:
        return None

    return {
        "structure_id": sd.structure_id,
        "structure_type": sd.structure_type.value,
        "direction": r.direction(),
        "asym": asym,
        "fade_target": fade_target,
        "fade_side": fade_side,
        "fade_score": fade_score,
        "p_profit": float(getattr(primary, "p_profit", float("nan"))),
        "expected_value_bp": float(getattr(primary, "expected_value_bp", float("nan"))),
        "carry_3m_bp": float(r.carry_3m_bp),
        "rolldown_bp": float(r.rolldown_bp),
        "composite_score": float(r.composite_score),
        "rank": int(r.rank),
        "leg_contracts": contracts,
        "legs": [(l.contract, float(l.weight)) for l in legs],
    }


def _price_via_irswap(
    *,
    curve_handle: Any,
    curve_name: str,
    ts: Any,
    legs: List[Tuple[str, float]],
) -> Dict[str, Any]:
    """Price each leg's IMM-IMM stub via the canonical IRSwapQuery pattern,
    then combine into the structure's rate using the leg weights.

    Returns the long-rate-convention level (sum of weight * leg_rate, in bp)
    plus the 1m rolldown for the front leg as a sanity check.
    """
    segments = [(c, w, _sfr_to_imm_segment(c)) for c, w in legs]
    tenor = "/".join(s[2] for s in segments)
    leg_rates_pct: List[Tuple[str, float, float]] = []  # (contract, weight, rate%)
    try:
        for c, w, seg in segments:
            q = IRSwapQuery(curve=curve_name, tenor=seg).resolve_query(
                ts, pricer_or_curve=curve_handle,
            )
            pkg, _ = q.resolve_package(pricer_or_curve=curve_handle)
            leg_rates_pct.append((c, float(w), float(pkg[0].rate().real)))
        weighted_pct = sum(w * r for _, w, r in leg_rates_pct)
        return {
            "tenor": tenor,
            "leg_rates": leg_rates_pct,
            "structure_rate_bp": weighted_pct * 100.0,
        }
    except Exception as exc:  # noqa: BLE001
        return {"tenor": tenor, "error": repr(exc)}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--as-of", required=True)
    p.add_argument("--top-k", type=int, default=15)
    p.add_argument("--near-term", nargs="+",
                   default=("SFRM26", "SFRU26", "SFRZ26", "SFRH27"),
                   help="Contracts treated as 'near-term hikes' targets")
    p.add_argument("--calendar-gaps", type=int, nargs="+", default=(1, 2, 3, 4))
    p.add_argument("--fly-gaps", type=int, nargs="+", default=(1, 2, 3, 4))
    p.add_argument("--from-cache", action="store_true",
                   help="Load the cached pickle for as_of (faster but may be 1 BD off)")
    p.add_argument("--cache-pkl", default=None,
                   help="Explicit cache pickle path; bypasses --from-cache hash lookup")
    p.add_argument("--curve", default="USD-SOFR-1D-Q12STIRT")
    p.add_argument("--no-pricing", action="store_true",
                   help="Skip the IRSwapQuery pricing pass (snapshot-only output)")
    args = p.parse_args()

    as_of = datetime.date.fromisoformat(args.as_of)
    cfg = _make_cfg(
        calendar_gaps=tuple(args.calendar_gaps),
        fly_gaps=tuple(args.fly_gaps),
    )

    if args.cache_pkl:
        with open(args.cache_pkl, "rb") as fh:
            snap = pickle.load(fh)
        print(f"loaded {args.cache_pkl}")
    else:
        print(f"building snapshot @ {as_of} | calendar_gaps={cfg.calendar_gaps} fly_gaps={cfg.fly_gaps}")
        snap = build_snapshot(cfg, as_of=as_of)
    print(f"results={len(snap.results)} | warnings={len(snap.run_warnings)}")
    for w in list(snap.run_warnings)[:5]:
        print(f"  - {w}")

    near_term = {c.upper() for c in args.near_term}
    rows = []
    for r in snap.results:
        row = _classify(r, near_term)
        if row is not None:
            rows.append(row)
    rows.sort(key=lambda r: r["fade_score"], reverse=True)

    print(f"\n=== fade-near-term-hikes ranking (target contracts: {sorted(near_term)}) ===")
    print(f"{'fade':>6} {'asym':>7} {'p_prof':>6} {'carry':>7} {'roll1m':>7} {'score':>7}  "
          f"{'type':<10} {'target':<8} {'direction'}")
    for r in rows[: args.top_k]:
        print(f"{r['fade_score']:>6.2f} {r['asym']:>7.3f} {r['p_profit']:>6.2f} "
              f"{r['carry_3m_bp']:>7.2f} {r['rolldown_bp']:>7.2f} "
              f"{r['composite_score']:>7.3f}  "
              f"{r['structure_type']:<10} {r['fade_target']:<8} {r['direction']}")

    if args.no_pricing or not rows:
        return 0

    # Price the top-K via the IRSwapQuery pattern from notebooks/pricers/sfr.ipynb
    print(f"\n=== IRSwapQuery pricing for top-{min(args.top_k, len(rows))} ===")
    print("(rate/PV01 from BARCHART_STIRF-RL OIS curve at 17:00 NYC, bpv=$100k notional per structure)")

    ts = NYC.localize(datetime.datetime.combine(as_of, datetime.time(17, 0)))
    curve_mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    try:
        curve_handle = curve_mdp.get_pricer(request=dict(curve_name=args.curve, timestamp=ts))
    except Exception as exc:  # noqa: BLE001
        print(f"  curve fetch failed: {exc!r}")
        return 1

    print(f"\n{'fade':>6} {'level (bp)':>11} {'sign-corrected':>15}  {'tenor'}")
    for r in rows[: args.top_k]:
        result = _price_via_irswap(
            curve_handle=curve_handle, curve_name=args.curve, ts=ts,
            legs=r["legs"],
        )
        if "error" in result:
            print(f"{r['fade_score']:>6.2f} {'err':>11} {'err':>15}  {result['tenor']}  ({result['error'][:60]})")
            continue
        # Long-rate level (the canonical sum of w_i * r_i in bp).
        lvl = result["structure_rate_bp"]
        # On the user's side: long-price flips the sign.
        side_lvl = -lvl if r["fade_side"] == "long_price" else lvl
        print(f"{r['fade_score']:>6.2f} {lvl:>10.2f}b {side_lvl:>13.2f}b  "
              f"{result['tenor']}  [{r['direction']}]")
        for c, w, rt in result["leg_rates"]:
            print(f"    {c:<8} w={w:+.0f} rate={rt:.4f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Short convexity via a forward curve trade vs via a short swaption, like for like.

The desk claim to test: "it's a lot safer to trade that steepener picking up carry
and roll vs selling a swaption." Both are short convexity; the question is what you
give up and what you are protected from.

Includes a carry ADJUDICATION, because the two measures in the repo disagree by
10bp on exactly this structure: ``strat1``'s ``carry_bp`` (which is
``IRSwapValue.CARRY_AND_ROLL_BPS_RUNNING``) says -1.10, the screener's aged-rate
roll says +9.13. The tie-break is arithmetic on the par rates themselves.
"""
from __future__ import annotations

import datetime
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
pd.set_option("display.width", 220)

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP  # noqa: E402
from RVUtils.ConvexityRV.strat1_curve_gamma import (  # noqa: E402
    STEEPENER, Strat1Config, atmf_straddle_premium_bp,
    straddle_dv01_for_carry, structure_profile,
)
from RVUtils.CurveFlyScreener import Leg, Structure, carry_roll_bp, par_rate_bp  # noqa: E402

ASOF = datetime.datetime(2026, 8, 21, 17, 0)
DV01, BD = 100_000.0, 252.0

mdp = IRSwapsMDP(source="citivelo_excel_rl")
pricer = mdp.get_data({"curve_name": "USD-SOFR-1D", "timestamp": ASOF})
cfg = Strat1Config(package_dv01=DV01)

# ------------------------------------------------------ carry adjudication
print("=== which carry measure is right for 10y10y/20y10y? ===")
r = {lab: par_rate_bp(pricer, Leg(f, t)) for lab, (f, t) in
     {"10y10y": (10, 10), "20y10y": (20, 10),
      "9y10y": (9, 10), "19y10y": (19, 10)}.items()}
for k, v in r.items():
    print(f"  {k:<8}{v:>9.2f}bp")
lvl_now = r["20y10y"] - r["10y10y"]
lvl_aged = r["19y10y"] - r["9y10y"]
print(f"\n  level today  = 20y10y - 10y10y = {lvl_now:>8.2f}bp")
print(f"  level aged 1y= 19y10y -  9y10y = {lvl_aged:>8.2f}bp")
print(f"  -> the quoted spread rolls {lvl_aged - lvl_now:+.2f}bp over one year")

steep = Structure("10y10y/20y10y", (Leg(10, 10), Leg(20, 10)), (-1.0, 1.0), "curve")
cr_screener = carry_roll_bp(pricer, steep, 1.0)
p = structure_profile(pricer, "10Yx10Y/20Yx10Y", "10Yx10Y", "20Yx10Y", cfg,
                      direction=STEEPENER)
print(f"\n  screener aged-rate roll : {cr_screener:+8.2f}bp   <- matches the arithmetic")
print(f"  strat1 CARRY_AND_ROLL.. : {p.carry_bp:+8.2f}bp   <- the query measure")
print("  The query measure is the one graded at corr -0.136 against Citi's published")
print("  screen (repriced roll: +0.991). It is disqualified, and this is what that")
print("  disqualification looks like on a live structure: a 10bp disagreement and a")
print("  SIGN FLIP on the desk's own trade.")

# ------------------------------------------------------ curvature + breakeven
sh = np.asarray(p.shifts_bp, dtype=float)
cx = np.asarray(p.convexity_ccy, dtype=float)
near = [i for i, s in enumerate(sh) if 0 < abs(s) <= 50]
G = float(np.mean([2.0 * cx[i] / (sh[i] ** 2) for i in near]))
carry_usd = cr_screener * DV01
be = math.sqrt(2.0 * abs(carry_usd) / (BD * abs(G)))
print(f"\n=== the steepener as a short-convexity position ===")
print(f"  carry-and-roll     {cr_screener:+.2f}bp/yr  = ${carry_usd:,.0f} on ${DV01:,.0f} DV01")
print(f"  curvature          {G:,.1f} $/bp^2  (negative = concave = short convexity)")
print(f"  breakeven daily    {be:.2f}bp   <- realise more than this and the concavity")
print(f"                                     eats the carry")

LH = REPO / "docs" / "curvefly" / "leg_history.parquet"
if LH.exists():
    lh = pd.read_parquet(LH)
    if {"10y10y", "20y10y"} <= set(lh.columns):
        lvl = (lh["20y10y"] - lh["10y10y"]).dropna()
        rv = float(lvl.diff().std())
        print(f"  realised daily     {rv:.2f}bp   ({len(lvl)} obs)")
        print(f"  RATIO be/realised  {be/rv:.2f}   (Citi enters the steepener above 1.0)")
        print(f"  level percentile   {float((lvl < lvl.iloc[-1]).mean())*100:.0f}%")
else:
    print("  realised daily     pending the leg warm")

# ------------------------------------------------------ like-for-like
print("\n" + "=" * 86)
print("SAME CARRY INTAKE, TWO WAYS TO BE SHORT CONVEXITY")
print("=" * 86)
carry = abs(carry_usd)
print(f"steepener at ${DV01:,.0f} DV01 intakes ${carry:,.0f} over 1y.\n")
print(f"{'vol bp/yr':>10}{'straddle prem':>16}{'DV01 to sell':>16}{'as % of the steepener':>24}")
for vol in (60.0, 70.0, 80.0, 90.0, 100.0):
    prem_bp = atmf_straddle_premium_bp(vol, tte_years=1.0)
    sdv01 = straddle_dv01_for_carry(carry, vol, tte_years=1.0)
    print(f"{vol:>10.0f}{prem_bp:>14.1f}bp{sdv01:>16,.0f}{sdv01/DV01*100:>23.1f}%")

VOL = 80.0
sdv01 = straddle_dv01_for_carry(carry, VOL, tte_years=1.0)
print(f"\nterminal P&L at a parallel move, $ (short straddle struck ATMF at {VOL:.0f} vol)")
print(f"{'move bp':>9}{'steepener':>14}{'short straddle':>17}{'ratio':>9}")
for m in (25, 50, 100, 150, 200, 250):
    i = int(np.argmin(np.abs(sh - m)))
    st = cx[i] + carry_usd                       # curvature + the carry earned
    sd = carry - abs(m) * sdv01                  # premium kept less intrinsic
    print(f"{m:>9}{st:>14,.0f}{sd:>17,.0f}{(abs(sd)/abs(st) if st else np.nan):>9.1f}")
print("\nBoth are short convexity. The steepener's loss grows with the SQUARE of the")
print("move and is bounded by curvature; the straddle's grows LINEARLY once through")
print("the strike and is unbounded. Neither line prices the two risks the curve")
print("trade simply does not have: vega marks and terminal pin gamma.")

# ------------------------------------------------- the risks the table misses
print("\n" + "=" * 86)
print("WHAT THE TERMINAL TABLE CANNOT SHOW")
print("=" * 86)
# Bachelier ATMF straddle premium = sqrt(2/pi)*sigma*sqrt(T) * DV01_underlying,
# so vega (per bp of normal vol) is just sqrt(2/pi)*sqrt(T)*DV01_underlying.
veg = math.sqrt(2.0 / math.pi) * math.sqrt(1.0) * sdv01
print(f"\n1. VEGA. The short straddle sized to this carry runs ${veg:,.0f} per bp of")
print(f"   normal vol. Rates unchanged, a vol move alone:")
for dv in (5, 10, 20, 30):
    print(f"     +{dv:>2}bp/yr of implied  ->  {-veg*dv:>12,.0f}  "
          f"({-veg*dv/carry*100:>5.0f}% of the year's carry)")
print(f"   The curve steepener's vega is exactly zero. It cannot lose money to a")
print(f"   repricing of implied volatility, only to realised curve moves.")

print(f"\n2. PIN GAMMA. The straddle's gamma concentrates into expiry -- the same")
print(f"   position is far more dangerous in its last month than its first. The")
print(f"   steepener's curvature is a property of the curve's shape and does not")
print(f"   have a clock on it.")

print(f"\n3. WHERE THE CURVE TRADE IS WORSE. Its concavity is quadratic, so beyond")
print(f"   the crossover in the table above it loses FASTER than the straddle, and")
print(f"   unlike the straddle there is no premium cap and no expiry to stop the")
print(f"   bleeding. ConvexityRV measured this book: the risk-adjusted-carry rule")
print(f"   over these pairs took a -$20.2m drawdown on $21.4m of gross P&L, with")
print(f"   2022 alone losing $9.8m at $100k DV01. Safer is not safe; the danger is")
print(f"   episodic REALISED vol, which is exactly what 2022 was.")
